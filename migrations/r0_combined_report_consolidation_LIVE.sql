-- =====================================================================
--  REPORT CONSOLIDATION — r1a01 + r2a02 + r3a03 + r4a04, combined
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  The four staged scripts you already validated against pettycashv2_clone,
--  merged into one transaction and re-pointed at production:
--
--    PART 1  (r1a01)  add 6 columns to `report` + backfill
--    PART 2  (r2a02)  drop the 4 FKs pinning report_v2
--    PART 3  (r3a03)  relax report.expenses / closing_balance to nullable
--                     + backfill a report row for every draft
--    PART 4  (r4a04)  re-point those 4 FKs at report.id
--
--  Everything runs inside ONE transaction. If any statement fails, the whole
--  thing rolls back and the live schema is untouched. There is no partial
--  state to clean up.
--
--  ------------------------------------------------------------------
--  *** IT ENDS IN ROLLBACK. READ THIS BEFORE YOU RUN IT. ***
--
--  As written this is a DRY RUN: it does all the work, prints the numbers,
--  and then throws it away. Run it once like that and read the output.
--
--  To actually apply it, change the last line from ROLLBACK to COMMIT.
--
--  ------------------------------------------------------------------
--  BEFORE YOU COMMIT
--
--  1. TAKE A BACKUP. Part 3 INSERTs rows into `report`. That part is not a
--     reversible no-op, and this is production data.
--
--  2. DEPLOY THE CODE FIRST, or at least at the same time. The application
--     already expects these columns (blueprints/report/models/report.py
--     declares status, current_section, completed_sections, withdrawal_type,
--     withdrawal_bank_account, actual_cash_total). Running old code against
--     the new schema is fine — the extra columns are ignored. Running the NEW
--     code against the OLD schema is not: it selects columns that do not
--     exist yet.
--
--  3. This does NOT drop anything. report_v2, report_draft and friends all
--     survive. Dropping them is Stage 5, later, deliberately separate.
--
--  ------------------------------------------------------------------
--  ALEMBIC
--
--  This script does NOT touch pettycashv2.alembic_version. If you apply it by
--  hand, alembic still believes the head is s7a07_cash_method and a later
--  `alembic upgrade head` will try to re-run r1a01..r4a04 on top of your
--  changes. Either:
--
--    (a) run `alembic upgrade head` INSTEAD of this script (the four .py
--        revisions do exactly the same work and stamp the version), or
--    (b) run this, then stamp manually:
--          UPDATE pettycashv2.alembic_version SET version_num = 'r4a04_repoint_fks';
--
--  (b) is only correct if this script committed cleanly.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — confirm we are where we think we are.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    v_missing text := '';
    t         text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'pettycashv2') THEN
        RAISE EXCEPTION 'Schema pettycashv2 does not exist.';
    END IF;

    FOREACH t IN ARRAY ARRAY['report','report_draft','report_cashcount_draft',
                             'report_detail','report_sale_detail',
                             'report_expense_detail']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2' AND table_name=t) THEN
            v_missing := v_missing || t || ' ';
        END IF;
    END LOOP;

    IF v_missing <> '' THEN
        RAISE EXCEPTION 'Missing expected table(s) in pettycashv2: %', trim(v_missing);
    END IF;

    RAISE NOTICE '';
    RAISE NOTICE '############################################################';
    RAISE NOTICE '#  REPORT CONSOLIDATION — TARGET SCHEMA: pettycashv2 (LIVE) #';
    RAISE NOTICE '############################################################';
    RAISE NOTICE '';
END $$;


-- =====================================================================
--  PART 1 (r1a01) — add the 6 columns and backfill them
--
--  All nullable. `status` takes a temporary DEFAULT 'posted' so any row
--  inserted while this runs lands sane; the default comes off at the end of
--  this part. The column stays nullable either way — s6a06 is the cautionary
--  tale for NOT NULL with no default.
--
--  The backfill is a plain join on the primary key: report.id ==
--  report_draft.id == report_cashcount_draft.report_id == report_detail.
--  report_id. No dedup, no (entity, date) matching.
-- =====================================================================

ALTER TABLE pettycashv2.report
    ADD COLUMN IF NOT EXISTS status                  varchar(20) DEFAULT 'posted',
    ADD COLUMN IF NOT EXISTS current_section         varchar(20),
    ADD COLUMN IF NOT EXISTS completed_sections      json,
    ADD COLUMN IF NOT EXISTS withdrawal_type         varchar(20),
    ADD COLUMN IF NOT EXISTS withdrawal_bank_account varchar(36),
    ADD COLUMN IF NOT EXISTS actual_cash_total       double precision;

