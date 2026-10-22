# CI and the stack E2E job

Every Minty **app** repo's `.github/workflows/ci.yml` is about a dozen lines that call a reusable
workflow in the public [`minty-oliveandvine/.github`](https://github.com/minty-oliveandvine/.github)
repo, pinned at `@v1`. That repo's README is the reference for the inputs; this page covers
Minty's two workflows and how to rehearse the stack job locally.

## The one documented exception: `minty-shared-ts`

`minty-shared-ts` (`@minty/shared`, created 2026-10-12) carries its **own** 20-line `ci.yml`
instead of calling into `.github`, deliberately:

- `next-web.yml` ends in `next build`, and a library published as source has nothing to build;
- a reusable workflow with exactly one caller is not shared CI. The stated reason `.github` exists
  is that fixing CI for all of them is one change in one place, which needs an *all*. This is the
  same judgement the modernisation plan already makes for `py-package.yml`, deferred until
  `minty-db` / `minty-shared-py` exist.

`minty-shared-py` (2026-10-22, public, immutable `vX.Y` tags) makes the same call for Python: its
own `ci.yml` runs Python 3.13, `pip install -e .[dev]`, then `ruff check`, `ruff format --check`,
`pyright` (strict) and `pytest`. `py-package.yml` arrives with a second Python package
(`minty-db`). Its five consumers (Minty and the four APIs) install it from the tag's archive over HTTPS (`.../archive/refs/tags/vX.Y.tar.gz`, never `git+`: the
slim Docker images have no git),
which works with no key only because the repo is public.

It runs checkout -> Node 24 (what `next-web.yml` defaults to, and what Vercel builds the consumers
with) -> `npm ci` -> `typecheck` -> `lint` -> `test`. **The day a second TypeScript package
exists, this becomes `ts-package.yml` in `.github` and both call it.**

### A shared change is proven in the consumer, not here

The package's CI never compiles a consumer - that would mean checking out other repos. Instead a
release is a git tag and each app bumps its pin in its own branch, so **that app's** CI and its
Vercel preview build run against the new tag before `development` moves:

```
minty-shared-ts: development -> green -> main -> git tag -a vX.Y -> push the tag
each consumer:   npm install "git+https://github.com/minty-oliveandvine/minty-shared-ts.git#vX.Y"
                 -> push a BRANCH -> check / check green + preview build green -> merge
```

Two rules that are not style:

- **The lockfile will say `git+ssh://`, and that is expected.** npm normalises any GitHub URL
  you type - including `git+https://...` - to the `github:` shorthand in `package.json` and a
  `git+ssh://` resolution in `package-lock.json`. For a **public** repo npm falls back to HTTPS,
  so `npm ci` works with no SSH key anywhere (verified 2026-10-12 by forcing ssh to fail, for both
  `npm install` and `npm ci`). **This is one of the reasons the package repo is public**: make it
  private and every CI and Vercel install breaks until a deploy key exists.
- **A tag here is immutable** - the opposite of `.github`'s `v1`, which moves by design. npm
  caches git dependencies, so a moved tag hands two machines different code under one pin. No
  `#main` or `#development` pins anywhere.

Never push a pin bump straight to `development`: Vercel auto-deploys on push and production builds
from that branch, so a pin that cannot install becomes a failed production build.

The design, and the four corrections the survey of 2026-10-07 forced on it, are in
[`../modernisation/modernisation_plan.md`](../modernisation/modernisation_plan.md), section
"CI/CD". Which repo calls which workflow, and the secret each one needs, is in
[`../ENVIRONMENT.md`](../ENVIRONMENT.md) section 8.

## Minty's workflows

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | `push` to `main`/`development`, every PR | calls `flask-app.yml`: `pytest -n auto` on a Postgres built from `docs/schema/01_schema_rebased.sql` |
| `e2e.yml` | **manual**, plus Sundays 19:00 UTC | calls `stack-e2e.yml`: the whole seven-service stack, then one repo's Playwright specs |
| `migrate.yml` | **manual** only | `flask db current` / `flask db upgrade` against a chosen environment |

**Branch preview sets** are the frontends' business, not Minty's: each of the four Next.js repos
has a `preview.yml` calling the `.github` repo's `vercel-preview-set.yml` (minty-infra `CUTOVER.md`
section 6). Flask's part is only handing back into a set (`authentication.md` 6.1).

`ci.yml` runs no ruff: `ruff check .` reports 96 findings over this repo and there is no
`[tool.ruff]` section to narrow them, so adopting it is a cleanup task of its own. The three
Django APIs are clean and do lint in CI.

## The stack job

It needs no application secret. `SECRET_KEY` is generated per run — it only has to be the *same*
for every service, which is what the hand-off JWTs depend on — `S3_URL` falls back to compose's
dummy, Stripe and SMTP stay unset, and `E2E_XERO` stays off. The one secret is
`STACK_READ_TOKEN`, a read-only PAT for the four private checkouts.

What it does, in order:

1. Checks out all seven repos side by side, which is exactly what `docker/stack`'s `*_PATH`
   defaults assume.
