"""STEP 4c — drop the seven legacy report tables. IRREVERSIBLE.

Revision ID: r10a10_drop_legacy_report
Revises: r9a09_reshape_xero_pks
Create Date: 2026-08-03

=============================================================================
TAKE A BACKUP BEFORE RUNNING THIS. downgrade() recreates the tables EMPTY.
There is no way to get the rows back without one.

    pg_dump -n pettycashv2 -Fc -f pre_r10a10.dump <db>

-----------------------------------------------------------------------------
WHAT THIS IS

The end of the report consolidation. Seven tables, none of which has any
reader or writer left after Steps 2, 3, 3.5 and 4a/4b:

    report_history_draft     no writers since the log_history_draft deletion (4a-4)
    shop_expense_draft       no writers since Step 3, no readers since 4a-3
    report_cashcount_draft   no writers since Step 3.5, no readers since 4a-5
    report_expense_detail    no writers or readers since Step 3.5
    report_detail            no writers since Step 3.5; never had a reader
    report_draft             no writers since Step 2, no readers since 4a-6
    report_v2                no writers since r2a02, no readers since 4a-2

The models were deleted in 4b. `import main` configures every mapper without
error, which is the cheapest proof that nothing still points at them.

-----------------------------------------------------------------------------
ORDER: children before parents

report_cash_count used to FK report_draft, which would have made dropping
report_draft fail — that was fixed in r8a08 (it now FKs report.id). The
pre-flight below re-checks that class of dependency generically rather than
trusting this list.

Bare DROP TABLE, never CASCADE. If a drop fails on a dependency, that
dependency is something the pre-flight missed and you want to know about it,
not have it silently removed along with the table.

-----------------------------------------------------------------------------
PRE-FLIGHT — aborts the whole transaction on any failure

    P1  no report would lose actual_cash_total   (r7a07 must have run)
    P2  no cash count exists ONLY as wide columns, with a NON-ZERO total
    P3  no FK from a surviving table references any of the seven
    P4  no view or materialized view depends on any of the seven

P2 deliberately tests the column TOTAL, not "is any column NOT NULL".
save_cash_count_details stores no row for a denomination counted as zero, so an
all-zero cash count legitimately has no report_cash_count rows while its wide
columns are 0 rather than NULL. The naive form reports those as data loss; they
are not. Only a non-zero total is a real gap.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r10a10_drop_legacy_report"
down_revision = "r9a09_reshape_xero_pks"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# children before parents
DROP_ORDER = [
    "report_history_draft",
    "shop_expense_draft",
    "report_cashcount_draft",
    "report_expense_detail",
    "report_detail",
    "report_draft",
    "report_v2",
]

# PART 0 — two more report_v2 children that the runbook believed were already
# gone. r0's PART 2 header states: "report_cash_detail and report_history_v2
# also FK'd report_v2 — both were dead and were removed in Stage 0". They were
# NOT removed, at least not everywhere: both were still present with live FKs
# to report_v2 when r10a10 was first run (3 Aug 2026), and P3 blocked the drop.
#
# Both are unmapped by the application (no model, no query, no reference
# outside migration files) and existed only as report_v2 children. They are
# dropped here, ahead of the seven, with an emptiness guard — if either has
# rows, something uses them after all and this aborts rather than guessing.
ORPHAN_V2_CHILDREN = ["report_cash_detail", "report_history_v2"]


def _existing(bind):
    insp = sa.inspect(bind)
    return [t for t in DROP_ORDER if insp.has_table(t, schema=SCHEMA)]


def upgrade():
    bind = op.get_bind()
    present = _existing(bind)
    if not present:
        print("r10a10: none of the seven tables exist; nothing to do")
        return
    print(f"r10a10: {len(present)} of 7 tables present: {', '.join(present)}")

    # ---- P1 -----------------------------------------------------------
    if "report_cashcount_draft" in present:
        lost = bind.execute(
            sa.text(
                f"""
                SELECT count(*) FROM {SCHEMA}.report_cashcount_draft c
                  JOIN {SCHEMA}.report r ON r.id = c.report_id
                 WHERE c.actual_cash_total IS NOT NULL
                   AND r.actual_cash_total IS NULL
                """
            )
        ).scalar()
        if lost:
            raise RuntimeError(
                f"r10a10 P1: {lost} reports would lose actual_cash_total. "
                "Run r7a07 first — it seeds the NEXT report's opening balance, "
                "and losing it fails silently as a wrong number."
            )
        print("r10a10: P1 OK — no report loses actual_cash_total")

        # ---- P2 -------------------------------------------------------
        wide_only = bind.execute(
            sa.text(
                f"""
                SELECT count(*) FROM {SCHEMA}.report_cashcount_draft c
                 WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.report_cash_count rc
                                    WHERE rc.report_id = c.report_id)
                   AND (COALESCE(c.thousand_note,0)*1000
                      + COALESCE(c.fivehundred_note,0)*500
                      + COALESCE(c.onehundred_note,0)*100
                      + COALESCE(c.fifty_note,0)*50
                      + COALESCE(c.twenty_note,0)*20
                      + COALESCE(c.ten_note,0)*10
                      + COALESCE(c.five_coin,0)*5
                      + COALESCE(c.two_coin,0)*2
                      + COALESCE(c.one_coin,0)*1) > 0
                """
            )
        ).scalar()
        if wide_only:
            raise RuntimeError(
                f"r10a10 P2: {wide_only} cash counts exist ONLY as wide columns "
                "with a non-zero total. c2a02 backfilled HKD only. Migrate "
                "them into report_cash_count before dropping, or those reports "
                "silently read as zero."
            )
        print("r10a10: P2 OK — no wide-column-only cash counts with a non-zero total")

    # ---- PART 0: the two orphan report_v2 children ------------------------
    insp = sa.inspect(bind)
    for table in ORPHAN_V2_CHILDREN:
        if not insp.has_table(table, schema=SCHEMA):
            continue
        n = bind.execute(sa.text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar()
        if n:
            raise RuntimeError(
                f"r10a10 PART 0: {table} has {n} rows. The runbook records it as "
                "dead and removed in Stage 0, but it is present AND populated — "
                "so something writes it. Investigate before dropping; do NOT "
                "force past this."
            )
        op.drop_table(table, schema=SCHEMA)
        print(f"r10a10: dropped orphan report_v2 child {table} (0 rows)")

    # ---- P3 ---------------------------------------------------------------
    rows = bind.execute(
        sa.text(
            """
            SELECT cl.relname AS child, con.conname, rcl.relname AS parent
              FROM pg_constraint con
              JOIN pg_class cl      ON cl.oid  = con.conrelid
              JOIN pg_namespace ns  ON ns.oid  = cl.relnamespace
              JOIN pg_class rcl     ON rcl.oid = con.confrelid
             WHERE con.contype = 'f'
               AND ns.nspname = :schema
               AND rcl.relname = ANY(:targets)
               AND cl.relname <> ALL(:targets)
            """
        ),
        {"schema": SCHEMA, "targets": DROP_ORDER},
    ).fetchall()
    if rows:
        detail = "; ".join(f"{c}.{n} -> {p}" for c, n, p in rows)
        raise RuntimeError(
            f"r10a10 P3: a surviving table still references one of the seven: "
            f"{detail}. Re-point it first (see r8a08 for the pattern)."
        )
    print("r10a10: P3 OK — no surviving table references any of the seven")

    # ---- P4 ---------------------------------------------------------------
    views = bind.execute(
        sa.text(
            """
            SELECT DISTINCT dependent.relname, dependent.relkind
              FROM pg_depend d
              JOIN pg_rewrite rw   ON rw.oid = d.objid
              JOIN pg_class dependent ON dependent.oid = rw.ev_class
              JOIN pg_class source ON source.oid = d.refobjid
              JOIN pg_namespace ns ON ns.oid = source.relnamespace
             WHERE ns.nspname = :schema
               AND source.relname = ANY(:targets)
               AND dependent.relkind IN ('v', 'm')
               AND dependent.relname <> ALL(:targets)
            """
        ),
        {"schema": SCHEMA, "targets": DROP_ORDER},
    ).fetchall()
    if views:
        detail = ", ".join(f"{n} ({'matview' if k == 'm' else 'view'})" for n, k in views)
        raise RuntimeError(
            f"r10a10 P4: view(s) depend on tables being dropped: {detail}. "
            "This is exactly the Supabase-view case the Step 3.5 notes flagged "
            "for report_detail. Re-point or drop them first."
        )
    print("r10a10: P4 OK — no view depends on the seven")

    # ---- P5 -------------------------------------------------------------
    # Sequences owned by the seven, borrowed by a table in ANOTHER schema.
    #
    # P3 only looks at foreign keys, which is not the only way something can
    # depend on a table. A schema copied with CREATE TABLE ... (LIKE ...) or a
    # hand-rolled clone keeps its columns pointing at the ORIGINAL sequences,
    # so `DROP TABLE` fails with DependentObjectsStillExist part-way through.
    #
    # Found on prestaging (4 Aug 2026): pettycashv2_clone.report_history_draft
    # borrowed pettycashv2.report_history_draft_id_seq. The drop failed at the
    # first table and rolled back — correct, but the pre-flight should have
    # said so before starting.
    borrowers = bind.execute(
        sa.text(
            """
            SELECT cn.nspname || '.' || c.relname AS borrower, s.relname AS seq
              FROM pg_depend d
              JOIN pg_class s      ON s.oid = d.refobjid AND s.relkind = 'S'
              JOIN pg_namespace sn ON sn.oid = s.relnamespace AND sn.nspname = :schema
              JOIN pg_attrdef ad   ON ad.oid = d.objid
              JOIN pg_class c      ON c.oid = ad.adrelid
              JOIN pg_namespace cn ON cn.oid = c.relnamespace AND cn.nspname <> :schema
             WHERE EXISTS (
                     SELECT 1 FROM unnest(:targets) t
                      WHERE s.relname LIKE t || '%')
            """
        ),
        {"schema": SCHEMA, "targets": DROP_ORDER},
    ).fetchall()
    if borrowers:
        detail = "; ".join(f"{b} uses {s}" for b, s in borrowers)
        raise RuntimeError(
            f"r10a10 P5: a table outside {SCHEMA} borrows a sequence owned by "
            f"one of the seven: {detail}. Detach it first — e.g. "
            "ALTER TABLE <borrower> ALTER COLUMN <col> DROP DEFAULT; — or drop "
            "the copy entirely. Do NOT use DROP TABLE ... CASCADE: that removes "
            "the sequence out from under the borrower and silently breaks it."
        )
    print("r10a10: P5 OK — no outside table borrows a sequence from the seven")

    # ---- DROP -------------------------------------------------------------
    for table in present:
        n = bind.execute(sa.text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar()
        op.drop_table(table, schema=SCHEMA)
        print(f"r10a10: dropped {table} ({n} rows)")

    print("r10a10: report consolidation complete.")


def downgrade():
    """Recreates the seven tables EMPTY, for schema shape only.

    It does NOT restore a single row, and it cannot — the data is gone. This
    exists so `alembic downgrade` does not error, not as a rollback. The real
    rollback for this revision is: restore the backup you took beforehand.

    Columns mirror the definitions the models carried at deletion; anything
    that read these tables was removed in Steps 3.5 and 4a, so the shape is
    for archaeology, not for running against.
    """
    print(
        "r10a10 downgrade: recreating the seven tables EMPTY. "
        "THE DATA IS NOT RESTORED — restore your backup if you need it."
    )

    op.create_table(
        "report_v2",
        sa.Column("report_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36)),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("starting_balance", sa.Float),
        sa.Column("add_cash_amount", sa.Float),
        sa.Column("cash_from_type", sa.String(10)),
        sa.Column("add_cash_bank_account_id", sa.String(36)),
        sa.Column("opening_balance", sa.Float),
        sa.Column("adjusted_opening_balance", sa.Float),
        sa.Column("xero_organiztion_id", sa.String(36)),
        sa.Column("cashsale_total", sa.Float),
        sa.Column("nocashsale_total", sa.Float),
        sa.Column("cash_deposit", sa.Float),
        sa.Column("expense_total", sa.Float),
        schema=SCHEMA,
    )
    op.create_table(
        "report_draft",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("next_transaction_date", sa.Date),
        sa.Column("date", sa.DateTime),
        sa.Column("opening_balance", sa.Float),
        sa.Column("cash_addition", sa.Float),
        sa.Column("adjusted_opening_balance", sa.Float),
        sa.Column("cash_sales", sa.Float),
        sa.Column("shop_sales", sa.Float),
        sa.Column("delivery_sales", sa.Float),
        sa.Column("total_sales", sa.Float),
        sa.Column("expenses", sa.Float),
        sa.Column("bank_deposit", sa.Float),
        sa.Column("closing_balance", sa.Float),
        sa.Column("receipt_files", sa.Text),
        sa.Column("current_section", sa.String(20)),
        sa.Column("completed_sections", sa.JSON),
        sa.Column("uploaded_by", sa.String(150)),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20)),
        sa.Column("withdrawal_type", sa.String(20)),
        sa.Column("withdrawal_bank_account", sa.String(36)),
        sa.Column("xero_integrated_yes", sa.Boolean),
        sa.Column("publishing_status", sa.String(20)),
        sa.Column("safe_box_balance", sa.Float),
        sa.Column("discrepancy_amount", sa.Float),
        sa.Column("discrepancy_reason", sa.String(300)),
        sa.Column("discrepancy_type", sa.String(20)),
        schema=SCHEMA,
    )
    op.create_table(
        "report_detail",
        sa.Column("report_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), primary_key=True),
        sa.Column("opening_balance", sa.Float),
        sa.Column("adjusted_opening_balance", sa.Float),
        sa.Column("nocashsale_total", sa.Float),
        sa.Column("cashsale_total", sa.Float),
        sa.Column("expense_total", sa.Float),
        sa.Column("discrepancy_amount", sa.Float),
        sa.Column("discrepancy_description", sa.Text),
        schema=SCHEMA,
    )
    op.create_table(
        "report_expense_detail",
        sa.Column("expense_id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36)),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Float),
        sa.Column("info_filepath", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("create_at", sa.DateTime),
        schema=SCHEMA,
    )
    op.create_table(
        "report_cashcount_draft",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("thousand_note", sa.Integer),
        sa.Column("fivehundred_note", sa.Integer),
        sa.Column("onehundred_note", sa.Integer),
        sa.Column("fifty_note", sa.Integer),
        sa.Column("twenty_note", sa.Integer),
        sa.Column("ten_note", sa.Integer),
        sa.Column("five_coin", sa.Integer),
        sa.Column("two_coin", sa.Integer),
        sa.Column("one_coin", sa.Integer),
        sa.Column("safe_box_balance", sa.Float),
        sa.Column("discrepancy_amount", sa.Float),
        sa.Column("discrepancy_reason", sa.String(300)),
        sa.Column("discrepancy_type", sa.String(20)),
        sa.Column("actual_cash_total", sa.Float),
        schema=SCHEMA,
    )
    op.create_table(
        "shop_expense_draft",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_draft_id", sa.String(36), nullable=False),
        sa.Column("item", sa.String(150), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("remarks", sa.String(300)),
        sa.Column("files", sa.Text),
        sa.Column("s3_key", sa.String(255)),
        sa.Column("contact_id", sa.String(36)),
        sa.Column("contact_name", sa.String(150)),
        sa.Column("account_id", sa.String(36)),
        sa.Column("account_code", sa.String(20)),
        sa.Column("item_code", sa.String(20)),
        schema=SCHEMA,
    )
    op.create_table(
        "report_history_draft",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("report_draft_id", sa.String(36), nullable=False),
        sa.Column("company", sa.String(150), nullable=False, index=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("field_changed", sa.String(255)),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        schema=SCHEMA,
    )
