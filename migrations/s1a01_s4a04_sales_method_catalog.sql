-- =====================================================================
--  SALES METHOD CATALOG — Steps 0, 1, 2, 3, 3.5
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  FINAL TABLE NAMES (the two swap — see Step 0):
--    sale_info            the CATALOG of methods (PK `id`, has `code`)
--    entity_sale_setting  per-entity selection   (PK `sale_id`, has `sale_name`)
--    report_sale_detail   per-report amounts     (unchanged)
--
--  Matching Python classes — note the names do NOT track the tables:
--    SalesMethod -> sale_info
--    SaleInfo    -> entity_sale_setting
--
--  Run this INSTEAD of s6a06_rename_sale_tables.sql. That file exists only
--  for pettycashv2_clone, which was migrated under the old names and renamed
--  afterwards. A database that has never run this script gets the final names
--  in one pass and never needs s6a06.
--
--  Equivalent to migrations s1a01 / s2a02 / s3a03 / s4a04.
--  Wrapped in a single transaction: if any statement fails, NOTHING is
--  applied. Re-runnable — every step guards against double-application.
--
--  This does NOT drop any columns. The 11 *_sales columns stay exactly as
--  they are; Step 5 (dropping them) is deliberately a separate script to be
--  run only after the verification at the bottom returns zero rows.
--
--  If you run migrations with Alembic instead, use the .py files and do NOT
--  run this — you would apply the same changes twice (harmless, but the
--  alembic_version table would not know about them).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- STEP 0 — free the `sale_info` name for the catalog.
--
-- The existing per-entity table is called `sale_info`; the catalog created
-- below TAKES OVER that name. So the incumbent is renamed first:
--
--     sale_info (per-entity selection)  ->  entity_sale_setting
--     [new catalog]                     ->  sale_info
--
-- Postgres tracks tables by OID, so report_sale_detail's FK to
-- sale_info.sale_id follows the rename automatically — no data moves.
--
-- Skipped when already renamed, so this script stays re-runnable.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('pettycashv2.entity_sale_setting') IS NULL THEN
        IF to_regclass('pettycashv2.sale_info') IS NULL THEN
            RAISE EXCEPTION
              'ABORT: neither pettycashv2.sale_info nor entity_sale_setting exists.';
        END IF;
        -- The incumbent is the per-entity table (it has sale_id as PK).
        -- Guard against renaming an already-created catalog by mistake.
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='pettycashv2' AND table_name='sale_info'
              AND column_name='sale_id'
        ) THEN
            ALTER TABLE pettycashv2.sale_info RENAME TO entity_sale_setting;
            RAISE NOTICE 'Renamed sale_info -> entity_sale_setting';
        END IF;
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- STEP 1 — create the catalog + seed the 11 canonical methods
--
-- The catalog is named `sale_info` (it took over the name in Step 0).
-- Its PK is `id`; the per-entity table's PK is `sale_id` — that difference
-- is what the Step 0 guard keys on.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pettycashv2.sale_info (
    id             varchar(36) PRIMARY KEY,
    -- NULL = global catalog row; set = custom method owned by one entity
    entity_id      varchar(36) REFERENCES pettycashv2.entities(id) ON DELETE CASCADE,
    code           varchar(50) NOT NULL,
    name           varchar(80) NOT NULL,
    type           varchar(20) NOT NULL,          -- 'Electronic' | 'Delivery'
    legacy_column  varchar(50),                   -- bridge to *_sales columns; dropped in Step 5
    is_active      boolean     NOT NULL DEFAULT true,
    display_order  integer     NOT NULL DEFAULT 0,
    created_at     timestamp   DEFAULT CURRENT_TIMESTAMP,
    updated_at     timestamp   DEFAULT CURRENT_TIMESTAMP
);

-- NULLS NOT DISTINCT is required: without it Postgres treats every NULL as
-- distinct, so the 11 global rows (entity_id IS NULL) would NOT be protected
-- from duplication. Requires Postgres 15+ (Supabase is 15+).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_sale_info_entity_code'
    ) THEN
        ALTER TABLE pettycashv2.sale_info
            ADD CONSTRAINT uq_sale_info_entity_code
            UNIQUE NULLS NOT DISTINCT (entity_id, code);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_sale_info_legacy_column
    ON pettycashv2.sale_info (legacy_column);

