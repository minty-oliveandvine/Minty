# 🐳 Run the whole Minty system

One command starts all seven repos and their shared database. If you only want
the Flask app and its database, use [`../README.md`](../README.md) instead —
that setup covers this repo alone.

| Service (hostname) | Repo | URL | What it is |
|---------|------|-----|------------|
| `minty-web` | `minty-web` | <http://localhost:3000> | The hub — Next.js |
| `subscription-api` | `minty-subscription-api` | <http://localhost:8000> | Subscriptions API — Django |
| `minty` | `Minty` | <http://localhost:8010> | Petty Cash — Flask app (owns the database schema) |
| `payment-request-web` | `minty-payment-request-web` | <http://localhost:3020> | Payment Request — Next.js UI |
| `payment-request-api` | `minty-payment-request-api` | <http://localhost:8020> | Payment Request — Django API |
| `onboarding-web` | `minty-onboarding-web` | <http://localhost:3030> | Onboarding — Next.js UI |
| `onboarding-api` | `minty-onboarding-api` | <http://localhost:8030> | Onboarding API — Django, extracted from Minty |
| `db` | — | `localhost:5433` | PostgreSQL 15, shared by every backend (`db:5432` inside the network) |

Ports follow one slot per domain: `30N0` for a web app, `80N0` for its API. Every variable
each service reads, and the old → new rename table, are in
[`docs/ENVIRONMENT.md`](../../docs/ENVIRONMENT.md).

---

## 1. Before you start

- **Docker Desktop** installed and running (whale icon in the tray).
  Compose **v2.24 or newer** — check with `docker compose version`.
- **All seven repos checked out side by side**, e.g.

  ```
  C:\Github\
    ├── Minty\                       ← you are here
    ├── minty-web\
    ├── minty-subscription-api\
    ├── minty-payment-request-web\
    ├── minty-payment-request-api\
    ├── minty-onboarding-web\
    └── minty-onboarding-api\
  ```

  If your layout differs — for instance a checkout still in a folder named after
  the old repo name (`billing-backend`, `onboarding`, …) — set the `*_PATH`
  variables in `.env` (step 2): `MINTY_PATH`, `MINTY_WEB_PATH`,
  `SUBSCRIPTION_API_PATH`, `PAYMENT_REQUEST_API_PATH`, `PAYMENT_REQUEST_WEB_PATH`,
  `ONBOARDING_API_PATH`, `ONBOARDING_WEB_PATH`.

You do **not** need Python, Node, or Postgres installed.

---

## 2. Create your settings file (one time)

From this folder:

```bash
cp .env.example .env      # PowerShell: copy .env.example .env
```

Open `.env` and set **`SECRET_KEY`** to a real value:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

That one key is shared by Flask and Django — Flask signs the JWT that hands a
signed-in user over to another module, and the Django APIs verify it with the
same key. If they differ, every module handoff fails with a 401.

Everything else has a working local default. The compose file builds one
`DATABASE_URL` (`postgresql://…@db:5432/minty_ref?schema=pettycashv3`) from the
`POSTGRES_*` / `DB_SCHEMA` values and hands it to every service, and sets each
service URL itself. Secrets you already have in `../../.env` (Minty) and the
sibling repos' `.env` files are loaded automatically underneath this file, so
you don't need to copy Stripe, Xero, `SMTP_URL` or `S3_URL` values across — only
override here what you want to change.

---

## 3. Start everything 🚀

```bash
docker compose up --build
```

The first run takes several minutes (it downloads Python and Node and installs
every dependency). Later starts are much faster.

Startup is ordered, and that order matters:

1. `db` comes up and passes its health check.
2. `minty` creates the `pettycashv3` schema, then starts serving.
3. `payment-request-api`, `onboarding-api` and `subscription-api` wait for
   `minty` to be **healthy** — they are tenants of Flask's schema and must never
   get there first.
4. The three Next.js apps start.

You're ready when the logs settle. Open <http://localhost:8010>.

The database comes up **empty** — see the next section.

---

