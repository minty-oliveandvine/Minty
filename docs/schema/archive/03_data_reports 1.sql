-- ==================================================================
--  Data migration  pettycashv2 -> pettycash_test   (STAGE B2: reports/cash/sale)
--
--  *** STATELESS REWRITE ***  No temp tables / no cross-statement session
--  state, so it runs in SQL editors (Supabase) that execute each statement on a
--  separate connection. Surrogate ids are recovered from the TARGET's natural
--  unique keys instead of from temp remap tables:
--     cash_info  -> (currency_id, cash_value)
--     sale_info  -> (sale_name)
--     report     -> (entity_id, transaction_date)   [children find their report
--                    by joining the source parent -> that (entity,date) key]
--  User ids mirror 02 EXACTLY: uuid ids kept; legacy ids -> md5('user:'||id).
--
--  Run AFTER 02_data_foundation.sql is COMMITTED (needs target entities /
--  currency_info / account_info / xero_contact_sync / user present).
--
--  DECISIONS baked in (unchanged from the temp-table version):
--   * report := report_v2 + report(legacy) + report_draft, deduped by
--     (entity_id, transaction_date), priority report_v2 > report > report_draft.
--   * cash_info: source serial cash_id dropped; new uuid keyed by currency+value.
--     HKD note/coin denominations ensured for the wide cashcount_draft columns.
--   * sale_info: per-entity rows collapsed to the global catalog by sale_name.
--
--  Ends with ROLLBACK. Flip to COMMIT to persist. Re-running: TRUNCATE the B2
--  tables first (report has no conflict guard) — see note at bottom.
-- ==================================================================

BEGIN;

-- ==================================================================
-- 1. cash_info
-- ==================================================================
-- Target currency_id = source country_info.currency_id (the uuid 02 copied into
-- currency_info.id). Dedup by (currency_id, cash_value).
INSERT INTO pettycash_test.cash_info (id, currency_id, type, cash_value, cash_name, description)
SELECT DISTINCT ON (co.currency_id, ci.cash_value)
       gen_random_uuid(), co.currency_id,
       (CASE lower(COALESCE(ci.type,''))
          WHEN 'coin' THEN 'coin' WHEN 'note' THEN 'note' ELSE NULL END)::pettycash_test.cash_type,
       ci.cash_value::numeric, ci.cash_name, ci."desc"
FROM pettycashv2.cash_info ci
JOIN pettycashv2.country_info co ON co.country_code = ci.country_code
WHERE co.currency_id IS NOT NULL
ORDER BY co.currency_id, ci.cash_value, ci.cash_id
ON CONFLICT (currency_id, cash_value) DO NOTHING;

-- ensure HKD note/coin denominations exist (wide cashcount_draft columns need them)
INSERT INTO pettycash_test.cash_info (id, currency_id, type, cash_value, cash_name, description)
SELECT gen_random_uuid(), hc.id,
       (CASE WHEN v.val >= 10 THEN 'note' ELSE 'coin' END)::pettycash_test.cash_type,
       v.val::numeric, 'HKD ' || v.val, NULL
FROM (SELECT id FROM pettycash_test.currency_info WHERE currency_code = 'HKD') hc
CROSS JOIN (VALUES (1000),(500),(100),(50),(20),(10),(5),(2),(1)) v(val)
ON CONFLICT (currency_id, cash_value) DO NOTHING;

-- entity_cash_detail (source serial cash_id -> target uuid via natural key)
INSERT INTO pettycash_test.entity_cash_detail (entity_id, cash_id, cash_type, cash_instock, description)
SELECT DISTINCT ON (ecd.entity_id, tc.id)
       ecd.entity_id::uuid, tc.id,
       (CASE lower(COALESCE(ecd.cash_type,''))
          WHEN 'coin' THEN 'coin' WHEN 'note' THEN 'note' ELSE NULL END)::pettycash_test.cash_type,
       ecd.cash_instock::numeric, ecd."desc"
