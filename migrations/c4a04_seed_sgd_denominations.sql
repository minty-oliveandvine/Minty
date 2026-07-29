-- =====================================================================
--  SEED SGD DENOMINATIONS into pettycashv2.cash_info
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  Prerequisite: c1a01_c3a03_cash_denomination_catalog.sql must have run.
--  That script adds currency_id, display_order, is_active and the
--  UNIQUE (currency_id, cash_value, type) this INSERT conflict-targets.
--
--  Re-runnable: ON CONFLICT DO UPDATE refreshes the descriptive columns
--  and leaves cash_id — and therefore every report_cash_count row that
--  FKs it — untouched.
--
--  No schema change and no code change: the catalog exists precisely so
--  that a new currency is an INSERT.
-- =====================================================================

BEGIN;

DO $$
DECLARE
    sgd        uuid := 'a4e05795-c10e-4a1a-81bb-c07dee783d0a';
    sgd_actual uuid;
BEGIN
    -- The currency_id is supplied as a literal rather than looked up by
    -- code, so verify it is the row it is claimed to be. A wrong UUID that
    -- happened to exist would silently file SGD notes under another
    -- currency, and the cash count form would then offer them to the wrong
    -- entities.
    SELECT id INTO sgd_actual
    FROM pettycashv2.currency_info
    WHERE currency_code = 'SGD';

    IF sgd_actual IS NULL THEN
        RAISE EXCEPTION
            'currency_info has no SGD row — run the e5b7d9f1a3c6 currency seed first';
    END IF;

    IF sgd_actual <> sgd THEN
        RAISE EXCEPTION
            'SGD currency_id mismatch: this script expects %, but currency_info holds %',
            sgd, sgd_actual;
    END IF;

    -- country_code is the legacy column the v3 cutover drops. It FKs
    -- country_info.country_code, which is CHARACTER(2) with a
    -- length = 2 CHECK — so 'SG', not the alpha-3 'SGP'.
    IF NOT EXISTS (
        SELECT 1 FROM pettycashv2.country_info WHERE country_code = 'SG'
    ) THEN
        RAISE EXCEPTION
            'country_info has no SG row — the country_code FK would reject these inserts';
    END IF;

    -- Denominations of the Singapore dollar. Notes descend, then coins
    -- descend; display_order is global across both so the cash count form
    -- renders one continuous list, matching the HKD convention.
    --
    -- The $1,000 and $10,000 notes were withdrawn from issue (2014 and
    -- 2021 respectively) but REMAIN LEGAL TENDER, so they are seeded and
    -- left active. Retire either with is_active = false rather than a
    -- DELETE, which report_cash_count's ON DELETE RESTRICT blocks anyway
    -- once counts reference it.
    --
    -- Unlike HKD, SGD circulates sub-dollar coins. cash_value is
    -- numeric(12,2), so 0.05 stores exactly; nothing here relies on the
    -- whole-dollar values the HKD seed happens to use.
    --
    -- cash_name is varchar(10) — every value below fits, '$10,000' being
    -- the longest at 7 characters.
    INSERT INTO pettycashv2.cash_info
        (currency_id, country_code, type, cash_value, cash_name, "desc",
         display_order, is_active)
    VALUES
        (sgd, 'SG', 'note', 10000, '$10,000', 'S$10,000 note',  1, true),
        (sgd, 'SG', 'note',  1000, '$1,000',  'S$1,000 note',   2, true),
        (sgd, 'SG', 'note',   100, '$100',    'S$100 note',     3, true),
        (sgd, 'SG', 'note',    50, '$50',     'S$50 note',      4, true),
        (sgd, 'SG', 'note',    10, '$10',     'S$10 note',      5, true),
        (sgd, 'SG', 'note',     5, '$5',      'S$5 note',       6, true),
        (sgd, 'SG', 'note',     2, '$2',      'S$2 note',       7, true),
        (sgd, 'SG', 'coin',     1, '$1',      'S$1 coin',       8, true),
        (sgd, 'SG', 'coin',  0.50, '50c',     'S$0.50 coin',    9, true),
        (sgd, 'SG', 'coin',  0.20, '20c',     'S$0.20 coin',   10, true),
        (sgd, 'SG', 'coin',  0.10, '10c',     'S$0.10 coin',   11, true),
        (sgd, 'SG', 'coin',  0.05, '5c',      'S$0.05 coin',   12, true)
    ON CONFLICT (currency_id, cash_value, type) DO UPDATE SET
        cash_name     = EXCLUDED.cash_name,
        "desc"        = EXCLUDED."desc",
        display_order = EXCLUDED.display_order;
END $$;

COMMIT;


-- =====================================================================
--  POST-RUN CHECKS — run these AFTER the script above commits.
-- =====================================================================

-- A. Seeded? Expect one SGD row with count 12.
SELECT cu.currency_code, count(*)
FROM pettycashv2.cash_info ci
JOIN pettycashv2.currency_info cu ON cu.id = ci.currency_id
GROUP BY 1 ORDER BY 1;

-- B. Rows well-formed? Expect 12, display_order 1..12, no gaps or dupes,
--    sub-dollar coins showing exact .50/.20/.10/.05.
SELECT ci.cash_id, ci.type, ci.cash_value, ci.cash_name, ci."desc",
       ci.display_order, ci.is_active, ci.country_code
FROM pettycashv2.cash_info ci
WHERE ci.currency_id = 'a4e05795-c10e-4a1a-81bb-c07dee783d0a'
ORDER BY ci.display_order;

-- C. Singapore entities can now render a non-empty cash count form.
--    Expect 0 rows. Same COALESCE rationale as check C in c1a01_c3a03:
--    entities.currency_id is authoritative, country currency is fallback.
SELECT e.id, e.name, e.country_code, e.currency_id
FROM pettycashv2.entities e
LEFT JOIN pettycashv2.country_info co ON co.country_code = e.country_code
WHERE e.status = 'active'
  AND COALESCE(e.currency_id, co.currency_id)
      = 'a4e05795-c10e-4a1a-81bb-c07dee783d0a'
  AND NOT EXISTS (
      SELECT 1 FROM pettycashv2.cash_info ci
      WHERE ci.currency_id = COALESCE(e.currency_id, co.currency_id)
        AND ci.is_active
  );


-- =====================================================================
--  ROLLBACK — only removes what this script created.
--  Fails loudly if any report_cash_count row references an SGD
--  denomination (ON DELETE RESTRICT). That is deliberate: deactivate
--  instead of deleting once real counts exist.
-- =====================================================================
-- BEGIN;
-- DELETE FROM pettycashv2.cash_info
--  WHERE currency_id = 'a4e05795-c10e-4a1a-81bb-c07dee783d0a';
-- COMMIT;

-- Deactivate-instead-of-delete:
-- UPDATE pettycashv2.cash_info SET is_active = false
--  WHERE currency_id = 'a4e05795-c10e-4a1a-81bb-c07dee783d0a';