-- Seed. gen_random_uuid() is in core Postgres 13+ (no pgcrypto needed).
-- Deliveroo seeded is_active = FALSE: already filtered out in code
-- (payment_methods.py:47) but still holds historical amounts.
-- Cash is intentionally NOT seeded — separate concept, keeps its column.
INSERT INTO pettycashv2.sale_info
    (id, entity_id, code, name, type, legacy_column, is_active, display_order, created_at, updated_at)
VALUES
    (gen_random_uuid()::text, NULL, 'VISA',      'Visa',       'Electronic', 'visa_sales',      TRUE,  1, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'ALIPAY',    'Alipay',     'Electronic', 'alipay_sales',    TRUE,  2, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'WECHAT',    'WeChat Pay', 'Electronic', 'wechat_sales',    TRUE,  3, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'MASTER',    'Mastercard', 'Electronic', 'master_sales',    TRUE,  4, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'UNIONPAY',  'UnionPay',   'Electronic', 'unionpay_sales',  TRUE,  5, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'AMEX',      'Amex',       'Electronic', 'amex_sales',      TRUE,  6, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'OCTOPUS',   'Octopus',    'Electronic', 'octopus_sales',   TRUE,  7, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'FOODPANDA', 'Food Panda', 'Delivery',   'foodpanda_sales', TRUE,  1, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'KEETA',     'Keeta',      'Delivery',   'keeta_sales',     TRUE,  2, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'OPENRICE',  'OpenRice',   'Delivery',   'openrice_sales',  TRUE,  3, NOW(), NOW()),
    (gen_random_uuid()::text, NULL, 'DELIVEROO', 'Deliveroo',  'Delivery',   'deliveroo_sales', FALSE, 4, NOW(), NOW())
ON CONFLICT (entity_id, code) DO UPDATE
SET name          = EXCLUDED.name,
    type          = EXCLUDED.type,
    legacy_column = EXCLUDED.legacy_column,
    is_active     = EXCLUDED.is_active,
    display_order = EXCLUDED.display_order,
    updated_at    = NOW();


-- ---------------------------------------------------------------------
-- STEP 2 — link sale_info to the catalog
--
-- NOT touched: sale_id (it is sale_info's PRIMARY KEY, and
-- report_sale_detail.sale_id is a FK pointing at it), sale_name (entities
-- rename methods for themselves), value_name / type (kept until Step 5).
-- ---------------------------------------------------------------------

ALTER TABLE pettycashv2.entity_sale_setting
    ADD COLUMN IF NOT EXISTS sale_info_id varchar(36);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_entity_sale_setting_sale_info'
    ) THEN
        ALTER TABLE pettycashv2.entity_sale_setting
            ADD CONSTRAINT fk_entity_sale_setting_sale_info
            FOREIGN KEY (sale_info_id)
            REFERENCES pettycashv2.sale_info(id)
            -- RESTRICT: a catalog row in active use must not vanish from under
            -- an entity. Deactivate it (is_active = FALSE) instead.
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_entity_sale_setting_sale_info_id
    ON pettycashv2.entity_sale_setting (sale_info_id);

-- 2a. Canonical rows: value_name matches a global row's legacy_column.
UPDATE pettycashv2.entity_sale_setting si
SET sale_info_id = sm.id
FROM pettycashv2.sale_info sm
WHERE sm.entity_id IS NULL
  AND sm.legacy_column = si.value_name
  AND si.sale_info_id IS NULL;

-- 2b. Custom rows: replace_sales_methods derives value_name as
--     name.lower().replace(' ','_') || '_sales', so "Tap & Go" becomes
--     'tap_&_go_sales' — matching no catalog row AND no physical column.
--     Mint one per-entity catalog row per distinct (entity_id, value_name)
--     so no sale_info row is left with a NULL FK.
INSERT INTO pettycashv2.sale_info
    (id, entity_id, code, name, type, legacy_column, is_active, display_order, created_at, updated_at)
SELECT
    gen_random_uuid()::text,
    s.entity_id,
    'CUSTOM_' || left(upper(regexp_replace(
        regexp_replace(s.value_name, '_sales$', ''), '[^a-zA-Z0-9]', '_', 'g')), 42),
    COALESCE(s.sale_name, 'Custom'),
    COALESCE(s.type, 'Electronic'),   -- catalog.type is NOT NULL; sale_info.type is not
    NULL,                             -- no legacy column exists for custom methods
    TRUE, 0, NOW(), NOW()
