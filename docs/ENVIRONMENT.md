# Environment — every service, port, URL and variable

The one reference for configuring the seven Minty repos, locally and on Render / Vercel.
Each repo's `.env.example` lists exactly its own variables (below, §5); this page is the
cross-repo picture and the migration from the old names (§9).

## 1. The naming rule

- **One name per thing, the same in every repo.** A service's URL is `<SERVICE>_URL`
  (`PETTY_CASH_URL`, `SUBSCRIPTION_API_URL`, …) wherever it is read — Flask, Django or Next.js.
- **No `NEXT_PUBLIC_` prefix.** The Next.js apps expose the plain names to the browser
  through `next.config.ts` (§6).
- **Connection settings are one URL each:** `DATABASE_URL`, `SMTP_URL`, `S3_URL`. Credentials
  inside them are URL-encoded.
- **Derive, don't configure.** Anything that follows from another value (the Xero redirect
  URI, the Xero token-service URL, CORS origins, timeouts) is derived in code, not set.
- **No fallbacks to old names.** A variable from §9's left-hand column is ignored.

## 2. Services, repos and ports

Each domain has a slot `N`: its web app listens on `30N0`, its API on `80N0`. Hosts inject
`PORT`; every server binds `${PORT:-<local port>}`.

| Service | Repo | Stack | Local port | Docker stack hostname |
|---|---|---|---|---|
| Minty web hub | `minty-web` | Next.js | 3000 | `minty-web` |
| Subscription API | `minty-subscription-api` | Django | 8000 | `subscription-api` |
| Petty Cash | `Minty` | Flask | 8010 | `minty` |
| Payment Request web | `minty-payment-request-web` | Next.js | 3020 | `payment-request-web` |
| Payment Request API | `minty-payment-request-api` | Django | 8020 | `payment-request-api` |
| Onboarding web | `minty-onboarding-web` | Next.js | 3030 | `onboarding-web` |
| Onboarding API | `minty-onboarding-api` | Django | 8030 | `onboarding-api` |
| PostgreSQL | — | Postgres 15 | 5432 (the Docker stack publishes 5433) | `db` |

Old local ports, for reference: hub 3002, subscription API 8004, Flask 5001, payment-request
web 3000, payment-request API 8000, onboarding web 3001, onboarding API 8001.

## 3. Service URLs

| Variable | Local default | Points at |
|---|---|---|
| `MINTY_WEB_URL` | `http://localhost:3000` | the hub |
| `SUBSCRIPTION_API_URL` | `http://localhost:8000` | subscription API |
| `PETTY_CASH_URL` | `http://localhost:8010` | Petty Cash (Flask) |
| `PAYMENT_REQUEST_WEB_URL` | `http://localhost:3020` | payment-request web |
| `PAYMENT_REQUEST_API_URL` | `http://localhost:8020` | payment-request API |
| `ONBOARDING_WEB_URL` | `http://localhost:3030` | onboarding web |
| `ONBOARDING_API_URL` | `http://localhost:8030` | onboarding API |

Trailing slashes are stripped when read. In a deployment each value is the other service's
public origin (e.g. `PETTY_CASH_URL=https://minty.oliveandvinehk.com`).

One exception: **`PETTY_CASH_PUBLIC_URL`** (subscription API only, optional, defaults to
`PETTY_CASH_URL`) — the browser-facing Flask origin for when `PETTY_CASH_URL` is an internal
hostname. Only the Docker stack needs it (`PETTY_CASH_URL=http://minty:8010` for the
server-to-server call, `PETTY_CASH_PUBLIC_URL=http://localhost:8010` for email links and CORS).

## 4. Infrastructure variables

### `APP_ENV`

`development` or `production`; **default `production`**, and any other value counts as
production. Django: `DEBUG = APP_ENV == "development"`. Flask: debug, and
`OAUTHLIB_INSECURE_TRANSPORT` (Xero OAuth over plain http) only in `development`. Replaces
`DEBUG`, `FLASK_ENV`, `ENV`, `FLASK_DEBUG`. The Django APIs refuse to start in production
with the placeholder `SECRET_KEY` (`change-me-in-production`).

