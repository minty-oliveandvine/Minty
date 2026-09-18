CODE CLEANSE - REFERENCE DOCUMENT

# Database

Four repositories, one schema  -  who touches it and what breaks

Revision 1 - measured 3 September 2026, at commit 41e1d18

Minty and billing-backend are two applications on ONE database. Both connect with search_path=pettycashv2,public - Minty through SQLALCHEMY_DATABASE_URI, billing-backend through config/settings.py:74 - and billing-backend mirrors six Minty-owned tables with managed = False so Django will never migrate them. That arrangement works, but it has a sharp edge: a column change in Minty cannot fail billing-backend's migrations, because billing-backend has no migrations for those tables. It fails at runtime instead, in whichever request happens to touch the column first.

This document exists so that a schema change can be planned against the code rather than discovered by it. It lists every file that depends on the database, ordered by how badly it depends. Unlike the four repository work documents, it lists files whether or not they have lint findings - a clean file that owns a table still matters the day the column moves.

## How to read the tiers

| Tier | What it means |
| --- | --- |
| RAW SQL | Builds or executes SQL as text. Invisible to a model refactor and to any IDE rename. If the table name is not schema-qualified it also depends on search_path being right. Highest risk tier. |
| MODEL | Declares a table. Changing a column here is a migration, not a refactor. |
| ORM | Reads or writes through the ORM/session. Survives a rename of the Python attribute; breaks when the underlying column is dropped. |
| PLUMBING | Engine, session, search_path, connection URI, Alembic wiring. Few files, but they decide which database everything else talks to. |

## The shared surface: tables Minty owns and billing-backend uses

These are the tables Minty owns and billing-backend reads through Django models marked managed = False. Four of the seven are also WRITTEN from billing-backend, and three of those carry docstrings calling themselves read-only. That contradiction is the single most important thing in this document: the declared contract and the actual behaviour disagree, across a repository boundary, on tables another application owns.

| Table | Declared in | Posture | Where billing-backend touches it |
| --- | --- | --- | --- |
| user | shared_models/models.py | WRITTEN - and the docstring says 'Read-only mirror' | profile_service.py:92 user.save(); api_profile.py raw UPDATE "user"; api_session.py sets signed_in_at / last_seen_at |
| xero_contact_sync | shared_models/models.py | WRITTEN - and the docstring says 'Read-only mirror' | contact_service.py:331 row.save(); :333 objects.create() |
| account_info | shared_models/models.py | WRITTEN - and the docstring says 'Read-only mirror' | api_config.py:393 .update(status=...) mirroring is_active back to Minty |
| currency_info | bills/models.py (not shared_models) | WRITTEN via ORM and reshaped by migrations | api_config.py ORM create/update; migrations 0012 and 0019 |
| entities | shared_models/models.py | Read-only | api_session.py, api_config.py, api.py, core/views.py, contact_service.py, xero_publish_service.py, xero_token_service.py |
| user_entity | shared_models/models.py | Read-only, and ONLY via raw SQL | core/auth.py, bills/api_profile.py, bills/api_config.py - all unqualified |
| entity_module_subscription | shared_models/models.py | Read-only, and ONLY via raw SQL | bills/api_profile.py - a 5-column mirror; raw SQL on payer_user_id and phase |
| country_info | NOT MODELLED ANYWHERE | Read via raw SQL only | core/management/commands/generate_token.py - schema-qualified |

## Minty  -  files that depend on the database

Flask + SQLAlchemy + Alembic. 42 model files declaring 44 tables. Ordered by tier, most severe first.

### RAW SQL   6 files

Minty has NO unqualified raw SQL. Every statement that names a table carries the pettycashv2 prefix, and the three that do not name a table do not need it.

