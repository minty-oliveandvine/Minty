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

Override the base URL with `E2E_BASE_URL` (a deployed host works: the seed then needs the
deployment's database, so run it with the `.env` that points there).
`E2E_SUBSCRIPTIONS=0` says Flask runs with `SUBSCRIPTION_ENABLED=0` (subscriptions dark).

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

Since 2026-09-22 it also creates and RESETS a second company for minty-web's live subscription
journeys, `E2E Subscription Shop` (printed as `E2E_MINTY_SUBSCRIPTION_ENTITY`): both modules off
and no subscription rows, so a card-free trial can be started on a module it has never held on
every run. The Petty Cash shop keeps both modules ON for this suite and the sibling apps' - a
module already on is not trial-eligible, which is why the journeys need a company of their own.

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
| `04_xero_publish.spec.ts` | `E2E_XERO=1` only: the report 02 posted → Publish on its submitted page → `/api/report/<id>/publishing_status` reaches `xero_integrated_yes` → Republish offered. Real bank transactions, a transfer and the receipt land in the linked organisation |

Serial, one worker: every spec signs in as the same user and writes to the same entity.

## A shop connected to Xero (`E2E_XERO=1`)

Link the seeded entity to a Xero **Demo Company** by hand once (an admin of the entity connects
on the Xero page and runs the sync). The seed then leaves the mapping and the synced contacts
alone, `e2e/helpers.ts::fixtures()` switches the supplier / expense account / mapping names to
the organisation's real rows (`ABC Furniture`, `General Expenses`, …; override any of them
with `E2E_SUPPLIER_QUERY`, `E2E_SUPPLIER`, `E2E_EXPENSE_ACCOUNT_QUERY`, `E2E_EXPENSE_ACCOUNT`),
and `04_xero_publish` runs. Without the variable the placeholders the seed writes are used and
the publish spec skips.

## Findings the suite records

`test.fail()` marks a test that documents a defect in the current code: it must fail today and
starts passing — and then must lose the marker — when the defect is fixed.

- **F4** `templates/report/cash_count.html` `applyCalculatorTotal()` strips only `$` before
  parsing the calculator total; the page renders the currency *code* (`HKD`), so the Actual Cash
  Balance field shows `HKD0.00` after Apply. Display only — the posted counts and discrepancy come
  from the hidden fields. Fixed in phase C4.

## What this layer does not cover

Xero OAuth itself (the connection is made by hand; with `E2E_XERO=1` the publish uses it),
Stripe, email delivery, the Next.js apps (`onboarding/e2e`, `billing-frontend/e2e`) and the
Django services.
