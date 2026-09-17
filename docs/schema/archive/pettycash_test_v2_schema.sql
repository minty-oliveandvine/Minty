-- ===========================================================================
-- pettycash_test :: the complete schema, in one file
--
-- Merged from migrations/pettycash_test/20_schema/, in dependency order:
--
--     21_schema_and_uuid7.sql   schema + the uuid7() every primary key defaults to
--     22_tables.sql             sequences and 67 tables (primary keys inline)
--     23_indexes.sql            the non-implicit indexes
--     25_constraints.sql        unique, check and foreign key constraints
--     26_views.sql              tracker
--     24_comments.sql           the defect register, as COMMENT ON
--
-- This builds an EMPTY pettycash_test. It is the schema on its own, with no
-- reference to pettycashv2 and nothing from 00_classify, 10_remediate or
-- 30_migrate - so it can be run against a fresh database, diffed, or reviewed
-- without the migration around it.
--
-- The ordering differs from run_all.sql on purpose. There, indexes and
-- constraints come after the load, because an index maintained during a bulk
-- insert costs more than one built at the end, and because the foreign keys are
-- the migration's acceptance test. With no data to load, everything can be
-- declared up front.
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/pettycash_test_v2_schema.sql
--
-- Generated from the files above. Edit those, not this - regenerate instead.
-- ===========================================================================

\set ON_ERROR_STOP on



-- ###########################################################################
-- ### 21_schema_and_uuid7.sql
-- ###########################################################################

-- ---------------------------------------------------------------------------
-- pettycash_test :: the schema, and the identifier generator it defaults to
--
-- This is the first file that touches the NEW database. Everything before it
-- read or repaired the source; nothing before it created anything here.
--
-- pettycash_test.uuid7() is deliberately a second copy of the function that also
-- lives in pettycash_migration. That one is scaffolding and gets dropped with the
-- migration schema; this one is part of the database being built - it is the
-- DEFAULT on every primary key, so it has to survive
--
--     pg_dump --schema=pettycash_test
--
-- and land in the new database with the tables that depend on it. Sharing one
-- function across both schemas would mean the dump either carried a dependency on
-- a schema that is meant to be thrown away, or silently lost its defaults.
--
-- ---------------------------------------------------------------------------
-- WHY NOT THE BUILT-IN uuidv7()
--
-- PostgreSQL 18 has a native uuidv7(). The local machine runs 18.4 and could use
-- it; Supabase runs 17.6 and cannot, and pg_uuidv7 is not among its available
-- extensions - only pgcrypto and uuid-ossp. Since the finished schema has to
-- restore onto Supabase, the function is built from pgcrypto primitives instead.
-- Verified working on Supabase 17.6: version nibble 7, RFC 9562 variant, and a
-- monotonic time prefix.
--
-- On a future all-PG18 estate the body can become `SELECT uuidv7()` with no other
-- change - the output is identical in format and ordering.
--
-- Note this copy takes NO argument: it is the default for new rows, so
-- clock_timestamp() is the right prefix. The migration copy takes a timestamp,
-- because historical rows must keep their real creation order. See
-- 00_classify/00_migration_schema.sql.
-- ---------------------------------------------------------------------------

\set ON_ERROR_STOP on

CREATE SCHEMA pettycash_test;

COMMENT ON SCHEMA pettycash_test IS
    'Normalized rebuild of pettycashv2: uuid v7 primary keys, timestamptz throughout. '
    'Column-for-column identical to pettycashv2 at z1a01_drop_payer_cycle (67 tables, '
    '656 columns) apart from those type changes and one forced nullability change on '
    'entity_bill_account_xero.created_by. Findings from the audit are attached to the '
    'objects they describe - see 24_comments.sql, or read pg_description.';

-- pgcrypto supplies gen_random_uuid(). On Supabase it is already installed; on a
-- plain Postgres 13+ gen_random_uuid() is built in, so this is a no-op there.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE FUNCTION pettycash_test.uuid7()
RETURNS uuid
LANGUAGE sql
VOLATILE
AS $$
    SELECT encode(
        set_byte(
            overlay(
                uuid_send(gen_random_uuid())
                PLACING substring(
                    int8send((floor(extract(epoch FROM clock_timestamp()) * 1000))::bigint)
                    FROM 3 FOR 6
                )
                FROM 1 FOR 6
            ),
            6,
            (get_byte(uuid_send(gen_random_uuid()), 6) & 15) | 112   -- version 7
        ),
        'hex'
    )::uuid;
$$;

COMMENT ON FUNCTION pettycash_test.uuid7() IS
    'RFC 9562 uuid version 7: 48-bit millisecond timestamp prefix then random, so keys '
    'sort by creation time and inserts land at the end of the index instead of scattering. '
    'Written against PostgreSQL 17 because Supabase has no native uuidv7(); on PG 18 the '
    'body can become SELECT uuidv7() unchanged.';


-- ###########################################################################
-- ### 22_tables.sql
-- ###########################################################################

-- --------------------------------------------------------------------------
-- pettycash_test :: tables
--
-- 67 tables, 656 columns - the same shape as pettycashv2 at
-- z1a01_drop_payer_cycle, with three deliberate differences:
--
--   1. 134 'ours' varchar(36) columns become uuid, defaulting to uuid7()
--      on primary keys. 31 'foreign' columns stay text because Xero owns
--      their format, and 1 'sentinel' column stays text because it holds
--      'system_backfill'/'entity_create' and never held an id at all.
--
--   2. All 43 naive timestamp columns become timestamptz. See
--      00_classify/02_classify_time.sql for why every one of them is UTC.
--
--   3. entity_bill_account_xero.created_by loses NOT NULL. 920 of 2853 rows
--      have no creator and were storing '' because the constraint forbade
--      the honest answer; '' has no uuid representation. This is the only
--      nullability change in the migration, and the type change forces it.
--
-- NO FOREIGN KEYS ARE DECLARED HERE. They arrive in 25_constraints.sql, after
-- the data has loaded, which is what makes load order irrelevant - and makes
-- that file the acceptance test for the whole migration. Primary keys, being
-- needed by the load itself, are declared inline.
--
-- Column order matches the source exactly, so a catalogue diff against head
-- shows type changes and nothing else.
-- --------------------------------------------------------------------------

\set ON_ERROR_STOP on


-- sequences, created before the tables whose defaults reference them

CREATE SEQUENCE pettycash_test.auth_group_id_seq;
CREATE SEQUENCE pettycash_test.auth_group_permissions_id_seq;
CREATE SEQUENCE pettycash_test.auth_permission_id_seq;
CREATE SEQUENCE pettycash_test.auth_user_groups_id_seq;
CREATE SEQUENCE pettycash_test.auth_user_id_seq;
CREATE SEQUENCE pettycash_test.auth_user_user_permissions_id_seq;
CREATE SEQUENCE pettycash_test.cash_info_cash_id_seq;
CREATE SEQUENCE pettycash_test.django_content_type_id_seq;
CREATE SEQUENCE pettycash_test.django_migrations_id_seq;
CREATE SEQUENCE pettycash_test.report_history_id_seq;
CREATE SEQUENCE pettycash_test.sessions_id_seq;

CREATE TABLE pettycash_test."account_info" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid,
    "type" character varying(50) NOT NULL,
    "name" character varying(80) NOT NULL,
    "xero_account_id" character varying(36),
    "xero_code" character varying(50),
    "status" character varying(50),
    "class_type" character varying(50),
    "bank_account_number" character varying(50),
    "bank_account_type" character varying(50),
    "description" character varying(255),
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "account_info_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."alembic_version" (
    "version_num" character varying(32) NOT NULL,
    CONSTRAINT "alembic_version_pkey" PRIMARY KEY (version_num)
);

