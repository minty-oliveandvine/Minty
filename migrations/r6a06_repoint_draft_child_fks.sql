-- =====================================================================
--  STAGE 4b — re-point the report_draft children at report.id
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision r6a06_repoint_draft_fks.
--
--  *** ENDS IN ROLLBACK. *** Run once as-is to read the counts, then change
--  the last line to COMMIT.
--
--  ------------------------------------------------------------------
--  WHAT AND WHY
--
--  Three tables still FK report_draft.id:
--
--    shop_expense_draft.report_draft_id   -> report_draft.id
--    report_cashcount_draft.report_id     -> report_draft.id   (CASCADE)
--    report_history_draft.report_draft_id -> report_draft.id   (CASCADE)
--
--  They are the last thing pinning report_draft, and they are what blocks the
--  write flip: pointing writes at `report` means draft rows stop being
--  created, and the next insert into any of these three violates its FK.
--  That is the s6a06 failure mode — code ceasing to write something the
--  schema still demands.
--
--  ------------------------------------------------------------------
--  THE VALUES ARE ALREADY CORRECT
--
--  A draft and its report share one id, and since Stage 4a the `report` row
--  exists from draft creation, with the r0 PART 3 backfill covering older
--  rows. Every one of these columns already holds a valid report.id — only
--  the constraint target changes. No data is read, written or moved.
--
--  Unlike r2a02 -> r4a04 there is no unconstrained interval: the parent rows
--  already exist, so drop and recreate happen in one transaction.
--
--  ------------------------------------------------------------------
--  CONSTRAINT NAMES ARE DISCOVERED
--
--  These FKs were created inline without explicit names, so Postgres
--  auto-generated them. The DO block below reads pg_constraint and drops
--  whatever actually references report_draft, rather than hardcoding a guess
--  that might silently match nothing.
--
--  ------------------------------------------------------------------
--  DEPLOY ORDER
--
--  Run this BEFORE deploying the write-flip code. Re-pointing the FK is
--  backwards-compatible: the old code keeps writing draft rows and they still
--  satisfy the new constraint, because draft id == report id. The new code
--  needs the constraint already moved.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. PRE-FLIGHT — orphans per table, before touching anything.
--
--    A child row whose id has no `report` row would fail the new constraint.
--    Report every offending table rather than letting Postgres stop at the
--    first one it happens to reach.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t text; col text; n bigint; total bigint := 0; bad text := '';
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== PRE-FLIGHT: rows with no matching `report` ===';
    FOREACH t IN ARRAY ARRAY['shop_expense_draft','report_cashcount_draft',
                             'report_history_draft']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2' AND table_name=t) THEN
            RAISE NOTICE '  %-24s (absent — skipped)', t;
            CONTINUE;
        END IF;
        col := CASE WHEN t='report_cashcount_draft' THEN 'report_id'
                    ELSE 'report_draft_id' END;
        EXECUTE format($f$
            SELECT count(*) FROM pettycashv2.%I c
             WHERE c.%I IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = c.%I)
        $f$, t, col, col) INTO n;
        RAISE NOTICE '  %-24s orphans = %', t, n;
        total := total + n;
        IF n > 0 THEN bad := bad || format('%s=%s ', t, n); END IF;
    END LOOP;

    IF total > 0 THEN
        RAISE EXCEPTION
          'ABORT: % orphaned row(s) (%). Confirm the r0 PART 3 backfill ran. Nothing committed.',
          total, trim(bad);
    END IF;
    RAISE NOTICE '  clean.';
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 2. DROP whatever currently references report_draft, then recreate
--    against report.id. ondelete is preserved per table.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    r        record;
    t        text;
    col      text;
    ondel    text;
    n_dropped int := 0;
