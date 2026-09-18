CODE CLEANSE - WORK DOCUMENT

# billing-frontend

Next.js 16 + TypeScript  -  branch Minty-BillingFrontend  -  24,491 LOC

148 tracked files  -  148 listed here  -  21 need work

Revision 5 - re-measured 8 September 2026, branch Minty-PettyCash at commit 68e8657

Structurally still the cleanest of the four, and structurally unchanged - the recent work (pagination, totals banner, entity billing dialog, incoming transfers) all landed in files that already existed. But no remediation has happened either: all five oversized files are still oversized, the two console.log calls are still on the same lines, and .env.example still does not exist for the twelve variables the code reads.

## Where the work is

| Area | Files | Need work | P1 | P2 | P3 | P4 |
| --- | --- | --- | --- | --- | --- | --- |
| app/ - routes | 19 | 2 |  |  | 2 |  |
| components/ - top level | 10 | 1 |  |  | 1 |  |
| components/layout/ | 5 | 0 |  |  |  |  |
| components/payment-request/ | 30 | 4 |  | 1 | 3 |  |
| components/profile/ | 16 | 2 |  |  | 2 |  |
| components/settings/ | 4 | 0 |  |  |  |  |
| lib/ | 28 | 4 |  | 1 | 2 | 1 |
| Root and config | 14 | 4 |  |  | 3 | 1 |
| public/ | 22 | 4 |  |  | 4 |  |
| Total | 148 | 21 | 0 | 2 | 17 | 2 |

## How to read the priority

| P1 | Correctness / exposure | Can produce a wrong answer, leak data, or fail silently in production. Do these first, one at a time, each with its own commit. |
| --- | --- | --- |
| P2 | Structural | Oversized or complex. Needs a plan and characterisation tests before anyone edits it. Do not fold these into a sweep. |
| P3 | Mechanical sweep | The same edit repeated. Safe, batchable, no design decisions. Best done per rule across the whole repo rather than per file. |
| P4 | Delete / untrack | Dead files and committed artefacts. Zero risk and immediate - do these before the sweep so their findings stop being counted. |

## What this covers

- Excluded everywhere: .venv/, node_modules/, .git/, __pycache__/, .next/, .pytest_cache/, lock files, and generated files such as next-env.d.ts.
- Tracked files only. Untracked working-tree files are out of scope for these listings - the one exception is noted in the database section, where an uncommitted script is the pending cutover step and has to be named.

## What needs work

Only the files that need a human are listed; every other file needs the formatter pass and nothing more. Rows are ordered by priority, not alphabetically - work down the table. Counts in brackets are occurrences of that rule in that file.

### app/ - routes   2 of 19 files need work

Two console.log calls to remove, one of which prints a user profile object to the browser console. Both are on the same lines as the last revision. Everything else is clean.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | app/module-selection/page.tsx | console.log at line 63 (unchanged) |
| P3 | app/page.tsx | One console.log at line 55 printing a whole user profile object to the browser console. Do this one first among the frontend P3s: it is a one-line deletion and it is user data in a place anyone can read. |

*The other 17 files in this area are clean - formatter pass only.*

### components/ - top level   1 of 10 files need work

Six of the repository's nine console.error calls are in one file. They are real error handlers rather than debug leftovers, so route them through a logger rather than deleting them.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | components/PaymentRequestModal.tsx | Six console.error calls (lines 430, 440, 446, 514, 524, 531). These are real error handlers, not debug leftovers - route them through a logger rather than deleting them, so the failures stay visible. |

*The other 9 files in this area are clean - formatter pass only.*

### components/payment-request/   4 of 30 files need work

Nothing to delete - every component is imported. Three files are large enough to be worth splitting and none of them has been touched since the last revision; PaymentRequestTable.tsx grew slightly. They remain the natural first targets for the tests this repo does not have.

