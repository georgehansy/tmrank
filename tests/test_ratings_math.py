import math
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tmrank.config_models import MajorEventsConfig, RatingProfile, TournamentRulesConfig
from tmrank.db.base import Base
from tmrank.db.models import Event, EventCompetitor, EventResult, Player
from tmrank.services.ratings import RatingsService

from tmrank.services.ratings import _best_rolling_average, _inflate_sigma, _normalize_goat_metrics, _normalize_metric, _percentile


def test_inflate_sigma_respects_cap() -> None:
    sigma = _inflate_sigma(
        current_sigma=8.0,
        previous_date=date(2024, 1, 1),
        next_date=date(2025, 1, 1),
        sigma_cap=8.333,
        monthly_drift=0.5,
    )
    assert math.isclose(sigma, 8.333)


def test_normalize_metric_handles_flat_series() -> None:
    normalized = _normalize_metric({"a": 3.0, "b": 3.0})
    assert normalized == {"a": 1.0, "b": 1.0}


def test_percentile_interpolates_sorted_values() -> None:
    values = [0.0, 10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 0) == 0.0
    assert _percentile(values, 50) == 20.0
    assert _percentile(values, 90) == 36.0
    assert _percentile(values, 100) == 40.0


def test_normalize_goat_metrics_uses_plain_min_max_for_all_dimensions() -> None:
    normalized = _normalize_goat_metrics(
        {
            "prime_rating": {"low": 0.0, "mid": 50.0, "high": 100.0},
            "median_conservative": {"low": 0.0, "mid": 50.0, "high": 100.0},
            "elite_area": {"low": 0.0, "mid": 9.0, "high": 100.0},
            "title_points": {"low": 0.0, "mid": 9.0, "high": 100.0},
        }
    )
    assert normalized["prime_rating"]["mid"] == 0.5
    assert normalized["median_conservative"]["mid"] == 0.5
    assert normalized["elite_area"]["mid"] == 0.09
    assert normalized["title_points"]["mid"] == 0.09


def test_normalize_goat_metrics_can_sqrt_selected_dimensions() -> None:
    normalized = _normalize_goat_metrics(
        {
            "prime_rating": {"low": 0.0, "mid": 50.0, "high": 100.0},
            "elite_area": {"low": 0.0, "mid": 9.0, "high": 100.0},
            "title_points": {"low": 0.0, "mid": 9.0, "high": 100.0},
        },
        sqrt_metrics={"elite_area", "title_points"},
    )
    assert normalized["prime_rating"]["mid"] == 0.5
    assert normalized["elite_area"]["mid"] == 0.3
    assert normalized["title_points"]["mid"] == 0.3


def test_best_rolling_average_uses_calendar_month_window() -> None:
    assert math.isclose(
        _best_rolling_average(
            [
                ("2024-01", 10.0),
                ("2024-02", 20.0),
                ("2025-02", 40.0),
            ],
            window_months=12,
            min_active_months=1,
        ),
        40.0,
    )


def test_best_rolling_average_requires_minimum_active_months() -> None:
    assert math.isclose(
        _best_rolling_average(
            [
                ("2024-01", 10.0),
                ("2024-03", 20.0),
                ("2024-05", 30.0),
            ],
            window_months=12,
            min_active_months=6,
        ),
        0.0,
    )


def test_field_size_controls_use_effective_field_size() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate(
                {
                    "max_effective_field_size": 128,
                    "field_size_dampening_start": 4,
                    "field_size_dampening_strength": 0.6,
                }
            ),
        )
        assert service._effective_field_size(8) == 8
        assert service._effective_field_size(128) == 128
        assert service._effective_field_size(386) == 128
        assert math.isclose(service._field_size_weight_factor(4), 1.0)
        assert math.isclose(service._field_size_weight_factor(128), 0.4)


def test_ratings_service_uses_mpmath_backend() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        assert service.environment.backend == "mpmath"