### `DATABASE_URL` — the schema is part of the URL

```
postgresql://USER:PASSWORD@HOST:5432/DBNAME?schema=pettycashv3[&sslmode=require...]
```

- Schemes `postgres`, `postgresql`, `postgresql+psycopg2`, `postgresql+psycopg` are accepted.
- `?schema=` (default `pettycashv3`) names the one schema every service shares. It is popped
  off and never passed to the driver; every other query parameter (`sslmode`, …) is kept.
- User, password and database name are percent-decoded — encode special characters
  (`@` → `%40`, `:` → `%3A`, `/` → `%2F`). Port defaults to 5432.
- Required by Petty Cash. The Django APIs fall back to `postgresql://postgres@localhost:5432/postgres`
  so settings import locally and in tests; always set it in a deployment.
- Helpers: Flask `services/app_runtime/env.py` (`database_url()`, `database_schema()`);
  Django `config/dburl.py` (`parse_database_url()`, `database_url()`).

### `SMTP_URL` and `MAIL_FROM`

```
smtp://USER:PASSWORD@HOST:587     STARTTLS   (default port 587)
smtps://USER:PASSWORD@HOST:465    implicit SSL (default port 465)
```

Query parameters: `timeout` (seconds per SMTP step, default 10); `tls=0` turns STARTTLS off
for `smtp://` (local mail catchers). User and password are percent-decoded. Unset: Petty Cash
logs and skips every send; the Django APIs print mail to the console. `MAIL_FROM` is the
default sender; `SUBSCRIPTION_EMAIL` and `ONBOARDING_EMAIL` are optional per-purpose senders
that default to `MAIL_FROM` (each must be a verified sender in Brevo).

### `S3_URL`

```
https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>
```

Gives the endpoint (`https://s3.<region>.backblazeb2.com`), the bucket, key and secret
(percent-decoded — URL-encode them) and the region (from the host, or `?region=`, which wins;
else `us-east-1`).

### `SECRET_KEY`

One HS256 key **shared by Petty Cash and the three Django APIs**: Flask mints the hand-off
JWTs and the APIs verify them, so a mismatch is a 401 on every call. Flask also signs
sessions and CSRF tokens with it (there is no separate CSRF or session secret).

> **Rotate `SECRET_KEY` everywhere.** A real key was committed to this repo's history
> (`docker/stack/.env.bak-xerofix`, now deleted — deleting does not remove it from history).
> Generate a new one (`python -c "import secrets; print(secrets.token_hex(32))"`) and set it on
> all four backends of an environment at the same time; it signs everyone out and voids
> in-flight hand-off tokens.

## 5. Variables per service

"opt" = optional. Nothing else belongs in a service's environment.

