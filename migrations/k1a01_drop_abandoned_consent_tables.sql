-- =====================================================================
--  CLEANUP — drop the four abandoned consent tables
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision k1a01_drop_consent.
--  Run the .sql OR the .py — never both.
--
--  *** ENDS IN ROLLBACK. *** Run once as-is to read the output, then change
--  the last line to COMMIT.
--
--  ------------------------------------------------------------------
--  WHAT THESE WERE
--
--    2026-06-24  commit 42f73fab  added blueprints/consent/ and migration
--                093b4bd031f1, which created four tables: terms_version,
--                terms_user_principal, consent_record, consent_event.
--
--    2026-07-08  commit 4baa65ef  deleted the whole blueprints/consent/
--                module AND that migration — but never dropped the tables.
--                They have sat in the database ever since with nothing in
--                the repo that creates, reads or writes them.
--
--  The Terms of Use feature that actually shipped uses ONE table,
--  pettycashv2.terms_consent. That one is LIVE. Do not touch it.
--
--  ------------------------------------------------------------------
--  *** DO NOT CONFUSE WITH entity_billing_consent ***
--
--  pettycashv2.entity_billing_consent has 19 rows and is in active use. It
--  records that a company agreed to be CHARGED for a subscription, and
--  belongs to blueprints/subscription. It has nothing to do with the Terms.
--  It is NOT in the list below, and must not be added to it.
--
--  ------------------------------------------------------------------
--  WHY THIS IS SAFE
--
--    * 0 rows in all four (re-verified by section 1 below before dropping)
--    * 0 foreign keys point at them from outside the set
--    * 0 views depend on them
--    * 0 references anywhere in the codebase
--    * 093b4bd031f1 is NOT in alembic_version, so no stale revision
--
--  This reclaims no space. It removes ambiguity: someone looking for "the
--  terms table" currently finds five candidates, four of which are dead.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. PRE-FLIGHT — refuse outright if any of them hold rows.
--
--    They were empty when this was written and nothing writes to them. But
--    a migration that destroys data because an assumption went stale is the
--    one nobody forgives, so check rather than trust.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t   text;
    n   bigint;
BEGIN
    FOREACH t IN ARRAY ARRAY['consent_event', 'consent_record',
                             'terms_user_principal', 'terms_version']
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'pettycashv2' AND table_name = t) THEN
            EXECUTE format('SELECT count(*) FROM pettycashv2.%I', t) INTO n;
            RAISE NOTICE '%: % row(s)', t, n;
            IF n > 0 THEN
                RAISE EXCEPTION
                  'pettycashv2.% holds % row(s) — something has started using it. Investigate before dropping.', t, n;
            END IF;
        ELSE
            RAISE NOTICE '%: already absent', t;
        END IF;
    END LOOP;
END $$;


-- ---------------------------------------------------------------------
-- 2. SANITY — the live table must still be here and populated.
--
--    If this reports 0, STOP. Either you are pointed at the wrong database,
--    or something has gone very wrong elsewhere.
-- ---------------------------------------------------------------------
SELECT count(*) AS terms_consent_rows_must_be_nonzero
  FROM pettycashv2.terms_consent;


-- ---------------------------------------------------------------------
-- 3. THE DROPS
--
--    Child first: consent_event -> consent_record -> the two parents.
--    Dropping a parent first fails on the foreign keys, and CASCADE would
--    silently take anything else attached with it.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS pettycashv2.consent_event;
DROP TABLE IF EXISTS pettycashv2.consent_record;
DROP TABLE IF EXISTS pettycashv2.terms_user_principal;
DROP TABLE IF EXISTS pettycashv2.terms_version;


-- ---------------------------------------------------------------------
-- 4. VERIFY — read this before deciding to COMMIT.
-- ---------------------------------------------------------------------

-- Expect exactly two rows: terms_consent and entity_billing_consent.
SELECT table_name
  FROM information_schema.tables
 WHERE table_schema = 'pettycashv2'
   AND (table_name ILIKE '%term%' OR table_name ILIKE '%consent%')
 ORDER BY table_name;

-- The live table, untouched.
SELECT count(*) AS terms_consent_rows FROM pettycashv2.terms_consent;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN
--
--   The four tables can be recreated exactly as they were — see
--   downgrade() in migrations/versions/k1a01_drop_abandoned_consent_tables.py,
--   reconstructed from the original migration in git history:
--
--     git show 4baa65ef^:migrations/versions/093b4bd031f1_create_consent_terms_tables.py
--
--   That restores the structure. There was never any data to restore.
-- ---------------------------------------------------------------------