def test_ratings_ignore_future_events() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="past-player", display_name="Past Player", source_ids=[]),
                Player(id=3, canonical_slug="past-player-two", display_name="Past Player Two", source_ids=[]),
                Player(id=2, canonical_slug="future-player", display_name="Future Player", source_ids=[]),
            ]
        )
        session.flush()

        past_event = Event(
            source="liquipedia",
            source_event_id="past-event",
            name="Past Event",
            end_date=date(today.year - 1, 1, 1),
        )
        future_event = Event(
            source="liquipedia",
            source_event_id="future-event",
            name="Future Event",
            end_date=date(today.year + 1, 1, 1),
        )
        session.add_all([past_event, future_event])
        session.flush()

        past_competitor = EventCompetitor(
            event_id=past_event.id,
            competitor_type="player",
            canonical_slug="past-player",
            display_name="Past Player",
            player_id=1,
        )
        past_competitor_two = EventCompetitor(
            event_id=past_event.id,
            competitor_type="player",
            canonical_slug="past-player-two",
            display_name="Past Player Two",
            player_id=3,
        )
        future_competitor = EventCompetitor(
            event_id=future_event.id,
            competitor_type="player",
            canonical_slug="future-player",
            display_name="Future Player",
            player_id=2,
        )
        session.add_all([past_competitor, past_competitor_two, future_competitor])
        session.flush()

        session.add_all(
            [
                EventResult(
                    event_id=past_event.id,
                    competitor_id=past_competitor.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
                EventResult(
                    event_id=past_event.id,
                    competitor_id=past_competitor_two.id,
                    placement_low=2,
                    placement_high=2,
                    placement_text="2",
                    raw_payload={},
                ),
                EventResult(
                    event_id=future_event.id,
                    competitor_id=future_competitor.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        rows = service.compute_current_rankings()
        assert [row.player_slug for row in rows] == ["past-player", "past-player-two"]


def test_ratings_ignore_single_competitor_events() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="real-player", display_name="Real Player", source_ids=[]),
                Player(id=2, canonical_slug="solo-placeholder", display_name="TBD", source_ids=[]),
            ]
        )
        session.flush()

        good_event = Event(
            source="liquipedia",
            source_event_id="good-event",
            name="Good Event",
            end_date=today,
        )
        bad_event = Event(
            source="liquipedia",
            source_event_id="bad-event",
            name="Bad Event",
            end_date=today,
        )
        session.add_all([good_event, bad_event])
        session.flush()

        good_a = EventCompetitor(
            event_id=good_event.id,
            competitor_type="player",
            canonical_slug="real-player",
            display_name="Real Player",
            player_id=1,
        )
        good_b = EventCompetitor(
            event_id=good_event.id,
            competitor_type="player",
            canonical_slug="solo-placeholder",
            display_name="TBD",
            player_id=2,
        )
        bad_only = EventCompetitor(
            event_id=bad_event.id,
            competitor_type="player",
            canonical_slug="solo-placeholder",
            display_name="TBD",
            player_id=2,
        )
        session.add_all([good_a, good_b, bad_only])
        session.flush()

        session.add_all(
            [
                EventResult(
                    event_id=good_event.id,
                    competitor_id=good_a.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
                EventResult(
                    event_id=good_event.id,
                    competitor_id=good_b.id,
                    placement_low=2,
                    placement_high=2,
                    placement_text="2",
                    raw_payload={},
                ),
                EventResult(
                    event_id=bad_event.id,
                    competitor_id=bad_only.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate(
                {
                    "current_eligibility": {
                        "min_events_played": 1,
                        "max_months_since_last_event": 24,
                    }
                }
            ),
        )
        rows = service.compute_current_rankings()
        assert [row.player_slug for row in rows] == ["real-player", "solo-placeholder"]


def test_ratings_cap_large_fields_to_effective_size() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        player_count = 130
        for player_id in range(1, player_count + 1):
            session.add(
                Player(
                    id=player_id,
                    canonical_slug=f"player-{player_id}",
                    display_name=f"Player {player_id}",
                    source_ids=[],
                )
            )
        session.flush()

        event = Event(
            source="liquipedia",
            source_event_id="big-event",
            name="Big Event",
            end_date=today,
        )
        session.add(event)
        session.flush()

        competitors = []
        for player_id in range(1, player_count + 1):
            competitor = EventCompetitor(
                event_id=event.id,
                competitor_type="player",
                canonical_slug=f"player-{player_id}",
                display_name=f"Player {player_id}",
                player_id=player_id,
            )
            competitors.append(competitor)
        session.add_all(competitors)
        session.flush()

        for placement, competitor in enumerate(competitors, start=1):
            session.add(
                EventResult(
                    event_id=event.id,
                    competitor_id=competitor.id,
                    placement_low=placement,
                    placement_high=placement,
                    placement_text=str(placement),
                    raw_payload={},
                )
            )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate(
                {
                    "current_eligibility": {
                        "min_events_played": 0,
                        "max_months_since_last_event": 24,
                    },
                    "max_effective_field_size": 128,
                    "field_size_dampening_start": None,
                }
            ),
        )
        rows = service.compute_current_rankings()
        by_slug = {row.player_slug: row for row in rows}
        assert by_slug["player-1"].events_played == 1
        assert by_slug["player-1"].recent_events_24_months == 1
        assert by_slug["player-128"].events_played == 1
        assert by_slug["player-128"].recent_events_24_months == 1
        assert "player-129" not in by_slug
        assert "player-130" not in by_slug


def test_export_rankings_supports_slotted_dataclasses(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="winner", display_name="Winner", source_ids=[]),
                Player(id=2, canonical_slug="runner-up", display_name="Runner Up", source_ids=[]),
            ]
        )
        session.flush()

        event = Event(
            source="liquipedia",
            source_event_id="export-event",
            name="Export Event",
            end_date=date(2024, 1, 1),
        )
        session.add(event)
        session.flush()

        winner = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="winner",
            display_name="Winner",
            player_id=1,
        )
        runner_up = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="runner-up",
            display_name="Runner Up",
            player_id=2,
        )
        session.add_all([winner, runner_up])
        session.flush()

        session.add_all(
            [
                EventResult(
                    event_id=event.id,
                    competitor_id=winner.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
                EventResult(
                    event_id=event.id,
                    competitor_id=runner_up.id,
                    placement_low=2,
                    placement_high=2,
                    placement_text="2",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        outputs = service.export_rankings(tmp_path)
        assert outputs["current_json"].exists()
        assert outputs["current_csv"].exists()
        assert outputs["goat_json"].exists()
        assert outputs["goat_csv"].exists()


def test_build_site_payload_trims_expected_views() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="winner", display_name="Winner", source_ids=[]),
                Player(id=2, canonical_slug="runner-up", display_name="Runner Up", source_ids=[]),
            ]
        )
        session.flush()

        event = Event(
            source="liquipedia",
            source_event_id="site-event",
            name="Site Event",
            end_date=today,
        )
        session.add(event)
        session.flush()

        winner = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="winner",
            display_name="Winner",
            player_id=1,
        )
        runner_up = EventCompetitor(
            event_id=event.id,
            competitor_type="player",
            canonical_slug="runner-up",
            display_name="Runner Up",
            player_id=2,
        )
        session.add_all([winner, runner_up])
        session.flush()

        session.add_all(
            [
                EventResult(
                    event_id=event.id,
                    competitor_id=winner.id,
                    placement_low=1,
                    placement_high=1,
                    placement_text="1",
                    raw_payload={},
                ),
                EventResult(
                    event_id=event.id,
                    competitor_id=runner_up.id,
                    placement_low=2,
                    placement_high=2,
                    placement_text="2",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
            MajorEventsConfig.model_validate({"rules": [{"name": "Major", "match": {"source_event_id": "site-event"}}]}),
        )
        payload = service.build_site_payload("default")

        assert payload["profile"] == {"name": "default", "label": "Esports"}
        assert set(payload) == {
            "profile",
            "generated_at",
            "goat_top20",
            "current_top10",
            "rating_leader_timeline",
            "title_leaders_top10",
        }
        assert len(payload["goat_top20"]) == 2
        assert len(payload["current_top10"]) == 2
        assert len(payload["title_leaders_top10"]) == 2
        assert payload["title_leaders_top10"][0]["title_points"] == 10.0
        assert payload["current_top10"][0]["recent_events_24_months"] == 1


def test_current_rankings_apply_inactivity_drift_as_of_today() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="active-winner", display_name="Active Winner", source_ids=[]),
                Player(id=2, canonical_slug="active-runner", display_name="Active Runner", source_ids=[]),
                Player(id=3, canonical_slug="inactive-winner", display_name="Inactive Winner", source_ids=[]),
                Player(id=4, canonical_slug="inactive-runner", display_name="Inactive Runner", source_ids=[]),
            ]
        )
        session.flush()

        active_event = Event(
            source="liquipedia",
            source_event_id="active-event",
            name="Active Event",
            end_date=today,
        )
        inactive_event = Event(
            source="liquipedia",
            source_event_id="inactive-event",
            name="Inactive Event",
            end_date=date(today.year - 3, today.month, max(1, today.day)),
        )
        session.add_all([active_event, inactive_event])
        session.flush()

        competitors = [
            EventCompetitor(event_id=active_event.id, competitor_type="player", canonical_slug="active-winner", display_name="Active Winner", player_id=1),
            EventCompetitor(event_id=active_event.id, competitor_type="player", canonical_slug="active-runner", display_name="Active Runner", player_id=2),
            EventCompetitor(event_id=inactive_event.id, competitor_type="player", canonical_slug="inactive-winner", display_name="Inactive Winner", player_id=3),
            EventCompetitor(event_id=inactive_event.id, competitor_type="player", canonical_slug="inactive-runner", display_name="Inactive Runner", player_id=4),
        ]
        session.add_all(competitors)
        session.flush()

        session.add_all(
            [
                EventResult(event_id=active_event.id, competitor_id=competitors[0].id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=active_event.id, competitor_id=competitors[1].id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=inactive_event.id, competitor_id=competitors[2].id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=inactive_event.id, competitor_id=competitors[3].id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        rows = service.compute_current_rankings()
        inactive = next(row for row in rows if row.player_slug == "inactive-winner")
        active = next(row for row in rows if row.player_slug == "active-winner")
        assert inactive.sigma == 8.333
        assert active.sigma < inactive.sigma
        assert active.conservative_score > inactive.conservative_score


def test_goat_rankings_include_events_played() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="winner", display_name="Winner", source_ids=[]),
                Player(id=2, canonical_slug="runner", display_name="Runner", source_ids=[]),
            ]
        )
        session.flush()

        event = Event(
            source="liquipedia",
            source_event_id="goat-event",
            name="Goat Event",
            end_date=today,
        )
        session.add(event)
        session.flush()

        winner = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="winner", display_name="Winner", player_id=1)
        runner = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="runner", display_name="Runner", player_id=2)
        session.add_all([winner, runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=event.id, competitor_id=winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=event.id, competitor_id=runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        rows = service.compute_goat_rankings()
        assert rows[0].events_played == 1
        assert hasattr(rows[0], "prime_rating")
        assert rows[0].prime_rating == 0
        assert rows[0].median_conservative > 0
        assert rows[0].active_months == 1


def test_goat_metric_summary_reports_min_median_max() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="winner", display_name="Winner", source_ids=[]),
                Player(id=2, canonical_slug="runner", display_name="Runner", source_ids=[]),
            ]
        )
        session.flush()

        event = Event(
            source="liquipedia",
            source_event_id="metric-event",
            name="Metric Event",
            end_date=today,
        )
        session.add(event)
        session.flush()

        winner = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="winner", display_name="Winner", player_id=1)
        runner = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="runner", display_name="Runner", player_id=2)
        session.add_all([winner, runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=event.id, competitor_id=winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=event.id, competitor_id=runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        summary = service.compute_goat_metric_summary()
        assert set(summary) == {
            "prime_rating",
            "elite_area",
            "median_conservative",
            "title_points",
        }
        assert summary["prime_rating"]["count"] == 2
        assert "p1" in summary["prime_rating"]
        assert "p10" in summary["prime_rating"]
        assert "p90" in summary["prime_rating"]
        assert "p99" in summary["prime_rating"]
        assert float(summary["prime_rating"]["max"]) >= float(summary["prime_rating"]["median"])
        assert float(summary["prime_rating"]["median"]) >= float(summary["prime_rating"]["min"])


def test_goat_rankings_use_full_monthly_snapshots_with_12_month_activity_window() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="gamma", display_name="Gamma", source_ids=[]),
                Player(id=4, canonical_slug="delta", display_name="Delta", source_ids=[]),
            ]
        )
        session.flush()

        early_event = Event(
            source="liquipedia",
            source_event_id="early-event",
            name="Early Event",
            end_date=date(2024, 1, 15),
        )
        late_event = Event(
            source="liquipedia",
            source_event_id="late-event",
            name="Late Event",
            end_date=date(2025, 3, 15),
        )
        session.add_all([early_event, late_event])
        session.flush()

        early_winner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        early_runner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        late_winner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="gamma", display_name="Gamma", player_id=3)
        late_runner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="delta", display_name="Delta", player_id=4)
        session.add_all([early_winner, early_runner, late_winner, late_runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=early_event.id, competitor_id=early_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=early_event.id, competitor_id=early_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_activity_window_months": 12}),
        )
        rows = service.compute_goat_rankings()
        assert len(rows) == 4


def test_major_events_drive_title_points_by_placement_band() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="p1", display_name="P1", source_ids=[]),
                Player(id=2, canonical_slug="p2", display_name="P2", source_ids=[]),
                Player(id=3, canonical_slug="p3", display_name="P3", source_ids=[]),
                Player(id=4, canonical_slug="p4", display_name="P4", source_ids=[]),
                Player(id=5, canonical_slug="p5", display_name="P5", source_ids=[]),
                Player(id=6, canonical_slug="p6", display_name="P6", source_ids=[]),
            ]
        )
        session.flush()

        major_event = Event(
            source="liquipedia",
            source_event_id="major-event",
            page_name="Major/Page",
            name="Major Event",
            end_date=date(2024, 1, 15),
        )
        regular_event = Event(
            source="liquipedia",
            source_event_id="regular-event",
            page_name="Regular/Page",
            name="Regular Event",
            end_date=date(2024, 2, 15),
        )
        session.add_all([major_event, regular_event])
        session.flush()

        major_competitors = []
        regular_competitors = []
        for player_id in range(1, 7):
            slug = f"p{player_id}"
            display_name = f"P{player_id}"
            major_competitors.append(
                EventCompetitor(
                    event_id=major_event.id,
                    competitor_type="player",
                    canonical_slug=slug,
                    display_name=display_name,
                    player_id=player_id,
                )
            )
            regular_competitors.append(
                EventCompetitor(
                    event_id=regular_event.id,
                    competitor_type="player",
                    canonical_slug=slug,
                    display_name=display_name,
                    player_id=player_id,
                )
            )
        session.add_all(major_competitors + regular_competitors)
        session.flush()

        major_places = [1, 2, 3, 4, 5, 6]
        regular_places = [6, 5, 4, 3, 2, 1]
        session.add_all(
            [
                EventResult(
                    event_id=major_event.id,
                    competitor_id=competitor.id,
                    placement_low=place,
                    placement_high=place,
                    placement_text=str(place),
                    raw_payload={},
                )
                for competitor, place in zip(major_competitors, major_places, strict=True)
            ]
            + [
                EventResult(
                    event_id=regular_event.id,
                    competitor_id=competitor.id,
                    placement_low=place,
                    placement_high=place,
                    placement_text=str(place),
                    raw_payload={},
                )
                for competitor, place in zip(regular_competitors, regular_places, strict=True)
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_weights": {"title_points": 1.0}}),
            MajorEventsConfig.model_validate({"rules": [{"name": "Major", "match": {"page_name": "Major/Page"}}]}),
        )
        rows = service.compute_goat_rankings()
        by_slug = {row.player_slug: row for row in rows}

        assert by_slug["p1"].title_points == 10.0
        assert by_slug["p2"].title_points == 4.0
        assert by_slug["p3"].title_points == 3.0
        assert by_slug["p4"].title_points == 2.0
        assert by_slug["p5"].title_points == 1.0
        assert by_slug["p6"].title_points == 1.0


def test_rating_leader_timeline_groups_consecutive_month_reigns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="gamma", display_name="Gamma", source_ids=[]),
                Player(id=4, canonical_slug="delta", display_name="Delta", source_ids=[]),
            ]
        )
        session.flush()

        early_event = Event(
            source="liquipedia",
            source_event_id="early-event",
            name="Early Event",
            end_date=date(2024, 1, 15),
        )
        late_event = Event(
            source="liquipedia",
            source_event_id="late-event",
            name="Late Event",
            end_date=date(2025, 3, 15),
        )
        session.add_all([early_event, late_event])
        session.flush()

        early_winner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        early_runner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        late_winner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="gamma", display_name="Gamma", player_id=3)
        late_runner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="delta", display_name="Delta", player_id=4)
        session.add_all([early_winner, early_runner, late_winner, late_runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=early_event.id, competitor_id=early_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=early_event.id, competitor_id=early_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_activity_window_months": 12}),
        )
        rows = service.compute_rating_leader_timeline()
        assert rows[0].player_slug == "alpha"
        assert rows[0].start_month == "2024-01"
        assert rows[0].end_month == "2025-01"
        assert rows[0].months == 13
        assert rows[1].player_slug == "gamma"
        assert rows[1].start_month == "2025-03"
        assert rows[1].end_month == "2025-03"
        assert rows[1].months == 1


def test_rating_leader_timeline_raw_lists_each_month_leader() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="gamma", display_name="Gamma", source_ids=[]),
                Player(id=4, canonical_slug="delta", display_name="Delta", source_ids=[]),
            ]
        )
        session.flush()

        early_event = Event(
            source="liquipedia",
            source_event_id="early-event",
            name="Early Event",
            end_date=date(2024, 1, 15),
        )
        late_event = Event(
            source="liquipedia",
            source_event_id="late-event",
            name="Late Event",
            end_date=date(2025, 3, 15),
        )
        session.add_all([early_event, late_event])
        session.flush()

        early_winner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        early_runner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        late_winner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="gamma", display_name="Gamma", player_id=3)
        late_runner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="delta", display_name="Delta", player_id=4)
        session.add_all([early_winner, early_runner, late_winner, late_runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=early_event.id, competitor_id=early_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=early_event.id, competitor_id=early_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_activity_window_months": 12}),
        )
        rows = service.compute_rating_leader_timeline_raw()
        assert rows[0].month == "2024-01"
        assert rows[0].player_slug == "alpha"
        assert rows[12].month == "2025-01"
        assert rows[12].player_slug == "alpha"
        assert rows[13].month == "2025-03"
        assert rows[13].player_slug == "gamma"


def test_active_players_by_month_uses_goat_activity_window() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="gamma", display_name="Gamma", source_ids=[]),
                Player(id=4, canonical_slug="delta", display_name="Delta", source_ids=[]),
            ]
        )
        session.flush()

        early_event = Event(
            source="liquipedia",
            source_event_id="early-event",
            name="Early Event",
            end_date=date(2024, 1, 15),
        )
        late_event = Event(
            source="liquipedia",
            source_event_id="late-event",
            name="Late Event",
            end_date=date(2024, 4, 15),
        )
        session.add_all([early_event, late_event])
        session.flush()

        early_winner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        early_runner = EventCompetitor(event_id=early_event.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        late_winner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="gamma", display_name="Gamma", player_id=3)
        late_runner = EventCompetitor(event_id=late_event.id, competitor_type="player", canonical_slug="delta", display_name="Delta", player_id=4)
        session.add_all([early_winner, early_runner, late_winner, late_runner])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=early_event.id, competitor_id=early_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=early_event.id, competitor_id=early_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_winner.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=late_event.id, competitor_id=late_runner.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_activity_window_months": 12}),
        )
        rows = service.compute_active_players_by_month()
        by_month = {row.month: row.active_players for row in rows}
        assert by_month["2024-01"] == 2
        assert by_month["2024-03"] == 2
        assert by_month["2024-04"] == 4
        assert rows[0].top10_conservative_cutoff is None
        assert rows[0].p95_conservative is not None
        assert rows[0].p99_conservative is not None


