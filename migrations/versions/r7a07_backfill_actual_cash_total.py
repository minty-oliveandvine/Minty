"""STEP 3.5 (Unit 0b) — backfill report.actual_cash_total from the draft table

Revision ID: r7a07_backfill_actual_cash
Revises: r6a06_repoint_draft_fks
Create Date: 2026-08-03

=============================================================================
WHAT THIS IS

`report.actual_cash_total` was added by r1a01, which hoisted it off
`report_cashcount_draft`. opening.py:1116 reads it in preference to the draft
table, and create.py now does the same.

It has never had a writer.

Every assignment in the application targeted `cashcount_draft`
(cash_count.py:376 / :419 / :459), never `current_draft` — and the draft->report
mirror explicitly excluded this column ("that column exists on `report` only").
So the preferred read has always found NULL and fallen through to
report_cashcount_draft. The preference was dead code that never once took its
primary branch.

Two things fix that, and BOTH are required:

  * cash_count.py now assigns `current_draft.actual_cash_total` in both
    branches (Step 3.5, Unit 0a) — covers everything written from now on.
  * this revision — covers everything already in the table.

-----------------------------------------------------------------------------
WHY IT MATTERS

actual_cash_total seeds the NEXT report's opening balance whenever the previous
report has no closing_balance. Step 3.5 deletes the writes to
report_cashcount_draft and Step 4 drops the table; without this backfill plus
Unit 0a, that opening balance silently becomes 0 for the affected reports.

Silently. There is no exception — just a wrong number, which is this
migration's characteristic failure mode.

-----------------------------------------------------------------------------
GUARD RULE — fill NULLs only

    ... AND r.actual_cash_total IS NULL

A report whose `report` row already carries a value is left alone. That makes
this idempotent, and means it can never overwrite a value written by the
Unit 0a code with an older one from the draft table.

Rows where the draft's value is NULL are skipped too — copying NULL over NULL
is a no-op that would only inflate the reported row count.

-----------------------------------------------------------------------------
REVERSIBLE, in the sense that matters.

downgrade() cannot distinguish a value this revision copied from one the
application has written since, so it does NOT null the column out — that would
destroy live data to undo a backfill. It is a deliberate no-op; see the note
there. The column itself is dropped by r1a01's downgrade if you need it gone.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r7a07_backfill_actual_cash"
down_revision = "r6a06_repoint_draft_fks"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def _has_table(bind, table):
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def upgrade():
    bind = op.get_bind()

    # Both tables must exist. report_cashcount_draft is dropped in Step 4, so
    # a re-run after that point is a no-op rather than an error.
    if not _has_table(bind, "report_cashcount_draft"):
        print("r7a07: report_cashcount_draft is gone (Step 4 ran); nothing to do")
        return
    if not _has_table(bind, "report"):
        raise RuntimeError("r7a07: pettycashv2.report is missing")

    before = bind.execute(
        sa.text(
            f"""
            SELECT count(*)
              FROM {SCHEMA}.report_cashcount_draft c
              JOIN {SCHEMA}.report r ON r.id = c.report_id
             WHERE c.actual_cash_total IS NOT NULL
               AND r.actual_cash_total IS NULL
            """
        )
    ).scalar()
    print(f"r7a07: {before} report rows missing actual_cash_total")

    if not before:
        print("r7a07: nothing to backfill")
        return

    bind.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.report r
               SET actual_cash_total = c.actual_cash_total
              FROM {SCHEMA}.report_cashcount_draft c
             WHERE c.report_id = r.id
               AND c.actual_cash_total IS NOT NULL
               AND r.actual_cash_total IS NULL
            """
        )
    )

    after = bind.execute(
        sa.text(
            f"""
            SELECT count(*)
              FROM {SCHEMA}.report_cashcount_draft c
              JOIN {SCHEMA}.report r ON r.id = c.report_id
             WHERE c.actual_cash_total IS NOT NULL
               AND r.actual_cash_total IS NULL
            """
        )
    ).scalar()
    print(f"r7a07: backfilled {before - after} rows; {after} remaining")

    if after:
        raise RuntimeError(
            f"r7a07: {after} rows still missing actual_cash_total after the "
            "backfill — the UPDATE did not cover them. Investigate before "
            "proceeding to Step 4."
        )


def downgrade():
    """Deliberate no-op.

    Nulling report.actual_cash_total would destroy values the application has
    written since (cash_count.py assigns it on every save from Unit 0a
    onwards), and there is no way to tell those apart from the ones copied
    here. Undoing a fill-only backfill is not worth losing live data over.
    """
    print("r7a07: downgrade is a no-op by design — see the docstring")
