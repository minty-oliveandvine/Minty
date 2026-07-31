-- =====================================================================
--  STAGE 4b — backfill shop_expense from shop_expense_draft
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision r5a05_backfill_expense
--  (migrations/versions/r5a05_backfill_shop_expense_from_drafts.py).
--
--  *** ENDS IN ROLLBACK. *** Run it once as-is to read the counts, then
--  change the last line to COMMIT to apply.
--
--  Re-runnable: the INSERT is guarded by NOT EXISTS on the primary key.
--
--  ------------------------------------------------------------------
--  WHAT AND WHY
--
--  ensure_shop_expense_for_draft() creates the paired shop_expense row for
--  every NEW draft expense. This is the one-off catch-up for the ones that
--  already exist, so expense reads can move to shop_expense without
--  in-progress reports losing their expenses.
--
--  Same shape as PART 3 of r0_combined_report_consolidation: an
--  INSERT ... WHERE NOT EXISTS keyed on the shared primary key.
--
--  ------------------------------------------------------------------
--  NO MERGE, NO WINNER, NO DEDUP
--
--  The submit path (ending.py:1617) copies draft -> real reusing the PRIMARY
--  KEY, so a submitted expense already sits in both tables under one id.
--  NOT EXISTS simply skips those: shop_expense wins by being there first.
--  Only never-submitted draft expenses get inserted.
--
--  report_id copies straight from report_draft_id — the same value, since a
--  draft and its report share an id (Stage 4a). That is why shop_expense's
--  FK to report.id resolves with no remapping.
--
--  ------------------------------------------------------------------
--  DEPLOY ORDER
--
--  Ship the CODE FIRST this time, or together. The code half
--  (expense_draft_mirror.py) only ADDS rows the app did not create before;
--  it needs no new columns, so old code and new schema coexist safely in
--  either direction. This is the reverse of the r0 situation, where the code
--  selected columns that did not exist yet.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema='pettycashv2' AND table_name='shop_expense') THEN
        RAISE EXCEPTION 'pettycashv2.shop_expense is missing.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema='pettycashv2' AND table_name='shop_expense_draft') THEN
        RAISE EXCEPTION 'pettycashv2.shop_expense_draft is missing.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 1. BEFORE — what we are starting from.
-- ---------------------------------------------------------------------
DO $$
DECLARE n_e bigint; n_d bigint; n_both bigint; n_gap bigint;
BEGIN
    SELECT count(*) INTO n_e FROM pettycashv2.shop_expense;
    SELECT count(*) INTO n_d FROM pettycashv2.shop_expense_draft;
    SELECT count(*) INTO n_both
      FROM pettycashv2.shop_expense_draft d
      JOIN pettycashv2.shop_expense e ON e.id = d.id;
    SELECT count(*) INTO n_gap
      FROM pettycashv2.shop_expense_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.shop_expense e WHERE e.id = d.id);

    RAISE NOTICE '';
    RAISE NOTICE '=== BEFORE ===';
    RAISE NOTICE '  shop_expense rows           : %', n_e;
    RAISE NOTICE '  shop_expense_draft rows     : %', n_d;
    RAISE NOTICE '  drafts already paired       : %  (submitted; will be skipped)', n_both;
    RAISE NOTICE '  drafts needing a row        : %  (this is what gets inserted)', n_gap;
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 2. FK PRE-FLIGHT
--
--    shop_expense.report_id REFERENCES report.id. A draft expense whose
--    parent draft has no `report` row would violate that FK and abort the
--    whole transaction, so the INSERT below joins `report` and skips them.
--    Surface the count first rather than dropping them silently.
-- ---------------------------------------------------------------------
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n
      FROM pettycashv2.shop_expense_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.shop_expense e WHERE e.id = d.id)
       AND NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.report_draft_id);

    IF n > 0 THEN
        RAISE WARNING
          '% draft expense(s) point at a report_draft with NO `report` row and will be SKIPPED. They will not appear once reads move to shop_expense. Investigate before committing.', n;
        RAISE NOTICE 'To see them:';
        RAISE NOTICE '  SELECT d.id, d.report_draft_id, d.item, d.amount';
        RAISE NOTICE '    FROM pettycashv2.shop_expense_draft d';
        RAISE NOTICE '   WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.report_draft_id);';
    ELSE
        RAISE NOTICE 'FK pre-flight clean — every draft expense has a parent report.';
    END IF;
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 3. THE BACKFILL
--
--    item/amount are NOT NULL on shop_expense. The multi-file upload path
--    (api.py:1737) creates skeleton drafts with item='' and amount=0.0 on
--    purpose; COALESCE covers any historical row that is NULL outright.
-- ---------------------------------------------------------------------
INSERT INTO pettycashv2.shop_expense
    (id, report_id, item, amount, remarks, files, s3_key,
     contact_id, contact_name, account_id, account_code, item_code)
SELECT d.id,
       d.report_draft_id,
       COALESCE(d.item, ''),
       COALESCE(d.amount, 0),
       d.remarks, d.files, d.s3_key,
       d.contact_id, d.contact_name, d.account_id, d.account_code, d.item_code
  FROM pettycashv2.shop_expense_draft d
  JOIN pettycashv2.report r ON r.id = d.report_draft_id
 WHERE NOT EXISTS (
           SELECT 1 FROM pettycashv2.shop_expense e WHERE e.id = d.id
       );


-- ---------------------------------------------------------------------
-- 4. AFTER
-- ---------------------------------------------------------------------
DO $$
DECLARE n_e bigint; n_gap bigint; n_orphan bigint;
BEGIN
    SELECT count(*) INTO n_e FROM pettycashv2.shop_expense;
    SELECT count(*) INTO n_gap
      FROM pettycashv2.shop_expense_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.shop_expense e WHERE e.id = d.id);
    SELECT count(*) INTO n_orphan
      FROM pettycashv2.shop_expense_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.report_draft_id);

    RAISE NOTICE '=== AFTER ===';
    RAISE NOTICE '  shop_expense rows           : %', n_e;
    RAISE NOTICE '  drafts still unpaired       : %', n_gap;
    RAISE NOTICE '    of which orphaned (no report row) : %', n_orphan;
    RAISE NOTICE '';
    IF n_gap = n_orphan THEN
        RAISE NOTICE '  OK — every draft with a parent report now has a shop_expense row.';
    ELSE
        RAISE WARNING '  % unpaired draft(s) are NOT explained by missing reports. Investigate.', n_gap - n_orphan;
    END IF;
    RAISE NOTICE '';
    RAISE NOTICE '  Nothing was DROPPED. shop_expense_draft still holds every row.';
    RAISE NOTICE '  >>> Ends in ROLLBACK. Change the last line to COMMIT to apply.';
    RAISE NOTICE '';
END $$;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — removes only shop_expense rows that mirror a draft. It CANNOT
-- distinguish rows this script inserted from ones the submit path created
-- (they share ids by design), so treat it as a blunt instrument and prefer
-- a backup if you need to be precise.
--
--   DELETE FROM pettycashv2.shop_expense e
--    WHERE EXISTS (SELECT 1 FROM pettycashv2.shop_expense_draft d
--                   WHERE d.id = e.id);
-- ---------------------------------------------------------------------