## 3b. Getting a schema ⚠️

`RUN_MIGRATIONS` ships as `false`, and that is deliberate: **the Alembic chain
cannot currently build a database from empty.** `0001_full_schema` was
consolidated from the current models, but the revisions after it still assume
the pre-consolidation state and collide with it — e.g. `f731e24bfe62`
re-creates `currency_info` and `user`, which `0001` has already created. The
upgrade runs in one transaction, so it rolls back and leaves you with nothing.

This is a repo-level defect, not a Docker one — a fresh local Postgres hits it
too. Until the chain is repaired, load a schema into the container yourself:

```bash
# Restore a dump from a working database into the stack's Postgres.
docker compose exec -T db psql -U minty_ref_user -d minty_ref < your_dump.sql

# ...or, for a custom-format dump:
docker compose cp your.dump db:/tmp/your.dump
docker compose exec db pg_restore -U minty_ref_user -d minty_ref /tmp/your.dump
```

Then restart the backends so they pick it up:

```bash
docker compose restart minty payment-request-api onboarding-api subscription-api
```

Once you're on a database that is already past the broken revisions, you can set
`RUN_MIGRATIONS=true` in `.env` to have both services migrate on start again.

Two cold-start blockers have already been fixed and are worth knowing about if
you pick the repair up:

- `docker/docker-entrypoint.sh` runs the upgrade with `SESSION_TYPE=cachelib`,
  because Flask-Session creates its `sessions` table at app-import time and
  would otherwise beat Alembic to it.
- `migrations/versions/0002_sync_user_columns.py` is guarded on column
  existence; it re-added `user.system_role`, which `0001` already creates.

---

## 4. Editing code while it runs

The Next.js apps, `minty`, `payment-request-api` and `subscription-api` bind-mount
their repo, so **save a file and it reloads.** No rebuild needed for ordinary
code changes.

Rebuild only when *dependencies* change:

```bash
docker compose up --build <service>     # e.g. payment-request-web
```

---

## 5. Everyday commands

Run these from this folder.

| I want to… | Command |
|------------|---------|
| Start and watch logs | `docker compose up` |
| Start in the background | `docker compose up -d` |
| Rebuild after a dependency change | `docker compose up --build` |
| Follow one service's logs | `docker compose logs -f minty` |
| Restart one service | `docker compose restart payment-request-api` |
| Shell inside a container | `docker compose exec minty sh` |
| Run Flask migrations by hand | `docker compose exec minty flask --app main.py db upgrade` |
| Run Django migrations by hand | `docker compose exec payment-request-api python manage.py migrate` |
| Stop everything | `docker compose down` |
| Stop **and wipe the database** | `docker compose down -v` |

> ⚠️ `docker compose down -v` deletes all local database data.

### Running the backends under gunicorn

`docker-compose.override.yml` is applied automatically and swaps `minty`,
`payment-request-api` and `subscription-api` to their auto-reloading dev servers. To run them the way they run when
deployed, skip it:

```bash
docker compose -f docker-compose.yml up
```

---

## 6. How the wiring works

Two kinds of URL, and mixing them up is the most common way to break this stack:

- **Browser-facing** — every URL handed to a Next.js app, Flask's own
  `PETTY_CASH_URL`, `subscription-api`'s `PETTY_CASH_PUBLIC_URL`, and the
  `*_WEB_URL` redirect/CORS origins. These end up in the address bar or in a
  `fetch()` the browser runs, so they are `http://localhost:<host port>`. A
  container name resolves inside Docker's network but not on your machine, so
  the page would fail every request.
- **Server-to-server** — `PETTY_CASH_URL` on the three Django APIs, and
  `DATABASE_URL`. These are dialled by one container to another, so they use the
  compose service name (`http://minty:8010`, `db:5432`) and never leave the
  network. That is why `subscription-api` carries both `PETTY_CASH_URL`
  (internal) and `PETTY_CASH_PUBLIC_URL` (the one its emails link to).

All of them are set in `docker-compose.yml` and the browser-facing ones are
built from the `*_HOST_PORT` values in `.env`, so changing a host port there is
all it takes.