**Petty Cash (`Minty`, Flask)**
- Required: `APP_ENV`, `SECRET_KEY`, `DATABASE_URL`, `S3_URL`, `PETTY_CASH_URL`,
  `MINTY_WEB_URL`, `SUBSCRIPTION_API_URL`, `PAYMENT_REQUEST_WEB_URL`, `ONBOARDING_WEB_URL`,
  `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `SPIRE_KEY`, `STRIPE_SECRET_KEY`,
  `STRIPE_PUBLISHABLE_KEY`, `SMTP_URL`, `MAIL_FROM` (start-up enforces `SECRET_KEY`,
  `DATABASE_URL` and `S3_URL`; without `SMTP_URL` no mail is sent).
- Optional: `SUBSCRIPTION_EMAIL`, `SUBSCRIPTION_SCHEDULER_ENABLED` (+ `_FULL_HOUR`, `_TZ`,
  `_LIGHT`), `MINTY_WEB_HUB`, `EXPENSE_AI_*` / `GEMINI_API_KEY` / `GOOGLE_CLOUD_PROJECT`, the
  legal flags (`REQUIRE_TERMS_AT_SIGNUP`, `CURRENT_TERMS_VERSION`, `CURRENT_PRIVACY_VERSION`),
  `INVITATION_*`, `AUTO_SUPERUSER_EMAILS`, `DD_CLIENT_TOKEN`, `LOG_LEVEL`, `SESSION_TYPE`,
  `RUN_MIGRATIONS` / `DB_WAIT_SECONDS` / `GUNICORN_WORKERS` (Docker).

**Payment Request API (`minty-payment-request-api`, Django)**
- Required: `APP_ENV`, `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`, `S3_URL`,
  `PETTY_CASH_URL`, `PAYMENT_REQUEST_WEB_URL`, `ONBOARDING_WEB_URL`.
- Optional: `CORS_ALLOWED_ORIGINS` (default `PAYMENT_REQUEST_WEB_URL,ONBOARDING_WEB_URL`),
  `LOG_LEVEL`, `RUN_MIGRATIONS`, `DB_WAIT_SECONDS`.

**Subscription API (`minty-subscription-api`, Django)**
- Required: `APP_ENV`, `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`, `SMTP_URL`, `MAIL_FROM`,
  `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `PETTY_CASH_URL`, `MINTY_WEB_URL`,
  `PAYMENT_REQUEST_WEB_URL`, `SUBSCRIPTION_SCHEDULER_*`.
- Optional: `PETTY_CASH_PUBLIC_URL`, `SUBSCRIPTION_EMAIL`, `ONBOARDING_EMAIL`,
  `CORS_ALLOWED_ORIGINS` (default `MINTY_WEB_URL,PAYMENT_REQUEST_WEB_URL,PETTY_CASH_PUBLIC_URL`),
  `LOG_LEVEL`.

**Onboarding API (`minty-onboarding-api`, Django)**
- Required: `APP_ENV`, `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`, `PETTY_CASH_URL`,
  `ONBOARDING_WEB_URL`, `DISPLAY_TIMEZONE`.
- Optional: `CORS_ALLOWED_ORIGINS` (default `ONBOARDING_WEB_URL`), `LOG_LEVEL`.

**Minty web hub (`minty-web`, Next.js)**: `PETTY_CASH_URL`, `SUBSCRIPTION_API_URL`,
`PAYMENT_REQUEST_WEB_URL`.

**Payment Request web (`minty-payment-request-web`, Next.js)**: `PETTY_CASH_URL`,
`PAYMENT_REQUEST_API_URL`, `SUBSCRIPTION_API_URL`; optional `MAINTENANCE_SHOW_NEW_LINK`.

**Onboarding web (`minty-onboarding-web`, Next.js)**: `PETTY_CASH_URL`, `ONBOARDING_API_URL`.

Test-only variables (`MINTY_TEST_PG_URI`, which may carry `?schema=`, `MINTY_TEST_PG_DBNAME`,
`MINTY_REPO`, `PG_BIN`, `MINTY_ROUTE_BASELINE`, `E2E_*`) are documented in each repo's test
README.

## 6. Next.js: plain names, inlined at build time

Each Next app lists its variables in `next.config.ts` under `env: { PETTY_CASH_URL: …, … }`.
Next inlines `process.env.PETTY_CASH_URL` for those keys **at build time**, in client, server
and middleware code alike; the app reads them in one place (`lib/env.ts`, which applies the
local default and strips a trailing slash).

So in a deployment a changed value takes effect only after a **rebuild** — redeploy after
editing an environment variable. Locally, restart `next dev`.

## 7. Xero redirect URI

Derived: `PETTY_CASH_URL` + `/callback` — `http://localhost:8010/callback` locally. Every
environment's value must be registered verbatim in the Xero app's *Redirect URIs*
(developer.xero.com → My Apps), or sign-in fails with `unauthorized_client`. Moving local
Flask from 5001 to 8010 means adding `http://localhost:8010/callback` there. The Django APIs
fetch Xero tokens from `PETTY_CASH_URL/api/internal/xero/token` (also derived); only Flask
holds `XERO_CLIENT_ID` / `XERO_CLIENT_SECRET`.

