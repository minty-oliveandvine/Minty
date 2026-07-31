-- =====================================================================
--  STAGE 1 — additive columns on `report` for the table consolidation
--  Copy-paste into the Supabase SQL editor and Run as ONE script.
--
--  *** TARGET SCHEMA: pettycashv2_clone  (NOT the live pettycashv2) ***
--
--  This is the raw-SQL twin of alembic revision r1a01_report_additive
--  (migrations/versions/r1a01_report_consolidation_additive.py), pointed at a
--  clone so you can watch it run and inspect the result before it goes
--  anywhere near production data.
--
--  Wrapped in a single transaction. It ends with ROLLBACK so a first run
--  shows you the counts and changes NOTHING. Flip the last line to COMMIT
--  when you want the clone to keep the result.
--
--  Re-runnable: every ADD COLUMN uses IF NOT EXISTS and every backfill uses
--  COALESCE, so running it twice does not clobber values.
--
--  ------------------------------------------------------------------
--  PREREQUISITE — the clone must exist. If you have not made it yet:
--
--    CREATE SCHEMA pettycashv2_clone;
--    -- then copy the tables you need, e.g. with pg_dump:
--    --   pg_dump -n pettycashv2 --schema-only ... | sed 's/pettycashv2/pettycashv2_clone/g'
--    -- followed by the data, or for a quick structural+data copy of just the
--    -- tables this script touches:
--    CREATE TABLE pettycashv2_clone.report                 AS TABLE pettycashv2.report;
--    CREATE TABLE pettycashv2_clone.report_draft           AS TABLE pettycashv2.report_draft;
--    CREATE TABLE pettycashv2_clone.report_cashcount_draft AS TABLE pettycashv2.report_cashcount_draft;
--    CREATE TABLE pettycashv2_clone.report_detail          AS TABLE pettycashv2.report_detail;
--
--  (CREATE TABLE AS copies columns + rows but NOT constraints or indexes.
--   That is fine here — this script only adds columns and UPDATEs.)
--
--  ------------------------------------------------------------------
--  WHY EVERY COLUMN IS NULLABLE
--
--  s6a06 is the cautionary tale: eleven columns were NOT NULL with no
--  DEFAULT, and the moment the code stopped writing them every INSERT into
--  `report` failed with NotNullViolation. Report submission was down until
--  the constraint was relaxed.
--
--  There is no NOT NULL in this script. `status` takes a temporary
--  server default so rows inserted by not-yet-updated code land in a sane
--  state during the backfill; the default is dropped at the end and the
--  column stays nullable, so an omitted value can never reject a row.
--
--  ------------------------------------------------------------------
--  WHY THE BACKFILL IS A PLAIN JOIN ON id
--
--  These four tables all share ONE identity:
--
--    report.id  ==  report_draft.id             (ending.py:387, :712)
--    report_cashcount_draft.report_id == that id (report_cash_count_draft.py:10)
--    report_detail.report_id          == that id (cash_count.py:391, :436)
--    report_v2.report_id              == that id (sales.py:747-750)
--
--  So this joins on the primary key. Contrast 03_data_reports.sql, which
--  migrates to a different schema and has to recover ids from
--  (entity_id, transaction_date) and dedup by priority. None of that applies
--  here — no dedup, no surrogate-key recovery, no ambiguity.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- GUARD — refuse to run against anything but the clone.
--
-- This script is deliberately scoped to pettycash_clone. If the schema is
-- missing, stop with a clear message instead of erroring 40 lines later.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'pettycashv2_clone') THEN
        RAISE EXCEPTION
          'Schema pettycashv2_clone does not exist. Create it first — see the header of this file.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'pettycashv2_clone' AND table_name = 'report') THEN
        RAISE EXCEPTION
          'pettycashv2_clone.report is missing. Copy the tables listed in the header first.';
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 1. ADD the six columns. All nullable. IF NOT EXISTS makes this a no-op
--    on a second run.
--
--    `status` gets a temporary DEFAULT 'posted' so that any row inserted
--    while the backfill runs is marked as a submitted report — which is
--    what a `report` row with no draft actually is (create.py:148 mints
--    one directly). The default comes off in step 5.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2_clone.report
    ADD COLUMN IF NOT EXISTS status                  varchar(20) DEFAULT 'posted',
    ADD COLUMN IF NOT EXISTS current_section         varchar(20),
    ADD COLUMN IF NOT EXISTS completed_sections      json,
    ADD COLUMN IF NOT EXISTS withdrawal_type         varchar(20),
    ADD COLUMN IF NOT EXISTS withdrawal_bank_account varchar(36),
    ADD COLUMN IF NOT EXISTS actual_cash_total       double precision;