CREATE TABLE pettycash_test."attachment" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "original_name" character varying(255) NOT NULL,
    "stored_name" character varying(255) NOT NULL,
    "file_path" text NOT NULL,
    "mime_type" character varying(100) NOT NULL,
    "file_size" bigint NOT NULL,
    "uploaded_by" uuid NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "file_extension" character varying(20) DEFAULT ''::character varying NOT NULL,
    "storage_provider" character varying(50) DEFAULT 's3'::character varying NOT NULL,
    "checksum_sha256" character varying(128) DEFAULT ''::character varying NOT NULL,
    "is_deleted" boolean DEFAULT false NOT NULL,
    "deleted_at" timestamp with time zone,
    "updated_at" timestamp with time zone NOT NULL,
    CONSTRAINT "attachment_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."audit" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "action" character varying(100) NOT NULL,
    "detail" text NOT NULL,
    "date" timestamp with time zone NOT NULL,
    "user_id" uuid NOT NULL,
    "bill_id" uuid NOT NULL,
    CONSTRAINT "audit_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_group" (
    "id" integer NOT NULL,
    "name" character varying(150) NOT NULL,
    CONSTRAINT "auth_group_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_group_permissions" (
    "id" bigint NOT NULL,
    "group_id" integer NOT NULL,
    "permission_id" integer NOT NULL,
    CONSTRAINT "auth_group_permissions_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_permission" (
    "id" integer NOT NULL,
    "name" character varying(255) NOT NULL,
    "content_type_id" integer NOT NULL,
    "codename" character varying(100) NOT NULL,
    CONSTRAINT "auth_permission_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_user" (
    "id" integer NOT NULL,
    "password" character varying(128) NOT NULL,
    "last_login" timestamp with time zone,
    "is_superuser" boolean NOT NULL,
    "username" character varying(150) NOT NULL,
    "first_name" character varying(150) NOT NULL,
    "last_name" character varying(150) NOT NULL,
    "email" character varying(254) NOT NULL,
    "is_staff" boolean NOT NULL,
    "is_active" boolean NOT NULL,
    "date_joined" timestamp with time zone NOT NULL,
    CONSTRAINT "auth_user_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_user_groups" (
    "id" bigint NOT NULL,
    "user_id" integer NOT NULL,
    "group_id" integer NOT NULL,
    CONSTRAINT "auth_user_groups_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."auth_user_user_permissions" (
    "id" bigint NOT NULL,
    "user_id" integer NOT NULL,
    "permission_id" integer NOT NULL,
    CONSTRAINT "auth_user_user_permissions_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."bill" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "contact" character varying(100) NOT NULL,
    "xero_contact_id" character varying(36) NOT NULL,
    "status" character varying(50) NOT NULL,
    "amount" numeric(10,2) NOT NULL,
    "description" text NOT NULL,
    "due_date" date,
    "invoice_date" date,
    "uploaded_by" uuid NOT NULL,
    "published" character varying(50) NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "reference" character varying(255) DEFAULT ''::character varying NOT NULL,
    "currency_code" character varying(10) DEFAULT ''::character varying NOT NULL,
    "xero_account_code" character varying(20) DEFAULT ''::character varying NOT NULL,
    CONSTRAINT "bill_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."bill_attachment" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "attachment_role" character varying(50) DEFAULT 'other'::character varying NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "note" text DEFAULT ''::text NOT NULL,
    "created_by" uuid NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "xero_attachment_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "xero_filename" character varying(255) DEFAULT ''::character varying NOT NULL,
    "bill_id" uuid NOT NULL,
    "attachment_id" uuid NOT NULL,
    CONSTRAINT "bill_attachment_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."bill_line_item" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "description" text NOT NULL,
    "bill_id" uuid NOT NULL,
    "quantity" numeric(12,4) DEFAULT 1 NOT NULL,
    "unit_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "line_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "account_code" character varying(20) DEFAULT ''::character varying NOT NULL,
    "account_name" character varying(150) DEFAULT ''::character varying NOT NULL,
    "tax_type" character varying(30) DEFAULT ''::character varying NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "note" text DEFAULT ''::text NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    CONSTRAINT "bill_line_item_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."billing_plan" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "code" character varying(100) NOT NULL,
    "display_name" character varying(255) NOT NULL,
    "amount" integer NOT NULL,
    "currency" character(3) NOT NULL,
    "interval_months" integer DEFAULT 1 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "billing_plan_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."billing_policy" (
    "id" integer NOT NULL,
    "trial_days" integer DEFAULT 30 NOT NULL,
    "paid_cancel_access_days" integer DEFAULT 30 NOT NULL,
    "past_due_window_days" integer DEFAULT 15 NOT NULL,
    "retry_offsets_days" character varying(100) DEFAULT '1,4,7,10,13'::character varying NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_by" character varying(255),
    CONSTRAINT "billing_policy_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."cash_info" (
    "cash_id" integer DEFAULT nextval('pettycash_test.cash_info_cash_id_seq'::regclass) NOT NULL,
    "country_code" character varying(3),
    "type" character varying(10),
    "cash_value" double precision,
    "cash_name" character varying(10),
    "desc" text,
    "currency_id" uuid,
    "display_order" integer DEFAULT 999 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    CONSTRAINT "cash_info_pkey" PRIMARY KEY (cash_id)
);

CREATE TABLE pettycash_test."country_info" (
    "country_code" character(2) NOT NULL,
    "alpha3_code" character(3) NOT NULL,
    "country_name_en" character varying(100) NOT NULL,
    "currency_id" uuid,
    "phone_code" character varying(10),
    "is_active" boolean DEFAULT true NOT NULL,
    "display_order" integer DEFAULT 999 NOT NULL,
    CONSTRAINT "country_info_pkey" PRIMARY KEY (country_code)
);

CREATE TABLE pettycash_test."currency_info" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "currency_code" character(3) NOT NULL,
    "currency_name" character varying(100) NOT NULL,
    "symbol" character varying(10) DEFAULT ''::character varying NOT NULL,
    "decimal_places" integer DEFAULT 2 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "currency_info_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."django_content_type" (
    "id" integer NOT NULL,
    "app_label" character varying(100) NOT NULL,
    "model" character varying(100) NOT NULL,
    CONSTRAINT "django_content_type_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."django_migrations" (
    "id" bigint NOT NULL,
    "app" character varying(255) NOT NULL,
    "name" character varying(255) NOT NULL,
    "applied" timestamp with time zone NOT NULL,
    CONSTRAINT "django_migrations_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."email_otp" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "email" character varying(100) NOT NULL,
    "code_hash" character varying(255) NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "attempts" integer NOT NULL,
    "verified_at" timestamp with time zone,
    "created_at" timestamp with time zone NOT NULL,
    CONSTRAINT "email_otp_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entities" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "country_code" character(2),
    "currency_id" uuid,
    "name" character varying(100) NOT NULL,
    "minimum_qty" integer,
    "deposit_frequency" integer,
    "deposit_day" integer,
    "contact_phone" character varying(20),
    "xero_org_id" character varying(36),
    "xero_short_code" character varying(50),
    "currency_format" character varying(30),
    "timezone" character varying(30),
    "note" text,
    "status" character varying(20),
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "last_connected_at" timestamp with time zone,
    "xero_tenant_name" character varying(255),
    "period_lock_date" date,
    "end_of_year_lock_date" date,
    "connected_by_user_id" uuid,
    "onboarding_saved_step" integer,
    "last_accessed_at" timestamp with time zone,
    "last_accessed_by_user_id" uuid,
    "business_email" character varying(100),
    CONSTRAINT "entities_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_account_xero" (
    "id" uuid NOT NULL,
    "account_id" uuid NOT NULL,
    "type" character varying(50),
    "xero_org_id" character varying(36),
    "xero_account_id" character varying(36),
    "name" character varying(80),
    "is_active" boolean DEFAULT true NOT NULL,
    CONSTRAINT "entity_account_xero_pkey" PRIMARY KEY (id, account_id)
);

CREATE TABLE pettycash_test."entity_bill_account_xero" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "account_code" character varying(150) NOT NULL,
    "account_name" character varying(150) DEFAULT ''::character varying NOT NULL,
    "account_type" character varying(50) DEFAULT ''::character varying NOT NULL,
    "is_default" boolean DEFAULT false NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "is_deleted" boolean DEFAULT false NOT NULL,
    "xero_account_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "created_by" uuid,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    CONSTRAINT "entity_bill_account_xero_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_bill_currency" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "is_default" boolean DEFAULT false NOT NULL,
    "is_enabled" boolean DEFAULT true NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "created_by" uuid NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "currency_info_id" uuid NOT NULL,
    CONSTRAINT "entity_bill_currency_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_billing_consent" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "user_id" uuid NOT NULL,
    "source" character varying(20) NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "entity_billing_consent_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_billing_group" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "payer_user_id" uuid NOT NULL,
    "billing_group_id" uuid NOT NULL,
    "source" character varying(20) NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "entity_billing_group_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_cash_detail_v2" (
    "entity_id" uuid NOT NULL,
    "cash_id" integer NOT NULL,
    "cash_type" character varying(30),
    "cash_instock" double precision,
    "desc" text,
    CONSTRAINT "entity_cash_detail_v2_pkey" PRIMARY KEY (entity_id, cash_id)
);

CREATE TABLE pettycash_test."entity_cash_setting" (
    "entity_id" uuid NOT NULL,
    "cash_id" integer NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "display_order" integer,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "entity_cash_setting_pkey" PRIMARY KEY (entity_id, cash_id)
);

CREATE TABLE pettycash_test."entity_function" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "function_code" character varying(100) NOT NULL,
    "function_name" character varying(150) NOT NULL,
    "description" text DEFAULT ''::text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    CONSTRAINT "entity_function_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_function_map" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "is_enabled" boolean DEFAULT true NOT NULL,
    "enabled_at" timestamp with time zone,
    "disabled_at" timestamp with time zone,
    "settings_json" jsonb,
    "created_by" character varying(36) DEFAULT ''::character varying NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "entity_function_id" uuid NOT NULL,
    CONSTRAINT "entity_function_map_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_module_subscription" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "function_code" character varying(100) NOT NULL,
    "payer_user_id" uuid NOT NULL,
    "phase" character varying(30) NOT NULL,
    "app_access_until" timestamp with time zone,
    "trial_end" timestamp with time zone,
    "first_billed_at" timestamp with time zone,
    "extension_amount" integer,
    "extension_state" character varying(20),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "billed_through" timestamp with time zone,
    CONSTRAINT "entity_module_subscription_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."entity_pettycash_settings" (
    "entity_id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "pettycash_account_id" uuid,
    "bank_account_id" uuid,
    "cash_sale_account_id" uuid,
    "discrepancy_bank_account_id" uuid,
    "discrepancy_account_id" uuid,
    "director_account_id" uuid,
    "cash_sale_contact_id" uuid,
    "director_contact_id" uuid,
    "discrepancy_contact_id" uuid,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "entity_pettycash_settings_pkey" PRIMARY KEY (entity_id)
);

CREATE TABLE pettycash_test."entity_sale_setting" (
    "sale_id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid,
    "type" character varying(50),
    "sale_name" character varying(80),
    "value_name" character varying(80),
    "create_date" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "display_order" integer,
    "enabled" boolean,
    "sale_info_id" uuid,
    CONSTRAINT "entity_sale_setting_pkey" PRIMARY KEY (sale_id)
);

CREATE TABLE pettycash_test."invitations" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "email" character varying(150) NOT NULL,
    "role" character varying(20) NOT NULL,
    "token" character varying(64) NOT NULL,
    "status" character varying(20) NOT NULL,
    "invited_by" uuid,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "accepted_at" timestamp with time zone,
    "expires_at" timestamp with time zone,
    "first_name" character varying(100),
    "last_name" character varying(100),
    CONSTRAINT "invitations_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."payer_billing_group" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "payer_user_id" uuid NOT NULL,
    "stripe_payment_method_id" character varying(255) NOT NULL,
    "paid_through" timestamp with time zone,
    "dunning_started_at" timestamp with time zone,
    "dunning_attempts" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "payer_billing_group_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."payment" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "payment_date" date,
    "amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "currency_code" character varying(10) DEFAULT ''::character varying NOT NULL,
    "payment_method" character varying(50) DEFAULT ''::character varying NOT NULL,
    "payment_status" character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    "reference_no" character varying(100) DEFAULT ''::character varying NOT NULL,
    "note" text DEFAULT ''::text NOT NULL,
    "xero_payment_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "created_by" uuid NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "bill_id" uuid NOT NULL,
    CONSTRAINT "payment_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."payment_attachment" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "attachment_role" character varying(50) DEFAULT 'other'::character varying NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "note" text DEFAULT ''::text NOT NULL,
    "created_by" uuid NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "xero_attachment_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "xero_filename" character varying(255) DEFAULT ''::character varying NOT NULL,
    "payment_id" uuid NOT NULL,
    "attachment_id" uuid NOT NULL,
    CONSTRAINT "payment_attachment_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."permissions" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "name" character varying(100) NOT NULL,
    "description" character varying(255),
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    CONSTRAINT "permissions_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."report" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "transaction_date" date NOT NULL,
    "next_transaction_date" date,
    "date" timestamp with time zone,
    "opening_balance" double precision NOT NULL,
    "cash_addition" double precision NOT NULL,
    "adjusted_opening_balance" double precision,
    "cash_sales" double precision NOT NULL,
    "shop_sales" double precision NOT NULL,
    "delivery_sales" double precision NOT NULL,
    "total_sales" double precision NOT NULL,
    "expenses" double precision,
    "bank_deposit" double precision NOT NULL,
    "closing_balance" double precision,
    "receipt_files" text,
    "uploaded_by" character varying(150),
    "company" uuid NOT NULL,
    "xero_integrated_yes" boolean,
    "safe_box_balance" double precision,
    "discrepancy_amount" double precision,
    "discrepancy_reason" character varying(300),
    "discrepancy_type" character varying(20),
    "publishing_status" character varying(20),
    "status" character varying(20),
    "current_section" character varying(20),
    "completed_sections" json,
    "withdrawal_type" character varying(20),
    "withdrawal_bank_account" character varying(36),
    "actual_cash_total" double precision,
    CONSTRAINT "report_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."report_cash_count" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "report_id" uuid NOT NULL,
    "cash_id" integer NOT NULL,
    "quantity" integer DEFAULT 0 NOT NULL,
    "cash_value" numeric(12,2) NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "report_cash_count_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."report_history" (
    "id" integer DEFAULT nextval('pettycash_test.report_history_id_seq'::regclass) NOT NULL,
    "report_id" uuid NOT NULL,
    "company" uuid NOT NULL,
    "user_id" uuid,
    "action" character varying(50) NOT NULL,
    "field_changed" character varying(255),
    "old_value" text,
    "new_value" text,
    "timestamp" timestamp with time zone NOT NULL,
    CONSTRAINT "report_history_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."report_sale_detail" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "sale_id" uuid,
    "report_id" uuid,
    "type" character varying(50),
    "amount" double precision,
    "create_at" timestamp with time zone,
    "sale_info_id" uuid,
    CONSTRAINT "report_sale_detail_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."role_permissions" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "role_id" uuid,
    "permission_id" uuid,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    CONSTRAINT "role_permissions_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."roles" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "name" character varying(100) NOT NULL,
    "description" character varying(255),
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    CONSTRAINT "roles_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."sale_info" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid,
    "code" character varying(50) NOT NULL,
    "name" character varying(80) NOT NULL,
    "type" character varying(20) NOT NULL,
    "legacy_column" character varying(50),
    "is_active" boolean DEFAULT true NOT NULL,
    "display_order" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "sale_info_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."sessions" (
    "id" integer DEFAULT nextval('pettycash_test.sessions_id_seq'::regclass) NOT NULL,
    "session_id" character varying(255),
    "data" bytea,
    "expiry" timestamp with time zone,
    CONSTRAINT "sessions_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."share_link" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "path_segment" character varying(255) NOT NULL,
    "token" text NOT NULL,
    "entity_id" uuid NOT NULL,
    "transaction_date" character varying(10) NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "expires_at" timestamp with time zone NOT NULL,
    CONSTRAINT "share_link_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."shop_expense" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "report_id" uuid NOT NULL,
    "item" character varying(150) NOT NULL,
    "amount" double precision NOT NULL,
    "remarks" character varying(300),
    "files" text,
    "s3_key" character varying(255),
    "account_code" character varying(20),
    "item_code" character varying(20),
    "contact_id" character varying(36),
    "contact_name" character varying(150),
    "account_id" character varying(36),
    CONSTRAINT "shop_expense_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."subscription_audit_log" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "function_code" character varying(100) NOT NULL,
    "payer_user_id" uuid NOT NULL,
    "actor_user_id" uuid,
    "action" character varying(40) NOT NULL,
    "phase_before" character varying(30),
    "phase_after" character varying(30),
    "app_access_until" timestamp with time zone,
    "extension_amount" integer,
    "extension_state" character varying(20),
    "outcome" character varying(20) NOT NULL,
    "note" character varying(500),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "cancel_reason" character varying(500),
    "payer_before" uuid,
    "payer_after" uuid,
    CONSTRAINT "subscription_audit_log_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."subscription_email_log" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "user_id" uuid NOT NULL,
    "event" character varying(40) NOT NULL,
    "dedupe_key" character varying(200) NOT NULL,
    "recipient" character varying(200),
    "status" character varying(20) NOT NULL,
    "error" character varying(500),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "subscription_email_log_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."subscription_invoice" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "payer_user_id" uuid NOT NULL,
    "stripe_customer_id" character varying(255),
    "external_id" character varying(255),
    "period_start" timestamp with time zone NOT NULL,
    "period_end" timestamp with time zone NOT NULL,
    "currency" character(3) NOT NULL,
    "total" integer DEFAULT 0 NOT NULL,
    "status" character varying(20) NOT NULL,
    "memo" character varying(500),
    "idempotency_key" character varying(255),
    "issued_at" timestamp with time zone,
    "paid_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "payment_method" character varying(100),
    "hosted_invoice_url" character varying(500),
    "billing_group_id" uuid,
    CONSTRAINT "subscription_invoice_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."subscription_invoice_line" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "invoice_id" uuid NOT NULL,
    "entity_id" uuid NOT NULL,
    "entity_name" character varying(255) NOT NULL,
    "product_name" character varying(255) NOT NULL,
    "amount" integer NOT NULL,
    "kind" character varying(20) DEFAULT 'full'::character varying NOT NULL,
    "at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "subscription_invoice_line_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."subscription_transfer" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid NOT NULL,
    "from_user_id" uuid NOT NULL,
    "to_user_id" uuid NOT NULL,
    "status" character varying(20) NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "responded_at" timestamp with time zone,
    "accepted_billed_through" timestamp with time zone,
    "accepted_anchor_at" timestamp with time zone,
    "quoted_amount" integer,
    "quoted_currency" character varying(3),
    "charge_attempt" integer DEFAULT 0 NOT NULL,
    "charge_key" character varying(120),
    "charge_invoice_id" character varying(64),
    "note" character varying(500),
    CONSTRAINT "subscription_transfer_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."terms_consent" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "user_id" uuid NOT NULL,
    "terms_version" character varying(32) NOT NULL,
    "document_hash" character varying(64) NOT NULL,
    "accepted_at" timestamp with time zone DEFAULT now() NOT NULL,
    "source" character varying(32) NOT NULL,
    "ip_address" character varying(45),
    "user_agent" character varying(512),
    CONSTRAINT "terms_consent_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."user" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "email" character varying(100),
    "password" character varying(150) NOT NULL,
    "xero_user_id" uuid,
    "first_name" character varying(150) NOT NULL,
    "last_name" character varying(150) NOT NULL,
    "user_phone" character varying(20),
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "username" character varying(150) NOT NULL,
    "xero_entity_id" character varying(36),
    "approved" boolean,
    "reset_token" character varying(100),
    "reset_token_expiry" timestamp with time zone,
    "xero_token" character varying(2048),
    "access_token" character varying(2048),
    "refresh_token" character varying(255),
    "id_token" character varying(2048),
    "expires_in" integer,
    "token_created_at" timestamp with time zone,
    "system_role" character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    "xero_email" character varying(100),
    "signed_in_at" timestamp with time zone,
    "last_seen_at" timestamp with time zone,
    "current_entity_id" uuid,
    CONSTRAINT "user_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."user_entity" (
    "user_id" uuid NOT NULL,
    "entity_id" uuid NOT NULL,
    "role" character varying(20) NOT NULL,
    "create_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "approved" boolean,
    "joined_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "user_entity_pkey" PRIMARY KEY (user_id, entity_id)
);

CREATE TABLE pettycash_test."user_stripe_customer" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "user_id" uuid NOT NULL,
    "stripe_customer_id" character varying(255) NOT NULL,
    "anchor_at" timestamp with time zone,
    "currency" character(3),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "user_stripe_customer_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."user_token" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "user_id" uuid NOT NULL,
    "access_token" text,
    "access_token_obtained_at" timestamp with time zone,
    "access_token_expires_in" integer,
    "refresh_token" text,
    "id_token" text,
    "refresh_token_last_used_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "user_token_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bank_transaction" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "sync_report_id" uuid,
    "type" character varying(10) NOT NULL,
    "xero_contact_id" character varying(36) NOT NULL,
    "xero_contact_name" character varying(100),
    "unit_amount" double precision NOT NULL,
    "quantity" double precision NOT NULL,
    "xero_account_id" character varying(36) NOT NULL,
    "xero_account_code" character varying(10),
    "description" text,
    "xero_bank_account_id" character varying(36) NOT NULL,
    "xero_bank_transaction_id" character varying(36) NOT NULL,
    "subtotal" double precision,
    "total_tax" double precision,
    "total" double precision,
    "status" character varying(10),
    "create_at" timestamp with time zone,
    CONSTRAINT "xero_bank_transaction_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bank_transfer" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "sync_report_id" uuid,
    "from_bank_account_id" character varying(36) NOT NULL,
    "to_bank_account_id" character varying(36) NOT NULL,
    "amount" double precision NOT NULL,
    "transfer_date" timestamp with time zone NOT NULL,
    "xero_bank_transfer_id" character varying(36) NOT NULL,
    "from_bank_transaction_id" character varying(36) NOT NULL,
    "to_bank_transaction_id" character varying(36) NOT NULL,
    "status" character varying(10),
    "error_message" text,
    CONSTRAINT "xero_bank_transfer_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bill_response_line" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "xero_line_item_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "description" text DEFAULT ''::text NOT NULL,
    "quantity" numeric(12,4) DEFAULT 0 NOT NULL,
    "unit_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "line_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "tax_type" character varying(30) DEFAULT ''::character varying NOT NULL,
    "tax_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "account_code" character varying(20) DEFAULT ''::character varying NOT NULL,
    "account_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "validation_errors" jsonb,
    "created_at" timestamp with time zone NOT NULL,
    "xero_bill_sync_id" uuid NOT NULL,
    CONSTRAINT "xero_bill_response_line_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bill_sync" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "sync_direction" character varying(20) NOT NULL,
    "sync_type" character varying(30) NOT NULL,
    "sync_status" character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    "request_type" character varying(20) DEFAULT ''::character varying NOT NULL,
    "request_status" character varying(30) DEFAULT ''::character varying NOT NULL,
    "request_contact_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "request_invoice_number" character varying(100) DEFAULT ''::character varying NOT NULL,
    "request_reference" character varying(255) DEFAULT ''::character varying NOT NULL,
    "request_invoice_date" date,
    "request_due_date" date,
    "response_invoice_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "response_invoice_number" character varying(100) DEFAULT ''::character varying NOT NULL,
    "response_status" character varying(30) DEFAULT ''::character varying NOT NULL,
    "response_amount_due" numeric(12,2),
    "response_amount_paid" numeric(12,2),
    "response_total" numeric(12,2),
    "response_currency_code" character varying(10) DEFAULT ''::character varying NOT NULL,
    "xero_response_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "xero_provider_name" character varying(100) DEFAULT ''::character varying NOT NULL,
    "xero_datetime_utc" character varying(100) DEFAULT ''::character varying NOT NULL,
    "http_status_code" integer,
    "idempotency_key" character varying(100) DEFAULT ''::character varying NOT NULL,
    "retry_count" integer DEFAULT 0 NOT NULL,
    "last_retry_at" timestamp with time zone,
    "has_errors" boolean DEFAULT false NOT NULL,
    "error_message" text DEFAULT ''::text NOT NULL,
    "requested_by" uuid NOT NULL,
    "requested_at" timestamp with time zone,
    "responded_at" timestamp with time zone,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "bill_id" uuid NOT NULL,
    CONSTRAINT "xero_bill_sync_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bill_sync_line" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "description" text DEFAULT ''::text NOT NULL,
    "quantity" numeric(12,4) DEFAULT 0 NOT NULL,
    "unit_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "line_amount" numeric(12,2) DEFAULT 0 NOT NULL,
    "account_code" character varying(20) DEFAULT ''::character varying NOT NULL,
    "tax_type" character varying(30) DEFAULT ''::character varying NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "response_line_item_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "response_account_id" character varying(36) DEFAULT ''::character varying NOT NULL,
    "response_tax_amount" numeric(12,2),
    "created_at" timestamp with time zone NOT NULL,
    "xero_bill_sync_id" uuid NOT NULL,
    "bill_line_item_id" uuid,
    CONSTRAINT "xero_bill_sync_line_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_bill_sync_payload" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "request_json" jsonb,
    "response_json" jsonb,
    "request_headers" jsonb,
    "response_headers" jsonb,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "xero_bill_sync_id" uuid NOT NULL,
    CONSTRAINT "xero_bill_sync_payload_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_contact_sync" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "entity_id" uuid,
    "xero_contact_id" character varying(36) NOT NULL,
    "xero_org_id" character varying(36),
    "name" character varying(150) NOT NULL,
    "category" character varying(50),
    CONSTRAINT "xero_contact_sync_pkey" PRIMARY KEY (id)
);

CREATE TABLE pettycash_test."xero_report_sync" (
    "id" uuid DEFAULT pettycash_test.uuid7() NOT NULL,
    "report_id" uuid,
    "sync_statuc" character varying(20),
    "reported_at" timestamp with time zone,
    "completed_at" timestamp with time zone,
    "xero_reponse_text" text,
    CONSTRAINT "xero_report_sync_pkey" PRIMARY KEY (id)
);

ALTER SEQUENCE pettycash_test.cash_info_cash_id_seq OWNED BY pettycash_test."cash_info"."cash_id";
ALTER SEQUENCE pettycash_test.report_history_id_seq OWNED BY pettycash_test."report_history"."id";
ALTER SEQUENCE pettycash_test.sessions_id_seq OWNED BY pettycash_test."sessions"."id";


-- ###########################################################################
-- ### 23_indexes.sql
-- ###########################################################################

-- --------------------------------------------------------------------------
-- pettycash_test :: indexes
--
-- Every index that is not created implicitly by a primary key or unique
-- constraint. Those arrive with their constraint, in 22 and 25 respectively.
--
-- Built after the load, not before it: an index maintained during a bulk insert
-- costs more than one built once at the end over the finished table.
--
-- 8 of the source's 73 indexes are NOT recreated here.
-- They are Django's varchar_pattern_ops twins - the extra index it creates beside
-- every CharField key so that LIKE 'prefix%%' can use one. On a uuid column that
-- opclass is rejected outright (varchar_pattern_ops does not accept uuid), and it
-- would be pointless anyway: nobody prefix-matches a uuid. They are also redundant,
-- because Django already creates a plain btree on the same column and that is the
-- one serving equality lookups. The _like twins on genuinely textual columns
-- (auth_group.name, auth_user.username) are kept.
--
-- Dropped: attachment.id, audit.bill_id, audit.id, bill.entity_id, bill.id, bill.uploaded_by, bill_line_item.bill_id, bill_line_item.id
-- --------------------------------------------------------------------------

\set ON_ERROR_STOP on


CREATE INDEX audit_bill_id_3df7b337 ON pettycash_test.audit USING btree (bill_id);
CREATE INDEX auth_group_name_a6ea08ec_like ON pettycash_test.auth_group USING btree (name varchar_pattern_ops);
CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON pettycash_test.auth_group_permissions USING btree (group_id);
CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON pettycash_test.auth_group_permissions USING btree (permission_id);
CREATE INDEX auth_permission_content_type_id_2f476e4b ON pettycash_test.auth_permission USING btree (content_type_id);
CREATE INDEX auth_user_username_6821ab7c_like ON pettycash_test.auth_user USING btree (username varchar_pattern_ops);
CREATE INDEX auth_user_groups_group_id_97559544 ON pettycash_test.auth_user_groups USING btree (group_id);
CREATE INDEX auth_user_groups_user_id_6a12ed8b ON pettycash_test.auth_user_groups USING btree (user_id);
CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON pettycash_test.auth_user_user_permissions USING btree (permission_id);
CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON pettycash_test.auth_user_user_permissions USING btree (user_id);
CREATE INDEX bill_entity_id_9f94c1e7 ON pettycash_test.bill USING btree (entity_id);
CREATE INDEX bill_uploaded_by_78d50a0e ON pettycash_test.bill USING btree (uploaded_by);
CREATE INDEX bill_attachment_attachment_id_idx ON pettycash_test.bill_attachment USING btree (attachment_id);
CREATE INDEX bill_attachment_bill_id_idx ON pettycash_test.bill_attachment USING btree (bill_id);
CREATE INDEX bill_line_item_bill_id_89c06dc2 ON pettycash_test.bill_line_item USING btree (bill_id);
CREATE INDEX bill_line_item_bill_id_idx ON pettycash_test.bill_line_item USING btree (bill_id);
CREATE INDEX ix_billing_plan_code ON pettycash_test.billing_plan USING btree (code);
CREATE INDEX ix_cash_info_currency_order ON pettycash_test.cash_info USING btree (currency_id, display_order);
CREATE INDEX idx_country_info_currency_id ON pettycash_test.country_info USING btree (currency_id);
CREATE INDEX ix_email_otp_email ON pettycash_test.email_otp USING btree (email);
CREATE INDEX entity_bill_account_xero_entity_id_idx ON pettycash_test.entity_bill_account_xero USING btree (entity_id);
CREATE INDEX entity_bill_currency_currency_info_id_idx ON pettycash_test.entity_bill_currency USING btree (currency_info_id);
CREATE INDEX entity_bill_currency_entity_id_idx ON pettycash_test.entity_bill_currency USING btree (entity_id);
CREATE INDEX ix_entity_billing_group_entity ON pettycash_test.entity_billing_group USING btree (entity_id);
CREATE INDEX ix_entity_billing_group_group ON pettycash_test.entity_billing_group USING btree (billing_group_id);
CREATE INDEX ix_entity_billing_group_payer ON pettycash_test.entity_billing_group USING btree (payer_user_id);
CREATE INDEX ix_entity_cash_setting_entity ON pettycash_test.entity_cash_setting USING btree (entity_id);
CREATE INDEX entity_function_map_entity_function_id_idx ON pettycash_test.entity_function_map USING btree (entity_function_id);
CREATE INDEX entity_function_map_entity_id_idx ON pettycash_test.entity_function_map USING btree (entity_id);
CREATE INDEX ix_ems_billed_through ON pettycash_test.entity_module_subscription USING btree (billed_through) WHERE (billed_through IS NOT NULL);
CREATE INDEX ix_entity_module_subscription_entity_id ON pettycash_test.entity_module_subscription USING btree (entity_id);
CREATE INDEX ix_entity_module_subscription_function_code ON pettycash_test.entity_module_subscription USING btree (function_code);
CREATE INDEX ix_entity_module_subscription_payer_user_id ON pettycash_test.entity_module_subscription USING btree (payer_user_id);
CREATE INDEX ix_entity_module_subscription_trial_end ON pettycash_test.entity_module_subscription USING btree (trial_end);
CREATE INDEX ix_entity_sale_setting_sale_info_id ON pettycash_test.entity_sale_setting USING btree (sale_info_id);
CREATE INDEX ix_payer_billing_group_dunning ON pettycash_test.payer_billing_group USING btree (dunning_started_at) WHERE (dunning_started_at IS NOT NULL);
CREATE INDEX ix_payer_billing_group_payer ON pettycash_test.payer_billing_group USING btree (payer_user_id);
CREATE INDEX payment_bill_id_idx ON pettycash_test.payment USING btree (bill_id);
CREATE INDEX payment_attachment_attachment_id_idx ON pettycash_test.payment_attachment USING btree (attachment_id);
CREATE INDEX payment_attachment_payment_id_idx ON pettycash_test.payment_attachment USING btree (payment_id);
CREATE INDEX ix_report_cash_count_report ON pettycash_test.report_cash_count USING btree (report_id);
CREATE INDEX ix_pettycashv2_report_history_company ON pettycash_test.report_history USING btree (company);
CREATE INDEX ix_report_sale_detail_sale_info_id ON pettycash_test.report_sale_detail USING btree (sale_info_id);
CREATE INDEX ix_sale_info_legacy_column ON pettycash_test.sale_info USING btree (legacy_column);
CREATE UNIQUE INDEX ix_pettycashv2_share_link_path_segment ON pettycash_test.share_link USING btree (path_segment);
CREATE INDEX ix_sub_audit_payer_after ON pettycash_test.subscription_audit_log USING btree (payer_after, created_at) WHERE (payer_after IS NOT NULL);
CREATE INDEX ix_subscription_audit_log_created_at ON pettycash_test.subscription_audit_log USING btree (created_at);
CREATE INDEX ix_subscription_audit_log_entity_id ON pettycash_test.subscription_audit_log USING btree (entity_id);
CREATE INDEX ix_sub_email_user_created ON pettycash_test.subscription_email_log USING btree (user_id, created_at);
CREATE INDEX ix_subscription_invoice_external_id ON pettycash_test.subscription_invoice USING btree (external_id);
CREATE INDEX ix_subscription_invoice_group ON pettycash_test.subscription_invoice USING btree (billing_group_id, period_start) WHERE (billing_group_id IS NOT NULL);
CREATE INDEX ix_subscription_invoice_payer ON pettycash_test.subscription_invoice USING btree (payer_user_id, period_start);
CREATE UNIQUE INDEX uq_subscription_invoice_idempotency_key ON pettycash_test.subscription_invoice USING btree (idempotency_key);
CREATE INDEX ix_subscription_invoice_line_entity_id ON pettycash_test.subscription_invoice_line USING btree (entity_id);
CREATE INDEX ix_subscription_invoice_line_invoice_id ON pettycash_test.subscription_invoice_line USING btree (invoice_id);
CREATE INDEX ix_subscription_transfer_entity ON pettycash_test.subscription_transfer USING btree (entity_id, created_at);
CREATE INDEX ix_subscription_transfer_stranded ON pettycash_test.subscription_transfer USING btree (status) WHERE ((status)::text = ANY ((ARRAY['charging'::character varying, 'charged'::character varying])::text[]));
CREATE INDEX ix_subscription_transfer_to_user ON pettycash_test.subscription_transfer USING btree (to_user_id, status);
CREATE UNIQUE INDEX uq_subscription_transfer_open ON pettycash_test.subscription_transfer USING btree (entity_id) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'charging'::character varying, 'charged'::character varying])::text[]));
CREATE INDEX ix_terms_consent_user ON pettycash_test.terms_consent USING btree (user_id);
CREATE INDEX ix_user_current_entity_id ON pettycash_test."user" USING btree (current_entity_id);
CREATE INDEX xero_bill_response_line_xero_bill_sync_id_idx ON pettycash_test.xero_bill_response_line USING btree (xero_bill_sync_id);
CREATE INDEX xero_bill_sync_bill_id_idx ON pettycash_test.xero_bill_sync USING btree (bill_id);
CREATE INDEX xero_bill_sync_line_bill_line_item_id_idx ON pettycash_test.xero_bill_sync_line USING btree (bill_line_item_id);
CREATE INDEX xero_bill_sync_line_xero_bill_sync_id_idx ON pettycash_test.xero_bill_sync_line USING btree (xero_bill_sync_id);


