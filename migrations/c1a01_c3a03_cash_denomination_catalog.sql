-- =====================================================================
--  CASH DENOMINATION CATALOG — Steps 1, 2, 3
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  Target schema: pettycashv2  (the CURRENT live schema)
--
--  Wrapped in a single transaction: if any statement fails, NOTHING is
--  applied. Re-runnable — every step guards against double-application.
--
--  Goal: adding a cash denomination becomes a single INSERT into
--  pettycashv2.cash_info — no schema change, no code change. Today a
--  denomination needs a migration, a model column, a template edit, and a
--  new hardcoded multiplier in FOUR separate places
--  (cash_count.py:300-309 and ending.py:666, 1157, 1279).
--
--  ------------------------------------------------------------------
--  NAMING follows the proposed v3 schema (docs/01_schema.sql section F)
--  so this migration is a step TOWARD that design, not away from it:
--
--    cash_info            denomination catalog, keyed on currency_id
--    entity_cash_setting  per-entity selection  (mirrors entity_sale_setting)
--    report_cash_count    per-report quantities (mirrors report_sale_detail)
--
--  Deviations from v3, forced by the live schema — all documented at their
--  point of use below:
--    * cash_info keeps its integer `cash_id` PK (v3 uses a UUID `id`);
--      rekeying it would break entity_cash_detail_v2 and report_cash_detail.
--    * report_cash_count.report_id references report_draft(id), because
--      pettycashv2 still splits report / report_draft / report_v2. v3 merges
--      them into one `report` table.
--    * `desc` is not renamed to `description` — it is referenced by the
--      existing CashInfo model. Rename it with the v3 cutover.
--
--  Four corrections applied on top of v3's section F — see
--  docs/cash_denomination_schema_review.md for the full rationale:
--    1. UNIQUE includes `type`, so a $10 note and a $10 coin can coexist.
--       v3's UNIQUE (currency_id, cash_value) silently blocks one of them.
--    2. entity_cash_setting exists at all — v3 has entity_sale_setting for
--       sales channels but no cash equivalent, so an entity cannot hide a
--       denomination it never handles.
--    3. report_cash_count snapshots cash_value, so revaluing a denomination
--       cannot silently re-total published historical reports.
--    4. cash_info gets is_active + display_order, so a withdrawn note can be
--       retired without deleting the counts that reference it.
--
--  This does NOT drop any columns. The nine note/coin columns on
--  report_cashcount_draft stay exactly as they are; they still have five
--  readers, including the next-day opening balance. Dropping them is a
--  separate script, gated on the checks at the bottom.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- STEP 1 — reshape cash_info into a real catalog + seed HKD
--
-- cash_info has existed since 0001_full_schema but was never seeded and is
-- read by nothing.
-- ---------------------------------------------------------------------

-- 1a. Re-key from country_code to currency_id.
--
-- A denomination is a property of the CURRENCY, not the country: two
-- countries sharing a currency would otherwise duplicate every row, and a
-- revaluation would have to touch each copy. The legacy column exists only
-- because that FK already existed on the table.
--
-- currency_id is added alongside country_code and backfilled through
-- country_info.currency_id. country_code is left in place for this migration
-- so nothing that still reads it breaks; the v3 cutover drops it.
ALTER TABLE pettycashv2.cash_info
    ADD COLUMN IF NOT EXISTS currency_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_cash_info_currency'
    ) THEN
        ALTER TABLE pettycashv2.cash_info
            ADD CONSTRAINT fk_cash_info_currency
            FOREIGN KEY (currency_id)
            REFERENCES pettycashv2.currency_info (id) ON DELETE RESTRICT;
    END IF;
END $$;

-- Backfill any pre-existing rows (the table is expected to be empty, but a
-- hand-seeded deployment must not be stranded with a NULL currency_id).
UPDATE pettycashv2.cash_info ci
SET currency_id = co.currency_id
FROM pettycashv2.country_info co
WHERE ci.currency_id IS NULL
  AND ci.country_code IS NOT NULL
  AND TRIM(ci.country_code) = co.country_code;

