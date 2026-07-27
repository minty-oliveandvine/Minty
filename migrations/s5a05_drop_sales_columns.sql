-- =====================================================================
--  STEP 5 — DROP the 11 per-method sales columns   ** IRREVERSIBLE **
--
--  Run ONLY after all of these are true:
--    1. s1a01_s4a04_sales_method_catalog.sql has been applied
--    2. Check D returns ZERO rows (verified below — this script aborts if not)
--    3. The Step 3 code changes are DEPLOYED and running in production
--    4. You have a database backup
--
--  A down-migration can recreate these columns but NOT their data. The
--  amounts live in report_sale_detail after this; the columns are redundant
--  copies. Once dropped, the only way back is the backup.
--
--  Ordering matters: deploy the code FIRST. The models no longer declare
--  these columns, so a running old build would emit them in every SELECT and
--  break the moment they disappear.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — abort the whole transaction unless it is safe to drop.
-- Nothing below runs if any check fails.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    v_catalog_rows   int;
    v_mismatch       int;
    v_unlinked_si    int;
    v_orphan_amounts int;
BEGIN
    -- (a) the catalog must exist and be seeded
    SELECT count(*) INTO v_catalog_rows
      FROM pettycashv2.sales_method WHERE entity_id IS NULL;
    IF v_catalog_rows < 11 THEN
        RAISE EXCEPTION
          'ABORT: sales_method has % global rows, expected >= 11. Run s1a01_s4a04 first.',
          v_catalog_rows;
    END IF;

    -- (b) CHECK D — columns and detail rows must agree to the cent,
    --     for reports AND drafts.
    SELECT count(*) INTO v_mismatch FROM (
        WITH col AS (
            SELECT id, COALESCE(visa_sales,0)+COALESCE(alipay_sales,0)+COALESCE(wechat_sales,0)
                      +COALESCE(master_sales,0)+COALESCE(unionpay_sales,0)+COALESCE(amex_sales,0)
                      +COALESCE(octopus_sales,0)+COALESCE(foodpanda_sales,0)+COALESCE(keeta_sales,0)
                      +COALESCE(openrice_sales,0)+COALESCE(deliveroo_sales,0) AS s
            FROM pettycashv2.report
        ), det AS (
            SELECT report_id, SUM(amount) AS s
            FROM pettycashv2.report_sale_detail GROUP BY report_id
        )
        SELECT c.id FROM col c JOIN det d ON d.report_id = c.id
        WHERE abs(c.s - d.s) > 0.01
        UNION ALL
        SELECT c.id FROM (
            SELECT id, COALESCE(visa_sales,0)+COALESCE(alipay_sales,0)+COALESCE(wechat_sales,0)
                      +COALESCE(master_sales,0)+COALESCE(unionpay_sales,0)+COALESCE(amex_sales,0)
                      +COALESCE(octopus_sales,0)+COALESCE(foodpanda_sales,0)+COALESCE(keeta_sales,0)
                      +COALESCE(openrice_sales,0)+COALESCE(deliveroo_sales,0) AS s
            FROM pettycashv2.report_draft
        ) c JOIN (
            SELECT report_id, SUM(amount) AS s
            FROM pettycashv2.report_sale_detail GROUP BY report_id
        ) d ON d.report_id = c.id
        WHERE abs(c.s - d.s) > 0.01
    ) x;
    IF v_mismatch > 0 THEN
        RAISE EXCEPTION
          'ABORT: % report(s)/draft(s) disagree between columns and detail rows. Investigate BEFORE dropping — the columns are the only fallback.',
          v_mismatch;
    END IF;

    -- (c) every sale_info row should be linked, or new writes are landing
    --     without a catalog id (Step 2 code not deployed?)
    SELECT count(*) INTO v_unlinked_si
      FROM pettycashv2.sale_info WHERE sales_method_id IS NULL;
    IF v_unlinked_si > 0 THEN
        RAISE WARNING
          'WARNING: % sale_info row(s) have no sales_method_id. New rows may be created unlinked — verify the Step 2 code is deployed.',
          v_unlinked_si;
    END IF;

    -- (d) reports holding column amounts but NO detail rows would lose data
    SELECT count(*) INTO v_orphan_amounts FROM pettycashv2.report r
     WHERE (COALESCE(r.visa_sales,0)+COALESCE(r.alipay_sales,0)+COALESCE(r.wechat_sales,0)
           +COALESCE(r.master_sales,0)+COALESCE(r.unionpay_sales,0)+COALESCE(r.amex_sales,0)
           +COALESCE(r.octopus_sales,0)+COALESCE(r.foodpanda_sales,0)+COALESCE(r.keeta_sales,0)
           +COALESCE(r.openrice_sales,0)+COALESCE(r.deliveroo_sales,0)) <> 0
       AND NOT EXISTS (SELECT 1 FROM pettycashv2.report_sale_detail d
                        WHERE d.report_id = r.id);
    IF v_orphan_amounts > 0 THEN
        RAISE EXCEPTION
          'ABORT: % report(s) have column amounts but NO detail rows — dropping would DESTROY that data. Re-run the s4a04 backfill.',
          v_orphan_amounts;
    END IF;

    RAISE NOTICE 'All guards passed. Dropping 11 per-method columns.';
