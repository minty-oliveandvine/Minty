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
public origin, exactly as the browser reaches it with no redirect in between (e.g.
`PETTY_CASH_URL=https://pettycash.dailyminty.com`). Never a host that redirects: the old apex
`https://minty.oliveandvinehk.com` answers a CORS preflight with a 307, which every browser
treats as a failure.

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
- In a `.env` file, keep the schema as its own line and fill it into the URL — every service
  loads `.env` with python-dotenv, which expands `${...}`, and so does Docker Compose:

  ```
  DB_SCHEMA=pettycashv3
  DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME?schema=${DB_SCHEMA}
  ```

  `DB_SCHEMA` is only a `.env` helper; the apps read the schema from the URL. Render and Vercel
  dashboards do **not** expand `${...}`, so there write the name into the URL itself.

### `SMTP_URL` and `MAIL_FROM`

```
smtp://USER:PASSWORD@HOST:587     STARTTLS   (default port 587)
smtps://USER:PASSWORD@HOST:465    implicit SSL (default port 465)
```

Query parameters: `timeout` (seconds per SMTP step, default 10); `tls=0` turns STARTTLS off
for `smtp://` (local mail catchers). User and password are percent-decoded. Unset: Petty Cash
logs and skips every send; the Django APIs print mail to the console. `MAIL_FROM` is the
default sender; `SUBSCRIPTION_EMAIL` and `ONBOARDING_EMAIL` are the subscription API's
optional per-purpose senders that default to `MAIL_FROM` (each must be a verified sender in
Brevo).

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
  `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `SPIRE_KEY`, `SMTP_URL`, `MAIL_FROM` (start-up
  enforces `SECRET_KEY`, `DATABASE_URL` and `S3_URL`; without `SMTP_URL` no mail is sent).
  `SUBSCRIPTION_API_URL` is also read server-side: the dashboard's subscription notice.
  No `STRIPE_*`, `SUBSCRIPTION_SCHEDULER_*` or `SUBSCRIPTION_EMAIL` since 2026-10-06 (Flask's
  subscription engine was deleted; nothing reads them).
- Optional: `EXPENSE_AI_*` / `GEMINI_API_KEY` / `GOOGLE_CLOUD_PROJECT`, the
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
  `SUBSCRIPTION_API_URL` (since 2026-10-06: cards, billing consent and finalize's trial start;
  outside development the service refuses to start without it), `ONBOARDING_WEB_URL`,
  `DISPLAY_TIMEZONE`.
- Optional: `CORS_ALLOWED_ORIGINS` (default `ONBOARDING_WEB_URL`), `LOG_LEVEL`.

**Minty web hub (`minty-web`, Next.js)**: `PETTY_CASH_URL`, `SUBSCRIPTION_API_URL`,
`PAYMENT_REQUEST_WEB_URL`.

**Payment Request web (`minty-payment-request-web`, Next.js)**: `PETTY_CASH_URL`,
`PAYMENT_REQUEST_API_URL`, `SUBSCRIPTION_API_URL`; optional `MAINTENANCE_SHOW_NEW_LINK`.

**Onboarding web (`minty-onboarding-web`, Next.js)**: `PETTY_CASH_URL`, `ONBOARDING_API_URL`.
(Its old `/auth*` addresses forward through Flask - `PETTY_CASH_URL` - to minty-web's `/login`
since phase 2, 2026-10-05, so it needs no minty-web variable.)

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

**This section describes the shape `minty-infra` creates, and most of it is NOT live yet
(checked against the Render, Vercel, Supabase and B2 APIs on 2026-10-08).** What is actually
running today:

- **There is no production/development split at all.** Render has four Minty services, *all* on
  `branch=development`, and all with auto-deploy **off**. Two of them carry the production
  domains (`pettycash.`, `payment-backend.`). Vercel's production builds also come from
  `development`.
- `minty-billing-api` and `onboarding-backend` are on the **free plan with no custom domain**, so
  `subscription-api.dailyminty.com` and `onboarding-api.dailyminty.com` **do not exist yet**.
- One Supabase project and one schema (`pettycashv3`) serve every backend; one B2 bucket serves
  every environment.
- Each service's variables come from its own Render env group (`New-Petty-Cash` and the other
  three), not from the `minty-shared-<env>` group described below.

So, forward-looking: `main` **will deploy** production and `development` the development
environment, once `minty-infra` is applied. Until then the dashboards are the source of truth
(as §8's "Cutover checklist" already says) and variables are set per service there.

### CI (the shared workflows)

Every repo's `.github/workflows/ci.yml` is about a dozen lines that call a reusable workflow in
[`minty-oliveandvine/.github`](https://github.com/minty-oliveandvine/.github), pinned at `@v1`
(never `@main`). All of them trigger on `push` to `[main, development]` plus `pull_request`.

| Repo | Calls | Secret that repo must hold |
|---|---|---|
| Minty | `flask-app.yml` | - |
| Minty (`e2e.yml`, weekly + manual) | `stack-e2e.yml` | `STACK_READ_TOKEN` |
| minty-subscription-api | `python-api.yml` | `MINTY_READ_TOKEN` |
| minty-payment-request-api | `python-api.yml` | `MINTY_READ_TOKEN` |
| minty-onboarding-api | `python-api.yml` | `MINTY_READ_TOKEN` |
| minty-web | `next-web.yml` | - |
| minty-payment-request-web | `next-web.yml` | - |
| minty-onboarding-web | `next-web.yml` | - |
| minty-www (was daily-minty-landing-page) | `next-web.yml` | - |
| minty-infra | its own `check.yml` (`terraform fmt` / `validate`, no credentials) | - |

- **`MINTY_READ_TOKEN`** - a fine-grained PAT with read access to the *contents* of
  `minty-oliveandvine/Minty` only. The three Django APIs' Postgres test pass builds its database
  from Minty's `docs/schema/01_schema_rebased.sql` through `Minty/tests/pg_harness.py`, so Minty
  is checked out (sparse, two files) beside the caller.
- **`STACK_READ_TOKEN`** - a fine-grained PAT with read access to the contents of the four
  private repos, for the stack job's seven checkouts. It needs **no** application secret:
  `SECRET_KEY` is generated per run, `S3_URL` falls back to compose's dummy, Stripe/SMTP stay
  unset and `E2E_XERO` stays off.
- The `.github` repo is **public**, because a public repo (minty-web, minty-payment-request-web,
  minty-onboarding-web) cannot call a reusable workflow that lives in a private one. Only workflow
  YAML lives there; secrets are passed by name from each caller.
- Browser tests run from Minty's `e2e.yml`, not in each repo's CI - they need the whole stack.
  The exception is the landing page, whose Playwright config starts its own server.
- `minty-infra`'s `github.tf` does **not** set required status checks yet, so a red run blocks no
  merge; and on GitHub Free, rulesets and environments exist only on public repos - which is now
  all seven application repos, leaving only `minty-infra` itself ungated (`github_pro = false`).

### Hosting as code (`minty-infra`, Option B)

The repo [`minty-infra`](https://github.com/minty-oliveandvine/minty-infra) brings the
dashboards into Terraform. **Option B - today's services (Render, Vercel, Supabase, B2,
GitHub) - was chosen on 2026-10-07** and lives on `minty-infra`'s `main`. Until it is applied
(`minty-infra/CUTOVER.md`: development first, production in the cutover window), the dashboards
above stay the source of truth.

Option A (the three Next.js apps on Cloudflare Workers, `dailyminty.com` on Cloudflare DNS,
backends still on Render) stays parked on the `infra-cloudflare` branches of `minty-infra`,
Minty and the three Next.js repos.

`minty-infra/services.tf` holds this table and nothing else generates a hostname. **"live?" says
whether that host exists today** — every "no" is created by the apply, not already there.

| Service | Production | live? | Development | live? | Host |
|---|---|---|---|---|---|
| Petty Cash | `pettycash.dailyminty.com` | yes | `dev-pettycash.dailyminty.com` | no | Render |
| Subscription API | `subscription-api.dailyminty.com` | **no** | `dev-subscription-api.dailyminty.com` | no | Render |
| Payment Request API | `payment-backend.dailyminty.com` | yes | `dev-payment-backend.dailyminty.com` | no | Render |
| Onboarding API | `onboarding-api.dailyminty.com` | **no** | `dev-onboarding-api.dailyminty.com` | no | Render |
| Minty web hub | `my.dailyminty.com` | yes | `dev-my.dailyminty.com` | no | Vercel |
| Payment Request web | `payment.dailyminty.com` | yes | `dev-payment.dailyminty.com` | no | Vercel |
| Onboarding web | `onboarding.dailyminty.com` | yes | `dev-onboarding.dailyminty.com` | no | Vercel |

- **The hub is `my.dailyminty.com`** (corrected 2026-10-09; this table said `login.` and was
  wrong). That is what `MINTY_WEB_URL` is set to on every live service, and it is not just a
  link: `blueprints/shared/hub_api.py` and `pettycash/core/hooks.py` use it as the **CORS allowed
  origin** for Flask's hub bearer API, so naming the wrong host there stops `/api/me/entities`
  and `/api/me/profile` working in the browser with nothing in the logs.
  `login.dailyminty.com` was a second address on the same Vercel project with nothing routing to
  it; it was **detached 2026-10-09** and no longer serves the hub. It was never in Terraform
  state, so nothing was applied. The hub's two open pages are **`/login`** (log in, invitations)
  and **`/signup`** (make an account — its own route since 2026-10-09); `hub_login.py` builds
  both, and `proxy.ts` 307s the old `/login?mode=signup` to `/signup`.
- The two **`no`**s in the Production column are services on Render's free plan with no custom
  domain. Anything that assumes `subscription-api.dailyminty.com` resolves today is wrong.
- Every `*_URL` above is set by Terraform from that one table; no dashboard edit.
- `APP_ENV`, `SECRET_KEY` and `DATABASE_URL` **will come** from one Render env group per
  environment (`minty-shared-<env>`), so a `SECRET_KEY` rotation is one value and one apply.
  Today they are set per service in the four `New-*` groups, which `render.tf` does not model —
  `minty-infra/terraform.tfvars`'s `extra_env` carries what it does not write.
- The subscription pass runs as an hourly Render cron job (`manage.py subscriptions tick`) in
  production; `SUBSCRIPTION_SCHEDULER_ENABLED=0` on every Render service. **The cron job does not
  exist yet** — it is created with the production stage.
- Render **will deploy** a branch only after its CI checks pass (`auto_deploy_trigger =
  "checksPass"`). Auto-deploy is currently **off** on every Render service, so that apply turns
  it on for the first time. Vercel's development environment is the preview deployment of the
  `development` branch.
- `S3_URL` **will use** a key scoped to one bucket per environment (development gets its own
  bucket). Today one bucket, `pettycash`, serves every environment, and production's key is a B2
  application key holding **all 27 capabilities** with no bucket restriction.

And:

- **Migrations are deliberate.** Hosted services run with `RUN_MIGRATIONS=false` (set by
  `minty-infra`; the image's own default is still `true`, so nothing changes until that apply).
  The schema moves only through Minty's manual **migrate** workflow
  (`.github/workflows/migrate.yml`: `current` to look, `upgrade` to apply; production from
  `main` behind the `production-db` environment). Run it **before** merging code that needs
  the new columns.
- **Health checks:** Petty Cash `/health`, subscription API `/healthz`, payment-request API
  `/healthz`, onboarding API `/health` — liveness only, no database.
- **Docker** (`docker/Dockerfile`) starts gunicorn like the `Procfile`: 2 workers
  (`GUNICORN_WORKERS`), 4 threads, `--timeout 120`.

### Cutover checklist

Do it in this order — the old variables can stay in place until the end, because nothing
running yet reads the new ones and nothing new reads the old ones:

1. **Set the new variables on every development service** (§5): `APP_ENV`, `DATABASE_URL`
   (with `?schema=pettycashv3`), `S3_URL`, `SMTP_URL`, `MAIL_FROM`, the `*_URL` set - including
   the onboarding API's `SUBSCRIPTION_API_URL`, without which it no longer starts (2026-10-06);
   on Render leave `PORT` to the platform. Rotate `SECRET_KEY` (§4) while you are there.
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
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `SUBSCRIPTION_SCHEDULER_*`, `SUBSCRIPTION_EMAIL` | PC | removed from Petty Cash (2026-10-06; still the subscription API's) |

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
`GOOGLE_CLOUD_PROJECT`, the legal flags, `MINTY_WEB_URL`, `INVITATION_*`,
`AUTO_SUPERUSER_EMAILS`, `DD_CLIENT_TOKEN`, `DISPLAY_TIMEZONE`, `RUN_MIGRATIONS`,
`DB_WAIT_SECONDS`, `SESSION_TYPE`, `GUNICORN_WORKERS`, and the test-only variables.
