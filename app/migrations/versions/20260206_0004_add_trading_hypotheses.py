"""Add TradingHypothesis table and update ShadowDecision for hypothesis tracking.

Revision ID: 0004
Revises: 0003
Create Date: 2024-02-06

Adds support for multiple concurrent trading hypotheses:
- TradingHypothesis: Define and track different trading strategies
- ShadowDecision updates: Add hypothesis reference and momentum data

Key hypotheses to be seeded:
- steam_follower: Back selections steaming in thin markets
- drift_fader: Lay selections drifting in thin markets
- score_based_classic: Traditional score-threshold entry
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # TradingHypothesis - Define trading strategies to test
    # ==========================================================================
    op.create_table(
        'trading_hypotheses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Entry criteria (flexible JSONB)
        sa.Column('entry_criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Selection logic
        sa.Column('selection_logic', sa.String(50), nullable=False, server_default='momentum'),
        sa.Column('decision_type', sa.String(10), nullable=False, server_default='BACK'),
        # Denormalized performance stats
        sa.Column('total_decisions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_wins', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_losses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_pnl', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('avg_clv', sa.Numeric(8, 4), nullable=True),
        sa.Column('last_decision_at', sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(
        'idx_hypotheses_enabled',
        'trading_hypotheses',
        ['enabled'],
        postgresql_where=sa.text('enabled = true')
    )

    # ==========================================================================
    # Update ShadowDecision - Add hypothesis tracking and momentum data
    # ==========================================================================

    # Add hypothesis reference
    op.add_column(
        'shadow_decisions',
        sa.Column('hypothesis_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'shadow_decisions',
        sa.Column('hypothesis_name', sa.String(50), nullable=True)
    )

    # Add momentum data columns
    op.add_column(
        'shadow_decisions',
        sa.Column('price_change_30m', sa.Numeric(8, 4), nullable=True)
    )
    op.add_column(
        'shadow_decisions',
        sa.Column('price_change_1h', sa.Numeric(8, 4), nullable=True)
    )
    op.add_column(
        'shadow_decisions',
        sa.Column('price_change_2h', sa.Numeric(8, 4), nullable=True)
    )

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_shadow_decisions_hypothesis',
        'shadow_decisions',
        'trading_hypotheses',
        ['hypothesis_id'],
        ['id']
    )

    # Add index for hypothesis filtering
    op.create_index(
        'idx_shadow_decisions_hypothesis',
        'shadow_decisions',
        ['hypothesis_name', 'outcome']
    )


def downgrade() -> None:
    # Remove index
    op.drop_index('idx_shadow_decisions_hypothesis', table_name='shadow_decisions')

    # Remove foreign key
    op.drop_constraint('fk_shadow_decisions_hypothesis', 'shadow_decisions', type_='foreignkey')

    # Remove columns from shadow_decisions
    op.drop_column('shadow_decisions', 'price_change_2h')
    op.drop_column('shadow_decisions', 'price_change_1h')
    op.drop_column('shadow_decisions', 'price_change_30m')
    op.drop_column('shadow_decisions', 'hypothesis_name')
    op.drop_column('shadow_decisions', 'hypothesis_id')

    # Drop trading_hypotheses table
    op.drop_index('idx_hypotheses_enabled', table_name='trading_hypotheses')
    op.drop_table('trading_hypotheses')
