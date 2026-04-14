from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import httpx

from tmrank.domain import ParsedCompetitor, ParsedEvent, ParsedEventResults, ParsedResultRow
from tmrank.services.aliases import AliasResolver
from tmrank.settings import Settings
from tmrank.utils import first_present, parse_date, slugify


class LiquipediaPayloadError(RuntimeError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        message = "; ".join(errors)
        if self.warnings:
            message = f"{message} | warnings: {'; '.join(self.warnings)}"
        super().__init__(message)


class LiquipediaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._next_request_at = 0.0
        self._client = httpx.Client(
            base_url=settings.liquipedia_base_url.rstrip("/") + "/",
            timeout=settings.liquipedia_timeout_seconds,
            headers={
                "Authorization": f"Apikey {settings.liquipedia_api_key}",
                "User-Agent": settings.liquipedia_user_agent,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def query_table(
        self,
        table: str,
        *,
        conditions: str,
        query_fields: str,
        order: str | None = None,
        page_size: int | None = None,
    ) -> Iterable[tuple[dict[str, Any], dict[str, Any], int]]:
        page_size = page_size or self.settings.liquipedia_page_size
        offset = 0
        while True:
            params: dict[str, Any] = {
                "wiki": self.settings.liquipedia_wiki,
                "conditions": conditions,
                "query": query_fields,
                "limit": page_size,
                "offset": offset,
            }
            if order:
                params["order"] = order
            payload, status_code = self._request_with_retries(table, params=params)
            if payload.get("error"):
                raise LiquipediaPayloadError(payload.get("error", []), payload.get("warning", []))
            rows = payload.get("result", [])
            yield params, payload, status_code
            if len(rows) < page_size:
                break
            offset += page_size

    def _request_with_retries(self, table: str, *, params: dict[str, Any]) -> tuple[dict[str, Any], int]:
        attempt = 0
        while True:
            self._wait_for_rate_limit()
            response = self._client.get(table, params=params)
            self._set_next_request_time(self.settings.liquipedia_request_sleep_seconds)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json(), response.status_code
            attempt += 1
            if attempt > self.settings.liquipedia_max_retries:
                response.raise_for_status()
            retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After"))
            self._set_next_request_time(max(self.settings.liquipedia_request_sleep_seconds, retry_after), reset=True)

    def _wait_for_rate_limit(self) -> None:
        remaining = self._next_request_at - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _set_next_request_time(self, seconds: float, *, reset: bool = False) -> None:
        base = time.monotonic() if reset else max(self._next_request_at, time.monotonic())
        self._next_request_at = base + max(0.0, seconds)


class LiquipediaProvider:
    source_name = "liquipedia"
    _tournament_query_fallbacks = (
        "pageid,pagename,name,shortname,seriespage,mode,type,startdate,enddate,sortdate,prizepool,participantsnumber,liquipediatier",
        "pageid,pagename,name,mode,type,startdate,enddate",
        "pageid,pagename,name",
    )
    _results_query_fallbacks = (
        "pageid,pagename,objectname,tournament,series,parent,date,placement,prizemoney,weight,mode,type,liquipediatier,opponentname,opponenttemplate,opponenttype,opponentplayers,qualifier,qualifierpage,qualifierurl,extradata",
        "pageid,pagename,objectname,tournament,parent,date,placement,prizemoney,opponentname,opponenttemplate,opponentplayers,extradata",
        "pageid,pagename,objectname,parent,date,placement,prizemoney,opponentname,opponentplayers,extradata",
        "pageid,pagename,objectname,parent,placement,opponentname",
    )

    def __init__(self, settings: Settings, alias_resolver: AliasResolver):
        self.settings = settings
        self.alias_resolver = alias_resolver
        self.client = LiquipediaClient(settings)

    def iter_tournaments(self) -> Iterable[tuple[ParsedEvent, dict[str, Any], dict[str, Any], int]]:
        last_error: Exception | None = None
        attempted_field_sets = []
        for query_fields in self._iter_tournament_query_fields():
            attempted_field_sets.append(query_fields)
            try:
                for params, payload, status_code in self.client.query_table(
                    self.settings.liquipedia_tournament_table,
                    conditions=self.settings.liquipedia_tournament_conditions,
                    query_fields=query_fields,
                    order="sortdate ASC",
                ):
                    for row in payload.get("result", []):
                        page_id = _to_int(row.get("pageid"))
                        page_name = row.get("pagename")
                        source_event_id = str(page_id or page_name or row.get("name"))
                        parsed = ParsedEvent(
                            source=self.source_name,
                            source_event_id=source_event_id,
                            page_id=page_id,
                            page_name=page_name,
                            name=str(row.get("name") or page_name or source_event_id),
                            series=row.get("seriespage") or row.get("shortname"),
                            tier=_to_int(row.get("liquipediatier")),
                            mode=_coerce_optional_str(row.get("mode")),
                            event_type=_coerce_optional_str(row.get("type")),
                            start_date=parse_date(row.get("startdate")),
                            end_date=parse_date(row.get("enddate")),
                            sort_date=parse_date(row.get("sortdate")) or parse_date(row.get("enddate")) or parse_date(row.get("startdate")),
                            prize_pool=_to_float(row.get("prizepool")),
                            participants_number=_to_int(row.get("participantsnumber")),
                            raw_payload=row,
                        )
                        yield parsed, params, row, status_code
                return
            except (httpx.HTTPStatusError, LiquipediaPayloadError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code != 404:
                    raise
                continue
        if last_error is not None:
            raise RuntimeError(
                "Liquipedia tournament query failed for all field sets. "
                f"Attempted: {attempted_field_sets}"
            ) from last_error

    def fetch_event_results(
        self,
        source_event_id: str,
        page_id: int | None = None,
        page_name: str | None = None,
    ) -> tuple[ParsedEventResults, dict[str, Any], dict[str, Any], int]:
        primary_conditions = self._primary_results_conditions(
            source_event_id,
            page_id=page_id,
            page_name=page_name,
        )
        primary_query_fields = self.settings.liquipedia_results_query_fields
        for conditions in primary_conditions:
            try:
                all_rows: list[dict[str, Any]] = []
                final_params: dict[str, Any] | None = None
                status_code = 200
                for params, payload, page_status in self.client.query_table(
                    self.settings.liquipedia_results_table,
                    conditions=conditions,
                    query_fields=primary_query_fields,
                    order=None,
                ):
                    status_code = page_status
                    final_params = params
                    all_rows.extend(payload.get("result", []))
                if all_rows or not self.settings.liquipedia_results_discovery_mode:
                    parsed = self._parse_event_results(source_event_id, all_rows)
                    return parsed, final_params or {}, {"result": all_rows}, status_code
            except (httpx.HTTPStatusError, LiquipediaPayloadError):
                if not self.settings.liquipedia_results_discovery_mode:
                    raise
                continue

        if not self.settings.liquipedia_results_discovery_mode:
            return self._parse_event_results(source_event_id, []), {}, {"result": []}, 200

        last_error: Exception | None = None
        attempts: list[tuple[str, str]] = []
        for conditions in self._iter_results_conditions(source_event_id, page_id=page_id, page_name=page_name):
            for query_fields in self._iter_results_query_fields():
                attempts.append((conditions, query_fields))
                try:
                    all_rows: list[dict[str, Any]] = []
                    final_params: dict[str, Any] | None = None
                    status_code = 200
                    for params, payload, page_status in self.client.query_table(
                        self.settings.liquipedia_results_table,
                        conditions=conditions,
                        query_fields=query_fields,
                        order=None,
                    ):
                        status_code = page_status
                        final_params = params
                        all_rows.extend(payload.get("result", []))
                    if all_rows:
                        parsed = self._parse_event_results(source_event_id, all_rows)
                        return parsed, final_params or {}, {"result": all_rows}, status_code
                except (httpx.HTTPStatusError, LiquipediaPayloadError) as exc:
                    last_error = exc
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (400, 404):
                        raise
                    continue
        if last_error is not None:
            raise RuntimeError(
                "Liquipedia results query failed for all condition/query combinations. "
                f"Attempted: {attempts}"
            ) from last_error
        return self._parse_event_results(source_event_id, []), {}, {"result": []}, 200

    def _parse_event_results(self, source_event_id: str, rows: list[dict[str, Any]]) -> ParsedEventResults:
        parsed_rows: list[ParsedResultRow] = []
        fetched_at = datetime.now(timezone.utc)
        for row in rows:
            place_low, place_high, place_text = _parse_placement(row)
            if not _is_ranking_result_row(row, place_low, place_high):
                continue
            competitor = self._parse_competitor(row)
            parsed_rows.append(
                ParsedResultRow(
                    placement_low=place_low,
                    placement_high=place_high,
                    placement_text=place_text,
                    prize=_to_float(first_present(row, ("prizemoney", "prize", "usdprize"))),
                    points=_to_float(row.get("points")),
                    competitor=competitor,
                    raw_payload=row,
                )
            )
        parsed_rows = _deduplicate_result_rows(parsed_rows)
        parsed_rows.sort(key=lambda result: (result.placement_low, result.placement_high, result.competitor.display_name))
        return ParsedEventResults(
            source=self.source_name,
            source_event_id=source_event_id,
            fetched_at=fetched_at,
            raw_rows=rows,
            results=parsed_rows,
        )

    def _parse_competitor(self, row: dict[str, Any]) -> ParsedCompetitor:
        extradata = _normalize_json_blob(row.get("extradata"))
        opponent_players = _normalize_json_value(row.get("opponentplayers"))
        member_names = _extract_member_names(extradata, opponent_players)
        opponent_type = (_coerce_optional_str(row.get("opponenttype")) or "").lower()
        if len(member_names) > 1 or opponent_type in {"team", "duo", "trio", "squad"}:
            source_id = _coerce_optional_str(first_present(row, ("opponenttemplate", "teamtemplate", "teamid")))
            alias = self.alias_resolver.resolve_team(source_id=source_id, exact_name=row.get("opponentname"))
            member_slugs: list[str] = []
            canonical_member_names: list[str] = []
            for member_name in member_names:
                player_alias = self.alias_resolver.resolve_player(source_id=None, exact_name=member_name)
                member_slugs.append(player_alias.canonical_slug)
                canonical_member_names.append(player_alias.display_name)
            return ParsedCompetitor(
                competitor_type="team",
                source_competitor_id=source_id,
                name=str(row.get("opponentname") or alias.display_name),
                canonical_slug=alias.canonical_slug,
                display_name=alias.display_name,
                member_slugs=member_slugs,
                member_names=canonical_member_names,
            )

        source_id = _coerce_optional_str(first_present(row, ("playerid", "participantid", "opponenttemplate")))
        raw_name = str(
            first_present(row, ("opponentname", "objectname", "tournament", "pagename", "player"))
            or source_id
            or "Unknown Player"
        )
        alias = self.alias_resolver.resolve_player(source_id=source_id, exact_name=raw_name)
        return ParsedCompetitor(
            competitor_type="player",
            source_competitor_id=source_id,
            name=raw_name,
            canonical_slug=alias.canonical_slug,
            display_name=alias.display_name,
            country=_coerce_optional_str(first_present(row, ("country", "nationality"))),
        )

    def _iter_tournament_query_fields(self) -> list[str]:
        field_sets = [self.settings.liquipedia_tournament_query_fields]
        for fallback in self._tournament_query_fallbacks:
            if fallback not in field_sets:
                field_sets.append(fallback)
        return field_sets

    def _iter_results_query_fields(self) -> list[str]:
        field_sets = [self.settings.liquipedia_results_query_fields]
        for fallback in self._results_query_fallbacks:
            if fallback not in field_sets:
                field_sets.append(fallback)
        return field_sets

    def _iter_results_conditions(
        self,
        source_event_id: str,
        *,
        page_id: int | None,
        page_name: str | None,
    ) -> list[str]:
        candidates: list[str] = self._primary_results_conditions(
            source_event_id,
            page_id=page_id,
            page_name=page_name,
        )
        template_values = {
            "source_event_id": source_event_id,
            "pageid": page_id or "",
            "page_id": page_id or "",
            "page_name": page_name or "",
            "pagename": page_name or "",
        }
        try:
            template_condition = self.settings.liquipedia_results_conditions_template.format(**template_values)
            if template_condition not in candidates:
                candidates.append(template_condition)
        except KeyError:
            pass
        for value in (source_event_id, str(page_id) if page_id is not None else None):
            if not value:
                continue
            candidates.extend(
                [
                    f"[[parent::{value}]]",
                    f"[[tournament::{value}]]",
                    f"[[pagename::{value}]]",
                ]
            )
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    def _primary_results_conditions(
        self,
        source_event_id: str,
        *,
        page_id: int | None,
        page_name: str | None,
    ) -> list[str]:
        candidates: list[str] = []
        if page_name:
            candidates.append(f"[[parent::{page_name}]]")
            return candidates
        if source_event_id and source_event_id != page_name:
            candidates.append(f"[[parent::{source_event_id}]]")
        if page_id is not None and str(page_id) not in {source_event_id, page_name}:
            candidates.append(f"[[parent::{page_id}]]")
        return candidates


def _normalize_json_blob(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, "", []):
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_json_value(value: Any) -> Any:
    if value in (None, "", []):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def _extract_member_names(extradata: dict[str, Any], opponent_players: Any = None) -> list[str]:
    members: list[str] = []
    for key in ("players", "members", "roster"):
        value = extradata.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    members.append(item.strip())
                elif isinstance(item, dict):
                    candidate = first_present(item, ("name", "display_name", "player"))
                    if isinstance(candidate, str) and candidate.strip():
                        members.append(candidate.strip())
    if isinstance(opponent_players, list):
        for item in opponent_players:
            if isinstance(item, str) and item.strip():
                members.append(item.strip())
            elif isinstance(item, dict):
                candidate = first_present(item, ("name", "display_name", "player"))
                if isinstance(candidate, str) and candidate.strip():
                    members.append(candidate.strip())
    elif isinstance(opponent_players, dict):
        indexed: dict[str, str] = {}
        for key, value in opponent_players.items():
            if not isinstance(value, str) or not value.strip():
                continue
            if key.startswith("p") and key[1:].isdigit():
                indexed[key[1:]] = value.strip()
            elif key.startswith("p") and key.endswith("dn") and key[1:-2].isdigit():
                indexed[key[1:-2]] = value.strip()
        members.extend(value for _, value in sorted(indexed.items(), key=lambda item: int(item[0])))
    if members:
        return list(dict.fromkeys(members))
    indexed = defaultdict(dict)
    for key, value in extradata.items():
        if not isinstance(value, str):
            continue
        if key.startswith("player"):
            suffix = key.removeprefix("player")
            indexed[suffix]["name"] = value
        elif key.startswith("p") and key[1:].isdigit():
            indexed[key[1:]]["name"] = value
    return [value["name"] for _, value in sorted(indexed.items()) if value.get("name")]


def _parse_placement(row: dict[str, Any]) -> tuple[int, int, str]:
    raw_value = first_present(row, ("placement", "place", "placementtext"))
    text = str(raw_value or "").strip()
    if not text:
        return 9999, 9999, "Unknown"
    digits = [int(part) for part in text.replace("th", "").replace("st", "").replace("nd", "").replace("rd", "").split("-") if part.strip().isdigit()]
    if len(digits) == 1:
        return digits[0], digits[0], text
    if len(digits) >= 2:
        return digits[0], digits[1], text
    try:
        as_int = int(text)
        return as_int, as_int, text
    except ValueError:
        return 9999, 9999, text


def _is_ranking_result_row(row: dict[str, Any], placement_low: int, placement_high: int) -> bool:
    if placement_low == 9999 and placement_high == 9999:
        return False
    object_name = str(row.get("objectname") or "").lower()
    if object_name.startswith(f"{row.get('pageid', '')}_award_") or "_award_" in object_name:
        return False
    if not (row.get("opponentname") or row.get("opponentplayers")):
        return False
    return True


def _deduplicate_result_rows(rows: list[ParsedResultRow]) -> list[ParsedResultRow]:
    by_competitor: dict[tuple[str, str], ParsedResultRow] = {}
    for row in rows:
        key = (row.competitor.competitor_type, row.competitor.canonical_slug)
        existing = by_competitor.get(key)
        if existing is None or _prefer_result_row(row, existing):
            by_competitor[key] = row
    return list(by_competitor.values())


def _prefer_result_row(candidate: ParsedResultRow, current: ParsedResultRow) -> bool:
    candidate_score = (
        -candidate.placement_low,
        -candidate.placement_high,
        _numeric_value(candidate.prize),
        _numeric_value(candidate.points),
        1 if candidate.competitor.source_competitor_id else 0,
    )
    current_score = (
        -current.placement_low,
        -current.placement_high,
        _numeric_value(current.prize),
        _numeric_value(current.points),
        1 if current.competitor.source_competitor_id else 0,
    )
    return candidate_score > current_score


def _numeric_value(value: float | None) -> float:
    return value if value is not None else float("-inf")


def _to_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0