| File | Schema | What it does |
| --- | --- | --- |
| blueprints/entity/services/settings.py | QUALIFIED | 5 text() statements - SELECT / UPDATE / INSERT / DELETE on {_TBL}, plus SELECT 1 FROM pettycashv2.account_info. _TBL is declared function-locally at lines 492 and 786 as 'pettycashv2.entity_bill_account_xero'. Also a pg_insert upsert naming the constraint uq_account_info_entity_xero_account as a literal string - schema-safe, rename-fragile. |
| blueprints/entity/services/onboarding_bill_codes.py | QUALIFIED | SELECT plus 2 UPDATEs on {_TBL}, declared as a module constant at line 20. All user values are bound parameters, so the 3 S608 findings are false positives for injection. |
| blueprints/subscription/services/clock.py | NO TABLE | text("SELECT now()") - reads the database server clock as one of three trusted time sources. Qualification does not apply. |
| blueprints/subscription/services/daily.py | NO TABLE | pg_try_advisory_lock / pg_advisory_unlock on its own db.engine.connect() - the two-worker guard for the daily jobs. |
| services/auth/token_service.py | NO TABLE | pg_try_advisory_lock(:ns, hashtext(:k)) on a separate AUTOCOMMIT connection, so the lock is not held by the request transaction. |
| blueprints/subscription/models/subscription_transfer.py | NO TABLE | db.text(f"status IN ({_OPEN})") inside its own __table_args__ - a partial-index predicate, not a query. |

### MODEL   42 files, 44 tables

Each of these owns its table. A column change here is a migration.

| File | Table(s) it declares |
| --- | --- |
| blueprints/auth/models/email_otp.py | email_otp |
| blueprints/auth/models/user.py | user |
| blueprints/auth/models/user_token.py | user_token |
| blueprints/entity/models/cash_info.py | cash_info |
| blueprints/entity/models/country_info.py | country_info |
| blueprints/entity/models/currency_info.py | currency_info |
| blueprints/entity/models/entity.py | entities |
| blueprints/entity/models/entity_cash_detail_v2.py | entity_cash_detail_v2 |
| blueprints/entity/models/entity_cash_setting.py | entity_cash_setting |
| blueprints/entity/models/entity_function.py | entity_function, entity_function_map |
| blueprints/entity/models/entity_pettycash_settings.py | entity_pettycash_settings |
| blueprints/entity/models/entity_sale_setting.py | entity_sale_setting |
| blueprints/entity/models/sale_info.py | sale_info |
| blueprints/entity/models/user_entity.py | user_entity |
| blueprints/invitation/models/invitation.py | invitations |
| blueprints/legal/models/terms_consent.py | terms_consent |
| blueprints/report/models/report.py | report |
| blueprints/report/models/report_cash_count.py | report_cash_count |
| blueprints/report/models/report_history.py | report_history |
| blueprints/report/models/report_sale_detail.py | report_sale_detail |
| blueprints/report/models/share_link.py | share_link |
| blueprints/report/models/shop_expense.py | shop_expense |
| blueprints/subscription/models/billing_plan.py | billing_plan |
| blueprints/subscription/models/billing_policy.py | billing_policy |
| blueprints/subscription/models/entity_billing_consent.py | entity_billing_consent |
| blueprints/subscription/models/entity_billing_group.py | entity_billing_group |
| blueprints/subscription/models/entity_module_subscription.py | entity_module_subscription |
| blueprints/subscription/models/payer_billing_group.py | payer_billing_group |
| blueprints/subscription/models/subscription_audit_log.py | subscription_audit_log |
| blueprints/subscription/models/subscription_email_log.py | subscription_email_log |
| blueprints/subscription/models/subscription_invoice.py | subscription_invoice, subscription_invoice_line |
| blueprints/subscription/models/subscription_transfer.py | subscription_transfer |
| blueprints/subscription/models/user_stripe_customer.py | user_stripe_customer |
| blueprints/user_management/models/permissions.py | permissions |
| blueprints/user_management/models/role_permissions.py | role_permissions |
| blueprints/user_management/models/roles.py | roles |
| blueprints/xero/models/account_info.py | account_info |
| blueprints/xero/models/entity_account_xero.py | entity_account_xero |
| blueprints/xero/models/xero_bank_transaction.py | xero_bank_transaction |
| blueprints/xero/models/xero_bank_transfer.py | xero_bank_transfer |
| blueprints/xero/models/xero_contact_sync.py | xero_contact_sync |
| blueprints/xero/models/xero_report_sync.py | xero_report_sync |

