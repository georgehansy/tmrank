from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tmrank.config_models import AliasesConfig, RatingProfile, TournamentRulesConfig
from tmrank.domain import ParsedCompetitor, ParsedEvent, ParsedEventResults, ParsedResultRow
from tmrank.services.aliases import AliasResolver
from tmrank.services.ratings import RatingsService
from tmrank.services.sync import SyncService


TEST_DATABASE_URL = os.getenv("TMRANK_TEST_DATABASE_URL")


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TMRANK_TEST_DATABASE_URL is not configured.")
def test_pipeline_roundtrip(tmp_path: Path) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL, future=True)

    class FakeProvider:
        source_name = "liquipedia"

        def __init__(self):
            self.settings = type("S", (), {"liquipedia_tournament_table": "tournament", "liquipedia_results_table": "placement"})()

        def iter_tournaments(self):
            yield (
                ParsedEvent(
                    source="liquipedia",
                    source_event_id="event-1",
                    page_id=1,
                    page_name="Event_1",
                    name="Event 1",
                    series="Series",
                    tier=1,
                    mode="solo",
                    event_type="Offline",
                    start_date=None,
                    end_date=date(2024, 1, 10),
                    sort_date=date(2024, 1, 10),
                    prize_pool=1000.0,
                    participants_number=2,
                    raw_payload={"pageid": 1},
                ),
                {"wiki": "trackmania"},
                {"pageid": 1},
                200,
            )

        def fetch_event_results(self, source_event_id, page_id=None, page_name=None):
            del source_event_id, page_id, page_name
            parsed = ParsedEventResults(
                source="liquipedia",
                source_event_id="event-1",
                fetched_at=datetime.now(timezone.utc),
                raw_rows=[],
                results=[
                    ParsedResultRow(
                        placement_low=1,
                        placement_high=1,
                        placement_text="1",
                        prize=600.0,
                        points=None,
                        competitor=ParsedCompetitor(
                            competitor_type="player",
                            source_competitor_id="p1",
                            name="Player One",
                            canonical_slug="player-one",
                            display_name="Player One",
                        ),
                        raw_payload={},
                    ),
                    ParsedResultRow(
                        placement_low=2,
                        placement_high=2,
                        placement_text="2",
                        prize=400.0,
                        points=None,
                        competitor=ParsedCompetitor(
                            competitor_type="player",
                            source_competitor_id="p2",
                            name="Player Two",
                            canonical_slug="player-two",
                            display_name="Player Two",
                        ),
                        raw_payload={},
                    ),
                ],
            )
            return parsed, {"parent": "event-1"}, {"result": []}, 200

    with Session(engine) as session:
        alias_resolver = AliasResolver(AliasesConfig(players=[], teams=[]))
        sync_service = SyncService(session, FakeProvider(), alias_resolver)
        sync_service.sync_tournaments()
        sync_service.sync_event_results()
        ratings = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        ).compute_current_rankings()
        assert [row.player_slug for row in ratings[:2]] == ["player-one", "player-two"]
