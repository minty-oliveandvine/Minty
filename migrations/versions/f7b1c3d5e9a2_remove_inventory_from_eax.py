"""Remove Inventory accounts from the petty-cash expense selector

Inventory was dropped from COA_INCLUDED_TYPES (the Module 1 petty-cash Chart of
Accounts allowlist). The Add-Expense dropdown reads entity_account_xero with no
type filter (is_active only), so already-ticked Inventory rows would otherwise
linger until the entity next saves settings. Delete them now so they disappear
immediately.

entity_account_xero is a rebuildable denormalized mirror — the petty-cash CoA
sync re-inserts rows on demand — so deleting is safe. We join account_info to key
off the canonical account type rather than the denormalized eax.type column.

Downgrade is a no-op: the sync rebuilds entity_account_xero on the next save, and
Inventory is no longer eligible anyway.

Revision ID: f7b1c3d5e9a2
Revises: add_user_xero_email
Create Date: 2026-06-09 00:00:00.000000

"""

from alembic import op

revision = "f7b1c3d5e9a2"
down_revision = "add_user_xero_email"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    # Remove petty-cash expense rows for Inventory accounts so they immediately
    # disappear from the Add-Expense dropdown (which filters only on is_active).
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.entity_account_xero eax
        USING {SCHEMA}.account_info ai
        WHERE eax.account_id = ai.id
          AND ai.type = 'INVENTORY'
        """
    )


def downgrade():
    # No-op: the petty-cash CoA sync rebuilds entity_account_xero on next save.
    pass
