"""Add event result sync state columns."""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0002"
down_revision = "20260406_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("results_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("results_fetch_ref", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_events_results_fetch_ref",
        "events",
        "api_fetches",
        ["results_fetch_ref"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_events_results_fetch_ref", "events", type_="foreignkey")
    op.drop_column("events", "results_fetch_ref")
    op.drop_column("events", "results_synced_at")
