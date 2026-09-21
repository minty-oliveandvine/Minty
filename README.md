# Minty

The Flask application behind Minty — companies, users, petty cash, Xero integration and the
subscription/billing engine. Historically "pettycashv3", and still the repo the other services
are being carved out of.

Runs on **port 5001**.

## The services around it

Minty is no longer the whole product. It is one of several repos, all against the same
PostgreSQL database and `pettycashv3` schema:

| Repo | What it is | Port |
|---|---|---|
| **Minty** (this one) | Flask. Auth, entities, petty cash, Xero, subscriptions | 5001 |
| `billing-backend` | Django + django-ninja. Bills, payments, Xero bill sync | 8000 |
| `billing-frontend` | Next.js. The payment-request module and the payer portal | 3000 |
| `onboarding` | Next.js. The nine-step new-company wizard | 3001 |
| `onboarding-backend` | Django + django-ninja. The wizard's API, extracted from this repo | 8001 |

The sibling repos live beside this one (`C:\Github\…`, as `CLAUDE.md`'s folder map lists them).

Two things hold them together and are easy to get wrong:

- **`SECRET_KEY` must be identical across Minty, `billing-backend` and `onboarding-backend`.**
  Minty mints the HS256 JWTs; the others only verify them. A mismatch is not a loud failure —
  it is a 401 on every request, which the frontends report as an expired session.
- **Alembic in this repo owns the schema.** The Django services map onto it with
  `managed = False` and ship no migrations of their own. A new column starts here.

## Live deployments

| Environment | URL |
|---|---|
| Production | https://minty.oliveandvinehk.com |
| Staging | https://staging-olive-and-vine-minty-26bm.onrender.com |
| Pre-staging | https://pre-staging-olive-and-vine-minty.onrender.com |
| Development | https://development-olive-and-vine-minty.onrender.com |

Taken from `billing-frontend/lib/mintyEnv.ts`, which is what the frontends actually call.
**Which branch deploys to which environment is configured in the Render dashboard, not in this
repo** — check there rather than trusting a list here.

## Running with Docker (recommended)

Docker runs the app **and** PostgreSQL in containers, so you need neither Python nor Postgres
locally. No Docker Hub account — the image is built from this repo.

### Just Minty and a database

```bash
git clone https://github.com/minty-oliveandvine/Minty.git
cd Minty
cp .env.example .env
cd docker
docker compose up --build
```

Builds the image, starts Postgres, waits for the DB, then serves the app on
http://localhost:5001. Code reloads automatically via `docker-compose.override.yml`, which is
applied when you run compose from inside `docker/`.

### The whole stack

`docker/stack/` brings up Minty, both Django services and both Next.js frontends together,
building the siblings from `../../../<repo>`. See [docker/stack/README.md](docker/stack/README.md).

```bash
cd docker/stack
docker compose up --build
```

`RUN_MIGRATIONS` defaults to `false` there, because the Alembic chain cannot currently build a
database from empty.

### Common commands (from `docker/`)

| Task | Command |
|---|---|
| Start (foreground, see logs) | `docker compose up` |
| Start in background | `docker compose up -d` |
| Rebuild after dependency changes | `docker compose up --build` |
| Stop containers | `docker compose down` |
| Stop **and wipe the database** | `docker compose down -v` |
| View app logs | `docker compose logs -f app` |
| Shell in the app container | `docker compose exec app sh` |
| Run a migration manually | `docker compose exec app flask --app main.py db upgrade` |

From the project root instead, pass both files so the dev override still applies:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml up --build
```

## Running without Docker

Requires **Python 3.11.9** and a PostgreSQL you can point at.

```bash
git clone https://github.com/minty-oliveandvine/Minty.git
cd Minty
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # then fill in the database URIs and SECRET_KEY
flask --app main.py db upgrade
flask run --host=localhost --port=5001 --debug
```

`.env.example` documents every variable. The ones without defaults —  `SECRET_KEY`,
`WTF_CSRF_SECRET_KEY`, `LOCAL_DATABASE_URI`, `RDS_DATABASE_URI`, `S3_*` — are required, and the
app raises at startup if any is missing.

## Tests

```bash
pytest -n auto        # Postgres only; each worker builds docs/schema/01_schema_rebased.sql into its own database
npm run test:e2e      # Playwright against a running Flask — e2e/README.md
```

The suite is green (1,694 passed on 2026-09-18, about two minutes). Compare a full run
before your change against a full run after — never a single file — and grep for `ERROR`
as well as `FAILED`, since collection errors do not show as failures.

## Documentation

- [`docs/features/README.md`](docs/features/README.md) — one page per feature: authentication
  across the five apps, companies and members, the report wizard, receipts, exports, Xero,
  modules and subscriptions, the hand-offs, terms, expense AI, operations.
- [`docs/schema/README.md`](docs/schema/README.md) — the redesigned database and the one-hop
  migration; [`docs/modernisation/modernisation_plan.md`](docs/modernisation/modernisation_plan.md)
  — the plan and the cutover runbook.

## Contributing

Work happens on `Minty-*` branches (`Minty-PettyCash`, `Minty-BillingBackend`, …), not on
`main`/`staging`/`dev` — an earlier version of this README described those, and they do not
exist in this repository. Branch from the one you are working against and open a PR back to it.
