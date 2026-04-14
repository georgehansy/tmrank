from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tmrank.config_models import AliasesConfig
from tmrank.db.base import Base
from tmrank.db.models import Event, EventCompetitor, EventResult, Player, TeamMembership
from tmrank.domain import ParsedCompetitor, ParsedEventResults, ParsedResultRow
from tmrank.services.aliases import AliasResolver
from tmrank.services.sync import SyncService


class _DummyProvider:
    source_name = "liquipedia"

    def __init__(self) -> None:
        self.settings = type(
            "S",
            (),
            {
                "liquipedia_tournament_table": "tournament",
                "liquipedia_results_table": "placement",
            },
        )()


class _BatchProvider(_DummyProvider):
    def fetch_event_results(self, source_event_id, page_id=None, page_name=None):
        del page_id, page_name
        if source_event_id == "boom":
            raise RuntimeError("boom")
        parsed = ParsedEventResults(
            source="liquipedia",
            source_event_id=source_event_id,
            fetched_at=datetime.now(timezone.utc),
            raw_rows=[],
            results=[
                ParsedResultRow(
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    prize=100.0,
                    points=None,
                    competitor=ParsedCompetitor(
                        competitor_type="player",
                        source_competitor_id=f"{source_event_id}-player",
                        name=f"{source_event_id} Player",
                        canonical_slug=f"{source_event_id}-player",
                        display_name=f"{source_event_id} Player",
                    ),
                    raw_payload={},
                )
            ],
        )
        return parsed, {"parent": source_event_id}, {"result": []}, 200


def test_results_sync_status_and_filters() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Event(
                    source="liquipedia",
                    source_event_id="old-unsynced",
                    name="Old Unsynced",
                    end_date=date(today.year - 2, 1, 1),
                ),
                Event(
                    source="liquipedia",
                    source_event_id="mid-synced",
                    name="Mid Synced",
                    end_date=date(today.year - 1, 1, 1),
                    results_synced_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
                ),
                Event(
                    source="liquipedia",
                    source_event_id="new-unsynced",
                    name="New Unsynced",
                    end_date=date(today.year, 1, 1),
                ),
                Event(
                    source="liquipedia",
                    source_event_id="future-unsynced",
                    name="Future Unsynced",
                    end_date=date(today.year + 1, 1, 1),
                ),
                Event(
                    source="liquipedia",
                    source_event_id="undated-unsynced",
                    name="Undated Unsynced",
                ),
            ]
        )
        session.commit()

        service = SyncService(
            session,
            _DummyProvider(),
            AliasResolver(AliasesConfig(players=[], teams=[])),
        )

        status = service.get_results_sync_status(limit=5)
        assert status["totals"] == {
            "matching_events": 3,
            "synced_events": 1,
            "unsynced_events": 2,
        }
        assert [candidate["source_event_id"] for candidate in status["next_candidates"]] == [
            "old-unsynced",
            "new-unsynced",
        ]

        filtered_status = service.get_results_sync_status(
            limit=5,
            start_date=date(today.year - 1, 1, 1),
            end_date=date(today.year, 12, 31),
        )
        assert filtered_status["totals"] == {
            "matching_events": 2,
            "synced_events": 1,
            "unsynced_events": 1,
        }
        assert [candidate["source_event_id"] for candidate in filtered_status["next_candidates"]] == [
            "new-unsynced",
        ]

        forced_status = service.get_results_sync_status(force=True, limit=5)
        assert [candidate["source_event_id"] for candidate in forced_status["next_candidates"]] == [
            "old-unsynced",
            "mid-synced",
            "new-unsynced",
        ]


def test_events_for_results_allows_explicit_future_event_selection() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Event(
                source="liquipedia",
                source_event_id="future-explicit",
                name="Future Explicit",
                end_date=date(today.year + 1, 1, 1),
            )
        )
        session.commit()

        service = SyncService(
            session,
            _DummyProvider(),
            AliasResolver(AliasesConfig(players=[], teams=[])),
        )

        candidates = service._events_for_results(
            ["future-explicit"],
            force=False,
            limit=10,
            start_date=None,
            end_date=None,
        )
        assert [event.source_event_id for event in candidates] == ["future-explicit"]


def test_sync_event_results_batch_persists_completed_events_on_late_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Event(
                    source="liquipedia",
                    source_event_id="ok",
                    name="Okay Event",
                    end_date=date(2006, 1, 1),
                ),
                Event(
                    source="liquipedia",
                    source_event_id="boom",
                    name="Broken Event",
                    end_date=date(2007, 1, 1),
                ),
            ]
        )
        session.commit()

        service = SyncService(
            session,
            _BatchProvider(),
            AliasResolver(AliasesConfig(players=[], teams=[])),
        )

        with pytest.raises(RuntimeError, match="boom"):
            service.sync_event_results_batch(force=True)

        persisted_event = session.query(Event).filter_by(source_event_id="ok").one()
        assert persisted_event.results_synced_at is not None
        assert session.query(EventResult).filter_by(event_id=persisted_event.id).count() == 1


def test_clear_existing_results_removes_memberships_referencing_player_competitors() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        event = Event(
            source="liquipedia",
            source_event_id="team-event",
            name="Team Event",
            end_date=date(2024, 1, 1),
        )
        session.add(event)
        session.flush()

        player_one = Player(canonical_slug="player-one", display_name="Player One", source_ids=[])
        player_two = Player(canonical_slug="player-two", display_name="Player Two", source_ids=[])
        session.add_all([player_one, player_two])
        session.flush()

        team_competitor = EventCompetitor(
            event_id=event.id,
            competitor_type="team",
            canonical_slug="duo-squad",
            display_name="Duo Squad",
        )
        player_competitor_one = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="player-one",
            display_name="Player One",
            player_id=player_one.id,
        )
        player_competitor_two = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="player-two",
            display_name="Player Two",
            player_id=player_two.id,
        )
        session.add_all([team_competitor, player_competitor_one, player_competitor_two])
        session.flush()

        session.add_all(
            [
                TeamMembership(
                    event_id=event.id,
                    team_competitor_id=team_competitor.id,
                    player_competitor_id=player_competitor_one.id,
                ),
                TeamMembership(
                    event_id=event.id,
                    team_competitor_id=team_competitor.id,
                    player_competitor_id=player_competitor_two.id,
                ),
            ]
        )
        session.flush()

        service = SyncService(
            session,
            _DummyProvider(),
            AliasResolver(AliasesConfig(players=[], teams=[])),
        )

        service._clear_existing_results(event.id)

        assert session.query(TeamMembership).count() == 0
        assert session.query(EventCompetitor).count() == 0