-- 1a. from report_draft (COALESCE so a re-run never clobbers)
UPDATE pettycashv2.report AS r
   SET status                  = COALESCE(r.status,                  d.status),
       current_section         = COALESCE(r.current_section,         d.current_section),
       completed_sections      = COALESCE(r.completed_sections,      d.completed_sections),
       withdrawal_type         = COALESCE(r.withdrawal_type,         d.withdrawal_type),
       withdrawal_bank_account = COALESCE(r.withdrawal_bank_account, d.withdrawal_bank_account)
  FROM pettycashv2.report_draft AS d
 WHERE d.id = r.id;

-- 1b. actual_cash_total — the one non-redundant column on
--     report_cashcount_draft. It seeds the NEXT report's opening balance
--     (create.py:288, opening.py:1044); losing it breaks the report chain.
UPDATE pettycashv2.report AS r
   SET actual_cash_total = COALESCE(r.actual_cash_total, c.actual_cash_total)
  FROM pettycashv2.report_cashcount_draft AS c
 WHERE c.report_id = r.id;

-- 1c. report_detail.discrepancy_description -> report.discrepancy_reason,
--     only where report's own value is empty. `report` stays authoritative.
UPDATE pettycashv2.report AS r
   SET discrepancy_reason = d.discrepancy_description
  FROM (
        SELECT DISTINCT ON (report_id) report_id, discrepancy_description
          FROM pettycashv2.report_detail
         WHERE discrepancy_description IS NOT NULL
           AND discrepancy_description <> ''
         ORDER BY report_id, entity_id
       ) AS d
 WHERE d.report_id = r.id
   AND (r.discrepancy_reason IS NULL OR r.discrepancy_reason = '');

-- 1d. drop the temporary default (the column stays nullable)
ALTER TABLE pettycashv2.report
    ALTER COLUMN status DROP DEFAULT;

DO $$
DECLARE n_d bigint; n_p bigint; n_n bigint; n_ac bigint;
BEGIN
    SELECT count(*) FILTER (WHERE status='draft'),
           count(*) FILTER (WHERE status='posted'),
           count(*) FILTER (WHERE status IS NULL),
           count(*) FILTER (WHERE actual_cash_total IS NOT NULL)
      INTO n_d, n_p, n_n, n_ac
      FROM pettycashv2.report;
    RAISE NOTICE 'PART 1 done — status draft=% posted=% null=% | actual_cash_total set=%',
                 n_d, n_p, n_n, n_ac;
    IF n_n > 0 THEN
        RAISE WARNING 'PART 1: % report row(s) have NULL status.', n_n;
    END IF;
END $$;


-- =====================================================================
--  PART 2 (r2a02) — drop the FKs pinning report_v2
--
--  These four constraints were the ONLY reason seven code sites manufactured
--  a ReportV2 row. Nothing ever read report_v2 back. The code that wrote it
--  is already gone; this releases the schema side.
--
--  report_cash_detail and report_history_v2 also FK'd report_v2 — both were
--  dead and were removed in Stage 0, so they are not listed here.
-- =====================================================================

ALTER TABLE IF EXISTS pettycashv2.report_sale_detail
    DROP CONSTRAINT IF EXISTS report_sale_detail_report_id_fkey;
ALTER TABLE IF EXISTS pettycashv2.report_expense_detail
    DROP CONSTRAINT IF EXISTS report_expense_detail_report_id_fkey;
ALTER TABLE IF EXISTS pettycashv2.xero_report_sync
    DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey;
ALTER TABLE IF EXISTS pettycashv2.xero_bank_transfer
    DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey;

DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n
      FROM pg_constraint con
      JOIN pg_class cl ON cl.oid=con.conrelid
      JOIN pg_namespace ns ON ns.oid=cl.relnamespace
      JOIN pg_class rcl ON rcl.oid=con.confrelid
     WHERE con.contype='f' AND ns.nspname='pettycashv2' AND rcl.relname='report_v2';
    RAISE NOTICE 'PART 2 done — FKs still referencing report_v2: % (expect 0)', n;
END $$;


-- =====================================================================
--  PART 3 (r3a03) — relax two NOT NULLs, then give every draft a report row
--
--  expenses and closing_balance are not knowable at draft creation, so they
--  must be nullable before a draft-shaped report row can be inserted.
--  transaction_date, opening_balance and company stay NOT NULL — all three
--  ARE known at that point, so the guarantee still holds.
--
--  Relaxing NOT NULL can never reject a row that previously succeeded. This
--  is the inverse of the s6a06 ordering, and it is the safe direction.
-- =====================================================================

ALTER TABLE pettycashv2.report
    ALTER COLUMN expenses        DROP NOT NULL,
    ALTER COLUMN closing_balance DROP NOT NULL;

