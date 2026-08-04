-- =====================================================================
-- STEP 4c — drop the legacy report tables. IRREVERSIBLE.
--
-- Supabase twin of migrations/versions/r10a10_drop_legacy_report_tables.py
-- Run the .sql OR the .py — never both.
--
-- ⚠️⚠️  TAKE A BACKUP FIRST. Nothing below can be undone without one.
--
--       pg_dump -n pettycashv2 -Fc -f pre_r10a10.dump <db>
--
-- The .py downgrade() recreates these tables EMPTY. It does not restore one
-- row and it cannot. The real rollback for this migration is: restore the
-- backup.
--
-- ⚠️  DEPLOY THE STEP 4a/4b CODE FIRST, AND LET IT SOAK.
--     Removing a table the code still reads does not fail at deploy — it
--     fails at the first request that touches it, from the middle of a route.
--     Code first, then schema. This is the opposite of Step 1.
-- =====================================================================

BEGIN;

-- =====================================================================
-- PRE-FLIGHT. Read every result before continuing. Any surprise = STOP.
-- =====================================================================

-- ---- P1: no report loses actual_cash_total (r7a07 must have run) -----
-- Expect 0. This value seeds the NEXT report's opening balance; losing it
-- fails silently as a wrong number, not an error.
SELECT count(*) AS p1_reports_losing_actual_cash_total
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;


-- ---- P2: no cash count exists ONLY as wide columns -------------------
-- Expect 0.
--
-- NOTE the "> 0" on the column total. save_cash_count_details stores NO row
-- for a denomination counted as zero, so an all-zero cash count legitimately
-- has no report_cash_count rows while its wide columns are 0 rather than
-- NULL. The naive "IS NOT NULL" form reports those as data loss; they are
-- not. Only a NON-ZERO total is a real gap. (Verified 3 Aug 2026: the naive
-- form returned 5 false positives, this form returned none.)
SELECT count(*) AS p2_wide_column_only_nonzero
  FROM pettycashv2.report_cashcount_draft c
 WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report_cash_count rc
                    WHERE rc.report_id = c.report_id)
   AND (COALESCE(c.thousand_note,0)*1000 + COALESCE(c.fivehundred_note,0)*500
      + COALESCE(c.onehundred_note,0)*100 + COALESCE(c.fifty_note,0)*50
      + COALESCE(c.twenty_note,0)*20  + COALESCE(c.ten_note,0)*10
      + COALESCE(c.five_coin,0)*5     + COALESCE(c.two_coin,0)*2
      + COALESCE(c.one_coin,0)*1) > 0;


-- ---- P3: no surviving table references any table being dropped -------
-- Expect NO ROWS. This is the check that caught report_cash_detail and
-- report_history_v2 on 3 Aug 2026 (see PART 0 below).
SELECT cl.relname AS child, con.conname, rcl.relname AS parent
  FROM pg_constraint con
  JOIN pg_class cl      ON cl.oid  = con.conrelid
  JOIN pg_namespace ns  ON ns.oid  = cl.relnamespace
  JOIN pg_class rcl     ON rcl.oid = con.confrelid
 WHERE con.contype = 'f'
   AND ns.nspname = 'pettycashv2'
   AND rcl.relname IN ('report_draft','shop_expense_draft',
                       'report_cashcount_draft','report_history_draft',
                       'report_detail','report_expense_detail','report_v2')
   AND cl.relname NOT IN ('report_draft','shop_expense_draft',
                          'report_cashcount_draft','report_history_draft',
                          'report_detail','report_expense_detail','report_v2',
                          'report_cash_detail','report_history_v2');


-- ---- P4: no view or matview depends on them --------------------------
-- Expect NO ROWS. This is where a Supabase view over report_detail would
-- show up — the open question from the Step 3.5 notes.
SELECT DISTINCT dependent.relname AS view_name,
       CASE dependent.relkind WHEN 'm' THEN 'materialized' ELSE 'view' END AS kind
  FROM pg_depend d
  JOIN pg_rewrite rw      ON rw.oid = d.objid
  JOIN pg_class dependent ON dependent.oid = rw.ev_class
  JOIN pg_class source    ON source.oid = d.refobjid
  JOIN pg_namespace ns    ON ns.oid = source.relnamespace
 WHERE ns.nspname = 'pettycashv2'
   AND source.relname IN ('report_draft','shop_expense_draft',
                          'report_cashcount_draft','report_history_draft',
                          'report_detail','report_expense_detail','report_v2')
   AND dependent.relkind IN ('v','m');


