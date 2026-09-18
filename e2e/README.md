# Minty browser tests

```bash
npm install                      # once; Playwright's Chromium is shared with onboarding/e2e
npm run test:e2e                 # against a Flask that is already running
```

A real browser against a **stack that is already up**. Nothing is started here (see
`playwright.config.ts` for why). Each spec skips with a reason when Flask is not reachable or
the seeded identity is not configured, so an unconfigured run reads as *not run here*, never as
*passed*.

## Why this suite exists

The pytest suite renders Jinja but runs no JavaScript. The report wizard is thousands of lines
of inline JS that reads the field names and JSON keys the schema redesign renames
(`docs/modernisation/modernisation_plan.md`, Part 1 phase C0.9). These specs are the only thing that runs it.

## What has to be up

| Service | Port | How |
|---|---|---|
| Flask (Minty) | 5001 | `.venv/Scripts/python.exe -m flask --app main.py run --port 5001` |
| PostgreSQL | 5432 | the database Flask's `LOCAL_DATABASE_URI` points at |

Override the base URL with `E2E_BASE_URL`.

## The seeded identity

The specs sign in through the real `/login` form as a user `scripts/e2e_seed.py` creates. Run the
seed **before every run** — it also wipes the seeded entity's reports so the wizard starts clean,
removes the user's terms consent so the terms modal is exercised, and resets the sales methods:

```bash
export E2E_MINTY_PASSWORD='<pick one; never commit it>'
.venv/Scripts/python.exe scripts/e2e_seed.py --print
# copy the export lines it prints:
export E2E_MINTY_USER=...   E2E_MINTY_ENTITY=...   E2E_MINTY_EMAIL=e2e@minty.test
npm run test:e2e
```

The seed goes through the app's own models, so it works against whichever schema the code
currently matches. It only ever touches the rows it created (`e2e@minty.test`,
`E2E Petty Cash Shop` and that entity's reports/settings) — safe against `minty_cleanse`.

To run the C0.9 **baseline** against the old-schema database while `.env` points elsewhere,
override the URIs for both the seed and Flask:

```bash
OLD=postgresql://postgres:***@localhost:5432/postgres
LOCAL_DATABASE_URI=$OLD RDS_DATABASE_URI=$OLD .venv/Scripts/python.exe scripts/e2e_seed.py
LOCAL_DATABASE_URI=$OLD RDS_DATABASE_URI=$OLD SUBSCRIPTION_SCHEDULER_ENABLED=0 \
  .venv/Scripts/python.exe -m flask --app main.py run --port 5001
```

## The specs

| File | Journeys |
|---|---|
| `01_login.spec.ts` | login form, wrong password, first sign-in shows the terms modal (scroll-to-end, tick, accept), the company dashboard |
| `02_report_wizard.spec.ts` | opening (live opening balance) → sales (three live sub-totals) → expenses (receipt upload, supplier and account pickers, running total) → deposit (cash on hand) → cash count (calculator modal, hidden fields, zero discrepancy) → ending (summary figures) → submitted → history row and the posted report's summary |
| `03_settings.spec.ts` | petty-cash account mapping, the sales-methods editor (add via the catalogue picker → visible on the sales form), users, the Xero page and an entity rename round-trip, the module page, the CSV export's movement lines |

Serial, one worker: every spec signs in as the same user and writes to the same entity.

## Findings the suite records

`test.fail()` marks a test that documents a defect in the current code: it must fail today and
starts passing — and then must lose the marker — when the defect is fixed.

- **F4** `templates/report/cash_count.html` `applyCalculatorTotal()` strips only `$` before
  parsing the calculator total; the page renders the currency *code* (`HKD`), so the Actual Cash
  Balance field shows `HKD0.00` after Apply. Display only — the posted counts and discrepancy come
  from the hidden fields. Fixed in phase C4.

## What this layer does not cover

Xero OAuth (no real connection is made; the connect page is only rendered), Stripe, email
delivery, the Next.js apps (`onboarding/e2e`, `billing-frontend/e2e`) and the Django services.
