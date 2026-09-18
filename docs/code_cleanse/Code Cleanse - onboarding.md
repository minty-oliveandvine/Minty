CODE CLEANSE - WORK DOCUMENT

# onboarding

Next.js 16 + TypeScript  -  branch Minty-Onboarding  -  ~9,800 LOC

49 tracked files  -  49 listed here  -  10 need work

Revision 5 - re-measured 8 September 2026, branch Minty-PettyCash at commit 68e8657

THIS DOCUMENT HAS BEEN CORRECTED. The previous revision covered 26 of 49 tracked files and omitted components/ and lib/ entirely - 17 files and 6,387 lines, including the two largest files in the repository. Its claim that the repo was 1,130 lines was wrong by a factor of roughly nine. The real work here is not the two auth pages; it is components/OnboardingSteps.jsx and components/OnboardingApp.jsx, which together are 3,917 lines and were never listed.

## Where the work is

| Area | Files | Need work | P1 | P2 | P3 | P4 |
| --- | --- | --- | --- | --- | --- | --- |
| components/ - NOT COVERED BY THE PREVIOUS REVISION | 11 | 4 |  | 2 | 2 |  |
| lib/ - NOT COVERED BY THE PREVIOUS REVISION | 6 | 1 |  |  | 1 |  |
| app/ | 6 | 3 |  | 1 | 2 |  |
| Root and config | 17 | 2 |  |  | 1 | 1 |
| public/ | 9 | 0 |  |  |  |  |
| Total | 49 | 10 | 0 | 3 | 6 | 1 |

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

### components/ - NOT COVERED BY THE PREVIOUS REVISION   4 of 11 files need work

The whole of the real code work in this repository is here, and none of it has ever been audited. OnboardingSteps.jsx and OnboardingApp.jsx are together 3,917 lines - both larger than any file the previous revision flagged anywhere in this repo. They are also .jsx rather than .tsx, so they are outside whatever type-checking the rest of the repo gets.

| Pri | File | What to do |
| --- | --- | --- |
| P2 | components/OnboardingApp.jsx | 1,802 lines, second largest, and also never previously listed. It carries entity_id end to end through the onboarding flow, so changes here touch every step. Split the state machine out from the rendering before anything else. |
| P2 | components/OnboardingSteps.jsx | 2,115 lines - the largest file in this repository, and it was never listed before this revision. It is also .jsx rather than .tsx, so it sits outside whatever type checking the rest of the repo gets. Extract one step at a time into its own component; each step is a natural, independently reviewable seam. |
| P3 | components/BuyNowSheet.jsx | 596 lines - larger than either auth page; 2 console.error at lines 61 and 143 |
| P3 | components/TermsModal.jsx | 418 lines - split candidate |

*The other 7 files in this area are clean - formatter pass only.*

### lib/ - NOT COVERED BY THE PREVIOUS REVISION   1 of 6 files need work

Small and clean, but it was never listed. lib/billing.js is the one that matters - it is the client for the buy-now flow and therefore the surface exposed to the billing-group cutover.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | lib/billing.js | 131 lines - the buy-now billing client; see the database section |

*The other 5 files in this area are clean - formatter pass only.*

### app/   3 of 6 files need work

Both auth pages are unchanged since the last revision. They are still worth extracting components from, but they are no longer the biggest thing in the repository - components/ is.

| Pri | File | What to do |
| --- | --- | --- |
| P2 | app/auth/page.tsx | 564 lines, unchanged since the first revision. Still worth extracting components from, but note it is no longer among the largest files in this repo - components/ holds two files three times its size. |
| P3 | app/auth/confirm/page.tsx | 509 lines - unchanged; extract components |
| P3 | app/globals.css | 1,839 lines - the largest stylesheet in any of the four repos |

*The other 3 files in this area are clean - formatter pass only.*

### Root and config   2 of 17 files need work

Add CI. There is still no .github/ directory, so nothing lints, builds or tests on push. At this size a single lint-and-build job is nearly the whole job. Note that the repo is now known to be ~9,800 lines, not ~1,100, so 'at this size' is a weaker argument than it was.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | docker/.env.example | exists here but not at the repo root - confirm which one the app reads |
| P4 | CODE_CLEANSE_NOTES.md | cross-check, then fold in or delete |

*The other 15 files in this area are clean - formatter pass only.*

## Method and totals

File lists from `git ls-files` in each working tree on 2 September 2026. Per-file codes from a single `ruff check` run over each Python repository with the rule set in the legend; the run reproduces the previous revision's counts exactly on blueprints/xero/services/publish.py, blueprints/entity/routes/settings.py and blueprints/report/routes/api.py, so the two revisions are directly comparable. Console counts, line counts and orphan checks were re-run, not carried over. TypeScript notes are from reference-graph sweeps and manual reading.

Minty 642 tracked files, billing-backend 109, billing-frontend 148, onboarding 49. Two repositories - billing-frontend and onboarding - still have no test files at all, and none of the four runs tests in CI.

*Generated from the Minty Stack Inventory. One document per repository; the other three cover billing-backend, billing-frontend, onboarding and Minty respectively.*
