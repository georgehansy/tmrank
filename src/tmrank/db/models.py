from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tmrank.db.base import Base


JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_written: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)


class ApiFetch(Base):
    __tablename__ = "api_fetches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    endpoint: Mapped[str] = mapped_column(String(100))
    request_params: Mapped[dict] = mapped_column(JSONVariant)
    response_payload: Mapped[dict] = mapped_column(JSONVariant)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    http_status: Mapped[int] = mapped_column(Integer)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_events_source_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    source_event_id: Mapped[str] = mapped_column(String(255))
    page_id: Mapped[int | None] = mapped_column(Integer, index=True)
    page_name: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    series: Mapped[str | None] = mapped_column(String(255))
    tier: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str | None] = mapped_column(String(50))
    event_type: Mapped[str | None] = mapped_column("type", String(50))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    sort_date: Mapped[date | None] = mapped_column(Date)
    prize_pool: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    participants_number: Mapped[int | None] = mapped_column(Integer)
    source_payload_ref: Mapped[int | None] = mapped_column(ForeignKey("api_fetches.id"))
    results_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results_fetch_ref: Mapped[int | None] = mapped_column(ForeignKey("api_fetches.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    competitors: Mapped[list["EventCompetitor"]] = relationship(back_populates="event")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_slug: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(10))
    source_ids: Mapped[list[str]] = mapped_column(JSONVariant, default=list)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_slug: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    source_ids: Mapped[list[str]] = mapped_column(JSONVariant, default=list)


class EventCompetitor(Base):
    __tablename__ = "event_competitors"
    __table_args__ = (
        UniqueConstraint("event_id", "competitor_type", "canonical_slug", name="uq_event_competitor_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    competitor_type: Mapped[str] = mapped_column(String(20))
    canonical_slug: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    source_competitor_id: Mapped[str | None] = mapped_column(String(255))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    country: Mapped[str | None] = mapped_column(String(10))

    event: Mapped[Event] = relationship(back_populates="competitors")
    result: Mapped["EventResult | None"] = relationship(back_populates="competitor", uselist=False)
    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="team_competitor",
        foreign_keys="TeamMembership.team_competitor_id",
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("team_competitor_id", "player_competitor_id", name="uq_team_membership"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    team_competitor_id: Mapped[int] = mapped_column(ForeignKey("event_competitors.id"))
    player_competitor_id: Mapped[int] = mapped_column(ForeignKey("event_competitors.id"))

    team_competitor: Mapped[EventCompetitor] = relationship(
        back_populates="memberships",
        foreign_keys=[team_competitor_id],
    )
    player_competitor: Mapped[EventCompetitor] = relationship(foreign_keys=[player_competitor_id])


class EventResult(Base):
    __tablename__ = "event_results"
    __table_args__ = (
        UniqueConstraint("event_id", "competitor_id", name="uq_event_results_competitor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("event_competitors.id"))
    placement_low: Mapped[int] = mapped_column(Integer)
    placement_high: Mapped[int] = mapped_column(Integer)
    placement_text: Mapped[str] = mapped_column(String(50))
    prize: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    points: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    raw_payload: Mapped[dict] = mapped_column(JSONVariant)

    competitor: Mapped[EventCompetitor] = relationship(back_populates="result")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_type", "source", "source_key", "match_kind", name="uq_entity_alias_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30))
    source_key: Mapped[str] = mapped_column(String(255))
    match_kind: Mapped[str] = mapped_column(String(30))
    canonical_slug: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255))


Index("ix_event_results_event_place", EventResult.event_id, EventResult.placement_low, EventResult.placement_high)
