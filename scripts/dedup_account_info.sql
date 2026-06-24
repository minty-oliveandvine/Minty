-- Deduplicate pettycashv2.account_info on (entity_id, xero_account_id).
--
-- Prerequisite cleanup for Alembic migration a3c5e7f9b1d4, which adds
-- UNIQUE (entity_id, xero_account_id) on account_info. Concurrent background
-- syncs could insert the same Xero account twice before any committed,
-- leaving duplicate rows that block the constraint.
--
-- Keep-rule: survivor = newest row per group (created_at DESC NULLS LAST,
-- tie-break on id). Child rows in entity_account_xero (FK account_id ->
-- account_info.id) are repointed from the losers to the survivor BEFORE the
-- losers are deleted, so no FK is violated and no link is orphaned.
--
-- Idempotent: once no duplicates remain, _acct_dedup is empty and both the
-- UPDATE and DELETE are no-ops. Run inside the transaction below so it is
-- all-or-nothing. Verify against staging first; take a snapshot before prod.
BEGIN;

CREATE TEMP TABLE _acct_dedup ON COMMIT DROP AS
WITH dups AS (
    SELECT entity_id, xero_account_id
    FROM pettycashv2.account_info
    WHERE xero_account_id IS NOT NULL
      AND entity_id IS NOT NULL
    GROUP BY entity_id, xero_account_id
    HAVING count(*) > 1
),
ranked AS (
    SELECT ai.id,
           ai.entity_id,
           ai.xero_account_id,
           row_number() OVER (
               PARTITION BY ai.entity_id, ai.xero_account_id
               ORDER BY ai.created_at DESC NULLS LAST, ai.id
           ) AS rn
    FROM pettycashv2.account_info ai
    JOIN dups d USING (entity_id, xero_account_id)
),
survivor AS (
    SELECT entity_id, xero_account_id, id AS keep_id
    FROM ranked
    WHERE rn = 1
)
SELECT r.id AS lose_id, s.keep_id
FROM ranked r
JOIN survivor s USING (entity_id, xero_account_id)
WHERE r.rn > 1;

-- 1. Repoint child links from the duplicate (loser) row to the survivor.
UPDATE pettycashv2.entity_account_xero e
SET account_id = d.keep_id
FROM _acct_dedup d
WHERE e.account_id = d.lose_id;

-- 2. Delete the duplicate account_info rows.
DELETE FROM pettycashv2.account_info
WHERE id IN (SELECT lose_id FROM _acct_dedup);

COMMIT;
