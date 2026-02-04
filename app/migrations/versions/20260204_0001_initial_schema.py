"""Initial schema for RidgeRadar.

Revision ID: 0001
Revises:
Create Date: 2026-02-04

This migration creates all the core tables for the RidgeRadar system:
- Sports, Competitions (with tier system), Events, Markets, Runners
- MarketSnapshots for raw data capture
- MarketProfilesDaily for aggregated metrics
- ExploitabilityScores for the scoring output
- ConfigVersions for configuration versioning
- JobRuns for task audit logging

CRITICAL: The tier system on competitions is essential.
- 'primary': Target leagues (2. Bundesliga, Serie B, etc.)
- 'secondary': Monitor leagues
- 'excluded': NEVER ingest (EPL, Champions League, etc.)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sports table
    op.create_table(
        "sports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("betfair_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True, default=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("betfair_id"),
    )

    # Competitions table with CRITICAL tier column
    op.create_table(
        "competitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("betfair_id", sa.String(length=50), nullable=False),
        sa.Column("sport_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country_code", sa.String(length=3), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True, default=True),
        sa.Column("priority", sa.Integer(), nullable=True, default=0),
        sa.Column(
            "tier",
            sa.String(length=20),
            nullable=False,
            default="secondary",
            comment="CRITICAL: 'primary', 'secondary', or 'excluded'",
        ),
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
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("betfair_id"),
    )
    op.create_index(
        "idx_competitions_tier",
        "competitions",
        ["tier"],
        postgresql_where=sa.text("enabled = true"),
    )

    # Events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("betfair_id", sa.String(length=50), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True, default="SCHEDULED"),
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
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("betfair_id"),
    )
    op.create_index(
        "idx_events_scheduled",
        "events",
        ["scheduled_start"],
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )

    # Markets table
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("betfair_id", sa.String(length=50), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("market_type", sa.String(length=50), nullable=False),
        sa.Column(
            "total_matched", sa.Numeric(precision=15, scale=2), nullable=True, default=0
        ),
        sa.Column("status", sa.String(length=20), nullable=True, default="OPEN"),
        sa.Column("in_play", sa.Boolean(), nullable=True, default=False),
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
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("betfair_id"),
    )
    op.create_index("idx_markets_status", "markets", ["status", "event_id"])

    # Runners table
    op.create_table(
        "runners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("betfair_id", sa.BigInteger(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_priority", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, default="ACTIVE"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("betfair_id", "market_id", name="uq_runner_market"),
    )

    # Market Snapshots table
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_matched", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("total_available", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("overround", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("ladder_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_snapshots_market_time",
        "market_snapshots",
        ["market_id", sa.text("captured_at DESC")],
    )

    # Market Profiles Daily table
    op.create_table(
        "market_profiles_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("profile_date", sa.Date(), nullable=False),
        sa.Column("time_bucket", sa.String(length=20), nullable=False),
        sa.Column("avg_spread_ticks", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("spread_volatility", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("avg_depth_best", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("depth_5_ticks", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column(
            "total_matched_volume", sa.Numeric(precision=15, scale=2), nullable=True
        ),
        sa.Column("update_rate_per_min", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("price_volatility", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("mean_price", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("snapshot_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_id", "profile_date", "time_bucket", name="uq_profile_market_date_bucket"
        ),
    )

    # Config Versions table
    op.create_table(
        "config_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("config_type", sa.String(length=50), nullable=False),
        sa.Column("config_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=True, default=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Exploitability Scores table
    op.create_table(
        "exploitability_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("runner_id", sa.Integer(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_bucket", sa.String(length=20), nullable=False),
        sa.Column("odds_band", sa.String(length=20), nullable=False),
        sa.Column("spread_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("volatility_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("update_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("depth_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("volume_penalty", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("total_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("config_version_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["config_version_id"], ["config_versions.id"]),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["runner_id"], ["runners.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_scores_total",
        "exploitability_scores",
        [sa.text("total_score DESC")],
        postgresql_where=sa.text("total_score > 50"),
    )
    op.create_index(
        "idx_scores_market_time",
        "exploitability_scores",
        ["market_id", sa.text("scored_at DESC")],
    )

    # Job Runs table
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_processed", sa.Integer(), nullable=True, default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
    op.drop_index("idx_scores_market_time", table_name="exploitability_scores")
    op.drop_index("idx_scores_total", table_name="exploitability_scores")
    op.drop_table("exploitability_scores")
    op.drop_table("config_versions")
    op.drop_table("market_profiles_daily")
    op.drop_index("idx_snapshots_market_time", table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_table("runners")
    op.drop_index("idx_markets_status", table_name="markets")
    op.drop_table("markets")
    op.drop_index("idx_events_scheduled", table_name="events")
    op.drop_table("events")
    op.drop_index("idx_competitions_tier", table_name="competitions")
    op.drop_table("competitions")
    op.drop_table("sports")
