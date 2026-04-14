from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class ParsedEvent:
    source: str
    source_event_id: str
    page_id: int | None
    page_name: str | None
    name: str
    series: str | None
    tier: int | None
    mode: str | None
    event_type: str | None
    start_date: date | None
    end_date: date | None
    sort_date: date | None
    prize_pool: float | None
    participants_number: int | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ParsedCompetitor:
    competitor_type: str
    source_competitor_id: str | None
    name: str
    canonical_slug: str
    display_name: str
    country: str | None = None
    member_slugs: list[str] = field(default_factory=list)
    member_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedResultRow:
    placement_low: int
    placement_high: int
    placement_text: str
    prize: float | None
    points: float | None
    competitor: ParsedCompetitor
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ParsedEventResults:
    source: str
    source_event_id: str
    fetched_at: datetime
    raw_rows: list[dict[str, Any]]
    results: list[ParsedResultRow]


@dataclass(slots=True)
class CuratedEvent:
    source_event_id: str
    page_id: int | None
    name: str
    series: str | None
    mode: str | None
    event_type: str | None
    start_date: date | None
    end_date: date | None
    include: bool
    weight: float
    tags: list[str]


@dataclass(slots=True)
class RatingRow:
    rank: int
    player_slug: str
    player_name: str
    mu: float
    sigma: float
    conservative_score: float
    events_played: int
    recent_events_24_months: int
    last_event_date: date | None


@dataclass(slots=True)
class GoatRow:
    rank: int
    player_slug: str
    player_name: str
    goat_score: float
    prime_rating: float
    elite_area: float
    median_conservative: float
    title_points: float
    norm_prime_rating: float
    norm_elite_area: float
    norm_median_conservative: float
    norm_title_points: float
    active_months: int
    events_played: int


@dataclass(slots=True)
class RatingLeaderTimelineRow:
    start_month: str
    end_month: str
    player_slug: str
    player_name: str
    months: int
    peak_conservative: float


@dataclass(slots=True)
class RatingLeaderTimelineMonthRow:
    month: str
    player_slug: str
    player_name: str
    conservative: float


@dataclass(slots=True)
class ActivePlayersMonthRow:
    month: str
    active_players: int
    top10_conservative_cutoff: float | None
    p95_conservative: float | None
    p99_conservative: float | None


@dataclass(slots=True)
class TournamentStrengthRow:
    rank: int
    source_event_id: str
    event_name: str
    event_date: date
    series: str | None
    field_size: int
    effective_field_size: int
    rated_strength_cap: int
    strength: float
