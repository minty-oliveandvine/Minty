-- =====================================================================
--  ENTITY 1 — add entities.last_accessed_at / last_accessed_by_user_id
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision e1a01_entity_last_accessed.
--  Run the .sql OR the .py — never both. (The guards make a double-run
--  harmless, but alembic_version would not record the SQL path.)
--
--  *** ENDS IN ROLLBACK. *** Run once as-is to read the output, then change
--  the last line to COMMIT.
--
--  ------------------------------------------------------------------
--  WHAT AND WHY
--
--  Two nullable columns on the existing entities table:
--
--    last_accessed_at          when this entity was last opened
--    last_accessed_by_user_id  which user opened it
--
--  These drive the "last logged in" clock on the Select Company card —
--  team-wide, so it answers "who last touched this company", not "when did
--  I last visit". That is why it lives on entities and not on user_entity:
--  a superuser can open an entity with no user_entity row at all, and that
--  visit still counts.
--
--  ------------------------------------------------------------------
--  SAFE TO RUN ON LIVE AT ANY TIME
--
--  Purely additive:
--
--    * ADD COLUMN ... NULL takes no table rewrite in PostgreSQL 11+, so
--      there is no long lock and no blocked traffic even on a large table;
--    * old code ignores columns it has never heard of;
--    * nothing reads them until the entity-list changes ship.
--
--  Schema first, code after. The ordinary direction for an addition.
--
--  ------------------------------------------------------------------
--  NO BACKFILL, DELIBERATELY
--
--  Both columns stay NULL until each entity's next open. There is nothing
--  to backfill FROM — no table recorded entity opens before this. The card
--  renders a greyed-out clock for the NULL state, which is honest: we do
--  not know when it was last opened, so we do not claim to.
--
--  Do not be tempted to seed these from created_at. "Last opened" and
--  "created" are different facts, and one dressed as the other is worse
--  than a blank.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. PRE-FLIGHT — both tables must exist, and we must not clobber
--    columns that are somehow already there.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'pettycashv2' AND table_name = 'entities'
    ) THEN
        RAISE EXCEPTION 'pettycashv2.entities not found — wrong schema or wrong database?';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'pettycashv2' AND table_name = 'user'
    ) THEN
        RAISE EXCEPTION 'pettycashv2."user" not found — the FK has no parent to point at.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'pettycashv2'
           AND table_name   = 'entities'
           AND column_name  = 'last_accessed_at'
    ) THEN
        RAISE NOTICE 'entities.last_accessed_at already exists — nothing to do.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 2. THE COLUMNS
--
--    Both nullable, no default. NULL means "never opened since this
--    shipped", which the card renders as a greyed clock.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2.entities
    ADD COLUMN IF NOT EXISTS last_accessed_at         TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_accessed_by_user_id VARCHAR(36);


-- ---------------------------------------------------------------------
-- 3. THE FOREIGN KEY
--
--    ON DELETE SET NULL, never CASCADE. Deleting a user must not delete
--    the company they last opened — it just forgets who that was.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint con
          JOIN pg_class cl      ON cl.oid = con.conrelid
          JOIN pg_namespace ns  ON ns.oid = cl.relnamespace
         WHERE ns.nspname = 'pettycashv2'
           AND cl.relname = 'entities'
           AND con.conname = 'fk_entities_last_accessed_by_user_id'
    ) THEN
        ALTER TABLE pettycashv2.entities
            ADD CONSTRAINT fk_entities_last_accessed_by_user_id
            FOREIGN KEY (last_accessed_by_user_id)
            REFERENCES pettycashv2."user" (id)
            ON DELETE SET NULL;
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 4. VERIFY — read these before deciding to COMMIT.
-- ---------------------------------------------------------------------

-- Both columns present, both nullable, no default.
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema = 'pettycashv2'
   AND table_name   = 'entities'
   AND column_name IN ('last_accessed_at', 'last_accessed_by_user_id')
 ORDER BY column_name;

-- The FK exists and is ON DELETE SET NULL (confdeltype = 'n').
SELECT con.conname, con.contype, con.confdeltype
  FROM pg_constraint con
  JOIN pg_class cl     ON cl.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
 WHERE ns.nspname = 'pettycashv2'
   AND cl.relname = 'entities'
   AND con.conname = 'fk_entities_last_accessed_by_user_id';

-- Must be 0 on both counts. Nothing is backfilled.
SELECT count(*) FILTER (WHERE last_accessed_at IS NOT NULL)         AS stamped_at,
       count(*) FILTER (WHERE last_accessed_by_user_id IS NOT NULL) AS stamped_by,
       count(*)                                                     AS total_entities
  FROM pettycashv2.entities;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN
--
--   ALTER TABLE pettycashv2.entities
--       DROP CONSTRAINT IF EXISTS fk_entities_last_accessed_by_user_id;
--   ALTER TABLE pettycashv2.entities
--       DROP COLUMN IF EXISTS last_accessed_by_user_id,
--       DROP COLUMN IF EXISTS last_accessed_at;
--
-- Safe at any time. These columns are a convenience display only — nothing
-- else reads them, and the data they hold is regenerated on the next open.
-- ---------------------------------------------------------------------
