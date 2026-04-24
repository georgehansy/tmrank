from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import trueskill
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmrank.config_models import MajorEventsConfig, RatingProfile, TournamentRulesConfig
from tmrank.app_context import profile_label
from tmrank.db.models import Event, EventCompetitor, EventResult, Player, TeamMembership
from tmrank.domain import (
    ActivePlayersMonthRow,
    GoatRow,
    MajorPodiumResult,
    RatingLeaderTimelineMonthRow,
    RatingLeaderTimelineRow,
    RatingRow,
    TitleLeaderRow,
    TournamentStrengthRow,
)
from tmrank.services.curation import EventView, MajorEventSelector, TournamentCurator
from tmrank.utils import ensure_dir


@dataclass(slots=True)
class PlayerState:
    slug: str
    name: str
    mu: float
    sigma: float
    events_played: int = 0
    first_event_date: date | None = None
    last_event_date: date | None = None
    title_points: float = 0.0
    major_podium_results: list[MajorPodiumResult] = field(default_factory=list)
    world_cup_results: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class RatedEvent:
    event: Event
    weight: float
    event_date: date
    competitors: list[dict]
    field_size: int
    effective_field_size: int
    is_major: bool
    major_rule_names: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class RatingsService:
    def __init__(
        self,
        session: Session,
        rules: TournamentRulesConfig,
        profile: RatingProfile,
        majors: MajorEventsConfig | None = None,
    ):
        self.session = session
        self.curator = TournamentCurator(rules)
        major_config = majors or MajorEventsConfig()
        self.major_selector = MajorEventSelector(major_config.rules)
        self.major_placement_points = major_config.placement_points
        self.profile = profile
        self.environment = trueskill.TrueSkill(
            mu=profile.initial_mu,
            sigma=profile.initial_sigma,
            backend="mpmath",
        )

    def compute_current_rankings(self) -> list[RatingRow]:
        rated_events = self._load_rated_events()
        state = self._build_state(rated_events=rated_events)
        return self._current_rankings_from_state(state, rated_events)

    def _current_rankings_from_state(
        self,
        state: dict[str, PlayerState],
        rated_events: list[RatedEvent],
    ) -> list[RatingRow]:
        today = date.today()
        recent_event_counts = self._count_recent_events(rated_events, today=today, window_months=24)
        rows = [
            RatingRow(
                rank=0,
                player_slug=player.slug,
                player_name=player.name,
                mu=round(player.mu, 4),
                sigma=round(
                    _inflate_sigma(
                        player.sigma,
                        player.last_event_date,
                        today,
                        self.profile.initial_sigma,
                        self.profile.monthly_inactivity_drift,
                    ),
                    4,
                ),
                conservative_score=round(
                    player.mu
                    - self.profile.conservative_multiplier
                    * _inflate_sigma(
                        player.sigma,
                        player.last_event_date,
                        today,
                        self.profile.initial_sigma,
                        self.profile.monthly_inactivity_drift,
                    ),
                    4,
                ),
                events_played=player.events_played,
                recent_events_24_months=recent_event_counts.get(player.slug, 0),
                last_event_date=player.last_event_date,
            )
            for player in state.values()
            if self._is_currently_eligible(player, today)
        ]
        rows.sort(key=lambda row: (-row.conservative_score, -row.mu, row.player_name.casefold()))
        for index, row in enumerate(rows, start=1):
            row.rank = index
        return rows

    def compute_goat_rankings(self, *, sqrt_metrics: set[str] | None = None) -> list[GoatRow]:
        state, metrics, active_month_counts = self._compute_goat_metrics()
        return self._goat_rankings_from_metrics(
            state,
            metrics,
            active_month_counts,
            sqrt_metrics=sqrt_metrics,
        )

    def _goat_rankings_from_metrics(
        self,
        state: dict[str, PlayerState],
        metrics: dict[str, dict[str, float]],
        active_month_counts: dict[str, int],
        *,
        sqrt_metrics: set[str] | None = None,
    ) -> list[GoatRow]:
        if not state:
            return []
        state, metrics, active_month_counts = self._filter_goat_pool(state, metrics, active_month_counts)
        if not state:
            return []
        normalized = _normalize_goat_metrics(metrics, sqrt_metrics=sqrt_metrics)
        weights = self.profile.goat_weights
        rows: list[GoatRow] = []
        for slug, player in state.items():
            goat_score = (
                normalized["prime_rating"][slug] * weights.prime_rating
                + normalized["elite_area"][slug] * weights.elite_area
                + normalized["median_conservative"][slug] * weights.median_conservative
                + normalized["title_points"][slug] * weights.title_points
            )
            rows.append(
                GoatRow(
                    rank=0,
                    player_slug=slug,
                    player_name=player.name,
                    goat_score=round(goat_score, 6),
                    prime_rating=round(metrics["prime_rating"][slug], 4),
                    elite_area=round(metrics["elite_area"][slug], 4),
                    median_conservative=round(metrics["median_conservative"][slug], 4),
                    title_points=round(metrics["title_points"][slug], 4),
                    norm_prime_rating=round(normalized["prime_rating"][slug], 6),
                    norm_elite_area=round(normalized["elite_area"][slug], 6),
                    norm_median_conservative=round(normalized["median_conservative"][slug], 6),
                    norm_title_points=round(normalized["title_points"][slug], 6),
                    active_months=active_month_counts[slug],
                    events_played=player.events_played,
                )
            )
        rows.sort(key=lambda row: (-row.goat_score, -row.prime_rating, row.player_name.casefold()))
        for index, row in enumerate(rows, start=1):
            row.rank = index
        return rows

    def compute_goat_metric_summary(self) -> dict[str, dict[str, float | int]]:
        state, metrics, active_month_counts = self._compute_goat_metrics()
        state, metrics, active_month_counts = self._filter_goat_pool(state, metrics, active_month_counts)
        summary: dict[str, dict[str, float | int]] = {}
        for metric_name, metric_values in metrics.items():
            values = list(metric_values.values())
            if not values:
                summary[metric_name] = {
                    "count": 0,
                    "min": 0.0,
                    "p1": 0.0,
                    "p10": 0.0,
                    "median": 0.0,
                    "p90": 0.0,
                    "p99": 0.0,
                    "max": 0.0,
                }
                continue
            sorted_values = sorted(values)
            summary[metric_name] = {
                "count": len(values),
                "min": round(sorted_values[0], 4),
                "p1": round(_percentile(sorted_values, 1), 4),
                "p10": round(_percentile(sorted_values, 10), 4),
                "median": round(float(statistics.median(values)), 4),
                "p90": round(_percentile(sorted_values, 90), 4),
                "p99": round(_percentile(sorted_values, 99), 4),
                "max": round(sorted_values[-1], 4),
            }
        return summary

    def compute_rating_leader_timeline(self) -> list[RatingLeaderTimelineRow]:
        state, snapshots = self._build_state(return_snapshots=True)
        return self._rating_leader_timeline_from_state(state, snapshots)

    def _rating_leader_timeline_from_state(
        self,
        state: dict[str, PlayerState],
        snapshots: list[tuple[str, dict[str, dict[str, float | date | None]]]],
    ) -> list[RatingLeaderTimelineRow]:
        if not state:
            return []
        player_months: dict[str, list[tuple[str, float]]] = {slug: [] for slug in state}
        player_names = {slug: player.name for slug, player in state.items()}
        leaders = self._compute_rating_leader_month_leaders(snapshots, player_months, player_names)
        if not leaders:
            return []
        grouped: list[RatingLeaderTimelineRow] = []
        current_start = leaders[0]["month"]
        current_end = leaders[0]["month"]
        current_slug = leaders[0]["player_slug"]
        current_name = leaders[0]["player_name"]
        current_peak = leaders[0]["conservative"]
        current_months = 1

        for leader in leaders[1:]:
            if leader["player_slug"] == current_slug and leader["month"] == _next_month_key(current_end):
                current_end = leader["month"]
                current_months += 1
                current_peak = max(current_peak, leader["conservative"])
                continue
            grouped.append(
                RatingLeaderTimelineRow(
                    start_month=current_start,
                    end_month=current_end,
                    player_slug=current_slug,
                    player_name=current_name,
                    months=current_months,
                    peak_conservative=round(current_peak, 4),
                )
            )
            current_start = leader["month"]
            current_end = leader["month"]
            current_slug = leader["player_slug"]
            current_name = leader["player_name"]
            current_peak = leader["conservative"]
            current_months = 1

        grouped.append(
            RatingLeaderTimelineRow(
                start_month=current_start,
                end_month=current_end,
                player_slug=current_slug,
                player_name=current_name,
                months=current_months,
                peak_conservative=round(current_peak, 4),
            )
        )
        return grouped

    def compute_rating_leader_timeline_raw(self) -> list[RatingLeaderTimelineMonthRow]:
        state, snapshots = self._build_state(return_snapshots=True)
        if not state:
            return []
        player_months: dict[str, list[tuple[str, float]]] = {slug: [] for slug in state}
        player_names = {slug: player.name for slug, player in state.items()}
        leaders = self._compute_rating_leader_month_leaders(snapshots, player_months, player_names)
        return [
            RatingLeaderTimelineMonthRow(
                month=str(leader["month"]),
                player_slug=str(leader["player_slug"]),
                player_name=str(leader["player_name"]),
                conservative=round(float(leader["conservative"]), 4),
            )
            for leader in leaders
        ]

    def compute_active_players_by_month(self) -> list[ActivePlayersMonthRow]:
        _, snapshots = self._build_state(return_snapshots=True)
        rows: list[ActivePlayersMonthRow] = []
        for snapshot_month, month_state in snapshots:
            active_scores: list[float] = []
            for values in month_state.values():
                last_event_date = values["last_event_date"]
                if last_event_date is None:
                    continue
                months_since_last = _month_delta(_month_key(last_event_date), snapshot_month)
                if months_since_last <= self.profile.goat_activity_window_months:
                    active_scores.append(float(values["conservative"]))
            active_scores.sort(reverse=True)
            top10_cutoff = active_scores[9] if len(active_scores) >= 10 else None
            sorted_scores = sorted(active_scores)
            p95 = _percentile(sorted_scores, 95) if sorted_scores else None
            p99 = _percentile(sorted_scores, 99) if sorted_scores else None
            rows.append(
                ActivePlayersMonthRow(
                    month=snapshot_month,
                    active_players=len(active_scores),
                    top10_conservative_cutoff=round(top10_cutoff, 4) if top10_cutoff is not None else None,
                    p95_conservative=round(p95, 4) if p95 is not None else None,
                    p99_conservative=round(p99, 4) if p99 is not None else None,
                )
            )
        return rows

    def compute_tournament_strengths(self, year: int | None = None, *, limit: int = 5, cap: int = 16) -> list[TournamentStrengthRow]:
        rated_events = self._load_rated_events()
        player_states: dict[str, PlayerState] = {}
        rows: list[TournamentStrengthRow] = []

        for rated_event in rated_events:
            competitor_strengths: list[float] = []
            for competitor in rated_event.competitors:
                player_scores: list[float] = []
                for player in competitor["players"]:
                    state = player_states.get(player["slug"])
                    if state is None:
                        mu = self.profile.initial_mu
                        sigma = self.profile.initial_sigma
                    else:
                        mu = state.mu
                        sigma = _inflate_sigma(
                            state.sigma,
                            state.last_event_date,
                            rated_event.event_date,
                            self.profile.initial_sigma,
                            self.profile.monthly_inactivity_drift,
                        )
                    player_scores.append(mu - self.profile.conservative_multiplier * sigma)
                if player_scores:
                    competitor_strengths.append(float(statistics.mean(player_scores)))

            if (year is None or rated_event.event_date.year == year) and competitor_strengths:
                strongest = sorted(competitor_strengths, reverse=True)[:cap]
                rows.append(
                    TournamentStrengthRow(
                        rank=0,
                        source_event_id=rated_event.event.source_event_id,
                        event_name=rated_event.event.name,
                        event_date=rated_event.event_date,
                        series=rated_event.event.series,
                        field_size=rated_event.field_size,
                        effective_field_size=rated_event.effective_field_size,
                        rated_strength_cap=len(strongest),
                        strength=round(float(statistics.mean(strongest)), 4),
                    )
                )

            self._apply_rated_event(player_states, rated_event)

        if year is not None:
            rows.sort(key=lambda row: (-row.strength, row.event_date, row.event_name.casefold()))
            rows = rows[:limit]
            for index, row in enumerate(rows, start=1):
                row.rank = index
            return rows

        rows_by_year: dict[int, list[TournamentStrengthRow]] = {}
        for row in rows:
            rows_by_year.setdefault(row.event_date.year, []).append(row)

        grouped_rows: list[TournamentStrengthRow] = []
        for event_year in sorted(rows_by_year):
            year_rows = rows_by_year[event_year]
            year_rows.sort(key=lambda row: (-row.strength, row.event_date, row.event_name.casefold()))
            for index, row in enumerate(year_rows[:limit], start=1):
                row.rank = index
                grouped_rows.append(row)
        return grouped_rows

    def _compute_goat_metrics(self) -> tuple[dict[str, PlayerState], dict[str, dict[str, float]], dict[str, int]]:
        state, snapshots = self._build_state(return_snapshots=True)
        return self._compute_goat_metrics_from_state(state, snapshots)

    def _compute_goat_metrics_from_state(
        self,
        state: dict[str, PlayerState],
        snapshots: list[tuple[str, dict[str, dict[str, float | date | None]]]],
    ) -> tuple[dict[str, PlayerState], dict[str, dict[str, float]], dict[str, int]]:
        if not state:
            return {}, {}, {}
        player_months: dict[str, list[tuple[str, float]]] = {slug: [] for slug in state}
        player_names = {slug: player.name for slug, player in state.items()}
        self._compute_rating_leader_month_rankings(snapshots, player_months, player_names)

        metrics = {
            "prime_rating": {
                slug: _best_rolling_average(
                    scores,
                    window_months=self.profile.goat_prime_window_months,
                    min_active_months=self.profile.goat_prime_min_active_months,
                )
                for slug, scores in player_months.items()
            },
            "elite_area": {
                slug: sum(max(0.0, score - self.profile.goat_elite_threshold) for _, score in scores)
                for slug, scores in player_months.items()
            },
            "median_conservative": {
                slug: float(statistics.median(score for _, score in scores)) if scores else 0.0
                for slug, scores in player_months.items()
            },
            "title_points": {
                slug: player.title_points
                for slug, player in state.items()
            },
        }
        active_month_counts = {
            slug: len(scores)
            for slug, scores in player_months.items()
        }
        return state, metrics, active_month_counts

    def export_rankings(self, output_dir: str | Path = "artifacts") -> dict[str, Path]:
        output_root = ensure_dir(Path(output_dir))
        current_rows = self.compute_current_rankings()
        goat_rows = self.compute_goat_rankings()
        outputs = {
            "current_csv": output_root / "current_rankings.csv",
            "current_json": output_root / "current_rankings.json",
            "goat_csv": output_root / "goat_rankings.csv",
            "goat_json": output_root / "goat_rankings.json",
        }
        _write_csv(outputs["current_csv"], current_rows)
        _write_json(outputs["current_json"], current_rows)
        _write_csv(outputs["goat_csv"], goat_rows)
        _write_json(outputs["goat_json"], goat_rows)
        return outputs

    def build_site_payload(self, profile_name: str, *, generated_at: datetime | None = None) -> dict[str, Any]:
        generated_at = generated_at or datetime.now(timezone.utc)
        rated_events = self._load_rated_events()
        state, snapshots = self._build_state(return_snapshots=True, rated_events=rated_events)
        goat_state, goat_metrics, goat_active_month_counts = self._compute_goat_metrics_from_state(state, snapshots)
        goat_rows = self._goat_rankings_from_metrics(goat_state, goat_metrics, goat_active_month_counts)
        current_rows = self._current_rankings_from_state(state, rated_events)
        timeline_rows = self._rating_leader_timeline_from_state(state, snapshots)

        title_leaders = sorted(
            goat_rows,
            key=lambda row: (-row.title_points, -row.goat_score, row.player_name.casefold()),
        )[:10]
        title_leader_rows: list[TitleLeaderRow] = []
        for index, row in enumerate(title_leaders, start=1):
            player_state = state.get(row.player_slug)
            title_leader_rows.append(
                TitleLeaderRow(
                    rank=index,
                    player_slug=row.player_slug,
                    player_name=row.player_name,
                    title_points=row.title_points,
                    events_played=row.events_played,
                    major_podium_results=self._sorted_major_podium_results(
                        player_state.major_podium_results if player_state else []
                    ),
                )
            )

        return {
            "profile": {
                "name": profile_name,
                "label": profile_label(profile_name),
            },
            "generated_at": generated_at.isoformat(),
            "goat_top20": [
                {
                    "rank": row.rank,
                    "player_slug": row.player_slug,
                    "player_name": row.player_name,
                    "goat_score": row.goat_score,
                    "prime_rating": row.prime_rating,
                    "elite_area": row.elite_area,
                    "median_conservative": row.median_conservative,
                    "title_points": row.title_points,
                    "active_months": row.active_months,
                    "events_played": row.events_played,
                    "first_event_date": state[row.player_slug].first_event_date.isoformat()
                    if state[row.player_slug].first_event_date
                    else None,
                    "last_event_date": state[row.player_slug].last_event_date.isoformat()
                    if state[row.player_slug].last_event_date
                    else None,
                    "best_world_cup_result": self._site_best_world_cup_result_payload(row.player_slug, state),
                    "major_podium_results": self._site_major_podium_payload(row.player_slug, state),
                }
                for row in goat_rows[:20]
            ],
            "current_top10": [
                {
                    "rank": row.rank,
                    "player_slug": row.player_slug,
                    "player_name": row.player_name,
                    "conservative_score": row.conservative_score,
                    "mu": row.mu,
                    "sigma": row.sigma,
                    "events_played": row.events_played,
                    "recent_events_24_months": row.recent_events_24_months,
                    "last_event_date": row.last_event_date,
                }
                for row in current_rows[:10]
            ],
            "rating_leader_timeline": [
                {
                    "start_month": row.start_month,
                    "end_month": row.end_month,
                    "player_slug": row.player_slug,
                    "player_name": row.player_name,
                    "months": row.months,
                    "peak_conservative": row.peak_conservative,
                }
                for row in timeline_rows
            ],
            "title_leaders_top10": [
                {
                    "rank": row.rank,
                    "player_slug": row.player_slug,
                    "player_name": row.player_name,
                    "title_points": row.title_points,
                    "events_played": row.events_played,
                    "major_podium_results": self._site_major_podium_payload(row.player_slug, state),
                }
                for row in title_leader_rows
            ],
        }

    def _build_state(self, *, return_snapshots: bool = False, rated_events: list[RatedEvent] | None = None):
        player_states: dict[str, PlayerState] = {}
        snapshots: list[tuple[str, dict[str, dict[str, float | date | None]]]] = []
        rated_events = rated_events if rated_events is not None else self._load_rated_events()

        for index, rated_event in enumerate(rated_events):
            self._apply_rated_event(player_states, rated_event)

            current_month = _month_key(rated_event.event_date)
            next_month = None
            if index + 1 < len(rated_events):
                next_month = _month_key(rated_events[index + 1].event_date)
            if return_snapshots and current_month != next_month:
                snapshot_month = current_month
                while True:
                    snapshots.append(
                        (
                            snapshot_month,
                            {
                                slug: {
                                    "conservative": state.mu - self.profile.conservative_multiplier * state.sigma,
                                    "mu": state.mu,
                                    "sigma": state.sigma,
                                    "last_event_date": state.last_event_date,
                                }
                                for slug, state in player_states.items()
                            },
                        )
                    )
                    if next_month is None:
                        break
                    snapshot_month = _next_month_key(snapshot_month)
                    if snapshot_month == next_month:
                        break
        return (player_states, snapshots) if return_snapshots else player_states

    def _load_rated_events(self) -> list[RatedEvent]:
        events = list(self.session.scalars(select(Event).order_by(Event.end_date.asc().nulls_last(), Event.source_event_id.asc())))
        rated_events: list[RatedEvent] = []
        today = date.today()
        for event in events:
            effective_date = event.end_date or event.sort_date or event.start_date
            if effective_date is None or effective_date > today:
                continue
            event_view = EventView(
                source_event_id=event.source_event_id,
                page_id=event.page_id,
                tier=event.tier,
                page_name=event.page_name,
                name=event.name,
                series=event.series,
                mode=event.mode,
                event_type=event.event_type,
                start_date=event.start_date,
                end_date=event.end_date,
            )
            curated = self.curator.evaluate(event_view)
            if not curated.include:
                continue
            major_rule_names = self.major_selector.matched_rule_names(event_view)
            competitors = self._load_event_competitors(event.id)
            field_size = len(competitors)
            effective_field_size = self._effective_field_size(field_size)
            competitors = competitors[:effective_field_size]
            if len(competitors) < 2:
                continue
            rated_events.append(
                RatedEvent(
                    event=event,
                    weight=curated.weight * self._field_size_weight_factor(effective_field_size),
                    event_date=effective_date,
                    competitors=competitors,
                    field_size=field_size,
                    effective_field_size=effective_field_size,
                    is_major=bool(major_rule_names),
                    major_rule_names=major_rule_names,
                    tags=list(curated.tags),
                )
            )
        return rated_events

    def _count_recent_events(self, rated_events: list[RatedEvent], *, today: date, window_months: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rated_event in rated_events:
            months_ago = max(
                0,
                (today.year - rated_event.event_date.year) * 12 + (today.month - rated_event.event_date.month),
            )
            if months_ago > window_months:
                continue
            seen_in_event: set[str] = set()
            for competitor in rated_event.competitors:
                for player in competitor["players"]:
                    slug = player["slug"]
                    if slug in seen_in_event:
                        continue
                    seen_in_event.add(slug)
                    counts[slug] = counts.get(slug, 0) + 1
        return counts

    def _apply_rated_event(self, player_states: dict[str, PlayerState], rated_event: RatedEvent) -> None:
        teams = []
        ranks = []
        affected_players: dict[str, tuple[float, float]] = {}
        for competitor in rated_event.competitors:
            team_ratings = []
            for player in competitor["players"]:
                state = player_states.setdefault(
                    player["slug"],
                    PlayerState(
                        slug=player["slug"],
                        name=player["name"],
                        mu=self.profile.initial_mu,
                        sigma=self.profile.initial_sigma,
                    ),
                )
                state.name = player["name"]
                inflated_sigma = _inflate_sigma(
                    state.sigma,
                    state.last_event_date,
                    rated_event.event_date,
                    self.profile.initial_sigma,
                    self.profile.monthly_inactivity_drift,
                )
                team_ratings.append(trueskill.Rating(mu=state.mu, sigma=inflated_sigma))
                affected_players[player["slug"]] = (state.mu, inflated_sigma)
            teams.append(team_ratings)
            ranks.append(competitor["rank"])

        new_ratings = self.environment.rate(teams, ranks=ranks)
        for competitor, rated_team in zip(rated_event.competitors, new_ratings, strict=True):
            for player, new_rating in zip(competitor["players"], rated_team, strict=True):
                state = player_states[player["slug"]]
                old_mu, old_sigma = affected_players[player["slug"]]
                state.mu = old_mu + rated_event.weight * (new_rating.mu - old_mu)
                state.sigma = old_sigma + rated_event.weight * (new_rating.sigma - old_sigma)
                state.events_played += 1
                state.first_event_date = state.first_event_date or rated_event.event_date
                state.last_event_date = rated_event.event_date
                if "world-cup" in rated_event.tags:
                    state.world_cup_results.append(
                        (competitor["placement_low"], competitor["placement_high"])
                    )
            if rated_event.is_major:
                placement_points = self._major_points_for_placement(
                    competitor["placement_low"],
                    competitor["placement_high"],
                )
                if placement_points > 0:
                    is_podium = (
                        competitor["placement_low"] == competitor["placement_high"]
                        and competitor["placement_low"] in {1, 2, 3}
                    )
                    for player in competitor["players"]:
                        state = player_states[player["slug"]]
                        state.title_points += placement_points
                        if is_podium:
                            state.major_podium_results.append(
                                MajorPodiumResult(
                                    event_name=rated_event.event.name,
                                    page_name=rated_event.event.page_name,
                                    event_date=rated_event.event_date,
                                    placement=competitor["placement_low"],
                                    title_points=placement_points,
                                    is_world_cup="world-cup" in rated_event.tags,
                                )
                            )

    def _major_points_for_placement(self, placement_low: int, placement_high: int) -> float:
        for placement in self.major_placement_points:
            if placement_low >= placement.placement_low and placement_high <= placement.placement_high:
                return placement.points
        return 0.0

    def _load_event_competitors(self, event_id: int) -> list[dict]:
        results = list(
            self.session.execute(
                select(EventResult, EventCompetitor)
                .join(EventCompetitor, EventResult.competitor_id == EventCompetitor.id)
                .where(EventResult.event_id == event_id)
                .order_by(EventResult.placement_low.asc(), EventResult.placement_high.asc(), EventCompetitor.display_name.asc())
            )
        )
        competitor_rows: list[dict] = []
        for event_result, competitor in results:
            players: list[dict[str, str]] = []
            if competitor.competitor_type == "player":
                player = self.session.scalar(select(Player).where(Player.id == competitor.player_id))
                if player:
                    players.append({"slug": player.canonical_slug, "name": player.display_name})
            else:
                memberships = list(
                    self.session.scalars(
                        select(TeamMembership)
                        .where(TeamMembership.team_competitor_id == competitor.id)
                        .order_by(TeamMembership.id.asc())
                    )
                )
                for membership in memberships:
                    member_competitor = self.session.get(EventCompetitor, membership.player_competitor_id)
                    if member_competitor and member_competitor.player_id:
                        player = self.session.get(Player, member_competitor.player_id)
                        if player:
                            players.append({"slug": player.canonical_slug, "name": player.display_name})
            if players:
                competitor_rows.append(
                    {
                        "rank": event_result.placement_low,
                        "placement_low": event_result.placement_low,
                        "placement_high": event_result.placement_high,
                        "players": players,
                    }
                )
        return competitor_rows

    def _is_currently_eligible(self, player: PlayerState, today: date) -> bool:
        if player.events_played < self.profile.current_eligibility.min_events_played:
            return False
        max_months = self.profile.current_eligibility.max_months_since_last_event
        if max_months is None or player.last_event_date is None:
            return True
        months_since_last = max(
            0,
            (today.year - player.last_event_date.year) * 12 + (today.month - player.last_event_date.month),
        )
        return months_since_last <= max_months

    def _filter_goat_pool(
        self,
        state: dict[str, PlayerState],
        metrics: dict[str, dict[str, float]],
        active_month_counts: dict[str, int],
    ) -> tuple[dict[str, PlayerState], dict[str, dict[str, float]], dict[str, int]]:
        min_events = self.profile.goat_min_events_played
        if min_events <= 0:
            return state, metrics, active_month_counts

        eligible_slugs = {
            slug
            for slug, player in state.items()
            if player.events_played >= min_events
        }
        return (
            {slug: player for slug, player in state.items() if slug in eligible_slugs},
            {
                metric_name: {slug: value for slug, value in metric_values.items() if slug in eligible_slugs}
                for metric_name, metric_values in metrics.items()
            },
            {slug: count for slug, count in active_month_counts.items() if slug in eligible_slugs},
        )

    def _compute_rating_leader_month_leaders(
        self,
        snapshots: list[tuple[str, dict[str, dict[str, float | date | None]]]],
        player_months: dict[str, list[tuple[str, float]]],
        player_names: dict[str, str],
    ) -> list[dict[str, str | float]]:
        month_rankings = self._compute_rating_leader_month_rankings(snapshots, player_months, player_names)
        return [month_ranking[0] for month_ranking in month_rankings if month_ranking]

    def _compute_rating_leader_month_rankings(
        self,
        snapshots: list[tuple[str, dict[str, dict[str, float | date | None]]]],
        player_months: dict[str, list[tuple[str, float]]],
        player_names: dict[str, str],
    ) -> list[list[dict[str, str | float]]]:
        month_rankings: list[list[dict[str, str | float]]] = []
        for snapshot_month, month_state in snapshots:
            active_items = []
            for slug, values in month_state.items():
                last_event_date = values["last_event_date"]
                if last_event_date is None:
                    continue
                months_since_last = _month_delta(_month_key(last_event_date), snapshot_month)
                if months_since_last <= self.profile.goat_activity_window_months:
                    active_items.append((slug, values))
                    player_months[slug].append((snapshot_month, float(values["conservative"])))
            if not active_items:
                continue
            active_items.sort(key=lambda item: (-item[1]["conservative"], item[0]))
            month_rankings.append(
                [
                    {
                        "month": snapshot_month,
                        "player_slug": slug,
                        "player_name": player_names.get(slug, slug),
                        "conservative": float(values["conservative"]),
                    }
                    for slug, values in active_items
                ]
            )
        return month_rankings

    def _effective_field_size(self, field_size: int) -> int:
        max_effective = self.profile.max_effective_field_size
        if max_effective is None:
            return field_size
        return min(field_size, max_effective)

    def _field_size_weight_factor(self, effective_field_size: int) -> float:
        start = self.profile.field_size_dampening_start
        strength = self.profile.field_size_dampening_strength
        if start is None or effective_field_size <= start:
            return 1.0
        max_effective = self.profile.max_effective_field_size
        if max_effective is None or max_effective <= start:
            return 1.0
        progress = math.log2(effective_field_size / start) / math.log2(max_effective / start)
        return 1.0 - strength * (progress**2)

    def _sorted_major_podium_results(self, results: list[MajorPodiumResult]) -> list[MajorPodiumResult]:
        return sorted(
            results,
            key=lambda result: (
                not result.is_world_cup,
                result.placement,
                -result.event_date.toordinal(),
                result.event_name.casefold(),
            ),
        )

    def _site_major_podium_payload(
        self,
        player_slug: str,
        state: dict[str, PlayerState],
    ) -> list[dict[str, Any]]:
        player_state = state.get(player_slug)
        if player_state is None:
            return []
        return [
            {
                "event_name": result.event_name,
                "page_name": result.page_name,
                "event_date": result.event_date.isoformat(),
                "placement": result.placement,
                "title_points": result.title_points,
                "is_world_cup": result.is_world_cup,
            }
            for result in self._sorted_major_podium_results(player_state.major_podium_results)
        ]

    def _best_world_cup_result(self, player_state: PlayerState) -> tuple[int, int, int] | None:
        if not player_state.world_cup_results:
            return None

        best_low, best_high = min(player_state.world_cup_results, key=lambda result: (result[0], result[1]))
        count = sum(
            1
            for placement_low, placement_high in player_state.world_cup_results
            if placement_low == best_low and placement_high == best_high
        )
        return best_low, best_high, count

    def _site_best_world_cup_result_payload(
        self,
        player_slug: str,
        state: dict[str, PlayerState],
    ) -> dict[str, int] | None:
        player_state = state.get(player_slug)
        if player_state is None:
            return None

        best_result = self._best_world_cup_result(player_state)
        if best_result is None:
            return None

        placement_low, placement_high, count = best_result
        return {
            "placement_low": placement_low,
            "placement_high": placement_high,
            "count": count,
        }


def _inflate_sigma(
    current_sigma: float,
    previous_date: date | None,
    next_date: date,
    sigma_cap: float,
    monthly_drift: float,
) -> float:
    if previous_date is None:
        return current_sigma
    months = max(0.0, ((next_date.year - previous_date.year) * 12) + (next_date.month - previous_date.month))
    return min(sigma_cap, math.sqrt(current_sigma**2 + (months * monthly_drift) ** 2))


def _month_key(value: date | None) -> str:
    if value is None:
        return "unknown"
    return f"{value.year:04d}-{value.month:02d}"


def _next_month_key(value: str) -> str:
    year_str, month_str = value.split("-", maxsplit=1)
    year = int(year_str)
    month = int(month_str)
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _month_delta(start: str, end: str) -> int:
    start_year_str, start_month_str = start.split("-", maxsplit=1)
    end_year_str, end_month_str = end.split("-", maxsplit=1)
    return (int(end_year_str) - int(start_year_str)) * 12 + (int(end_month_str) - int(start_month_str))


def _normalize_metric(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    minimum = min(values.values())
    maximum = max(values.values())
    if math.isclose(minimum, maximum):
        return {key: 1.0 for key in values}
    return {key: (value - minimum) / (maximum - minimum) for key, value in values.items()}


def _normalize_goat_metrics(
    metrics: dict[str, dict[str, float]],
    *,
    sqrt_metrics: set[str] | None = None,
) -> dict[str, dict[str, float]]:
    sqrt_metrics = sqrt_metrics or set()
    return {
        metric_name: _normalize_metric(
            {
                key: math.sqrt(max(0.0, value)) if metric_name in sqrt_metrics else value
                for key, value in values.items()
            }
        )
        for metric_name, values in metrics.items()
    }


def _best_rolling_average(
    month_scores: list[tuple[str, float]],
    *,
    window_months: int,
    min_active_months: int = 1,
) -> float:
    if not month_scores:
        return 0.0
    best = 0.0
    for end_index, (end_month, _) in enumerate(month_scores):
        window_scores = [
            score
            for start_month, score in month_scores[: end_index + 1]
            if _month_delta(start_month, end_month) < window_months
        ]
        if len(window_scores) >= min_active_months:
            best = max(best, sum(window_scores) / len(window_scores))
    return best


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (position - lower)


def _write_csv(path: Path, rows: Iterable[RatingRow | GoatRow]) -> None:
    rows = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            handle.write("")
            return
        payload_rows = [asdict(row) for row in rows]
        writer = csv.DictWriter(handle, fieldnames=list(payload_rows[0].keys()))
        writer.writeheader()
        for payload_row in payload_rows:
            writer.writerow(payload_row)


def _write_json(path: Path, rows: Iterable[RatingRow | GoatRow]) -> None:
    payload = [asdict(row) for row in rows]
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
