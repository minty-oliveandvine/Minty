"""STAGE 2a — drop the FK constraints that pin the report_v2 children

Revision ID: r2a02_drop_v2_fks
Revises: r1a01_report_additive
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

Stage 2 of the consolidation is "stop writing report_v2". That cannot happen
while these FK constraints exist, because they are the *reason* the writes
exist.

Four tables FK report_v2.report_id today (a7b8c9d0e1f2 made them CASCADE):

    report_sale_detail.report_id      -> report_v2.report_id
    report_expense_detail.report_id   -> report_v2.report_id
    xero_report_sync.report_id        -> report_v2.report_id
    xero_bank_transfer.sync_report_id -> report_v2.report_id

(report_cash_detail and report_history_v2 also FK'd it; both were dead code
and their tables/models were removed in Stage 0.)

-----------------------------------------------------------------------------
WHY THIS MUST COME BEFORE REMOVING THE WRITES

There are seven sites that create a ReportV2 row — sales.py:443/:606/:764,
expense.py:527, deposit.py:277, api.py:442/:743. Not one of them exists
because anything READS report_v2. Nothing does: the only reader,
display_deposit_balance() (entity/services/shared.py:246), is never called
from anywhere, and its `Date == datetime` comparison would return None even
if it were. update_report_after_deposit_change() (report/services/shared.py:836)
only writes.

Every one of those sites is the same shape:

    report_v2 = ReportV2.query.filter_by(report_id=draft.id).first()
    if not report_v2:
        report_v2 = ReportV2(...)      # <- purely so the FK below resolves
        db.session.add(report_v2)
    ...
    db.session.add(ReportSaleDetail(report_id=report_v2.report_id, ...))

i.e. "manufacture a parent so the child insert does not violate the
constraint". Delete the writes with the FK still in place and the very next
sales or expense entry on a new draft raises ForeignKeyViolation. That is the
s6a06 failure mode exactly: code stops writing something the live schema
still demands.

-----------------------------------------------------------------------------
WHY THE FKs CANNOT SIMPLY BE RE-POINTED AT report.id INSTEAD

They will be, in Stage 3 — but not yet. A draft does not get a `report` row
until it is SUBMITTED (ending.py:1418). Detail rows are written during data
entry, long before that. Re-pointing now would fail for every in-progress
draft. Stage 4 makes a report row exist from draft creation onward; only then
can Stage 3 add the constraint back against report.id.

So this revision leaves the columns as plain, unconstrained columns for one
stage. That is a deliberate, temporary loosening.

-----------------------------------------------------------------------------
WHAT IS NOT LOST

The VALUES do not change. report_v2.report_id is the draft id, which is the
report id (sales.py:747-750, ending.py:1418-1419), so every child row already
carries the id Stage 3 will constrain it to. Dropping a constraint deletes no
data.

What IS given up for one stage is the CASCADE: deleting a report_v2 row no
longer auto-deletes its detail rows. The one code path that relies on this,
_delete_report_v2_cascade() (report_detail.py:374-381), does not — it already
deletes each child explicitly, in order, before the parent. Verified: that
function names ReportExpenseDetail, ReportSaleDetail, XeroReportSync and
XeroBankTransfer individually. So the app-level delete is unaffected.

-----------------------------------------------------------------------------
REVERSIBLE. downgrade() recreates all four constraints exactly as
a7b8c9d0e1f2 defined them (CASCADE, same names). It will fail if orphaned
child rows have accumulated in the meantime — which is correct: that is
data the constraint would have forbidden, and it needs looking at rather
than silently re-constraining.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r2a02_drop_v2_fks"
down_revision = "r1a01_report_additive"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (table, constraint_name, local_cols) — all reference report_v2.report_id.
# Names come from a7b8c9d0e1f2, which created them.
V2_CHILD_FKS = [
    ("report_sale_detail", "report_sale_detail_report_id_fkey", ["report_id"]),
    ("report_expense_detail", "report_expense_detail_report_id_fkey", ["report_id"]),
    ("xero_report_sync", "xero_report_sync_report_id_fkey", ["report_id"]),
    ("xero_bank_transfer", "xero_bank_transfer_sync_report_id_fkey", ["sync_report_id"]),
]


def _existing_fk_names(bind, table):
    insp = sa.inspect(bind)
    if not insp.has_table(table, schema=SCHEMA):
        return set()
    return {
        fk["name"] for fk in insp.get_foreign_keys(table, schema=SCHEMA) if fk["name"]
    }


def upgrade():
    bind = op.get_bind()
    for table, fk_name, _cols in V2_CHILD_FKS:
        # Guarded: tolerate a partially-applied run, or an environment where
        # the constraint was already dropped by hand.
        if fk_name in _existing_fk_names(bind, table):
            op.drop_constraint(fk_name, table, schema=SCHEMA, type_="foreignkey")


def downgrade():
    bind = op.get_bind()
    for table, fk_name, cols in V2_CHILD_FKS:
        if fk_name in _existing_fk_names(bind, table):
            continue
        insp = sa.inspect(bind)
        if not insp.has_table(table, schema=SCHEMA):
            continue
        op.create_foreign_key(
            fk_name,
            table,
            "report_v2",
            cols,
            ["report_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )
