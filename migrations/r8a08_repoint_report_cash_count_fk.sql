-- =====================================================================
-- STEP 3.5 (Unit 0e) — re-point report_cash_count.report_id at report.id
--
-- Supabase twin of migrations/versions/r8a08_repoint_report_cash_count_fk.py
-- Run the .sql OR the .py — never both. (The guards make a double-run
-- harmless, but alembic_version would not record the SQL path.)
--
-- ⚠️ THIS FIXES A LIVE BUG. Not housekeeping.
--
-- r6a06 re-pointed the three draft children it knew about. report_cash_count
-- — the NEW source-of-truth table for denominations — was not on that list and
-- still references report_draft.
--
-- Step 2 stopped creating report_draft rows. So for any report created from
-- 31 Jul 2026 onward there is no draft row, and inserting its cash count
-- fails:
--
--   insert or update on table "report_cash_count" violates foreign key
--   constraint "report_cash_count_report_id_fkey"
--
-- i.e. SAVING A CASH COUNT ON A NEW REPORT IS BROKEN until this runs. It has
-- not surfaced only because no report had been created since the Step 2
-- deploy — every existing report still has its pre-flip draft twin.
--
-- Deploy order: SCHEMA FIRST. This widens what is accepted (report.id is a
-- superset of report_draft.id now that drafts have stopped being created), so
-- the currently-deployed code keeps working against it.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- PRE-FLIGHT — every value must already resolve against report(id), or the
-- re-add fails after the drop and the table is left with NO constraint.
--
-- Expected: 0. A draft and its report share one id, so these values are
-- already correct; only the constraint's target changes.
-- ---------------------------------------------------------------------
SELECT count(*) AS orphans_against_report
  FROM pettycashv2.report_cash_count c
 WHERE c.report_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = c.report_id);
-- ⚠️ If this is not 0, STOP. Do not continue — investigate first.


-- ---------------------------------------------------------------------
-- Show what the constraint points at today (expect: report_draft)
-- ---------------------------------------------------------------------
SELECT con.conname, rcl.relname AS current_parent
  FROM pg_constraint con
  JOIN pg_class cl      ON cl.oid  = con.conrelid
  JOIN pg_namespace ns  ON ns.oid  = cl.relnamespace
  JOIN pg_class rcl     ON rcl.oid = con.confrelid
 WHERE con.contype = 'f'
   AND ns.nspname  = 'pettycashv2'
   AND cl.relname  = 'report_cash_count';


-- ---------------------------------------------------------------------
-- THE RE-POINT
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2.report_cash_count
    DROP CONSTRAINT IF EXISTS report_cash_count_report_id_fkey;

ALTER TABLE pettycashv2.report_cash_count
    ADD CONSTRAINT report_cash_count_report_id_report_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id)
    ON DELETE CASCADE;


-- ---------------------------------------------------------------------
-- VERIFY — must now say `report`
-- ---------------------------------------------------------------------
SELECT con.conname, rcl.relname AS new_parent,
       CASE con.confdeltype WHEN 'c' THEN 'CASCADE' ELSE con.confdeltype::text END AS on_delete
  FROM pg_constraint con
  JOIN pg_class cl      ON cl.oid  = con.conrelid
  JOIN pg_namespace ns  ON ns.oid  = cl.relnamespace
  JOIN pg_class rcl     ON rcl.oid = con.confrelid
 WHERE con.contype = 'f'
   AND ns.nspname  = 'pettycashv2'
   AND cl.relname  = 'report_cash_count';


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — point it back at report_draft.id. This FAILS if a count row's draft
-- has since been deleted while its report survived, which is correct: such a
-- row is exactly what the old constraint forbade. It also fails outright once
-- r10a10 has dropped report_draft.
--
--   ALTER TABLE pettycashv2.report_cash_count
--       DROP CONSTRAINT IF EXISTS report_cash_count_report_id_report_fkey,
--       ADD CONSTRAINT report_cash_count_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2.report_draft(id)
--       ON DELETE CASCADE;
-- ---------------------------------------------------------------------
