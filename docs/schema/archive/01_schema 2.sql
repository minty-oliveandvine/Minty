-- ==================================================================
--  ★ 이 스크립트가 생성하는 스키마 이름:  pettycash_test
--
--  ▸ 다른 이름으로 만들고 싶다면 아래 둘 중 하나:
--
--    (A) 에디터에서 "전체 바꾸기" (Ctrl+H)
--          pettycash_test  →  원하는_이름
--        · 이 파일의 pettycash_test 는 100% 대상 스키마만 가리키므로
--          단순 문자열 치환이 안전합니다(다른 식별자에 섞여 있지 않음).
--        · pettycashv2 는 "원본" 스키마입니다. 절대 바꾸지 마세요.
--        · 02_data_foundation.sql / 03_data_reports.sql 도 같은 이름을
--          참조하므로 반드시 같이 바꿔야 합니다(각 24곳 / 64곳).
--
--    (B) 헬퍼 스크립트로 이름만 바꾼 사본 생성 (권장, 원본 보존)
--          powershell -File .\rename_schema.ps1 -To pettycash_dev
--        → .\out\pettycash_dev\ 아래에 01/02/03 이 새 이름으로 생성됨
--
--  ▸ 스키마 이름 규칙: 소문자/숫자/밑줄, 첫 글자는 문자 또는 밑줄
--    (따옴표 없이 쓸 수 있어야 하므로 하이픈·공백·대문자 금지)
-- ==================================================================

-- Auto-generated from Downloads/pettycashv2_full_schema.sql
-- Target schema: pettycash_test (underscore => valid unquoted identifier)
-- Transforms applied vs the source file:
--   * schema pettycashv2 -> pettycash_test
--   * ENUM block uncommented (source had it inside /* ... */)
--   * app_user -> user (source left app_user commented but FKs referenced it)
--   * removed destructive "DROP SCHEMA pettycashv2 CASCADE"
-- Safe to run against a database that still holds the live pettycashv2 schema:
-- it only creates the new pettycash_test schema and never touches pettycashv2.

DROP SCHEMA IF EXISTS pettycash_test CASCADE;
CREATE SCHEMA pettycash_test;

-- ==================================================================
--  pettycashv2  전체 재설계 DDL  (Consolidated Redesign)
--  기준 파일: prestaging_table_08_jul_2026.sql (50+ 테이블 분석)
--
--  주요 재설계 원칙 (DBA)
--   1) draft/v2 제거: report/report_draft/report_v2 → report(status 상태머신)
--                     report_cashcount_draft → report_cash_count(권종 정규화)
--                     shop_expense_draft     → report_expense
--                     report_history_*        → report_history
--   2) 판매채널 정규화: report의 *_sales 컬럼(~18개) → sale_info + report_sale
--                     sale_info.type = electric / delivery / cash / other
--   3) 타입 표준화: varchar(36) → uuid,  double precision(금액) → numeric,
--                  timestamp → timestamptz,  상태값 → enum
--   4) 토큰 분리: user(신원) → app_user + user_token(OAuth 1:1)
--   5) 오타 교정: "desc", sync_statuc, xero_reponse_text, xero_organiztion_id ...
--   6) Django 프레임워크 테이블(auth_*, django_*, sessions)은 재설계 대상에서
--      제외(프레임워크 마이그레이션 관리) → 커스텀 role/permission/app_user 로 일원화
--  Target: PostgreSQL 14+
-- ==================================================================

-- gen_random_uuid(): PG13+ 내장. 구버전이면 아래 주석 해제
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==========================================
-- 0. Clean up
-- ==========================================

-- ==========================================
-- 1. 공통 트리거 함수 (updated_at 자동 갱신)
-- ==========================================
CREATE OR REPLACE FUNCTION pettycash_test.set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ==========================================
-- 2. ENUM 타입
-- ==========================================
-- entity_status: actual source values are onboarding / connected / disconnected
-- only (no 'active'), so the enum mirrors them and migration is identity.
CREATE TYPE pettycash_test.entity_status     AS ENUM ('onboarding','connected','disconnected');
CREATE TYPE pettycash_test.system_role       AS ENUM ('normal','admin','superadmin');
-- entity_role: kept as the app's existing 6-level hierarchy (matches ROLE_RANK
-- in services/permission_policy.py) rather than the redesign's owner/admin/
-- member/viewer, so existing user_entity.role / invitation.role values migrate
-- without a lossy remap. Values are ordered low->high privilege.
CREATE TYPE pettycash_test.entity_role       AS ENUM ('entity_base','cashier','shop_manager','accountant','admin','super_admin');
CREATE TYPE pettycash_test.invitation_status AS ENUM ('pending','accepted','expired','revoked');
CREATE TYPE pettycash_test.report_status     AS ENUM ('draft','submitted','published','void');
CREATE TYPE pettycash_test.publish_status    AS ENUM ('unpublished','publishing','completed','failed');
CREATE TYPE pettycash_test.discrepancy_type  AS ENUM ('none','over','short');
CREATE TYPE pettycash_test.sale_type         AS ENUM ('electric','delivery','other');  -- ★ 요청 반영
CREATE TYPE pettycash_test.cash_type         AS ENUM ('coin','note');
CREATE TYPE pettycash_test.bill_status       AS ENUM ('draft','submitted','partially_paid','paid','void');
CREATE TYPE pettycash_test.publish_state     AS ENUM ('draft','published');
CREATE TYPE pettycash_test.payment_status    AS ENUM ('pending','partial','completed','failed');
CREATE TYPE pettycash_test.sync_status       AS ENUM ('pending','processing','success','failed');
CREATE TYPE pettycash_test.sync_direction    AS ENUM ('push','pull');
CREATE TYPE pettycash_test.attachment_role   AS ENUM ('receipt','invoice','proof','other');


