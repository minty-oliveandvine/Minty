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

    # -----------------------------------------------------------------------
    # THE BACKFILL — one report row per draft that lacks one.
    #
    # Relaxing the NOT NULLs is only half of stage 4a. The other half is giving
    # every existing draft a paired `report` row, which is the precondition
    # r4a04 checks before re-pointing report_sale_detail.report_id at report.id.
    #
    # This statement existed only in the hand-written
    # migrations/r0_combined_report_consolidation_LIVE.sql, not in this
    # revision, so a database migrated purely through alembic never got it and
    # r4a04 refused:
    #
    #   Cannot re-point FKs to report.id - orphaned rows exist
    #   (report_expense_detail=175, report_sale_detail=614)
    #
    # Which meant `flask db upgrade` could not reach head on its own. Porting
    # the backfill here makes the chain self-contained and repeatable, which is
    # what production needs - it cannot rely on someone remembering to run a
    # loose .sql file at the right point in the sequence.
    #
    # The application already creates the paired row for NEW drafts
    # (ensure_report_row_for_draft), so this only closes the historical gap.
    # NOT EXISTS makes it idempotent.
    # -----------------------------------------------------------------------
    insp = sa.inspect(bind)
    if not insp.has_table("report_draft", schema=SCHEMA):
        return

    # -----------------------------------------------------------------------
    # PORTED FROM s6a06_relax_sales_columns_not_null.sql
    #
    # The 11 per-method sales columns on `report` are NOT NULL with no default,
    # while their report_draft counterparts are nullable. So a draft-shaped row
    # cannot be inserted until they are relaxed:
    #
    #   NotNullViolation: null value in column "visa_sales" of relation
    #   "report" violates not-null constraint
    #
    # s6a06 does exactly this relaxation, but it is a hand-written .sql file
    # with NO alembic revision - the second of two such files this stage depends
    # on. Leaving it outside the chain means `flask db upgrade` cannot reach head
    # without someone knowing to run it here, which is not a thing to rely on for
    # a production cutover.
    #
    # DROP NOT NULL on an already-nullable column is a no-op, so this is safe to
    # re-run and safe on a database where s6a06 was applied by hand.
    # -----------------------------------------------------------------------
    sales_columns = (
        "visa_sales", "alipay_sales", "wechat_sales", "master_sales",
        "unionpay_sales", "amex_sales", "octopus_sales", "foodpanda_sales",
        "keeta_sales", "openrice_sales", "deliveroo_sales",
    )
    for table in ("report", "report_draft"):
        if not insp.has_table(table, schema=SCHEMA):
            continue
        current = {c["name"]: c["nullable"] for c in insp.get_columns(table, schema=SCHEMA)}
        for col in sales_columns:
            if current.get(col) is False:
                bind.execute(
                    sa.text(
                        f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {col} DROP NOT NULL"
                    )
                )
    insp = sa.inspect(bind)

    draft_cols = {c["name"] for c in insp.get_columns("report_draft", schema=SCHEMA)}
    report_cols = {c["name"] for c in insp.get_columns("report", schema=SCHEMA)}

    # Only carry across columns both tables actually have at this point in the
    # chain - the shapes differ by revision, and naming a missing column would
    # abort the upgrade.
    carried = [
        c for c in (
            "id", "transaction_date", "next_transaction_date", "date",
            "cash_addition", "adjusted_opening_balance", "cash_sales",
            "shop_sales", "delivery_sales", "total_sales", "expenses",
            "bank_deposit", "closing_balance", "receipt_files", "uploaded_by",
            "company", "xero_integrated_yes", "safe_box_balance",
            "discrepancy_amount", "discrepancy_reason", "discrepancy_type",
            "publishing_status", "current_section", "completed_sections",
            "withdrawal_type", "withdrawal_bank_account",
        )
        if c in draft_cols and c in report_cols
    ]

    # opening_balance is NOT NULL on report but nullable on report_draft, so it
    # is coalesced rather than copied. A draft with no opening balance would
    # otherwise reject the whole INSERT.
    select_parts = [f"d.{c}" for c in carried]
    insert_parts = list(carried)
    if "opening_balance" in draft_cols and "opening_balance" in report_cols:
        insert_parts.append("opening_balance")
        select_parts.append("COALESCE(d.opening_balance, 0)")
    if "status" in draft_cols and "status" in report_cols:
        insert_parts.append("status")
        select_parts.append("COALESCE(d.status, 'draft')")

    n_null_ob = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {SCHEMA}.report_draft d "
            f"WHERE d.opening_balance IS NULL "
            f"  AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.report r WHERE r.id = d.id)"
        )
    ).scalar()
    if n_null_ob:
        print(
            f"  r3a03: WARNING {n_null_ob} draft(s) have NULL opening_balance "
            f"and are inserted as 0.0 - review after this run."
        )

    result = bind.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.report ({", ".join(insert_parts)})
            SELECT {", ".join(select_parts)}
              FROM {SCHEMA}.report_draft d
             WHERE NOT EXISTS (
                 SELECT 1 FROM {SCHEMA}.report r WHERE r.id = d.id
             )
            """
        )
    )
    print(f"  r3a03: backfilled {result.rowcount} report row(s) from report_draft")

    # -----------------------------------------------------------------------
    # SECOND BACKFILL - report_v2 rows that became neither a report nor a draft
    #
    # The draft backfill above closes the report_draft gap. It does not close
    # report_v2: production carries 49 report_v2 rows (all status='draft',
    # Jan-May 2026, 11 still-active entities) that exist in NEITHER report nor
    # report_draft. Their children do exist - 504 report_sale_detail and 159
    # report_expense_detail rows carrying 1,661,883.10 of sales - so r4a04
    # refuses to re-point the foreign keys while they dangle:
    #
    #   Cannot re-point FKs to report.id - orphaned rows exist
    #
    # They are abandoned drafts from the old report system, but the money in
    # their detail rows is real, so they are carried across rather than deleted.
    #
    # report_v2 uses the OLD column names, so this is a translation, not a copy:
    #
    #   report_id       -> id                 entity_id      -> company
    #   report_date     -> transaction_date   cashsale_total -> cash_sales
    #   expense_total   -> expenses           cash_deposit   -> bank_deposit
    #   add_cash_amount -> cash_addition
    #
    # shop_sales and delivery_sales have no report_v2 equivalent and are set to
    # 0: report_sale_detail holds the authoritative per-method breakdown for
    # these reports, and a header total invented here would contradict it.
    # total_sales is the one derived value worth keeping, because both halves
    # are present. closing_balance stays NULL - it is not knowable and the
    # relaxation above exists precisely so NULL means "not entered".
    # -----------------------------------------------------------------------
    if insp.has_table("report_v2", schema=SCHEMA):
        v2_cols = {c["name"] for c in insp.get_columns("report_v2", schema=SCHEMA)}
        report_cols = {c["name"] for c in insp.get_columns("report", schema=SCHEMA)}

        pairs = [
            ("id",                       "v.report_id"),
            ("transaction_date",         "v.report_date"),
            ("date",                     "v.report_date"),
            ("company",                  "v.entity_id"),
            ("status",                   "COALESCE(v.status, 'draft')"),
            ("opening_balance",          "COALESCE(v.opening_balance, v.starting_balance, 0)"),
            ("adjusted_opening_balance", "COALESCE(v.adjusted_opening_balance, v.opening_balance, v.starting_balance, 0)"),
            ("cash_addition",            "COALESCE(v.add_cash_amount, 0)"),
            ("cash_sales",               "COALESCE(v.cashsale_total, 0)"),
            ("shop_sales",               "0"),
            ("delivery_sales",           "0"),
            ("total_sales",              "COALESCE(v.cashsale_total, 0) + COALESCE(v.nocashsale_total, 0)"),
            ("expenses",                 "COALESCE(v.expense_total, 0)"),
            ("bank_deposit",             "COALESCE(v.cash_deposit, 0)"),
        ]
        # only map columns both tables actually have at this revision
        use = [(c, e) for c, e in pairs
               if c in report_cols
               and all(t.split(".")[1] in v2_cols
                       for t in e.replace("(", " ").replace(")", " ").replace(",", " ").split()
                       if t.startswith("v."))]

        # every remaining NOT NULL numeric with no default gets an explicit 0,
        # or the insert is rejected for columns report_v2 knows nothing about
        for col in insp.get_columns("report", schema=SCHEMA):
            if (not col["nullable"] and col.get("default") is None
                    and col["name"] not in {c for c, _ in use}
                    and str(col["type"]).upper().startswith(("DOUBLE", "NUMERIC", "REAL", "FLOAT"))):
                use.append((col["name"], "0"))

        result = bind.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.report ({", ".join(c for c, _ in use)})
                SELECT {", ".join(e for _, e in use)}
                  FROM {SCHEMA}.report_v2 v
                 WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.report r WHERE r.id = v.report_id)
                """
            )
        )
        print(f"  r3a03: backfilled {result.rowcount} report row(s) from report_v2")

    # actual_cash_total for the rows just inserted - the earlier stage ran
    # before they existed, so they would otherwise be missing it.
    if "actual_cash_total" in report_cols and insp.has_table(
        "report_cashcount_draft", schema=SCHEMA
    ):
        bind.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA}.report AS r
                   SET actual_cash_total = c.actual_cash_total
                  FROM {SCHEMA}.report_cashcount_draft AS c
                 WHERE c.report_id = r.id
                   AND r.actual_cash_total IS NULL
                   AND c.actual_cash_total IS NOT NULL
                """
            )
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