FROM pettycashv2.entity_cash_detail_v2 ecd
JOIN pettycashv2.cash_info sci    ON sci.cash_id = ecd.cash_id
JOIN pettycashv2.country_info co  ON co.country_code = sci.country_code
JOIN pettycash_test.cash_info tc  ON tc.currency_id = co.currency_id
                                 AND tc.cash_value = sci.cash_value::numeric
ORDER BY ecd.entity_id, tc.id, ecd.cash_id;

-- ==================================================================
-- 2. sale_info (global catalog by sale_name) + entity_sale_setting (per-entity)
-- ==================================================================
-- sale_type mapping: 'delivery' kept as delivery; everything else (including the
-- old 'other' and NULL) -> 'electric'.  <-- per request: other => electric
INSERT INTO pettycash_test.sale_info (id, type, sale_name, value_name, display_order, enabled, created_at, updated_at)
SELECT DISTINCT ON (sale_name)
       gen_random_uuid(),
       (CASE lower(COALESCE(type,''))
          WHEN 'delivery' THEN 'delivery' ELSE 'electric' END)::pettycash_test.sale_type,
       sale_name, value_name, display_order, COALESCE(enabled,true), now(), now()
FROM pettycashv2.sale_info
WHERE sale_name IS NOT NULL
ORDER BY sale_name, sale_id
ON CONFLICT (sale_name) DO NOTHING;

-- entity_sale_setting: the source sale_info is per-entity, so each (entity,
-- sale_name) pair becomes a mapping row (entity_id, global catalog sale_id).
INSERT INTO pettycash_test.entity_sale_setting (entity_id, sale_id, is_active, display_order)
SELECT DISTINCT ON (te.id, ts.id)
       te.id, ts.id, COALESCE(si.enabled, true), si.display_order
FROM pettycashv2.sale_info si
JOIN pettycash_test.entities te  ON te.id::text = lower(si.entity_id)
JOIN pettycash_test.sale_info ts ON ts.sale_name = si.sale_name
WHERE si.sale_name IS NOT NULL
ORDER BY te.id, ts.id, si.sale_id
ON CONFLICT (entity_id, sale_id) DO NOTHING;

-- ==================================================================
-- 3. report consolidation (v2 + legacy + draft, dedup by entity+date)
-- ==================================================================
-- The winning source id becomes the target report id. Children below DO NOT need
-- a remap table: they find their target report by (entity_id, transaction_date),
-- which is UNIQUE in the target.
INSERT INTO pettycash_test.report
  (id, entity_id, transaction_date, next_transaction_date, status, publishing_status,
   opening_balance, cash_addition, adjusted_opening_balance, cashsale_total, nocashsale_total,
   total_sales, expense_total, bank_deposit, closing_balance, safe_box_balance,
   discrepancy_amount, discrepancy_type, discrepancy_reason, current_section, completed_sections,
   xero_integrated, created_by, created_at, updated_at)
SELECT DISTINCT ON (src.entity_id, src.txn_date)
       src.old_id::uuid, src.entity_id::uuid, src.txn_date, src.next_txn_date,
       src.status::pettycash_test.report_status,
       (CASE WHEN lower(COALESCE(src.publishing_status,'')) IN ('completed','published','success','complete')
             THEN 'completed' ELSE 'unpublished' END)::pettycash_test.publish_status,
       src.opening_balance::numeric, src.cash_addition::numeric, src.adjusted_opening_balance::numeric,
       src.cashsale_total::numeric, src.nocashsale_total::numeric, src.total_sales::numeric,
       src.expense_total::numeric, src.bank_deposit::numeric, src.closing_balance::numeric, src.safe_box_balance::numeric,
       src.discrepancy_amount::numeric,
       (CASE lower(COALESCE(src.discrepancy_type,'none'))
          WHEN 'over' THEN 'over' WHEN 'short' THEN 'short' ELSE 'none' END)::pettycash_test.discrepancy_type,
       src.discrepancy_reason, src.current_section, src.completed_sections::jsonb, src.xero_integrated,
       (SELECT CASE WHEN uu.id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    THEN uu.id::uuid ELSE md5('user:'||uu.id)::uuid END
          FROM pettycashv2."user" uu WHERE uu.username = src.uploaded_by LIMIT 1),
       COALESCE(src.created_at, now()), now()