-- 3b. Pre-flight: drafts with no opening_balance would be COALESCEd to 0 by
--     the INSERT below. Surface them rather than silently inventing a number.
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n
      FROM pettycashv2.report_draft d
     WHERE d.opening_balance IS NULL
       AND NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.id);
    IF n > 0 THEN
        RAISE WARNING
          'PART 3: % draft(s) have NULL opening_balance and will be inserted as 0.0. Review after this run.', n;
    END IF;
END $$;

-- 3c. THE BACKFILL — one report row per draft that lacks one.
--
--     This is the statement that makes Stage 3 possible: it closes the gap
--     for EXISTING rows (the application already creates the paired row for
--     new drafts via ensure_report_row_for_draft).
--
--     status is carried across, so these rows stay distinguishable from
--     submitted reports. expenses/closing_balance copy as-is, NULL included.
INSERT INTO pettycashv2.report
    (id, transaction_date, next_transaction_date, date, opening_balance,
     cash_addition, adjusted_opening_balance, cash_sales, shop_sales,
     delivery_sales, total_sales, expenses, bank_deposit, closing_balance,
     receipt_files, uploaded_by, company, xero_integrated_yes,
     safe_box_balance, discrepancy_amount, discrepancy_reason,
     discrepancy_type, publishing_status, status, current_section,
     completed_sections, withdrawal_type, withdrawal_bank_account)
SELECT d.id, d.transaction_date, d.next_transaction_date, d.date,
       COALESCE(d.opening_balance, 0), d.cash_addition,
       d.adjusted_opening_balance, d.cash_sales, d.shop_sales,
       d.delivery_sales, d.total_sales, d.expenses, d.bank_deposit,
       d.closing_balance, d.receipt_files, d.uploaded_by, d.company,
       d.xero_integrated_yes, d.safe_box_balance, d.discrepancy_amount,
       d.discrepancy_reason, d.discrepancy_type, d.publishing_status,
       COALESCE(d.status, 'draft'), d.current_section, d.completed_sections,
       d.withdrawal_type, d.withdrawal_bank_account
  FROM pettycashv2.report_draft d
 WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.id);

-- 3d. actual_cash_total for the rows just inserted (PART 1b ran before they
--     existed, so they would otherwise be missing it).
UPDATE pettycashv2.report AS r
   SET actual_cash_total = c.actual_cash_total
  FROM pettycashv2.report_cashcount_draft AS c
 WHERE c.report_id = r.id
   AND r.actual_cash_total IS NULL
   AND c.actual_cash_total IS NOT NULL;

DO $$
DECLARE n_rep bigint; n_gap bigint;
BEGIN
    SELECT count(*) INTO n_rep FROM pettycashv2.report;
    SELECT count(*) INTO n_gap
      FROM pettycashv2.report_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.id);
    RAISE NOTICE 'PART 3 done — report rows now=% | drafts still lacking one=% (expect 0)',
                 n_rep, n_gap;
END $$;


-- =====================================================================
--  PART 4 (r4a04) — re-point the four FKs at report.id
--
--  The VALUES never changed: report_v2.report_id was always the draft id,
--  which is always the report id. What was missing was the parent ROW, which
--  PART 3 just supplied.
--
--  The pre-flight below is the real guard. It counts orphans per table and
--  ABORTS naming all of them, rather than letting Postgres reject on the
--  first one it happens to hit.
-- =====================================================================

DO $$
DECLARE
    t text; col text; n bigint; n_total bigint := 0; bad text := '';
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'PART 4 pre-flight — rows pointing at a non-existent report:';
    FOREACH t IN ARRAY ARRAY['report_sale_detail','report_expense_detail',
                             'xero_report_sync','xero_bank_transfer']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2' AND table_name=t) THEN
            RAISE NOTICE '  %-24s (table absent — skipped)', t;
            CONTINUE;
        END IF;
        col := CASE WHEN t='xero_bank_transfer' THEN 'sync_report_id' ELSE 'report_id' END;
        EXECUTE format($f$
            SELECT count(*) FROM pettycashv2.%I c
             WHERE c.%I IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = c.%I)
        $f$, t, col, col) INTO n;
        RAISE NOTICE '  %-24s orphans = %', t, n;
        n_total := n_total + n;
        IF n > 0 THEN bad := bad || format('%s=%s ', t, n); END IF;
    END LOOP;

    IF n_total > 0 THEN
        RAISE EXCEPTION
          'ABORT in PART 4: % orphaned row(s) (%). These reference an id with no `report` row — PART 3 should have created them. Nothing has been committed.',
          n_total, trim(bad);
    END IF;
    RAISE NOTICE '  clean.';
END $$;

ALTER TABLE pettycashv2.report_sale_detail
    ADD CONSTRAINT report_sale_detail_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id) ON DELETE CASCADE;

