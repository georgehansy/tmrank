from datetime import date

from tmrank.config_models import TournamentRulesConfig
from tmrank.services.curation import EventView, TournamentCurator


def test_tournament_rules_last_match_wins() -> None:
    curator = TournamentCurator(
        TournamentRulesConfig.model_validate(
            {
                "defaults": {"include": True, "weight": 1.0, "tags": []},
                "rules": [
                    {"name": "lan", "match": {"type": "Offline"}, "weight": 1.2, "tags": ["lan"]},
                    {"name": "exclude finals", "match": {"name_regex": "Final"}, "include": False},
                ],
            }
        )
    )
    curated = curator.evaluate(
        EventView(
            source_event_id="event-1",
            page_id=1,
            tier=1,
            page_name="Winter_Final",
            name="Winter Final",
            series="Winter",
            mode="solo",
            event_type="Offline",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
        )
    )
    assert curated.include is False
    assert curated.weight == 1.2
    assert curated.tags == ["lan"]


def test_tournament_rules_can_exclude_series() -> None:
    curator = TournamentCurator(
        TournamentRulesConfig.model_validate(
            {
                "defaults": {"include": True, "weight": 1.0, "tags": []},
                "rules": [
                    {
                        "name": "exclude campaign",
                        "match": {"series": "Trackmania_Seasonal_Campaign"},
                        "include": False,
                        "tags": ["campaign"],
                    }
                ],
            }
        )
    )
    curated = curator.evaluate(
        EventView(
            source_event_id="event-2",
            page_id=2,
            tier=1,
            page_name="Spring_2024_Campaign",
            name="Spring 2024 Campaign",
            series="Trackmania_Seasonal_Campaign",
            mode="solo",
            event_type="Online",
            start_date=date(2024, 3, 1),
            end_date=date(2024, 3, 31),
        )
    )
    assert curated.include is False
    assert curated.weight == 1.0
    assert curated.tags == ["campaign"]


def test_tournament_rules_can_match_page_name_regex() -> None:
    curator = TournamentCurator(
        TournamentRulesConfig.model_validate(
            {
                "defaults": {"include": True, "weight": 1.0, "tags": []},
                "rules": [
                    {
                        "name": "boost world cup",
                        "match": {"page_name_regex": r"^Trackmania_World_Tour/2025/World_Cup$"},
                        "weight": 1.3,
                        "tags": ["world-cup"],
                    }
                ],
            }
        )
    )
    curated = curator.evaluate(
        EventView(
            source_event_id="event-3",
            page_id=3,
            tier=1,
            page_name="Trackmania_World_Tour/2025/World_Cup",
            name="Trackmania World Cup 2025",
            series="Trackmania_World_Tour",
            mode="solo",
            event_type="Offline",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 5),
        )
    )
    assert curated.include is True
    assert curated.weight == 1.3
    assert curated.tags == ["world-cup"]


def test_tournament_rules_can_match_tier() -> None:
    curator = TournamentCurator(
        TournamentRulesConfig.model_validate(
            {
                "defaults": {"include": True, "weight": 1.0, "tags": []},
                "rules": [
                    {
                        "name": "downweight tier 2",
                        "match": {"tier": 2},
                        "weight": 0.6,
                        "tags": ["tier-2"],
                    }
                ],
            }
        )
    )
    curated = curator.evaluate(
        EventView(
            source_event_id="event-4",
            page_id=4,
            tier=2,
            page_name="Trackmania_Open/2025",
            name="Trackmania Open 2025",
            series="Trackmania_Open",
            mode="solo",
            event_type="Online",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 15),
        )
    )
    assert curated.include is True
    assert curated.weight == 0.6
    assert curated.tags == ["tier-2"]