FROM (
  -- priority 3: report_v2 (lowest)
  SELECT 3 AS prio, v.report_id AS old_id, NULLIF(v.entity_id,'') AS entity_id, v.report_date AS txn_date,
         NULL::date AS next_txn_date,
         (CASE lower(COALESCE(v.status,''))
            WHEN 'published' THEN 'published' WHEN 'complete' THEN 'published' WHEN 'completed' THEN 'published'
            WHEN 'submit' THEN 'submitted' WHEN 'submitted' THEN 'submitted'
            ELSE 'draft' END) AS status,
         'unpublished' AS publishing_status,
         v.opening_balance, v.add_cash_amount AS cash_addition, v.adjusted_opening_balance,
         v.cashsale_total, v.nocashsale_total,
         COALESCE(v.cashsale_total,0)+COALESCE(v.nocashsale_total,0) AS total_sales,
         v.expense_total, v.cash_deposit AS bank_deposit,
         NULL::double precision AS closing_balance, NULL::double precision AS safe_box_balance,
         NULL::double precision AS discrepancy_amount, 'none' AS discrepancy_type, NULL::varchar AS discrepancy_reason,
         NULL::varchar AS current_section, NULL::json AS completed_sections, NULL::boolean AS xero_integrated,
         NULL::varchar AS uploaded_by, v.report_date::timestamp AS created_at
  FROM pettycashv2.report_v2 v
  UNION ALL
  -- priority 1: legacy report (highest)
  SELECT 1, r.id, NULLIF(r.company,''), r.transaction_date, r.next_transaction_date,
         'published', r.publishing_status,
         r.opening_balance, r.cash_addition, r.adjusted_opening_balance,
         r.cash_sales, COALESCE(r.total_sales,0)-COALESCE(r.cash_sales,0), r.total_sales,
         r.expenses, r.bank_deposit, r.closing_balance, r.safe_box_balance,
         r.discrepancy_amount, r.discrepancy_type, r.discrepancy_reason,
         NULL, NULL, r.xero_integrated_yes, r.uploaded_by, r.date
  FROM pettycashv2.report r
  UNION ALL
  -- priority 2: report_draft
  SELECT 2, d.id, NULLIF(d.company,''), d.transaction_date, d.next_transaction_date,
         (CASE lower(COALESCE(d.status,''))
            WHEN 'submit' THEN 'submitted' WHEN 'submitted' THEN 'submitted'
            WHEN 'published' THEN 'published' WHEN 'completed' THEN 'published'
            ELSE 'draft' END),
         'unpublished',
         d.opening_balance, d.cash_addition, d.adjusted_opening_balance,
         d.cash_sales, COALESCE(d.total_sales,0)-COALESCE(d.cash_sales,0), d.total_sales,
         d.expenses, d.bank_deposit, d.closing_balance, d.safe_box_balance,
         d.discrepancy_amount, d.discrepancy_type, d.discrepancy_reason,
         d.current_section, d.completed_sections, d.xero_integrated_yes, d.uploaded_by, d.date
  FROM pettycashv2.report_draft d
) src
WHERE src.entity_id IS NOT NULL
ORDER BY src.entity_id, src.txn_date, src.prio;

