-- ==================================================================
--  Data migration  pettycashv2  ->  pettycash_test   (STAGE B1: foundation)
--
--  *** STATELESS REWRITE ***
--  The source schema is ALREADY in the new shape (verified via
--  information_schema): currency_info(id uuid, currency_code, symbol),
--  country_info.currency_id uuid, entities.currency_id uuid. So NO currency
--  remap table is needed — the uuids are copied straight across.
--
--  This version uses NO temp tables / NO cross-statement session state, so it
--  runs correctly in SQL editors that execute each statement on a separate
--  connection (where CREATE TEMP TABLE / SET LOCAL / BEGIN..ROLLBACK do not
--  span statements). Every INSERT is fully self-contained.
--
--  ID remapping without a temp table: user ids that are already uuids are kept;
--  legacy non-uuid ids are mapped to a DETERMINISTIC uuid via md5('user:'||id),
--  so every table that references a user resolves to the same new id.
--
--  Scope: this app (petty cash) only. Billing/Django tables excluded.
--  18 foundation tables. Reports/cash/sale = stage B2 (03_data_reports.sql).
--
--  DECISIONS baked in:
--   * entities.currency_id copied straight (already a uuid FK).
--   * user.email := username (source email is mostly null).
--   * entities.status mapped to the target enum (connected/disconnected/
--     onboarding; anything else -> onboarding).
--   * roles/permissions deduped by name (target enforces UNIQUE); role_permission
--     remapped onto the canonical id via correlated subqueries.
--
--  For a true dry run (counts then discard), run this file with psql, which
--  honours the single BEGIN..ROLLBACK transaction. In a per-statement editor
--  the ROLLBACK cannot undo committed rows — clear the target first if re-running.
-- ==================================================================

BEGIN;

-- ---------- currency_info (copy uuids straight; carry real decimal_places) ----
INSERT INTO pettycash_test.currency_info
  (id, currency_code, currency_name, symbol, decimal_places, is_active, created_at, updated_at)
SELECT id, currency_code, currency_name, COALESCE(symbol,''),
       COALESCE(decimal_places,2), COALESCE(is_active,true),
       COALESCE(created_at, now()), COALESCE(updated_at, now())
FROM pettycashv2.currency_info;

-- ---------- country_info (currency_id is already the uuid FK) ------------------
-- country_code source may be varchar(3); target is CHAR(2) -> left 2 chars.
INSERT INTO pettycash_test.country_info
  (country_code, alpha3_code, country_name_en, currency_id, phone_code, is_active, display_order)
SELECT left(country_code,2), NULL, country_name_en,
       currency_id, NULL, TRUE, 999
FROM pettycashv2.country_info;

-- ---------- user (email := username; deterministic id remap) ------------------
INSERT INTO pettycash_test."user"
  (id, username, email, password, first_name, last_name, user_phone,
   is_active, approved, xero_user_id, xero_email, last_login, created_at, updated_at)
SELECT CASE WHEN id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN id::uuid ELSE md5('user:'||id)::uuid END,
       username, username, password,
       COALESCE(first_name,''), COALESCE(last_name,''), user_phone,
       TRUE, COALESCE(approved,false), xero_user_id, xero_email,
       NULL, COALESCE(created_at, now()), now()
FROM pettycashv2."user";

INSERT INTO pettycash_test.user_token
  (id, user_id, access_token, access_token_obtained_at, access_token_expires_in,
   refresh_token, refresh_token_last_used_at, id_token, created_at, updated_at)
SELECT id::uuid,
       CASE WHEN user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN user_id::uuid ELSE md5('user:'||user_id)::uuid END,
       access_token, access_token_obtained_at, access_token_expires_in,
       refresh_token, refresh_token_last_used_at, id_token,
       COALESCE(created_at, now()), COALESCE(updated_at, now())
FROM pettycashv2.user_token;

-- ---------- roles / permissions (dedup by name) -------------------------------
INSERT INTO pettycash_test.role (id, name, description, created_at, updated_at)
SELECT DISTINCT ON (name)
       id::uuid, name, description, COALESCE(created_at,now()), COALESCE(updated_at,now())
FROM pettycashv2.roles
ORDER BY name, created_at NULLS LAST, id;

INSERT INTO pettycash_test.permission (id, code, name, description, created_at, updated_at)
SELECT DISTINCT ON (name)
       id::uuid, name, name, description, COALESCE(created_at,now()), COALESCE(updated_at,now())
FROM pettycashv2.permissions
ORDER BY name, created_at NULLS LAST, id;

-- role_permission: remap each side to the canonical (kept) id for its name via
-- correlated subqueries, then DISTINCT so the (role_id, permission_id) PK holds.
INSERT INTO pettycash_test.role_permission (role_id, permission_id)
SELECT DISTINCT
  (SELECT r2.id::uuid FROM pettycashv2.roles r2
    WHERE r2.name = r.name ORDER BY r2.created_at NULLS LAST, r2.id LIMIT 1),
  (SELECT p2.id::uuid FROM pettycashv2.permissions p2
    WHERE p2.name = p.name ORDER BY p2.created_at NULLS LAST, p2.id LIMIT 1)