-- ###########################################################################
-- ### 25_constraints.sql
-- ###########################################################################

-- --------------------------------------------------------------------------
-- pettycash_test :: constraints - and the acceptance test
--
-- 30 unique, 8 check, 82 foreign key.
--
-- THIS FILE IS THE ACCEPTANCE TEST FOR THE MIGRATION. It runs after the data is
-- in. If the remediation missed a broken reference, or the id map dropped a row,
-- or a load statement mapped the wrong column, a foreign key refuses to build and
-- names the offending value. Nothing else in the migration checks the id graph as
-- thoroughly, because nothing else has to.
--
-- It also explains why load order does not matter: with no keys in place during
-- the load, no table has to precede any other. That is worth having, because the
-- foreign key graph is NOT a valid load order here - 54 id columns carry no key at
-- all, so tables like bill and entity_bill_account_xero look like roots while
-- actually depending on entities.
--
-- The 54 unenforced references stay unenforced: adding a key can reject rows, and
-- that is a behaviour change this migration does not make. They are recorded in
-- 24_comments.sql instead.
-- --------------------------------------------------------------------------

\set ON_ERROR_STOP on


-- --- unique ----------------------------------------------------------------
ALTER TABLE pettycash_test."account_info" ADD CONSTRAINT "uq_account_info_entity_xero_account" UNIQUE (entity_id, xero_account_id);
ALTER TABLE pettycash_test."auth_group" ADD CONSTRAINT "auth_group_name_key" UNIQUE (name);
ALTER TABLE pettycash_test."auth_group_permissions" ADD CONSTRAINT "auth_group_permissions_group_id_permission_id_0cd325b0_uniq" UNIQUE (group_id, permission_id);
ALTER TABLE pettycash_test."auth_permission" ADD CONSTRAINT "auth_permission_content_type_id_codename_01ab375a_uniq" UNIQUE (content_type_id, codename);
ALTER TABLE pettycash_test."auth_user" ADD CONSTRAINT "auth_user_username_key" UNIQUE (username);
ALTER TABLE pettycash_test."auth_user_groups" ADD CONSTRAINT "auth_user_groups_user_id_group_id_94350c0c_uniq" UNIQUE (user_id, group_id);
ALTER TABLE pettycash_test."auth_user_user_permissions" ADD CONSTRAINT "auth_user_user_permissions_user_id_permission_id_14a6b632_uniq" UNIQUE (user_id, permission_id);
ALTER TABLE pettycash_test."billing_plan" ADD CONSTRAINT "billing_plan_code_key" UNIQUE (code);
ALTER TABLE pettycash_test."cash_info" ADD CONSTRAINT "uq_cash_info_currency_value_type" UNIQUE (currency_id, cash_value, type);
ALTER TABLE pettycash_test."currency_info" ADD CONSTRAINT "currency_info_currency_code_key" UNIQUE (currency_code);
ALTER TABLE pettycash_test."django_content_type" ADD CONSTRAINT "django_content_type_app_label_model_76bd3d3b_uniq" UNIQUE (app_label, model);
ALTER TABLE pettycash_test."entity_billing_consent" ADD CONSTRAINT "uq_entity_billing_consent_entity_user" UNIQUE (entity_id, user_id);
ALTER TABLE pettycash_test."entity_billing_group" ADD CONSTRAINT "uq_entity_billing_group_entity_payer" UNIQUE (entity_id, payer_user_id);
ALTER TABLE pettycash_test."entity_function" ADD CONSTRAINT "entity_function_function_code_key" UNIQUE (function_code);
ALTER TABLE pettycash_test."entity_module_subscription" ADD CONSTRAINT "uq_entity_module_subscription_entity_code" UNIQUE (entity_id, function_code);
ALTER TABLE pettycash_test."invitations" ADD CONSTRAINT "invitations_token_key" UNIQUE (token);
ALTER TABLE pettycash_test."payer_billing_group" ADD CONSTRAINT "uq_payer_billing_group_payer_card" UNIQUE (payer_user_id, stripe_payment_method_id);
ALTER TABLE pettycash_test."report_cash_count" ADD CONSTRAINT "report_cash_count_uq" UNIQUE (report_id, cash_id);
ALTER TABLE pettycash_test."sale_info" ADD CONSTRAINT "uq_sale_info_entity_code" UNIQUE NULLS NOT DISTINCT (entity_id, code);
ALTER TABLE pettycash_test."sessions" ADD CONSTRAINT "sessions_session_id_key" UNIQUE (session_id);
ALTER TABLE pettycash_test."subscription_email_log" ADD CONSTRAINT "uq_sub_email_event_key" UNIQUE (event, dedupe_key);
ALTER TABLE pettycash_test."terms_consent" ADD CONSTRAINT "uq_terms_consent_user_version" UNIQUE (user_id, terms_version);
ALTER TABLE pettycash_test."user" ADD CONSTRAINT "uq_user_xero_email" UNIQUE (xero_email);
ALTER TABLE pettycash_test."user" ADD CONSTRAINT "user_email_key" UNIQUE (email);
ALTER TABLE pettycash_test."user" ADD CONSTRAINT "user_username_key" UNIQUE (username);
ALTER TABLE pettycash_test."user" ADD CONSTRAINT "user_xero_user_id_key" UNIQUE (xero_user_id);
ALTER TABLE pettycash_test."user_stripe_customer" ADD CONSTRAINT "user_stripe_customer_stripe_customer_id_key" UNIQUE (stripe_customer_id);
ALTER TABLE pettycash_test."user_stripe_customer" ADD CONSTRAINT "user_stripe_customer_user_id_key" UNIQUE (user_id);
ALTER TABLE pettycash_test."user_token" ADD CONSTRAINT "user_token_user_id_key" UNIQUE (user_id);
ALTER TABLE pettycash_test."xero_bill_sync_payload" ADD CONSTRAINT "xero_bill_sync_payload_xero_bill_sync_id_key" UNIQUE (xero_bill_sync_id);

