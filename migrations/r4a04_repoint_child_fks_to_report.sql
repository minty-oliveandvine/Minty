-- =====================================================================
--  STAGE 3 — re-point the detail/xero FKs from report_v2 to report
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  *** TARGET SCHEMA: pettycashv2_clone  (NOT the live pettycashv2) ***
--
--  Raw-SQL twin of alembic revision r4a04_repoint_fks
--  (migrations/versions/r4a04_repoint_child_fks_to_report.py).
--
--  Ends with ROLLBACK so a first run VALIDATES and changes NOTHING.
--  Flip the last line to COMMIT to keep the constraints on the clone.
--
--  PREREQUISITE: r1a01, r2a02 and r3a03 applied — INCLUDING r3a03's
--  section-5 one-off backfill. Without that backfill this script will
--  correctly refuse to run.
--
--  ------------------------------------------------------------------
--  WHAT IT DOES
--
--    report_sale_detail.report_id      -> report.id   ON DELETE CASCADE
--    report_expense_detail.report_id   -> report.id   ON DELETE CASCADE
--    xero_report_sync.report_id        -> report.id   ON DELETE CASCADE
--    xero_bank_transfer.sync_report_id -> report.id   ON DELETE CASCADE
--
--  After this, report_v2 is referenced by NOTHING and Stage 5 can drop it.
--
--  ------------------------------------------------------------------
--  WHY THIS COULD NOT RUN UNTIL NOW
--
--  The values never changed. report_v2.report_id was always the draft id,
--  which is always the report id (sales.py:747-750, ending.py:1418-1419).
--  What was missing was the PARENT ROW: a draft only got a `report` row at
--  submit, so every in-progress draft's detail rows pointed at an id absent
--  from `report`, and this constraint would have been rejected for all of them.
--
--  Stage 4a closed that from three directions:
--    * r3a03 relaxed report.expenses / closing_balance to nullable, so a
--      draft-shaped report row is insertable at all;
--    * ensure_report_row_for_draft() creates the paired row at draft creation,
--      so no NEW gap appears;
--    * r3a03's section-5 backfill closed the gap for existing rows.
--
--  ------------------------------------------------------------------
--  THIS SCRIPT IS A GUARD, NOT A DATA CHANGE
--
--  Nothing is read, written or moved. If it succeeds, every child row already
--  pointed at a real report. If it FAILS, that is the useful outcome — orphans
--  exist and step 1 names them per table before anything is attempted.
--
--  ------------------------------------------------------------------
--  ON DELETE — a note, not a silent decision
--
--  The two detail tables get CASCADE, matching what a7b8c9d0e1f2 gave them
--  against report_v2: those rows are components of a report and mean nothing
--  without it.
--
--  The two xero tables are an AUDIT TRAIL of what was pushed to Xero, and
--  arguably should survive a local report delete — that record is how a
--  double-publish is detected. They keep CASCADE here only because
--  report_id / sync_report_id are part of a composite PRIMARY KEY today and a
--  PK column cannot be SET NULL. Stage 5 reshapes those PKs; the retention
--  question belongs there. Flagging rather than deciding quietly.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — clone only.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'pettycashv2_clone') THEN
        RAISE EXCEPTION 'Schema pettycashv2_clone does not exist.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema='pettycashv2_clone' AND table_name='report') THEN
        RAISE EXCEPTION 'pettycashv2_clone.report is missing.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 1. PRE-FLIGHT — count orphans per table BEFORE attempting any ALTER.
--
--    Postgres would reject on the first offending table and stop; this
--    reports every one, so a single run tells you the whole story.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t          text;
    col        text;
    n          bigint;
    n_total    bigint := 0;
    bad        text := '';
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== PRE-FLIGHT: rows pointing at a non-existent report ===';

    FOREACH t IN ARRAY ARRAY['report_sale_detail','report_expense_detail',
                             'xero_report_sync','xero_bank_transfer']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema='pettycashv2_clone' AND table_name=t) THEN
            RAISE NOTICE '  %-24s (not on clone — skipped)', t;
            CONTINUE;
        END IF;

        col := CASE WHEN t='xero_bank_transfer' THEN 'sync_report_id' ELSE 'report_id' END;

        EXECUTE format($f$
            SELECT count(*) FROM pettycashv2_clone.%I c
             WHERE c.%I IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = c.%I)
        $f$, t, col, col) INTO n;

        RAISE NOTICE '  %-24s orphans = %', t, n;
        n_total := n_total + n;
        IF n > 0 THEN
            bad := bad || format('%s=%s ', t, n);
        END IF;
    END LOOP;

    RAISE NOTICE '';
    IF n_total > 0 THEN
        RAISE EXCEPTION
          'ABORT: % orphaned row(s) (%). These point at an id with no `report` row. Apply r3a03 section-5 backfill first, then re-run.',
          n_total, trim(bad);
    END IF;
    RAISE NOTICE 'PRE-FLIGHT CLEAN — every child row has a real report parent.';
    RAISE NOTICE '';