**Xero:** the Flask app is the only service allowed to refresh Xero tokens.
The Django APIs ask it for one at `PETTY_CASH_URL/api/internal/xero/token` over
the internal URL. Never give them their own Xero credentials — Xero invalidates
a refresh token the moment it is used, so a second refresher breaks the
connection until someone reconnects by hand. The redirect URI registered in the
Xero app must be `http://localhost:8010/callback` (`PETTY_CASH_URL/callback`).

**Subscriptions (Part 2):** always on - the dark switch (`SUBSCRIPTION_ENABLED`)
was removed on 2026-10-01. The one switch left is the daily pass,
`SUBSCRIPTION_SCHEDULER_ENABLED`, read by `minty` AND `subscription-api`: never set it
on both, they share the database. Stripe keys are read by `minty` and by
`subscription-api`.

---

## 7. Note on the database volume

This stack uses its own volume (`minty-stack_postgres_data`), separate from the
Flask-only setup in `../` (`docker_postgres_data`). Data does not carry over
between the two, and that's deliberate — the single-repo setup has no payment-request
tables in it. Use one or the other consistently.

---

## 8. Troubleshooting

**"Cannot connect to the Docker daemon"**
→ Docker Desktop isn't running. Start it and wait for the whale icon.

**"port is already allocated"**
→ Something on your machine already uses 5433/3000/8000/8010/3020/8020/3030/8030. Either
stop it, or change the matching `*_HOST_PORT` in `.env` (`DB_HOST_PORT`,
`MINTY_WEB_HOST_PORT`, `SUBSCRIPTION_API_HOST_PORT`, `MINTY_HOST_PORT`,
`PAYMENT_REQUEST_WEB_HOST_PORT`, `PAYMENT_REQUEST_API_HOST_PORT`,
`ONBOARDING_WEB_HOST_PORT`, `ONBOARDING_API_HOST_PORT`); the URLs follow it.

**`payment-request-api` exits with "Database/schema not ready"**
→ `minty` never got as far as creating the `pettycashv3` schema. Read its logs
first: `docker compose logs minty`.

**The app loads but every page errors on a missing table**
→ The database is empty. See [Getting a schema](#3b-getting-a-schema-️).

**`DuplicateTable` / `DuplicateColumn` during migration**
→ You turned `RUN_MIGRATIONS` on against an empty database. That path is broken
today; see [Getting a schema](#3b-getting-a-schema-️).

**Module handoff bounces you back to login / 401s**
→ `SECRET_KEY` differs between the backends. It is set once in `.env` and
injected into all of them; confirm
`docker compose exec minty printenv SECRET_KEY` matches
`docker compose exec payment-request-api printenv SECRET_KEY`.

**A frontend can't reach an API (CORS or connection refused)**
→ Check the URL values are `localhost` URLs:
`docker compose exec payment-request-web printenv | grep _URL`. The Next.js apps
read them when the dev server starts, so restart the service after a change.

**Edits don't show up**
→ Polling is enabled for the frontends (`WATCHPACK_POLLING`). If a Python
change is ignored, confirm the override is active:
`docker compose config | grep -A2 "command:"` should show the dev servers.

**Database looks broken**
→ Clean start (deletes local DB data):
```bash
docker compose down -v
docker compose up --build
```

---

## Quick reference (TL;DR)

```bash
cd docker/stack
cp .env.example .env          # set SECRET_KEY
docker compose up --build

# the database starts EMPTY — load a schema into it:
docker compose exec -T db psql -U minty_ref_user -d minty_ref < your_dump.sql
docker compose restart minty payment-request-api onboarding-api subscription-api

# Minty hub                http://localhost:3000
# Subscription API         http://localhost:8000
# Petty Cash (Flask)       http://localhost:8010
# Payment Request UI       http://localhost:3020
# Payment Request API      http://localhost:8020
# Onboarding UI            http://localhost:3030
# Onboarding API           http://localhost:8030

docker compose down           # stop
```
