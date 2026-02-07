"""Add return_on_risk, max_loss, and closing_mid_price columns.

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-07

Addresses quantitative audit findings:
- closing_mid_price: Mid-price at market close for improved CLV calculation
  (CLV vs closing mid rather than closing back/lay separately)
- max_loss: Maximum potential loss normalised by decision type
  (stake for BACK, stake*(odds-1) for LAY)
- return_on_risk: Return on Risk = net_pnl / max_loss
  (makes BACK and LAY hypothesis comparisons meaningful)
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mid-price at close for improved CLV calculation
    op.add_column(
        'shadow_decisions',
        sa.Column(
            'closing_mid_price', sa.Numeric(8, 2), nullable=True,
            comment='Mid price at close: (closing_back + closing_lay) / 2'
        )
    )

    # Maximum loss at risk, normalised by decision type
    op.add_column(
        'shadow_decisions',
        sa.Column(
            'max_loss', sa.Numeric(10, 2), nullable=True,
            comment='Maximum loss at risk: stake for BACK, stake*(odds-1) for LAY'
        )
    )

    # Return on Risk for comparing BACK vs LAY fairly
    op.add_column(
        'shadow_decisions',
        sa.Column(
            'return_on_risk', sa.Numeric(8, 4), nullable=True,
            comment='Return on Risk = net_pnl / max_loss'
        )
    )


def downgrade() -> None:
    op.drop_column('shadow_decisions', 'return_on_risk')
    op.drop_column('shadow_decisions', 'max_loss')
    op.drop_column('shadow_decisions', 'closing_mid_price')