END $$;


-- ---------------------------------------------------------------------
-- 2. Drop any leftover constraint by these names, so the script is
--    re-runnable and cannot collide with a partially-applied attempt.
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
-- 3. CREATE them against report.id.
--
--    Each ALTER validates every existing row. Step 1 already proved they
--    pass, so these are assertions rather than gambles.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2_clone.report_sale_detail
    ADD CONSTRAINT report_sale_detail_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report(id)
    ON DELETE CASCADE;

ALTER TABLE pettycashv2_clone.report_expense_detail
    ADD CONSTRAINT report_expense_detail_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report(id)
    ON DELETE CASCADE;

ALTER TABLE pettycashv2_clone.xero_report_sync
    ADD CONSTRAINT xero_report_sync_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2_clone.report(id)
    ON DELETE CASCADE;

ALTER TABLE pettycashv2_clone.xero_bank_transfer
    ADD CONSTRAINT xero_bank_transfer_sync_report_id_fkey
    FOREIGN KEY (sync_report_id) REFERENCES pettycashv2_clone.report(id)
    ON DELETE CASCADE;


-- ---------------------------------------------------------------------
-- 4. CONFIRM — what each constraint now points at, and that report_v2 is
--    finally referenced by nothing.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    r        record;
    n_report int := 0;
    n_v2     int := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '=== FKs AFTER ===';
    FOR r IN
        SELECT cl.relname AS child, con.conname, rcl.relname AS parent
          FROM pg_constraint con
          JOIN pg_class      cl  ON cl.oid  = con.conrelid
          JOIN pg_namespace  ns  ON ns.oid  = cl.relnamespace
          JOIN pg_class      rcl ON rcl.oid = con.confrelid
         WHERE con.contype='f'
           AND ns.nspname='pettycashv2_clone'
           AND rcl.relname IN ('report','report_v2')
         ORDER BY rcl.relname, cl.relname
    LOOP
        RAISE NOTICE '  %-24s -> %', r.child, r.parent;
        IF r.parent = 'report'    THEN n_report := n_report + 1; END IF;
        IF r.parent = 'report_v2' THEN n_v2     := n_v2 + 1;     END IF;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE 'FKs -> report    : %', n_report;
    RAISE NOTICE 'FKs -> report_v2 : %  (must be 0 before Stage 5 drops it)', n_v2;
    RAISE NOTICE '';
    IF n_v2 > 0 THEN
        RAISE WARNING 'report_v2 is still referenced by % constraint(s).', n_v2;
    ELSE
        RAISE NOTICE 'report_v2 is now referenced by nothing — Stage 5 can drop it.';
    END IF;
    RAISE NOTICE '';
END $$;


-- =====================================================================
--  ROLLBACK = validate only. Change to COMMIT to keep the constraints.
-- =====================================================================
ROLLBACK;

-- ---------------------------------------------------------------------
-- DOWN (if you committed and want the columns unconstrained again —
-- i.e. back to the r2a02 state):
--
--   ALTER TABLE pettycashv2_clone.report_sale_detail
--       DROP CONSTRAINT IF EXISTS report_sale_detail_report_id_fkey;
--   ALTER TABLE pettycashv2_clone.report_expense_detail
--       DROP CONSTRAINT IF EXISTS report_expense_detail_report_id_fkey;
--   ALTER TABLE pettycashv2_clone.xero_report_sync
--       DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey;
--   ALTER TABLE pettycashv2_clone.xero_bank_transfer
--       DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey;
--
-- This does NOT restore the report_v2 FKs. Going back that far means
-- reinstating the seven ReportV2 write sites as well — a code rollback,
-- not a schema one.
-- ---------------------------------------------------------------------
