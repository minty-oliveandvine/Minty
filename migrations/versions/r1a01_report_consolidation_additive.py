"""STAGE 1 — additive columns on `report` for the table consolidation

Revision ID: r1a01_report_additive
Revises: s7a07_cash_method
Create Date: 2026-07-31

=============================================================================
WHAT THIS IS

The first schema step of folding these tables into `report`:

    report_draft            -> report (status='draft')
    report_v2               -> report
    report_expense_detail   -> shop_expense
    report_cashcount_draft  -> report_cash_count (+ actual_cash_total here)
    shop_expense_draft      -> shop_expense
    report_detail           -> report

This revision is PURELY ADDITIVE. It adds six nullable columns to `report`
and backfills them. Nothing reads these columns yet — the code changes land
in later stages. Deploying this alone is a no-op for running application
behaviour, which is the point: it is safe to ship ahead of the code.

-----------------------------------------------------------------------------
WHY EVERY COLUMN IS NULLABLE

s6a06 is the cautionary tale. Eleven columns were NOT NULL with no DEFAULT;
the moment code stopped writing them, every INSERT into `report` failed with
NotNullViolation and report submission was down until the constraint was
relaxed. There is no NOT NULL here. `status` gets a server_default so rows
inserted by not-yet-updated code still land in a sane state, but the column
stays nullable so an omitted value can never reject a row.

-----------------------------------------------------------------------------
WHY THE BACKFILL IS A SIMPLE JOIN ON id

`report`, `report_draft`, `report_cashcount_draft` and `report_detail` all
share ONE identity:

    Report.id == ReportDraft.id                (ending.py:387, :712)
    ReportCashCountDraft.report_id == draft.id (report_cash_count_draft.py:10)
    ReportDetail.report_id == draft.id         (cash_count.py:391, :436)
    ReportV2.report_id == draft.id             (sales.py:747-750)

So this is a join on the primary key, not a remap by (entity, transaction_date)
the way the pettycash_test migration in 03_data_reports.sql has to do it. No
dedup, no surrogate-key recovery, no ambiguity about which row wins.

-----------------------------------------------------------------------------
COLUMNS ADDED

  status                    <- report_draft.status ('draft'|'posted')
                               `report` has no status column today; ending.py
                               :506-510 already assigns report.status on a
                               query Row, which is a no-op until this exists.
  current_section           <- report_draft.current_section
  completed_sections        <- report_draft.completed_sections (JSON)
  withdrawal_type           <- report_draft.withdrawal_type
                               NOTE: download.py:350 and :586 already do
                               getattr(report, "withdrawal_type", None), which
                               returns None today. Adding the column makes that
                               personal/company branch reachable. Backfilling it
                               here (rather than leaving NULL) is what keeps it
                               correct when it wakes up.
  withdrawal_bank_account   <- report_draft.withdrawal_bank_account
  actual_cash_total         <- report_cashcount_draft.actual_cash_total
                               The one genuinely non-redundant column on that
                               table: create.py:288 and opening.py:1044 seed the
                               NEXT report's opening balance from it. Losing it
                               breaks the report chain.

report_detail's columns (opening_balance, adjusted_opening_balance,
cashsale_total, nocashsale_total, expense_total, discrepancy_amount,
discrepancy_description) are NOT added — `report` already carries equivalents.
Only discrepancy_description has no exact counterpart; it duplicates
report.discrepancy_reason and is backfilled into it where report's is empty.

-----------------------------------------------------------------------------
REVERSIBLE. downgrade() drops the six columns. Data added by the backfill is
recoverable from the source tables, which this revision does not touch.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r1a01_report_additive"
down_revision = "s7a07_cash_method"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (column_name, type) — all nullable, all added to `report`
NEW_COLUMNS = [
    ("status", sa.String(length=20)),
    ("current_section", sa.String(length=20)),
    ("completed_sections", sa.JSON()),
    ("withdrawal_type", sa.String(length=20)),
    ("withdrawal_bank_account", sa.String(length=36)),
    ("actual_cash_total", sa.Float()),
]


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name, schema=SCHEMA)


def _column_names(bind, table):
    if not _has_table(bind, table):
        return set()
    return {c["name"] for c in sa.inspect(bind).get_columns(table, schema=SCHEMA)}


def upgrade():
    bind = op.get_bind()
    existing = _column_names(bind, "report")

    # ---------------------------------------------------------------
    # 1. Add the columns. Guarded so a partially-applied run is safe.
    # ---------------------------------------------------------------
    for name, type_ in NEW_COLUMNS:
        if name in existing:
            continue
        server_default = sa.text("'posted'") if name == "status" else None
        op.add_column(
            "report",
            sa.Column(name, type_, nullable=True, server_default=server_default),
            schema=SCHEMA,
        )

    # ---------------------------------------------------------------
    # 2. Backfill from report_draft (joined on the shared id).
    #
    #    COALESCE so a re-run does not clobber values already written.
    #    Rows with no matching draft keep status='posted' from the
    #    server_default — a Report with no draft is a submitted report
    #    (create.py:148 mints one directly).
    # ---------------------------------------------------------------
    if _has_table(bind, "report_draft"):
        draft_cols = _column_names(bind, "report_draft")
        mapping = [
            ("status", "status"),
            ("current_section", "current_section"),
            ("completed_sections", "completed_sections"),
            ("withdrawal_type", "withdrawal_type"),
            ("withdrawal_bank_account", "withdrawal_bank_account"),
        ]
        sets = [
            f"{tgt} = COALESCE(r.{tgt}, d.{src})"
            for tgt, src in mapping
            if src in draft_cols
        ]
        if sets:
            op.execute(
                f"""
                UPDATE {SCHEMA}.report AS r
                   SET {", ".join(sets)}
                  FROM {SCHEMA}.report_draft AS d
                 WHERE d.id = r.id
                """
            )

    # ---------------------------------------------------------------
    # 3. Backfill actual_cash_total from report_cashcount_draft.
    #    This is the column that seeds the next report's opening balance.
    # ---------------------------------------------------------------
    if _has_table(bind, "report_cashcount_draft"):
        op.execute(
            f"""
            UPDATE {SCHEMA}.report AS r
               SET actual_cash_total = COALESCE(r.actual_cash_total, c.actual_cash_total)
              FROM {SCHEMA}.report_cashcount_draft AS c
             WHERE c.report_id = r.id
            """
        )

    # ---------------------------------------------------------------
    # 4. report_detail.discrepancy_description -> report.discrepancy_reason,
    #    but ONLY where report's own value is empty. report is authoritative.
    #    report_detail's PK is (report_id, entity_id); a report belongs to one
    #    entity, so the join cannot fan out, but DISTINCT ON guards anyway.
    # ---------------------------------------------------------------
    if _has_table(bind, "report_detail"):
        op.execute(
            f"""
            UPDATE {SCHEMA}.report AS r
               SET discrepancy_reason = d.discrepancy_description
              FROM (
                    SELECT DISTINCT ON (report_id) report_id, discrepancy_description
                      FROM {SCHEMA}.report_detail
                     WHERE discrepancy_description IS NOT NULL
                       AND discrepancy_description <> ''
                     ORDER BY report_id, entity_id
                   ) AS d
             WHERE d.report_id = r.id
               AND (r.discrepancy_reason IS NULL OR r.discrepancy_reason = '')
            """
        )

    # ---------------------------------------------------------------
    # 5. Drop the server_default now that the backfill has run. Keeping it
    #    would silently mark future INSERTs 'posted'; Stage 4 sets status
    #    explicitly. The column stays nullable either way.
    # ---------------------------------------------------------------
    if "status" not in existing:
        op.alter_column("report", "status", server_default=None, schema=SCHEMA)


def downgrade():
    bind = op.get_bind()
    existing = _column_names(bind, "report")
    for name, _type in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column("report", name, schema=SCHEMA)
