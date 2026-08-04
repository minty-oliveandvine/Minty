-- =====================================================================
-- STEP 4d — reshape the Xero audit-trail PKs
--
-- Supabase twin of migrations/versions/r9a09_reshape_xero_audit_pks.py
-- Run the .sql OR the .py — never both.
--
-- WHY: xero_report_sync and xero_bank_transfer are the record of what was
-- pushed to Xero — the thing that detects a double-publish. Publishing stores
-- no Xero object IDs, so a second publish re-POSTs everything and duplicates
-- it in the customer's ledger.
--
-- Today, deleting a local report ERASES that record. Both tables carry their
-- report FK inside a COMPOSITE PRIMARY KEY, and r4a04 gave those FKs
-- ON DELETE CASCADE only because a PK column cannot be SET NULL — the cascade
-- was forced by the key shape, not chosen for its behaviour.
--
-- This changes the shape so the intended behaviour is available:
--     drop the composite PK  ->  id becomes the sole PK
--     make the FK column nullable
--     ON DELETE SET NULL
--
-- NO DATA MOVEMENT. `id` already exists on both tables as String(36) with a
-- uuid4 default and is already part of the PK, so it is populated and unique.
--
-- ⚠️ THE CODE HALF ALREADY SHIPPED. report_detail.py::_delete_report_children
-- used to delete rows from both tables explicitly; those two lines were
-- removed in Step 4a-2. That removal is a NO-OP until this migration runs
-- (the FKs still cascade), and this migration achieves NOTHING if those lines
-- come back. Both halves are required.
--
-- Independent of r10a10. Ship before or after; do NOT bundle them.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- PRE-FLIGHT — `id` must be able to stand alone as the primary key.
-- Both must return 0.
-- ---------------------------------------------------------------------
SELECT 'xero_report_sync' AS tbl, count(*) AS null_or_duplicate_ids FROM (
    SELECT id FROM pettycashv2.xero_report_sync WHERE id IS NULL
    UNION ALL
    SELECT id FROM pettycashv2.xero_report_sync GROUP BY id HAVING count(*) > 1
) x
UNION ALL
SELECT 'xero_bank_transfer', count(*) FROM (
    SELECT id FROM pettycashv2.xero_bank_transfer WHERE id IS NULL
    UNION ALL
    SELECT id FROM pettycashv2.xero_bank_transfer GROUP BY id HAVING count(*) > 1
) y;
-- ⚠️ If either is non-zero, STOP.


-- ---------------------------------------------------------------------
-- xero_report_sync
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2.xero_report_sync
    DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey;
ALTER TABLE pettycashv2.xero_report_sync
    DROP CONSTRAINT IF EXISTS xero_report_sync_pkey;
ALTER TABLE pettycashv2.xero_report_sync
    ADD CONSTRAINT xero_report_sync_pkey PRIMARY KEY (id);
ALTER TABLE pettycashv2.xero_report_sync
    ALTER COLUMN report_id DROP NOT NULL;
ALTER TABLE pettycashv2.xero_report_sync
    ADD CONSTRAINT xero_report_sync_report_id_fkey
    FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id)
    ON DELETE SET NULL;


-- ---------------------------------------------------------------------
-- xero_bank_transfer
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2.xero_bank_transfer
    DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey;
ALTER TABLE pettycashv2.xero_bank_transfer
    DROP CONSTRAINT IF EXISTS xero_bank_transfer_pkey;
ALTER TABLE pettycashv2.xero_bank_transfer
    ADD CONSTRAINT xero_bank_transfer_pkey PRIMARY KEY (id);
ALTER TABLE pettycashv2.xero_bank_transfer
    ALTER COLUMN sync_report_id DROP NOT NULL;
ALTER TABLE pettycashv2.xero_bank_transfer
    ADD CONSTRAINT xero_bank_transfer_sync_report_id_fkey
    FOREIGN KEY (sync_report_id) REFERENCES pettycashv2.report(id)
    ON DELETE SET NULL;


-- ---------------------------------------------------------------------
-- VERIFY — both should report on_delete = SET NULL, single-column PK (id)
-- ---------------------------------------------------------------------
SELECT cl.relname AS tbl, con.conname, con.contype,
       CASE con.confdeltype WHEN 'n' THEN 'SET NULL' WHEN 'c' THEN 'CASCADE'
            WHEN 'a' THEN 'NO ACTION' ELSE con.confdeltype::text END AS on_delete
  FROM pg_constraint con
  JOIN pg_class cl     ON cl.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
 WHERE ns.nspname = 'pettycashv2'
   AND cl.relname IN ('xero_report_sync','xero_bank_transfer')
   AND con.contype IN ('p','f')
 ORDER BY 1, 3;


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;


-- ---------------------------------------------------------------------
-- DOWN — restore the composite PKs and the CASCADE.
--
-- FAILS if any row has a NULL FK by then (an audit row whose report was
-- deleted while this was applied). That is correct: the old shape cannot
-- represent such a row. Deleting those orphans first DESTROYS Xero publish
-- history, so think before you do it.
--
--   ALTER TABLE pettycashv2.xero_report_sync
--       DROP CONSTRAINT IF EXISTS xero_report_sync_report_id_fkey,
--       DROP CONSTRAINT IF EXISTS xero_report_sync_pkey;
--   ALTER TABLE pettycashv2.xero_report_sync
--       ALTER COLUMN report_id SET NOT NULL,
--       ADD CONSTRAINT xero_report_sync_pkey PRIMARY KEY (id, report_id),
--       ADD CONSTRAINT xero_report_sync_report_id_fkey
--       FOREIGN KEY (report_id) REFERENCES pettycashv2.report(id)
--       ON DELETE CASCADE;
--
--   ALTER TABLE pettycashv2.xero_bank_transfer
--       DROP CONSTRAINT IF EXISTS xero_bank_transfer_sync_report_id_fkey,
--       DROP CONSTRAINT IF EXISTS xero_bank_transfer_pkey;
--   ALTER TABLE pettycashv2.xero_bank_transfer
--       ALTER COLUMN sync_report_id SET NOT NULL,
--       ADD CONSTRAINT xero_bank_transfer_pkey PRIMARY KEY (id, sync_report_id),
--       ADD CONSTRAINT xero_bank_transfer_sync_report_id_fkey
--       FOREIGN KEY (sync_report_id) REFERENCES pettycashv2.report(id)
--       ON DELETE CASCADE;
-- ---------------------------------------------------------------------