### ORM   86 files

Query or write through the session without declaring a table or running raw SQL. Listed by area rather than individually - a rename survives these, a column drop does not.

| Area | n | Files |
| --- | --- | --- |
| blueprints/auth | 8 | dashboard.py, email_auth.py, email_auth.py, identity.py, login.py, password_reset.py, permissions.py, register.py |
| blueprints/entity | 14 | billing_sync.py, create.py, list.py, modules.py, modules.py, onboarding_account_codes.py, onboarding_invites.py, onboarding_state.py, onboarding_xero.py, payment_methods.py, settings.py, shared.py, xero_account_mapping_post.py, xero_mapping_form_context.py |
| blueprints/invitation | 3 | accept.py, api.py, invite.py |
| blueprints/legal | 4 | accept.py, admin.py, consent.py, documents.py |
| blueprints/report | 21 | api.py, cash_count.py, cash_denominations.py, create.py, deposit.py, download.py, ending.py, expense.py, export_screenshot.py, history.py, history_query.py, legacy.py, module_guard.py, opening.py, report_detail.py, report_detail.py, report_download.py, sales.py, share.py, shared.py, submitted.py |
| blueprints/subscription | 16 | access_sweep.py, cards.py, catalog.py, checkout.py, consent.py, money.py, notices.py, notify.py, panel.py, payment_methods.py, policy.py, portal.py, portal.py, renewals.py, store.py, transfers.py |
| blueprints/user_management | 6 | admin_dashboard.py, approve_reject_access.py, create_user.py, find_user.py, roles.py, roles.py |
| blueprints/xero | 6 | integration.py, publish.py, publish_resolution.py, routes.py, settings.py, settings.py |
| cli | 2 | modules.py, subscription_access.py |
| pettycash | 1 | hooks.py |
| services | 5 | permission_policy.py, session.py, user_presence.py, xero_bridge.py, xero_service.py |

### PLUMBING   8 files

| File | What it decides |
| --- | --- |
| models/db.py | Declares db = SQLAlchemy() and imports all 42 model modules. The single registration chokepoint - see the P1 note in the Minty work document. |
| services/app_runtime/legacy/bootstrap.py | Chooses the URI (RDS_DATABASE_URI vs LOCAL_DATABASE_URI), sets pool options, calls db.init_app() and Migrate(), and puts the session table in the pettycashv2 schema. |
| migrations/env.py | Alembic wiring; pins version_table_schema='pettycashv2'. |
| config.py | SQLALCHEMY_LOCAL_DATABASE_URI / SQLALCHEMY_RDS_DATABASE_URI. |
| default_settings.py | SQLALCHEMY_DATABASE_URI from RDS_DATABASE_URI. |
| pettycash/core/hooks.py | Per-request teardown: db.session.rollback() and db.session.remove(). Also does ORM reads. |
| docker/docker-entrypoint.sh | The only place outside the app that builds its own engine: create_engine(), SELECT 1, then CREATE SCHEMA IF NOT EXISTS pettycashv2. |
| tests/conftest.py | Points both URIs at a SQLite file and imports main, building the whole engine. Note that 27 test files each carry their OWN duplicated schema-bootstrap fixture; conftest contains no database code at all. |

## billing-backend  -  files that depend on the database

Django 5. 19 migrations, head 0019, clean tree. Runs on search_path=pettycashv2,public.

### RAW SQL   6 sites

THREE OF THESE ARE UNQUALIFIED, against tables Minty owns. This is the highest-risk finding in this document.