2. `docker compose -f docker-compose.yml up -d --wait db`. The `-f` is deliberate on every call:
   it skips `docker-compose.override.yml`, so the backends run under gunicorn rather than the
   auto-reloading dev servers.
3. **Builds the schema** by running `docs/schema/01_schema_rebased.sql` into the database and
   renaming `pettycash_test` to `pettycashv3` — the same two steps `tests/pg_harness.py` takes.
   `RUN_MIGRATIONS` stays `false`: the Alembic chain cannot build from empty
   (`docker/stack/README.md` section 3b), and the schema file is the source of truth anyway.
   The rename is checked rather than assumed, so a change to what the file creates says so.
4. Brings up the other six with `--wait` (every service has a healthcheck, and the Django APIs
   already wait for Flask to be healthy).
5. Runs `scripts/e2e_seed.py --print` inside the `minty` container and pipes the `E2E_*` block it
   prints into the job. The seed creates its own reference rows (HKD, the denominations, the
   `entity_function` rows), so it works against a schema with no data in it.
6. Runs the chosen repo's `npm run test:e2e` against the stack's localhost ports.

### The cold start's catalogue (found and closed by running it, 2026-10-07)

A database built from `01_schema_rebased.sql` has no `billing_plan` and no `billing_policy` rows,
so no subscription journey could run against it: a trial start had no plan to start. Running the
job is what found it - 79 of minty-web's 81 specs passed and
`features/subscription/e2e/04_live_api.spec.ts` sat on the Confirm dialog until Playwright's 45s
timeout.

Those two tables used to arrive only by **migrating a legacy database**:
`02_data_foundation_rebased.sql` reads them out of `pettycashv2` in the same database, which an
empty one does not have, and nothing in any repo created them - `manage.py plans list` says so in
its own docstring ("Read-only; the catalog is edited by hand in SQL"). The catalogue lived in the
databases it had been typed into and nowhere in version control.

**[`docs/schema/seed_catalogue.sql`](../schema/seed_catalogue.sql) is now that catalogue, in git**
- three plans, the one policy row, and the single `currency_info` row the plans' foreign key needs.
It is idempotent and never UPDATEs, so it cannot silently revert a price edited in a database. The
job loads it straight after the schema and then checks the rows are there. Changing a price or a
window means changing the row **and** that file in the same change.

It also uncovered a second, quieter disagreement: `scripts/e2e_seed.py` created HKD with
`symbol="$"` while production records no symbol at all, and the browser falls back to the currency
code when none is recorded. So production renders `HKD 400` and the specs match on `HK$0` or
`HKD 0`, but a cold start rendered `$0` and matched neither. In a migrated database HKD already
exists, so that branch never ran and the defect was invisible. `e2e_seed.py` now writes `symbol=""`
to agree with production, and the catalogue seed runs before the services so HKD is already right
whichever way round they run.

With both in place the suite is **80 passed, 1 skipped, 0 failed** (the skip is 08-C's Stripe
address form, which needs Stripe keys by design).

### Which suites it can run

`e2e.yml` offers `minty-web` (the default), `Minty` and `minty-payment-request-web`.
**`minty-onboarding-web` is refused by name**: its `walk` and `resume` specs need a disposable
entity in `onboarding` status (`E2E_ENTITY_ID`) that `scripts/e2e_seed.py` does not create yet.
Adding that to the seed is what it takes to let that suite in.

**Flask has no browser specs of its own since 2026-10-20**: it draws no page, and the specs that
drove its Jinja pages (`02_report_wizard`, `03_settings`, `04_xero_publish`) went with them. The
browser journeys are the Next apps' suites; Minty's part of the job is the stack, the schema and
the seed. What is left in `Minty/e2e/` is described by `e2e/README.md`.

### Rehearsing it locally

The job is six steps you can run by hand, and a failure is far easier to read here:

```bash
cd docker/stack
cp .env.example .env            # set SECRET_KEY to anything
docker compose -f docker-compose.yml up -d --wait db

# the schema (what the job does; locally the harness function is right there)
python -c "import sys; sys.path.insert(0, 'tests'); import pg_harness; \
  pg_harness.build_schema('postgresql://minty_ref_user:minty_ref_pass@localhost:5433/minty_ref', \
  rename_to='pettycashv3')"

docker compose -f docker-compose.yml up -d --build --wait
E2E_MINTY_PASSWORD=whatever docker compose -f docker-compose.yml exec -T \
  -e E2E_MINTY_PASSWORD=whatever minty python scripts/e2e_seed.py --print

cd ../../../minty-web && npm run test:e2e
```

If it does not pass here it will not pass in CI.

## Why there is no `minty-e2e`

The modernisation plan called for a repo to hold "the cross-service journeys no app owns". They
are owned: `minty-web/e2e/04_live_api.spec.ts` starts a real trial through the subscription API
and asserts this app's `entity_function_map` gate opened; `minty-onboarding-web/e2e/walk.spec.ts`
finalizes an entity across four services.
What was missing was never a repo — it was something that stands the stack up and runs them, and
that is `stack-e2e.yml`. Unit tests and each app's Playwright suite stay in their own repo, where
they can gate their own pull request.
