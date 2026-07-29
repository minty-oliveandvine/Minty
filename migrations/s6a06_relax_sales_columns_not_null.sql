-- =====================================================================
--  STEP 6 — DROP NOT NULL on the 11 per-method sales columns
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  Target schema: pettycashv2
--
--  Wrapped in a single transaction: if any statement fails, NOTHING is
--  applied. Re-runnable — DROP NOT NULL on an already-nullable column is a
--  no-op, so running this twice is harmless.
--
--  REVERSIBLE. Nothing is destroyed; see the DOWN section at the bottom.
--
--  ------------------------------------------------------------------
--  WHY — this is a production hotfix, not a schema improvement
--
--  s5a05's header says: deploy the code FIRST, because the models no longer
--  declare these columns and an old build would SELECT columns that no
--  longer exist.
--
--  That is correct for the SELECT hazard, and it assumes the two deploy
--  states OVERLAP: new code omitting the columns still works against the old
--  schema, so you can deploy, verify, then drop at leisure.
--
--  For these 11 columns that assumption does not hold. They are NOT NULL
--  with no DEFAULT in the live schema, so the moment the Step 3 code went
--  live, every INSERT into `report` omitted them and Postgres rejected the
--  row:
--
--    (psycopg2.errors.NotNullViolation) null value in column "visa_sales"
--    of relation "report" violates not-null constraint
--
--  There is no window where both old and new code work — the overlap the
--  ordering note assumes is actually a GAP. Every report submission fails
--  from the Step 3 deploy until s5a05 completes.
--
--  This script restores that overlap by making the columns nullable while
--  leaving them in place. After it runs, new code inserts successfully
--  (columns come out NULL) and any straggler old build still reads them.
--
--  ------------------------------------------------------------------
--  RELATIONSHIP TO s5a05
--
--  This does NOT replace s5a05. It buys time so s5a05 can be run
--  deliberately, with its guards doing real work, instead of being rushed
--  while production is down.
--
--  Run order:  s6a06 (this, now)  ->  verify  ->  s5a05 (when ready)
--
--  s5a05 drops these columns outright, which makes the NOT NULL question
--  moot. Running this first costs nothing there.
--
--  ------------------------------------------------------------------
--  READ THIS BEFORE YOU LATER RUN s5a05
--
--  Once this script is applied, new reports insert NULL into all 11 columns.
--  s5a05's guard (b) (CHECK D) sums those columns with COALESCE(...,0), so a
--  post-deploy report reads as column-total 0 while its report_sale_detail
--  rows hold the real non-cash amounts. CHECK D will see a mismatch and
--  ABORT the drop.
--
--  That abort is CORRECT behaviour on a WRONG premise: the data is not
--  corrupt, it simply lives in report_sale_detail now, which is the entire
--  point of the migration.
--
--  Guard (d) has the mirror blind spot — it only flags rows whose column sum
--  is non-zero, so these NULL-column reports sail past it silently.
--
--  Use s6a06_verify_sales_split.sql to separate "expected post-deploy NULL
--  rows" from genuine mismatches BEFORE running s5a05. Do not loosen CHECK D
--  until that query shows the only mismatches are the expected kind.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — this script is only meaningful while the columns still exist.
-- If s5a05 has already run, say so and stop cleanly rather than erroring
-- on eleven missing columns.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    v_cols        int;
    v_notnull     int;
BEGIN
    SELECT count(*) INTO v_cols
      FROM information_schema.columns
     WHERE table_schema = 'pettycashv2'
       AND table_name   IN ('report', 'report_draft')
       AND column_name  IN ('visa_sales','alipay_sales','wechat_sales',
                            'master_sales','unionpay_sales','amex_sales',
                            'octopus_sales','foodpanda_sales','keeta_sales',
                            'openrice_sales','deliveroo_sales');

    IF v_cols = 0 THEN
        RAISE NOTICE
          'Nothing to do: the 11 per-method columns are already gone (s5a05 has run).';
        RETURN;
    END IF;

    SELECT count(*) INTO v_notnull
      FROM information_schema.columns
     WHERE table_schema = 'pettycashv2'
       AND table_name   IN ('report', 'report_draft')
       AND column_name  IN ('visa_sales','alipay_sales','wechat_sales',
                            'master_sales','unionpay_sales','amex_sales',
                            'octopus_sales','foodpanda_sales','keeta_sales',
                            'openrice_sales','deliveroo_sales')
       AND is_nullable  = 'NO';

    RAISE NOTICE 'Found % per-method column(s), % still NOT NULL. Relaxing.',
                 v_cols, v_notnull;
END $$;


-- ---------------------------------------------------------------------
-- RELAX — report
--
-- IF EXISTS is not available on ALTER COLUMN, so each table is guarded by
-- the DO block below instead: it builds the ALTER from the columns that are
-- actually present, making the script safe to run at any point in the
-- s5a05 rollout (before, after, or partially through).
-- ---------------------------------------------------------------------
DO $$
DECLARE
    v_sql  text;
    v_list text;