-- --- check -----------------------------------------------------------------
ALTER TABLE pettycash_test."billing_policy" ADD CONSTRAINT "ck_billing_policy_cancel_days" CHECK ((paid_cancel_access_days >= 0));
ALTER TABLE pettycash_test."billing_policy" ADD CONSTRAINT "ck_billing_policy_past_due_window" CHECK ((past_due_window_days >= 3));
ALTER TABLE pettycash_test."billing_policy" ADD CONSTRAINT "ck_billing_policy_retry_offsets_format" CHECK (((retry_offsets_days)::text ~ '^[0-9]+(,[0-9]+)*$'::text));
ALTER TABLE pettycash_test."billing_policy" ADD CONSTRAINT "ck_billing_policy_singleton" CHECK ((id = 1));
ALTER TABLE pettycash_test."billing_policy" ADD CONSTRAINT "ck_billing_policy_trial_days" CHECK ((trial_days >= 0));
ALTER TABLE pettycash_test."country_info" ADD CONSTRAINT "chk_alpha3_code_length" CHECK ((length(alpha3_code) = 3));
ALTER TABLE pettycash_test."country_info" ADD CONSTRAINT "chk_country_code_length" CHECK ((length(country_code) = 2));
ALTER TABLE pettycash_test."report_cash_count" ADD CONSTRAINT "chk_rcc_qty" CHECK ((quantity >= 0));

