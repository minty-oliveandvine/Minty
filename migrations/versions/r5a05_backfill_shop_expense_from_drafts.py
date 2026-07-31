"""STAGE 4b — backfill shop_expense from shop_expense_draft

Revision ID: r5a05_backfill_expense
Revises: r4a04_repoint_fks
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

The one-off catch-up for the shop_expense_draft -> shop_expense pairing.

``ensure_shop_expense_for_draft`` (services/expense_draft_mirror.py) creates
the paired shop_expense row for every NEW draft expense from now on. This
revision does the same for the ones that already exist, so expense reads can
be migrated to shop_expense without in-progress reports losing their expenses.

Exactly the same shape as PART 3 of r0_combined_report_consolidation: an
INSERT ... WHERE NOT EXISTS keyed on the shared primary key.

-----------------------------------------------------------------------------
WHY THERE IS NO MERGE, NO WINNER, NO DEDUP

The submit path (ending.py:1617) copies draft -> real reusing the PRIMARY KEY:

    ShopExpense(id=shop_expense_draft.id,
                report_id=shop_expense_draft.report_draft_id, ...)

So a submitted expense already exists in both tables under one id, and
``WHERE NOT EXISTS`` simply skips it — the shop_expense row wins by being
there first. Only draft expenses that were never submitted get inserted.

report_id is copied straight from report_draft_id. Those are the same value:
a draft and its report share an id (Stage 4a), which is why shop_expense's FK
to report.id resolves without any remapping.

-----------------------------------------------------------------------------
THE FK GUARD

shop_expense.report_id REFERENCES report.id. Stage 4a plus the r0 backfill
mean every draft should have a report row, but a draft expense whose parent
draft somehow has none would violate that FK and abort the whole migration.

Rather than let it fail opaquely, the INSERT joins `report` — so such rows are
skipped — and the check afterwards reports how many were skipped and why. A
non-zero count there is worth investigating; it means a draft expense is
orphaned from any report.

-----------------------------------------------------------------------------
NOT NULL

shop_expense.item and shop_expense.amount are NOT NULL. The multi-file upload
path (api.py:1737) deliberately creates skeleton drafts with item="" and
amount=0.0 until the PATCH fills them in, and those placeholders satisfy the
constraint. COALESCE covers any historical row that is NULL outright.

-----------------------------------------------------------------------------
REVERSIBLE-ISH. downgrade() deletes only the rows this revision could have
created — draft expenses with no corresponding submitted expense. It cannot
distinguish those from rows the application has legitimately created since,
so it is deliberately conservative and matches on the draft table.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r5a05_backfill_expense"
down_revision = "r4a04_repoint_fks"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Columns that exist on BOTH tables (report_id/report_draft_id handled apart).
SHARED = [
    "item",
    "amount",
    "remarks",
    "files",
    "s3_key",
    "contact_id",
    "contact_name",
    "account_id",
    "account_code",
    "item_code",
]


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name, schema=SCHEMA)


def upgrade():
    bind = op.get_bind()
    if not (
        _has_table(bind, "shop_expense") and _has_table(bind, "shop_expense_draft")
    ):
        return

    cols = ", ".join(SHARED)
    # item/amount are NOT NULL on the target; the rest copy as-is.
    sel = ", ".join(
        {
            "item": "COALESCE(d.item, '')",
            "amount": "COALESCE(d.amount, 0)",
        }.get(c, f"d.{c}")
        for c in SHARED
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.shop_expense (id, report_id, {cols})
        SELECT d.id, d.report_draft_id, {sel}
          FROM {SCHEMA}.shop_expense_draft d
          -- FK guard: report_id REFERENCES report.id, so only insert rows
          -- whose parent report actually exists.
          JOIN {SCHEMA}.report r ON r.id = d.report_draft_id
         WHERE NOT EXISTS (
                   SELECT 1 FROM {SCHEMA}.shop_expense e WHERE e.id = d.id
               )
        """
    )

    # Report anything skipped by the FK guard — a draft expense with no report
    # is orphaned data and should be looked at rather than silently dropped.
    orphans = bind.execute(
        sa.text(
            f"""
            SELECT count(*) FROM {SCHEMA}.shop_expense_draft d
             WHERE NOT EXISTS (
                       SELECT 1 FROM {SCHEMA}.report r WHERE r.id = d.report_draft_id
                   )
            """
        )
    ).scalar()
    if orphans:
        print(
            f"WARNING: {orphans} shop_expense_draft row(s) reference a "
            "report_draft with no matching `report` row and were skipped. "
            "These expenses will not appear once reads move to shop_expense."
        )


def downgrade():
    bind = op.get_bind()
    if not (
        _has_table(bind, "shop_expense") and _has_table(bind, "shop_expense_draft")
    ):
        return
    # Conservative: only remove shop_expense rows that mirror a draft. Rows
    # created by the submit path share the same ids, so this cannot tell them
    # apart — which is why the docstring calls this reversible-ish.
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.shop_expense e
         WHERE EXISTS (
                   SELECT 1 FROM {SCHEMA}.shop_expense_draft d WHERE d.id = e.id
               )
        """
    )
