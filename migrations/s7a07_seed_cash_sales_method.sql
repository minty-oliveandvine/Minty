-- =====================================================================
--  SEED CASH INTO THE SALES CATALOG
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  Target schema: pettycashv2
--
--  Wrapped in a single transaction: if any statement fails, NOTHING is
--  applied. Re-runnable — every step guards against double-application.
--
--  ------------------------------------------------------------------
--  WHY
--
--  s1a01 deliberately excluded Cash from the catalog: cash_sales has its own
--  column, its own `type == "Cash"` branch in get_cash_sales_from_detail, and
--  its own Xero account (cash_sale_account_id). That reasoning was about what
--  happens DOWNSTREAM of a cash sale, and all of it stays true.
--
--  But as a thing a customer paid with, cash is exactly like Visa or Octopus.
--  Excluding it from the catalog costs three things:
--
--    1. The settings page lists every payment method EXCEPT the one most
--       shops take most often. Users notice.
--    2. get_cash_sales_from_detail's fallback to report_draft.cash_sales
--       becomes permanent rather than transitional — an entity with no Cash
--       row can never have a Cash detail row, so the fallback IS the path.
--    3. report_sale_detail is "every payment method except one", which every
--       future query has to remember.
--
--  The sales form already posts sales[shop_sales][cash] (sales.html), and
--  sales.py already reads it at lines 332 and 557. Cash is already a
--  first-class field in the UI — this only makes the DATA match.
--
--  ------------------------------------------------------------------
--  WHAT DELIBERATELY DOES NOT CHANGE
--
--  This script is additive and behaviour-preserving. After it runs:
--
--    * get_cash_sales_from_detail still finds cash by `type == "Cash"`.
--      The new rows carry type='Cash', so the existing branch matches them —
--      no code change needed for the read path to keep working.
--    * The closing-balance formula is untouched:
--        opening + cash_addition + cash_sales - expenses - bank_deposit
--    * report_draft.cash_sales / report.cash_sales KEEP their columns. They
--      are the Step-5 survivors and this does not change that.
--    * Xero still publishes cash against cash_sale_account_id.
--    * The zero-fallback in get_cash_sales_from_detail is NOT touched. It
--      still returns the column value whenever the detail sum is 0, so a
--      genuine zero-cash day still reads the column. Fixing that is a
--      separate change with its own verification — see the note at the end.
--
--  legacy_column = 'cash_sales' is set so the catalog row maps to the
--  physical column exactly as the other 11 do. Unlike theirs, this column is
--  NOT dropped at Step 5 — cash_sales survives. The mapping is what lets
--  sales.py resolve the Cash row by legacy_column like any other method.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- STEP 1 — the global catalog row
--
-- entity_id IS NULL = available to every entity, same as the other 11
-- globals. type='Cash' is a THIRD type alongside 'Electronic' and
-- 'Delivery' — it is what get_cash_sales_from_detail already looks for.
-- ---------------------------------------------------------------------

INSERT INTO pettycashv2.sale_info
    (id, entity_id, code, name, type, legacy_column, is_active, display_order,
     created_at, updated_at)
VALUES
    (gen_random_uuid()::text, NULL, 'CASH', 'Cash', 'Cash', 'cash_sales',
     TRUE, 0, NOW(), NOW())
ON CONFLICT (entity_id, code) DO UPDATE SET
    name          = EXCLUDED.name,
    type          = EXCLUDED.type,
    legacy_column = EXCLUDED.legacy_column,
    is_active     = EXCLUDED.is_active,
    display_order = EXCLUDED.display_order,
    updated_at    = NOW();

-- display_order 0 puts Cash first in the payment method list, ahead of Visa
-- (1) through Octopus (7). It is the most-used method; it should lead.


-- ---------------------------------------------------------------------
-- STEP 2 — give every existing entity a Cash row
--
-- New entities get this automatically: create_default_entity_settings
-- (blueprints/entity/services/shared.py:184) already seeds from the catalog
-- when it is populated. This backfills the entities that already exist.
--
-- Guarded on NOT EXISTS rather than ON CONFLICT because entity_sale_setting
-- has no unique constraint on (entity_id, value_name) — production is known
-- to contain duplicate rows, which is why payment_methods.py dedupes with
-- max(sale_id). An entity that somehow already has a Cash row keeps it.
-- ---------------------------------------------------------------------

