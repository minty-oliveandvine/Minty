-- =====================================================================
--  STAGE 4a — relax report NOT NULLs so a draft can BE a report row
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  *** TARGET SCHEMA: pettycashv2_clone  (NOT the live pettycashv2) ***
--
--  Raw-SQL twin of alembic revision r3a03_relax_report_nn
--  (migrations/versions/r3a03_relax_report_notnull_for_drafts.py).
--
--  Ends with ROLLBACK so a first run reports and changes NOTHING.
--  Flip the last line to COMMIT to keep the result on the clone.
--
--  Re-runnable: DROP NOT NULL on an already-nullable column is a no-op.
--
--  PREREQUISITE: run r1a01 and r2a02 on the clone first.
--
--  ------------------------------------------------------------------
--  WHY
--
--  Stage 4a makes a `report` row exist from DRAFT CREATION rather than only
--  from submit. That is the precondition Stage 3 needs: Stage 3 re-points
--  report_sale_detail.report_id (and the other three) at report.id, which is
--  only satisfiable once every detail row's parent id exists in `report`.
--  Detail rows are written throughout data entry, long before submit.
--
--  `report` has five NOT NULL columns with no default:
--
--    transaction_date   known at draft creation  (opening.py:742)
--    opening_balance    known at draft creation
--    company            known at draft creation
--    expenses           NOT known yet   <-- blocker
--    closing_balance    NOT known yet   <-- blocker
--
--  expenses is only settled at the expense step; closing_balance derives from
--  it. So an INSERT at draft creation fails on exactly those two. This script
--  relaxes exactly those two and nothing else.
--
--  ------------------------------------------------------------------
--  WHY NULL RATHER THAN DEFAULT 0.0
--
--  0.0 is a lie that survives. A report with genuinely zero expenses and one
--  where expenses have not been entered yet would become indistinguishable,
--  and closing_balance = 0.0 reads as a real balance to every downstream sum.
--  NULL states the truth during entry. Readers already cope —
--  recalculate_report() does `expenses or 0.0` before any arithmetic.
--
--  This also matches the table being absorbed: report_draft.expenses and
--  report_draft.closing_balance are both already nullable
--  (report_draft.py:22, :24). No new convention is being invented.
--
--  ------------------------------------------------------------------
--  WHY THIS DIRECTION IS SAFE
--
--  Relaxing NOT NULL can never reject a row that used to be accepted, so every
--  existing INSERT keeps working. This is the exact INVERSE of s6a06, where
--  columns stayed NOT NULL with no default while the code stopped writing
--  them and every submission failed. Widen first, then change the writers —
--  that order has no failure window.
--
--  transaction_date, opening_balance and company deliberately stay NOT NULL.
--  All three are known at draft creation, so keeping them constrained
--  preserves a guarantee that still holds.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — clone only.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'pettycashv2_clone') THEN
        RAISE EXCEPTION
          'Schema pettycashv2_clone does not exist. See the header of this file.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'pettycashv2_clone' AND table_name = 'report') THEN
        RAISE EXCEPTION 'pettycashv2_clone.report is missing.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 1. BEFORE — show the current nullability of all five.
-- ---------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== report NOT NULL columns BEFORE ===';
    FOR r IN
        SELECT column_name, is_nullable
          FROM information_schema.columns
         WHERE table_schema = 'pettycashv2_clone'
           AND table_name   = 'report'
           AND column_name IN ('transaction_date','opening_balance','company',
                               'expenses','closing_balance')
         ORDER BY column_name
    LOOP
        RAISE NOTICE '  %-18s nullable=%', r.column_name, r.is_nullable;
    END LOOP;
END $$;


-- ---------------------------------------------------------------------
-- 2. RELAX the two that are unknowable at draft creation.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2_clone.report
    ALTER COLUMN expenses        DROP NOT NULL,
    ALTER COLUMN closing_balance DROP NOT NULL;


-- ---------------------------------------------------------------------
-- 3. AFTER — confirm, and restate what stays constrained.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    r          record;
    n_relaxed  int := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== report NOT NULL columns AFTER ===';
    FOR r IN
        SELECT column_name, is_nullable
          FROM information_schema.columns
         WHERE table_schema = 'pettycashv2_clone'
           AND table_name   = 'report'
           AND column_name IN ('transaction_date','opening_balance','company',
                               'expenses','closing_balance')
         ORDER BY column_name
    LOOP
        RAISE NOTICE '  %-18s nullable=%', r.column_name, r.is_nullable;
        IF r.column_name IN ('expenses','closing_balance') AND r.is_nullable = 'YES' THEN
            n_relaxed := n_relaxed + 1;
        END IF;
    END LOOP;

    RAISE NOTICE '';
    IF n_relaxed = 2 THEN
        RAISE NOTICE 'OK — expenses and closing_balance are nullable.';
        RAISE NOTICE 'A draft-shaped report row can now be inserted at draft creation.';
    ELSE
        RAISE WARNING 'Expected 2 relaxed columns, got %. Check the output above.', n_relaxed;
    END IF;
    RAISE NOTICE 'transaction_date, opening_balance and company stay NOT NULL by design.';
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 4. STAGE 3 READINESS — how many report rows would still be missing?
--
--    Stage 3 can add the FKs back only when every detail row's parent id
--    exists in `report`. Today the gap is the unsubmitted drafts. This counts
--    that gap, which is exactly the backfill Stage 4a's code change removes
--    going forward (and which a one-off backfill closes for existing rows).
-- ---------------------------------------------------------------------
DO $$
DECLARE
    n_draft_no_report bigint;
    n_sale_orphan     bigint;
    n_exp_orphan      bigint;