-- ==================================================================
-- 4. report children — join source parent -> target report by (entity, date)
--    (entity match is done on text to avoid casting any stray non-uuid string)
-- ==================================================================
-- 4a. report_sale  <- report_sale_detail (parent report_v2)
INSERT INTO pettycash_test.report_sale (id, report_id, sale_id, amount, created_at)
SELECT rsd.id::uuid, tr.id, ts.id, COALESCE(rsd.amount,0)::numeric, COALESCE(rsd.create_at, now())
FROM pettycashv2.report_sale_detail rsd
JOIN pettycashv2.report_v2 v      ON v.report_id = rsd.report_id
JOIN pettycash_test.report tr     ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date
JOIN pettycashv2.sale_info ssi    ON ssi.sale_id = rsd.sale_id
JOIN pettycash_test.sale_info ts  ON ts.sale_name = ssi.sale_name
ON CONFLICT (report_id, sale_id) DO NOTHING;

-- 4b. report_expense  <- report_expense_detail (parent report_v2)
INSERT INTO pettycash_test.report_expense
  (id, report_id, account_id, contact_id, item, amount, remarks, description, attachment_id, created_at)
SELECT ed.expense_id::uuid, tr.id, ai.id::uuid, NULL, NULL,
       COALESCE(ed.amount,0)::numeric, NULL, ed.description, NULL, COALESCE(ed.create_at, now())
FROM pettycashv2.report_expense_detail ed
JOIN pettycashv2.report_v2 v   ON v.report_id = ed.report_id
JOIN pettycash_test.report tr  ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date
LEFT JOIN pettycashv2.account_info ai ON ai.id = ed.account_id
ON CONFLICT (id) DO NOTHING;

-- 4b(2). report_expense  <- shop_expense (parent legacy report)
INSERT INTO pettycash_test.report_expense
  (id, report_id, account_id, contact_id, item, amount, remarks, description, attachment_id, created_at)
SELECT se.id::uuid, tr.id, ai.id::uuid, xc.id::uuid, se.item,
       COALESCE(se.amount,0)::numeric, se.remarks, NULL, NULL, now()
FROM pettycashv2.shop_expense se
JOIN pettycashv2.report r      ON r.id = se.report_id
JOIN pettycash_test.report tr  ON tr.entity_id::text = lower(r.company) AND tr.transaction_date = r.transaction_date
LEFT JOIN pettycashv2.account_info ai ON ai.id = se.account_id
LEFT JOIN pettycashv2.xero_contact_sync xc ON xc.id = se.contact_id
ON CONFLICT (id) DO NOTHING;

-- 4c. report_cash_count  <- report_cash_detail (parent report_v2)
INSERT INTO pettycash_test.report_cash_count (id, report_id, cash_id, quantity)
SELECT gen_random_uuid(), tr.id, tc.id, GREATEST(COALESCE(rcd.count,0)::int, 0)
FROM pettycashv2.report_cash_detail rcd
JOIN pettycashv2.report_v2 v      ON v.report_id = rcd.report_id
JOIN pettycash_test.report tr     ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date
JOIN pettycashv2.cash_info sci    ON sci.cash_id = rcd.cash_id
JOIN pettycashv2.country_info co  ON co.country_code = sci.country_code
JOIN pettycash_test.cash_info tc  ON tc.currency_id = co.currency_id
                                 AND tc.cash_value = sci.cash_value::numeric
ON CONFLICT (report_id, cash_id) DO NOTHING;

-- 4d. report_cash_count  <- report_cashcount_draft (wide HKD columns -> rows, parent report_draft)
INSERT INTO pettycash_test.report_cash_count (id, report_id, cash_id, quantity)
SELECT gen_random_uuid(), tr.id, tc.id, GREATEST(q.qty,0)
FROM (
      SELECT report_id, 1000 AS val, thousand_note    AS qty FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,  500, fivehundred_note FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,  100, onehundred_note  FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,   50, fifty_note       FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,   20, twenty_note      FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,   10, ten_note         FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,    5, five_coin        FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,    2, two_coin         FROM pettycashv2.report_cashcount_draft
      UNION ALL SELECT report_id,    1, one_coin         FROM pettycashv2.report_cashcount_draft
     ) q
