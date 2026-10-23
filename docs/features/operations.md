# Running it — configuration, storage, mail, the test suites

The cross-cutting facts a person needs before touching any feature. The database and its
migration story are documented separately: `docs/schema/README.md` (the redesigned schema
and the one-hop pipeline) and `docs/modernisation/modernisation_plan.md` (the plan and
the cutover runbook).

**Flask is backend only since 2026-10-20** (the owner's instruction): no templates, no pages;
every screen is a Next.js app's. `static/` keeps only `img/new_logo.png` (the invitation
email's logo, and with `img/email/*` a source for
`scripts/subscription/build_email_assets.py`). Every error answer - 404, 405, 500, a CSRF
failure, the read-only superuser block - is JSON (`pettycash/core/hooks.py`).
`tests/test_zz_no_html_frontend.py` fails on a templates folder, a `render_template` call or a
GET route that answers `text/html`.

## Process model

`Procfile`: `web: gunicorn app:app` on `${PORT:-8010}` with two workers, no `--preload` — `create_app` runs
once per worker (`services/app_runtime/legacy/bootstrap.py` builds the app; `main.py` /
`app.py` expose it). **A route module that fails to import stops the start-up** with its
traceback (`pettycash/core/blueprint_loader.py`, `blueprints/report/routes/__init__.py`, since
2026-10-05): until then the failure was skipped at DEBUG and the app ran with those routes
missing, so a deploy that lacks a package now fails its boot instead. There is no worker dyno and no cron. The
subscription daily pass is minty-subscription-api's (its in-process timer,
`SUBSCRIPTION_SCHEDULER_ENABLED` there); Flask's scheduler and its engine were deleted on
2026-10-06.
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
| Xero | `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`; the redirect URI is `ACCOUNTS_API_URL` (alias `PETTY_CASH_URL`) + `/callback` |
| storage | `S3_URL` — `https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>` (key and secret URL-encoded), Backblaze B2 through the S3 API; one bucket shared by every environment today |
| mail | `SMTP_URL` — `smtp://user:pass@host:587` (STARTTLS) or `smtps://…:465`, `?timeout=` seconds per SMTP step (default 10 - `services/app_runtime/mail.py`); `MAIL_FROM` (the sender) |
| URLs | `ACCOUNTS_API_URL` (this app's public origin; `PETTY_CASH_URL` is its transitional alias, and one of them is required outside development), `PETTY_CASH_WEB_URL` (minty-petty-cash-web: where every Petty Cash address hands over; default `http://localhost:3010`), `MINTY_WEB_URL`, `PAYMENT_REQUEST_WEB_URL` (the payment app), `ONBOARDING_WEB_URL` (the wizard) |
| other keys | none. `SPIRE_KEY` is no longer read (the docx export went 2026-10-20); no Stripe keys since 2026-10-06 - Stripe is minty-subscription-api's |
| switches | `EXPENSE_AI_*` |
| sessions | `SESSION_TYPE` (`sqlalchemy`), `SESSION_SQLALCHEMY_TABLE` (`sessions`) |

Never paste a real value into a chat or a ticket; the deployed `SECRET_KEY` differs from
the local one on purpose.

## Storage

Receipts: [receipts-and-attachments.md](receipts-and-attachments.md). Bill attachments are
minty-payment-request-api's, in the same bucket under its own prefixes. Nothing is stored on the
web host's disk.

## Mail

Flask-Mail over Brevo SMTP (`SMTP_URL`; unset, every send is logged and skipped). What sends mail: OTP codes and invitations (inline HTML built in Python). The
subscription emails are minty-subscription-api's since 2026-10-06. Tests never send: the suite's
app config points mail at nothing.

## Logging

Standard-library `logging` since 2026-10-22: loguru is gone (`tests/test_zz_no_loguru.py`).
Every Minty backend, Flask and the four Django APIs, writes one line, defined once in
[`minty-shared-py`](https://github.com/minty-oliveandvine/minty-shared-py) (`minty_shared.logctx`):

```
2026-10-22T08:42:15.123Z INFO [trace=a1b2c3d4] [user=<uuid>|entity=<uuid>|step=xero.publish] message
```

- **Call sites are unchanged.** `from services.app_runtime.log import logger` is loguru's call
  shape (`logger.info("{} issued", n)`, `logger.exception(...)`) over the stdlib `minty` logger.
  Werkzeug's, xero_python's and urllib3's lines reach the same root handlers (stderr, and
  `services/app_runtime/legacy/app.log` rotated at 5 MB with 10 kept), set once per process in
  `bootstrap._setup_logging`.
- **`trace`** is opened by `http_hardening.open_trace`, the `before_request` that runs straight
  after `preview_origin.capture`, so it comes before every hook that logs. An `X-Request-ID` of
  8-32 lowercase hex digits is kept (the Django APIs send theirs on every internal call);
  anything else is replaced. The id is echoed on the response.
- **`user` / `entity`** are bound only where they are verified: the session's `load_user`, a
  bearer token's signature (`bearer_api.claims_from_bearer`, the person only), a backend's
  service assertion (`_authenticate_internal_caller`, its company and person), and the Petty
  Cash guard (the company once every check has passed).
- **`step`** is the endpoint name unless code names one (`with logctx.log_step("…"):`).
- **Threads** start through `logctx.carry_context(target)`, so a background Xero sync keeps the
  request's trace.

Two rules the tests enforce: no token in a log line (`tests/test_zz_no_token_logging.py`), and no error message that leaks internals to
the user (`docs/features/ERROR_MESSAGE_LEAKS.md`). Tracebacks carry no variable values (loguru's
`diagnose` went with it).

The access log is Flask's own since 2026-10-05 (`pettycash/core/http_hardening.py`):
`METHOD path status ms`, no query string, secret path segments `[redacted]`. gunicorn's
`--access-logfile` is gone from the `Procfile` because it printed the whole request line,
tokens included, and since 2026-10-20 `gunicorn.conf.py` (repo root, read from the working
directory) gives gunicorn `NoAccessLogger`, because Render's native runtime turns the access
log on through `GUNICORN_CMD_ARGS` anyway (`tests/test_gunicorn_access_log.py`).
On Windows, parallel pytest workers share `app.log`, so a rotation can fail with
`PermissionError: [WinError 32]` ("--- Logging error ---"). That is noise, not a test failure,
and doesn't happen on the Linux host.

## The test suites

- **pytest** (`tests/`, Postgres only since C10): `pytest -n auto` — about two minutes; each
  xdist worker builds `docs/schema/01_schema_rebased.sql` into its own database
  (`tests/pg_harness.py`, `MINTY_TEST_PG_URI` or the `.env` URI) and renames it to the
  schema named in the URL's `?schema=`. The three Django APIs load the same harness by path
  from their own conftest, without Minty on `sys.path`, so it imports nothing from the app:
  `services/app_runtime/env.py` (stdlib-only) is loaded by file path too. The `test_zz_*` files are the guards that run last: the schema audit
  against the harness build, the schema-name literal guard, route coverage, the
  token-logging guard, the no-HTML-frontend guard. **Route coverage** counts a route only when a request ran its view
  (never OPTIONS, never a refusal) and fails on an in-scope route that is neither reached nor
  listed in `tests/_baseline/route_coverage_misses.txt` (the known gaps), on a listed route
  that a test now reaches, and on a route `route_inventory.json` doesn't know. It judges a
  complete run only - a partial or `-k`/`-x` run prints "not judged" - and rewrites the list
  only with `MINTY_ROUTE_BASELINE=update` (drop covered) or `=add` (also add misses). `tests/_baseline/README.md` holds the pre-C10 history.
  `test_zz_no_stripe.py` fails if application code imports `stripe`, `apscheduler` or any
  `blueprints.subscription.services` module but the read-only `store_ro`.
- **Browser tests**: Flask draws no page, so it has no browser journeys of its own since
  2026-10-20 ([ci.md](ci.md)). `scripts/e2e_seed.py --print` still seeds the identity and shop
  the Next apps' suites sign in as; against a deployment, run it with that deployment's
  `DATABASE_URL` so it reaches its database.
- The Django APIs and the Next apps have their own suites; the Next apps' e2e suites together
  are the smoke test of a cutover (`modernisation_plan.md`, Phase E step 7).

## Scripts

`scripts/e2e_seed.py` (the e2e identity and shop, idempotent, leaves a Xero-connected
shop's mapping alone), `scripts/schema_migration/` (`rehearse.py`, `cutover_checks.py`), `scripts/subscription/build_email_assets.py` (the subscription emails' images, shipped by minty-subscription-api; scenario replay is its `manage.py replay_scenarios`),
`docs/schema/generators/` (`gen.py`, `audit_models.py`, `mkdoc.py`).