FROM pettycashv2.role_permissions rp
JOIN pettycashv2.roles r       ON r.id::text = rp.role_id::text
JOIN pettycashv2.permissions p ON p.id::text = rp.permission_id::text
WHERE rp.role_id IS NOT NULL AND rp.permission_id IS NOT NULL;

-- ---------- entities (currency_id copied straight; deterministic user remap) ---
INSERT INTO pettycash_test.entities
  (id, country_code, currency_id, name, status, contact_option, currency_format,
   timezone, note, xero_org_id, xero_tenant_name, connected_by_user_id,
   onboarding_saved_step, last_connected_at, created_at, updated_at)
SELECT e.id::uuid, left(e.country_code,2), e.currency_id, e.name,
       (CASE lower(COALESCE(e.status,'onboarding'))
          WHEN 'connected'    THEN 'connected'
          WHEN 'disconnected' THEN 'disconnected'
          WHEN 'onboarding'   THEN 'onboarding'
          ELSE 'onboarding'
        END)::pettycash_test.entity_status,
       e.contact_option, e.currency_format, e.timezone, e.note, e.xero_org_id,
       e.xero_tenant_name,
       CASE WHEN e.connected_by_user_id IS NULL THEN NULL
            WHEN e.connected_by_user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN e.connected_by_user_id::uuid
            ELSE md5('user:'||e.connected_by_user_id)::uuid END,
       e.onboarding_saved_step, e.last_connected_at,
       COALESCE(e.created_at, now()), now()
FROM pettycashv2.entities e;

INSERT INTO pettycash_test.user_entity
  (user_id, entity_id, role, approved, joined_at, created_at)
SELECT CASE WHEN ue.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN ue.user_id::uuid ELSE md5('user:'||ue.user_id)::uuid END,
       ue.entity_id::uuid,
       (CASE lower(COALESCE(ue.role,'entity_base'))
          WHEN 'user' THEN 'entity_base' WHEN 'no_role' THEN 'entity_base'
          WHEN 'none' THEN 'entity_base'
          WHEN 'super_admin' THEN 'super_admin' WHEN 'admin' THEN 'admin'
          WHEN 'accountant' THEN 'accountant' WHEN 'shop_manager' THEN 'shop_manager'
          WHEN 'cashier' THEN 'cashier' WHEN 'entity_base' THEN 'entity_base'
          ELSE 'entity_base'
        END)::pettycash_test.entity_role,
       COALESCE(ue.approved,false), ue.joined_at, COALESCE(ue.create_at, now())
FROM pettycashv2.user_entity ue;

INSERT INTO pettycash_test.invitation
  (id, entity_id, email, role, token, status, invited_by, accepted_at, expires_at, created_at)
SELECT i.id::uuid, i.entity_id::uuid, i.email,
       (CASE lower(COALESCE(i.role,'entity_base'))
          WHEN 'user' THEN 'entity_base' WHEN 'no_role' THEN 'entity_base'
          WHEN 'none' THEN 'entity_base'
          WHEN 'super_admin' THEN 'super_admin' WHEN 'admin' THEN 'admin'
          WHEN 'accountant' THEN 'accountant' WHEN 'shop_manager' THEN 'shop_manager'
          WHEN 'cashier' THEN 'cashier' WHEN 'entity_base' THEN 'entity_base'
          ELSE 'entity_base'
        END)::pettycash_test.entity_role,
       i.token,
       (CASE lower(COALESCE(i.status,'pending'))
          WHEN 'accepted' THEN 'accepted'
          WHEN 'expired'  THEN 'expired'
          WHEN 'revoked'  THEN 'revoked'
          WHEN 'cancelled' THEN 'revoked' WHEN 'canceled' THEN 'revoked'
          ELSE 'pending'
        END)::pettycash_test.invitation_status,
       CASE WHEN i.invited_by IS NULL THEN NULL
            WHEN i.invited_by ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN i.invited_by::uuid
            ELSE md5('user:'||i.invited_by)::uuid END,
       i.accepted_at, i.expires_at, COALESCE(i.created_at, now())
FROM pettycashv2.invitations i;

INSERT INTO pettycash_test.email_otp
  (id, email, code_hash, attempts, expires_at, verified_at, created_at)
SELECT id::uuid, email, code_hash, COALESCE(attempts,0), expires_at, verified_at,
       COALESCE(created_at, now())
FROM pettycashv2.email_otp;

INSERT INTO pettycash_test.account_info
  (id, entity_id, type, name, xero_account_id, xero_code, status, class_type,
   bank_account_number, bank_account_type, description, created_at, updated_at)
