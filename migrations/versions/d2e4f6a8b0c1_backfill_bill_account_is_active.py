"""Backfill entity_bill_account_xero.is_active for bill CoA types

One-time fix to recover from past clobbering by the petty cash cross-module
mirror. Re-ticks every non-deleted row whose account_type is in the bill CoA
allowlist (DIRECTCOSTS, EXPENSE, FIXED, INVENTORY, OVERHEADS, PREPAYMENT) so
the bill settings page shows the "default = ticked" baseline. After this runs,
the sync logic preserves user toggles instead of resetting them.

Downgrade is intentionally a no-op: reverting this would just restore the
broken half-ticked state, which is never desired.

Revision ID: d2e4f6a8b0c1
Revises: c7d9e1f3a5b7
Create Date: 2026-05-19 00:00:00.000000

"""

from alembic import op

revision = "d2e4f6a8b0c1"
down_revision = "c7d9e1f3a5b7"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_bill_account_xero
        SET is_active = true,
            updated_at = NOW()
        WHERE is_deleted = false
          AND account_type IN (
              'DIRECTCOSTS', 'EXPENSE', 'FIXED',
              'INVENTORY', 'OVERHEADS', 'PREPAYMENT'
          )
        """
    )


def downgrade():
    # Intentional no-op — reverting would re-introduce the bug this fixed.
    pass
