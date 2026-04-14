from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tmrank.db.models import ApiFetch, EntityAlias, Event, EventCompetitor, EventResult, Player, SyncRun, Team, TeamMembership
from tmrank.domain import ParsedEvent, ParsedEventResults, ParsedResultRow
from tmrank.services.aliases import AliasResolver
from tmrank.source.liquipedia import LiquipediaProvider
from tmrank.utils import compact_dict, sha256_json


class SyncService:
    def __init__(
        self,
        session: Session,
        provider: LiquipediaProvider,
        alias_resolver: AliasResolver,
        progress_callback: Callable[[str], None] | None = None,
    ):
        self.session = session
        self.provider = provider
        self.alias_resolver = alias_resolver
        self.progress_callback = progress_callback

    def sync_tournaments(self) -> dict[str, int]:
        with self._sync_run("sync tournaments") as run:
            seen = 0
            written = 0
            current_page_key: tuple[int, int] | None = None
            current_page_rows = 0
            self._emit_progress("Starting tournament sync")
            for parsed_event, params, raw_row, status_code in self.provider.iter_tournaments():
                page_offset = int(params.get("offset", 0))
                page_limit = int(params.get("limit", 0) or 0)
                page_key = (page_offset, page_limit)
                if current_page_key != page_key:
                    if current_page_key is not None:
                        previous_offset, previous_limit = current_page_key
                        previous_page = (previous_offset // previous_limit) + 1 if previous_limit else 1
                        self._emit_progress(
                            f"[page {previous_page}] Finished tournament page: rows={current_page_rows} written_so_far={written}"
                        )
                    current_page_key = page_key
                    current_page_rows = 0
                    page_number = (page_offset // page_limit) + 1 if page_limit else 1
                    self._emit_progress(
                        f"[page {page_number}] Processing tournament page offset={page_offset} limit={page_limit}"
                    )
                seen += 1
                current_page_rows += 1
                fetch = self._create_fetch(
                    endpoint=self.provider.settings.liquipedia_tournament_table,
                    params=params,
                    payload={"result": [raw_row]},
                    status_code=status_code,
                )
                self._upsert_event(parsed_event, fetch.id)
                written += 1
            if current_page_key is not None:
                final_offset, final_limit = current_page_key
                final_page = (final_offset // final_limit) + 1 if final_limit else 1
                self._emit_progress(
                    f"[page {final_page}] Finished tournament page: rows={current_page_rows} written_so_far={written}"
                )
            run.items_seen = seen
            run.items_written = written
            return {"seen": seen, "written": written}

    def sync_event_results(self, source_event_ids: Iterable[str] | None = None) -> dict[str, int]:
        return self.sync_event_results_batch(source_event_ids=source_event_ids, force=False, limit=None)

    def sync_event_results_batch(
        self,
        *,
        source_event_ids: Iterable[str] | None = None,
        force: bool = False,
        limit: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        with self._sync_run("sync event-results") as run:
            events = self._events_for_results(
                source_event_ids,
                force=force,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )
            seen = 0
            written = 0
            candidates = len(events)
            self._emit_progress(
                f"Starting event-results sync for {candidates} candidate event(s)"
            )
            for index, event in enumerate(events, start=1):
                self._emit_progress(
                    f"[{index}/{candidates}] Syncing event results for {event.source_event_id} ({event.name})"
                )
                parsed_results, params, payload, status_code = self.provider.fetch_event_results(
                    event.source_event_id,
                    event.page_id,
                    event.page_name,
                )
                fetch = self._create_fetch(
                    endpoint=self.provider.settings.liquipedia_results_table,
                    params=params,
                    payload=payload,
                    status_code=status_code,
                )
                written += self._upsert_event_results(event, parsed_results, fetch.id)
                seen += len(parsed_results.results)
                run.items_seen = seen
                run.items_written = written
                self.session.commit()
                self._emit_progress(
                    f"[{index}/{candidates}] Finished {event.source_event_id}: rows={len(parsed_results.results)} written_so_far={written}"
                )
            run.items_seen = seen
            run.items_written = written
            return {"candidates": candidates, "seen": seen, "written": written}

    def sync_all(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, dict[str, int]]:
        tournaments = self.sync_tournaments()
        results = self.sync_event_results_batch(
            force=force,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        return {"tournaments": tournaments, "event_results": results}

    def get_results_sync_status(
        self,
        *,
        force: bool = False,
        limit: int = 10,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        base_statement = self._events_query(None, force=True, start_date=start_date, end_date=end_date)
        total = self.session.scalar(select(func.count()).select_from(base_statement.subquery())) or 0

        synced_statement = self._events_query(None, force=True, start_date=start_date, end_date=end_date).where(
            Event.results_synced_at.is_not(None)
        )
        synced = self.session.scalar(select(func.count()).select_from(synced_statement.subquery())) or 0
        unsynced = max(total - synced, 0)

        next_candidates = self._events_for_results(
            None,
            force=force,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "filters": {
                "start_date": start_date,
                "end_date": end_date,
                "force": force,
            },
            "totals": {
                "matching_events": total,
                "synced_events": synced,
                "unsynced_events": unsynced,
            },
            "next_candidates": [
                {
                    "source_event_id": event.source_event_id,
                    "name": event.name,
                    "start_date": event.start_date,
                    "end_date": event.end_date,
                    "results_synced_at": event.results_synced_at,
                }
                for event in next_candidates
            ],
        }

    @contextmanager
    def _sync_run(self, command: str):
        run = SyncRun(command=command, status="running")
        self.session.add(run)
        self.session.flush()
        try:
            yield run
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            with self.session.begin():
                failed_run = self.session.get(SyncRun, run.id)
                if failed_run is not None:
                    failed_run.status = "failed"
                    failed_run.finished_at = datetime.now(timezone.utc)
                    failed_run.error_summary = str(exc)
            raise

    def _create_fetch(self, *, endpoint: str, params: dict[str, Any], payload: dict[str, Any], status_code: int) -> ApiFetch:
        fetch = ApiFetch(
            source=self.provider.source_name,
            endpoint=endpoint,
            request_params=params,
            response_payload=payload,
            payload_hash=sha256_json(payload),
            http_status=status_code,
        )
        self.session.add(fetch)
        self.session.flush()
        return fetch

    def _upsert_event(self, parsed: ParsedEvent, fetch_id: int) -> Event:
        existing = self.session.scalar(
            select(Event).where(
                Event.source == parsed.source,
                Event.source_event_id == parsed.source_event_id,
            )
        )
        target = existing or Event(source=parsed.source, source_event_id=parsed.source_event_id)
        target.page_id = parsed.page_id
        target.page_name = parsed.page_name
        target.name = parsed.name
        target.series = parsed.series
        target.tier = parsed.tier
        target.mode = parsed.mode
        target.event_type = parsed.event_type
        target.start_date = parsed.start_date
        target.end_date = parsed.end_date
        target.sort_date = parsed.sort_date
        target.prize_pool = _as_decimal(parsed.prize_pool)
        target.participants_number = parsed.participants_number
        target.source_payload_ref = fetch_id
        self.session.add(target)
        self.session.flush()
        return target

    def _events_for_results(
        self,
        source_event_ids: Iterable[str] | None,
        *,
        force: bool,
        limit: int | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[Event]:
        statement = self._events_query(
            source_event_ids,
            force=force,
            start_date=start_date,
            end_date=end_date,
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def _events_query(
        self,
        source_event_ids: Iterable[str] | None,
        *,
        force: bool,
        start_date: date | None,
        end_date: date | None,
    ):
        effective_date = func.coalesce(Event.end_date, Event.start_date)
        statement = select(Event).order_by(Event.end_date.asc().nulls_last(), Event.source_event_id.asc())
        if source_event_ids:
            statement = statement.where(Event.source_event_id.in_(list(source_event_ids)))
        else:
            statement = statement.where(effective_date.is_not(None))
            statement = statement.where(effective_date <= date.today())
            if not force:
                statement = statement.where(Event.results_synced_at.is_(None))
        if start_date is not None:
            statement = statement.where(effective_date >= start_date)
        if end_date is not None:
            statement = statement.where(effective_date <= end_date)
        return statement

    def _upsert_event_results(self, event: Event, parsed_results: ParsedEventResults, fetch_id: int) -> int:
        event.results_fetch_ref = fetch_id
        event.results_synced_at = parsed_results.fetched_at
        self._clear_existing_results(event.id)
        written = 0
        for result in parsed_results.results:
            competitor = self._upsert_competitor(event, result)
            event_result = EventResult(
                event_id=event.id,
                competitor_id=competitor.id,
                placement_low=result.placement_low,
                placement_high=result.placement_high,
                placement_text=result.placement_text,
                prize=_as_decimal(result.prize),
                points=_as_decimal(result.points),
                raw_payload=result.raw_payload,
            )
            self.session.add(event_result)
            written += 1
        self.session.flush()
        return written

    def _clear_existing_results(self, event_id: int) -> None:
        competitors = list(
            self.session.scalars(select(EventCompetitor).where(EventCompetitor.event_id == event_id))
        )
        competitor_ids = [competitor.id for competitor in competitors]
        memberships_by_id: dict[int, TeamMembership] = {}
        if competitor_ids:
            memberships = list(
                self.session.scalars(
                    select(TeamMembership).where(
                        or_(
                            TeamMembership.team_competitor_id.in_(competitor_ids),
                            TeamMembership.player_competitor_id.in_(competitor_ids),
                        )
                    )
                )
            )
            memberships_by_id = {membership.id: membership for membership in memberships}
        for membership in memberships_by_id.values():
            self.session.delete(membership)
        for competitor in competitors:
            if competitor.result is not None:
                self.session.delete(competitor.result)
            self.session.delete(competitor)
        self.session.flush()

    def _upsert_competitor(self, event: Event, result: ParsedResultRow) -> EventCompetitor:
        existing = self.session.scalar(
            select(EventCompetitor).where(
                EventCompetitor.event_id == event.id,
                EventCompetitor.competitor_type == result.competitor.competitor_type,
                EventCompetitor.canonical_slug == result.competitor.canonical_slug,
            )
        )
        if existing:
            return existing
        competitor = EventCompetitor(
            event_id=event.id,
            competitor_type=result.competitor.competitor_type,
            canonical_slug=result.competitor.canonical_slug,
            display_name=result.competitor.display_name,
            source_competitor_id=result.competitor.source_competitor_id,
            country=result.competitor.country,
        )
        if result.competitor.competitor_type == "player":
            player = self._upsert_player(result.competitor.canonical_slug, result.competitor.display_name, result.competitor.country, result.competitor.source_competitor_id)
            competitor.player_id = player.id
            self._upsert_alias("player", result.competitor.source_competitor_id, result.competitor.name, result.competitor.canonical_slug, result.competitor.display_name)
        else:
            team = self._upsert_team(result.competitor.canonical_slug, result.competitor.display_name, result.competitor.source_competitor_id)
            competitor.team_id = team.id
            self._upsert_alias("team", result.competitor.source_competitor_id, result.competitor.name, result.competitor.canonical_slug, result.competitor.display_name)
        self.session.add(competitor)
        self.session.flush()
        if result.competitor.competitor_type == "team":
            for slug, name in zip(result.competitor.member_slugs, result.competitor.member_names, strict=True):
                player = self._upsert_player(slug, name, None, None)
                player_competitor = self.session.scalar(
                    select(EventCompetitor).where(
                        EventCompetitor.event_id == event.id,
                        EventCompetitor.competitor_type == "player",
                        EventCompetitor.canonical_slug == player.canonical_slug,
                    )
                )
                if player_competitor is None:
                    player_competitor = EventCompetitor(
                        event_id=event.id,
                        competitor_type="player",
                        canonical_slug=player.canonical_slug,
                        display_name=player.display_name,
                        player_id=player.id,
                        country=player.country,
                    )
                    self.session.add(player_competitor)
                    self.session.flush()
                membership = TeamMembership(
                    event_id=event.id,
                    team_competitor_id=competitor.id,
                    player_competitor_id=player_competitor.id,
                )
                self.session.add(membership)
                self._upsert_alias("player", None, name, player.canonical_slug, player.display_name)
        self.session.flush()
        return competitor

    def _upsert_player(self, slug: str, display_name: str, country: str | None, source_id: str | None) -> Player:
        player = self.session.scalar(select(Player).where(Player.canonical_slug == slug))
        if not player:
            player = Player(canonical_slug=slug, display_name=display_name, country=country, source_ids=[])
        player.display_name = display_name
        if country:
            player.country = country
        source_ids = list(player.source_ids or [])
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
        player.source_ids = source_ids
        self.session.add(player)
        self.session.flush()
        return player

    def _upsert_team(self, slug: str, display_name: str, source_id: str | None) -> Team:
        team = self.session.scalar(select(Team).where(Team.canonical_slug == slug))
        if not team:
            team = Team(canonical_slug=slug, display_name=display_name, source_ids=[])
        team.display_name = display_name
        source_ids = list(team.source_ids or [])
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
        team.source_ids = source_ids
        self.session.add(team)
        self.session.flush()
        return team

    def _upsert_alias(
        self,
        entity_type: str,
        source_id: str | None,
        exact_name: str | None,
        canonical_slug: str,
        display_name: str,
    ) -> None:
        candidates = compact_dict(
            {
                "source_id": source_id,
                "exact_name": exact_name,
            }
        )
        for match_kind, value in candidates.items():
            alias = self.session.scalar(
                select(EntityAlias).where(
                    EntityAlias.entity_type == entity_type,
                    EntityAlias.source == self.provider.source_name,
                    EntityAlias.source_key == value,
                    EntityAlias.match_kind == match_kind,
                )
            )
            if not alias:
                alias = EntityAlias(
                    entity_type=entity_type,
                    source=self.provider.source_name,
                    source_key=value,
                    match_kind=match_kind,
                    canonical_slug=canonical_slug,
                    display_name=display_name,
                )
            alias.canonical_slug = canonical_slug
            alias.display_name = display_name
            self.session.add(alias)
        self.session.flush()

    def _emit_progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


def _as_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 2)))