| Pri | File | What to do |
| --- | --- | --- |
| P2 | components/payment-request/PaymentRequestDetailBody.tsx | 1,530 lines - the largest file in the repo and unchanged since the first revision. Extract the detail sections into their own components; it has no tests, so do it in small reviewable steps. |
| P3 | components/payment-request/BankSlipDetailsModal.tsx | 984 lines - unchanged; split |
| P3 | components/payment-request/PaymentRequestTable.tsx | 1,240 lines - grew 4 lines since the last revision; split |
| P3 | components/payment-request/PaymentRequestView.tsx | 1 console.error, line 578 |

*The other 26 files in this area are clean - formatter pass only.*

### components/profile/   2 of 16 files need work

One file over 950 lines, unchanged since the last revision. It is also the screen most exposed to the billing-group cutover - see the database section.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | components/profile/AddPaymentMethodModal.tsx | 2 console.error - lines 68, 239 (Stripe.js load failures; duplicated verbatim in the onboarding repo) |
| P3 | components/profile/PaymentMethodsPanel.tsx | 969 lines - unchanged; split. Renders payer state that is mid-cutover |

*The other 14 files in this area are clean - formatter pass only.*

### lib/   4 of 28 files need work

mintyEnv.ts and mintyUrls.ts are where the seven hardcoded hosts belong. api.ts is unchanged at 1,044 lines and remains the other split candidate and the highest-value place for a first test, since every screen goes through it.

| Pri | File | What to do |
| --- | --- | --- |
| P2 | lib/api.ts | 1,044 lines, unchanged since the first revision, and every screen in the app goes through it. It is also the primary mirror of the database schema in this repo - its types restate the bill, payment, attachment and audit columns one for one. Highest-value place for the first test in this repository. Split by resource. |
| P3 | lib/mintyEnv.ts | Together with mintyUrls.ts this is where the seven hardcoded hosts belong. Move them here and read from env, so a environment change is configuration rather than a code change. |
| P3 | lib/mintyUrls.ts | same - hardcoded hosts belong in env |
| P4 | lib/subscriptionNotice.ts | 1 console.warn, line 62 - a deliberate tagged logger; route it, do not delete it |

*The other 24 files in this area are clean - formatter pass only.*

### Root and config   4 of 14 files need work

Write .env.example - still none exists, and the code reads 12 variables. Then check the two CI workflows: they fire on different branch names in the same repository, so one may never run. This is the only one of the four repos with any CI at all.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | .github/workflows/clickup-notif.yml | fires on PRESTAGING-PETTYCASH |
| P3 | .github/workflows/vercel-deploy.yml | fires on prestaging - confirm both branches exist |
| P3 | package.json | lint script exists but nothing enforces it; no format script |
| P4 | CODE_CLEANSE_NOTES.md | cross-check, then fold in or delete |

*The other 10 files in this area are clean - formatter pass only.*

### public/   4 of 22 assets need work

Still not audited for orphans. Next.js resolves public/ by URL string, so a sweep has to match filenames across app/ and components/. Four look like untouched Next.js starter assets. The count is 22, not the 20 previously recorded.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | public/file.svg | Next.js starter asset - likely unused |
| P3 | public/globe.svg | Next.js starter asset - likely unused |
| P3 | public/next.svg | Next.js starter asset - likely unused |
| P3 | public/window.svg | Next.js starter asset - likely unused |

*The other 18 files in this area are clean - formatter pass only.*

## Method and totals

File lists from `git ls-files` in each working tree on 2 September 2026. Per-file codes from a single `ruff check` run over each Python repository with the rule set in the legend; the run reproduces the previous revision's counts exactly on blueprints/xero/services/publish.py, blueprints/entity/routes/settings.py and blueprints/report/routes/api.py, so the two revisions are directly comparable. Console counts, line counts and orphan checks were re-run, not carried over. TypeScript notes are from reference-graph sweeps and manual reading.

Minty 642 tracked files, billing-backend 109, billing-frontend 148, onboarding 49. Two repositories - billing-frontend and onboarding - still have no test files at all, and none of the four runs tests in CI.

*Generated from the Minty Stack Inventory. One document per repository; the other three cover billing-backend, billing-frontend, onboarding and Minty respectively.*
