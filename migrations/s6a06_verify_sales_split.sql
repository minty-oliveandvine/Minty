-- =====================================================================
--  STEP 6 VERIFY — is it safe to run s5a05 yet?
--  Copy-paste into the Supabase SQL editor. READ-ONLY: no BEGIN, no writes.
--
--  Target schema: pettycashv2
--
--  ------------------------------------------------------------------
--  WHY THIS EXISTS
--
--  s5a05's CHECK D compares the 11 per-method columns against
--  report_sale_detail and aborts on any disagreement. That guard was written
--  for a world where the columns were the source of truth.
--
--  After s6a06 they are nullable, and the Step 3 code stops writing them.
--  So a report submitted after the deploy has NULL columns (summing to 0 via
--  COALESCE) but real amounts in report_sale_detail. CHECK D sees a mismatch
--  and aborts — correctly by its own logic, but for a reason that is NOT
--  data loss. That data is exactly where it is supposed to be.
--
--  A genuine mismatch — column amounts and detail rows that disagree on a
--  report where BOTH were written — is a real problem and must be
--  investigated before dropping anything.
--
--  These two look identical to CHECK D. This script tells them apart.
--
--  ------------------------------------------------------------------
--  HOW TO READ THE RESULT
--
--  Query 1 classifies every mismatching row. You are looking for:
--
--    EXPECTED_POST_DEPLOY  — columns NULL, detail rows present.
--                            Safe. This is the new normal.
--
--    GENUINE_MISMATCH      — columns written AND detail rows present, and
--                            they disagree. INVESTIGATE. Do not run s5a05.
--
--    ORPHAN_COLUMNS        — columns written, NO non-cash detail rows.
--                            Dropping would DESTROY this data. Re-run the
--                            s4a04 backfill first.
--
--  If query 1 returns only EXPECTED_POST_DEPLOY rows, s5a05 is safe to run
--  once you relax CHECK D to ignore them (see the note at the bottom).
--
--  Cash is excluded from the detail side throughout, for the same reason
--  s5a05 excludes it: the 11 columns never included cash_sales, but s7a07
--  seeded Cash rows into report_sale_detail. Counting them would make every
--  cash report look mismatched.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. CLASSIFY every disagreeing report and draft.
--    Expect: only EXPECTED_POST_DEPLOY rows, or no rows at all.
-- ---------------------------------------------------------------------
WITH cols AS (
    SELECT 'report' AS src, id, transaction_date,
           visa_sales, alipay_sales, wechat_sales, master_sales,
           unionpay_sales, amex_sales, octopus_sales, foodpanda_sales,
           keeta_sales, openrice_sales, deliveroo_sales
      FROM pettycashv2.report
    UNION ALL
    SELECT 'report_draft', id, transaction_date,
           visa_sales, alipay_sales, wechat_sales, master_sales,
           unionpay_sales, amex_sales, octopus_sales, foodpanda_sales,
           keeta_sales, openrice_sales, deliveroo_sales
      FROM pettycashv2.report_draft
), col AS (
    SELECT src, id, transaction_date,
           -- COALESCE for the SUM, but keep the all-NULL fact separately:
           -- that distinction is the whole point of this script.
           COALESCE(visa_sales,0)+COALESCE(alipay_sales,0)+COALESCE(wechat_sales,0)
          +COALESCE(master_sales,0)+COALESCE(unionpay_sales,0)+COALESCE(amex_sales,0)
          +COALESCE(octopus_sales,0)+COALESCE(foodpanda_sales,0)+COALESCE(keeta_sales,0)
          +COALESCE(openrice_sales,0)+COALESCE(deliveroo_sales,0) AS col_total,
           (visa_sales IS NULL AND alipay_sales IS NULL AND wechat_sales IS NULL
            AND master_sales IS NULL AND unionpay_sales IS NULL AND amex_sales IS NULL
            AND octopus_sales IS NULL AND foodpanda_sales IS NULL AND keeta_sales IS NULL
            AND openrice_sales IS NULL AND deliveroo_sales IS NULL) AS cols_all_null
      FROM cols
), det AS (
    SELECT report_id, SUM(amount) AS det_total, count(*) AS det_rows
      FROM pettycashv2.report_sale_detail
     WHERE COALESCE(type,'') <> 'Cash'
     GROUP BY report_id
)
SELECT
    CASE
        WHEN c.cols_all_null AND COALESCE(d.det_rows,0) > 0
            THEN 'EXPECTED_POST_DEPLOY'
        WHEN c.col_total <> 0 AND COALESCE(d.det_rows,0) = 0
            THEN 'ORPHAN_COLUMNS'
        ELSE 'GENUINE_MISMATCH'
    END                                            AS classification,
    c.src,
    c.id,
    c.transaction_date,
    c.col_total,
    COALESCE(d.det_total, 0)                       AS detail_total,
    COALESCE(d.det_rows, 0)                        AS detail_rows,
    c.cols_all_null,
    round((c.col_total - COALESCE(d.det_total,0))::numeric, 2) AS difference