JOIN pettycashv2.report_draft d  ON d.id = q.report_id
JOIN pettycash_test.report tr    ON tr.entity_id::text = lower(d.company) AND tr.transaction_date = d.transaction_date
JOIN pettycash_test.cash_info tc ON tc.cash_value = q.val::numeric
                                AND tc.currency_id = (SELECT id FROM pettycash_test.currency_info WHERE currency_code='HKD')
WHERE q.qty IS NOT NULL AND q.qty <> 0
ON CONFLICT (report_id, cash_id) DO NOTHING;

-- ==================================================================
-- 4e. report_history  <- report_history + report_history_draft + report_history_v2
-- ==================================================================
-- user_id mapping mirrors 02 (deterministic); LEFT JOIN the source user so we
-- only emit ids that actually exist in the migrated user table.
INSERT INTO pettycash_test.report_history
  (id, report_id, user_id, action, field_changed, old_value, new_value, created_at)
SELECT gen_random_uuid(), tr.id,
       CASE WHEN hu.id IS NULL THEN NULL
            WHEN hu.id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN hu.id::uuid ELSE md5('user:'||hu.id)::uuid END,
       h.action, h.field_changed, h.old_value, h.new_value, h."timestamp"
FROM pettycashv2.report_history h
JOIN pettycashv2.report r     ON r.id = h.report_id
JOIN pettycash_test.report tr ON tr.entity_id::text = lower(r.company) AND tr.transaction_date = r.transaction_date
LEFT JOIN pettycashv2."user" hu ON hu.id = h.user_id;

INSERT INTO pettycash_test.report_history
  (id, report_id, user_id, action, field_changed, old_value, new_value, created_at)
SELECT gen_random_uuid(), tr.id,
       CASE WHEN hu.id IS NULL THEN NULL
            WHEN hu.id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN hu.id::uuid ELSE md5('user:'||hu.id)::uuid END,
       h.action, h.field_changed, h.old_value, h.new_value, h."timestamp"
FROM pettycashv2.report_history_draft h
JOIN pettycashv2.report_draft d ON d.id = h.report_draft_id
JOIN pettycash_test.report tr   ON tr.entity_id::text = lower(d.company) AND tr.transaction_date = d.transaction_date
LEFT JOIN pettycashv2."user" hu ON hu.id = h.user_id;

-- v2 history is a balance snapshot; folded into the audit shape as action='snapshot'
INSERT INTO pettycash_test.report_history
  (id, report_id, user_id, action, field_changed, old_value, new_value, created_at)
SELECT gen_random_uuid(), tr.id,
       CASE WHEN hu.id IS NULL THEN NULL
            WHEN hu.id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN hu.id::uuid ELSE md5('user:'||hu.id)::uuid END,
       'snapshot', h.status, NULL,
       json_build_object('opening_balance',h.opening_balance,'sale_amount',h.sale_amount,
                         'expense_amount',h.expense_amount,'withdraw_amount',h.withdraw_amount)::text,
       COALESCE(h.create_date, now())
FROM pettycashv2.report_history_v2 h
JOIN pettycashv2.report_v2 v  ON v.report_id = h.report_id
JOIN pettycash_test.report tr ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date
LEFT JOIN pettycashv2."user" hu ON hu.id = h.emp_id;

-- ==================================================================
-- 5. xero sync (remap report link via (entity,date); fix typo columns)
-- ==================================================================
INSERT INTO pettycash_test.xero_bank_transaction
  (id, sync_report_id, type, xero_contact_id, xero_contact_name, unit_amount, quantity,
   xero_account_id, xero_account_code, description, xero_bank_account_id, xero_bank_transaction_id,
   subtotal, total_tax, total, status, created_at)