SELECT id::uuid, NULLIF(entity_id::text,'')::uuid, type, name, xero_account_id, xero_code,
       status, class_type, bank_account_number, bank_account_type, description,
       COALESCE(created_at, now()), now()
FROM pettycashv2.account_info;

INSERT INTO pettycash_test.entity_account_xero
  (id, account_id, type, xero_org_id, xero_account_id, name, is_active)
SELECT id::uuid, account_id::uuid, type, xero_org_id, xero_account_id, name,
       COALESCE(is_active,true)
FROM pettycashv2.entity_account_xero;

INSERT INTO pettycash_test.xero_contact_sync
  (id, entity_id, xero_contact_id, xero_org_id, name, category, created_at, updated_at)
SELECT id::uuid, NULLIF(entity_id::text,'')::uuid, xero_contact_id, xero_org_id,
       name, category, now(), now()
FROM pettycashv2.xero_contact_sync;

INSERT INTO pettycash_test.entity_function
  (id, function_code, function_name, description, is_active, display_order, created_at, updated_at)
SELECT id::uuid, function_code, function_name, COALESCE(description,''),
       COALESCE(is_active,true), 999, COALESCE(created_at,now()), COALESCE(updated_at,now())
FROM pettycashv2.entity_function;

INSERT INTO pettycash_test.entity_function_map
  (entity_id, entity_function_id, is_enabled, settings_json, enabled_at, disabled_at,
   created_by, created_at, updated_at)
SELECT DISTINCT ON (entity_id, entity_function_id)
       entity_id::uuid, entity_function_id::uuid, COALESCE(is_enabled,true),
       settings_json, enabled_at, disabled_at,
       CASE WHEN created_by ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN created_by::uuid ELSE NULL END,
       COALESCE(created_at,now()), COALESCE(updated_at,now())
FROM pettycashv2.entity_function_map
ORDER BY entity_id, entity_function_id, updated_at DESC NULLS LAST;

INSERT INTO pettycash_test.entity_pettycash_settings
  (entity_id, opening_balance, start_date,
   pettycash_account_id, bank_account_id, cash_sale_account_id,
   discrepancy_bank_account_id, discrepancy_account_id, director_account_id,
   cash_sale_contact_id, director_contact_id, discrepancy_contact_id,
   created_at, updated_at)
SELECT entity_id::uuid, NULL, NULL,
       NULLIF(pettycash_account_id::text,'')::uuid,
       NULLIF(bank_account_id::text,'')::uuid,
       NULLIF(cash_sale_account_id::text,'')::uuid,
       NULLIF(discrepancy_bank_account_id::text,'')::uuid,
       NULLIF(discrepancy_account_id::text,'')::uuid,
       NULLIF(director_account_id::text,'')::uuid,
       NULLIF(cash_sale_contact_id::text,'')::uuid,
       NULLIF(director_contact_id::text,'')::uuid,
       NULLIF(discrepancy_contact_id::text,'')::uuid,
       COALESCE(created_at,now()), COALESCE(updated_at,now())
FROM pettycashv2.entity_pettycash_settings;

INSERT INTO pettycash_test.share_link
  (id, entity_id, path_segment, token, transaction_date, expires_at, created_at)
SELECT id::uuid, entity_id::uuid, path_segment, token,
       transaction_date::date, expires_at, COALESCE(created_at, now())
FROM pettycashv2.share_link;

-- counts -------------------------------------------------------------
-- NOTE: roles/permissions/role_permissions rows are deduped by name, so those
-- three lines are EXPECTED to show MISMATCH (target < source). All others OK.
DO $$
DECLARE
  pairs text[][] := ARRAY[
    ['currency_info','currency_info'],['country_info','country_info'],
    ['user','user'],['user_token','user_token'],['roles','role'],
    ['permissions','permission'],['role_permissions','role_permission'],
    ['entities','entities'],['user_entity','user_entity'],
    ['invitations','invitation'],['email_otp','email_otp'],
    ['account_info','account_info'],['entity_account_xero','entity_account_xero'],
    ['xero_contact_sync','xero_contact_sync'],['entity_function','entity_function'],
    ['entity_function_map','entity_function_map'],
    ['entity_pettycash_settings','entity_pettycash_settings'],['share_link','share_link']
  ];
  r text[]; s bigint; d bigint;
BEGIN
  FOREACH r SLICE 1 IN ARRAY pairs LOOP
    EXECUTE format('SELECT count(*) FROM pettycashv2.%I', r[1]) INTO s;
    EXECUTE format('SELECT count(*) FROM %I.%I', 'pettycash_test', r[2]) INTO d;
    RAISE NOTICE 'B1  % : src=%  ->  % : dst=%   %',
      rpad(r[1],26), s, rpad(r[2],26), d,
      CASE WHEN s=d THEN 'OK' ELSE '*** MISMATCH ***' END;
  END LOOP;
END $$;

ROLLBACK;
