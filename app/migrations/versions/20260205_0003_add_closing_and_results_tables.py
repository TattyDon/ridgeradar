"""Add MarketClosingData, EventResult, and ShadowDecision tables.

Revision ID: 0003
Revises: 0002
Create Date: 2024-02-05

These tables are CRITICAL for Phase 1 validation and Phase 2 shadow trading:
- MarketClosingData: Final scores and closing odds before kickoff
- EventResult: Actual match outcomes (goals, scores) for O/U validation
- ShadowDecision: Hypothetical trading decisions for Phase 2
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # EventResult - Actual match outcomes
    # ==========================================================================
    op.create_table(
        'event_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        # Football scores
        sa.Column('home_score', sa.Integer(), nullable=True),
        sa.Column('away_score', sa.Integer(), nullable=True),
        sa.Column('home_ht_score', sa.Integer(), nullable=True),
        sa.Column('away_ht_score', sa.Integer(), nullable=True),
        # Derived fields
        sa.Column('total_goals', sa.Integer(), nullable=True),
        sa.Column('btts', sa.Boolean(), nullable=True),
        # Tennis
        sa.Column('home_sets', sa.Integer(), nullable=True),
        sa.Column('away_sets', sa.Integer(), nullable=True),
        # Extended stats
        sa.Column('statistics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source', sa.String(50), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.UniqueConstraint('event_id'),
    )
    op.create_index('idx_event_results_status', 'event_results', ['status'])
    op.create_index(
        'idx_event_results_total_goals',
        'event_results',
        ['total_goals'],
        postgresql_where=sa.text('total_goals IS NOT NULL')
    )

    # ==========================================================================
    # MarketClosingData - Final scores and closing odds
    # ==========================================================================
    op.create_table(
        'market_closing_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.Integer(), nullable=False),
        # Final score
        sa.Column('final_score_id', sa.Integer(), nullable=True),
        sa.Column('final_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('score_captured_at', sa.DateTime(timezone=True), nullable=True),
        # Closing odds
        sa.Column('closing_snapshot_id', sa.BigInteger(), nullable=True),
        sa.Column('closing_odds', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('odds_captured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('minutes_to_start', sa.Integer(), nullable=True),
        # Settlement
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['final_score_id'], ['exploitability_scores.id']),
        sa.ForeignKeyConstraint(['closing_snapshot_id'], ['market_snapshots.id']),
        sa.UniqueConstraint('market_id'),
    )
    op.create_index(
        'idx_closing_data_score',
        'market_closing_data',
        ['final_score'],
        postgresql_where=sa.text('final_score IS NOT NULL')
    )
    op.create_index(
        'idx_closing_data_unsettled',
        'market_closing_data',
        ['market_id'],
        postgresql_where=sa.text('settled_at IS NULL')
    )

    # ==========================================================================
    # ShadowDecision - Phase 2 hypothetical trading decisions
    # ==========================================================================
    op.create_table(
        'shadow_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        # What we would bet on
        sa.Column('market_id', sa.Integer(), nullable=False),
        sa.Column('runner_id', sa.Integer(), nullable=False),
        sa.Column('decision_type', sa.String(10), nullable=False),  # BACK or LAY
        # Trigger
        sa.Column('score_id', sa.Integer(), nullable=False),
        sa.Column('trigger_score', sa.Numeric(6, 2), nullable=False),
        sa.Column('trigger_reason', sa.String(200), nullable=True),
        # Entry conditions
        sa.Column('decision_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('minutes_to_start', sa.Integer(), nullable=False),
        sa.Column('entry_back_price', sa.Numeric(8, 2), nullable=False),
        sa.Column('entry_lay_price', sa.Numeric(8, 2), nullable=False),
        sa.Column('entry_spread', sa.Numeric(6, 4), nullable=False),
        sa.Column('available_to_back', sa.Numeric(12, 2), nullable=True),
        sa.Column('available_to_lay', sa.Numeric(12, 2), nullable=True),
        # Theoretical stake
        sa.Column('theoretical_stake', sa.Numeric(10, 2), nullable=False, server_default='10.00'),
        # CLV (populated later)
        sa.Column('closing_back_price', sa.Numeric(8, 2), nullable=True),
        sa.Column('closing_lay_price', sa.Numeric(8, 2), nullable=True),
        sa.Column('clv_percent', sa.Numeric(6, 4), nullable=True),
        # Outcome (populated after settlement)
        sa.Column('outcome', sa.String(20), nullable=True),  # WIN, LOSE, VOID, PENDING
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        # P&L
        sa.Column('gross_pnl', sa.Numeric(10, 2), nullable=True),
        sa.Column('commission', sa.Numeric(10, 2), nullable=True),
        sa.Column('spread_cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('net_pnl', sa.Numeric(10, 2), nullable=True),
        # Niche classification
        sa.Column('niche', sa.String(100), nullable=True),
        sa.Column('competition_id', sa.Integer(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['runner_id'], ['runners.id']),
        sa.ForeignKeyConstraint(['score_id'], ['exploitability_scores.id']),
        sa.ForeignKeyConstraint(['competition_id'], ['competitions.id']),
    )
    op.create_index('idx_shadow_decisions_niche', 'shadow_decisions', ['niche', 'outcome'])
    op.create_index(
        'idx_shadow_decisions_pending',
        'shadow_decisions',
        ['market_id'],
        postgresql_where=sa.text("outcome = 'PENDING'")
    )
    op.create_index('idx_shadow_decisions_date', 'shadow_decisions', ['decision_at'])


def downgrade() -> None:
    op.drop_table('shadow_decisions')
    op.drop_table('market_closing_data')
    op.drop_table('event_results')
