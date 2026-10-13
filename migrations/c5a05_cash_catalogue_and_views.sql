-- =====================================================================
--  CASH CATALOGUE + VIEWS (c5a05, 2026-10-13)
--
--  TARGET: a pettycashv3-shaped schema - local dev `postgres` by default.
--  Run with psql; the schema is a variable, and nothing commits unless asked:
--
--    psql "$URL" -v ON_ERROR_STOP=1 -v schema=pettycashv3 -f c5a05_cash_catalogue_and_views.sql
--        -> runs everything, prints the checks, ROLLS BACK
--    ... -v apply=1 ...
--        -> the same, then COMMIT
--
--  A database built from docs/schema/01_schema_rebased.sql after 2026-10-13
--  already has all of this; this script brings an older build up to it.
--
--  ------------------------------------------------------------------
--  WHAT
--
--    cash_info.type NOT NULL; unique on (currency_id, cash_value, type)
--        - HKD's $10 note and $10 coin are two denominations. The key had left
--          type out (pettycashv2's uq_cash_info_currency_value_type never did).
--    entity_cash_detail.cash_type NOT NULL (copied from cash_info.type).
--    report_cash_summary: a report whose cash-count step is done with no rows
--        reads 0, not NULL (the rule Report.actual_cash_total carried alone).
--    entity_setup_summary: (re)created - one row per company's setup state,
--        from the Supabase original plus pettycash_account_id and
--        bill_accounts_default_inactive.
--
--  FAILS LOUDLY, ON PURPOSE: SET NOT NULL refuses if any cash_info row has no
--  type, and the new key refuses if two rows share (currency, value, type).
--  Fix the data, never weaken the constraint.
-- =====================================================================

\if :{?schema}
\else
  \set schema pettycashv3
\endif

BEGIN;
SET LOCAL search_path TO :"schema";

-- before
SELECT count(*) AS cash_info_rows,
       count(*) FILTER (WHERE type IS NULL) AS untyped
  FROM cash_info;

ALTER TABLE cash_info ALTER COLUMN type SET NOT NULL;
ALTER TABLE cash_info DROP CONSTRAINT IF EXISTS cash_info_currency_value_key;
ALTER TABLE cash_info DROP CONSTRAINT IF EXISTS uq_cash_info_currency_value_type;
ALTER TABLE cash_info
  ADD CONSTRAINT uq_cash_info_currency_value_type UNIQUE (currency_id, cash_value, type);

ALTER TABLE entity_cash_detail ALTER COLUMN cash_type SET NOT NULL;

CREATE OR REPLACE VIEW report_cash_summary AS
SELECT r.id                                      AS report_id,
       COALESCE(c.total, CASE WHEN r.completed_sections ? 'cash_count' THEN 0 END)
                                                 AS actual_cash_total,
       COALESCE(c.total, CASE WHEN r.completed_sections ? 'cash_count' THEN 0 END)
         + COALESCE(r.safe_box_balance, 0)       AS cash_balance
  FROM report r
  LEFT JOIN (SELECT report_id,
                    SUM(quantity * cash_value) AS total
               FROM report_cash_count
              GROUP BY report_id) c
    ON c.report_id = r.id;

COMMENT ON VIEW report_cash_summary IS
  'Replaces report.actual_cash_total. NULL actual_cash_total means the report '
  'was never cash-counted; a report whose cash-count step is done with no rows '
  '(every denomination counted as zero) reads 0.';

DROP VIEW IF EXISTS entity_setup_summary;
CREATE VIEW entity_setup_summary AS
SELECT e.id AS entity_id,
       e.name AS entity_name,
       e.status AS entity_status,
       e.currency_id,
       e.country_code,
       e.status = 'connected' AS xero_connected,
       e.xero_org_id IS NOT NULL AS xero_org_linked,
       e.xero_org_id,
       e.xero_tenant_name,
       e.last_connected_at,
       e.connected_by_user_id,
       cu.username AS connected_by_username,
       COALESCE(m.pettycash_enabled, false) AS pettycash_module_enabled,
       COALESCE(m.bill_enabled, false) AS bill_module_enabled,
       (eps.pettycash_account_id IS NOT NULL)::integer + (eps.bank_account_id IS NOT NULL)::integer
         + (eps.cash_sale_account_id IS NOT NULL)::integer + (eps.discrepancy_bank_account_id IS NOT NULL)::integer
         + (eps.discrepancy_account_id IS NOT NULL)::integer + (eps.director_account_id IS NOT NULL)::integer
         AS pettycash_accounts_set,
       6 AS pettycash_accounts_total,
       (eps.cash_sale_contact_id IS NOT NULL)::integer + (eps.director_contact_id IS NOT NULL)::integer
         + (eps.discrepancy_contact_id IS NOT NULL)::integer AS pettycash_contacts_set,
       3 AS pettycash_contacts_total,
       COALESCE(ai.n, 0) AS xero_accounts_synced,
       COALESCE(ba.n_active, 0) AS bill_accounts_set,
       COALESCE(ba.n_default, 0) AS bill_accounts_default,
       COALESCE(ba.n_default_inactive, 0) AS bill_accounts_default_inactive,
       eps.opening_balance,
       eps.start_date,
       eps.pettycash_account_id,
       a_pc.name AS pettycash_account_name,
       a_pc.xero_code AS pettycash_account_code,
       a_bk.name AS bank_account_name,
       a_bk.xero_code AS bank_account_code,
       a_cs.name AS cash_sale_account_name,
       a_cs.xero_code AS cash_sale_account_code,
       a_db.name AS discrepancy_bank_account_name,
       a_db.xero_code AS discrepancy_bank_account_code,
       a_dc.name AS discrepancy_account_name,
       a_dc.xero_code AS discrepancy_account_code,
       a_dr.name AS director_account_name,
       a_dr.xero_code AS director_account_code,
       c_cs.name AS cash_sale_contact_name,
       c_dr.name AS director_contact_name,
       c_dc.name AS discrepancy_contact_name,
       eps.updated_at AS pettycash_settings_updated_at
  FROM entities e
  LEFT JOIN "user" cu ON cu.id = e.connected_by_user_id
  LEFT JOIN entity_pettycash_settings eps ON eps.entity_id = e.id
  LEFT JOIN account_info a_pc ON a_pc.id = eps.pettycash_account_id
  LEFT JOIN account_info a_bk ON a_bk.id = eps.bank_account_id
  LEFT JOIN account_info a_cs ON a_cs.id = eps.cash_sale_account_id
  LEFT JOIN account_info a_db ON a_db.id = eps.discrepancy_bank_account_id
  LEFT JOIN account_info a_dc ON a_dc.id = eps.discrepancy_account_id
  LEFT JOIN account_info a_dr ON a_dr.id = eps.director_account_id
  LEFT JOIN xero_contact_sync c_cs ON c_cs.id = eps.cash_sale_contact_id
  LEFT JOIN xero_contact_sync c_dr ON c_dr.id = eps.director_contact_id
  LEFT JOIN xero_contact_sync c_dc ON c_dc.id = eps.discrepancy_contact_id
  LEFT JOIN LATERAL (
        SELECT bool_or(ef.function_code = 'PETTY_CASH' AND efm.is_enabled) AS pettycash_enabled,
               bool_or(ef.function_code = 'PAYMENT_REQUEST' AND efm.is_enabled) AS bill_enabled
          FROM entity_function_map efm
          JOIN entity_function ef ON ef.id = efm.entity_function_id
         WHERE efm.entity_id = e.id) m ON true
  LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM account_info x WHERE x.entity_id = e.id) ai ON true
  LEFT JOIN LATERAL (
        SELECT count(*) FILTER (WHERE b.is_active AND NOT b.is_deleted) AS n_active,
               count(*) FILTER (WHERE b.is_active AND NOT b.is_deleted AND b.is_default) AS n_default,
               count(*) FILTER (WHERE b.is_default AND NOT b.is_deleted AND NOT b.is_active) AS n_default_inactive
          FROM entity_bill_account_xero b
         WHERE b.entity_id = e.id) ba ON true;

COMMENT ON VIEW entity_setup_summary IS
  'One row per company: Xero connection, modules on, how many of the six petty-cash '
  'accounts and three contacts are mapped, bill account codes (active, default, a default '
  'left inactive), and the petty-cash settings (opening balance, start date, mapped names).';

-- after
SELECT conname, pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
 WHERE conrelid = 'cash_info'::regclass AND contype = 'u';
SELECT table_name, column_name, is_nullable
  FROM information_schema.columns
 WHERE table_schema = :'schema'
   AND ((table_name = 'cash_info' AND column_name = 'type')
     OR (table_name = 'entity_cash_detail' AND column_name = 'cash_type'));
SELECT count(*) AS companies_in_setup_summary FROM entity_setup_summary;
SELECT count(*) AS reports_in_cash_summary FROM report_cash_summary;

\if :{?apply}
  COMMIT;
\else
  ROLLBACK;
\endif