INSERT INTO pettycashv2.entity_sale_setting
    (sale_id, entity_id, type, sale_name, value_name, sale_info_id,
     create_date, updated_at, display_order, enabled)
SELECT
    gen_random_uuid()::text,
    e.id,
    'Cash',
    'Cash',
    'cash_sales',
    cat.id,
    NOW(), NOW(),
    0,
    TRUE
FROM pettycashv2.entities e
CROSS JOIN (
    SELECT id FROM pettycashv2.sale_info
    WHERE entity_id IS NULL AND code = 'CASH'
) cat
WHERE NOT EXISTS (
    SELECT 1 FROM pettycashv2.entity_sale_setting ess
    WHERE ess.entity_id = e.id
      AND (ess.sale_info_id = cat.id OR ess.value_name = 'cash_sales')
);


-- ---------------------------------------------------------------------
-- STEP 3 — BACKFILL: cash_sales column -> report_sale_detail
--                                              ** MOVES REAL DATA **
--
-- GUARD RULE — per (report, entity), and only where NO Cash detail row
-- exists yet. Unlike the s1a01 backfill (which guarded per-report on having
-- NO detail rows at all), this one must be per-method: every report already
-- has detail rows for the other 11 methods, so a per-report guard would skip
-- every single one.
--
-- Zero and NULL are skipped. A report with no cash sales gets no row, which
-- reads as zero — and, importantly, keeps get_cash_sales_from_detail's
-- existing zero-fallback behaving exactly as it does today.
--
-- Both report and report_draft are covered. They share an id (ending.py:437),
-- so the NOT EXISTS guard prevents the second pass from double-inserting.
-- ---------------------------------------------------------------------

INSERT INTO pettycashv2.report_sale_detail
    (id, sale_id, report_id, type, amount, create_at)
SELECT
    gen_random_uuid()::text,
    ess.sale_id,
    r.id,
    'Cash',
    r.cash_sales,
    NOW()
FROM pettycashv2.report r
JOIN pettycashv2.entity_sale_setting ess
  ON ess.entity_id = r.company
 AND ess.value_name = 'cash_sales'
WHERE r.cash_sales IS NOT NULL
  AND r.cash_sales <> 0
  AND NOT EXISTS (
      SELECT 1 FROM pettycashv2.report_sale_detail d
      WHERE d.report_id = r.id AND d.sale_id = ess.sale_id
  );

-- Same again for drafts.
INSERT INTO pettycashv2.report_sale_detail
    (id, sale_id, report_id, type, amount, create_at)
SELECT
    gen_random_uuid()::text,
    ess.sale_id,
    rd.id,
    'Cash',
    rd.cash_sales,
    NOW()
FROM pettycashv2.report_draft rd
JOIN pettycashv2.entity_sale_setting ess
  ON ess.entity_id = rd.company
 AND ess.value_name = 'cash_sales'
WHERE rd.cash_sales IS NOT NULL
  AND rd.cash_sales <> 0
  AND NOT EXISTS (
      SELECT 1 FROM pettycashv2.report_sale_detail d
      WHERE d.report_id = rd.id AND d.sale_id = ess.sale_id
  );

COMMIT;


-- =====================================================================
--  POST-RUN CHECKS — run these AFTER the script above commits.
-- =====================================================================

-- A. Catalog row present? Expect exactly 1 row: CASH / Cash / Cash / cash_sales.
SELECT code, name, type, legacy_column, is_active, display_order
FROM pettycashv2.sale_info
WHERE entity_id IS NULL AND code = 'CASH';

-- B. Every entity has exactly one Cash row? Expect 0 rows.
--    Anything returned either has none (the backfill missed it) or more than
--    one (a pre-existing duplicate — see payment_methods.py:38-50).
SELECT e.id, e.name, count(ess.sale_id) AS cash_rows
FROM pettycashv2.entities e
LEFT JOIN pettycashv2.entity_sale_setting ess
       ON ess.entity_id = e.id AND ess.value_name = 'cash_sales'
GROUP BY e.id, e.name
HAVING count(ess.sale_id) <> 1;