END $$;


-- ---------------------------------------------------------------------
-- DROP — the 11 per-method columns only.
--
-- KEPT deliberately:
--   cash_sales      — separate concept, its own totals branch
--   shop_sales      — aggregate cache, read in ~20 places
--   delivery_sales  — aggregate cache
--   total_sales     — aggregate cache
-- ---------------------------------------------------------------------

ALTER TABLE pettycashv2.report
    DROP COLUMN IF EXISTS visa_sales,
    DROP COLUMN IF EXISTS alipay_sales,
    DROP COLUMN IF EXISTS wechat_sales,
    DROP COLUMN IF EXISTS master_sales,
    DROP COLUMN IF EXISTS unionpay_sales,
    DROP COLUMN IF EXISTS amex_sales,
    DROP COLUMN IF EXISTS octopus_sales,
    DROP COLUMN IF EXISTS foodpanda_sales,
    DROP COLUMN IF EXISTS keeta_sales,
    DROP COLUMN IF EXISTS openrice_sales,
    DROP COLUMN IF EXISTS deliveroo_sales;

ALTER TABLE pettycashv2.report_draft
    DROP COLUMN IF EXISTS visa_sales,
    DROP COLUMN IF EXISTS alipay_sales,
    DROP COLUMN IF EXISTS wechat_sales,
    DROP COLUMN IF EXISTS master_sales,
    DROP COLUMN IF EXISTS unionpay_sales,
    DROP COLUMN IF EXISTS amex_sales,
    DROP COLUMN IF EXISTS octopus_sales,
    DROP COLUMN IF EXISTS foodpanda_sales,
    DROP COLUMN IF EXISTS keeta_sales,
    DROP COLUMN IF EXISTS openrice_sales,
    DROP COLUMN IF EXISTS deliveroo_sales;

COMMIT;


-- =====================================================================
--  STEP 5b — transition bridges. RUN SEPARATELY, and only once you are
--  confident nothing needs to map a method back to a physical column.
--
--  Held back from the main transaction on purpose:
--    * sale_info.value_name is still the join key in several read paths
--      (get_unique_sale_info_for_entity, the sales_amounts template dicts).
--      Dropping it now would break them.
--    * sales_method.legacy_column is what made the backfill possible; keep it
--      until you are sure no re-backfill is needed.
--
--  Do NOT run this until value_name has been removed from the code.
-- =====================================================================
-- BEGIN;
-- ALTER TABLE pettycashv2.sales_method DROP COLUMN IF EXISTS legacy_column;
-- ALTER TABLE pettycashv2.sale_info    DROP COLUMN IF EXISTS value_name;
-- ALTER TABLE pettycashv2.sale_info    DROP COLUMN IF EXISTS type;
-- COMMIT;


-- =====================================================================
--  POST-DROP VERIFICATION — run after the COMMIT above.
-- =====================================================================

-- 1. The 11 are gone, the 4 survivors remain. Expect exactly:
--    cash_sales, delivery_sales, shop_sales, total_sales
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'pettycashv2'
  AND table_name IN ('report', 'report_draft')
  AND column_name LIKE '%_sales'
ORDER BY table_name, column_name;

-- 2. Detail rows still resolve to a method. Expect unlinked = 0.
SELECT count(*) FILTER (WHERE sales_method_id IS NULL) AS unlinked,
       count(*)                                        AS total
FROM pettycashv2.report_sale_detail;

-- 3. Aggregates still reconcile against the detail rows they now derive from.
--    Expect zero rows.
WITH det AS (
    SELECT report_id, SUM(amount) AS s
    FROM pettycashv2.report_sale_detail GROUP BY report_id
)
SELECT r.id, r.total_sales, d.s AS detail_total,
       round((COALESCE(r.total_sales,0) - COALESCE(d.s,0))::numeric, 2) AS difference
FROM pettycashv2.report r
JOIN det d ON d.report_id = r.id
WHERE abs(COALESCE(r.total_sales,0) - COALESCE(r.cash_sales,0) - COALESCE(d.s,0)) > 0.01
ORDER BY 4 DESC
LIMIT 50;
