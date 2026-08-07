-- =====================================================================
--  TERMS 1 — create terms_consent
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision t1a01_terms_consent.
--  Run the .sql OR the .py — never both. (The guards make a double-run
--  harmless, but alembic_version would not record the SQL path.)
--
--  *** ENDS IN ROLLBACK. *** Run once as-is to read the output, then change
--  the last line to COMMIT.
--
--  ------------------------------------------------------------------
--  WHAT AND WHY
--
--  One new table, holding one row per (person, version of the Terms):
--
--    terms_consent   who agreed, to which version, when, and to exactly
--                    what wording (document_hash)
--
--  Nothing existing is touched. No column is added to another table, no
--  constraint is changed, no data is moved.
--
--  ------------------------------------------------------------------
--  SAFE TO RUN ON LIVE AT ANY TIME
--
--  Purely additive, so the code-first/schema-first rule that governs the
--  report consolidation does not apply:
--
--    * old code ignores a table it has never heard of;
--    * nothing reads this table until the accept screen and the gate ship;
--    * CREATE TABLE locks nothing that already exists — no blocked traffic,
--      no rewrite of a large table.
--
--  Schema first, code after. The ordinary direction for an addition.
--
--  ------------------------------------------------------------------
--  NO BACKFILL, DELIBERATELY
--
--  This script inserts no rows and no later one should. Existing users have
--  not agreed to anything, and inventing records for them would defeat the
--  purpose of having any — a fabricated record is worse than an absent one,
--  because it looks genuine. They are asked at their next login.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. PRE-FLIGHT — the parent table must exist, and we must not clobber
--    an existing terms_consent.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'pettycashv2' AND table_name = 'user'
    ) THEN
        RAISE EXCEPTION 'pettycashv2."user" not found — wrong schema or wrong database?';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'pettycashv2' AND table_name = 'terms_consent'
    ) THEN
        RAISE NOTICE 'pettycashv2.terms_consent already exists — nothing to do.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 2. THE TABLE
--
--    document_hash is NOT NULL on purpose: a consent row that does not pin
--    the wording it agreed to is unverifiable, which is the one thing this
--    table exists to prevent.
--
--    accepted_at is TIMESTAMPTZ, not TIMESTAMP. A naive timestamp is
--    ambiguous the moment anyone asks "when, exactly?".
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.terms_consent (
    id            VARCHAR(36)  PRIMARY KEY,
    user_id       VARCHAR(36)  NOT NULL,
    terms_version VARCHAR(32)  NOT NULL,
    document_hash VARCHAR(64)  NOT NULL,
    accepted_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    source        VARCHAR(32)  NOT NULL,
    ip_address    VARCHAR(45),
    user_agent    VARCHAR(512),
    CONSTRAINT fk_terms_consent_user
        FOREIGN KEY (user_id)
        REFERENCES pettycashv2."user"(id)
        -- Section 13 of the Terms allows permanent deletion of a user.
        -- Consent records about a deleted person are data we would have no
        -- reason to hold, so they go with them.
        ON DELETE CASCADE,
    -- One record per person per version, so a double-click or two open tabs
    -- collapse to a single row. The application treats the resulting
    -- violation as success.
    CONSTRAINT uq_terms_consent_user_version UNIQUE (user_id, terms_version)
);

CREATE INDEX IF NOT EXISTS ix_terms_consent_user
    ON pettycashv2.terms_consent (user_id);


-- ---------------------------------------------------------------------
-- 3. VERIFY — shape, constraints, and that it is empty.
-- ---------------------------------------------------------------------
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'pettycashv2' AND table_name = 'terms_consent'
 ORDER BY ordinal_position;

SELECT con.conname, con.contype
  FROM pg_constraint con
  JOIN pg_class cl ON cl.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
 WHERE ns.nspname = 'pettycashv2' AND cl.relname = 'terms_consent'
 ORDER BY con.contype, con.conname;

-- Must be 0. This table is never backfilled.
SELECT count(*) AS rows_present FROM pettycashv2.terms_consent;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN
--
--   DROP INDEX  IF EXISTS pettycashv2.ix_terms_consent_user;
--   DROP TABLE  IF EXISTS pettycashv2.terms_consent;
--
-- Safe while the table is empty. NOT safe afterwards: it destroys the
-- consent records, and a consent record cannot be reconstructed after the
-- fact. Take a backup first once real agreements exist.
-- ---------------------------------------------------------------------
