from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TournamentRuleMatch(StrictConfigModel):
    source_event_id: str | None = None
    pageid: int | None = None
    tier: int | None = None
    page_name: str | None = None
    page_name_regex: str | None = None
    name: str | None = None
    name_regex: str | None = None
    series: str | None = None
    mode: str | None = None
    type: str | None = None
    start_date_gte: str | None = None
    start_date_lte: str | None = None


class TournamentRule(StrictConfigModel):
    name: str
    match: TournamentRuleMatch
    include: bool | None = None
    weight: float | None = None
    tags: list[str] | None = None


class TournamentRuleDefaults(StrictConfigModel):
    include: bool = True
    weight: float = 1.0
    tags: list[str] = Field(default_factory=list)


class TournamentRulesConfig(StrictConfigModel):
    defaults: TournamentRuleDefaults = Field(default_factory=TournamentRuleDefaults)
    rules: list[TournamentRule] = Field(default_factory=list)


class MajorPlacementPoints(StrictConfigModel):
    placement_low: int
    placement_high: int
    points: float


class MajorEventRule(StrictConfigModel):
    name: str
    match: TournamentRuleMatch


class MajorEventsConfig(StrictConfigModel):
    placement_points: list[MajorPlacementPoints] = Field(
        default_factory=lambda: [
            MajorPlacementPoints(placement_low=1, placement_high=1, points=10.0),
            MajorPlacementPoints(placement_low=2, placement_high=2, points=4.0),
            MajorPlacementPoints(placement_low=3, placement_high=3, points=3.0),
            MajorPlacementPoints(placement_low=4, placement_high=4, points=2.0),
            MajorPlacementPoints(placement_low=5, placement_high=8, points=1.0),
        ]
    )
    rules: list[MajorEventRule] = Field(default_factory=list)


class AliasEntry(StrictConfigModel):
    canonical_slug: str
    display_name: str
    source_ids: list[str] = Field(default_factory=list)
    exact_names: list[str] = Field(default_factory=list)


class AliasesConfig(StrictConfigModel):
    players: list[AliasEntry] = Field(default_factory=list)
    teams: list[AliasEntry] = Field(default_factory=list)


class GoatWeights(StrictConfigModel):
    prime_rating: float = 0.25
    elite_area: float = 0.25
    median_conservative: float = 0.20
    title_points: float = 0.20


class CurrentEligibility(StrictConfigModel):
    min_events_played: int = 0
    max_months_since_last_event: int | None = None


class RatingProfile(StrictConfigModel):
    initial_mu: float = 25.0
    initial_sigma: float = 8.333
    monthly_inactivity_drift: float = 0.5
    conservative_multiplier: float = 2.0
    max_effective_field_size: int | None = 128
    field_size_dampening_start: int | None = 16
    field_size_dampening_strength: float = 0.75
    goat_activity_window_months: int = 12
    goat_prime_window_months: int = 12
    goat_prime_min_active_months: int = 6
    goat_min_events_played: int = 0
    goat_elite_threshold: float = 25.0
    goat_weights: GoatWeights = Field(default_factory=GoatWeights)
    current_eligibility: CurrentEligibility = Field(default_factory=CurrentEligibility)


def load_yaml_model(path: str | Path, model_type: type[BaseModel]) -> BaseModel:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return model_type.model_validate(data)
