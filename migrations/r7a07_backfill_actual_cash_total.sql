-- =====================================================================
-- STEP 3.5 (Unit 0b) — backfill report.actual_cash_total
--
-- Supabase twin of migrations/versions/r7a07_backfill_actual_cash_total.py
-- Run the .sql OR the .py — never both. (The guards make a double-run
-- harmless, but alembic_version would not record the SQL path.)
--
-- WHY: report.actual_cash_total was added by r1a01 and read in preference by
-- opening.py, but NOTHING EVER WROTE IT. Every assignment in the app targeted
-- report_cashcount_draft, and the draft->report mirror excluded this column by
-- design. So the preferred read always found NULL and fell through.
--
-- It seeds the NEXT report's opening balance when the previous report has no
-- closing_balance. Step 3.5 removes the draft-table writes and Step 4 drops
-- the table, so without this the value silently becomes 0.
--
-- Ship this BEFORE the Unit 0a code. It is additive; old code ignores it.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- BEFORE — how many report rows are missing the value.
-- Record this number. It is the same query as PREFLIGHT P4.
-- ---------------------------------------------------------------------
SELECT count(*) AS rows_missing_before
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;


-- ---------------------------------------------------------------------
-- THE BACKFILL
--
-- GUARD: `r.actual_cash_total IS NULL` — fill only, never overwrite. This
-- makes the statement idempotent and means it can never replace a value the
-- Unit 0a code has written with an older one from the draft table.
-- ---------------------------------------------------------------------
UPDATE pettycashv2.report r
   SET actual_cash_total = c.actual_cash_total
  FROM pettycashv2.report_cashcount_draft c
 WHERE c.report_id = r.id
   AND c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;


-- ---------------------------------------------------------------------
-- AFTER — must be 0.
-- ---------------------------------------------------------------------
SELECT count(*) AS rows_missing_after
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;


-- ---------------------------------------------------------------------
-- Sanity: no value should have CHANGED, only filled. This must return 0.
-- (A non-zero result means the guard above was edited out.)
-- ---------------------------------------------------------------------
SELECT count(*) AS values_disagreeing
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NOT NULL
   AND r.actual_cash_total <> c.actual_cash_total;
-- NOTE: a non-zero count here is NOT necessarily a fault after Unit 0a has
-- been running — the app writes `report` on every cash-count save, so a report
-- edited since the draft row was last touched will legitimately differ. Before
-- Unit 0a ships it should be 0.


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — none, by design.
--
-- Nulling report.actual_cash_total would destroy values the application has
-- written since Unit 0a shipped, and nothing distinguishes those from the ones
-- copied here. Undoing a fill-only backfill is not worth losing live data.
--
-- If you genuinely need the column gone, that is r1a01's downgrade.
-- ---------------------------------------------------------------------