-- 1b. Catalog columns.
--   is_active     retires a denomination without deleting historical counts
--                 (the FK below is RESTRICT, so deletion is blocked anyway).
--   display_order the order the cash count form renders in.
-- Both mirror what sale_info already has; v3's section F omits them.
ALTER TABLE pettycashv2.cash_info
    ADD COLUMN IF NOT EXISTS display_order integer NOT NULL DEFAULT 999,
    ADD COLUMN IF NOT EXISTS is_active     boolean NOT NULL DEFAULT true;

-- 1c. Uniqueness INCLUDING type.
--
-- v3 proposes UNIQUE (currency_id, cash_value). HKD circulates BOTH a $10
-- note and a $10 coin, so that constraint admits only one of them —
-- see docs/cash_denomination_schema_review.md point 1.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_cash_info_currency_value_type'
    ) THEN
        ALTER TABLE pettycashv2.cash_info
            ADD CONSTRAINT uq_cash_info_currency_value_type
            UNIQUE (currency_id, cash_value, type);
    END IF;
END $$;

-- 1d. cash_id must self-assign, or adding a denomination needs a
-- MAX(cash_id)+1 race. v3 uses gen_random_uuid() and avoids this entirely;
-- here the integer PK is retained because entity_cash_detail_v2 and
-- report_cash_detail both FK it.
--
-- Only convert a column with NO default: a live database may already have it
-- as serial (a plain DEFAULT nextval), which is functionally equivalent —
-- and Postgres rejects adding an identity on top of an existing default with
-- "column ... already has a default value".
DO $$
DECLARE
    has_default boolean;
    is_identity boolean;
BEGIN
    SELECT a.atthasdef, a.attidentity <> ''
      INTO has_default, is_identity
    FROM pg_attribute a
    WHERE a.attrelid = 'pettycashv2.cash_info'::regclass
      AND a.attname = 'cash_id';

    IF is_identity THEN
        RAISE NOTICE 'cash_info.cash_id is already an identity column';
    ELSIF has_default THEN
        RAISE NOTICE 'cash_info.cash_id already has a default (serial); leaving as-is';
    ELSE
        ALTER TABLE pettycashv2.cash_info
            ALTER COLUMN cash_id ADD GENERATED BY DEFAULT AS IDENTITY;
    END IF;
END $$;

-- The cash count form's read path: denominations for one currency, in order.
CREATE INDEX IF NOT EXISTS ix_cash_info_currency_order
    ON pettycashv2.cash_info (currency_id, display_order);

-- 1e. Seed HKD.
--
-- Face values sourced from the hardcoded multipliers in
-- cash_count.py:300-309. Notes descend, then coins descend; display_order is
-- global across both so the form renders one continuous list.
--
-- These nine rows are EXACTLY the denominations the cash count form can post
-- today (the nine actual_cash[...] fields in cash_count.html:237-245). The
-- catalog and the form agree, so nothing is offered that cannot be recorded.
--
-- Deliberately NOT seeded, pending the form rendering from this catalog:
--   * HK$200 note — no form field and no column; the value was dropped on
--     save. (The catalog rewrite removed that phantom parse.)
--   * HK$10 coin  — cash_count.html defines a '10coins' input with an id but
--     no name, so it adds to the total the cashier sees and never posts.
-- Both are one INSERT away once the form loops over this table. Note that
-- the $10 coin is only expressible because of the `type` in the constraint
-- at 1c.
DO $$
DECLARE hkd uuid;
BEGIN
    SELECT id INTO hkd FROM pettycashv2.currency_info WHERE currency_code = 'HKD';
    IF hkd IS NULL THEN
        RAISE EXCEPTION
            'currency_info has no HKD row — run the e5b7d9f1a3c6 currency seed first';
    END IF;

    INSERT INTO pettycashv2.cash_info
        (currency_id, country_code, type, cash_value, cash_name, "desc",
         display_order, is_active)
    VALUES
        (hkd, 'HK', 'note', 1000, '$1,000', 'HK$1,000 note',  1, true),
        (hkd, 'HK', 'note',  500, '$500',   'HK$500 note',    2, true),
        (hkd, 'HK', 'note',  100, '$100',   'HK$100 note',    3, true),
        (hkd, 'HK', 'note',   50, '$50',    'HK$50 note',     4, true),
        (hkd, 'HK', 'note',   20, '$20',    'HK$20 note',     5, true),
        (hkd, 'HK', 'note',   10, '$10',    'HK$10 note',     6, true),
        (hkd, 'HK', 'coin',    5, '$5',     'HK$5 coin',      7, true),
        (hkd, 'HK', 'coin',    2, '$2',     'HK$2 coin',      8, true),
        (hkd, 'HK', 'coin',    1, '$1',     'HK$1 coin',      9, true)
    ON CONFLICT (currency_id, cash_value, type) DO UPDATE SET
        cash_name     = EXCLUDED.cash_name,
        "desc"        = EXCLUDED."desc",
        display_order = EXCLUDED.display_order;