ALTER TABLE pettycashv2.report_expense_detail
    ADD CONSTRAINT report_expense_detail_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id) ON DELETE CASCADE;

ALTER TABLE pettycashv2.xero_report_sync
    ADD CONSTRAINT xero_report_sync_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id) ON DELETE CASCADE;

ALTER TABLE pettycashv2.xero_bank_transfer
    ADD CONSTRAINT xero_bank_transfer_sync_report_id_fkey
    FOREIGN KEY (sync_report_id) REFERENCES pettycashv2.report(id) ON DELETE CASCADE;


-- =====================================================================
--  FINAL REPORT
-- =====================================================================
DO $$
DECLARE
    r          record;
    n_report   int := 0;
    n_v2       int := 0;
    n_draft    bigint;
    n_posted   bigint;
    n_rows     bigint;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== FKs now ===';
    FOR r IN
        SELECT cl.relname AS child, rcl.relname AS parent
          FROM pg_constraint con
          JOIN pg_class cl ON cl.oid=con.conrelid
          JOIN pg_namespace ns ON ns.oid=cl.relnamespace
          JOIN pg_class rcl ON rcl.oid=con.confrelid
         WHERE con.contype='f' AND ns.nspname='pettycashv2'
           AND rcl.relname IN ('report','report_v2')
         ORDER BY rcl.relname, cl.relname
    LOOP
        RAISE NOTICE '  %-24s -> %', r.child, r.parent;
        IF r.parent='report'    THEN n_report := n_report + 1; END IF;
        IF r.parent='report_v2' THEN n_v2     := n_v2 + 1;     END IF;
    END LOOP;

    SELECT count(*), count(*) FILTER (WHERE status='draft'),
           count(*) FILTER (WHERE status='posted')
      INTO n_rows, n_draft, n_posted FROM pettycashv2.report;

    RAISE NOTICE '';
    RAISE NOTICE '=== SUMMARY ===';
    RAISE NOTICE '  report rows      : %  (draft=%  posted=%)', n_rows, n_draft, n_posted;
    RAISE NOTICE '  FKs -> report    : %', n_report;
    RAISE NOTICE '  FKs -> report_v2 : %  (0 means Stage 5 can drop it)', n_v2;
    RAISE NOTICE '';
    RAISE NOTICE '  Nothing was DROPPED. report_v2 / report_draft / report_detail';
    RAISE NOTICE '  / report_cashcount_draft all still exist and still hold data.';
    RAISE NOTICE '';
    RAISE NOTICE '  >>> This run ends in ROLLBACK. Change the last line to COMMIT';
    RAISE NOTICE '  >>> to apply it for real. Take a backup first.';
    RAISE NOTICE '';
END $$;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — reverses PART 4, 2 and 1. PART 3's INSERT is NOT reversed here:
-- deleting rows from `report` on the basis of status='draft' would also
-- delete the draft-shaped rows the application has legitimately created
-- since. If you need to undo PART 3, use the backup.
--
--   -- PART 4 down: unconstrain the four columns again
--   ALTER TABLE pettycashv2.report_sale_detail
--       DROP CONSTRAINT IF EXISTS report_sale_detail_report_id_fkey;
--   ALTER TABLE pettycashv2.report_expense_detail
--       DROP CONSTRAINT IF EXISTS report_expense_detail_report_id_fkey;
--   ALTER TABLE pettycashv2.xero_report_sync
--       DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey;
--   ALTER TABLE pettycashv2.xero_bank_transfer
--       DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey;
--
--   -- PART 3 down: restore NOT NULL. FAILS while draft-shaped rows exist,
--   -- which is correct — backfill them first if you really mean it:
--   --   UPDATE pettycashv2.report
--   --      SET expenses = COALESCE(expenses,0),
--   --          closing_balance = COALESCE(closing_balance,0)
--   --    WHERE expenses IS NULL OR closing_balance IS NULL;
--   ALTER TABLE pettycashv2.report
--       ALTER COLUMN expenses        SET NOT NULL,
--       ALTER COLUMN closing_balance SET NOT NULL;
--
--   -- PART 1 down: drop the six columns
--   ALTER TABLE pettycashv2.report
--       DROP COLUMN IF EXISTS actual_cash_total,
--       DROP COLUMN IF EXISTS withdrawal_bank_account,
--       DROP COLUMN IF EXISTS withdrawal_type,
--       DROP COLUMN IF EXISTS completed_sections,
--       DROP COLUMN IF EXISTS current_section,
--       DROP COLUMN IF EXISTS status;
--
-- The report_v2 FKs are deliberately NOT restored: going back that far means
-- reinstating the seven ReportV2 write sites too, which is a code rollback.
-- ---------------------------------------------------------------------