BEGIN
    SELECT count(*) INTO n_draft_no_report
      FROM pettycashv2_clone.report_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = d.id);

    SELECT count(*) INTO n_sale_orphan
      FROM pettycashv2_clone.report_sale_detail c
     WHERE c.report_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = c.report_id);

    SELECT count(*) INTO n_exp_orphan
      FROM pettycashv2_clone.report_expense_detail c
     WHERE c.report_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = c.report_id);

    RAISE NOTICE '=== STAGE 3 READINESS ===';
    RAISE NOTICE 'drafts with no report row            : %', n_draft_no_report;
    RAISE NOTICE 'report_sale_detail rows w/o a report : %', n_sale_orphan;
    RAISE NOTICE 'report_expense_detail rows w/o report: %', n_exp_orphan;
    RAISE NOTICE '';
    RAISE NOTICE 'All three must be 0 before Stage 3 can re-add the FKs.';
    RAISE NOTICE 'Stage 4a stops NEW gaps appearing; existing rows need the';
    RAISE NOTICE 'one-off backfill below (commented out — review before running).';
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 5. ONE-OFF BACKFILL — commented out ON PURPOSE.
--
--    This creates a report row for every draft that lacks one, which is what
--    closes the Stage 3 gap for EXISTING data. Read it before you run it:
--    it inserts rows into `report`, which is not a reversible no-op.
--
--    status='draft' is what makes these rows distinguishable from submitted
--    reports. expenses/closing_balance are copied as-is, NULL included —
--    which is why step 2 above had to run first.
--
--    UNCOMMENT ONLY AFTER the counts above look right to you.
--
--  INSERT INTO pettycashv2_clone.report
--      (id, transaction_date, next_transaction_date, date, opening_balance,
--       cash_addition, adjusted_opening_balance, cash_sales, shop_sales,
--       delivery_sales, total_sales, expenses, bank_deposit, closing_balance,
--       receipt_files, uploaded_by, company, xero_integrated_yes,
--       safe_box_balance, discrepancy_amount, discrepancy_reason,
--       discrepancy_type, publishing_status, status, current_section,
--       completed_sections, withdrawal_type, withdrawal_bank_account)
--  SELECT d.id, d.transaction_date, d.next_transaction_date, d.date,
--         COALESCE(d.opening_balance, 0), d.cash_addition,
--         d.adjusted_opening_balance, d.cash_sales, d.shop_sales,
--         d.delivery_sales, d.total_sales, d.expenses, d.bank_deposit,
--         d.closing_balance, d.receipt_files, d.uploaded_by, d.company,
--         d.xero_integrated_yes, d.safe_box_balance, d.discrepancy_amount,
--         d.discrepancy_reason, d.discrepancy_type, d.publishing_status,
--         COALESCE(d.status, 'draft'), d.current_section, d.completed_sections,
--         d.withdrawal_type, d.withdrawal_bank_account
--    FROM pettycashv2_clone.report_draft d
--   WHERE NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = d.id);
--
--    NOTE opening_balance is COALESCEd to 0 because it stays NOT NULL while
--    report_draft.opening_balance is nullable. If that COALESCE ever fires it
--    is masking a draft with no opening balance — check for those first:
--      SELECT count(*) FROM pettycashv2_clone.report_draft WHERE opening_balance IS NULL;
-- ---------------------------------------------------------------------


-- =====================================================================
--  ROLLBACK = dry run. Change to COMMIT to keep the result on the clone.
-- =====================================================================
ROLLBACK;

-- ---------------------------------------------------------------------
-- DOWN (if you committed and want NOT NULL back):
--
--   -- Will FAIL if any draft-shaped report rows exist (NULL expenses).
--   -- That is correct: those rows are what the constraint forbids.
--   -- To force it, backfill first:
--   --   UPDATE pettycashv2_clone.report
--   --      SET expenses = COALESCE(expenses, 0),
--   --          closing_balance = COALESCE(closing_balance, 0)
--   --    WHERE expenses IS NULL OR closing_balance IS NULL;
--
--   ALTER TABLE pettycashv2_clone.report
--       ALTER COLUMN expenses        SET NOT NULL,
--       ALTER COLUMN closing_balance SET NOT NULL;
-- ---------------------------------------------------------------------
