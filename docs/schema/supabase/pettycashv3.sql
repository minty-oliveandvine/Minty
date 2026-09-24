DROP SCHEMA IF EXISTS pettycashv3 CASCADE;
CREATE SCHEMA pettycashv3;

CREATE OR REPLACE FUNCTION pettycashv3.set_updated_at()
RETURNS trigger AS $$BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TYPE pettycashv3.entity_status     AS ENUM
  ('onboarding','connected','disconnected');

CREATE TYPE pettycashv3.system_role       AS ENUM ('normal','admin','superadmin');

CREATE TYPE pettycashv3.entity_role       AS ENUM ('entity_base','cashier','shop_manager','accountant','admin','super_admin');

CREATE TYPE pettycashv3.invitation_status AS ENUM
  ('pending','accepted','expired','revoked');

CREATE TYPE pettycashv3.report_status     AS ENUM
  ('draft','submitted','published','void');

CREATE TYPE pettycashv3.publish_status    AS ENUM
  ('unpublished','publishing','completed','failed');

CREATE TYPE pettycashv3.discrepancy_type  AS ENUM
  ('none','over','short');

CREATE TYPE pettycashv3.sale_type         AS ENUM
  ('electronic','delivery','other');

CREATE TYPE pettycashv3.cash_type         AS ENUM ('coin','note');

CREATE TYPE pettycashv3.bill_status       AS ENUM
  ('draft','submitted','returned','partially_paid','paid','void');

CREATE TYPE pettycashv3.publish_state     AS ENUM
  ('draft','published','failed');

CREATE TYPE pettycashv3.payment_status    AS ENUM
  ('pending','partial','completed','failed');

CREATE TYPE pettycashv3.sync_status       AS ENUM
  ('pending','processing','success','failed');

CREATE TYPE pettycashv3.sync_direction    AS ENUM
  ('push','pull');

CREATE TYPE pettycashv3.bill_attachment_role AS ENUM
  ('invoice','supporting_document','receipt','approval_document','other','proof');

CREATE TYPE pettycashv3.payment_attachment_role AS ENUM
  ('bank_slip','remittance_proof','payment_receipt','other');

CREATE TYPE pettycashv3.expense_attachment_role AS ENUM
  ('receipt','invoice','other');

CREATE TYPE pettycashv3.subscription_phase AS ENUM
  ('trial','active','past_due','scheduled_cancel','cancelled','expired');
CREATE TYPE pettycashv3.extension_state    AS ENUM
  ('pending','invoiced','deleted','credited','refunded');
CREATE TYPE pettycashv3.transfer_status    AS ENUM
  ('pending','charging','charged','accepted','declined','cancelled','expired');
CREATE TYPE pettycashv3.audit_outcome      AS ENUM ('succeeded','aborted');

CREATE TYPE pettycashv3.module_code        AS ENUM ('PETTY_CASH','PAYMENT_REQUEST');

CREATE TABLE pettycashv3.currency_info (
  id             UUID          NOT NULL DEFAULT gen_random_uuid(),
  currency_code  CHAR(3)       NOT NULL,
  currency_name  VARCHAR(100)  NOT NULL,
  symbol         VARCHAR(10)   NOT NULL DEFAULT '',
  decimal_places SMALLINT      NOT NULL DEFAULT 2,
  is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT currency_info_pkey PRIMARY KEY (id),
  CONSTRAINT currency_info_code_key UNIQUE (currency_code),
  CONSTRAINT chk_currency_code_len CHECK (length(currency_code) = 3)
);

CREATE TABLE pettycashv3.country_info (
  country_code    CHAR(2)       NOT NULL,
  alpha3_code     CHAR(3)       NULL,
  country_name_en VARCHAR(100)  NOT NULL,
  currency_id     UUID          NULL,
  phone_code      VARCHAR(10)   NULL,
  is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
  display_order   INTEGER       NOT NULL DEFAULT 999,
  CONSTRAINT country_info_pkey PRIMARY KEY (country_code),
  CONSTRAINT fk_country_currency FOREIGN KEY (currency_id)
      REFERENCES pettycashv3.currency_info (id) ON DELETE SET NULL,
  CONSTRAINT chk_country_code_len CHECK (length(country_code) = 2),
  CONSTRAINT chk_alpha3_code_len  CHECK (alpha3_code IS NULL OR length(alpha3_code) = 3)
);

CREATE TABLE pettycashv3.user (
  id                 UUID                     NOT NULL DEFAULT gen_random_uuid(),
  username           VARCHAR(150)             NOT NULL,
  email              VARCHAR(254)             NULL,
  password      VARCHAR(255)             NOT NULL,
  first_name         VARCHAR(150)             NOT NULL DEFAULT '',
  last_name          VARCHAR(150)             NOT NULL DEFAULT '',
  user_phone         VARCHAR(20)              NULL,

  system_role        pettycashv3.system_role  NOT NULL DEFAULT 'normal',
  is_active          BOOLEAN                  NOT NULL DEFAULT TRUE,
  approved           BOOLEAN                  NOT NULL DEFAULT FALSE,
  xero_user_id       UUID                     NULL,
  xero_email         VARCHAR(100)             NULL,

  reset_token        VARCHAR(100)             NULL,
  reset_token_expiry TIMESTAMPTZ              NULL,

  signed_in_at       TIMESTAMPTZ              NULL,
  last_seen_at       TIMESTAMPTZ              NULL,

  last_login         TIMESTAMPTZ              NULL,
  created_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),

  CONSTRAINT user_pkey PRIMARY KEY (id),
  CONSTRAINT user_username_key UNIQUE (username)

 );

