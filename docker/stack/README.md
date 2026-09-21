# 🐳 Run the whole Minty system

One command starts all seven repos and their shared database. If you only want
the Flask app and its database, use [`../README.md`](../README.md) instead —
that setup covers this repo alone.

| Service | Repo | URL | What it is |
|---------|------|-----|------------|
| `minty` | `Minty` | <http://localhost:5001> | Module 1 — Flask app (owns the database schema) |
| `billing-backend` | `billing-backend` | <http://localhost:8000> | Module 2 — Django API |
| `billing-frontend` | `billing-frontend` | <http://localhost:3000> | Module 2 — Next.js UI |
| `onboarding-backend` | `onboarding-backend` | <http://localhost:8001> | Onboarding API — Django, extracted from Minty |
| `onboarding` | `onboarding` | <http://localhost:3001> | Onboarding — Next.js UI |
| `billing-api` | `minty-billing-api` | <http://localhost:8004> | Subscriptions API — Django, Part 2 of the modernisation plan (dark unless `SUBSCRIPTION_ENABLED=1`) |
| `minty-web` | `minty-web` | <http://localhost:3002> | The hub — Next.js, Part 2; subscriptions is its only feature until Part 3 |
| `db` | — | `localhost:5432` | PostgreSQL 15, shared by every backend |

Ports follow the plan's rule 6 — one digit per domain, `800d` for a Django API and `300d`
for its Next.js UI (`docs/modernisation/modernisation_plan.md`, Part 3 § cross-cutting rules).

---

## 1. Before you start

- **Docker Desktop** installed and running (whale icon in the tray).
  Compose **v2.24 or newer** — check with `docker compose version`.
- **All seven repos checked out side by side**, e.g.

  ```
  C:\Github\
    ├── Minty\              ← you are here
    ├── billing-backend\
    ├── billing-frontend\
    ├── onboarding\
    ├── onboarding-backend\
    ├── minty-billing-api\  ← Part 2
    └── minty-web\          ← Part 2
  ```

  If your layout differs, set the `*_PATH` variables in `.env` (step 2).

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
signed-in user over to the billing module, and Django verifies it with the same
key. If they differ, every module handoff fails with a 401.

Everything else has a working local default. Secrets you already have in
`../../.env` (Minty) and `../../../billing-backend/.env` are loaded
automatically underneath this file, so you don't need to copy Stripe, Xero,
mail or S3 values across — only override here what you want to change.

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
3. `billing-backend`, `onboarding-backend` and `billing-api` wait for `minty` to
   be **healthy** — they are tenants of Flask's schema and must never get there
   first.
4. The three frontends start.

You're ready when the logs settle. Open <http://localhost:5001>.

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
docker compose restart minty billing-backend onboarding-backend billing-api
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

All seven services bind-mount their repo, so **save a file and it reloads.** No
rebuild needed for ordinary code changes.

Rebuild only when *dependencies* change:

```bash
docker compose up --build <service>     # e.g. billing-frontend
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
| Restart one service | `docker compose restart billing-backend` |
| Shell inside a container | `docker compose exec minty sh` |
| Run Flask migrations by hand | `docker compose exec minty flask --app main.py db upgrade` |
| Run Django migrations by hand | `docker compose exec billing-backend python manage.py migrate` |
| Stop everything | `docker compose down` |
| Stop **and wipe the database** | `docker compose down -v` |

> ⚠️ `docker compose down -v` deletes all local database data.

### Running the backends under gunicorn

`docker-compose.override.yml` is applied automatically and swaps both Python
services to their auto-reloading dev servers. To run them the way they run when
deployed, skip it:

```bash
docker compose -f docker-compose.yml up
```

---

## 6. How the wiring works

Two kinds of URL, and mixing them up is the most common way to break this stack:

- **Browser-facing** (`PUBLIC_URL`, `FRONTEND_APP_URL`, `ONBOARDING_APP_URL`,
  every `NEXT_PUBLIC_*`) — these end up in the address bar or in a `fetch()`
  the browser runs. They must be `http://localhost:<port>`. A container name
  resolves inside Docker's network but not on your machine, so the page would
  fail every request.
- **Server-to-server** (`FLASK_APP_URL`, `XERO_TOKEN_SERVICE_URL`, the database
  URIs) — these are dialled by one container to another. They use the compose
  service name (`http://minty:5001`, `db:5432`) and never leave the network.

Both are already set correctly in `docker-compose.yml`; you only touch them if
you change a host port, in which case update the matching `*_PUBLIC_URL` in
`.env` too.

**Xero:** the Flask app is the only service allowed to refresh Xero tokens.
Billing asks it for one over the internal URL. Never give the billing backend
its own `XERO_CLIENT_ID`/`SECRET` — Xero invalidates a refresh token the moment
it is used, so a second refresher breaks the connection until someone
reconnects by hand.

**Subscriptions (Part 2):** `billing-api` and `minty-web` ship **dark**. Three
backends read `SUBSCRIPTION_ENABLED` (`minty`, `onboarding-backend`, `billing-api`)
and must carry the same value; the two web apps read
`NEXT_PUBLIC_SUBSCRIPTION_ENABLED`, which is on unless `0`. Dark, every
`billing-api` route answers 404 (with CORS headers) and its scheduler never
starts. Stripe keys are read by `minty` today and by `billing-api`; from Part 2
step 5 only `billing-api` holds them.

---

## 7. Note on the database volume

This stack uses its own volume (`minty-stack_postgres_data`), separate from the
Flask-only setup in `../` (`docker_postgres_data`). Data does not carry over
between the two, and that's deliberate — the single-repo setup has no billing
tables in it. Use one or the other consistently.

---

## 8. Troubleshooting

**"Cannot connect to the Docker daemon"**
→ Docker Desktop isn't running. Start it and wait for the whale icon.

**"port is already allocated"**
→ Something on your machine already uses 5432/5001/8000/8001/8004/3000/3001/3002. Either stop
it, or change the matching `*_HOST_PORT` in `.env` (and the `*_PUBLIC_URL` that
goes with it).

**`billing-backend` exits with "Database/schema not ready"**
→ `minty` never got as far as creating the `pettycashv3` schema. Read its logs
first: `docker compose logs minty`.

**The app loads but every page errors on a missing table**
→ The database is empty. See [Getting a schema](#3b-getting-a-schema-️).

**`DuplicateTable` / `DuplicateColumn` during migration**
→ You turned `RUN_MIGRATIONS` on against an empty database. That path is broken
today; see [Getting a schema](#3b-getting-a-schema-️).

**Module handoff bounces you back to login / 401s**
→ `SECRET_KEY` differs between the two backends. It is set once in `.env` and
injected into both; check nothing in `../../.env` is shadowing it by confirming
`docker compose exec minty printenv SECRET_KEY` matches
`docker compose exec billing-backend printenv SECRET_KEY`.

**A frontend can't reach an API (CORS or connection refused)**
→ Check the `NEXT_PUBLIC_*` values are `localhost` URLs:
`docker compose exec billing-frontend printenv | grep NEXT_PUBLIC`.

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
docker compose restart minty billing-backend onboarding-backend billing-api

# Minty              http://localhost:5001
# Billing API        http://localhost:8000
# Onboarding API     http://localhost:8001
# Subscriptions API  http://localhost:8004   (every route 404 while dark)
# Billing UI         http://localhost:3000
# Onboarding UI      http://localhost:3001
# Minty hub          http://localhost:3002

docker compose down           # stop
```