-- ==================================================================
--  A. 마스터 / 레퍼런스
-- ==================================================================

-- 2.1 currency_info
CREATE TABLE pettycash_test.currency_info (
  id             UUID          NOT NULL DEFAULT gen_random_uuid(),
  currency_code  CHAR(3)       NOT NULL,           -- ISO 4217 (구 iso_code)
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

-- 2.2 country_info
CREATE TABLE pettycash_test.country_info (
  country_code    CHAR(2)       NOT NULL,
  alpha3_code     CHAR(3)       NULL,     -- relaxed: source country_info has no alpha3 column
  country_name_en VARCHAR(100)  NOT NULL,
  currency_id     UUID          NULL,
  phone_code      VARCHAR(10)   NULL,
  is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
  display_order   INTEGER       NOT NULL DEFAULT 999,
  CONSTRAINT country_info_pkey PRIMARY KEY (country_code),
  CONSTRAINT fk_country_currency FOREIGN KEY (currency_id)
      REFERENCES pettycash_test.currency_info (id) ON DELETE SET NULL,
  CONSTRAINT chk_country_code_len CHECK (length(country_code) = 2),
  CONSTRAINT chk_alpha3_code_len  CHECK (alpha3_code IS NULL OR length(alpha3_code) = 3)
);


-- ==================================================================
--  B. 사용자 / 권한  (Django auth_* 대체 → app_user/role/permission 일원화)
-- ==================================================================

-- 2.3 app_user  (구 user + auth_user 통합, 토큰은 user_token 으로 분리)
/*
CREATE TABLE pettycash_test.user (
  id                 UUID                     NOT NULL DEFAULT gen_random_uuid(),
  username           VARCHAR(150)             NOT NULL,
  email              VARCHAR(254)             NULL,
  password_hash      VARCHAR(255)             NOT NULL,
  first_name         VARCHAR(150)             NOT NULL DEFAULT '',
  last_name          VARCHAR(150)             NOT NULL DEFAULT '',
  user_phone         VARCHAR(20)              NULL,
  --system_role        pettycash_test.system_role  NOT NULL DEFAULT 'normal',
  is_active          BOOLEAN                  NOT NULL DEFAULT TRUE,
  approved           BOOLEAN                  NOT NULL DEFAULT FALSE,
  xero_user_id       UUID                     NULL,
  xero_email         VARCHAR(100)             NULL,
  reset_token        VARCHAR(100)             NULL,
  reset_token_expiry TIMESTAMPTZ              NULL,
  last_login         TIMESTAMPTZ              NULL,
  created_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  CONSTRAINT app_user_pkey PRIMARY KEY (id),
  CONSTRAINT app_user_username_key UNIQUE (username),
  CONSTRAINT app_user_email_key    UNIQUE (email),
  CONSTRAINT app_user_xero_email_key UNIQUE (xero_email)
);
*/
CREATE TABLE pettycash_test.user (
  id                 UUID                     NOT NULL DEFAULT gen_random_uuid(),
  username           VARCHAR(150)             NOT NULL,
  email              VARCHAR(254)             NULL,   -- migrated = username value (per decision)
  password      VARCHAR(255)             NOT NULL,
  first_name         VARCHAR(150)             NOT NULL DEFAULT '',
  last_name          VARCHAR(150)             NOT NULL DEFAULT '',
  user_phone         VARCHAR(20)              NULL,
  --system_role        pettycash_test.system_role  NOT NULL DEFAULT 'normal',
  is_active          BOOLEAN                  NOT NULL DEFAULT TRUE,
  approved           BOOLEAN                  NOT NULL DEFAULT FALSE,
  xero_user_id       UUID                     NULL,
  xero_email         VARCHAR(100)             NULL,
  last_login         TIMESTAMPTZ              NULL,
  created_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  CONSTRAINT user_pkey PRIMARY KEY (id),
  CONSTRAINT user_username_key UNIQUE (username)
 );
-- 2.4 user_token  (OAuth 토큰 1:1 분리 — 구 user 내장 토큰 + user_token 통합)
CREATE TABLE pettycash_test.user_token (
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
      REFERENCES pettycash_test.user (id) ON DELETE CASCADE
);

-- 2.5 role
CREATE TABLE pettycash_test.role (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT role_pkey PRIMARY KEY (id),
  CONSTRAINT role_name_key UNIQUE (name)
);

-- 2.6 permission
CREATE TABLE pettycash_test.permission (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  code        VARCHAR(100) NOT NULL,
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT permission_pkey PRIMARY KEY (id),
  CONSTRAINT permission_code_key UNIQUE (code)
);

-- 2.7 role_permission (M:N)
CREATE TABLE pettycash_test.role_permission (
  role_id       UUID NOT NULL,
  permission_id UUID NOT NULL,
  CONSTRAINT role_permission_pkey PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role       FOREIGN KEY (role_id)       REFERENCES pettycash_test.role (id)       ON DELETE CASCADE,
  CONSTRAINT fk_rp_permission FOREIGN KEY (permission_id) REFERENCES pettycash_test.permission (id) ON DELETE CASCADE
);


-- ==================================================================
--  C. 엔티티 / 회원 / 초대
-- ==================================================================

-- 2.8 entities  (구 entities 컬럼 보강 + 타입 정비)
CREATE TABLE pettycash_test.entities (
  id                    UUID                      NOT NULL DEFAULT gen_random_uuid(),
  country_code          CHAR(2)                   NULL,   -- relaxed: onboarding entities may have no country yet
  currency_id           UUID                      NULL,   -- relaxed: onboarding entities may have no currency yet
  name                  VARCHAR(100)              NOT NULL,
  status                pettycash_test.entity_status NOT NULL DEFAULT 'onboarding',
  --minimum_qty           INTEGER                   NULL,
  --deposit_frequency     INTEGER                   NULL,
  --deposit_day           INTEGER                   NULL,
  contact_option        VARCHAR(36)               NULL,
  currency_format       VARCHAR(30)               NULL,
  timezone              VARCHAR(30)               NULL,
  note                  TEXT                      NULL,
  xero_org_id           VARCHAR(36)               NULL,
  --xero_short_code       VARCHAR(50)               NULL,
  xero_tenant_name      VARCHAR(255)              NULL,
  --period_lock_date      DATE                      NULL,
  --end_of_year_lock_date DATE                      NULL,
  connected_by_user_id  UUID                      NULL,
  onboarding_saved_step INTEGER                   NULL DEFAULT 9,
  last_connected_at     TIMESTAMPTZ               NULL,
  created_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  CONSTRAINT entities_pkey PRIMARY KEY (id),
  CONSTRAINT fk_entities_country  FOREIGN KEY (country_code)         REFERENCES pettycash_test.country_info (country_code) ON DELETE RESTRICT,
  CONSTRAINT fk_entities_currency FOREIGN KEY (currency_id)          REFERENCES pettycash_test.currency_info (id)          ON DELETE RESTRICT,
  CONSTRAINT fk_entities_conn_user FOREIGN KEY (connected_by_user_id) REFERENCES pettycash_test.user (id)              ON DELETE RESTRICT
);

-- 2.9 user_entity  (회원 ↔ 엔티티 멤버십 + 역할)
CREATE TABLE pettycash_test.user_entity (
  user_id   UUID                    NOT NULL,
  entity_id UUID                    NOT NULL,
  role      pettycash_test.entity_role NOT NULL,
  approved  BOOLEAN                 NOT NULL DEFAULT FALSE,
  joined_at TIMESTAMPTZ             NULL,
  created_at TIMESTAMPTZ            NOT NULL DEFAULT now(),
  CONSTRAINT user_entity_pkey PRIMARY KEY (user_id, entity_id),
  CONSTRAINT fk_ue_user   FOREIGN KEY (user_id)   REFERENCES pettycash_test.user (id) ON DELETE CASCADE,
  CONSTRAINT fk_ue_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);

-- 2.10 invitation
CREATE TABLE pettycash_test.invitation (
  id         UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id  UUID                          NOT NULL,
  email      VARCHAR(150)                  NOT NULL,
  role       pettycash_test.entity_role       NOT NULL,
  token      VARCHAR(64)                   NOT NULL,
  status     pettycash_test.invitation_status NOT NULL DEFAULT 'pending',
  invited_by UUID                          NULL,
  accepted_at TIMESTAMPTZ                  NULL,
  expires_at  TIMESTAMPTZ                  NULL,
  created_at  TIMESTAMPTZ                  NOT NULL DEFAULT now(),
  CONSTRAINT invitation_pkey PRIMARY KEY (id),
  CONSTRAINT invitation_token_key UNIQUE (token),
  CONSTRAINT fk_inv_entity     FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_inv_invited_by FOREIGN KEY (invited_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.11 email_otp
CREATE TABLE pettycash_test.email_otp (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  email       VARCHAR(100) NOT NULL,
  code_hash   VARCHAR(255) NOT NULL,
  attempts    INTEGER      NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ  NOT NULL,
  verified_at TIMESTAMPTZ  NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT email_otp_pkey PRIMARY KEY (id)
);


-- ==================================================================
--  D. Xero 연동 마스터
-- ==================================================================

-- 2.12 account_info  (Xero 계정과목)
CREATE TABLE pettycash_test.account_info (
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
  CONSTRAINT fk_account_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);

-- 2.13 entity_account_xero  (account_info ↔ Xero org 매핑)
CREATE TABLE pettycash_test.entity_account_xero (
  id              UUID        NOT NULL DEFAULT gen_random_uuid(),
  account_id      UUID        NOT NULL,
  type            VARCHAR(50) NULL,
  xero_org_id     VARCHAR(36) NULL,
  xero_account_id VARCHAR(36) NULL,
  name            VARCHAR(80) NULL,
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
  CONSTRAINT entity_account_xero_pkey PRIMARY KEY (id),
  CONSTRAINT fk_eax_account FOREIGN KEY (account_id) REFERENCES pettycash_test.account_info (id) ON DELETE CASCADE
);

-- 2.14 entity_bill_account_xero  (엔티티별 청구 계정 설정 — entity FK 추가)
CREATE TABLE pettycash_test.entity_bill_account_xero (
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
  CONSTRAINT entity_bill_account_xero_pkey PRIMARY KEY (id),
  CONSTRAINT fk_ebax_entity  FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ebax_creator FOREIGN KEY (created_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.15 entity_bill_currency  (엔티티별 청구 통화 — currency FK 추가)
CREATE TABLE pettycash_test.entity_bill_currency (
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
  CONSTRAINT uq_ebc_entity_currency UNIQUE (entity_id, currency_id),
  CONSTRAINT fk_ebc_entity   FOREIGN KEY (entity_id)   REFERENCES pettycash_test.entities (id)      ON DELETE CASCADE,
  CONSTRAINT fk_ebc_currency FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info (id) ON DELETE RESTRICT,
  CONSTRAINT fk_ebc_creator  FOREIGN KEY (created_by)  REFERENCES pettycash_test.user (id)      ON DELETE SET NULL
);

-- 2.16 xero_contact_sync
CREATE TABLE pettycash_test.xero_contact_sync (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id       UUID         NULL,
  xero_contact_id VARCHAR(36)  NOT NULL,
  xero_org_id     VARCHAR(36)  NULL,
  name            VARCHAR(150) NOT NULL,
  category        VARCHAR(50)  NULL,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT xero_contact_sync_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xero_contact_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);


-- ==================================================================
--  E. 엔티티 기능 / 설정
-- ==================================================================

-- 2.17 entity_function
CREATE TABLE pettycash_test.entity_function (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  function_code VARCHAR(100) NOT NULL,
  function_name VARCHAR(150) NOT NULL,
  description   TEXT         NOT NULL DEFAULT '',
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  display_order INTEGER      NOT NULL DEFAULT 999,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT entity_function_pkey PRIMARY KEY (id),
  CONSTRAINT entity_function_code_key UNIQUE (function_code)
);

-- 2.18 entity_function_map  (복합 PK로 중복 매핑 방지 — 구 surrogate id 제거)
CREATE TABLE pettycash_test.entity_function_map (
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
  CONSTRAINT fk_efm_entity   FOREIGN KEY (entity_id)          REFERENCES pettycash_test.entities (id)        ON DELETE CASCADE,
  CONSTRAINT fk_efm_function FOREIGN KEY (entity_function_id) REFERENCES pettycash_test.entity_function (id) ON DELETE RESTRICT,
  CONSTRAINT fk_efm_creator  FOREIGN KEY (created_by)         REFERENCES pettycash_test.user (id)        ON DELETE SET NULL
);

-- 2.19 entity_pettycash_settings  (FOREIGN 누락 오류 수정 + uuid 정비)
CREATE TABLE pettycash_test.entity_pettycash_settings (
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
  CONSTRAINT fk_eps_entity        FOREIGN KEY (entity_id)                   REFERENCES pettycash_test.entities (id)          ON DELETE CASCADE,
  CONSTRAINT fk_eps_pettycash_acct FOREIGN KEY (pettycash_account_id)       REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_bank_acct      FOREIGN KEY (bank_account_id)            REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_acct  FOREIGN KEY (cash_sale_account_id)       REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_bank_acct FOREIGN KEY (discrepancy_bank_account_id) REFERENCES pettycash_test.account_info (id)     ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_acct      FOREIGN KEY (discrepancy_account_id)     REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_acct  FOREIGN KEY (director_account_id)        REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_ct    FOREIGN KEY (cash_sale_contact_id)       REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_ct    FOREIGN KEY (director_contact_id)        REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_ct        FOREIGN KEY (discrepancy_contact_id)     REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL
);


-- ==================================================================
--  F. 현금 / 판매 카탈로그
-- ==================================================================

-- 2.20 cash_info  (권종 마스터 — "desc"→description, country_code→currency_id, serial→uuid)
CREATE TABLE pettycash_test.cash_info (
  id          UUID                  NOT NULL DEFAULT gen_random_uuid(),
  currency_id UUID                  NOT NULL,
  type        pettycash_test.cash_type NULL,
  cash_value  NUMERIC(12,2)         NOT NULL,
  cash_name   VARCHAR(20)           NULL,
  description TEXT                  NULL,
  CONSTRAINT cash_info_pkey PRIMARY KEY (id),
  CONSTRAINT cash_info_currency_value_key UNIQUE (currency_id, cash_value),
  CONSTRAINT fk_cash_currency FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info (id) ON DELETE RESTRICT
);

-- 2.21 entity_cash_detail  (엔티티별 현금 재고 — 구 entity_cash_detail_v2)
CREATE TABLE pettycash_test.entity_cash_detail (
  entity_id    UUID                  NOT NULL,
  cash_id      UUID                  NOT NULL,
  cash_type    pettycash_test.cash_type NULL,
  cash_instock NUMERIC(14,2)         NULL,
  description  TEXT                  NULL,
  CONSTRAINT entity_cash_detail_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecd_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecd_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE RESTRICT
);

-- 2.22 sale_info  (판매채널 카탈로그 — ★ type: electric/delivery/cash/other)
--   구 report 의 *_sales 하드코딩 컬럼을 이 카탈로그의 행으로 정규화.
CREATE TABLE pettycash_test.sale_info (
  id            UUID              NOT NULL DEFAULT gen_random_uuid(),
  type          pettycash_test.sale_type NOT NULL DEFAULT 'other',
  sale_name     VARCHAR(80)       NOT NULL,   -- 예: 'Visa','Deliveroo','Cash'
  value_name    VARCHAR(80)       NULL,
  display_order INTEGER           NULL,
  enabled       BOOLEAN           NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  CONSTRAINT sale_info_pkey PRIMARY KEY (id),
  CONSTRAINT sale_info_name_key UNIQUE (sale_name)
);

-- 2.23 entity_sale_setting  (엔티티별 사용 판매채널 매핑)
CREATE TABLE pettycash_test.entity_sale_setting (
  entity_id     UUID    NOT NULL,
  sale_id       UUID    NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NULL,
  CONSTRAINT entity_sale_setting_pkey PRIMARY KEY (entity_id, sale_id),
  CONSTRAINT fk_ess_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ess_sale   FOREIGN KEY (sale_id)   REFERENCES pettycash_test.sale_info (id) ON DELETE RESTRICT
);


-- ==================================================================
--  G. 첨부 / 공유
-- ==================================================================

-- 2.24 attachment  (범용 파일 저장)
CREATE TABLE pettycash_test.attachment (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  original_name    VARCHAR(255) NOT NULL,
  stored_name      VARCHAR(255) NOT NULL,
  file_path        TEXT         NOT NULL,
  file_extension   VARCHAR(20)  NOT NULL DEFAULT '',
  mime_type        VARCHAR(100) NOT NULL,
  file_size        BIGINT       NOT NULL,
  storage_provider VARCHAR(50)  NOT NULL DEFAULT 's3',
  checksum_sha256  VARCHAR(128) NOT NULL DEFAULT '',
  uploaded_by      UUID         NULL,
  is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE,
  deleted_at       TIMESTAMPTZ  NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_attachment_uploader FOREIGN KEY (uploaded_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.25 share_link
CREATE TABLE pettycash_test.share_link (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID         NOT NULL,
  path_segment     VARCHAR(255) NOT NULL,
  token            TEXT         NOT NULL,
  transaction_date DATE         NOT NULL,
  expires_at       TIMESTAMPTZ  NOT NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT share_link_pkey PRIMARY KEY (id),
  CONSTRAINT share_link_path_key UNIQUE (path_segment),
  CONSTRAINT fk_share_link_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);


-- ==================================================================
--  H. 리포트  (★ report/report_draft/report_v2 → report 단일 + status)
-- ==================================================================

-- 2.26 report  (헤더. *_sales 채널 컬럼 제거 → report_sale 로 정규화)
CREATE TABLE pettycash_test.report (
  id                        UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id                 UUID                          NOT NULL,   -- 구 report.company/report_v2.entity_id
  transaction_date          DATE                          NOT NULL,
  next_transaction_date     DATE                          NULL,
  status                    pettycash_test.report_status     NOT NULL DEFAULT 'draft',
  publishing_status         pettycash_test.publish_status    NOT NULL DEFAULT 'unpublished',
  -- 잔액 요약 (double precision → numeric)
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
  -- 불일치(discrepancy)
  discrepancy_amount        NUMERIC(14,2)                 NULL,
  discrepancy_type          pettycash_test.discrepancy_type  NOT NULL DEFAULT 'none',
  discrepancy_reason        VARCHAR(300)                  NULL,
  -- 워크플로 진행 상태(구 draft 의 current_section/completed_sections 흡수)
  current_section           VARCHAR(20)                   NULL,
  completed_sections        JSONB                         NULL,
  xero_integrated           BOOLEAN                       NULL,
  created_by                UUID                          NULL,
  submitted_at              TIMESTAMPTZ                   NULL,
  published_at              TIMESTAMPTZ                   NULL,
  created_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT report_pkey PRIMARY KEY (id),
  CONSTRAINT fk_report_entity  FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id) ON DELETE RESTRICT,
  CONSTRAINT fk_report_creator FOREIGN KEY (created_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL,
  CONSTRAINT report_entity_date_key UNIQUE (entity_id, transaction_date)  -- 하루 1 리포트
);
COMMENT ON COLUMN pettycash_test.report.status IS
  'draft→submitted→published→void. report_draft/report_v2 를 이 컬럼으로 통합';

-- 2.27 report_sale  (판매채널별 매출 — 구 *_sales 컬럼 + report_sale_detail 정규화)
CREATE TABLE pettycash_test.report_sale (
  id         UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id  UUID          NOT NULL,
  sale_id    UUID          NOT NULL,
  amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_sale_pkey PRIMARY KEY (id),
  CONSTRAINT report_sale_uq UNIQUE (report_id, sale_id),
  CONSTRAINT fk_rs_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rs_sale   FOREIGN KEY (sale_id)   REFERENCES pettycash_test.sale_info (id) ON DELETE RESTRICT
);

-- 2.28 report_expense  (지출 상세 — 구 report_expense_detail + shop_expense 통합)
CREATE TABLE pettycash_test.report_expense (
  id           UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id    UUID          NOT NULL,
  account_id   UUID          NULL,
  contact_id   UUID          NULL,
  item         VARCHAR(150)  NULL,
  amount       NUMERIC(14,2) NOT NULL DEFAULT 0,
  remarks      VARCHAR(300)  NULL,
  description  TEXT          NULL,
  attachment_id UUID         NULL,
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_expense_pkey PRIMARY KEY (id),
  CONSTRAINT fk_re_report     FOREIGN KEY (report_id)     REFERENCES pettycash_test.report (id)            ON DELETE CASCADE,
  CONSTRAINT fk_re_account    FOREIGN KEY (account_id)    REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_re_contact    FOREIGN KEY (contact_id)    REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_re_attachment FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment (id)        ON DELETE SET NULL
);

-- 2.29 report_cash_count  (권종별 실사 — 구 report_cashcount_draft/report_cash_detail 정규화)
CREATE TABLE pettycash_test.report_cash_count (
  id        UUID    NOT NULL DEFAULT gen_random_uuid(),
  report_id UUID    NOT NULL,
  cash_id   UUID    NOT NULL,
  quantity  INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT report_cash_count_pkey PRIMARY KEY (id),
  CONSTRAINT report_cash_count_uq UNIQUE (report_id, cash_id),
  CONSTRAINT fk_rcc_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rcc_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE RESTRICT,
  CONSTRAINT chk_rcc_qty CHECK (quantity >= 0)
);

-- 2.30 report_history  (감사 로그 — report_history/_draft/_v2 통합)
CREATE TABLE pettycash_test.report_history (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  report_id     UUID         NOT NULL,
  user_id       UUID         NULL,
  action        VARCHAR(50)  NOT NULL,
  field_changed VARCHAR(255) NULL,
  old_value     TEXT         NULL,
  new_value     TEXT         NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT report_history_pkey PRIMARY KEY (id),
  CONSTRAINT fk_rh_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)   ON DELETE CASCADE,
  CONSTRAINT fk_rh_user   FOREIGN KEY (user_id)   REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);


-- ==================================================================
--  I. 청구서 / 결제
-- ==================================================================

-- 2.31 bill
CREATE TABLE pettycash_test.bill (
  id                UUID                       NOT NULL DEFAULT gen_random_uuid(),
  entity_id         UUID                       NOT NULL,
  contact_id        UUID                       NULL,
  currency_id       UUID                       NULL,
  contact_name      VARCHAR(100)               NULL,
  bill_number       VARCHAR(50)                NULL,
  reference         VARCHAR(255)               NOT NULL DEFAULT '',
  status            pettycash_test.bill_status    NOT NULL DEFAULT 'draft',
  published         pettycash_test.publish_state  NOT NULL DEFAULT 'draft',
  amount            NUMERIC(14,2)              NOT NULL DEFAULT 0,
  amount_paid       NUMERIC(14,2)              NOT NULL DEFAULT 0,
  description       TEXT                       NOT NULL DEFAULT '',
  invoice_date      DATE                       NULL,
  due_date          DATE                       NULL,
  xero_account_code VARCHAR(20)                NOT NULL DEFAULT '',
  created_by        UUID                       NULL,
  created_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT bill_pkey PRIMARY KEY (id),
  CONSTRAINT fk_bill_entity   FOREIGN KEY (entity_id)   REFERENCES pettycash_test.entities (id)          ON DELETE RESTRICT,
  CONSTRAINT fk_bill_contact  FOREIGN KEY (contact_id)  REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_bill_currency FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info (id)      ON DELETE RESTRICT,
  CONSTRAINT fk_bill_creator  FOREIGN KEY (created_by)  REFERENCES pettycash_test.user (id)           ON DELETE SET NULL
);

-- 2.32 bill_line  (구 bill_line_item)
CREATE TABLE pettycash_test.bill_line (
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
  CONSTRAINT fk_bl_bill FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill (id) ON DELETE CASCADE
);

-- 2.33 bill_attachment
CREATE TABLE pettycash_test.bill_attachment (
  id                 UUID                          NOT NULL DEFAULT gen_random_uuid(),
  bill_id            UUID                          NOT NULL,
  attachment_id      UUID                          NOT NULL,
  attachment_role    pettycash_test.attachment_role   NOT NULL DEFAULT 'other',
  sort_order         INTEGER                       NOT NULL DEFAULT 0,
  note               TEXT                          NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                   NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                  NOT NULL DEFAULT '',
  created_by         UUID                          NULL,
  created_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT bill_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_ba_bill       FOREIGN KEY (bill_id)       REFERENCES pettycash_test.bill (id)       ON DELETE CASCADE,
  CONSTRAINT fk_ba_attachment FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment (id) ON DELETE CASCADE,
  CONSTRAINT fk_ba_creator    FOREIGN KEY (created_by)    REFERENCES pettycash_test.user (id)   ON DELETE SET NULL
);

-- 2.34 payment
CREATE TABLE pettycash_test.payment (
  id              UUID                       NOT NULL DEFAULT gen_random_uuid(),
  bill_id         UUID                       NOT NULL,
  payment_date    DATE                       NULL,
  amount          NUMERIC(14,2)              NOT NULL DEFAULT 0,
  currency_id     UUID                       NULL,
  payment_method  VARCHAR(50)                NOT NULL DEFAULT '',
  payment_status  pettycash_test.payment_status NOT NULL DEFAULT 'pending',
  reference_no    VARCHAR(100)               NOT NULL DEFAULT '',
  note            TEXT                       NOT NULL DEFAULT '',
  xero_payment_id VARCHAR(36)                NOT NULL DEFAULT '',
  created_by      UUID                       NULL,
  created_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT payment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_payment_bill     FOREIGN KEY (bill_id)     REFERENCES pettycash_test.bill (id)          ON DELETE CASCADE,
  CONSTRAINT fk_payment_currency FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info (id) ON DELETE SET NULL,
  CONSTRAINT fk_payment_creator  FOREIGN KEY (created_by)  REFERENCES pettycash_test.user (id)      ON DELETE SET NULL
);

-- 2.35 payment_attachment
CREATE TABLE pettycash_test.payment_attachment (
  id                 UUID                        NOT NULL DEFAULT gen_random_uuid(),
  payment_id         UUID                        NOT NULL,
  attachment_id      UUID                        NOT NULL,
  attachment_role    pettycash_test.attachment_role NOT NULL DEFAULT 'other',
  sort_order         INTEGER                     NOT NULL DEFAULT 0,
  note               TEXT                        NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                 NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                NOT NULL DEFAULT '',
  created_by         UUID                        NULL,
  created_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  CONSTRAINT payment_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_pa_payment    FOREIGN KEY (payment_id)    REFERENCES pettycash_test.payment (id)    ON DELETE CASCADE,
  CONSTRAINT fk_pa_attachment FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment (id) ON DELETE CASCADE,
  CONSTRAINT fk_pa_creator    FOREIGN KEY (created_by)    REFERENCES pettycash_test.user (id)   ON DELETE SET NULL
);

-- 2.36 bill_audit  (구 audit — bill 전용 감사)
CREATE TABLE pettycash_test.bill_audit (
  id      UUID         NOT NULL DEFAULT gen_random_uuid(),
  bill_id UUID         NOT NULL,
  user_id UUID         NULL,
  action  VARCHAR(100) NOT NULL,
  detail  TEXT         NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bill_audit_pkey PRIMARY KEY (id),
  CONSTRAINT fk_audit_bill FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill (id)     ON DELETE CASCADE,
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);


-- ==================================================================
--  J. Xero 동기화 (작업/로그)
-- ==================================================================

-- 2.37 xero_bill_sync
CREATE TABLE pettycash_test.xero_bill_sync (
  id                     UUID                        NOT NULL DEFAULT gen_random_uuid(),
  bill_id                UUID                        NOT NULL,
  sync_direction         pettycash_test.sync_direction  NOT NULL,
  sync_type              VARCHAR(30)                 NOT NULL,
  sync_status            pettycash_test.sync_status     NOT NULL DEFAULT 'pending',
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
  CONSTRAINT fk_xbs_bill    FOREIGN KEY (bill_id)      REFERENCES pettycash_test.bill (id)     ON DELETE CASCADE,
  CONSTRAINT fk_xbs_req_by  FOREIGN KEY (requested_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.38 xero_bill_sync_line
CREATE TABLE pettycash_test.xero_bill_sync_line (
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
  CONSTRAINT fk_xbsl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE,
  CONSTRAINT fk_xbsl_line FOREIGN KEY (bill_line_id)      REFERENCES pettycash_test.bill_line (id)       ON DELETE SET NULL
);

-- 2.39 xero_bill_response_line
CREATE TABLE pettycash_test.xero_bill_response_line (
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
  CONSTRAINT fk_xbrl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE
);

-- 2.40 xero_bill_sync_payload
CREATE TABLE pettycash_test.xero_bill_sync_payload (
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
  CONSTRAINT fk_xbsp_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE
);

-- 2.41 xero_bank_transaction  (sync_report_id → report 로 연결)
CREATE TABLE pettycash_test.xero_bank_transaction (
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
  CONSTRAINT fk_xbt_report FOREIGN KEY (sync_report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);

-- 2.42 xero_bank_transfer
CREATE TABLE pettycash_test.xero_bank_transfer (
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
  CONSTRAINT xero_bank_transfer_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbtr_report FOREIGN KEY (sync_report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);

-- 2.43 xero_report_sync  (오타 교정: sync_statuc→sync_status, xero_reponse_text→xero_response_text)
CREATE TABLE pettycash_test.xero_report_sync (
  id                 UUID        NOT NULL DEFAULT gen_random_uuid(),
  report_id          UUID        NOT NULL,
  sync_status        VARCHAR(20) NULL,
  reported_at        TIMESTAMPTZ NULL,
  completed_at       TIMESTAMPTZ NULL,
  xero_response_text TEXT        NULL,
  CONSTRAINT xero_report_sync_pkey PRIMARY KEY (id),
  CONSTRAINT xero_report_sync_report_key UNIQUE (report_id),
  CONSTRAINT fk_xrs_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);


-- ==================================================================
--  3. updated_at 트리거 부착
-- ==================================================================
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'currency_info','country_info','user','user_token','role','permission',
      'entities','account_info','entity_bill_account_xero','entity_bill_currency',
      'xero_contact_sync','entity_function','entity_function_map','entity_pettycash_settings',
      'sale_info','attachment','report','bill','bill_line','bill_attachment',
      'payment','payment_attachment','xero_bill_sync','xero_bill_sync_payload'
    ])
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_updated BEFORE UPDATE ON pettycash_test.%1$I
         FOR EACH ROW EXECUTE FUNCTION pettycash_test.set_updated_at();', t);
  END LOOP;
END $$;


-- ==================================================================
--  4. 인덱스 (FK 지원 + tracker 뷰 최적화 + 조회 패턴)
-- ==================================================================
CREATE INDEX idx_country_currency         ON pettycash_test.country_info (currency_id);
CREATE INDEX idx_user_token_user          ON pettycash_test.user_token (user_id);
CREATE INDEX idx_entities_country_cur     ON pettycash_test.entities (country_code, currency_id);
CREATE INDEX idx_entities_conn_user       ON pettycash_test.entities (connected_by_user_id);
CREATE INDEX idx_user_entity_entity       ON pettycash_test.user_entity (entity_id);
CREATE INDEX idx_invitation_entity        ON pettycash_test.invitation (entity_id);
CREATE INDEX idx_email_otp_email          ON pettycash_test.email_otp (email);
CREATE INDEX idx_account_entity           ON pettycash_test.account_info (entity_id);
CREATE INDEX idx_eax_account              ON pettycash_test.entity_account_xero (account_id);
CREATE INDEX idx_ebax_entity              ON pettycash_test.entity_bill_account_xero (entity_id);
CREATE INDEX idx_ebc_entity               ON pettycash_test.entity_bill_currency (entity_id);
CREATE INDEX idx_xero_contact_entity      ON pettycash_test.xero_contact_sync (entity_id);
CREATE INDEX idx_cash_currency            ON pettycash_test.cash_info (currency_id);
CREATE INDEX idx_ess_sale                 ON pettycash_test.entity_sale_setting (sale_id);
CREATE INDEX idx_sale_info_type           ON pettycash_test.sale_info (type);
CREATE INDEX idx_attachment_uploader      ON pettycash_test.attachment (uploaded_by);
CREATE INDEX idx_report_sale_report       ON pettycash_test.report_sale (report_id);
CREATE INDEX idx_report_expense_report    ON pettycash_test.report_expense (report_id);
CREATE INDEX idx_report_cash_count_report ON pettycash_test.report_cash_count (report_id);
CREATE INDEX idx_report_history_report    ON pettycash_test.report_history (report_id);
CREATE INDEX idx_bill_line_bill           ON pettycash_test.bill_line (bill_id);
CREATE INDEX idx_bill_attachment_bill     ON pettycash_test.bill_attachment (bill_id);
CREATE INDEX idx_payment_bill             ON pettycash_test.payment (bill_id);
CREATE INDEX idx_payment_attachment_pay   ON pettycash_test.payment_attachment (payment_id);
CREATE INDEX idx_bill_audit_bill          ON pettycash_test.bill_audit (bill_id);
CREATE INDEX idx_xbs_bill                 ON pettycash_test.xero_bill_sync (bill_id);
CREATE INDEX idx_xbsl_sync                ON pettycash_test.xero_bill_sync_line (xero_bill_sync_id);
CREATE INDEX idx_xbrl_sync                ON pettycash_test.xero_bill_response_line (xero_bill_sync_id);
CREATE INDEX idx_xbt_report               ON pettycash_test.xero_bank_transaction (sync_report_id);
CREATE INDEX idx_xbtr_report              ON pettycash_test.xero_bank_transfer (sync_report_id);

-- tracker 뷰 전용 커버링/부분 인덱스
CREATE INDEX idx_efm_entity_covering
  ON pettycash_test.entity_function_map (entity_id) INCLUDE (entity_function_id, is_enabled);
CREATE INDEX idx_report_entity_txndate
  ON pettycash_test.report (entity_id, transaction_date DESC);
CREATE INDEX idx_report_entity_published
  ON pettycash_test.report (entity_id, transaction_date DESC)
  WHERE publishing_status = 'completed';
CREATE INDEX idx_bill_entity_covering
  ON pettycash_test.bill (entity_id) INCLUDE (status, published, created_at, updated_at);
CREATE INDEX idx_bill_entity_published
  ON pettycash_test.bill (entity_id, updated_at DESC)
  WHERE published = 'published';

-- ==================================================================
--  참고: 이전 tracker 뷰는 report.company → report.entity_id 로 바뀌었으니
--        WHERE r.company = e.id  →  WHERE r.entity_id = e.id  로 수정.
--  Django 프레임워크 테이블(auth_*, django_content_type, django_migrations,
--        sessions)은 본 스크립트에서 제외 — 프레임워크 마이그레이션이 관리.
-- ==================================================================