BEGIN
    FOR v_sql IN
        SELECT format('ALTER TABLE pettycashv2.%I ALTER COLUMN %I DROP NOT NULL',
                      table_name, column_name)
          FROM information_schema.columns
         WHERE table_schema = 'pettycashv2'
           AND table_name   IN ('report', 'report_draft')
           AND column_name  IN ('visa_sales','alipay_sales','wechat_sales',
                                'master_sales','unionpay_sales','amex_sales',
                                'octopus_sales','foodpanda_sales','keeta_sales',
                                'openrice_sales','deliveroo_sales')
           AND is_nullable  = 'NO'
         ORDER BY table_name, column_name
    LOOP
        RAISE NOTICE 'Running: %', v_sql;
        EXECUTE v_sql;
    END LOOP;

    -- Confirm none are left NOT NULL.
    SELECT string_agg(table_name || '.' || column_name, ', ' ORDER BY table_name, column_name)
      INTO v_list
      FROM information_schema.columns
     WHERE table_schema = 'pettycashv2'
       AND table_name   IN ('report', 'report_draft')
       AND column_name  IN ('visa_sales','alipay_sales','wechat_sales',
                            'master_sales','unionpay_sales','amex_sales',
                            'octopus_sales','foodpanda_sales','keeta_sales',
                            'openrice_sales','deliveroo_sales')
       AND is_nullable  = 'NO';

    IF v_list IS NOT NULL THEN
        RAISE EXCEPTION 'ABORT: still NOT NULL after relaxing: %', v_list;
    END IF;

    RAISE NOTICE 'All per-method columns are now nullable. Submissions unblocked.';
END $$;

COMMIT;


-- =====================================================================
--  POST-RUN VERIFICATION — run after the COMMIT above.
-- =====================================================================

-- 1. Every per-method column on both tables should report is_nullable = YES.
--    Expect 22 rows (11 columns x 2 tables) while the columns still exist,
--    or 0 rows once s5a05 has dropped them.
SELECT table_name, column_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'pettycashv2'
  AND table_name  IN ('report', 'report_draft')
  AND column_name IN ('visa_sales','alipay_sales','wechat_sales',
                      'master_sales','unionpay_sales','amex_sales',
                      'octopus_sales','foodpanda_sales','keeta_sales',
                      'openrice_sales','deliveroo_sales')
ORDER BY table_name, column_name;

-- 2. The four survivors are untouched and still NOT NULL on `report`.
--    Expect: cash_sales, delivery_sales, shop_sales, total_sales — all NO.
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'pettycashv2'
  AND table_name  = 'report'
  AND column_name IN ('cash_sales','shop_sales','delivery_sales','total_sales')
ORDER BY column_name;


-- =====================================================================
--  DOWN — restore NOT NULL.
--
--  Only meaningful if you are rolling the Step 3 CODE back too. With the new
--  code running, restoring NOT NULL immediately re-breaks every submission —
--  that is the bug this script exists to fix.
--
--  Backfill first: any row inserted while this script was in effect has NULL
--  in these columns, and NOT NULL cannot be restored until they are filled.
--  Zero is the honest value — the real amounts live in report_sale_detail.
-- =====================================================================
-- BEGIN;
-- UPDATE pettycashv2.report SET
--     visa_sales      = COALESCE(visa_sales, 0),
--     alipay_sales    = COALESCE(alipay_sales, 0),
--     wechat_sales    = COALESCE(wechat_sales, 0),
--     master_sales    = COALESCE(master_sales, 0),
--     unionpay_sales  = COALESCE(unionpay_sales, 0),
--     amex_sales      = COALESCE(amex_sales, 0),
--     octopus_sales   = COALESCE(octopus_sales, 0),
--     foodpanda_sales = COALESCE(foodpanda_sales, 0),
--     keeta_sales     = COALESCE(keeta_sales, 0),
--     openrice_sales  = COALESCE(openrice_sales, 0),
--     deliveroo_sales = COALESCE(deliveroo_sales, 0);
--
-- ALTER TABLE pettycashv2.report
--     ALTER COLUMN visa_sales      SET NOT NULL,
--     ALTER COLUMN alipay_sales    SET NOT NULL,
--     ALTER COLUMN wechat_sales    SET NOT NULL,
--     ALTER COLUMN master_sales    SET NOT NULL,
--     ALTER COLUMN unionpay_sales  SET NOT NULL,
--     ALTER COLUMN amex_sales      SET NOT NULL,
--     ALTER COLUMN octopus_sales   SET NOT NULL,
--     ALTER COLUMN foodpanda_sales SET NOT NULL,
--     ALTER COLUMN keeta_sales     SET NOT NULL,
--     ALTER COLUMN openrice_sales  SET NOT NULL,
--     ALTER COLUMN deliveroo_sales SET NOT NULL;
-- COMMIT;
--
--  Note: report_draft's per-method columns were NOT NULL only if the
--  original schema made them so. Check verification query 1 above before
--  restoring them, and mirror the block above for report_draft as needed.