FROM (
    SELECT entity_id, value_name, type, MIN(sale_name) AS sale_name
    FROM pettycashv2.entity_sale_setting
    WHERE sale_info_id IS NULL
      AND entity_id IS NOT NULL
      AND value_name IS NOT NULL
    GROUP BY entity_id, value_name, type
) s
ON CONFLICT (entity_id, code) DO NOTHING;

-- 2c. Link those custom sale_info rows to the rows just minted.
UPDATE pettycashv2.entity_sale_setting si
SET sale_info_id = sm.id
FROM pettycashv2.sale_info sm
WHERE sm.entity_id = si.entity_id
  AND sm.code = 'CUSTOM_' || left(upper(regexp_replace(
        regexp_replace(si.value_name, '_sales$', ''), '[^a-zA-Z0-9]', '_', 'g')), 42)
  AND si.sale_info_id IS NULL;


-- ---------------------------------------------------------------------
-- STEP 3 — link report_sale_detail directly to the catalog
--
-- Denormalized on purpose: ending.py:524 uses outerjoin(SaleInfo) "to include
-- deleted/disabled sale types". When a sale_info row is deleted the amount
-- survives with no way to tell what it was for. This column makes every
-- report self-describing, permanently.
--
-- NOT added: report_draft_id. ending.py:445 creates the revert draft with
-- id = full_report.id, so a report and its draft SHARE one id and one set of
-- detail rows. A second FK would double every sum.
-- ---------------------------------------------------------------------