-- --- foreign key -----------------------------------------------------------
ALTER TABLE pettycash_test."account_info" ADD CONSTRAINT "account_info_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."audit" ADD CONSTRAINT "fk_audit_bill_id" FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."auth_group_permissions" ADD CONSTRAINT "auth_group_permissio_permission_id_84c5c92e_fk_auth_perm" FOREIGN KEY (permission_id) REFERENCES pettycash_test.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_group_permissions" ADD CONSTRAINT "auth_group_permissions_group_id_b120cbf9_fk_auth_group_id" FOREIGN KEY (group_id) REFERENCES pettycash_test.auth_group(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_permission" ADD CONSTRAINT "auth_permission_content_type_id_2f476e4b_fk_django_co" FOREIGN KEY (content_type_id) REFERENCES pettycash_test.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_user_groups" ADD CONSTRAINT "auth_user_groups_group_id_97559544_fk_auth_group_id" FOREIGN KEY (group_id) REFERENCES pettycash_test.auth_group(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_user_groups" ADD CONSTRAINT "auth_user_groups_user_id_6a12ed8b_fk_auth_user_id" FOREIGN KEY (user_id) REFERENCES pettycash_test.auth_user(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_user_user_permissions" ADD CONSTRAINT "auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm" FOREIGN KEY (permission_id) REFERENCES pettycash_test.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."auth_user_user_permissions" ADD CONSTRAINT "auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id" FOREIGN KEY (user_id) REFERENCES pettycash_test.auth_user(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE pettycash_test."bill_attachment" ADD CONSTRAINT "fk_bill_attachment_attachment_id" FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."bill_attachment" ADD CONSTRAINT "fk_bill_attachment_bill_id" FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."bill_line_item" ADD CONSTRAINT "fk_bill_line_item_bill_id" FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."billing_plan" ADD CONSTRAINT "fk_billing_plan_currency" FOREIGN KEY (currency) REFERENCES pettycash_test.currency_info(currency_code);
ALTER TABLE pettycash_test."cash_info" ADD CONSTRAINT "cash_info_country_code_fkey" FOREIGN KEY (country_code) REFERENCES pettycash_test.country_info(country_code);
ALTER TABLE pettycash_test."cash_info" ADD CONSTRAINT "fk_cash_info_currency" FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info(id) ON DELETE RESTRICT;
ALTER TABLE pettycash_test."country_info" ADD CONSTRAINT "fk_country_info_currency_id" FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entities" ADD CONSTRAINT "fk_entities_connected_by_user_id" FOREIGN KEY (connected_by_user_id) REFERENCES pettycash_test."user"(id) ON DELETE RESTRICT;
ALTER TABLE pettycash_test."entities" ADD CONSTRAINT "fk_entities_country_code" FOREIGN KEY (country_code) REFERENCES pettycash_test.country_info(country_code);
ALTER TABLE pettycash_test."entities" ADD CONSTRAINT "fk_entities_currency_id" FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info(id);
ALTER TABLE pettycash_test."entities" ADD CONSTRAINT "fk_entities_last_accessed_by_user_id" FOREIGN KEY (last_accessed_by_user_id) REFERENCES pettycash_test."user"(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_account_xero" ADD CONSTRAINT "entity_account_xero_account_id_fkey" FOREIGN KEY (account_id) REFERENCES pettycash_test.account_info(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_bill_currency" ADD CONSTRAINT "fk_entity_bill_currency_currency_info_id" FOREIGN KEY (currency_info_id) REFERENCES pettycash_test.currency_info(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_billing_consent" ADD CONSTRAINT "entity_billing_consent_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_billing_consent" ADD CONSTRAINT "entity_billing_consent_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_billing_group" ADD CONSTRAINT "fk_entity_billing_group_entity" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_billing_group" ADD CONSTRAINT "fk_entity_billing_group_group" FOREIGN KEY (billing_group_id) REFERENCES pettycash_test.payer_billing_group(id);
ALTER TABLE pettycash_test."entity_billing_group" ADD CONSTRAINT "fk_entity_billing_group_user" FOREIGN KEY (payer_user_id) REFERENCES pettycash_test."user"(id);
ALTER TABLE pettycash_test."entity_cash_detail_v2" ADD CONSTRAINT "entity_cash_detail_v2_cash_id_fkey" FOREIGN KEY (cash_id) REFERENCES pettycash_test.cash_info(cash_id);
ALTER TABLE pettycash_test."entity_cash_detail_v2" ADD CONSTRAINT "entity_cash_detail_v2_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_cash_setting" ADD CONSTRAINT "entity_cash_setting_cash_id_fkey" FOREIGN KEY (cash_id) REFERENCES pettycash_test.cash_info(cash_id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_cash_setting" ADD CONSTRAINT "entity_cash_setting_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_function_map" ADD CONSTRAINT "fk_entity_function_map_entity_function_id" FOREIGN KEY (entity_function_id) REFERENCES pettycash_test.entity_function(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_module_subscription" ADD CONSTRAINT "entity_module_subscription_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_module_subscription" ADD CONSTRAINT "entity_module_subscription_payer_user_id_fkey" FOREIGN KEY (payer_user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_bank_account_id_fkey" FOREIGN KEY (bank_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_cash_sale_account_id_fkey" FOREIGN KEY (cash_sale_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_cash_sale_contact_id_fkey" FOREIGN KEY (cash_sale_contact_id) REFERENCES pettycash_test.xero_contact_sync(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_director_account_id_fkey" FOREIGN KEY (director_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_director_contact_id_fkey" FOREIGN KEY (director_contact_id) REFERENCES pettycash_test.xero_contact_sync(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_discrepancy_account_id_fkey" FOREIGN KEY (discrepancy_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_discrepancy_bank_account_id_fkey" FOREIGN KEY (discrepancy_bank_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_discrepancy_contact_id_fkey" FOREIGN KEY (discrepancy_contact_id) REFERENCES pettycash_test.xero_contact_sync(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."entity_pettycash_settings" ADD CONSTRAINT "entity_pettycash_settings_pettycash_account_id_fkey" FOREIGN KEY (pettycash_account_id) REFERENCES pettycash_test.account_info(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."entity_sale_setting" ADD CONSTRAINT "fk_entity_sale_setting_sale_info" FOREIGN KEY (sale_info_id) REFERENCES pettycash_test.sale_info(id) ON DELETE RESTRICT;
ALTER TABLE pettycash_test."entity_sale_setting" ADD CONSTRAINT "sale_info_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."invitations" ADD CONSTRAINT "invitations_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."invitations" ADD CONSTRAINT "invitations_invited_by_fkey" FOREIGN KEY (invited_by) REFERENCES pettycash_test."user"(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."payer_billing_group" ADD CONSTRAINT "fk_payer_billing_group_user" FOREIGN KEY (payer_user_id) REFERENCES pettycash_test."user"(id);
ALTER TABLE pettycash_test."payment" ADD CONSTRAINT "fk_payment_bill_id" FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."payment_attachment" ADD CONSTRAINT "fk_payment_attachment_attachment_id" FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."payment_attachment" ADD CONSTRAINT "fk_payment_attachment_payment_id" FOREIGN KEY (payment_id) REFERENCES pettycash_test.payment(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."report" ADD CONSTRAINT "report_uploaded_by_fkey" FOREIGN KEY (uploaded_by) REFERENCES pettycash_test."user"(username);
ALTER TABLE pettycash_test."report_cash_count" ADD CONSTRAINT "report_cash_count_cash_id_fkey" FOREIGN KEY (cash_id) REFERENCES pettycash_test.cash_info(cash_id) ON DELETE RESTRICT;
ALTER TABLE pettycash_test."report_cash_count" ADD CONSTRAINT "report_cash_count_report_id_report_fkey" FOREIGN KEY (report_id) REFERENCES pettycash_test.report(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."report_history" ADD CONSTRAINT "report_history_report_id_fkey" FOREIGN KEY (report_id) REFERENCES pettycash_test.report(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."report_history" ADD CONSTRAINT "report_history_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."report_sale_detail" ADD CONSTRAINT "fk_report_sale_detail_sale_info" FOREIGN KEY (sale_info_id) REFERENCES pettycash_test.sale_info(id) ON DELETE RESTRICT;
ALTER TABLE pettycash_test."report_sale_detail" ADD CONSTRAINT "report_sale_detail_report_id_fkey" FOREIGN KEY (report_id) REFERENCES pettycash_test.report(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."report_sale_detail" ADD CONSTRAINT "report_sale_detail_sale_id_fkey" FOREIGN KEY (sale_id) REFERENCES pettycash_test.entity_sale_setting(sale_id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."role_permissions" ADD CONSTRAINT "role_permissions_permission_id_fkey" FOREIGN KEY (permission_id) REFERENCES pettycash_test.permissions(id);
ALTER TABLE pettycash_test."role_permissions" ADD CONSTRAINT "role_permissions_role_id_fkey" FOREIGN KEY (role_id) REFERENCES pettycash_test.roles(id);
ALTER TABLE pettycash_test."sale_info" ADD CONSTRAINT "sale_info_entity_id_fkey1" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."shop_expense" ADD CONSTRAINT "shop_expense_report_id_fkey" FOREIGN KEY (report_id) REFERENCES pettycash_test.report(id);
ALTER TABLE pettycash_test."subscription_email_log" ADD CONSTRAINT "subscription_email_log_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."subscription_invoice" ADD CONSTRAINT "fk_subscription_invoice_currency" FOREIGN KEY (currency) REFERENCES pettycash_test.currency_info(currency_code);
ALTER TABLE pettycash_test."subscription_invoice_line" ADD CONSTRAINT "subscription_invoice_line_invoice_id_fkey" FOREIGN KEY (invoice_id) REFERENCES pettycash_test.subscription_invoice(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."subscription_transfer" ADD CONSTRAINT "fk_subscription_transfer_entity" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."terms_consent" ADD CONSTRAINT "fk_terms_consent_user" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."user_entity" ADD CONSTRAINT "user_entity_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."user_entity" ADD CONSTRAINT "user_entity_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."user_stripe_customer" ADD CONSTRAINT "fk_user_stripe_customer_currency" FOREIGN KEY (currency) REFERENCES pettycash_test.currency_info(currency_code);
ALTER TABLE pettycash_test."user_stripe_customer" ADD CONSTRAINT "user_stripe_customer_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."user_token" ADD CONSTRAINT "user_token_user_id_fkey" FOREIGN KEY (user_id) REFERENCES pettycash_test."user"(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_bank_transfer" ADD CONSTRAINT "xero_bank_transfer_sync_report_id_fkey" FOREIGN KEY (sync_report_id) REFERENCES pettycash_test.report(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."xero_bill_response_line" ADD CONSTRAINT "fk_xero_bill_response_line_xero_bill_sync_id" FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_bill_sync" ADD CONSTRAINT "fk_xero_bill_sync_bill_id" FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_bill_sync_line" ADD CONSTRAINT "fk_xero_bill_sync_line_bill_line_item_id" FOREIGN KEY (bill_line_item_id) REFERENCES pettycash_test.bill_line_item(id) ON DELETE SET NULL;
ALTER TABLE pettycash_test."xero_bill_sync_line" ADD CONSTRAINT "fk_xero_bill_sync_line_xero_bill_sync_id" FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_bill_sync_payload" ADD CONSTRAINT "fk_xero_bill_sync_payload_xero_bill_sync_id" FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_contact_sync" ADD CONSTRAINT "xero_contact_sync_entity_id_fkey" FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities(id) ON DELETE CASCADE;
ALTER TABLE pettycash_test."xero_report_sync" ADD CONSTRAINT "xero_report_sync_report_id_fkey" FOREIGN KEY (report_id) REFERENCES pettycash_test.report(id) ON DELETE SET NULL;


-- ###########################################################################
-- ### 26_views.sql
-- ###########################################################################

-- --------------------------------------------------------------------------
-- pettycash_test :: views
--
-- tracker - the only view in the schema.
--
-- The source definition joins on ::text casts (ef.id::text = efm.entity_function_id::text)
-- because both sides were varchar(36). With uuid on both sides those casts are
-- worse than redundant: a cast on the indexed side stops the planner using the
-- index, so the view would quietly get slower after a migration meant to help it.
-- They are removed here.
--
-- Comparisons against genuine text columns - publishing_status, status, published,
-- function_code - keep their casts, because those columns really are text.
-- --------------------------------------------------------------------------

\set ON_ERROR_STOP on


CREATE VIEW pettycash_test.tracker AS
SELECT e.name AS "entities.name",
    e.id AS entity_id,
    (EXISTS ( SELECT 1
           FROM pettycash_test.entity_function_map efm
             JOIN pettycash_test.entity_function ef ON ef.id = efm.entity_function_id
          WHERE efm.entity_id = e.id AND ef.function_code::text = 'PETTY_CASH'::text AND efm.is_enabled = true)) AS pettycash,
    (EXISTS ( SELECT 1
           FROM pettycash_test.entity_function_map efm
             JOIN pettycash_test.entity_function ef ON ef.id = efm.entity_function_id
          WHERE efm.entity_id = e.id AND ef.function_code::text = 'BILL'::text AND efm.is_enabled = true)) AS billing,
    rpt.pc_latest_submitted,
    rpt.pc_latest_published,
    bil.num_paid,
    bil.num_partialpaid,
    bil.num_unpaid,
    bil.num_published,
    bil.latest_bill_published,
    bil.latest_bill_update
   FROM pettycash_test.entities e
     LEFT JOIN LATERAL ( SELECT max(r.transaction_date) FILTER (WHERE true) AS pc_latest_submitted,
            max(r.transaction_date) FILTER (WHERE r.publishing_status::text = 'completed'::text) AS pc_latest_published
           FROM pettycash_test.report r
          WHERE r.company = e.id) rpt ON true
     LEFT JOIN LATERAL ( SELECT count(*) FILTER (WHERE b.status::text = 'paid'::text) AS num_paid,
            count(*) FILTER (WHERE b.status::text = 'partially_paid'::text) AS num_partialpaid,
            count(*) FILTER (WHERE b.status::text = 'submitted'::text) AS num_unpaid,
            count(*) FILTER (WHERE b.published::text = 'published'::text) AS num_published,
            max(b.updated_at) FILTER (WHERE b.published::text = 'published'::text) AS latest_bill_published,
            ( SELECT max(t.ts) AS max
                   FROM ( SELECT b2.updated_at AS ts
                           FROM pettycash_test.bill b2
                          WHERE b2.entity_id::text = e.id::text
                        UNION ALL
                         SELECT b2.created_at AS ts
                           FROM pettycash_test.bill b2
                          WHERE b2.entity_id::text = e.id::text) t) AS latest_bill_update
           FROM pettycash_test.bill b
          WHERE b.entity_id = e.id) bil ON true;;


-- ###########################################################################
-- ### 24_comments.sql
-- ###########################################################################

-- --------------------------------------------------------------------------
-- pettycash_test :: the defect register
--
-- Every finding from the database normalization audit, attached to the object
-- it describes. NOTHING HERE CHANGES BEHAVIOUR - these are comments. The point
-- is that the audit travels with the database instead of living in a document
-- that goes stale, so the next cleanup pass reads pg_description rather than
-- repeating the work.
--
-- The prose report is docs/code_cleanse/Code Cleanse - Database Normalization.docx.
-- Both are generated from one source, so they cannot disagree.
--
-- Measured 3 September 2026 against production-backup, local postgres and Supabase, at commit 0f4a32f.
-- --------------------------------------------------------------------------


-- ==========================================================================
-- A. DEAD - no reader, no writer, in any of the four repositories
-- Kept, not dropped: dropping a column is a behaviour change and does not belong
-- in the same step as a type migration. These 11 are the shortlist for a later pass.
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.entities.note IS
    'DEAD as of 3 September 2026: No reference anywhere outside the model declaration. '
    'Non-null in 0 of 82 production rows.';

COMMENT ON COLUMN pettycash_test.entities.timezone IS
    'DEAD as of 3 September 2026: No reference outside the model. The only per-entity '
    'timezone field, and NULL everywhere - which is why the UTC migration must fall back to a '
    'single global Asia/Hong_Kong. Non-null in 0 of 82 production rows.';

COMMENT ON COLUMN pettycash_test.entities.deposit_day IS
    'DEAD as of 3 September 2026: Model declaration only. Non-null in 0 of 82 production '
    'rows.';

COMMENT ON COLUMN pettycash_test.entities.deposit_frequency IS
    'DEAD as of 3 September 2026: Model declaration only. Non-null in 0 of 82 production '
    'rows.';

COMMENT ON COLUMN pettycash_test.entities.minimum_qty IS
    'DEAD as of 3 September 2026: Model declaration only. Non-null in 0 of 82 production '
    'rows.';

COMMENT ON COLUMN pettycash_test.entities.xero_short_code IS
    'DEAD as of 3 September 2026: Model declaration only. Non-null in 0 of 82 production '
    'rows.';

COMMENT ON COLUMN pettycash_test.attachment.deleted_at IS
    'DEAD as of 3 September 2026: Model only. The sole other mention is an aspirational line '
    'in a Korean design doc. Non-null in 0 of 592 production rows.';

COMMENT ON COLUMN pettycash_test.attachment.checksum_sha256 IS
    'DEAD as of 3 September 2026: billing-backend bills/models.py:193 declares it; ZERO write '
    'sites. Integrity checking was never implemented. Empty string in all 592 rows. Non-null '
    'in 0 of 592 production rows.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.retry_count IS
    'DEAD as of 3 September 2026: ZERO write sites - never incremented. Echoed in '
    'api_xero.py:99 only. Non-null in 0 of 470 production rows.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.last_retry_at IS
    'DEAD as of 3 September 2026: ZERO write sites. Pairs with retry_count: the retry '
    'mechanism does not exist. Non-null in 0 of 470 production rows.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync_line.response_tax_amount IS
    'DEAD as of 3 September 2026: Echoed in api_xero.py:35, never assigned. Non-null in 0 of '
    '416 production rows.';


-- ==========================================================================
-- B. EMPTY IN THE DATA, BUT THE CODE IS ALIVE - do NOT drop
-- NULL everywhere, yet a working read and write path exists. The data is empty
-- for a reason that is not deadness.
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.user.reset_token IS
    'NOT DEAD despite being empty: NULL is the RESTING STATE. password_reset.py:22-23 sets '
    'it; it is cleared once the reset completes. A value exists only inside a 1-hour window.';

COMMENT ON COLUMN pettycash_test.user.reset_token_expiry IS
    'NOT DEAD despite being empty: Same flow: set at password_reset.py:24, cleared at line '
    '89.';

COMMENT ON COLUMN pettycash_test.report.receipt_files IS
    'NOT DEAD despite being empty: Read in 4 places (report_detail.py:102,448-449; selected '
    'in cash_count.py, deposit.py, sales.py). The feature reads it; nothing has populated it '
    'yet.';

COMMENT ON COLUMN pettycash_test.shop_expense.s3_key IS
    'NOT DEAD despite being empty: api.py:1056-1057 explicitly sets it to None. Uploads use a '
    'LOCAL s3_key variable and a different storage path.';

COMMENT ON COLUMN pettycash_test.user.user_phone IS
    'NOT DEAD despite being empty: Editable profile field - roles.py:317 allows it, 346 and '
    '368 return it.';

COMMENT ON COLUMN pettycash_test.entity_function_map.settings_json IS
    'NOT DEAD despite being empty: Written by billing-backend api_config.py:185.';


-- ==========================================================================
-- C. MONEY STORED AS BINARY FLOAT
-- 21 money columns and 2 quantity columns are double precision. This is a
-- petty-cash system whose job is reconciling counted cash against recorded cash -
-- and report.discrepancy_amount, the field that measures the mismatch, is a float.
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.cash_info.cash_value IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.actual_cash_total IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.adjusted_opening_balance IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.bank_deposit IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.cash_addition IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.cash_sales IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.closing_balance IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.delivery_sales IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.discrepancy_amount IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.expenses IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.opening_balance IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.safe_box_balance IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.shop_sales IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report.total_sales IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.report_sale_detail.amount IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.shop_expense.amount IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.subtotal IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.total IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.total_tax IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.unit_amount IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.amount IS
    'Money stored as double precision. Binary floats cannot represent 0.10 exactly, so sums '
    'drift. The schema carries THREE money conventions: double precision here, numeric on the '
    'billing side (bill.amount, payment.amount, xero_bill_* amounts), integer cents in '
    'subscriptions (billing_plan.amount, subscription_invoice.total). Target: numeric(14,2).';

COMMENT ON COLUMN pettycash_test.entity_cash_detail_v2.cash_instock IS
    'A count stored as double precision. Should be an integer or numeric.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.quantity IS
    'A quantity stored as double precision. Should be numeric.';


-- ==========================================================================
-- D. DUPLICATED XERO TOKEN STATE
-- Two sources of truth for a live credential.
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.user.access_token IS
    'DUPLICATED credential state: this column also exists on user_token. token_service.py:306 '
    'copies one into the other. Where both exist they agree (73 users, 0 divergences), but 29 '
    'users have user.access_token set and NO user_token row - the extraction to user_token '
    'was never finished.';

COMMENT ON COLUMN pettycash_test.user.refresh_token IS
    'DUPLICATED credential state: this column also exists on user_token. token_service.py:306 '
    'copies one into the other. Where both exist they agree (73 users, 0 divergences), but 29 '
    'users have user.access_token set and NO user_token row - the extraction to user_token '
    'was never finished.';

COMMENT ON COLUMN pettycash_test.user.id_token IS
    'DUPLICATED credential state: this column also exists on user_token. token_service.py:306 '
    'copies one into the other. Where both exist they agree (73 users, 0 divergences), but 29 '
    'users have user.access_token set and NO user_token row - the extraction to user_token '
    'was never finished.';

COMMENT ON COLUMN pettycash_test.user.expires_in IS
    'DUPLICATED credential state: this column also exists on user_token. token_service.py:306 '
    'copies one into the other. Where both exist they agree (73 users, 0 divergences), but 29 '
    'users have user.access_token set and NO user_token row - the extraction to user_token '
    'was never finished.';

COMMENT ON COLUMN pettycash_test.user.token_created_at IS
    'DUPLICATED credential state: this column also exists on user_token. token_service.py:306 '
    'copies one into the other. Where both exist they agree (73 users, 0 divergences), but 29 '
    'users have user.access_token set and NO user_token row - the extraction to user_token '
    'was never finished.';

COMMENT ON COLUMN pettycash_test.user_token.access_token IS
    'DUPLICATED credential state: the same value is also held on the user table. See the '
    'matching user.* column. 29 users exist only in the legacy user.* copy.';

COMMENT ON COLUMN pettycash_test.user_token.refresh_token IS
    'DUPLICATED credential state: the same value is also held on the user table. See the '
    'matching user.* column. 29 users exist only in the legacy user.* copy.';

COMMENT ON COLUMN pettycash_test.user_token.id_token IS
    'DUPLICATED credential state: the same value is also held on the user table. See the '
    'matching user.* column. 29 users exist only in the legacy user.* copy.';

COMMENT ON COLUMN pettycash_test.user_token.access_token_expires_in IS
    'DUPLICATED credential state: the same value is also held on the user table. See the '
    'matching user.* column. 29 users exist only in the legacy user.* copy.';

COMMENT ON COLUMN pettycash_test.user_token.access_token_obtained_at IS
    'DUPLICATED credential state: the same value is also held on the user table. See the '
    'matching user.* column. 29 users exist only in the legacy user.* copy.';


-- ==========================================================================
-- E. REFERENTIAL INTEGRITY NOT ENFORCED - 54 id columns carry no foreign key
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.account_info.xero_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.audit.user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.bill.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.bill.xero_contact_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.bill_attachment.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.bill_attachment.xero_attachment_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.entities.xero_org_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.entity_account_xero.xero_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.entity_account_xero.xero_org_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.entity_bill_account_xero.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_bill_account_xero.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_bill_account_xero.xero_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.entity_bill_currency.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_bill_currency.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_function_map.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_function_map.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.entity_sale_setting.sale_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.payment.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.payment.xero_payment_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.payment_attachment.created_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.payment_attachment.xero_attachment_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.share_link.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.shop_expense.account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.shop_expense.contact_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.subscription_audit_log.actor_user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_audit_log.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_audit_log.payer_user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_invoice.billing_group_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_invoice.payer_user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_invoice_line.entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_transfer.from_user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.subscription_transfer.to_user_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.user.current_entity_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.user.xero_entity_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.sync_report_id IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.xero_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.xero_bank_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.xero_bank_transaction_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.xero_contact_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.from_bank_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.from_bank_transaction_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.to_bank_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.to_bank_transaction_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.xero_bank_transfer_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_response_line.account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_response_line.xero_line_item_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.request_contact_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.requested_by IS
    'NO FOREIGN KEY: this references one of our own tables with nothing preventing a dangling '
    'value. 54 id columns are unenforced this way; the two legacy users'' ~800 orphan-prone '
    'rows survived precisely because nothing checked.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.response_invoice_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync.xero_response_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync_line.response_account_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_bill_sync_line.response_line_item_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_contact_sync.xero_contact_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';

COMMENT ON COLUMN pettycash_test.xero_contact_sync.xero_org_id IS
    'NO FOREIGN KEY, and none is possible: this identifier is owned by Xero, not by us. Stays '
    'text through the uuid migration; empty strings are nulled.';


-- ==========================================================================
-- F. FREE-TEXT ENUMS - no CHECK constraint, no lookup table, no shared convention
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.account_info.bank_account_type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.account_info.class_type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.account_info.status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.cash_info.type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.entities.status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery). CONFLATES TWO DOMAINS: Xero '
    'connection state (connected 49, disconnected 17) and account lifecycle (onboarding 7, '
    'active 7, cancelled 2). One column answering two questions, so neither can be queried '
    'cleanly.';

COMMENT ON COLUMN pettycash_test.entity_account_xero.type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.entity_cash_detail_v2.cash_type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.entity_module_subscription.extension_state IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.entity_sale_setting.type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.report.discrepancy_type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.report.publishing_status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery). USES NULL *AND* EMPTY STRING '
    'FOR THE SAME STATE: completed 2729, NULL 1024, failed 10, '''' 1. Any IS NULL check misses '
    'that one row.';

COMMENT ON COLUMN pettycash_test.report.status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.report.withdrawal_type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.report_sale_detail.type IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.subscription_audit_log.extension_state IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.subscription_invoice.payment_method IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.xero_bank_transfer.status IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';

COMMENT ON COLUMN pettycash_test.xero_contact_sync.category IS
    'Free-text enum: no CHECK constraint and no lookup table. Casing convention differs per '
    'column across the schema (account_info.status is ACTIVE/INACTIVE, entities.status is '
    'lowercase, report_sale_detail.type is Electronic/Delivery).';


-- ==========================================================================
-- G. NAMING INCONSISTENCY and 1NF
-- Renaming was considered and declined: the cost lands in application code, and
-- keeping this migration purely type-level keeps that stage small.
-- ==========================================================================

COMMENT ON COLUMN pettycash_test.report_sale_detail.create_at IS
    'NAMING: creation timestamp named create_at; 40 other tables use created_at.';

COMMENT ON COLUMN pettycash_test.user_entity.create_at IS
    'NAMING: creation timestamp named create_at, and this table ALSO carries joined_at - two '
    'creation timestamps on one row.';

COMMENT ON COLUMN pettycash_test.user_entity.joined_at IS
    'NAMING: second creation timestamp on a table that already has create_at.';

COMMENT ON COLUMN pettycash_test.xero_bank_transaction.create_at IS
    'NAMING: creation timestamp named create_at; 40 other tables use created_at.';

COMMENT ON COLUMN pettycash_test.entity_sale_setting.create_date IS
    'NAMING: creation timestamp named create_date; 40 other tables use created_at.';

COMMENT ON COLUMN pettycash_test.report_history.timestamp IS
    'NAMING: creation timestamp named timestamp; 40 other tables use created_at.';

COMMENT ON COLUMN pettycash_test.report.company IS
    'NAMING: this is the entity reference. Every other table calls it entity_id, and this one '
    'carries no FK - which is why the tracker view must join r.company::text = e.id::text.';

COMMENT ON COLUMN pettycash_test.report.uploaded_by IS
    'NAMING and MODELLING: foreign key to user.username, NOT user.id. The only user reference '
    'in the schema targeting a mutable natural key.';

COMMENT ON COLUMN pettycash_test.report.xero_integrated_yes IS
    'NAMING: boolean whose name ends in _yes. 19 booleans use is_*; 5 do not.';

COMMENT ON COLUMN pettycash_test.entity_sale_setting.enabled IS
    'NAMING: same concept as is_active (10 tables) and is_enabled (2 tables). Three spellings '
    'for one idea.';

COMMENT ON COLUMN pettycash_test.entity_bill_currency.is_enabled IS
    'NAMING: same concept as is_active (10 tables) and enabled (1 table).';

COMMENT ON COLUMN pettycash_test.entity_function_map.is_enabled IS
    'NAMING: same concept as is_active (10 tables) and enabled (1 table).';

COMMENT ON COLUMN pettycash_test.billing_plan.currency IS
    'NAMING: FK to currency_info.currency_code, while entities/cash_info/country_info use '
    'currency_id -> currency_info.id. Two different keys of one table used as FK targets, so '
    'currency cannot be joined uniformly.';

COMMENT ON COLUMN pettycash_test.subscription_invoice.currency IS
    'NAMING: FK to currency_info.currency_code. See billing_plan.currency.';

COMMENT ON COLUMN pettycash_test.user_stripe_customer.currency IS
    'NAMING: FK to currency_info.currency_code. See billing_plan.currency.';

COMMENT ON COLUMN pettycash_test.cash_info.cash_name IS
    'NAMING: lookup tables prefix the name column at random - sale_info.name and '
    'account_info.name against cash_info.cash_name, currency_info.currency_name, '
    'entity_function.function_name.';

COMMENT ON COLUMN pettycash_test.shop_expense.files IS
    '1NF VIOLATION: 1049 of 10235 rows hold several S3 paths joined by commas; '
    'report_detail.py:449 parses them with .split('',''). A repeating group in a scalar column. '
    'The fix is a child table.';


-- ==========================================================================
-- H. TABLE-LEVEL FINDINGS
-- ==========================================================================

COMMENT ON TABLE pettycash_test.entity_account_xero IS
    '1:1 SHADOW of account_info - all 2530 rows join on account_id. Duplicates type, name and '
    'xero_account_id, adding only xero_org_id and is_active. THE DUPLICATION HAS ALREADY '
    'DRIFTED: name disagrees in 2 rows - account_info says ''Cleaning Service Fee'' where this '
    'table says ''Professional expense - Cleaning'' and ''Cleaning expense''. Also: PK (id, '
    'account_id) is redundant (both columns independently unique); column id matches neither '
    'entities.id nor account_info.id; named entity_* but has no entity_id.';

COMMENT ON TABLE pettycash_test.roles IS
    '6 rows (Admin, Accountant, Entity Base, Cashier, Super Admin, Shop Manager) but '
    'user_entity.role stores lowercase free text - admin 149, accountant 100, shop_manager '
    '68, cashier 21 - with NO foreign key. Different case, no link. permissions and '
    'role_permissions are empty in all three databases.';

COMMENT ON TABLE pettycash_test.permissions IS
    'EMPTY in all three databases. The permission model was designed and never populated. See '
    'roles.';

COMMENT ON TABLE pettycash_test.role_permissions IS
    'EMPTY in all three databases. See roles.';

COMMENT ON TABLE pettycash_test.auth_user IS
    'Dead Django install - empty in all three databases. Minty authenticates through its own '
    'user table.';

COMMENT ON TABLE pettycash_test.auth_group IS
    'Dead Django install - empty in all three databases.';

COMMENT ON TABLE pettycash_test.auth_user_groups IS
    'Dead Django install - empty in all three databases.';

COMMENT ON TABLE pettycash_test.auth_group_permissions IS
    'Dead Django install - empty in all three databases.';

COMMENT ON TABLE pettycash_test.auth_user_user_permissions IS
    'Dead Django install - empty in all three databases.';

COMMENT ON TABLE pettycash_test.auth_permission IS
    'Dead Django install - 100 rows of framework bookkeeping for an auth system this app does '
    'not use. Entangled with the roles/permissions decision.';

COMMENT ON TABLE pettycash_test.django_content_type IS
    'Dead Django install - 25 rows of framework bookkeeping.';

COMMENT ON TABLE pettycash_test.django_migrations IS
    'Dead Django install - 32 rows of framework bookkeeping.';