-- ---------------------------------------------------------------------
-- 2. BACKFILL from report_draft, joined on the shared id.
--
--    COALESCE(r.x, d.x) so a re-run never overwrites a value that is
--    already there. Reports with no matching draft keep 'posted' from the
--    column default.
-- ---------------------------------------------------------------------
UPDATE pettycashv2_clone.report AS r
   SET status                  = COALESCE(r.status,                  d.status),
       current_section         = COALESCE(r.current_section,         d.current_section),
       completed_sections      = COALESCE(r.completed_sections,      d.completed_sections),
       withdrawal_type         = COALESCE(r.withdrawal_type,         d.withdrawal_type),
       withdrawal_bank_account = COALESCE(r.withdrawal_bank_account, d.withdrawal_bank_account)
  FROM pettycashv2_clone.report_draft AS d
 WHERE d.id = r.id;


-- ---------------------------------------------------------------------
-- 3. BACKFILL actual_cash_total from report_cashcount_draft.
--
--    This is the one genuinely non-redundant column on that table: the
--    NEXT report's opening balance is seeded from it (create.py:288,
--    opening.py:1044). Every other cashcount_draft column is either a
--    denomination (now in report_cash_count) or already duplicated onto
--    report. Lose this one and the report chain breaks.
-- ---------------------------------------------------------------------
UPDATE pettycashv2_clone.report AS r
   SET actual_cash_total = COALESCE(r.actual_cash_total, c.actual_cash_total)
  FROM pettycashv2_clone.report_cashcount_draft AS c
 WHERE c.report_id = r.id;


-- ---------------------------------------------------------------------
-- 4. report_detail.discrepancy_description -> report.discrepancy_reason,
--    but ONLY where report's own value is empty. `report` is authoritative;
--    report_detail is the duplicate (cash_count.py:397-398, :448).
--
--    report_detail's PK is (report_id, entity_id). A report belongs to one
--    entity so the join cannot fan out, but DISTINCT ON makes that explicit
--    rather than assumed.
-- ---------------------------------------------------------------------
UPDATE pettycashv2_clone.report AS r
   SET discrepancy_reason = d.discrepancy_description
  FROM (
        SELECT DISTINCT ON (report_id) report_id, discrepancy_description
          FROM pettycashv2_clone.report_detail
         WHERE discrepancy_description IS NOT NULL
           AND discrepancy_description <> ''
         ORDER BY report_id, entity_id
       ) AS d
 WHERE d.report_id = r.id
   AND (r.discrepancy_reason IS NULL OR r.discrepancy_reason = '');


-- ---------------------------------------------------------------------
-- 5. DROP the temporary default. Leaving it would silently stamp every
--    future INSERT 'posted'; Stage 4 sets status explicitly. The column
--    remains NULLABLE — that part is not temporary.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2_clone.report
    ALTER COLUMN status DROP DEFAULT;


-- ---------------------------------------------------------------------
-- REPORT — what actually happened. Read these numbers before committing.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    n_report      bigint;
    n_draft_match bigint;
    n_status_d    bigint;
    n_status_p    bigint;
    n_status_null bigint;
    n_section     bigint;
    n_sections    bigint;
    n_wtype       bigint;
    n_wbank       bigint;
    n_acash       bigint;
    n_disc        bigint;
    n_orphan_draft bigint;
