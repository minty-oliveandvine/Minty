"""Backfill contact_name on shop_expense and shop_expense_draft

One-time fix for expenses that show "N/A" because contact_name is NULL even
though contact_id points at a real Xero contact. We resolve the name from
pettycashv2.xero_contact_sync, matching on contact_id = xero_contact_id and the
expense's entity (report.company / report_draft.company) = xero_contact_sync.entity_id.

xero_contact_sync has no unique constraint, so the same (entity_id,
xero_contact_id) pair can have duplicate rows. We dedup deterministically with
DISTINCT ON: prefer the row whose xero_org_id matches the entity's current
xero_org_id, then the longest (least-truncated) name. Only rows whose
contact_name is NULL/'' are touched; existing names are left intact.

Downgrade is intentionally a no-op: reverting would just restore the "N/A" state.

Revision ID: f3a1c2b4d6e8
Revises: f7b1c3d5e9a2
Create Date: 2026-06-10 00:00:00.000000

"""

from alembic import op
from sqlalchemy import text

revision = "f3a1c2b4d6e8"
down_revision = "f7b1c3d5e9a2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Deterministic one-name-per-(entity, contact) pick.
PICK = f"""
WITH picked AS (
    SELECT DISTINCT ON (xcs.entity_id, xcs.xero_contact_id)
           xcs.entity_id        AS entity_id,
           xcs.xero_contact_id  AS xero_contact_id,
           xcs.name             AS name
    FROM {SCHEMA}.xero_contact_sync AS xcs
    LEFT JOIN {SCHEMA}.entities AS e ON e.id = xcs.entity_id
    WHERE xcs.name IS NOT NULL AND xcs.name <> ''
    ORDER BY xcs.entity_id,
             xcs.xero_contact_id,
             (xcs.xero_org_id IS NOT DISTINCT FROM e.xero_org_id) DESC,
             length(xcs.name) DESC
)
"""


def upgrade():
    bind = op.get_bind()

    # shop_expense_draft
    bind.execute(text(PICK + f"""
        UPDATE {SCHEMA}.shop_expense_draft AS sed
        SET contact_name = picked.name
        FROM {SCHEMA}.report_draft AS rd
        JOIN picked ON picked.entity_id = rd.company
        WHERE sed.report_draft_id = rd.id
          AND sed.contact_id = picked.xero_contact_id
          AND sed.contact_id IS NOT NULL
          AND (sed.contact_name IS NULL OR sed.contact_name = '')
    """))

    # shop_expense
    bind.execute(text(PICK + f"""
        UPDATE {SCHEMA}.shop_expense AS se
        SET contact_name = picked.name
        FROM {SCHEMA}.report AS r
        JOIN picked ON picked.entity_id = r.company
        WHERE se.report_id = r.id
          AND se.contact_id = picked.xero_contact_id
          AND se.contact_id IS NOT NULL
          AND (se.contact_name IS NULL OR se.contact_name = '')
    """))

    # Report leftovers (contact_id NULL, or no matching sync row).
    for tbl in ("shop_expense", "shop_expense_draft"):
        remaining = bind.execute(text(
            f"SELECT count(*) FROM {SCHEMA}.{tbl} "
            f"WHERE contact_name IS NULL OR contact_name = ''"
        )).scalar()
        print(f"[backfill] {tbl}: {remaining} rows still without contact_name")


def downgrade():
    # Intentional no-op — reverting would re-introduce the "N/A" state.
    pass