END $$;


-- ---------------------------------------------------------------------
-- STEP 2 — per-denomination count storage + per-entity selection
-- ---------------------------------------------------------------------

-- 2a. report_cash_count — v3's name and shape, plus a face-value snapshot.
--
-- report_id references report_draft(id) because pettycashv2 still splits
-- report / report_draft / report_v2. A report and its draft SHARE one id
-- (ending.py:445 creates the revert draft with id=full_report.id), so one set
-- of rows serves both — the same reason the sales runbook warns against
-- adding a separate report_draft_id to report_sale_detail. When v3 merges
-- the three tables, this FK re-points at report(id) with no data change.
CREATE TABLE IF NOT EXISTS pettycashv2.report_cash_count (
    id          varchar(36) PRIMARY KEY,
    report_id   varchar(36) NOT NULL
                REFERENCES pettycashv2.report_draft(id) ON DELETE CASCADE,
    -- RESTRICT, not CASCADE: deleting a denomination must never silently
    -- delete the historical counts referencing it. Retire with is_active.
    cash_id     integer     NOT NULL
                REFERENCES pettycashv2.cash_info(cash_id) ON DELETE RESTRICT,
    -- v3 calls this `quantity`. Integer — you cannot hold half a note.
    quantity    integer     NOT NULL DEFAULT 0,
    -- NOT in v3. Face value AS AT the time of counting: without it, revaluing
    -- or retiring a denomination silently re-totals every published
    -- historical report. See schema review point 3.
    cash_value  numeric(12,2) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    -- One count per denomination per report. What the app's upsert targets,
    -- and what stops a double-submit doubling a total.
    CONSTRAINT report_cash_count_uq UNIQUE (report_id, cash_id),
    CONSTRAINT chk_rcc_qty CHECK (quantity >= 0)
);

CREATE INDEX IF NOT EXISTS ix_report_cash_count_report
    ON pettycashv2.report_cash_count (report_id);