-- C. Any Cash detail row left unlinked to the catalog? Expect 0.
SELECT count(*) AS unlinked_cash_detail
FROM pettycashv2.report_sale_detail d
JOIN pettycashv2.entity_sale_setting ess ON ess.sale_id = d.sale_id
WHERE ess.value_name = 'cash_sales'
  AND ess.sale_info_id IS NULL;

-- D. *** THE GATE ***
--     Does the detail row agree with the column, for every report that has
--     one? MUST RETURN ZERO ROWS.
--     This is what proves get_cash_sales_from_detail returns the same number
--     after this migration as it did before.
SELECT r.id, r.cash_sales AS column_value, d.amount AS detail_value
FROM pettycashv2.report r
JOIN pettycashv2.entity_sale_setting ess
  ON ess.entity_id = r.company AND ess.value_name = 'cash_sales'
JOIN pettycashv2.report_sale_detail d
  ON d.report_id = r.id AND d.sale_id = ess.sale_id
WHERE ABS(COALESCE(r.cash_sales, 0) - COALESCE(d.amount, 0)) > 0.01
UNION ALL
SELECT rd.id, rd.cash_sales, d.amount
FROM pettycashv2.report_draft rd
JOIN pettycashv2.entity_sale_setting ess
  ON ess.entity_id = rd.company AND ess.value_name = 'cash_sales'
JOIN pettycashv2.report_sale_detail d
  ON d.report_id = rd.id AND d.sale_id = ess.sale_id
WHERE ABS(COALESCE(rd.cash_sales, 0) - COALESCE(d.amount, 0)) > 0.01;

-- E. Coverage. Compare against DISTINCT ids, not reports + drafts summed:
--    a report and its draft share one id (ending.py:437), so the NOT EXISTS
--    guard means one shared id produces ONE detail row, not two.
--
--    expected_rows must equal actual_rows. A shortfall means the backfill's
--    entity join missed something — most likely a report whose company has no
--    entity_sale_setting Cash row (which check B would also catch).
SELECT
  (SELECT count(DISTINCT id) FROM (
      SELECT id FROM pettycashv2.report
       WHERE cash_sales IS NOT NULL AND cash_sales <> 0
      UNION
      SELECT id FROM pettycashv2.report_draft
       WHERE cash_sales IS NOT NULL AND cash_sales <> 0
   ) x)                                                      AS expected_rows,
  (SELECT count(*) FROM pettycashv2.report_sale_detail d
     JOIN pettycashv2.entity_sale_setting ess ON ess.sale_id = d.sale_id
    WHERE ess.value_name = 'cash_sales'
      AND d.amount IS NOT NULL AND d.amount <> 0)            AS actual_rows,
  -- Informational: the raw per-table counts, which will exceed expected_rows
  -- wherever a report and its draft share an id.
  (SELECT count(*) FROM pettycashv2.report
    WHERE cash_sales IS NOT NULL AND cash_sales <> 0)        AS reports_with_cash,
  (SELECT count(*) FROM pettycashv2.report_draft
    WHERE cash_sales IS NOT NULL AND cash_sales <> 0)        AS drafts_with_cash;


-- =====================================================================
--  FOLLOW-UP, NOT DONE HERE
--
--  get_cash_sales_from_detail (services/shared.py) still falls back to the
--  column whenever the detail sum is 0:
--
--      if cash_sales > 0: return cash_sales
--      else:              return fallback_value
--
--  So a genuine zero-cash day is indistinguishable from "no Cash row
--  exists". Once check B returns zero rows for every entity, that can become
--  a row-existence test instead:
--
--      if any Cash detail row exists: return sum   -- 0 is a real 0
--      else:                          return fallback_value
--
--  That changes an input to the closing-balance formula, so it needs its own
--  smoke test. Deliberately out of scope here.
-- =====================================================================


-- =====================================================================
--  ROLLBACK — only removes what this script created.
--  The cash_sales columns were never cleared, so dropping these rows loses
--  nothing.
-- =====================================================================
-- BEGIN;
-- DELETE FROM pettycashv2.report_sale_detail d
--  USING pettycashv2.entity_sale_setting ess
--  WHERE ess.sale_id = d.sale_id AND ess.value_name = 'cash_sales';
-- DELETE FROM pettycashv2.entity_sale_setting WHERE value_name = 'cash_sales';
-- DELETE FROM pettycashv2.sale_info WHERE entity_id IS NULL AND code = 'CASH';
-- COMMIT;