| File | Schema | What it does |
| --- | --- | --- |
| core/auth.py | UNQUALIFIED | Three raw SELECTs on user_entity (lines 17, 65, 189) with a bare table name, on the authorisation path. A wrong search_path makes permission checks fail open or closed. |
| bills/api_profile.py | UNQUALIFIED | SELECT on user_entity; a join over entity_module_subscription and entities; and UPDATE "user" SET approved, access_token, refresh_token, id_token, expires_in, signed_in_at. Four Minty-owned tables, all bare. |
| bills/api_config.py | UNQUALIFIED | SELECT on user_entity and a join on entities - both bare. |
| core/api_session.py | QUALIFIED | Joins pettycashv2.entities to pettycashv2.currency_info. Its docstring explains the raw SQL: 'entities is Flask-managed'. This is the pattern the three above should follow. |
| core/management/commands/generate_token.py | QUALIFIED | Reads pettycashv2.country_info and pettycashv2.currency_info - the only access to country_info anywhere, and it has no model. |
| scripts/repair_missing_tables.sql | MIXED | Standalone DDL repair script for 12 bills tables plus a django_migrations insert. |

### MODEL   2 files, 21 models

| File | What it declares |
| --- | --- |
| bills/models.py | 15 models. 14 are owned by this repo (bill, bill_line_item, audit, payment, attachment, bill_attachment, payment_attachment, entity_function, entity_function_map, entity_bill_account_xero, entity_bill_currency, xero_bill_sync, xero_bill_sync_line, xero_bill_sync_payload, xero_bill_response_line). CurrencyInfo is managed = False and belongs to Minty. |
| shared_models/models.py | 6 models, ALL managed = False - the mirror layer. See the table above for which of them this repo writes. |

### ORM   17 files

bills/api.py, api_audit.py, api_payments.py, api_xero.py, api_xero_actions.py; services/{bill,payment,attachment,audit,contact,profile,xero_publish,xero_token}_service.py and bill_reference_generator.py; core/entitlements.py, core/views.py; plus conftest.py and 26 test modules.

### PLUMBING   5 files

| File | What it decides |
| --- | --- |
| config/settings.py | DATABASES default plus OPTIONS -c search_path=pettycashv2,public at line 74. Everything unqualified in this repo depends on it. |
| config/settings_test.py | Overrides to in-memory SQLite and sets SHARED_MODELS_MANAGED_FOR_TESTING. |
| shared_models/apps.py | ready() flips managed = True on the six mirrors under test settings, so tests can create them. |
| docker/entrypoint.sh | psycopg2 connect loop, then checks pettycashv2 exists, then runs migrate. |
| pytest.ini | --no-migrations, because the bills migrations are raw Postgres DDL and cannot run on SQLite. |

## billing-frontend and onboarding  -  no database dependency

No database dependency of any kind. Confirmed by searching every tracked file AND package-lock.json for pg, postgres, prisma, drizzle, knex, mysql, sequelize, typeorm, mongodb, supabase, sqlite and DATABASE_URL: zero hits in both repositories. All data arrives over HTTP. What follows is the indirect coupling - files whose correctness depends on the SHAPE of database rows delivered by the API.

### billing-frontend  -  schema-coupled files

| File | What it mirrors |
| --- | --- |
| lib/api.ts | The primary schema mirror in this repo, and 1,044 lines. Its types restate database columns one for one: BillListItem/BillDetail = bill; LineItem = bill_line_item; Attachment = attachment; PaymentItem = payment; AuditItem = audit; EntityBillAccount = entity_bill_account_xero. It also mirrors two Minty-owned tables: CurrencyInfo = currency_info and EntityBillContact = xero_contact_sync. |
| lib/paymentRequestBillMap.ts | The row mapper - reads bill.reference, amount, currency_code, description, contact, xero_contact_id, invoice_date, due_date, xero_account_code and line_items[0].account_code, and builds the PUT payload. |
| lib/payerPortal.ts | Types for Minty's payer endpoints, including ModuleStatus, which mirrors entity_module_subscription.phase semantics. |
| lib/billStatusDisplay.ts / billStatusRollback.ts | Enumerate the bill.status values (draft, submitted, returned, authorised, partially_paid, paid, voided, cancelled, sync_failed). A new status in the database that is not added here renders as unknown. |
| lib/moduleClaims.ts | function_code claims from entity_function / entity_function_map. |
| lib/useUserRole.ts | JWT claims mirroring user_entity.role and user.system_role. |
| lib/entityCurrency.ts | currency_code resolved via entities.currency_id. |
| lib/amountFormat.ts / currencyDisplay.ts | The decimal contract for numeric(14,2) columns - amount and line_amount are carried as strings to avoid float drift. |