CREATE TABLE pettycashv3.user_token (
  id                         UUID        NOT NULL DEFAULT gen_random_uuid(),
  user_id                    UUID        NOT NULL,
  access_token               TEXT        NULL,
  access_token_obtained_at   TIMESTAMPTZ NULL,
  access_token_expires_in    INTEGER     NULL,
  refresh_token              TEXT        NULL,
  refresh_token_last_used_at TIMESTAMPTZ NULL,
  id_token                   TEXT        NULL,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT user_token_pkey PRIMARY KEY (id),
  CONSTRAINT user_token_user_key UNIQUE (user_id),
  CONSTRAINT fk_user_token_user FOREIGN KEY (user_id)
      REFERENCES pettycashv3.user (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.role (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT role_pkey PRIMARY KEY (id),
  CONSTRAINT role_name_key UNIQUE (name)
);

CREATE TABLE pettycashv3.permission (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  code        VARCHAR(100) NOT NULL,
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT permission_pkey PRIMARY KEY (id),
  CONSTRAINT permission_code_key UNIQUE (code)
);

CREATE TABLE pettycashv3.role_permission (
  role_id       UUID NOT NULL,
  permission_id UUID NOT NULL,
  CONSTRAINT role_permission_pkey PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role       FOREIGN KEY (role_id)       REFERENCES pettycashv3.role (id)       ON DELETE CASCADE,
  CONSTRAINT fk_rp_permission FOREIGN KEY (permission_id) REFERENCES pettycashv3.permission (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entities (
  id                    UUID                      NOT NULL DEFAULT gen_random_uuid(),
  country_code          CHAR(2)                   NULL,
  currency_id           UUID                      NULL,
  name                  VARCHAR(100)              NOT NULL,
  status                pettycashv3.entity_status NOT NULL DEFAULT 'onboarding',

  contact_phone         VARCHAR(36)               NULL,
  business_email        VARCHAR(100)              NULL,
  currency_format       VARCHAR(30)               NULL,
  timezone              VARCHAR(30)               NULL,
  note                  TEXT                      NULL,
  xero_org_id           VARCHAR(36)               NULL,
  xero_tenant_name      VARCHAR(255)              NULL,

  financial_year_end_day   SMALLINT               NULL,
  financial_year_end_month SMALLINT               NULL,

  connected_by_user_id  UUID                      NULL,
  onboarding_saved_step INTEGER                   NULL DEFAULT 9,
  last_connected_at     TIMESTAMPTZ               NULL,

  last_accessed_at      TIMESTAMPTZ               NULL,
  last_accessed_by_user_id UUID                   NULL,
  created_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  CONSTRAINT entities_pkey PRIMARY KEY (id),
  CONSTRAINT fk_entities_country  FOREIGN KEY (country_code)         REFERENCES pettycashv3.country_info (country_code) ON DELETE RESTRICT,
  CONSTRAINT fk_entities_currency FOREIGN KEY (currency_id)          REFERENCES pettycashv3.currency_info (id)          ON DELETE RESTRICT,
  CONSTRAINT fk_entities_conn_user FOREIGN KEY (connected_by_user_id) REFERENCES pettycashv3.user (id)              ON DELETE RESTRICT,
  CONSTRAINT fk_entities_last_user FOREIGN KEY (last_accessed_by_user_id) REFERENCES pettycashv3.user (id)          ON DELETE SET NULL,
  CONSTRAINT chk_entities_fy_end_day   CHECK (financial_year_end_day   IS NULL
                                          OR financial_year_end_day   BETWEEN 1 AND 31),
  CONSTRAINT chk_entities_fy_end_month CHECK (financial_year_end_month IS NULL
                                          OR financial_year_end_month BETWEEN 1 AND 12)
);

CREATE TABLE pettycashv3.user_entity (
  user_id   UUID                    NOT NULL,
  entity_id UUID                    NOT NULL,
  role      pettycashv3.entity_role NOT NULL,
  approved  BOOLEAN                 NOT NULL DEFAULT FALSE,
  joined_at TIMESTAMPTZ             NULL,
  created_at TIMESTAMPTZ            NOT NULL DEFAULT now(),
  CONSTRAINT user_entity_pkey PRIMARY KEY (user_id, entity_id),
  CONSTRAINT fk_ue_user   FOREIGN KEY (user_id)   REFERENCES pettycashv3.user (id) ON DELETE CASCADE,
  CONSTRAINT fk_ue_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.invitation (
  id         UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id  UUID                          NOT NULL,
  email      VARCHAR(150)                  NOT NULL,
  first_name VARCHAR(100)                  NULL,
  last_name  VARCHAR(100)                  NULL,
  role       pettycashv3.entity_role       NOT NULL,
  token      VARCHAR(64)                   NOT NULL,
  status     pettycashv3.invitation_status NOT NULL DEFAULT 'pending',
  invited_by UUID                          NULL,
  accepted_at TIMESTAMPTZ                  NULL,
  expires_at  TIMESTAMPTZ                  NULL,
  created_at  TIMESTAMPTZ                  NOT NULL DEFAULT now(),
  CONSTRAINT invitation_pkey PRIMARY KEY (id),
  CONSTRAINT invitation_token_key UNIQUE (token),
  CONSTRAINT fk_inv_entity     FOREIGN KEY (entity_id)  REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_inv_invited_by FOREIGN KEY (invited_by) REFERENCES pettycashv3.user (id) ON DELETE SET NULL
);

CREATE TABLE pettycashv3.email_otp (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  email       VARCHAR(100) NOT NULL,
  code_hash   VARCHAR(255) NOT NULL,
  attempts    INTEGER      NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ  NOT NULL,
  verified_at TIMESTAMPTZ  NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT email_otp_pkey PRIMARY KEY (id)
);

CREATE TABLE pettycashv3.account_info (
  id                  UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id           UUID         NOT NULL,
  type                VARCHAR(50)  NOT NULL,
  name                VARCHAR(80)  NOT NULL,
  xero_account_id     VARCHAR(36)  NULL,
  xero_code           VARCHAR(50)  NULL,
  status              VARCHAR(50)  NULL,
  class_type          VARCHAR(50)  NULL,
  bank_account_number VARCHAR(50)  NULL,
  bank_account_type   VARCHAR(50)  NULL,
  description         VARCHAR(255) NULL,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT account_info_pkey PRIMARY KEY (id),
  CONSTRAINT uq_account_entity_xero UNIQUE (entity_id, xero_account_id),
  CONSTRAINT fk_account_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entity_account_xero (
  id              UUID        NOT NULL DEFAULT gen_random_uuid(),
  account_id      UUID        NOT NULL,
  type            VARCHAR(50) NULL,
  xero_org_id     VARCHAR(36) NULL,
  xero_account_id VARCHAR(36) NULL,
  name            VARCHAR(80) NULL,
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
  CONSTRAINT entity_account_xero_pkey PRIMARY KEY (id),
  CONSTRAINT fk_eax_account FOREIGN KEY (account_id) REFERENCES pettycashv3.account_info (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entity_bill_account_xero (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id       UUID         NOT NULL,
  account_code    VARCHAR(150) NOT NULL,
  account_name    VARCHAR(150) NOT NULL DEFAULT '',
  account_type    VARCHAR(50)  NOT NULL DEFAULT '',
  xero_account_id VARCHAR(36)  NULL,
  is_default      BOOLEAN      NOT NULL DEFAULT FALSE,
  is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
  is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
  sort_order      INTEGER      NOT NULL DEFAULT 0,
  created_by      UUID         NULL,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT entity_bill_account_xero_pkey PRIMARY KEY (id)
);

CREATE TABLE pettycashv3.entity_bill_currency (
  id          UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id   UUID        NOT NULL,
  currency_id UUID        NOT NULL,
  is_default  BOOLEAN     NOT NULL DEFAULT FALSE,
  is_enabled  BOOLEAN     NOT NULL DEFAULT TRUE,
  sort_order  INTEGER     NOT NULL DEFAULT 0,
  created_by  UUID        NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_bill_currency_pkey PRIMARY KEY (id),
  CONSTRAINT uq_ebc_entity_currency UNIQUE (entity_id, currency_id)
);

CREATE TABLE pettycashv3.xero_contact_sync (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id       UUID         NULL,
  xero_contact_id VARCHAR(36)  NOT NULL,
  xero_org_id     VARCHAR(36)  NULL,
  name            VARCHAR(150) NOT NULL,
  category        VARCHAR(50)  NULL,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT xero_contact_sync_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xero_contact_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entity_function (
  id            UUID                     NOT NULL DEFAULT gen_random_uuid(),
  function_code pettycashv3.module_code NOT NULL,
  function_name VARCHAR(150) NOT NULL,
  description   TEXT         NOT NULL DEFAULT '',
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  display_order INTEGER      NOT NULL DEFAULT 999,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT entity_function_pkey PRIMARY KEY (id),
  CONSTRAINT entity_function_code_key UNIQUE (function_code)
);

CREATE TABLE pettycashv3.entity_function_map (
  entity_id          UUID        NOT NULL,
  entity_function_id UUID        NOT NULL,
  is_enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
  settings_json      JSONB       NULL,
  enabled_at         TIMESTAMPTZ NULL,
  disabled_at        TIMESTAMPTZ NULL,

  created_by         UUID        NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_function_map_pkey PRIMARY KEY (entity_id, entity_function_id),
  CONSTRAINT fk_efm_entity   FOREIGN KEY (entity_id)          REFERENCES pettycashv3.entities (id)        ON DELETE CASCADE,
  CONSTRAINT fk_efm_function FOREIGN KEY (entity_function_id) REFERENCES pettycashv3.entity_function (id) ON DELETE RESTRICT,
  CONSTRAINT fk_efm_creator  FOREIGN KEY (created_by)         REFERENCES pettycashv3.user (id)            ON DELETE SET NULL
);

CREATE TABLE pettycashv3.entity_pettycash_settings (
  entity_id                   UUID          NOT NULL,
  opening_balance             NUMERIC(14,2) NULL,
  start_date                  DATE          NULL,
  pettycash_account_id        UUID          NULL,
  bank_account_id             UUID          NULL,
  cash_sale_account_id        UUID          NULL,
  discrepancy_bank_account_id UUID          NULL,
  discrepancy_account_id      UUID          NULL,
  director_account_id         UUID          NULL,
  cash_sale_contact_id        UUID          NULL,
  director_contact_id         UUID          NULL,
  discrepancy_contact_id      UUID          NULL,
  created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT entity_pettycash_settings_pkey PRIMARY KEY (entity_id),
  CONSTRAINT fk_eps_entity        FOREIGN KEY (entity_id)                   REFERENCES pettycashv3.entities (id)          ON DELETE CASCADE,
  CONSTRAINT fk_eps_pettycash_acct FOREIGN KEY (pettycash_account_id)       REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_bank_acct      FOREIGN KEY (bank_account_id)            REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_acct  FOREIGN KEY (cash_sale_account_id)       REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_bank_acct FOREIGN KEY (discrepancy_bank_account_id) REFERENCES pettycashv3.account_info (id)     ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_acct      FOREIGN KEY (discrepancy_account_id)     REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_acct  FOREIGN KEY (director_account_id)        REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_ct    FOREIGN KEY (cash_sale_contact_id)       REFERENCES pettycashv3.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_ct    FOREIGN KEY (director_contact_id)        REFERENCES pettycashv3.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_ct        FOREIGN KEY (discrepancy_contact_id)     REFERENCES pettycashv3.xero_contact_sync (id) ON DELETE SET NULL
);

CREATE TABLE pettycashv3.cash_info (
  id          UUID                  NOT NULL DEFAULT gen_random_uuid(),
  currency_id UUID                  NOT NULL,
  type        pettycashv3.cash_type NULL,
  cash_value  NUMERIC(12,2)         NOT NULL,
  cash_name   VARCHAR(20)           NULL,
  description TEXT                  NULL,
  is_active     BOOLEAN             NOT NULL DEFAULT TRUE,
  display_order INTEGER             NOT NULL DEFAULT 0,
  CONSTRAINT cash_info_pkey PRIMARY KEY (id),
  CONSTRAINT cash_info_currency_value_key UNIQUE (currency_id, cash_value),
  CONSTRAINT fk_cash_currency FOREIGN KEY (currency_id) REFERENCES pettycashv3.currency_info (id) ON DELETE RESTRICT
);

CREATE TABLE pettycashv3.entity_cash_detail (
  entity_id    UUID                  NOT NULL,
  cash_id      UUID                  NOT NULL,
  cash_type    pettycashv3.cash_type NULL,
  cash_instock NUMERIC(14,2)         NULL,
  description  TEXT                  NULL,
  CONSTRAINT entity_cash_detail_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecd_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecd_cash   FOREIGN KEY (cash_id)   REFERENCES pettycashv3.cash_info (id) ON DELETE RESTRICT
);

CREATE TABLE pettycashv3.entity_cash_setting (
  entity_id     UUID        NOT NULL,
  cash_id       UUID        NOT NULL,
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  display_order INTEGER     NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_cash_setting_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecs_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecs_cash   FOREIGN KEY (cash_id)   REFERENCES pettycashv3.cash_info (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.sale_info (
  id            UUID              NOT NULL DEFAULT gen_random_uuid(),
  type          pettycashv3.sale_type NOT NULL DEFAULT 'other',
  sale_name     VARCHAR(80)       NOT NULL,
  value_name    VARCHAR(80)       NULL,
  display_order INTEGER           NULL,
  enabled       BOOLEAN           NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  CONSTRAINT sale_info_pkey PRIMARY KEY (id),
  CONSTRAINT sale_info_name_key UNIQUE (sale_name)
);

CREATE TABLE pettycashv3.entity_sale_setting (
  entity_id     UUID    NOT NULL,
  sale_id       UUID    NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NULL,

  CONSTRAINT entity_sale_setting_pkey PRIMARY KEY (entity_id, sale_id),
  CONSTRAINT fk_ess_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id)  ON DELETE CASCADE
);

CREATE TABLE pettycashv3.attachment (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  original_name    VARCHAR(255) NOT NULL,
  stored_name      VARCHAR(255) NOT NULL,
  file_path        TEXT         NOT NULL,
  file_extension   VARCHAR(20)  NOT NULL DEFAULT '',
  mime_type        VARCHAR(100) NOT NULL,

  file_size        BIGINT       NULL,
  storage_provider VARCHAR(50)  NOT NULL DEFAULT 's3',

  checksum_sha256  VARCHAR(128) NOT NULL DEFAULT '',
  uploaded_by      UUID         NULL,
  is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE,
  deleted_at       TIMESTAMPTZ  NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT attachment_pkey PRIMARY KEY (id)
);

CREATE TABLE pettycashv3.share_link (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID         NOT NULL,
  path_segment     VARCHAR(255) NOT NULL,
  token            TEXT         NOT NULL,
  transaction_date DATE         NOT NULL,
  expires_at       TIMESTAMPTZ  NOT NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT share_link_pkey PRIMARY KEY (id),
  CONSTRAINT share_link_path_key UNIQUE (path_segment),
  CONSTRAINT fk_share_link_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.report (
  id                        UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id                 UUID                          NOT NULL,
  transaction_date          DATE                          NOT NULL,
  next_transaction_date     DATE                          NULL,
  status                    pettycashv3.report_status     NOT NULL DEFAULT 'draft',
  publishing_status         pettycashv3.publish_status    NOT NULL DEFAULT 'unpublished',

  opening_balance           NUMERIC(14,2)                 NULL,
  cash_addition             NUMERIC(14,2)                 NULL,
  adjusted_opening_balance  NUMERIC(14,2)                 NULL,
  cashsale_total            NUMERIC(14,2)                 NULL,
  nocashsale_total          NUMERIC(14,2)                 NULL,
  total_sales               NUMERIC(14,2)                 NULL,
  expense_total             NUMERIC(14,2)                 NULL,
  bank_deposit              NUMERIC(14,2)                 NULL,
  closing_balance           NUMERIC(14,2)                 NULL,
  safe_box_balance          NUMERIC(14,2)                 NULL,

  discrepancy_amount        NUMERIC(14,2)                 NULL,
  discrepancy_type          pettycashv3.discrepancy_type  NOT NULL DEFAULT 'none',
  discrepancy_reason        VARCHAR(300)                  NULL,

  current_section           VARCHAR(20)                   NULL,
  completed_sections        JSONB                         NULL,
  xero_integrated           BOOLEAN                       NULL,

  cash_addition_type        VARCHAR(20)                   NULL,

  created_by                UUID                          NULL,
  submitted_at              TIMESTAMPTZ                   NULL,
  published_at              TIMESTAMPTZ                   NULL,
  created_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT report_pkey PRIMARY KEY (id),
  CONSTRAINT fk_report_entity  FOREIGN KEY (entity_id)  REFERENCES pettycashv3.entities (id) ON DELETE RESTRICT,
  CONSTRAINT fk_report_creator FOREIGN KEY (created_by) REFERENCES pettycashv3.user (id) ON DELETE SET NULL,
  CONSTRAINT report_entity_date_key UNIQUE (entity_id, transaction_date)
);
COMMENT ON COLUMN pettycashv3.report.status IS
  'draft→submitted→published→void. report_draft/report_v2 를 이 컬럼으로 통합';

CREATE TABLE pettycashv3.report_sale (
  id         UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id  UUID          NOT NULL,
  sale_id    UUID          NOT NULL,
  amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_sale_pkey PRIMARY KEY (id),
  CONSTRAINT report_sale_uq UNIQUE (report_id, sale_id),
  CONSTRAINT fk_rs_report FOREIGN KEY (report_id) REFERENCES pettycashv3.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rs_sale   FOREIGN KEY (sale_id)   REFERENCES pettycashv3.sale_info (id) ON DELETE RESTRICT
);

CREATE TABLE pettycashv3.report_expense (
  id           UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id    UUID          NOT NULL,
  account_id   UUID          NULL,
  contact_id   UUID          NULL,
  item         VARCHAR(150)  NULL,
  amount       NUMERIC(14,2) NOT NULL DEFAULT 0,
  remarks      VARCHAR(300)  NULL,
  description  TEXT          NULL,

  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_expense_pkey PRIMARY KEY (id),
  CONSTRAINT fk_re_report     FOREIGN KEY (report_id)     REFERENCES pettycashv3.report (id)            ON DELETE CASCADE,
  CONSTRAINT fk_re_account    FOREIGN KEY (account_id)    REFERENCES pettycashv3.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_re_contact    FOREIGN KEY (contact_id)    REFERENCES pettycashv3.xero_contact_sync (id) ON DELETE SET NULL
);

CREATE TABLE pettycashv3.report_expense_attachment (
  id                 UUID    NOT NULL DEFAULT gen_random_uuid(),
  report_expense_id  UUID    NOT NULL,
  attachment_id      UUID    NOT NULL,
  attachment_role    pettycashv3.expense_attachment_role NOT NULL DEFAULT 'receipt',
  sort_order         INTEGER NOT NULL DEFAULT 0,

  xero_attachment_id VARCHAR(36) NOT NULL DEFAULT '',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT report_expense_attachment_pkey PRIMARY KEY (id),

  CONSTRAINT uq_rea_expense_attachment UNIQUE (report_expense_id, attachment_id),
  CONSTRAINT fk_rea_expense    FOREIGN KEY (report_expense_id)
      REFERENCES pettycashv3.report_expense (id) ON DELETE CASCADE,
  CONSTRAINT fk_rea_attachment FOREIGN KEY (attachment_id)
      REFERENCES pettycashv3.attachment (id)     ON DELETE CASCADE
);

CREATE TABLE pettycashv3.report_cash_count (
  id        UUID    NOT NULL DEFAULT gen_random_uuid(),
  report_id UUID    NOT NULL,
  cash_id   UUID    NOT NULL,
  quantity  INTEGER NOT NULL DEFAULT 0,

  cash_value NUMERIC(12,2) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT report_cash_count_pkey PRIMARY KEY (id),
  CONSTRAINT report_cash_count_uq UNIQUE (report_id, cash_id),
  CONSTRAINT fk_rcc_report FOREIGN KEY (report_id) REFERENCES pettycashv3.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rcc_cash   FOREIGN KEY (cash_id)   REFERENCES pettycashv3.cash_info (id) ON DELETE RESTRICT,
  CONSTRAINT chk_rcc_qty CHECK (quantity >= 0)
);

CREATE TABLE pettycashv3.report_history (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  report_id     UUID         NOT NULL,
  user_id       UUID         NULL,
  action        VARCHAR(50)  NOT NULL,
  field_changed VARCHAR(255) NULL,
  old_value     TEXT         NULL,
  new_value     TEXT         NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT report_history_pkey PRIMARY KEY (id),
  CONSTRAINT fk_rh_report FOREIGN KEY (report_id) REFERENCES pettycashv3.report (id)   ON DELETE CASCADE,
  CONSTRAINT fk_rh_user   FOREIGN KEY (user_id)   REFERENCES pettycashv3.user (id) ON DELETE SET NULL
);

CREATE TABLE pettycashv3.bill (
  id                UUID                       NOT NULL DEFAULT gen_random_uuid(),
  entity_id         UUID                       NOT NULL,
  contact_id        UUID                       NULL,
  currency_id       UUID                       NULL,
  contact_name      VARCHAR(100)               NULL,
  bill_number       VARCHAR(50)                NULL,
  reference         VARCHAR(255)               NOT NULL DEFAULT '',
  status            pettycashv3.bill_status    NOT NULL DEFAULT 'draft',
  published         pettycashv3.publish_state  NOT NULL DEFAULT 'draft',
  amount            NUMERIC(14,2)              NOT NULL DEFAULT 0,
  amount_paid       NUMERIC(14,2)              NOT NULL DEFAULT 0,
  description       TEXT                       NOT NULL DEFAULT '',
  invoice_date      DATE                       NULL,
  due_date          DATE                       NULL,
  xero_account_code VARCHAR(20)                NOT NULL DEFAULT '',
  created_by        UUID                       NULL,
  created_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT bill_pkey PRIMARY KEY (id)
);

CREATE TABLE pettycashv3.bill_line (
  id           UUID          NOT NULL DEFAULT gen_random_uuid(),
  bill_id      UUID          NOT NULL,
  description  TEXT          NOT NULL,
  quantity     NUMERIC(12,4) NOT NULL DEFAULT 1,
  unit_amount  NUMERIC(14,2) NOT NULL DEFAULT 0,
  line_amount  NUMERIC(14,2) NOT NULL DEFAULT 0,
  account_code VARCHAR(20)   NOT NULL DEFAULT '',
  account_name VARCHAR(150)  NOT NULL DEFAULT '',
  tax_type     VARCHAR(30)   NOT NULL DEFAULT '',
  sort_order   INTEGER       NOT NULL DEFAULT 0,
  note         TEXT          NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT bill_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_bl_bill FOREIGN KEY (bill_id) REFERENCES pettycashv3.bill (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.bill_attachment (
  id                 UUID                          NOT NULL DEFAULT gen_random_uuid(),
  bill_id            UUID                          NOT NULL,
  attachment_id      UUID                          NOT NULL,
  attachment_role    pettycashv3.bill_attachment_role NOT NULL DEFAULT 'other',
  sort_order         INTEGER                       NOT NULL DEFAULT 0,
  note               TEXT                          NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                   NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                  NOT NULL DEFAULT '',
  created_by         UUID                          NULL,
  created_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT bill_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_ba_bill       FOREIGN KEY (bill_id)       REFERENCES pettycashv3.bill (id)       ON DELETE CASCADE,
  CONSTRAINT fk_ba_attachment FOREIGN KEY (attachment_id) REFERENCES pettycashv3.attachment (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.payment (
  id              UUID                       NOT NULL DEFAULT gen_random_uuid(),
  bill_id         UUID                       NOT NULL,
  payment_date    DATE                       NULL,
  amount          NUMERIC(14,2)              NOT NULL DEFAULT 0,
  currency_id     UUID                       NULL,
  payment_method  VARCHAR(50)                NOT NULL DEFAULT '',
  payment_status  pettycashv3.payment_status NOT NULL DEFAULT 'pending',
  reference_no    VARCHAR(100)               NOT NULL DEFAULT '',
  note            TEXT                       NOT NULL DEFAULT '',
  xero_payment_id VARCHAR(36)                NOT NULL DEFAULT '',
  created_by      UUID                       NULL,
  created_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT payment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_payment_bill     FOREIGN KEY (bill_id)     REFERENCES pettycashv3.bill (id)          ON DELETE CASCADE
);

CREATE TABLE pettycashv3.payment_attachment (
  id                 UUID                        NOT NULL DEFAULT gen_random_uuid(),
  payment_id         UUID                        NOT NULL,
  attachment_id      UUID                        NOT NULL,
  attachment_role    pettycashv3.payment_attachment_role NOT NULL DEFAULT 'other',
  sort_order         INTEGER                     NOT NULL DEFAULT 0,
  note               TEXT                        NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                 NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                NOT NULL DEFAULT '',
  created_by         UUID                        NULL,
  created_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  CONSTRAINT payment_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_pa_payment    FOREIGN KEY (payment_id)    REFERENCES pettycashv3.payment (id)    ON DELETE CASCADE,
  CONSTRAINT fk_pa_attachment FOREIGN KEY (attachment_id) REFERENCES pettycashv3.attachment (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.bill_audit (
  id      UUID         NOT NULL DEFAULT gen_random_uuid(),
  bill_id UUID         NOT NULL,
  user_id UUID         NULL,
  action  VARCHAR(100) NOT NULL,
  detail  TEXT         NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bill_audit_pkey PRIMARY KEY (id),
  CONSTRAINT fk_audit_bill FOREIGN KEY (bill_id) REFERENCES pettycashv3.bill (id)     ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_bill_sync (
  id                     UUID                        NOT NULL DEFAULT gen_random_uuid(),
  bill_id                UUID                        NOT NULL,
  sync_direction         pettycashv3.sync_direction  NOT NULL,
  sync_type              VARCHAR(30)                 NOT NULL,
  sync_status            pettycashv3.sync_status     NOT NULL DEFAULT 'pending',
  request_type           VARCHAR(20)                 NOT NULL DEFAULT '',
  request_status         VARCHAR(30)                 NOT NULL DEFAULT '',
  request_contact_id     VARCHAR(36)                 NOT NULL DEFAULT '',
  request_invoice_number VARCHAR(100)                NOT NULL DEFAULT '',
  request_reference      VARCHAR(255)                NOT NULL DEFAULT '',
  request_invoice_date   DATE                        NULL,
  request_due_date       DATE                        NULL,
  response_invoice_id    VARCHAR(36)                 NOT NULL DEFAULT '',
  response_status        VARCHAR(30)                 NOT NULL DEFAULT '',
  response_amount_due    NUMERIC(12,2)               NULL,
  response_amount_paid   NUMERIC(12,2)               NULL,
  response_total         NUMERIC(12,2)               NULL,
  response_currency_code VARCHAR(10)                 NOT NULL DEFAULT '',
  http_status_code       INTEGER                     NULL,
  idempotency_key        VARCHAR(100)                NOT NULL DEFAULT '',

  response_invoice_number VARCHAR(100)               NOT NULL DEFAULT '',
  xero_response_id       VARCHAR(36)                 NOT NULL DEFAULT '',
  xero_provider_name     VARCHAR(100)                NOT NULL DEFAULT '',
  xero_datetime_utc      VARCHAR(100)                NOT NULL DEFAULT '',
  retry_count            INTEGER                     NOT NULL DEFAULT 0,
  last_retry_at          TIMESTAMPTZ                 NULL,
  has_errors             BOOLEAN                     NOT NULL DEFAULT FALSE,
  error_message          TEXT                        NOT NULL DEFAULT '',
  requested_by           UUID                        NULL,
  requested_at           TIMESTAMPTZ                 NULL,
  responded_at           TIMESTAMPTZ                 NULL,
  created_at             TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbs_bill    FOREIGN KEY (bill_id)      REFERENCES pettycashv3.bill (id)     ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_bill_sync_line (
  id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id     UUID          NOT NULL,
  bill_line_id          UUID          NULL,
  description           TEXT          NOT NULL DEFAULT '',
  quantity              NUMERIC(12,4) NOT NULL DEFAULT 0,
  unit_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
  line_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
  account_code          VARCHAR(20)   NOT NULL DEFAULT '',
  tax_type              VARCHAR(30)   NOT NULL DEFAULT '',
  sort_order            INTEGER       NOT NULL DEFAULT 0,
  response_line_item_id VARCHAR(36)   NOT NULL DEFAULT '',
  response_account_id   VARCHAR(36)   NOT NULL DEFAULT '',
  response_tax_amount   NUMERIC(12,2) NULL,
  created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbsl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycashv3.xero_bill_sync (id) ON DELETE CASCADE,
  CONSTRAINT fk_xbsl_line FOREIGN KEY (bill_line_id)      REFERENCES pettycashv3.bill_line (id)       ON DELETE SET NULL
);

CREATE TABLE pettycashv3.xero_bill_response_line (
  id                UUID          NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id UUID          NOT NULL,
  xero_line_item_id VARCHAR(36)   NOT NULL DEFAULT '',
  description       TEXT          NOT NULL DEFAULT '',
  quantity          NUMERIC(12,4) NOT NULL DEFAULT 0,
  unit_amount       NUMERIC(12,2) NOT NULL DEFAULT 0,
  line_amount       NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_type          VARCHAR(30)   NOT NULL DEFAULT '',
  tax_amount        NUMERIC(12,2) NOT NULL DEFAULT 0,
  account_code      VARCHAR(20)   NOT NULL DEFAULT '',
  account_id        VARCHAR(36)   NOT NULL DEFAULT '',
  validation_errors JSONB         NULL,
  created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_response_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbrl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycashv3.xero_bill_sync (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_bill_sync_payload (
  id                UUID        NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id UUID        NOT NULL,
  request_json      JSONB       NULL,
  response_json     JSONB       NULL,
  request_headers   JSONB       NULL,
  response_headers  JSONB       NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_payload_pkey PRIMARY KEY (id),
  CONSTRAINT xero_bill_sync_payload_key UNIQUE (xero_bill_sync_id),
  CONSTRAINT fk_xbsp_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycashv3.xero_bill_sync (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_bank_transaction (
  id                       UUID          NOT NULL DEFAULT gen_random_uuid(),
  sync_report_id           UUID          NULL,
  type                     VARCHAR(10)   NOT NULL,
  xero_contact_id          VARCHAR(36)   NOT NULL,
  xero_contact_name        VARCHAR(100)  NULL,
  unit_amount              NUMERIC(14,2) NOT NULL,
  quantity                 NUMERIC(12,2) NOT NULL,
  xero_account_id          VARCHAR(36)   NOT NULL,
  xero_account_code        VARCHAR(10)   NULL,
  description              TEXT          NULL,
  xero_bank_account_id     VARCHAR(36)   NOT NULL,
  xero_bank_transaction_id VARCHAR(36)   NOT NULL,
  subtotal                 NUMERIC(14,2) NULL,
  total_tax                NUMERIC(14,2) NULL,
  total                    NUMERIC(14,2) NULL,
  status                   VARCHAR(10)   NULL,
  created_at               TIMESTAMPTZ   NULL DEFAULT now(),
  CONSTRAINT xero_bank_transaction_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbt_report FOREIGN KEY (sync_report_id) REFERENCES pettycashv3.report (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_bank_transfer (
  id                       UUID          NOT NULL DEFAULT gen_random_uuid(),
  sync_report_id           UUID          NOT NULL,
  from_bank_account_id     VARCHAR(36)   NOT NULL,
  to_bank_account_id       VARCHAR(36)   NOT NULL,
  amount                   NUMERIC(14,2) NOT NULL,
  transfer_date            TIMESTAMPTZ   NOT NULL,
  xero_bank_transfer_id    VARCHAR(36)   NOT NULL,
  from_bank_transaction_id VARCHAR(36)   NOT NULL,
  to_bank_transaction_id   VARCHAR(36)   NOT NULL,
  status                   VARCHAR(10)   NULL,
  error_message            TEXT          NULL,
  created_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT xero_bank_transfer_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbtr_report FOREIGN KEY (sync_report_id) REFERENCES pettycashv3.report (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.xero_report_sync (
  id                 UUID        NOT NULL DEFAULT gen_random_uuid(),
  report_id          UUID        NOT NULL,
  sync_status        VARCHAR(20) NULL,
  reported_at        TIMESTAMPTZ NULL,
  completed_at       TIMESTAMPTZ NULL,
  xero_response_text TEXT        NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT xero_report_sync_pkey PRIMARY KEY (id),
  CONSTRAINT xero_report_sync_report_key UNIQUE (report_id),
  CONSTRAINT fk_xrs_report FOREIGN KEY (report_id) REFERENCES pettycashv3.report (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.billing_plan (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  code            VARCHAR(100) NOT NULL,
  display_name    VARCHAR(255) NOT NULL,
  amount          INTEGER      NOT NULL,
  currency        CHAR(3)      NOT NULL,
  interval_months INTEGER      NOT NULL DEFAULT 1,
  is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT billing_plan_pkey PRIMARY KEY (id),
  CONSTRAINT billing_plan_code_key UNIQUE (code),
  CONSTRAINT fk_billing_plan_currency FOREIGN KEY (currency)
      REFERENCES pettycashv3.currency_info (currency_code)
);

CREATE TABLE pettycashv3.billing_policy (
  id                      INTEGER      NOT NULL,
  trial_days              INTEGER      NOT NULL DEFAULT 30,
  paid_cancel_access_days INTEGER      NOT NULL DEFAULT 30,
  past_due_window_days    INTEGER      NOT NULL DEFAULT 15,
  retry_offsets_days      VARCHAR(100) NOT NULL DEFAULT '1,2,3,4,5,6,7,8,9,10,11,12,13',
  updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_by              VARCHAR(255) NULL,
  CONSTRAINT billing_policy_pkey PRIMARY KEY (id),
  CONSTRAINT ck_billing_policy_singleton       CHECK (id = 1),
  CONSTRAINT ck_billing_policy_trial_days      CHECK (trial_days >= 0),
  CONSTRAINT ck_billing_policy_cancel_days     CHECK (paid_cancel_access_days >= 0),
  CONSTRAINT ck_billing_policy_past_due_window CHECK (past_due_window_days >= 3),
  CONSTRAINT ck_billing_policy_retry_offsets_format
      CHECK (retry_offsets_days ~ '^[0-9]+(,[0-9]+)*$')
);

CREATE TABLE pettycashv3.payer_billing_group (
  id                       UUID         NOT NULL DEFAULT gen_random_uuid(),
  payer_user_id            UUID         NOT NULL,

  stripe_payment_method_id VARCHAR(255) NOT NULL,

  billing_email            VARCHAR(255) NULL,
  billing_company          VARCHAR(255) NULL,

  paid_through             TIMESTAMPTZ  NULL,
  dunning_started_at       TIMESTAMPTZ  NULL,
  dunning_attempts         INTEGER      NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT payer_billing_group_pkey PRIMARY KEY (id),

  CONSTRAINT fk_pbg_user FOREIGN KEY (payer_user_id) REFERENCES pettycashv3.user (id)
);

CREATE TABLE pettycashv3.billing_account_payment_method (
  id                       UUID         NOT NULL DEFAULT gen_random_uuid(),
  billing_group_id         UUID         NOT NULL,
  stripe_payment_method_id VARCHAR(255) NOT NULL,
  is_default               BOOLEAN      NOT NULL DEFAULT false,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT billing_account_payment_method_pkey PRIMARY KEY (id),
  CONSTRAINT uq_bapm_group_card UNIQUE (billing_group_id, stripe_payment_method_id),

  CONSTRAINT fk_bapm_group FOREIGN KEY (billing_group_id)
      REFERENCES pettycashv3.payer_billing_group (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entity_billing_group (
  id               UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID        NOT NULL,
  payer_user_id    UUID        NOT NULL,
  billing_group_id UUID        NOT NULL,
  source           VARCHAR(20) NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_billing_group_pkey PRIMARY KEY (id),
  CONSTRAINT uq_entity_billing_group_entity_payer UNIQUE (entity_id, payer_user_id),
  CONSTRAINT fk_ebg_entity FOREIGN KEY (entity_id)        REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ebg_user   FOREIGN KEY (payer_user_id)    REFERENCES pettycashv3.user (id),
  CONSTRAINT fk_ebg_group  FOREIGN KEY (billing_group_id) REFERENCES pettycashv3.payer_billing_group (id)
);

CREATE TABLE pettycashv3.entity_billing_consent (
  id         UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id  UUID        NOT NULL,
  user_id    UUID        NOT NULL,
  source     VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_billing_consent_pkey PRIMARY KEY (id),
  CONSTRAINT uq_entity_billing_consent_entity_user UNIQUE (entity_id, user_id),
  CONSTRAINT fk_ebcon_entity FOREIGN KEY (entity_id) REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ebcon_user   FOREIGN KEY (user_id)   REFERENCES pettycashv3.user (id)     ON DELETE CASCADE
);

CREATE TABLE pettycashv3.entity_module_subscription (
  id               UUID                              NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID                              NOT NULL,
  function_code    pettycashv3.module_code        NOT NULL,
  payer_user_id    UUID                              NOT NULL,
  phase            pettycashv3.subscription_phase NOT NULL,
  app_access_until TIMESTAMPTZ                       NULL,
  trial_end        TIMESTAMPTZ                       NULL,
  first_billed_at  TIMESTAMPTZ                       NULL,
  billed_through   TIMESTAMPTZ                       NULL,
  extension_amount INTEGER                           NULL,
  extension_state  pettycashv3.extension_state    NULL,
  created_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  CONSTRAINT entity_module_subscription_pkey PRIMARY KEY (id),
  CONSTRAINT uq_ems_entity_code UNIQUE (entity_id, function_code),
  CONSTRAINT fk_ems_entity FOREIGN KEY (entity_id)     REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ems_user   FOREIGN KEY (payer_user_id) REFERENCES pettycashv3.user (id)     ON DELETE CASCADE
);

CREATE TABLE pettycashv3.user_stripe_customer (
  id                 UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id            UUID         NOT NULL,
  stripe_customer_id VARCHAR(255) NOT NULL,
  anchor_at          TIMESTAMPTZ  NULL,
  currency           CHAR(3)      NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT user_stripe_customer_pkey PRIMARY KEY (id),
  CONSTRAINT user_stripe_customer_user_key   UNIQUE (user_id),
  CONSTRAINT user_stripe_customer_stripe_key UNIQUE (stripe_customer_id),
  CONSTRAINT fk_usc_user     FOREIGN KEY (user_id)  REFERENCES pettycashv3.user (id) ON DELETE CASCADE,
  CONSTRAINT fk_usc_currency FOREIGN KEY (currency) REFERENCES pettycashv3.currency_info (currency_code)
);

CREATE TABLE pettycashv3.subscription_invoice (
  id                 UUID         NOT NULL DEFAULT gen_random_uuid(),
  payer_user_id      UUID         NOT NULL,
  billing_group_id   UUID         NULL,
  stripe_customer_id VARCHAR(255) NULL,
  external_id        VARCHAR(255) NULL,
  period_start       TIMESTAMPTZ  NOT NULL,
  period_end         TIMESTAMPTZ  NOT NULL,
  currency           CHAR(3)      NOT NULL,
  total              INTEGER      NOT NULL DEFAULT 0,
  status             VARCHAR(20)  NOT NULL,
  memo               VARCHAR(500) NULL,
  payment_method     VARCHAR(100) NULL,
  hosted_invoice_url VARCHAR(500) NULL,

  idempotency_key    VARCHAR(255) NULL,
  issued_at          TIMESTAMPTZ  NULL,
  paid_at            TIMESTAMPTZ  NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_invoice_pkey PRIMARY KEY (id),
  CONSTRAINT fk_si_user     FOREIGN KEY (payer_user_id)    REFERENCES pettycashv3.user (id),
  CONSTRAINT fk_si_group    FOREIGN KEY (billing_group_id) REFERENCES pettycashv3.payer_billing_group (id) ON DELETE SET NULL,
  CONSTRAINT fk_si_currency FOREIGN KEY (currency)         REFERENCES pettycashv3.currency_info (currency_code)
);

CREATE TABLE pettycashv3.subscription_invoice_line (
  id           UUID         NOT NULL DEFAULT gen_random_uuid(),
  invoice_id   UUID         NOT NULL,
  entity_id    UUID         NOT NULL,
  entity_name  VARCHAR(255) NOT NULL,
  product_name VARCHAR(255) NOT NULL,
  amount       INTEGER      NOT NULL,
  kind         VARCHAR(20)  NOT NULL DEFAULT 'full',
  at           TIMESTAMPTZ  NULL,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_invoice_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_sil_invoice FOREIGN KEY (invoice_id) REFERENCES pettycashv3.subscription_invoice (id) ON DELETE CASCADE,
  CONSTRAINT fk_sil_entity  FOREIGN KEY (entity_id)  REFERENCES pettycashv3.entities (id)
);

CREATE TABLE pettycashv3.subscription_transfer (
  id                      UUID                            NOT NULL DEFAULT gen_random_uuid(),
  entity_id               UUID                            NOT NULL,
  from_user_id            UUID                            NOT NULL,
  to_user_id              UUID                            NOT NULL,
  status                  pettycashv3.transfer_status  NOT NULL,
  created_at              TIMESTAMPTZ                     NOT NULL DEFAULT now(),
  expires_at              TIMESTAMPTZ                     NOT NULL,
  responded_at            TIMESTAMPTZ                     NULL,
  accepted_billed_through TIMESTAMPTZ                     NULL,
  accepted_anchor_at      TIMESTAMPTZ                     NULL,
  quoted_amount           INTEGER                         NULL,
  quoted_currency         CHAR(3)                         NULL,
  charge_attempt          INTEGER                         NOT NULL DEFAULT 0,
  charge_key              VARCHAR(120)                    NULL,
  charge_invoice_id       VARCHAR(64)                     NULL,

  collect_at              TIMESTAMPTZ                     NULL,

  outcome_seen_at         TIMESTAMPTZ                     NULL,
  note                    VARCHAR(500)                    NULL,
  CONSTRAINT subscription_transfer_pkey PRIMARY KEY (id),
  CONSTRAINT fk_st_entity FOREIGN KEY (entity_id)    REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_st_from   FOREIGN KEY (from_user_id) REFERENCES pettycashv3.user (id),
  CONSTRAINT fk_st_to     FOREIGN KEY (to_user_id)   REFERENCES pettycashv3.user (id)
);

CREATE TABLE pettycashv3.subscription_audit_log (
  id               UUID                              NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID                              NOT NULL,
  function_code    pettycashv3.module_code        NOT NULL,
  payer_user_id    UUID                              NOT NULL,
  actor_user_id    UUID                              NULL,
  action           VARCHAR(40)                       NOT NULL,
  phase_before     pettycashv3.subscription_phase NULL,
  phase_after      pettycashv3.subscription_phase NULL,
  app_access_until TIMESTAMPTZ                       NULL,
  extension_amount INTEGER                           NULL,
  extension_state  pettycashv3.extension_state    NULL,
  outcome          pettycashv3.audit_outcome      NOT NULL,
  cancel_reason    VARCHAR(500)                      NULL,
  note             VARCHAR(500)                      NULL,
  payer_before     UUID                              NULL,
  payer_after      UUID                              NULL,
  created_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  CONSTRAINT subscription_audit_log_pkey PRIMARY KEY (id),
  CONSTRAINT fk_sal_entity FOREIGN KEY (entity_id)     REFERENCES pettycashv3.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_sal_payer  FOREIGN KEY (payer_user_id) REFERENCES pettycashv3.user (id),
  CONSTRAINT fk_sal_actor  FOREIGN KEY (actor_user_id) REFERENCES pettycashv3.user (id) ON DELETE SET NULL
);

CREATE TABLE pettycashv3.subscription_email_log (
  id         UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id    UUID         NOT NULL,
  event      VARCHAR(40)  NOT NULL,
  dedupe_key VARCHAR(200) NOT NULL,
  recipient  VARCHAR(200) NULL,
  status     VARCHAR(20)  NOT NULL,
  error      VARCHAR(500) NULL,
  created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_email_log_pkey PRIMARY KEY (id),
  CONSTRAINT uq_sub_email_event_key UNIQUE (event, dedupe_key),
  CONSTRAINT fk_sel_user FOREIGN KEY (user_id) REFERENCES pettycashv3.user (id) ON DELETE CASCADE
);

CREATE TABLE pettycashv3.terms_consent (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id       UUID         NOT NULL,
  terms_version VARCHAR(32)  NOT NULL,
  document_hash VARCHAR(64)  NOT NULL,
  accepted_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  source        VARCHAR(32)  NOT NULL,
  ip_address    VARCHAR(45)  NULL,
  user_agent    VARCHAR(512) NULL,
  CONSTRAINT terms_consent_pkey PRIMARY KEY (id),
  CONSTRAINT uq_terms_consent_user_version UNIQUE (user_id, terms_version),
  CONSTRAINT fk_tc_user FOREIGN KEY (user_id) REFERENCES pettycashv3.user (id) ON DELETE CASCADE
);

DO $$DECLARE t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'currency_info','user','user_token','role','permission',
      'entities','account_info','entity_bill_account_xero','entity_bill_currency',
      'xero_contact_sync','entity_function','entity_function_map','entity_pettycash_settings',
      'sale_info','attachment','report','bill','bill_line','bill_attachment',
      'payment','payment_attachment','xero_bill_sync','xero_bill_sync_payload',
      'xero_report_sync','xero_bank_transfer',

      'entity_cash_setting','billing_plan','billing_policy','payer_billing_group',
      'entity_billing_group','billing_account_payment_method',
      'entity_module_subscription','user_stripe_customer',
      'subscription_invoice'
    ])
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_updated BEFORE UPDATE ON pettycashv3.%1$I
         FOR EACH ROW EXECUTE FUNCTION pettycashv3.set_updated_at();', t);
  END LOOP;
END
$$;

CREATE INDEX idx_country_currency         ON pettycashv3.country_info (currency_id);
CREATE INDEX idx_user_token_user          ON pettycashv3.user_token (user_id);
CREATE INDEX idx_entities_country_cur     ON pettycashv3.entities (country_code, currency_id);
CREATE INDEX idx_entities_conn_user       ON pettycashv3.entities (connected_by_user_id);
CREATE INDEX idx_user_entity_entity       ON pettycashv3.user_entity (entity_id);
CREATE INDEX idx_invitation_entity        ON pettycashv3.invitation (entity_id);
CREATE INDEX idx_email_otp_email          ON pettycashv3.email_otp (email);
CREATE INDEX idx_account_entity           ON pettycashv3.account_info (entity_id);
CREATE INDEX idx_eax_account              ON pettycashv3.entity_account_xero (account_id);
CREATE INDEX idx_ebax_entity              ON pettycashv3.entity_bill_account_xero (entity_id);
CREATE INDEX idx_ebc_entity               ON pettycashv3.entity_bill_currency (entity_id);
CREATE INDEX idx_xero_contact_entity      ON pettycashv3.xero_contact_sync (entity_id);
CREATE INDEX idx_cash_currency            ON pettycashv3.cash_info (currency_id);
CREATE INDEX idx_ess_sale                 ON pettycashv3.entity_sale_setting (sale_id);
CREATE INDEX idx_sale_info_type           ON pettycashv3.sale_info (type);
CREATE INDEX idx_attachment_uploader      ON pettycashv3.attachment (uploaded_by);
CREATE INDEX idx_report_sale_report       ON pettycashv3.report_sale (report_id);
CREATE INDEX idx_report_expense_report    ON pettycashv3.report_expense (report_id);
CREATE INDEX idx_rea_expense              ON pettycashv3.report_expense_attachment (report_expense_id);
CREATE INDEX idx_rea_attachment           ON pettycashv3.report_expense_attachment (attachment_id);
CREATE INDEX idx_report_cash_count_report ON pettycashv3.report_cash_count (report_id);
CREATE INDEX idx_report_history_report    ON pettycashv3.report_history (report_id);
CREATE INDEX idx_bill_line_bill           ON pettycashv3.bill_line (bill_id);
CREATE INDEX idx_bill_attachment_bill     ON pettycashv3.bill_attachment (bill_id);
CREATE INDEX idx_payment_bill             ON pettycashv3.payment (bill_id);
CREATE INDEX idx_payment_attachment_pay   ON pettycashv3.payment_attachment (payment_id);
CREATE INDEX idx_bill_audit_bill          ON pettycashv3.bill_audit (bill_id);
CREATE INDEX idx_xbs_bill                 ON pettycashv3.xero_bill_sync (bill_id);
CREATE INDEX idx_xbsl_sync                ON pettycashv3.xero_bill_sync_line (xero_bill_sync_id);
CREATE INDEX idx_xbrl_sync                ON pettycashv3.xero_bill_response_line (xero_bill_sync_id);
CREATE INDEX idx_xbt_report               ON pettycashv3.xero_bank_transaction (sync_report_id);
CREATE INDEX idx_xbtr_report              ON pettycashv3.xero_bank_transfer (sync_report_id);

CREATE INDEX idx_ecs_entity               ON pettycashv3.entity_cash_setting (entity_id);
CREATE INDEX idx_ecs_cash                 ON pettycashv3.entity_cash_setting (cash_id);
CREATE INDEX idx_pbg_user                 ON pettycashv3.payer_billing_group (payer_user_id);
CREATE INDEX idx_bapm_group                ON pettycashv3.billing_account_payment_method (billing_group_id);
CREATE INDEX idx_ebg_entity               ON pettycashv3.entity_billing_group (entity_id);
CREATE INDEX idx_ebg_group                ON pettycashv3.entity_billing_group (billing_group_id);
CREATE INDEX idx_ebcon_entity             ON pettycashv3.entity_billing_consent (entity_id);
CREATE INDEX idx_ems_entity               ON pettycashv3.entity_module_subscription (entity_id);
CREATE INDEX idx_ems_payer                ON pettycashv3.entity_module_subscription (payer_user_id);
CREATE INDEX idx_si_payer                 ON pettycashv3.subscription_invoice (payer_user_id);
CREATE INDEX idx_si_group                 ON pettycashv3.subscription_invoice (billing_group_id);
CREATE INDEX idx_sil_invoice              ON pettycashv3.subscription_invoice_line (invoice_id);
CREATE INDEX idx_sil_entity               ON pettycashv3.subscription_invoice_line (entity_id);
CREATE INDEX idx_st_entity                ON pettycashv3.subscription_transfer (entity_id);
CREATE INDEX idx_sal_entity               ON pettycashv3.subscription_audit_log (entity_id);
CREATE INDEX idx_sel_user                 ON pettycashv3.subscription_email_log (user_id);
CREATE INDEX idx_tc_user                  ON pettycashv3.terms_consent (user_id);
CREATE INDEX idx_entities_last_user       ON pettycashv3.entities (last_accessed_by_user_id);

CREATE INDEX idx_ems_access_until         ON pettycashv3.entity_module_subscription (app_access_until);
CREATE INDEX idx_ems_billed_through       ON pettycashv3.entity_module_subscription (billed_through);
CREATE INDEX idx_pbg_paid_through         ON pettycashv3.payer_billing_group (paid_through);

CREATE UNIQUE INDEX uq_bapm_one_default
    ON pettycashv3.billing_account_payment_method (billing_group_id)
 WHERE is_default;

CREATE UNIQUE INDEX idx_st_entity_open    ON pettycashv3.subscription_transfer (entity_id)
  WHERE status IN ('pending','charging','charged');

CREATE INDEX ix_subscription_transfer_collect
    ON pettycashv3.subscription_transfer (collect_at)
 WHERE collect_at IS NOT NULL;

CREATE UNIQUE INDEX idx_si_idempotency_key
  ON pettycashv3.subscription_invoice (idempotency_key);

CREATE INDEX idx_efm_entity_covering
  ON pettycashv3.entity_function_map (entity_id) INCLUDE (entity_function_id, is_enabled);
CREATE INDEX idx_report_entity_txndate
  ON pettycashv3.report (entity_id, transaction_date DESC);
CREATE INDEX idx_report_entity_published
  ON pettycashv3.report (entity_id, transaction_date DESC)
  WHERE publishing_status = 'completed';
CREATE INDEX idx_bill_entity_covering
  ON pettycashv3.bill (entity_id) INCLUDE (status, published, created_at, updated_at);
CREATE INDEX idx_bill_entity_published
  ON pettycashv3.bill (entity_id, updated_at DESC)
  WHERE published = 'published';

CREATE VIEW pettycashv3.report_cash_summary AS
SELECT r.id                                      AS report_id,
       c.total                                   AS actual_cash_total,
       c.total + COALESCE(r.safe_box_balance, 0) AS cash_balance
  FROM pettycashv3.report r
  LEFT JOIN (SELECT report_id,
                    SUM(quantity * cash_value) AS total
               FROM pettycashv3.report_cash_count
              GROUP BY report_id) c
    ON c.report_id = r.id;

COMMENT ON VIEW pettycashv3.report_cash_summary IS
  'Replaces report.actual_cash_total. NULL actual_cash_total means the report '
  'was never cash-counted, which is not the same as counting zero.';

CREATE VIEW pettycashv3.tracker AS
SELECT e.name AS "entities.name",
       e.id   AS entity_id,
       EXISTS (SELECT 1 FROM pettycashv3.entity_function_map efm
                JOIN pettycashv3.entity_function ef ON ef.id = efm.entity_function_id
               WHERE efm.entity_id = e.id AND ef.function_code = 'PETTY_CASH' AND efm.is_enabled) AS pettycash,
       EXISTS (SELECT 1 FROM pettycashv3.entity_function_map efm
                JOIN pettycashv3.entity_function ef ON ef.id = efm.entity_function_id
               WHERE efm.entity_id = e.id AND ef.function_code = 'PAYMENT_REQUEST' AND efm.is_enabled) AS billing,
       rpt.pc_latest_submitted,
       rpt.pc_latest_published,
       bil.num_paid, bil.num_partialpaid, bil.num_unpaid, bil.num_published,
       bil.latest_bill_published, bil.latest_bill_update
  FROM pettycashv3.entities e
  LEFT JOIN LATERAL (
        SELECT max(r.transaction_date) AS pc_latest_submitted,
               max(r.transaction_date) FILTER (WHERE r.publishing_status = 'completed') AS pc_latest_published
          FROM pettycashv3.report r
         WHERE r.entity_id = e.id) rpt ON true
  LEFT JOIN LATERAL (
        SELECT count(*) FILTER (WHERE b.status = 'paid')            AS num_paid,
               count(*) FILTER (WHERE b.status = 'partially_paid')  AS num_partialpaid,
               count(*) FILTER (WHERE b.status = 'submitted')       AS num_unpaid,
               count(*) FILTER (WHERE b.published = 'published')    AS num_published,
               max(b.updated_at) FILTER (WHERE b.published = 'published') AS latest_bill_published,
               greatest(max(b.updated_at), max(b.created_at))       AS latest_bill_update
          FROM pettycashv3.bill b
         WHERE b.entity_id = e.id) bil ON true;
