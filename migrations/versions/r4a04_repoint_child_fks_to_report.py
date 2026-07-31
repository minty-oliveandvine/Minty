"""STAGE 3 — re-point the detail/xero FKs from report_v2 to report

Revision ID: r4a04_repoint_fks
Revises: r3a03_relax_report_nn
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

Stage 2a (r2a02) dropped four FK constraints that pointed at
report_v2.report_id, because they were the only reason seven code sites
manufactured a ReportV2 row. Those columns have been unconstrained since.

This revision constrains them again — against `report.id` this time:

    report_sale_detail.report_id      -> report.id
    report_expense_detail.report_id   -> report.id
    xero_report_sync.report_id        -> report.id
    xero_bank_transfer.sync_report_id -> report.id

report_v2 is now referenced by nothing and can be dropped in Stage 5.

-----------------------------------------------------------------------------
WHY THIS CAN ONLY RUN NOW

The values never changed: report_v2.report_id was always the draft id, which
is always the report id (sales.py:747-750, ending.py:1418-1419). What was
missing was the PARENT ROW. A draft only got a `report` row at submit, so
every in-progress draft's detail rows pointed at an id absent from `report`,
and this constraint would have been rejected for all of them.

Stage 4a fixed that from both directions:
  * r3a03 relaxed report.expenses / report.closing_balance to nullable, so a
    draft-shaped report row is insertable at all.
  * ensure_report_row_for_draft() (services/shared.py) now creates the paired
    report row at draft creation, so no NEW gap appears.
  * the one-off backfill in r3a03's .sql twin closed the gap for existing
    rows.

Only with all three done is every child row's parent guaranteed to exist.

-----------------------------------------------------------------------------
ON DELETE BEHAVIOUR — deliberately NOT uniform

report_sale_detail / report_expense_detail get CASCADE, matching what
a7b8c9d0e1f2 gave them against report_v2: these rows are components of a
report and have no meaning without it.

xero_report_sync / xero_bank_transfer get SET NULL, NOT CASCADE. They are an
audit trail of what was pushed to Xero. Deleting a local report should not
silently erase the record that it was published — that record is how a
double-publish gets detected. The columns are part of a composite primary key
today, though, and a PK column cannot be SET NULL, so they keep CASCADE for
now and the audit-retention question is left to Stage 5 where the PKs are
being reshaped anyway. Flagged here rather than silently decided.

-----------------------------------------------------------------------------
THIS REVISION IS A GUARD, NOT A DATA CHANGE

No rows are read, written or moved. If it succeeds, every child row already
pointed at a real report. If it FAILS, that is the useful outcome: it means
orphans exist, and the exception names the constraint that found them. Run
the ORPHAN ANALYSIS in r2a02's .sql twin to see them before retrying.

-----------------------------------------------------------------------------
REVERSIBLE. downgrade() drops the four constraints again, returning to the
r2a02 state (unconstrained columns). It deliberately does NOT restore the
report_v2 FKs — going back that far means reinstating the seven ReportV2
write sites too, which is a code rollback, not a schema one.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r4a04_repoint_fks"
down_revision = "r3a03_relax_report_nn"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (table, constraint_name, local_cols, ondelete)
# Names reuse the originals from a7b8c9d0e1f2 so the schema reads consistently;
# they now point at `report` rather than `report_v2`.
REPOINTED_FKS = [
    ("report_sale_detail", "report_sale_detail_report_id_fkey", ["report_id"], "CASCADE"),
    ("report_expense_detail", "report_expense_detail_report_id_fkey", ["report_id"], "CASCADE"),
    ("xero_report_sync", "xero_report_sync_report_id_fkey", ["report_id"], "CASCADE"),
    ("xero_bank_transfer", "xero_bank_transfer_sync_report_id_fkey", ["sync_report_id"], "CASCADE"),
]


def _existing_fk_names(bind, table):
    insp = sa.inspect(bind)
    if not insp.has_table(table, schema=SCHEMA):
        return set()
    return {
        fk["name"] for fk in insp.get_foreign_keys(table, schema=SCHEMA) if fk["name"]
    }


def _orphan_count(bind, table, col):
    """Rows whose parent id is not in `report`. Zero is the precondition."""
    insp = sa.inspect(bind)
    if not insp.has_table(table, schema=SCHEMA):
        return 0
    return bind.execute(
        sa.text(
            f"""
            SELECT count(*) FROM {SCHEMA}.{table} c
             WHERE c.{col} IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM {SCHEMA}.report r WHERE r.id = c.{col}
               )
            """
        )
    ).scalar()


def upgrade():
    bind = op.get_bind()

    # Pre-flight: report orphans by table before attempting anything, so a
    # failure names every offending table rather than only the first one
    # Postgres happens to reject.
    orphans = {}
    for table, _fk, cols, _od in REPOINTED_FKS:
        n = _orphan_count(bind, table, cols[0])
        if n:
            orphans[table] = n

    if orphans:
        detail = ", ".join(f"{t}={n}" for t, n in sorted(orphans.items()))
        raise RuntimeError(
            "Cannot re-point FKs to report.id — orphaned rows exist "
            f"({detail}). These reference an id with no matching `report` row. "
            "Run the ORPHAN ANALYSIS in migrations/"
            "r2a02_drop_report_v2_child_fks.sql to inspect them, and make sure "
            "the r3a03 one-off backfill has been applied."
        )

    for table, fk_name, cols, ondelete in REPOINTED_FKS:
        insp = sa.inspect(bind)
        if not insp.has_table(table, schema=SCHEMA):
            continue
        # Guarded: tolerate a partially-applied run.
        if fk_name in _existing_fk_names(bind, table):
            continue
        op.create_foreign_key(
            fk_name,
            table,
            "report",
            cols,
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete=ondelete,
        )


def downgrade():
    bind = op.get_bind()
    for table, fk_name, _cols, _od in reversed(REPOINTED_FKS):
        if fk_name in _existing_fk_names(bind, table):
            op.drop_constraint(fk_name, table, schema=SCHEMA, type_="foreignkey")