## 8. Branches and deployments

`main` deploys **production**; `development` deploys the **development** environment. Each
service's variables are set per environment in its host's dashboard (Render or Vercel —
whichever hosts that service); none are committed.

### Cutover checklist

Do it in this order — the old variables can stay in place until the end, because nothing
running yet reads the new ones and nothing new reads the old ones:

1. **Set the new variables on every development service** (§5): `APP_ENV`, `DATABASE_URL`
   (with `?schema=pettycashv3`), `S3_URL`, `SMTP_URL`, `MAIL_FROM`, the `*_URL` set; on Render
   leave `PORT` to the platform. Rotate `SECRET_KEY` (§4) while you are there.
2. **Register** the development `PETTY_CASH_URL/callback` in the Xero app if it is not there.
3. **Deploy `development`** in every repo (the Next apps must rebuild — §6).
4. **Verify**: sign in, hand off to each module (hub, payment request, onboarding), upload a
   receipt (S3), trigger a mail (OTP or invitation), connect Xero, open the subscription
   overview. Check each service's logs for missing-variable errors.
5. **Set the new variables on every production service** (with a fresh production
   `SECRET_KEY`, identical on the four backends).
6. **Merge `development` into `main`** in every repo and let production deploy; verify as in 4.
7. Only then **delete the old variables** (§9) from both environments.

### Renamed repos

| Old repo | New repo |
|---|---|
| `minty-billing-api` | `minty-subscription-api` |
| `billing-frontend` | `minty-payment-request-web` |
| `billing-backend` | `minty-payment-request-api` |
| `onboarding` | `minty-onboarding-web` |
| `onboarding-backend` | `minty-onboarding-api` |
| `Minty`, `minty-web` | unchanged |

GitHub redirects the old URLs, but **re-check each Render and Vercel service's Git
connection after renaming** (repository and branch), and update local clones
(`git remote set-url origin …`) and checkout folder names — the Docker stack's defaults
expect the new names (`docker/stack/.env.example`, `*_PATH`).

## 9. Old → new variable names

"removed" = no longer read; "derived" = computed from another variable; "constant" = fixed
in code. Repos: PC = Minty (Petty Cash), SUB = subscription API, PRA = payment-request API,
PRW = payment-request web, ONA = onboarding API, ONW = onboarding web, HUB = minty-web,
STACK = `docker/stack` / `docker/` compose files.

### Runtime, secrets, database