BEGIN
    SELECT count(*) INTO n_report FROM pettycashv2_clone.report;

    SELECT count(*) INTO n_draft_match
      FROM pettycashv2_clone.report r
      JOIN pettycashv2_clone.report_draft d ON d.id = r.id;

    SELECT count(*) FILTER (WHERE status = 'draft'),
           count(*) FILTER (WHERE status = 'posted'),
           count(*) FILTER (WHERE status IS NULL),
           count(*) FILTER (WHERE current_section         IS NOT NULL),
           count(*) FILTER (WHERE completed_sections      IS NOT NULL),
           count(*) FILTER (WHERE withdrawal_type         IS NOT NULL),
           count(*) FILTER (WHERE withdrawal_bank_account IS NOT NULL),
           count(*) FILTER (WHERE actual_cash_total       IS NOT NULL),
           count(*) FILTER (WHERE discrepancy_reason IS NOT NULL AND discrepancy_reason <> '')
      INTO n_status_d, n_status_p, n_status_null, n_section, n_sections,
           n_wtype, n_wbank, n_acash, n_disc
      FROM pettycashv2_clone.report;

    -- Drafts with NO matching report row. These are in-progress reports that
    -- were never submitted. Stage 4 has to CREATE report rows for them —
    -- this number is the size of that job.
    SELECT count(*) INTO n_orphan_draft
      FROM pettycashv2_clone.report_draft d
     WHERE NOT EXISTS (SELECT 1 FROM pettycashv2_clone.report r WHERE r.id = d.id);

    RAISE NOTICE '';
    RAISE NOTICE '=== r1a01 STAGE 1 (pettycashv2_clone) ===';
    RAISE NOTICE 'report rows                     : %', n_report;
    RAISE NOTICE '  of which matched a draft      : %', n_draft_match;
    RAISE NOTICE '';
    RAISE NOTICE 'status = draft                  : %', n_status_d;
    RAISE NOTICE 'status = posted                 : %', n_status_p;
    RAISE NOTICE 'status IS NULL  (expect 0)      : %', n_status_null;
    RAISE NOTICE '';
    RAISE NOTICE 'current_section    backfilled   : %', n_section;
    RAISE NOTICE 'completed_sections backfilled   : %', n_sections;
    RAISE NOTICE 'withdrawal_type    backfilled   : %', n_wtype;
    RAISE NOTICE 'withdrawal_bank    backfilled   : %', n_wbank;
    RAISE NOTICE 'actual_cash_total  backfilled   : %', n_acash;
    RAISE NOTICE 'discrepancy_reason non-empty    : %', n_disc;
    RAISE NOTICE '';
    RAISE NOTICE '>> report_draft rows with NO report row : %', n_orphan_draft;
    RAISE NOTICE '   (unsubmitted drafts — Stage 4 must create report rows for these)';
    RAISE NOTICE '';

    IF n_status_null > 0 THEN
        RAISE WARNING 'status IS NULL on % row(s) — expected 0 after the default. Investigate before Stage 4.', n_status_null;
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- Sanity: any report whose status disagrees with its draft's status.
-- Should return ZERO rows. Non-zero means the COALESCE preserved a
-- pre-existing value that conflicts — worth eyeballing before Stage 4.
-- ---------------------------------------------------------------------
SELECT r.id, r.status AS report_status, d.status AS draft_status
  FROM pettycashv2_clone.report r
  JOIN pettycashv2_clone.report_draft d ON d.id = r.id
 WHERE r.status IS DISTINCT FROM d.status
 LIMIT 50;


-- =====================================================================
--  ROLLBACK = dry run. Change to COMMIT to keep the result on the clone.
-- =====================================================================
ROLLBACK;

-- ---------------------------------------------------------------------
-- DOWN (if you committed and want the columns gone again):
--
--   ALTER TABLE pettycashv2_clone.report
--       DROP COLUMN IF EXISTS actual_cash_total,
--       DROP COLUMN IF EXISTS withdrawal_bank_account,
--       DROP COLUMN IF EXISTS withdrawal_type,
--       DROP COLUMN IF EXISTS completed_sections,
--       DROP COLUMN IF EXISTS current_section,
--       DROP COLUMN IF EXISTS status;
--
-- The backfill reads only; every source table is left untouched, so
-- dropping the columns loses nothing that cannot be rebuilt by re-running.
-- ---------------------------------------------------------------------
