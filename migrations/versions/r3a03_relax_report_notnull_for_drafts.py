"""STAGE 4a — relax report NOT NULLs so a draft can be a report row

Revision ID: r3a03_relax_report_nn
Revises: r2a02_drop_v2_fks
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

Stage 4a makes a `report` row exist from DRAFT CREATION rather than only from
submit. That is the precondition Stage 3 needs: it re-points
report_sale_detail.report_id (and friends) at report.id, which is only
satisfiable once every detail row's parent id exists in `report`. Detail rows
are written all through data entry, long before submit.

`report` currently has five NOT NULL columns with no default:

    transaction_date   known at draft creation  (opening.py:742)
    opening_balance    known at draft creation
    company            known at draft creation
    expenses           NOT known yet   <-- blocker
    closing_balance    NOT known yet   <-- blocker

expenses is only determined at the expense step; closing_balance is derived
from it. Inserting a report row at draft creation therefore fails on those two
today. This revision makes exactly those two nullable.

-----------------------------------------------------------------------------
WHY NOT JUST DEFAULT THEM TO 0.0

Because 0.0 is a lie that survives. A report whose expenses are genuinely zero
and one whose expenses have not been entered yet would become
indistinguishable the moment the column is written, and closing_balance = 0.0
reads as a real balance to every downstream sum. NULL says "not entered yet",
which is the truth during data entry, and the existing readers already
COALESCE — recalculate_report (services/shared.py) does `expenses or 0.0` and
`bank_deposit or 0.0` before arithmetic.

The draft columns this mirrors are already nullable: report_draft.expenses is
`nullable=True` (report_draft.py:22) and report_draft.closing_balance likewise
(:24). So this brings `report` in line with the table it is absorbing, rather
than inventing a new convention.

-----------------------------------------------------------------------------
WHY THIS IS THE SAFE DIRECTION

Relaxing NOT NULL can never reject a row that used to be accepted — every
existing INSERT keeps working unchanged. This is the exact inverse of the
s6a06 incident, where columns were left NOT NULL with no default while the
code stopped writing them and every report submission failed. Widening first,
then narrowing the writers, is the order that has no failure window.

The columns are NOT dropped and no data is touched. Existing rows keep their
values; only the constraint changes.

-----------------------------------------------------------------------------
WHAT THIS DOES NOT DO

It does not create any report rows, and it does not change any code path. On
its own it is invisible to the running application — deliberately, so it can
ship ahead of the code that starts inserting draft-shaped report rows.

-----------------------------------------------------------------------------
REVERSIBLE, WITH ONE CONDITION. downgrade() restores NOT NULL, which fails if
any row now holds NULL in those columns — i.e. if draft-shaped report rows
exist. That is correct: those rows are precisely what the constraint forbids.
Backfill them to 0.0 first if you genuinely need to roll back; the DOWN
section of the .sql twin shows the statement.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r3a03_relax_report_nn"
down_revision = "r2a02_drop_v2_fks"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Only the two that are unknowable at draft creation. transaction_date,
# opening_balance and company stay NOT NULL — they are all known at that point
# and keeping them constrained preserves a real guarantee.
RELAX_COLUMNS = [
    ("expenses", sa.Float()),
    ("closing_balance", sa.Float()),
]


def _nullable_map(bind, table):
    insp = sa.inspect(bind)
    if not insp.has_table(table, schema=SCHEMA):
        return {}
    return {c["name"]: c["nullable"] for c in insp.get_columns(table, schema=SCHEMA)}


def upgrade():
    bind = op.get_bind()
    nullable = _nullable_map(bind, "report")
    for name, type_ in RELAX_COLUMNS:
        # Guarded: a no-op if already nullable, so a re-run is harmless.
        if nullable.get(name) is False:
            op.alter_column(
                "report", name, existing_type=type_, nullable=True, schema=SCHEMA
            )


def downgrade():
    bind = op.get_bind()
    nullable = _nullable_map(bind, "report")
    for name, type_ in reversed(RELAX_COLUMNS):
        if nullable.get(name) is True:
            # Fails loudly if draft-shaped rows (NULL expenses) exist. That is
            # the intended behaviour — see the module docstring.
            op.alter_column(
                "report", name, existing_type=type_, nullable=False, schema=SCHEMA
            )