SELECT x.id::uuid, tr.id, x.type, x.xero_contact_id, x.xero_contact_name,
       x.unit_amount::numeric, x.quantity::numeric, x.xero_account_id, x.xero_account_code,
       x.description, x.xero_bank_account_id, x.xero_bank_transaction_id,
       x.subtotal::numeric, x.total_tax::numeric, x.total::numeric, x.status, COALESCE(x.create_at, now())
FROM pettycashv2.xero_bank_transaction x
LEFT JOIN pettycashv2.report_v2 v ON v.report_id = x.sync_report_id
LEFT JOIN pettycash_test.report tr ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date;

INSERT INTO pettycash_test.xero_bank_transfer
  (id, sync_report_id, from_bank_account_id, to_bank_account_id, amount, transfer_date,
   xero_bank_transfer_id, from_bank_transaction_id, to_bank_transaction_id, status, error_message)
SELECT x.id::uuid, tr.id, x.from_bank_account_id, x.to_bank_account_id, x.amount::numeric,
       x.transfer_date, x.xero_bank_transfer_id, x.from_bank_transaction_id, x.to_bank_transaction_id,
       x.status, x.error_message
FROM pettycashv2.xero_bank_transfer x
JOIN pettycashv2.report_v2 v  ON v.report_id = x.sync_report_id
JOIN pettycash_test.report tr ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date;

INSERT INTO pettycash_test.xero_report_sync
  (id, report_id, sync_status, reported_at, completed_at, xero_response_text)
SELECT DISTINCT ON (tr.id)
       x.id::uuid, tr.id, x.sync_statuc, x.reported_at, x.completed_at, x.xero_reponse_text
FROM pettycashv2.xero_report_sync x
JOIN pettycashv2.report_v2 v  ON v.report_id = x.report_id
JOIN pettycash_test.report tr ON tr.entity_id::text = lower(v.entity_id) AND tr.transaction_date = v.report_date
ORDER BY tr.id, x.completed_at DESC NULLS LAST;

-- counts -------------------------------------------------------------
DO $$
DECLARE
  n_rep bigint; n_sale bigint; n_exp bigint; n_cc bigint; n_hist bigint; n_cash bigint;
  n_si bigint; n_ess bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM pettycash_test.report'             INTO n_rep;
  EXECUTE 'SELECT count(*) FROM pettycash_test.report_sale'        INTO n_sale;
  EXECUTE 'SELECT count(*) FROM pettycash_test.report_expense'     INTO n_exp;
  EXECUTE 'SELECT count(*) FROM pettycash_test.report_cash_count'  INTO n_cc;
  EXECUTE 'SELECT count(*) FROM pettycash_test.report_history'     INTO n_hist;
  EXECUTE 'SELECT count(*) FROM pettycash_test.cash_info'          INTO n_cash;
  EXECUTE 'SELECT count(*) FROM pettycash_test.sale_info'          INTO n_si;
  EXECUTE 'SELECT count(*) FROM pettycash_test.entity_sale_setting' INTO n_ess;
  RAISE NOTICE 'B2  report=%  report_sale=%  report_expense=%  report_cash_count=%  report_history=%  cash_info=%  sale_info=%  entity_sale_setting=%',
    n_rep, n_sale, n_exp, n_cc, n_hist, n_cash, n_si, n_ess;
END $$;

-- Re-running note: `report` has no conflict guard, so before a re-run clear B2:
--   TRUNCATE pettycash_test.report, pettycash_test.report_sale,
--     pettycash_test.report_expense, pettycash_test.report_cash_count,
--     pettycash_test.report_history, pettycash_test.entity_cash_detail,
--     pettycash_test.cash_info, pettycash_test.sale_info,
--     pettycash_test.entity_sale_setting,
--     pettycash_test.xero_bank_transaction, pettycash_test.xero_bank_transfer,
--     pettycash_test.xero_report_sync RESTART IDENTITY CASCADE;

ROLLBACK;