def test_tournament_strength_uses_pre_event_ratings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="gamma", display_name="Gamma", source_ids=[]),
                Player(id=4, canonical_slug="delta", display_name="Delta", source_ids=[]),
            ]
        )
        session.flush()

        opener = Event(
            source="liquipedia",
            source_event_id="opener",
            name="Opener",
            end_date=date(2024, 1, 15),
        )
        followup = Event(
            source="liquipedia",
            source_event_id="followup",
            name="Followup",
            end_date=date(2024, 2, 15),
        )
        session.add_all([opener, followup])
        session.flush()

        opener_alpha = EventCompetitor(event_id=opener.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        opener_beta = EventCompetitor(event_id=opener.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        followup_alpha = EventCompetitor(event_id=followup.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        followup_beta = EventCompetitor(event_id=followup.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        followup_gamma = EventCompetitor(event_id=followup.id, competitor_type="player", canonical_slug="gamma", display_name="Gamma", player_id=3)
        followup_delta = EventCompetitor(event_id=followup.id, competitor_type="player", canonical_slug="delta", display_name="Delta", player_id=4)
        session.add_all([opener_alpha, opener_beta, followup_alpha, followup_beta, followup_gamma, followup_delta])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=opener.id, competitor_id=opener_alpha.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=opener.id, competitor_id=opener_beta.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=followup.id, competitor_id=followup_alpha.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=followup.id, competitor_id=followup_beta.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=followup.id, competitor_id=followup_gamma.id, placement_low=3, placement_high=3, placement_text="3", raw_payload={}),
                EventResult(event_id=followup.id, competitor_id=followup_delta.id, placement_low=4, placement_high=4, placement_text="4", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile(),
        )
        rows = service.compute_tournament_strengths(2024, limit=2, cap=2)

        assert rows[0].source_event_id == "followup"
        assert rows[0].strength > rows[1].strength
        assert rows[0].rated_strength_cap == 2

        all_year_rows = service.compute_tournament_strengths(limit=1, cap=2)
        assert [row.source_event_id for row in all_year_rows] == ["followup"]
        assert all_year_rows[0].rank == 1


def test_rating_leader_timeline_raw_carries_across_skipped_events() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="alpha", display_name="Alpha", source_ids=[]),
                Player(id=2, canonical_slug="beta", display_name="Beta", source_ids=[]),
                Player(id=3, canonical_slug="placeholder", display_name="Placeholder", source_ids=[]),
            ]
        )
        session.flush()

        good_early = Event(
            source="liquipedia",
            source_event_id="good-early",
            name="Good Early",
            end_date=date(2024, 10, 15),
        )
        skipped_middle = Event(
            source="liquipedia",
            source_event_id="skipped-middle",
            name="Skipped Middle",
            end_date=date(2025, 1, 15),
        )
        good_late = Event(
            source="liquipedia",
            source_event_id="good-late",
            name="Good Late",
            end_date=date(2025, 3, 15),
        )
        session.add_all([good_early, skipped_middle, good_late])
        session.flush()

        early_alpha = EventCompetitor(event_id=good_early.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        early_beta = EventCompetitor(event_id=good_early.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        middle_only = EventCompetitor(event_id=skipped_middle.id, competitor_type="player", canonical_slug="placeholder", display_name="Placeholder", player_id=3)
        late_alpha = EventCompetitor(event_id=good_late.id, competitor_type="player", canonical_slug="alpha", display_name="Alpha", player_id=1)
        late_beta = EventCompetitor(event_id=good_late.id, competitor_type="player", canonical_slug="beta", display_name="Beta", player_id=2)
        session.add_all([early_alpha, early_beta, middle_only, late_alpha, late_beta])
        session.flush()

        session.add_all(
            [
                EventResult(event_id=good_early.id, competitor_id=early_alpha.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=good_early.id, competitor_id=early_beta.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                EventResult(event_id=skipped_middle.id, competitor_id=middle_only.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=good_late.id, competitor_id=late_alpha.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=good_late.id, competitor_id=late_beta.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate({"goat_activity_window_months": 12}),
        )
        rows = service.compute_rating_leader_timeline_raw()
        months = [row.month for row in rows]
        assert "2024-11" in months
        assert "2024-12" in months
        assert "2025-01" in months
        assert "2025-02" in months


def test_current_rankings_apply_profile_eligibility_filters() -> None:
    today = date.today()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(id=1, canonical_slug="eligible-a", display_name="Eligible A", source_ids=[]),
                Player(id=2, canonical_slug="eligible-b", display_name="Eligible B", source_ids=[]),
                Player(id=3, canonical_slug="few-events-a", display_name="Few Events A", source_ids=[]),
                Player(id=4, canonical_slug="few-events-b", display_name="Few Events B", source_ids=[]),
                Player(id=5, canonical_slug="stale-a", display_name="Stale A", source_ids=[]),
                Player(id=6, canonical_slug="stale-b", display_name="Stale B", source_ids=[]),
            ]
        )
        session.flush()

        recent_dates = [date(2025, month, 1) for month in range(1, 6)]
        stale_dates = [date(2023, month, 1) for month in range(1, 6)]
        events = []
        for idx, event_date in enumerate(recent_dates, start=1):
            events.append(
                Event(
                    source="liquipedia",
                    source_event_id=f"recent-{idx}",
                    name=f"Recent {idx}",
                    end_date=event_date,
                )
            )
        for idx, event_date in enumerate(stale_dates, start=1):
            events.append(
                Event(
                    source="liquipedia",
                    source_event_id=f"stale-{idx}",
                    name=f"Stale {idx}",
                    end_date=event_date,
                )
            )
        few_event = Event(
            source="liquipedia",
            source_event_id="few-only",
            name="Few Only",
            end_date=today,
        )
        events.append(few_event)
        session.add_all(events)
        session.flush()

        for event in events[:5]:
            competitor_a = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="eligible-a", display_name="Eligible A", player_id=1)
            competitor_b = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="eligible-b", display_name="Eligible B", player_id=2)
            session.add_all([competitor_a, competitor_b])
            session.flush()
            session.add_all(
                [
                    EventResult(event_id=event.id, competitor_id=competitor_a.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                    EventResult(event_id=event.id, competitor_id=competitor_b.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                ]
            )

        for event in events[5:10]:
            competitor_a = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="stale-a", display_name="Stale A", player_id=5)
            competitor_b = EventCompetitor(event_id=event.id, competitor_type="player", canonical_slug="stale-b", display_name="Stale B", player_id=6)
            session.add_all([competitor_a, competitor_b])
            session.flush()
            session.add_all(
                [
                    EventResult(event_id=event.id, competitor_id=competitor_a.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                    EventResult(event_id=event.id, competitor_id=competitor_b.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
                ]
            )

        competitor_a = EventCompetitor(event_id=few_event.id, competitor_type="player", canonical_slug="few-events-a", display_name="Few Events A", player_id=3)
        competitor_b = EventCompetitor(event_id=few_event.id, competitor_type="player", canonical_slug="few-events-b", display_name="Few Events B", player_id=4)
        session.add_all([competitor_a, competitor_b])
        session.flush()
        session.add_all(
            [
                EventResult(event_id=few_event.id, competitor_id=competitor_a.id, placement_low=1, placement_high=1, placement_text="1", raw_payload={}),
                EventResult(event_id=few_event.id, competitor_id=competitor_b.id, placement_low=2, placement_high=2, placement_text="2", raw_payload={}),
            ]
        )
        session.commit()

        service = RatingsService(
            session,
            TournamentRulesConfig.model_validate({"defaults": {"include": True, "weight": 1.0, "tags": []}, "rules": []}),
            RatingProfile.model_validate(
                {
                    "current_eligibility": {
                        "min_events_played": 5,
                        "max_months_since_last_event": 24,
                    }
                }
            ),
        )
        rows = service.compute_current_rankings()
        assert [row.player_slug for row in rows] == ["eligible-a", "eligible-b"]
