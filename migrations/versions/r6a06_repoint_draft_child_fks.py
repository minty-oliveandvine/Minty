"""STAGE 4b — re-point the report_draft children at report.id

Revision ID: r6a06_repoint_draft_fks
Revises: r5a05_backfill_expense
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

Three tables still FK report_draft.id:

    shop_expense_draft.report_draft_id  -> report_draft.id
    report_cashcount_draft.report_id    -> report_draft.id   (CASCADE)
    report_history_draft.report_draft_id-> report_draft.id   (CASCADE)

They are the last thing pinning report_draft, and they are why the write flip
cannot happen: "point writes at `report` instead of report_draft" means draft
rows stop being created, and the very next insert into any of these three
violates its FK. That is the s6a06 failure mode exactly — code ceasing to
write something the schema still demands.

This revision re-points all three at report.id.

-----------------------------------------------------------------------------
WHY THE VALUES ARE ALREADY CORRECT

A draft and its report share one id, and since Stage 4a the `report` row
exists from draft creation (ensure_report_row_for_draft) with the r0 backfill
covering everything older. So every one of these columns already holds a value
that is a valid report.id — only the constraint's target changes.

Unlike r2a02 -> r4a04 there is no unconstrained interval here. The parent rows
already exist, so the FKs can be dropped and recreated in one transaction.

-----------------------------------------------------------------------------
CONSTRAINT NAMES ARE DISCOVERED, NOT ASSUMED

These FKs were created inline by 0001_full_schema / f731e24bfe62 without
explicit names, so Postgres auto-generated them. Rather than hardcode a guess
that silently matches nothing, upgrade() reads pg_constraint and drops
whatever actually references report_draft from each table.

-----------------------------------------------------------------------------
ON DELETE

Preserved per table: report_cashcount_draft and report_history_draft keep
CASCADE (a report's cash count and history die with it); shop_expense_draft
had none and keeps none, matching shop_expense, whose rows are deleted
explicitly by the delete flow.

-----------------------------------------------------------------------------
GUARDED. upgrade() counts orphans per table BEFORE touching anything and
aborts naming all of them, rather than letting Postgres reject on whichever it
reaches first.

REVERSIBLE. downgrade() points them back at report_draft.id. That fails if a
child row's draft has since been deleted while its report survived — correct,
because such a row is exactly what the old constraint forbade.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r6a06_repoint_draft_fks"
down_revision = "r5a05_backfill_expense"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (table, local_column, ondelete)
DRAFT_CHILD_FKS = [
    ("shop_expense_draft", "report_draft_id", None),
    ("report_cashcount_draft", "report_id", "CASCADE"),
    ("report_history_draft", "report_draft_id", "CASCADE"),
]


def _has_table(bind, table):
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def _fks_referencing(bind, table, target):
    """Names of FKs on `table` that reference `target`. Discovered, not guessed."""
    if not _has_table(bind, table):
        return []
    return [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT con.conname
                  FROM pg_constraint con
                  JOIN pg_class      cl  ON cl.oid  = con.conrelid
                  JOIN pg_namespace  ns  ON ns.oid  = cl.relnamespace
                  JOIN pg_class      rcl ON rcl.oid = con.confrelid
                 WHERE con.contype = 'f'
                   AND ns.nspname  = :schema
                   AND cl.relname  = :table
                   AND rcl.relname = :target
                """
            ),
            {"schema": SCHEMA, "table": table, "target": target},
        )
    ]


def _orphans(bind, table, col):
    if not _has_table(bind, table):
        return 0
    return bind.execute(
        sa.text(
            f"""
            SELECT count(*) FROM {SCHEMA}.{table} c
             WHERE c.{col} IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.report r WHERE r.id = c.{col})
            """
        )
    ).scalar()


def upgrade():
    bind = op.get_bind()

    # Pre-flight: name every offending table, not just the first one Postgres
    # happens to reject.
    bad = {
        t: n
        for t, col, _od in DRAFT_CHILD_FKS
        if (n := _orphans(bind, t, col))
    }
    if bad:
        detail = ", ".join(f"{t}={n}" for t, n in sorted(bad.items()))
        raise RuntimeError(
            "Cannot re-point the report_draft children at report.id — orphaned "
            f"rows exist ({detail}). These reference an id with no matching "
            "`report` row. Confirm the r0 backfill (PART 3) has been applied."
        )

    for table, col, ondelete in DRAFT_CHILD_FKS:
        if not _has_table(bind, table):
            continue
        for name in _fks_referencing(bind, table, "report_draft"):
            op.drop_constraint(name, table, schema=SCHEMA, type_="foreignkey")
        # Skip if something already points this column at `report`.
        if _fks_referencing(bind, table, "report"):
            continue
        op.create_foreign_key(
            f"{table}_{col}_report_fkey",
            table,
            "report",
            [col],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete=ondelete,
        )


def downgrade():
    bind = op.get_bind()
    for table, col, ondelete in reversed(DRAFT_CHILD_FKS):
        if not _has_table(bind, table):
            continue
        for name in _fks_referencing(bind, table, "report"):
            op.drop_constraint(name, table, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{col}_fkey",
            table,
            "report_draft",
            [col],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete=ondelete,
        )