| Old | Repos | New |
|---|---|---|
| `FLASK_ENV`, `ENV`, `FLASK_DEBUG` | PC, STACK | `APP_ENV` |
| `DEBUG` | PRA, SUB, ONA | `APP_ENV` |
| `DJANGO_DEBUG` | STACK | `APP_ENV` |
| `DJANGO_ALLOWED_HOSTS` | STACK | `ALLOWED_HOSTS` |
| `LOCAL_DATABASE_URI`, `RDS_DATABASE_URI` | PC, STACK | `DATABASE_URL` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT` | PRA, SUB, ONA, STACK app services | `DATABASE_URL` (`POSTGRES_*` remain only for the `db` container) |
| `MINTY_DB_SCHEMA` | all backends, STACK | `DATABASE_URL` `?schema=` (STACK interpolation: `DB_SCHEMA`) |
| `WTF_CSRF_SECRET_KEY` | PC, STACK | removed (`SECRET_KEY`) |
| `SESSION_SECRET` | PC, STACK | removed |
| `NEXT_PUBLIC_APP_ENV` | PRW, STACK | constant |

### Service URLs

| Old | Repos | New |
|---|---|---|
| `PUBLIC_URL` | PC | `PETTY_CASH_URL` |
| `MINTY_PUBLIC_URL` | SUB | `PETTY_CASH_PUBLIC_URL` (optional) |
| `MINTY_PUBLIC_URL` | STACK | removed (built from `MINTY_HOST_PORT`) |
| `FLASK_APP_URL` | PRA, SUB, ONA | `PETTY_CASH_URL` |
| `NEXT_PUBLIC_MODULE1_URL` (+ `_DEV`, `_PRESTAGING`, `_STAGING`, `_PROD`) | PRW | `PETTY_CASH_URL` |
| `NEXT_PUBLIC_MODULE1_API_URL`, `NEXT_PUBLIC_API_URL` | ONW | `PETTY_CASH_URL` |
| `NEXT_PUBLIC_MINTY_URL` | HUB | `PETTY_CASH_URL` |
| `NEXT_PUBLIC_MODULE2_BACKEND_URL` | PRW | `PAYMENT_REQUEST_API_URL` |
| `FRONTEND_APP_URL` | PC, PRA | `PAYMENT_REQUEST_WEB_URL` |
| `PAYMENTS_WEB_URL` | SUB | `PAYMENT_REQUEST_WEB_URL` |
| `NEXT_PUBLIC_PAYMENTS_WEB_URL` | HUB | `PAYMENT_REQUEST_WEB_URL` |
| `BILLING_API_URL` | PC | `SUBSCRIPTION_API_URL` |
| `NEXT_PUBLIC_BILLING_API_URL` | HUB, PRW | `SUBSCRIPTION_API_URL` |
| `NEXT_PUBLIC_ONBOARDING_API_URL` | ONW | `ONBOARDING_API_URL` |
| `ONBOARDING_APP_URL` | PC, ONA | `ONBOARDING_WEB_URL` |
| `ONBOARDING_WEB_URL` | SUB (stack only) | removed (not read) |
| `BILLING_APP_URL` | PC, STACK | removed |
| `NEXT_PUBLIC_MAINTENANCE_SHOW_NEW_LINK` | PRW | `MAINTENANCE_SHOW_NEW_LINK` |
| `NEXT_PUBLIC_MINTY_ENTITY_SETTINGS_PATH`, `NEXT_PUBLIC_MINTY_USERS_PATH`, `NEXT_PUBLIC_MINTY_XERO_PATH` | PRW | constant |
| `PAYMENT_REQUEST_APP_HOME_PATH`, `PAYMENT_REQUEST_SETTINGS_PATH`, `BILLING_APP_HOME_PATH`, `BILLING_SETTINGS_PATH` | PC | constant |

### Mail, storage, Xero, Stripe

| Old | Repos | New |
|---|---|---|
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_TIMEOUT` | PC, STACK | `SMTP_URL` (`?timeout=`) |
| `MAIL_DEBUG` | PC | removed |
| `BREVO_EMAIL` | PC, STACK | `MAIL_FROM` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_TIMEOUT`, `EMAIL_BACKEND` | SUB | `SMTP_URL` (unset → console backend) |
| `DEFAULT_FROM_EMAIL` | SUB | `MAIL_FROM` |
| `S3_BUCKET`, `S3_KEY`, `S3_SECRET`, `S3_REGION`, `S3_ENDPOINT_URL` | PC, PRA, STACK | `S3_URL` |
| `XERO_REDIRECT_URI` | PC, STACK | derived (`PETTY_CASH_URL/callback`) |
| `XERO_API_BASE_URL` | PC, STACK | constant (`https://api.xero.com`) |
| `XERO_TOKEN_SERVICE_URL` | PRA, ONA, STACK | derived (`PETTY_CASH_URL/api/internal/xero/token`) |
| `XERO_TOKEN_SERVICE_TIMEOUT` | PRA, ONA | constant (15 s) |
| `MINTY_PROXY_TIMEOUT`, `FLASK_PROXY_TIMEOUT` | ONA, SUB | constant (20 s) |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET` | PRA | removed (only Petty Cash holds them) |
| `STRIPE_WEBHOOK_SECRET` | PC, STACK | removed |

### Docker stack (`docker/stack/.env`)

| Old | New |
|---|---|
| `MINTY_DB_SCHEMA` | `DB_SCHEMA` |
| `DB_HOST_PORT` default 5432 | `DB_HOST_PORT` default 5433 |
| `BILLING_BACKEND_PATH` | `PAYMENT_REQUEST_API_PATH` (default `../../../minty-payment-request-api`) |
| `BILLING_FRONTEND_PATH` | `PAYMENT_REQUEST_WEB_PATH` (default `../../../minty-payment-request-web`) |
| `ONBOARDING_BACKEND_PATH` | `ONBOARDING_API_PATH` (default `../../../minty-onboarding-api`) |
| `ONBOARDING_PATH` | `ONBOARDING_WEB_PATH` (default `../../../minty-onboarding-web`) |
| `BILLING_API_PATH` | `SUBSCRIPTION_API_PATH` (default `../../../minty-subscription-api`) |
| `MINTY_PATH`, `MINTY_WEB_PATH` | unchanged |
| `MINTY_HOST_PORT` (5001) | `MINTY_HOST_PORT` (8010) |
| `MINTY_WEB_HOST_PORT` (3002) | `MINTY_WEB_HOST_PORT` (3000) |
| `BILLING_API_HOST_PORT` (8004) | `SUBSCRIPTION_API_HOST_PORT` (8000) |
| `BILLING_BACKEND_HOST_PORT` (8000) | `PAYMENT_REQUEST_API_HOST_PORT` (8020) |
| `BILLING_FRONTEND_HOST_PORT` (3000) | `PAYMENT_REQUEST_WEB_HOST_PORT` (3020) |
| `ONBOARDING_BACKEND_HOST_PORT` (8001) | `ONBOARDING_API_HOST_PORT` (8030) |
| `ONBOARDING_HOST_PORT` (3001) | `ONBOARDING_WEB_HOST_PORT` (3030) |
| `MINTY_PUBLIC_URL`, `MINTY_WEB_PUBLIC_URL`, `BILLING_API_PUBLIC_URL`, `BILLING_BACKEND_PUBLIC_URL`, `BILLING_FRONTEND_PUBLIC_URL`, `ONBOARDING_PUBLIC_URL`, `ONBOARDING_BACKEND_PUBLIC_URL` | removed (built from the `*_HOST_PORT` values) |

Stack service names: `billing-backend` → `payment-request-api`, `billing-frontend` →
`payment-request-web`, `onboarding-backend` → `onboarding-api`, `onboarding` →
`onboarding-web`, `billing-api` → `subscription-api`; `minty`, `minty-web`, `db` unchanged.

### End-to-end test variables

| Old | New |
|---|---|
| `E2E_FLASK_URL` | `E2E_PETTY_CASH_URL` |
| `E2E_BACKEND_URL` | `E2E_PAYMENT_REQUEST_API_URL` |
| `E2E_BILLING_API_URL` | `E2E_SUBSCRIPTION_API_URL` |
| `E2E_PAYMENTS_WEB_URL`, `E2E_PAYMENTS_ORIGIN` | `E2E_PAYMENT_REQUEST_WEB_URL` |
| `E2E_WEB_ORIGIN` | `E2E_MINTY_WEB_URL` |
| `E2E_ONBOARDING_API_URL`, `E2E_BASE_URL` | unchanged (defaults moved to the new ports) |

### Unchanged

`SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` (now optional, defaults derived),
`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, Petty Cash's `XERO_CLIENT_ID` /
`XERO_CLIENT_SECRET`, `SPIRE_KEY`, `LOG_LEVEL`, `SUBSCRIPTION_SCHEDULER_*`,
`SUBSCRIPTION_EMAIL`, `ONBOARDING_EMAIL`, `EXPENSE_AI_*`, `GEMINI_API_KEY`,
`GOOGLE_CLOUD_PROJECT`, the legal flags, `MINTY_WEB_URL`, `MINTY_WEB_HUB`, `INVITATION_*`,
`AUTO_SUPERUSER_EMAILS`, `DD_CLIENT_TOKEN`, `DISPLAY_TIMEZONE`, `RUN_MIGRATIONS`,
`DB_WAIT_SECONDS`, `SESSION_TYPE`, `GUNICORN_WORKERS`, and the test-only variables.