BEGIN
    FOREACH t IN ARRAY ARRAY['shop_expense_draft','report_cashcount_draft',
                             'report_history_draft']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2' AND table_name=t) THEN
            CONTINUE;
        END IF;

        col   := CASE WHEN t='report_cashcount_draft' THEN 'report_id'
                      ELSE 'report_draft_id' END;
        -- shop_expense_draft had no ON DELETE; the other two CASCADE.
        ondel := CASE WHEN t='shop_expense_draft' THEN ''
                      ELSE ' ON DELETE CASCADE' END;

        FOR r IN
            SELECT con.conname
              FROM pg_constraint con
              JOIN pg_class      cl  ON cl.oid  = con.conrelid
              JOIN pg_namespace  ns  ON ns.oid  = cl.relnamespace
              JOIN pg_class      rcl ON rcl.oid = con.confrelid
             WHERE con.contype='f' AND ns.nspname='pettycashv2'
               AND cl.relname = t AND rcl.relname = 'report_draft'
        LOOP
            EXECUTE format('ALTER TABLE pettycashv2.%I DROP CONSTRAINT %I',
                           t, r.conname);
            RAISE NOTICE 'dropped %  on %', r.conname, t;
            n_dropped := n_dropped + 1;
        END LOOP;

        -- Skip if this column already points at `report`.
        IF EXISTS (
            SELECT 1 FROM pg_constraint con
              JOIN pg_class cl  ON cl.oid  = con.conrelid
              JOIN pg_namespace ns ON ns.oid = cl.relnamespace
              JOIN pg_class rcl ON rcl.oid = con.confrelid
             WHERE con.contype='f' AND ns.nspname='pettycashv2'
               AND cl.relname = t AND rcl.relname = 'report'
        ) THEN
            RAISE NOTICE '%  already references report — skipped', t;
            CONTINUE;
        END IF;

        EXECUTE format(
            'ALTER TABLE pettycashv2.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (%I) REFERENCES pettycashv2.report(id)%s',
            t, t || '_' || col || '_report_fkey', col, ondel);
        RAISE NOTICE 'created %_%_report_fkey -> report(id)%', t, col, ondel;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE 'dropped % old constraint(s).', n_dropped;
END $$;


-- ---------------------------------------------------------------------
-- 3. CONFIRM
-- ---------------------------------------------------------------------
DO $$
DECLARE r record; n_draft int := 0; n_report int := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== FKs AFTER ===';
    FOR r IN
        SELECT cl.relname AS child, rcl.relname AS parent, con.conname
          FROM pg_constraint con
          JOIN pg_class cl  ON cl.oid  = con.conrelid
          JOIN pg_namespace ns ON ns.oid = cl.relnamespace
          JOIN pg_class rcl ON rcl.oid = con.confrelid
         WHERE con.contype='f' AND ns.nspname='pettycashv2'
           AND rcl.relname IN ('report','report_draft')
           AND cl.relname IN ('shop_expense_draft','report_cashcount_draft',
                              'report_history_draft')
         ORDER BY cl.relname
    LOOP
        RAISE NOTICE '  %-24s -> %', r.child, r.parent;
        IF r.parent='report_draft' THEN n_draft := n_draft + 1;
        ELSE n_report := n_report + 1; END IF;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE '  -> report       : %', n_report;
    RAISE NOTICE '  -> report_draft : %  (must be 0 before the write flip)', n_draft;
    RAISE NOTICE '';
    IF n_draft > 0 THEN
        RAISE WARNING 'report_draft still has % child FK(s).', n_draft;
    ELSE
        RAISE NOTICE '  report_draft has no child FKs left — the write flip is unblocked.';
    END IF;
    RAISE NOTICE '';
    RAISE NOTICE '  Nothing was dropped or moved. All three tables keep their rows.';
    RAISE NOTICE '  >>> Ends in ROLLBACK. Change the last line to COMMIT to apply.';
    RAISE NOTICE '';
END $$;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — point them back at report_draft.id. This FAILS if a child row's
-- draft has since been deleted while its report survived, which is correct:
-- such a row is exactly what the old constraint forbade.
--
--   ALTER TABLE pettycashv2.shop_expense_draft
--       DROP CONSTRAINT IF EXISTS shop_expense_draft_report_draft_id_report_fkey,
--       ADD CONSTRAINT shop_expense_draft_report_draft_id_fkey
--       FOREIGN KEY (report_draft_id) REFERENCES pettycashv2.report_draft(id);
--
--   ALTER TABLE pettycashv2.report_cashcount_draft
--       DROP CONSTRAINT IF EXISTS report_cashcount_draft_report_id_report_fkey,
--       ADD CONSTRAINT report_cashcount_draft_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2.report_draft(id)
--       ON DELETE CASCADE;
--
--   ALTER TABLE pettycashv2.report_history_draft
--       DROP CONSTRAINT IF EXISTS report_history_draft_report_draft_id_report_fkey,
--       ADD CONSTRAINT report_history_draft_report_draft_id_fkey
--       FOREIGN KEY (report_draft_id) REFERENCES pettycashv2.report_draft(id)
--       ON DELETE CASCADE;
-- ---------------------------------------------------------------------