FROM col c
LEFT JOIN det d ON d.report_id = c.id
-- Only rows CHECK D would trip on: a real disagreement, or orphaned columns.
WHERE (
        COALESCE(d.det_rows,0) > 0
        AND abs(c.col_total - COALESCE(d.det_total,0)) > 0.01
      )
   OR (c.col_total <> 0 AND COALESCE(d.det_rows,0) = 0)
ORDER BY classification, c.transaction_date DESC, c.src, c.id;


-- ---------------------------------------------------------------------
-- 2. SUMMARY — one line per classification. Read this first.
--    GENUINE_MISMATCH or ORPHAN_COLUMNS > 0  =>  DO NOT run s5a05.
-- ---------------------------------------------------------------------
WITH cols AS (
    SELECT 'report' AS src, id,
           visa_sales, alipay_sales, wechat_sales, master_sales,
           unionpay_sales, amex_sales, octopus_sales, foodpanda_sales,
           keeta_sales, openrice_sales, deliveroo_sales
      FROM pettycashv2.report
    UNION ALL
    SELECT 'report_draft', id,
           visa_sales, alipay_sales, wechat_sales, master_sales,
           unionpay_sales, amex_sales, octopus_sales, foodpanda_sales,
           keeta_sales, openrice_sales, deliveroo_sales
      FROM pettycashv2.report_draft
), col AS (
    SELECT src, id,
           COALESCE(visa_sales,0)+COALESCE(alipay_sales,0)+COALESCE(wechat_sales,0)
          +COALESCE(master_sales,0)+COALESCE(unionpay_sales,0)+COALESCE(amex_sales,0)
          +COALESCE(octopus_sales,0)+COALESCE(foodpanda_sales,0)+COALESCE(keeta_sales,0)
          +COALESCE(openrice_sales,0)+COALESCE(deliveroo_sales,0) AS col_total,
           (visa_sales IS NULL AND alipay_sales IS NULL AND wechat_sales IS NULL
            AND master_sales IS NULL AND unionpay_sales IS NULL AND amex_sales IS NULL
            AND octopus_sales IS NULL AND foodpanda_sales IS NULL AND keeta_sales IS NULL
            AND openrice_sales IS NULL AND deliveroo_sales IS NULL) AS cols_all_null
      FROM cols
), det AS (
    SELECT report_id, SUM(amount) AS det_total, count(*) AS det_rows
      FROM pettycashv2.report_sale_detail
     WHERE COALESCE(type,'') <> 'Cash'
     GROUP BY report_id
), classified AS (
    SELECT CASE
             WHEN c.cols_all_null AND COALESCE(d.det_rows,0) > 0
                 THEN 'EXPECTED_POST_DEPLOY'
             WHEN c.col_total <> 0 AND COALESCE(d.det_rows,0) = 0
                 THEN 'ORPHAN_COLUMNS'
             ELSE 'GENUINE_MISMATCH'
           END AS classification
      FROM col c
      LEFT JOIN det d ON d.report_id = c.id
     WHERE (
             COALESCE(d.det_rows,0) > 0
             AND abs(c.col_total - COALESCE(d.det_total,0)) > 0.01
           )
        OR (c.col_total <> 0 AND COALESCE(d.det_rows,0) = 0)
)
SELECT classification,
       count(*) AS rows,
       CASE classification
         WHEN 'EXPECTED_POST_DEPLOY' THEN 'Safe. Columns NULL, data is in report_sale_detail.'
         WHEN 'ORPHAN_COLUMNS'       THEN 'DANGER. Dropping destroys this. Re-run s4a04 backfill.'
         ELSE                             'INVESTIGATE. Columns and detail rows disagree.'
       END AS verdict
FROM classified
GROUP BY classification
ORDER BY classification;


-- ---------------------------------------------------------------------
-- 3. HOW MANY reports were submitted after the Step 3 deploy?
--    Sanity check on query 2: EXPECTED_POST_DEPLOY should not exceed this.
-- ---------------------------------------------------------------------
SELECT count(*) FILTER (WHERE visa_sales IS NULL) AS null_column_reports,
       count(*)                                   AS total_reports,
       min(date) FILTER (WHERE visa_sales IS NULL) AS first_null_report,
       max(date) FILTER (WHERE visa_sales IS NULL) AS latest_null_report
FROM pettycashv2.report;


-- =====================================================================
--  IF QUERY 2 SHOWS ONLY EXPECTED_POST_DEPLOY
--
--  s5a05's CHECK D still aborts on those rows, because it cannot tell them
--  apart. Add this to its `det` CTEs — both of them — so all-NULL rows are
--  excluded from the comparison rather than counted as zero:
--
--      -- Skip rows the new code wrote: their columns are NULL by design and
--      -- report_sale_detail is already the source of truth for them.
--      AND NOT (c.cols_all_null)
--
--  Concretely, change CHECK D's two comparison predicates from:
--
--      WHERE abs(c.s - d.s) > 0.01
--
--  to:
--
--      WHERE abs(c.s - d.s) > 0.01
--        AND NOT (c.visa_sales IS NULL AND c.alipay_sales IS NULL AND ...)
--
--  Do this ONLY after this script confirms there are no GENUINE_MISMATCH or
--  ORPHAN_COLUMNS rows. The guard is the last thing standing between you and
--  an irreversible drop — loosen it with evidence, not on faith.
-- =====================================================================
