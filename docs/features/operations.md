# Running it — configuration, storage, mail, the scheduler, the test suites

The cross-cutting facts a person needs before touching any feature. The database and its
migration story are documented separately: `docs/schema/README.md` (the redesigned schema
and the one-hop pipeline) and `docs/modernisation/modernisation_plan.md` (the plan and
the cutover runbook).

## Process model

`Procfile`: `web: gunicorn app:app` on `${PORT:-8010}` with two workers, no `--preload` — `create_app` runs
once per worker (`services/app_runtime/legacy/bootstrap.py` builds the app; `main.py` /
`app.py` expose it). **A route module that fails to import stops the start-up** with its
traceback (`pettycash/core/blueprint_loader.py`, `blueprints/report/routes/__init__.py`, since
2026-10-05): until then the failure was skipped at DEBUG and the app ran with those pages
missing, so a deploy that lacks a package now fails its boot instead. There is no worker dyno and no cron: the subscription scheduler is an
in-process APScheduler thread (`services/app_runtime/scheduler.py`), off unless
`SUBSCRIPTION_SCHEDULER_ENABLED` - and minty-subscription-api has the same timer behind the same
name against the same database, so never on in both. In dev it is OFF here and ON in the API
since 2026-10-05: Flask's engine is being deleted and lacks the API's fixes (a replay-scoped
renewal key made Flask's runner bill a period twice).
`docker/` has a Dockerfile, an entrypoint that creates the schema if missing, and
`docker/stack/` a compose file for the whole seven-app stack.

## Configuration (`.env`; `.env.example` documents every variable)

The cross-repo reference — every service's variables, ports, URLs, the deploy checklist and
the old → new rename table — is [`docs/ENVIRONMENT.md`](../ENVIRONMENT.md). This app's:

| Group | Variables |
|---|---|
| runtime | `APP_ENV` — `development` or `production` (the default; anything else counts as production). `development` turns on debug and allows Xero's OAuth over plain http |
| database | `DATABASE_URL` — `postgresql://user:pass@host:5432/db?schema=pettycashv3`. `?schema=` (default `pettycashv3`) is the schema name every model, raw query, the session table and the Django services read — `services/app_runtime/env.py` pops it off before SQLAlchemy connects (`blueprints/shared/schema.py` reads it from there); other query params such as `sslmode` stay |
| secrets | `SECRET_KEY` (shared with the three Django APIs; also signs CSRF tokens) |
| Xero | `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`; the redirect URI is `PETTY_CASH_URL` + `/callback` |
| storage | `S3_URL` — `https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>` (key and secret URL-encoded), Backblaze B2 through the S3 API; one bucket shared by every environment today |
| mail | `SMTP_URL` — `smtp://user:pass@host:587` (STARTTLS) or `smtps://…:465`, `?timeout=` seconds per SMTP step (default 10 - `services/app_runtime/mail.py`); `MAIL_FROM` (the sender), `SUBSCRIPTION_EMAIL` (billing mail, defaults to `MAIL_FROM`) |
| URLs | `PETTY_CASH_URL` (this app's public origin), `MINTY_WEB_URL`, `SUBSCRIPTION_API_URL`, `PAYMENT_REQUEST_WEB_URL` (the payment app), `ONBOARDING_WEB_URL` (the wizard) |
| other keys | `SPIRE_KEY` (DOCX export), `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` |
| switches | `SUBSCRIPTION_SCHEDULER_ENABLED` (+ `_FULL_HOUR`, `_TZ`, `_LIGHT`), `EXPENSE_AI_*` |
| sessions | `SESSION_TYPE` (`sqlalchemy`), `SESSION_SQLALCHEMY_TABLE` (`sessions`) |

Never paste a real value into a chat or a ticket; the deployed `SECRET_KEY` differs from
the local one on purpose.

## Storage

Receipts: [receipts-and-attachments.md](receipts-and-attachments.md). Bill attachments are
minty-payment-request-api's, in the same bucket under its own prefixes. Nothing is stored on the
web host's disk except the temporary files of an export.

## Mail

Flask-Mail over Brevo SMTP (`SMTP_URL`; unset, every send is logged and skipped). What sends mail: OTP codes, invitations, password resets, the
subscription notices (`blueprints/subscription/services/notify.py`, templates under
`templates/email/`). Tests never send: the suite's app config points mail at nothing and
the notice tests assert on the log table.

## Logging

`loguru` everywhere (`logger.info(...)`), shipped off the host; the `/api/client-logs`
sink receives the browser's own log. Two rules the tests enforce: no token in a log line
(`tests/test_zz_no_token_logging.py`) and no error message that leaks internals to the
user (`docs/features/ERROR_MESSAGE_LEAKS.md`).

The access log is Flask's own since 2026-10-05 (`pettycash/core/http_hardening.py`):
`METHOD path status ms`, no query string, secret path segments `[redacted]`. gunicorn's
`--access-logfile` is gone from the `Procfile` because it printed the whole request line,
tokens included. `diagnose` (variable values in tracebacks) is on in development only.
On Windows, parallel pytest workers share `services/app_runtime/legacy/app.log`, and loguru's
5 MB rotation then fails with `PermissionError: [WinError 32]` ("Logging error in Loguru
Handler"). It is noise, not a test failure, and does not happen on the Linux host.

## The test suites

- **pytest** (`tests/`, Postgres only since C10): `pytest -n auto` — about two minutes; each
  xdist worker builds `docs/schema/01_schema_rebased.sql` into its own database
  (`tests/pg_harness.py`, `MINTY_TEST_PG_URI` or the `.env` URI) and renames it to the
  schema named in the URL's `?schema=`. The three Django APIs load the same harness by path
  from their own conftest, without Minty on `sys.path`, so it imports nothing from the app:
  `services/app_runtime/env.py` (stdlib-only) is loaded by file path too. The `test_zz_*` files are the guards that run last: the schema audit
  against the harness build, the schema-name literal guard, route coverage, the
  token-logging guard. **Route coverage** counts a route only when a request ran its view
  (never OPTIONS, never a refusal) and fails on an in-scope route that is neither reached nor
  listed in `tests/_baseline/route_coverage_misses.txt` (the known gaps), on a listed route
  that a test now reaches, and on a route `route_inventory.json` doesn't know. It judges a
  complete run only - a partial or `-k`/`-x` run prints "not judged" - and rewrites the list
  only with `MINTY_ROUTE_BASELINE=update` (drop covered) or `=add` (also add misses). `tests/_baseline/README.md` holds the pre-C10 history.
  `tests/conftest.py` pins `SUBSCRIPTION_SCHEDULER_ENABLED=0`, so a
  developer `.env` that switches the daily billing jobs on never starts them in a test app.
- **Playwright** (`e2e/`, `npm run test:e2e`): a real browser against a Flask that is
  already running — `e2e/README.md` has the environment (`E2E_BASE_URL`, the seeded
  identity from `scripts/e2e_seed.py --print`, `E2E_XERO=1` for a shop linked to a Demo
  Company). Against a deployment, run the seed
  with that deployment's `DATABASE_URL` so it reaches its database.
- The three Django APIs and the three Next apps have their own suites; the three e2e
  suites together are the smoke test of a cutover (`modernisation_plan.md`, Phase E
  step 7).

## Scripts

`scripts/e2e_seed.py` (the e2e identity and shop, idempotent, leaves a Xero-connected
shop's mapping alone), `scripts/schema_migration/` (`rehearse.py`, `cutover_checks.py`), `scripts/subscription/` (scenario replay),
`docs/schema/generators/` (`gen.py`, `audit_models.py`, `mkdoc.py`).
