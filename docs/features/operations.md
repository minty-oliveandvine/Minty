# Running it — configuration, storage, mail, the scheduler, the test suites

The cross-cutting facts a person needs before touching any feature. The database and its
migration story are documented separately: `docs/schema/README.md` (the redesigned schema
and the one-hop pipeline) and `docs/modernisation/modernisation_plan.md` (the plan and
the cutover runbook).

## Process model

`Procfile`: `web: gunicorn app:app` with two workers, no `--preload` — `create_app` runs
once per worker (`services/app_runtime/legacy/bootstrap.py` builds the app; `main.py` /
`app.py` expose it). There is no worker dyno and no cron: the subscription scheduler is an
in-process APScheduler thread (`services/app_runtime/scheduler.py`), off unless
`SUBSCRIPTION_SCHEDULER_ENABLED` - and minty-billing-api has the same timer behind the same
name against the same database, so never on in both.
`docker/` has a Dockerfile, an entrypoint that creates the schema if missing, and
`docker/stack/` a compose file for the whole five-app stack.

## Configuration (`.env`; `.env.example` documents every variable)

| Group | Variables |
|---|---|
| database | `FLASK_ENV` decides which URI is read — `development` → `LOCAL_DATABASE_URI`, anything else → `RDS_DATABASE_URI` (production reads the latter; the `.env` comment block explains the swap). `MINTY_DB_SCHEMA` (default `pettycashv3`) is the schema name every model, raw query, the session table and both Django services read — `blueprints/shared/schema.py`; leave it unset in deployments |
| secrets | `SECRET_KEY` (shared with the two Django services), `WTF_CSRF_SECRET_KEY` |
| Xero | `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`, `XERO_API_BASE_URL` |
| storage | `S3_KEY`, `S3_SECRET`, `S3_REGION`, `S3_BUCKET` — Backblaze B2 through the S3 API; one bucket shared by every environment today |
| mail | `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_TIMEOUT` (seconds per SMTP step, default 10 - `services/app_runtime/mail.py`), `BREVO_EMAIL` (the sender), `SUBSCRIPTION_EMAIL` |
| URLs | `PUBLIC_URL` (Minty), `ONBOARDING_APP_URL` (the wizard), `FRONTEND_APP_URL` (the payment app) |
| switches | `SUBSCRIPTION_SCHEDULER_ENABLED` (+ `_FULL_HOUR`, `_TZ`, `_LIGHT`), `MINTY_WEB_HUB`, `EXPENSE_AI_*` |
| sessions | `SESSION_TYPE` (`sqlalchemy`), `SESSION_SQLALCHEMY_TABLE` (`sessions`) |

Never paste a real value into a chat or a ticket; the deployed `SECRET_KEY` differs from
the local one on purpose.

## Storage

Receipts: [receipts-and-attachments.md](receipts-and-attachments.md). Bill attachments are
billing-backend's, in the same bucket under its own prefixes. Nothing is stored on the
web host's disk except the temporary files of an export.

## Mail

Flask-Mail over Brevo SMTP. What sends mail: OTP codes, invitations, password resets, the
subscription notices (`blueprints/subscription/services/notify.py`, templates under
`templates/email/`). Tests never send: the suite's app config points mail at nothing and
the notice tests assert on the log table.

## Logging

`loguru` everywhere (`logger.info(...)`), shipped off the host; the `/api/client-logs`
sink receives the browser's own log. Two rules the tests enforce: no token in a log line
(`tests/test_zz_no_token_logging.py`) and no error message that leaks internals to the
user (`docs/features/ERROR_MESSAGE_LEAKS.md`).

## The test suites

- **pytest** (`tests/`, Postgres only since C10): `pytest -n auto` — about two minutes; each
  xdist worker builds `docs/schema/01_schema_rebased.sql` into its own database
  (`tests/pg_harness.py`, `MINTY_TEST_PG_URI` or the `.env` URI) and renames it to
  `MINTY_DB_SCHEMA`. The `test_zz_*` files are the guards that run last: the schema audit
  against the harness build, the schema-name literal guard, route coverage, the
  token-logging guard. **Route coverage** counts a route only when a request ran its view
  (never OPTIONS, never a refusal) and fails on an in-scope route that is neither reached nor
  listed in `tests/_baseline/route_coverage_misses.txt` (the known gaps), on a listed route
  that a test now reaches, and on a route `route_inventory.json` doesn't know. It judges a
  complete run only - a partial or `-k`/`-x` run prints "not judged" - and rewrites the list
  only with `MINTY_ROUTE_BASELINE=update` (drop covered) or `=add` (also add misses). `tests/_baseline/README.md` holds the pre-C10 history.
  `tests/conftest.py` pins `SUBSCRIPTION_SCHEDULER_ENABLED=0` (and `MINTY_WEB_HUB=0`), so a
  developer `.env` that switches the daily billing jobs on never starts them in a test app.
- **Playwright** (`e2e/`, `npm run test:e2e`): a real browser against a Flask that is
  already running — `e2e/README.md` has the environment (`E2E_BASE_URL`, the seeded
  identity from `scripts/e2e_seed.py --print`, `E2E_XERO=1` for a shop linked to a Demo
  Company). Against a deployment, run the seed
  with `FLASK_ENV=production` so it reaches the deployment's database.
- The two Django services and the two Next apps have their own suites; the three e2e
  suites together are the smoke test of a cutover (`modernisation_plan.md`, Phase E
  step 7).

## Scripts

`scripts/e2e_seed.py` (the e2e identity and shop, idempotent, leaves a Xero-connected
shop's mapping alone), `scripts/schema_migration/` (`rehearse.py`, `cutover_checks.py`), `scripts/subscription/` (scenario replay),
`docs/schema/generators/` (`gen.py`, `audit_models.py`, `mkdoc.py`).