-- 2b. entity_cash_setting — the cash mirror of entity_sale_setting.
--
-- NOT in v3 (schema review point 2). Without it a shop that never handles
-- HK$1,000 notes cannot hide that row from its cash count.
--
-- A row exists ONLY where the entity diverges from its currency default, so
-- an entity with no rows sees every active cash_info row for its currency
-- and automatically picks up denominations added later. That is why there is
-- no per-entity seed here.
--
-- Deliberately NOT reusing entity_cash_detail_v2 (entity_id + cash_id,
-- already exists, already FKs both sides): it holds cash_instock, a running
-- quantity-on-hand. Overloading it would make a row's absence ambiguous
-- between "not stocked" and "not tracked", and enabling a denomination would
-- silently invent a stock figure.
--
-- Column names mirror entity_sale_setting exactly (is_active, not `enabled`).
CREATE TABLE IF NOT EXISTS pettycashv2.entity_cash_setting (
    entity_id     varchar(36) NOT NULL
                  REFERENCES pettycashv2.entities(id) ON DELETE CASCADE,
    cash_id       integer     NOT NULL
                  REFERENCES pettycashv2.cash_info(cash_id) ON DELETE CASCADE,
    is_active     boolean     NOT NULL DEFAULT true,
    -- NULL inherits cash_info.display_order. Set only when an entity
    -- reorders its own list.
    display_order integer,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT entity_cash_setting_pkey PRIMARY KEY (entity_id, cash_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_cash_setting_entity
    ON pettycashv2.entity_cash_setting (entity_id);


-- ---------------------------------------------------------------------
-- STEP 3 — BACKFILL: nine columns -> count rows   ** MOVES REAL DATA **
--
-- GUARD RULE — per REPORT, not per denomination:
--   only reports with NO count rows at all are backfilled.
-- Same rationale as the sales backfill: a per-denomination guard would
-- insert missing ones alongside app-written rows and silently disagree with
-- what is displayed. Per-report is the only safe granularity.
--
-- Only HKD denominations are targeted. Every historical count was entered
-- through a form whose face values were hardcoded HKD, so HKD is what those
-- numbers mean regardless of the entity's currency. Mapping them to another
-- currency's catalog would silently revalue them.
--
-- Zero and NULL counts are skipped — the columns default to 0 and most
-- reports leave most denominations empty. A missing row reads as zero (the
-- service layer coalesces), so totals are identical either way.
--
-- There is no note200 column to backfill: the value was never persisted.
-- ---------------------------------------------------------------------

WITH src AS (
    SELECT cd.report_id, v.cash_value, v.kind, v.qty
    FROM pettycashv2.report_cashcount_draft cd
    CROSS JOIN LATERAL (VALUES
        (1000::numeric, 'note', cd.thousand_note),
        ( 500::numeric, 'note', cd.fivehundred_note),
        ( 100::numeric, 'note', cd.onehundred_note),
        (  50::numeric, 'note', cd.fifty_note),
        (  20::numeric, 'note', cd.twenty_note),
        (  10::numeric, 'note', cd.ten_note),
        (   5::numeric, 'coin', cd.five_coin),
        (   2::numeric, 'coin', cd.two_coin),
        (   1::numeric, 'coin', cd.one_coin)
    ) AS v(cash_value, kind, qty)
    WHERE v.qty IS NOT NULL AND v.qty <> 0
      -- A draft deleted between migrations simply has no row here; FK holds.
      AND EXISTS (
          SELECT 1 FROM pettycashv2.report_draft d WHERE d.id = cd.report_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM pettycashv2.report_cash_count x
          WHERE x.report_id = cd.report_id
      )
)
INSERT INTO pettycashv2.report_cash_count
    (id, report_id, cash_id, quantity, cash_value, created_at, updated_at)
SELECT
    gen_random_uuid()::text,
    src.report_id, ci.cash_id, src.qty, ci.cash_value, now(), now()
FROM src
JOIN pettycashv2.currency_info cu ON cu.currency_code = 'HKD'
JOIN pettycashv2.cash_info ci
  ON ci.currency_id = cu.id
 AND ci.cash_value  = src.cash_value
 AND ci.type        = src.kind;

COMMIT;


-- =====================================================================
--  POST-RUN CHECKS — run these AFTER the script above commits.
-- =====================================================================

-- A. Catalog seeded? Expect 9 HKD rows + however many custom rows.
SELECT cu.currency_code, count(*)
FROM pettycashv2.cash_info ci
JOIN pettycashv2.currency_info cu ON cu.id = ci.currency_id
GROUP BY 1 ORDER BY 2 DESC;

-- B. Rows well-formed? Expect 9, display_order 1..9, no NULL currency_id.
SELECT ci.cash_id, ci.type, ci.cash_value, ci.cash_name,
       ci.display_order, ci.is_active, cu.currency_code
FROM pettycashv2.cash_info ci
LEFT JOIN pettycashv2.currency_info cu ON cu.id = ci.currency_id
ORDER BY ci.display_order;

-- C. Entities whose currency has no denominations. These would render an
--    EMPTY cash count form. Expect 0 rows.
--    COALESCE: entities.currency_id is authoritative; fall back to the
--    country's currency for any entity where it was never backfilled.
SELECT e.id, e.name, e.country_code, e.currency_id
FROM pettycashv2.entities e
LEFT JOIN pettycashv2.country_info co ON co.country_code = e.country_code
WHERE e.status = 'active'
  AND NOT EXISTS (
      SELECT 1 FROM pettycashv2.cash_info ci
      WHERE ci.currency_id = COALESCE(e.currency_id, co.currency_id)
        AND ci.is_active
  );

-- D. *** THE GATE FOR DROPPING THE NINE COLUMNS ***
--     Column-derived total vs count-row total, per report. Uses the same
--     arithmetic cash_count.py:300-323 uses today.
--     MUST RETURN ZERO ROWS before the columns are dropped.
WITH col AS (
    SELECT cd.report_id,
           (COALESCE(cd.thousand_note,0)    * 1000
          + COALESCE(cd.fivehundred_note,0) *  500
          + COALESCE(cd.onehundred_note,0)  *  100
          + COALESCE(cd.fifty_note,0)       *   50
          + COALESCE(cd.twenty_note,0)      *   20
          + COALESCE(cd.ten_note,0)         *   10
          + COALESCE(cd.five_coin,0)        *    5
          + COALESCE(cd.two_coin,0)         *    2
          + COALESCE(cd.one_coin,0)         *    1)::numeric AS column_total
    FROM pettycashv2.report_cashcount_draft cd
), det AS (
    SELECT report_id, SUM(quantity * cash_value) AS detail_total
    FROM pettycashv2.report_cash_count GROUP BY report_id
)
SELECT col.report_id, col.column_total, det.detail_total
FROM col JOIN det ON det.report_id = col.report_id
WHERE ABS(col.column_total - det.detail_total) > 0.01;

-- E. Stored actual_cash_total vs count rows. actual_cash_total feeds the
--    NEXT DAY'S opening balance (opening.py:1044, create.py:284), so a
--    mismatch here propagates forward. Expect 0 rows.
SELECT cd.report_id, cd.actual_cash_total,
       SUM(d.quantity * d.cash_value) AS detail_total
FROM pettycashv2.report_cashcount_draft cd
JOIN pettycashv2.report_cash_count d ON d.report_id = cd.report_id
GROUP BY cd.report_id, cd.actual_cash_total
HAVING ABS(COALESCE(cd.actual_cash_total,0) - SUM(d.quantity * d.cash_value)) > 0.01;


-- =====================================================================
--  ROLLBACK — only removes what this script created.
--  The nine columns were never cleared, so dropping the count rows loses
--  nothing.
-- =====================================================================
-- BEGIN;
-- DROP TABLE IF EXISTS pettycashv2.entity_cash_setting;
-- DROP TABLE IF EXISTS pettycashv2.report_cash_count;
-- DELETE FROM pettycashv2.cash_info
--  WHERE currency_id = (SELECT id FROM pettycashv2.currency_info
--                        WHERE currency_code = 'HKD');
-- ALTER TABLE pettycashv2.cash_info
--     DROP CONSTRAINT IF EXISTS uq_cash_info_currency_value_type,
--     DROP CONSTRAINT IF EXISTS fk_cash_info_currency,
--     DROP COLUMN IF EXISTS currency_id,
--     DROP COLUMN IF EXISTS display_order,
--     DROP COLUMN IF EXISTS is_active;
-- COMMIT;