### onboarding  -  schema-coupled files

| File | What it mirrors |
| --- | --- |
| lib/refData.js | Documents itself against pettycashv2.country_info and currency_info, and consumes the uuid primary keys the entities table references: country_id, country_name_en, country_code, currency_id, currency_name, iso_code. |
| components/OnboardingSteps.jsx | Maps country_id and currency_id into the selects that submit the entities.country_id / currency_id foreign keys, and resolves currency_id to iso_code for amount prefixes. It also collects entities.contact_phone and business_email, which migration c1a01 renamed and narrowed to varchar(20). |
| components/OnboardingApp.jsx | Carries entity_id end to end and persists onboarding progress keyed on it. |
| lib/billing.js | has_payment_method / has_billing_consent per entity and payer - the consent and billing-group surface. |

## Cross-repository coupling

For each shared table: the migration that shaped it, and the files on each side that would need to change if a column were renamed or dropped.

| Table / columns | Migration | Minty | billing-backend / other |
| --- | --- | --- | --- |
| user - signed_in_at, last_seen_at | p1a01_user_presence | blueprints/auth/models/user.py; services/user_presence.py; blueprints/auth/routes/leave_entity.py | shared_models/models.py; bills/api_profile.py; core/api_session.py |
| user - current_entity_id | p2a01_user_current_entity | blueprints/auth/models/user.py; services/user_presence.py | NOT MIRRORED - billing-backend clears the two presence columns on logout but leaves this one stale |
| entity_module_subscription - payer_user_id, phase, billed_through | a1b2c3d4e5f7, x1a01_transfer_schema | blueprints/subscription/models/entity_module_subscription.py; services/store.py, renewals.py, transfers.py | shared_models/models.py; bills/api_profile.py (raw SQL - the payer guard on account deactivation) |
| entity_function / entity_function_map | b8f3a2c1d4e5, m1a01_revoke_ungranted | blueprints/entity/services/modules.py; blueprints/subscription/services/access_sweep.py; cli/modules.py | bills/models.py; bills/api_config.py - a full UNGUARDED create/update/delete router |
| currency_info - uuid primary key | c8e0a2b4d6f8 -> billing-backend 0019 | blueprints/entity/models/currency_info.py; country_info.py; entity.py | bills/models.py; bills/migrations/0019 - RAISES unless Minty's migration ran first |
| entities - contact_phone (renamed), business_email | c1a01_entity_contact_fields | blueprints/entity/models/entity.py; forms.py; routes/create.py; services/onboarding_state.py; templates/entity/entity_create.html | onboarding: components/OnboardingSteps.jsx |
| payer_billing_group, entity_billing_group, subscription_invoice.billing_group_id | y1a01_billing_group_schema | ~20 files: subscription models and services/{store,renewals,dunning,checkout,changes,billing_gateway,payment_methods,portal}.py; entity/routes/{create,settings}.py | none - zero references to billing groups anywhere in billing-backend |
| report.*_sales - 11 columns dropped | s5a05_drop_legacy_sales | blueprints/report/models/{report,report_sale_detail}.py; routes/{api,create,sales,report_detail,deposit,expense}.py; services/{ending,shared}.py | none - report tables are not mirrored |

## Risks, most severe first

### Three files run unqualified SQL against tables another application owns

