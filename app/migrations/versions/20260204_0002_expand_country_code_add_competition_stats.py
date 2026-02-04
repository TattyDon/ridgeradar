"""Expand country_code column and add competition_stats table.

Revision ID: ffeb4b9a7482
Revises: initial_schema
Create Date: 2026-02-04 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand country_code column to accommodate "International" and similar values
    op.alter_column(
        "competitions",
        "country_code",
        existing_type=sa.VARCHAR(length=3),
        type_=sa.String(length=50),
        existing_nullable=True,
    )

    # Create competition_stats table for learning which competitions score well
    op.create_table(
        "competition_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("stats_date", sa.Date(), nullable=False),
        sa.Column("markets_scored", sa.Integer(), server_default="0"),
        sa.Column("avg_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("max_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("min_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("score_std_dev", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("markets_above_40", sa.Integer(), server_default="0"),
        sa.Column("markets_above_55", sa.Integer(), server_default="0"),
        sa.Column("markets_above_70", sa.Integer(), server_default="0"),
        sa.Column("rolling_30d_avg_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "competition_id", "stats_date", name="uq_competition_stats_date"
        ),
    )
    op.create_index(
        "idx_competition_stats_date",
        "competition_stats",
        ["competition_id", "stats_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_competition_stats_date", table_name="competition_stats")
    op.drop_table("competition_stats")
    op.alter_column(
        "competitions",
        "country_code",
        existing_type=sa.String(length=50),
        type_=sa.VARCHAR(length=3),
        existing_nullable=True,
    )