-- ---- P5: sequences borrowed by a table in ANOTHER schema --------------
-- Expect NO ROWS.
--
-- P3 only covers foreign keys, which is not the only way something can depend
-- on a table. A schema copied with CREATE TABLE (LIKE ...) keeps its columns
-- pointing at the ORIGINAL sequences, so DROP TABLE fails part-way through
-- with DependentObjectsStillExist.
--
-- Hit on prestaging 4 Aug 2026: pettycashv2_clone.report_history_draft
-- borrowed pettycashv2.report_history_draft_id_seq.
--
-- FIX: detach the borrower, do NOT use CASCADE (that drops the sequence out
-- from under it and silently breaks the copy):
--     ALTER TABLE <borrower> ALTER COLUMN <col> DROP DEFAULT;
SELECT cn.nspname||'.'||c.relname AS borrower, s.relname AS borrowed_sequence
  FROM pg_depend d
  JOIN pg_class s      ON s.oid = d.refobjid AND s.relkind='S'
  JOIN pg_namespace sn ON sn.oid = s.relnamespace AND sn.nspname='pettycashv2'
  JOIN pg_attrdef ad   ON ad.oid = d.objid
  JOIN pg_class c      ON c.oid = ad.adrelid
  JOIN pg_namespace cn ON cn.oid = c.relnamespace AND cn.nspname <> 'pettycashv2'
 WHERE EXISTS (
   SELECT 1 FROM unnest(ARRAY['report_draft','shop_expense_draft',
                              'report_cashcount_draft','report_history_draft',
                              'report_detail','report_expense_detail','report_v2']) t
    WHERE s.relname LIKE t||'%');


-- ---- Row counts, for the record --------------------------------------
SELECT 'report_history_draft' t, count(*) FROM pettycashv2.report_history_draft
UNION ALL SELECT 'shop_expense_draft',     count(*) FROM pettycashv2.shop_expense_draft
UNION ALL SELECT 'report_cashcount_draft', count(*) FROM pettycashv2.report_cashcount_draft
UNION ALL SELECT 'report_expense_detail',  count(*) FROM pettycashv2.report_expense_detail
UNION ALL SELECT 'report_detail',          count(*) FROM pettycashv2.report_detail
UNION ALL SELECT 'report_draft',           count(*) FROM pettycashv2.report_draft
UNION ALL SELECT 'report_v2',              count(*) FROM pettycashv2.report_v2;


-- =====================================================================
-- PART 0 — two orphan report_v2 children
--
-- r0's PART 2 header states that report_cash_detail and report_history_v2
-- "were dead and were removed in Stage 0". They were NOT: both were still
-- present with live FKs to report_v2 on 3 Aug 2026, and P3 blocked the drop.
--
-- Both are unmapped by the application — no model, no query, no reference
-- outside migration files — and existed only as report_v2 children.
--
-- ⚠️ CHECK THESE ARE EMPTY FIRST. If either has rows, something writes it
--    after all: STOP and investigate rather than dropping.
-- =====================================================================
SELECT 'report_cash_detail' t, count(*) FROM pettycashv2.report_cash_detail
UNION ALL
SELECT 'report_history_v2',   count(*) FROM pettycashv2.report_history_v2;

DROP TABLE IF EXISTS pettycashv2.report_cash_detail;
DROP TABLE IF EXISTS pettycashv2.report_history_v2;


-- =====================================================================
-- THE DROPS — children before parents.
--
-- Bare DROP TABLE, never CASCADE. If a drop fails on a dependency, that
-- dependency is something the pre-flight missed and you want to know about
-- it, not have it silently removed along with the table.
-- =====================================================================
DROP TABLE pettycashv2.report_history_draft;
DROP TABLE pettycashv2.shop_expense_draft;
DROP TABLE pettycashv2.report_cashcount_draft;   -- P1/P2 must have passed
DROP TABLE pettycashv2.report_expense_detail;
DROP TABLE pettycashv2.report_detail;
DROP TABLE pettycashv2.report_draft;
DROP TABLE pettycashv2.report_v2;


-- ---------------------------------------------------------------------
-- VERIFY — must return NO ROWS
-- ---------------------------------------------------------------------
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'pettycashv2'
   AND table_name IN ('report_draft','shop_expense_draft',
                      'report_cashcount_draft','report_history_draft',
                      'report_detail','report_expense_detail','report_v2',
                      'report_cash_detail','report_history_v2');


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
--
--  Once you commit this, the only way back is the backup you took.
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — none that is worth writing here.
--
-- The .py downgrade() recreates the seven tables EMPTY so `alembic downgrade`
-- does not error. It restores no data. If you need the rows back, restore the
-- backup — which is why the banner at the top of this file exists.
-- ---------------------------------------------------------------------
