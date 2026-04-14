"""Initial schema for tmrank."""

from alembic import op
import sqlalchemy as sa


revision = "20260406_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text()),
    )

    op.create_table(
        "api_fetches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("endpoint", sa.String(length=100), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
    )
    op.create_index("ix_api_fetches_payload_hash", "api_fetches", ["payload_hash"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("page_id", sa.Integer()),
        sa.Column("page_name", sa.String(length=255)),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("series", sa.String(length=255)),
        sa.Column("tier", sa.Integer()),
        sa.Column("mode", sa.String(length=50)),
        sa.Column("type", sa.String(length=50)),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("sort_date", sa.Date()),
        sa.Column("prize_pool", sa.Numeric(14, 2)),
        sa.Column("participants_number", sa.Integer()),
        sa.Column("source_payload_ref", sa.Integer(), sa.ForeignKey("api_fetches.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("source", "source_event_id", name="uq_events_source_event"),
    )
    op.create_index("ix_events_page_id", "events", ["page_id"])

    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=10)),
        sa.Column("source_ids", sa.JSON(), nullable=False),
    )

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
    )

    op.create_table(
        "event_competitors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("competitor_type", sa.String(length=20), nullable=False),
        sa.Column("canonical_slug", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_competitor_id", sa.String(length=255)),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id")),
        sa.Column("country", sa.String(length=10)),
        sa.UniqueConstraint("event_id", "competitor_type", "canonical_slug", name="uq_event_competitor_slug"),
    )
    op.create_index("ix_event_competitors_event_id", "event_competitors", ["event_id"])

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("team_competitor_id", sa.Integer(), sa.ForeignKey("event_competitors.id"), nullable=False),
        sa.Column("player_competitor_id", sa.Integer(), sa.ForeignKey("event_competitors.id"), nullable=False),
        sa.UniqueConstraint("team_competitor_id", "player_competitor_id", name="uq_team_membership"),
    )
    op.create_index("ix_team_memberships_event_id", "team_memberships", ["event_id"])

    op.create_table(
        "event_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("event_competitors.id"), nullable=False),
        sa.Column("placement_low", sa.Integer(), nullable=False),
        sa.Column("placement_high", sa.Integer(), nullable=False),
        sa.Column("placement_text", sa.String(length=50), nullable=False),
        sa.Column("prize", sa.Numeric(14, 2)),
        sa.Column("points", sa.Numeric(14, 2)),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("event_id", "competitor_id", name="uq_event_results_competitor"),
    )
    op.create_index("ix_event_results_event_id", "event_results", ["event_id"])
    op.create_index("ix_event_results_event_place", "event_results", ["event_id", "placement_low", "placement_high"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("match_kind", sa.String(length=30), nullable=False),
        sa.Column("canonical_slug", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.UniqueConstraint("entity_type", "source", "source_key", "match_kind", name="uq_entity_alias_key"),
    )
    op.create_index("ix_entity_aliases_canonical_slug", "entity_aliases", ["canonical_slug"])


def downgrade() -> None:
    op.drop_index("ix_entity_aliases_canonical_slug", table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index("ix_event_results_event_place", table_name="event_results")
    op.drop_index("ix_event_results_event_id", table_name="event_results")
    op.drop_table("event_results")
    op.drop_index("ix_team_memberships_event_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_index("ix_event_competitors_event_id", table_name="event_competitors")
    op.drop_table("event_competitors")
    op.drop_table("teams")
    op.drop_table("players")
    op.drop_index("ix_events_page_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_api_fetches_payload_hash", table_name="api_fetches")
    op.drop_table("api_fetches")
    op.drop_table("sync_runs")
