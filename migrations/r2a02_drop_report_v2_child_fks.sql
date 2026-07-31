-- =====================================================================
--  STAGE 2a — drop the FK constraints pinning the report_v2 children
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  *** TARGET SCHEMA: pettycashv2_clone  (NOT the live pettycashv2) ***
--
--  Raw-SQL twin of alembic revision r2a02_drop_v2_fks
--  (migrations/versions/r2a02_drop_report_v2_child_fks.py).
--
--  Ends with ROLLBACK so a first run reports and changes NOTHING.
--  Flip the last line to COMMIT to keep the result on the clone.
--
--  Re-runnable: every DROP uses IF EXISTS.
--  ------------------------------------------------------------------
BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — clone only.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'pettycashv2_clone') THEN
        RAISE EXCEPTION
          'Schema pettycashv2_clone does not exist. See the header of this file.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 1. REPORT what is actually constrained right now, before touching it.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    r record;
    n int := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== FKs referencing report_v2 BEFORE ===';
    FOR r IN
        SELECT con.conname, cl.relname AS child_table
          FROM pg_constraint con
          JOIN pg_class      cl  ON cl.oid = con.conrelid
          JOIN pg_namespace  ns  ON ns.oid = cl.relnamespace
          JOIN pg_class      rcl ON rcl.oid = con.confrelid
         WHERE con.contype = 'f'
           AND ns.nspname  = 'pettycashv2_clone'
           AND rcl.relname = 'report_v2'
         ORDER BY cl.relname
    LOOP
        RAISE NOTICE '  % on %', r.conname, r.child_table;
        n := n + 1;
    END LOOP;
    IF n = 0 THEN
        RAISE NOTICE '  (none — expected if the clone was built with CREATE TABLE AS)';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 2. DROP them. IF EXISTS so this is a no-op when already absent.
-- ---------------------------------------------------------------------
ALTER TABLE IF EXISTS pettycashv2_clone.report_sale_detail
    DROP CONSTRAINT IF EXISTS report_sale_detail_report_id_fkey;

ALTER TABLE IF EXISTS pettycashv2_clone.report_expense_detail
    DROP CONSTRAINT IF EXISTS report_expense_detail_report_id_fkey;

ALTER TABLE IF EXISTS pettycashv2_clone.xero_report_sync
    DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey;

ALTER TABLE IF EXISTS pettycashv2_clone.xero_bank_transfer
    DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey;


-- ---------------------------------------------------------------------
-- 3. ORPHAN ANALYSIS — the real reason to run this on the clone.
--
--    Stage 3 re-points these columns at report.id. That only works if every
--    child row's report_id already exists in `report`. Any row counted as
--    "NOT in report" here is a row Stage 3 would reject.
--
--    Expect NON-ZERO numbers in the draft column: detail rows written during
--    entry, for drafts never submitted, have no report row YET. Stage 4
--    creates those rows. The number that must reach zero before Stage 3 is
--    "in NEITHER" — a child pointing at an id that is neither a report nor
--    a draft is genuinely orphaned and needs investigating.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t            text;
    col          text;
    n_total      bigint;
    n_in_report  bigint;
    n_draft_only bigint;
    n_neither    bigint;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== ORPHAN ANALYSIS (can Stage 3 re-point to report.id?) ===';
    RAISE NOTICE 'table                    total   in report   draft-only   NEITHER';

    FOREACH t IN ARRAY ARRAY['report_sale_detail','report_expense_detail',
                             'xero_report_sync','xero_bank_transfer']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2_clone' AND table_name=t) THEN
            RAISE NOTICE '%-24s (table not on clone — skipped)', t;
            CONTINUE;
        END IF;

        col := CASE WHEN t = 'xero_bank_transfer' THEN 'sync_report_id' ELSE 'report_id' END;

        EXECUTE format($f$
            SELECT count(*),
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pettycashv2_clone.report      r WHERE r.id = c.%I)),
                   count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report  r WHERE r.id = c.%I)
                                      AND EXISTS (SELECT 1 FROM pettycashv2_clone.report_draft d WHERE d.id = c.%I)),
                   count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report      r WHERE r.id = c.%I)
                                      AND NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report_draft d WHERE d.id = c.%I))
              FROM pettycashv2_clone.%I c
             WHERE c.%I IS NOT NULL
        $f$, col, col, col, col, col, t, col)
        INTO n_total, n_in_report, n_draft_only, n_neither;

        RAISE NOTICE '%-24s % % % %',
            t,
            lpad(n_total::text, 5),
            lpad(n_in_report::text, 9),
            lpad(n_draft_only::text, 11),
            lpad(n_neither::text, 9);

        IF n_neither > 0 THEN
            RAISE WARNING '  ^ % row(s) in % point at an id that is NEITHER a report NOR a draft. Investigate before Stage 3.', n_neither, t;
        END IF;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE 'draft-only rows are EXPECTED (unsubmitted drafts have no report row yet).';
    RAISE NOTICE 'Stage 4 creates report rows for them; Stage 3 then adds the FK back.';
    RAISE NOTICE 'Only the NEITHER column must be zero before Stage 3.';
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 4. Confirm the constraints are gone.
-- ---------------------------------------------------------------------
DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n
      FROM pg_constraint con
      JOIN pg_class      cl  ON cl.oid = con.conrelid
      JOIN pg_namespace  ns  ON ns.oid = cl.relnamespace
      JOIN pg_class      rcl ON rcl.oid = con.confrelid
     WHERE con.contype='f' AND ns.nspname='pettycashv2_clone' AND rcl.relname='report_v2';

    RAISE NOTICE '=== FKs referencing report_v2 AFTER: %  (expect 0) ===', n;
    IF n > 0 THEN
        RAISE WARNING 'Still % FK(s) on report_v2 — it cannot be dropped in Stage 5 until they are gone.', n;
    END IF;
END $$;


-- =====================================================================
--  ROLLBACK = dry run. Change to COMMIT to keep the result on the clone.
-- =====================================================================
ROLLBACK;

-- ---------------------------------------------------------------------
-- DOWN (if you committed and want the constraints back):
--
--   ALTER TABLE pettycashv2_clone.report_sale_detail
--       ADD CONSTRAINT report_sale_detail_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report_v2(report_id)
--       ON DELETE CASCADE;
--
--   ALTER TABLE pettycashv2_clone.report_expense_detail
--       ADD CONSTRAINT report_expense_detail_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report_v2(report_id)
--       ON DELETE CASCADE;
--
--   ALTER TABLE pettycashv2_clone.xero_report_sync
--       ADD CONSTRAINT xero_report_sync_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report_v2(report_id)
--       ON DELETE CASCADE;
--
--   ALTER TABLE pettycashv2_clone.xero_bank_transfer
--       ADD CONSTRAINT xero_bank_transfer_sync_report_id_fkey
--       FOREIGN KEY (sync_report_id) REFERENCES pettycashv2_clone.report_v2(report_id)
--       ON DELETE CASCADE;
--
-- These will FAIL if orphaned rows accumulated while unconstrained. That is
-- correct behaviour, not a bug — such rows are exactly what the constraint
-- forbids, and they need looking at rather than being silently re-admitted.
-- ---------------------------------------------------------------------