core/auth.py, bills/api_profile.py and bills/api_config.py name user_entity, entity_module_subscription, entities and "user" with bare table names. They resolve only because config/settings.py:74 sets search_path=pettycashv2,public on the connection. A pooler that resets the session, a connection opened by other means, or someone changing that OPTIONS line, and these silently resolve elsewhere or fail. core/auth.py is the worst of the three because it is the authorisation path. core/api_session.py already does this correctly - copy its pattern. By contrast MINTY HAS NO UNQUALIFIED RAW SQL ANYWHERE: every table-touching statement, all 64 migrations and all 20 .sql files carry the pettycashv2 prefix.

### Three 'read-only mirrors' are written to

shared_models/models.py documents User, XeroContactSync and AccountInfo as 'Read-only mirror of pettycashv2.x managed by the Flask app'. billing-backend writes all three: profile_service.py:92, contact_service.py:331/333, api_config.py:393. Whichever way this is resolved - correct the docstrings and own the writes, or move them behind a Minty endpoint - the two must be made to agree. Right now a reader of the model file is told something false about a shared table.

### entity_function_map is reconciled by one app and freely writable from the other

Minty treats entity_function_map.is_enabled as a projection of entity_module_subscription and reconciles it daily in blueprints/subscription/services/access_sweep.py. billing-backend's bills/api_config.py exposes unguarded POST/PUT/DELETE on the same table. A write there can grant module access that Minty's sweep then silently revokes, which will present as an intermittent entitlement bug with no error anywhere.

### billing-backend migration 0019 depends on a Minty migration

bills/migrations/0019_align_currency_fk_types.py converts entity_bill_currency.currency_info_id from varchar(36) to uuid and RAISES unless Minty's c8e0a2b4d6f8 has already rebuilt pettycashv2.currency_info with a uuid primary key. Deploy order is permanent: Minty first. It is long applied, but a fresh environment built in the wrong order will stop here.

### s6a06 is a production schema change with no Alembic revision

migrations/s6a06_relax_sales_columns_not_null.sql and s6a06_verify_sales_split.sql are tracked, hand-run scripts. There is no migrations/versions/s6a06*.py - verified. A database built by running flask db upgrade from empty will not have the change, and r1a01_report_consolidation_additive.py calls s6a06 'the cautionary tale'. Either write the revision or document that upgrade-from-empty is unsupported. (Note: s5a05 DOES now have a Python revision, added 2026-08-27 - only s6a06 is missing.)

### An already-applied migration was edited in place

Revision a1b2c3d4e5f7 originally created subscription_email_log with a sent_at column. It was later removed from the revision file itself and existing databases were ALTERed by hand; the migration documents this at line 574. Any environment not hand-altered still has the column and flask db upgrade will never reconcile it. That revision has been edited in five separate commits.

### entity_bill_account_xero has no model in either repository

It is reached only through raw SQL strings, and its qualified name is re-declared three times - once as a module constant in onboarding_bill_codes.py:20 and twice as a function-local in entity/services/settings.py at lines 492 and 786. Nothing type-checks those strings and nothing will catch a typo until the query runs.

## Pending migration state

One migration is written and applied nowhere. Repo head is z1a01_drop_payer_cycle (commit 41e1d18), which drops user_stripe_customer.paid_through, dunning_started_at and dunning_attempts. The development database reports alembic_version = s5a05_drop_legacy_sales and all three columns are still present. docs/schema/README.md confirms it has not been run against any database.

This is safe in this direction - the models no longer declare the columns, so nothing selects them - but it is unfinished. The commit message carries the correct warning: run scripts/backfill_billing_groups.py before applying it. That backfill HAS already run on the development database (payer_billing_group holds 16 rows and entity_billing_group 68, of which 40 carry source='backfill'), but the script is still UNTRACKED in git, so it cannot be run from a clean checkout of any other environment.

Two caveats on scope. Both .env URIs currently point at localhost:5432/postgres with Stripe TEST keys, so the state of the Supabase and production databases cannot be confirmed from this machine - do not read the local result as covering them. And 64 Alembic revisions is the current count, with the chain linear and single-headed.
