"""STEP 3.5 (Unit 0e) — re-point report_cash_count.report_id at report.id

Revision ID: r8a08_repoint_rcc_fk
Revises: r7a07_backfill_actual_cash
Create Date: 2026-08-03

=============================================================================
WHAT THIS IS — AND WHY IT IS URGENT

`report_cash_count.report_id` still references `report_draft.id`.

r6a06 re-pointed the three draft children it knew about — shop_expense_draft,
report_cashcount_draft, report_history_draft — but report_cash_count was not
on that list. It is the NEW source-of-truth table for denominations, and it
was left pointing at the table the whole migration is retiring.

-----------------------------------------------------------------------------
THIS IS A LIVE BUG, NOT JUST STEP 4 HOUSEKEEPING

Step 2 stopped creating `report_draft` rows. So for any report created from
31 Jul 2026 onward there IS no draft row — and inserting its cash count
violates this FK:

    insert or update on table "report_cash_count" violates foreign key
    constraint "report_cash_count_report_id_fkey"

Reproduced against the live schema on 3 Aug 2026: create a `report` row with
no draft twin (the post-Step-2 shape), then insert a report_cash_count row —
it fails. **Saving a cash count on any newly created report raises
IntegrityError until this revision runs.**

It has not surfaced yet only because no report had been created since the
Step 2 deploy — every existing report still has its pre-flip draft twin.

This is the s6a06 failure mode inverted: there, code stopped writing something
the schema still demanded; here, the schema demands a parent row that code no
longer creates.

-----------------------------------------------------------------------------
WHY THE VALUES ARE ALREADY CORRECT

A draft and its report share one id (the invariant this whole consolidation
rests on), so every report_cash_count.report_id already holds a value that is
a valid report.id. Only the constraint's target changes — no data moves.

The pre-flight below proves that before touching the constraint, and aborts
rather than dropping an FK it cannot re-add.

-----------------------------------------------------------------------------
ORDER

Schema first, then code — this WIDENS what is accepted (report.id is a
superset of report_draft.id now that drafts have stopped being created), so
old code keeps working against the new constraint.

REVERSIBLE. downgrade() points it back at report_draft.id. That fails if a
count row's draft has since been deleted while its report survived — correct,
because such a row is exactly what the old constraint forbade.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r8a08_repoint_rcc_fk"
down_revision = "r7a07_backfill_actual_cash"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
TABLE = "report_cash_count"
COLUMN = "report_id"


def _has_table(bind, table):
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def _fks_referencing(bind, table, target):
    """Names of FKs on `table` that reference `target`. Discovered, not guessed."""
    return [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT con.conname
                  FROM pg_constraint con
                  JOIN pg_class cl   ON cl.oid  = con.conrelid
                  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
                  JOIN pg_class rcl  ON rcl.oid = con.confrelid
                 WHERE con.contype = 'f'
                   AND ns.nspname  = :schema
                   AND cl.relname  = :table
                   AND rcl.relname = :target
                """
            ),
            {"schema": SCHEMA, "table": table, "target": target},
        )
    ]


def _repoint(bind, target, new_target, ondelete):
    names = _fks_referencing(bind, TABLE, target)
    if not names:
        print(f"r8a08: {TABLE}.{COLUMN} does not reference {target}; nothing to do")
        return

    # Pre-flight: every value must already resolve against the NEW parent, or
    # the re-add fails after the drop and we are left with no constraint.
    orphans = bind.execute(
        sa.text(
            f"""
            SELECT count(*) FROM {SCHEMA}.{TABLE} c
             WHERE c.{COLUMN} IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM {SCHEMA}.{new_target} p WHERE p.id = c.{COLUMN})
            """
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"r8a08: {orphans} {TABLE} rows have no matching {new_target} row. "
            "Re-pointing would fail after the drop. Investigate before retrying "
            "— do NOT force past this."
        )
    print(f"r8a08: pre-flight OK, 0 orphans against {new_target}")

    for name in names:
        op.drop_constraint(name, TABLE, schema=SCHEMA, type_="foreignkey")
        print(f"r8a08: dropped {name}")

    op.create_foreign_key(
        f"{TABLE}_{COLUMN}_{new_target}_fkey",
        TABLE,
        new_target,
        [COLUMN],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete=ondelete,
    )
    print(f"r8a08: {TABLE}.{COLUMN} -> {new_target}.id (ON DELETE {ondelete})")


def upgrade():
    bind = op.get_bind()
    if not _has_table(bind, TABLE):
        print(f"r8a08: {TABLE} missing; nothing to do")
        return
    _repoint(bind, target="report_draft", new_target="report", ondelete="CASCADE")


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, TABLE):
        return
    if not _has_table(bind, "report_draft"):
        raise RuntimeError(
            "r8a08 downgrade: report_draft no longer exists (Step 4 ran). "
            "There is nothing to point back at."
        )
    _repoint(bind, target="report", new_target="report_draft", ondelete="CASCADE")