ALTER TABLE pettycashv2.report_sale_detail
    ADD COLUMN IF NOT EXISTS sales_method_id varchar(36);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_report_sale_detail_sales_method'
    ) THEN
        ALTER TABLE pettycashv2.report_sale_detail
            ADD CONSTRAINT fk_report_sale_detail_sales_method
            FOREIGN KEY (sales_method_id)
            REFERENCES pettycashv2.sale_info(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_report_sale_detail_sales_method_id
    ON pettycashv2.report_sale_detail (sales_method_id);

UPDATE pettycashv2.report_sale_detail rsd
SET sales_method_id = si.sale_info_id
FROM pettycashv2.entity_sale_setting si
WHERE si.sale_id = rsd.sale_id
  AND si.sale_info_id IS NOT NULL
  AND rsd.sales_method_id IS NULL;


-- ---------------------------------------------------------------------
-- STEP 3.5 — BACKFILL: 11 columns -> detail rows   ** MOVES REAL DATA **
--
-- GUARD RULE — per REPORT, not per method:
--   only reports with NO detail rows at all are backfilled.
-- Current code dual-writes SOME methods to detail rows while the columns hold
-- ALL of them. A per-method guard would insert the missing ones and silently
-- disagree with what the app already displays. Per-report is the only safe
-- granularity.
--
-- Excluded: cash_sales (separate concept, keeps its column) and
-- shop_sales / delivery_sales / total_sales (aggregates, not methods).
--
-- sale_id may be NULL on inserted rows: sales_method_id is the authoritative
-- pointer, sale_id is filled opportunistically where a sale_info row still
-- exists. MIN(sale_id) makes duplicate sale_info rows resolve deterministically
-- so they cannot multiply inserted rows.
-- ---------------------------------------------------------------------

WITH src AS (
    SELECT r.id AS report_id, r.company AS entity_id, v.legacy_column, v.amount
    FROM pettycashv2.report r
    CROSS JOIN LATERAL (VALUES
        ('visa_sales',      r.visa_sales),
        ('alipay_sales',    r.alipay_sales),
        ('wechat_sales',    r.wechat_sales),
        ('master_sales',    r.master_sales),
        ('unionpay_sales',  r.unionpay_sales),
        ('amex_sales',      r.amex_sales),
        ('octopus_sales',   r.octopus_sales),
        ('foodpanda_sales', r.foodpanda_sales),
        ('keeta_sales',     r.keeta_sales),
        ('openrice_sales',  r.openrice_sales),
        ('deliveroo_sales', r.deliveroo_sales)
    ) AS v(legacy_column, amount)
    WHERE v.amount IS NOT NULL AND v.amount <> 0
      AND NOT EXISTS (
          SELECT 1 FROM pettycashv2.report_sale_detail d WHERE d.report_id = r.id
      )
)
INSERT INTO pettycashv2.report_sale_detail
    (id, sale_id, report_id, sales_method_id, type, amount, create_at)
SELECT
    gen_random_uuid()::text,
    (SELECT MIN(si.sale_id) FROM pettycashv2.entity_sale_setting si
      WHERE si.entity_id = src.entity_id AND si.sale_info_id = sm.id),
    src.report_id, sm.id, sm.type, src.amount, NOW()
FROM src
JOIN pettycashv2.sale_info sm
  ON sm.entity_id IS NULL AND sm.legacy_column = src.legacy_column;

-- Same again for drafts.
WITH src AS (
    SELECT r.id AS report_id, r.company AS entity_id, v.legacy_column, v.amount
    FROM pettycashv2.report_draft r
    CROSS JOIN LATERAL (VALUES
        ('visa_sales',      r.visa_sales),
        ('alipay_sales',    r.alipay_sales),
        ('wechat_sales',    r.wechat_sales),
        ('master_sales',    r.master_sales),
        ('unionpay_sales',  r.unionpay_sales),
        ('amex_sales',      r.amex_sales),
        ('octopus_sales',   r.octopus_sales),
        ('foodpanda_sales', r.foodpanda_sales),
        ('keeta_sales',     r.keeta_sales),
        ('openrice_sales',  r.openrice_sales),
        ('deliveroo_sales', r.deliveroo_sales)
    ) AS v(legacy_column, amount)
    WHERE v.amount IS NOT NULL AND v.amount <> 0
      AND NOT EXISTS (
          SELECT 1 FROM pettycashv2.report_sale_detail d WHERE d.report_id = r.id
      )
)
INSERT INTO pettycashv2.report_sale_detail
    (id, sale_id, report_id, sales_method_id, type, amount, create_at)
SELECT
    gen_random_uuid()::text,
    (SELECT MIN(si.sale_id) FROM pettycashv2.entity_sale_setting si
      WHERE si.entity_id = src.entity_id AND si.sale_info_id = sm.id),
    src.report_id, sm.id, sm.type, src.amount, NOW()
FROM src
JOIN pettycashv2.sale_info sm
  ON sm.entity_id IS NULL AND sm.legacy_column = src.legacy_column;

COMMIT;


-- =====================================================================
--  POST-RUN CHECKS — run these AFTER the script above commits.
-- =====================================================================

-- A. Catalog seeded? Expect 11 global rows + however many CUSTOM_ rows.
SELECT COALESCE(entity_id, '<global>') AS scope, count(*)
FROM pettycashv2.sale_info GROUP BY 1 ORDER BY 2 DESC;

-- B. Any sale_info row left unlinked? Expect 0.
SELECT count(*) AS unlinked_entity_sale_setting
FROM pettycashv2.entity_sale_setting WHERE sales_method_id IS NULL;

-- C. Any detail row left unlinked? Non-zero here means its sale_info row was
--    hard-deleted before this ran — pre-existing loss, not caused by this.
SELECT count(*) AS unlinked_detail
FROM pettycashv2.report_sale_detail WHERE sales_method_id IS NULL;

-- D. *** THE GATE FOR STEP 5 ***
--     Columns vs detail rows must agree to the cent. MUST RETURN ZERO ROWS
--     before you drop any columns. Anything listed here is a report whose two
--     stores disagree — investigate before dropping, while columns are still
--     the fallback.
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
SELECT c.id AS report_id, c.s AS column_total, d.s AS detail_total,
       round((c.s - d.s)::numeric, 2) AS difference
FROM col c JOIN det d ON d.report_id = c.id
WHERE abs(c.s - d.s) > 0.01
ORDER BY abs(c.s - d.s) DESC;


-- =====================================================================
--  ROLLBACK (only if nothing else has written to these columns since)
-- =====================================================================
-- BEGIN;
-- DELETE FROM pettycashv2.report_sale_detail
--  WHERE sales_method_id IS NOT NULL AND sale_id IS NULL;  -- backfill artefacts only
-- ALTER TABLE pettycashv2.report_sale_detail DROP COLUMN IF EXISTS sales_method_id;
-- ALTER TABLE pettycashv2.entity_sale_setting          DROP COLUMN IF EXISTS sales_method_id;
-- DROP TABLE IF EXISTS pettycashv2.sale_info;
-- COMMIT;
