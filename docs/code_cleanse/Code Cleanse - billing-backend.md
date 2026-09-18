CODE CLEANSE - WORK DOCUMENT

# billing-backend

Django 5 + django-ninja  -  branch Minty-BillingBackend  -  20,818 LOC

110 tracked files  -  107 listed here  -  29 need work

Revision 5 - re-measured 8 September 2026, branch Minty-PettyCash at commit 68e8657

Unchanged since the last revision. Every lint count re-measures identically - B904 41, DJ001 14, TRY400 16, BLE001 16, PLR2004 19 - so nothing here has been fixed and nothing has regressed. It remains the B904 repository, and the only one of the four where a test suite already exists without being wired to CI.

## Where the work is

| Area | Files | Need work | P1 | P2 | P3 | P4 |
| --- | --- | --- | --- | --- | --- | --- |
| bills/ - the billing app | 23 | 15 | 2 | 4 | 9 |  |
| bills/migrations/ - out of lint scope | 20 | 1 |  |  | 1 |  |
| bills/tests/ | 29 | 1 |  |  | 1 |  |
| config/ | 5 | 1 |  |  | 1 |  |
| core/ | 13 | 3 | 1 |  | 2 |  |
| shared_models/ | 3 | 1 |  |  | 1 |  |
| Root and support | 14 | 7 |  |  | 4 | 3 |
| Total | 107 | 29 | 3 | 4 | 19 | 3 |

## How to read the priority

| P1 | Correctness / exposure | Can produce a wrong answer, leak data, or fail silently in production. Do these first, one at a time, each with its own commit. |
| --- | --- | --- |
| P2 | Structural | Oversized or complex. Needs a plan and characterisation tests before anyone edits it. Do not fold these into a sweep. |
| P3 | Mechanical sweep | The same edit repeated. Safe, batchable, no design decisions. Best done per rule across the whole repo rather than per file. |
| P4 | Delete / untrack | Dead files and committed artefacts. Zero risk and immediate - do these before the sweep so their findings stop being counted. |

## Reading the annotations

| BLE001 | blind except Exception - narrow it, or log a reason before swallowing |
| --- | --- |
| C901 / PLR0912 / PLR0915 | function too complex - guard clauses, early returns, or split it |
| PLR2004 | magic number - name it, or use http.HTTPStatus |
| S608 | string-built SQL - bind parameters if any input comes from a request |
| S105 / S106 | hardcoded secret - move it to .env |
| T201 | print() - convert to logger.debug |
| ERA001 | commented-out code - delete it, git is the archive |
| B904 | raise without from - add 'from exc' so the cause survives |
| TRY400 | logger.error inside except - use logger.exception to keep the traceback |
| DJ001 | nullable Django string field - use blank=True without null=True |

## What this covers

- Excluded everywhere: .venv/, node_modules/, .git/, __pycache__/, .next/, .pytest_cache/, lock files, and generated files such as next-env.d.ts.
- Tracked files only. Untracked working-tree files are out of scope for these listings - the one exception is noted in the database section, where an uncommitted script is the pending cutover step and has to be named.
- Migrations are listed but out of scope for the lint pass - 63 revisions in Minty, 19 in billing-backend. They are historical records of schema changes that have already run. What they imply for the code is covered in the database section instead.

## What needs work

Only the files that need a human are listed; every other file needs the formatter pass and nothing more. Rows are ordered by priority, not alphabetically - work down the table. Counts in brackets are occurrences of that rule in that file.

### bills/ - the billing app   15 of 23 files, excluding migrations and tests need work

41 B904 violations sit here - raise inside an except without 'from exc', which discards the original traceback. Mechanical to fix and still the highest-value change in this repo. TRY400 is its sibling: logger.error where logger.exception would keep the stack.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P1 | bills/api_config.py | B904(15) | Two raw SELECTs on user_entity and entities with bare table names - qualify them. Separately, this file exposes UNGUARDED POST/PUT/DELETE on entity_function_map, which Minty treats as a projection of entity_module_subscription and reconciles daily in blueprints/subscription/services/access_sweep.py: a write here can grant module access that Minty then silently revokes. Guard the router or stop writing that table. The 15 B904s in this file are P3 and unrelated - do them separately. |
| P1 | bills/api_profile.py |  | Runs raw SQL against four tables that MINTY owns - user_entity, entity_module_subscription, entities, and `UPDATE "user"` - all with bare table names. It works only because config/settings.py:74 sets search_path=pettycashv2,public. A pooled or replaced connection that loses that setting hits the wrong schema or errors at runtime, with no import failure and no migration to catch it. Qualify every table explicitly as pettycashv2.x. See the database document. |
| P2 | bills/services/contact_service.py | B904(1) C901(1) PLR0912(1) PLR0915(1) PLR2004(4) | Writes to xero_contact_sync - another `managed = False` mirror - via objects.create and row.save(). Same decision as profile_service.py: the model says read-only, the code writes. The B904 and complexity findings here are P3 and separate. |
| P2 | bills/services/file_downsize.py | BLE001(4) C901(2) PLR0912(1) PLR2004(1) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 2 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. Name 1 magic numbers, or use http.HTTPStatus for status codes. |
| P2 | bills/services/profile_service.py | B904(1) TRY400(1) | Calls user.save() on the User model, which is declared `managed = False` and documented as a 'read-only mirror of pettycashv2.user managed by the Flask app'. The docstring and the behaviour disagree, across a repository boundary, on a table another application owns. Decide which is true and make them agree - either correct the docstring and own the write, or move the write behind a Minty endpoint. |
| P2 | bills/services/xero_publish_service.py | B904(7) BLE001(3) C901(1) ERA001(1) PLR0915(2) PLR2004(2) S608(1) TRY400(5) | 1,180 LOC; the only commented-out code in the repo, line 38 |
| P3 | bills/api.py | B904(4) BLE001(4) PLR2004(1) TRY400(2) | Add `from exc` to 4 raises inside except, so the original traceback survives. Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Name 1 magic numbers, or use http.HTTPStatus for status codes. Swap logger.error for logger.exception in 2 except blocks to keep the stack. |
| P3 | bills/api_audit.py | B904(1) | Add `from exc` to 1 raises inside except, so the original traceback survives. |
| P3 | bills/api_payments.py | B904(4) BLE001(2) TRY400(1) | Add `from exc` to 4 raises inside except, so the original traceback survives. Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Swap logger.error for logger.exception in 1 except blocks to keep the stack. |
| P3 | bills/api_xero.py | B904(2) | Add `from exc` to 2 raises inside except, so the original traceback survives. |
| P3 | bills/api_xero_actions.py | B904(2) | Add `from exc` to 2 raises inside except, so the original traceback survives. |
| P3 | bills/services/attachment_service.py | B904(4) BLE001(1) TRY400(2) | Add `from exc` to 4 raises inside except, so the original traceback survives. Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Swap logger.error for logger.exception in 2 except blocks to keep the stack. |
| P3 | bills/services/bill_reference_generator.py | PLR2004(3) | Name 3 magic numbers, or use http.HTTPStatus for status codes. |
| P3 | bills/services/flask_billing_sync.py | PLR2004(3) TRY400(2) | Name 3 magic numbers, or use http.HTTPStatus for status codes. Swap logger.error for logger.exception in 2 except blocks to keep the stack. |
| P3 | bills/services/xero_token_service.py | BLE001(1) PLR2004(3) S105(1) TRY400(3) | builds a Xero auth header - check it is never logged |

*The other 8 files in this area are clean - formatter pass only.*

### bills/migrations/ - out of lint scope   1 of 20 files need work

Nothing to lint. Head is 0019_align_currency_fk_types and the chain is linear. The one thing to know about it is a cross-repo ordering constraint - see the database section.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | bills/migrations/0019_align_currency_fk_types.py | raises unless Minty's c8e0a2b4d6f8 ran first - deploy Minty before this repo |

*The other 19 files in this area are clean - formatter pass only.*

### bills/tests/   1 of 28 files need work

Leave them alone and get them running in CI. pytest-cov is already declared, so a coverage baseline is one command away. This is still the only repo of the four where the safety net exists - and it is still not wired to anything.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | bills/tests/test_depreciatn_account.py | filename typo for depreciation - rename with the test |

*The other 28 files in this area are clean - formatter pass only.*

### config/   1 of 5 files need work

Framework wiring, all string-referenced from settings.py. Nothing to remove.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | config/settings_test.py | S105(1) | a test fixture, not a secret - verify and leave |

*The other 4 files in this area are clean - formatter pass only.*

### core/   3 of 13 files need work

generate_token.py is the one to question: it is a management command, so no code references it and nobody could say whether it is still run. It now also trips S106.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P1 | core/auth.py | C901(1) | Three raw SELECTs on user_entity with a bare table name, on the authorisation path - so a search_path change fails OPEN or CLOSED on permission checks. Qualify them as pettycashv2.user_entity. The C901 is secondary; do the qualification as its own commit. |
| P3 | core/api_session.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | core/management/commands/generate_token.py | S106(1) | S106 hardcoded password argument, plus a placeholder password already noted. Nothing references this management command, so nobody can say whether it is still run - establish that first. If it is dead, deleting it is simpler than fixing it. |

*The other 10 files in this area are clean - formatter pass only.*

### shared_models/   1 of 3 files need work

14 nullable string columns. Django convention is blank=True without null=True, so there is one representation of empty rather than two. Changing it generates a migration - raise it first. This file is also the mirror of Minty's tables; see the database section for the column it is missing.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | shared_models/models.py | DJ001(14) | 14 nullable string columns: use blank=True without null=True so empty has one representation. This generates a migration - raise it before doing it. This file is also the managed=False mirror of six Minty-owned tables and is missing user.current_entity_id; see the database document. |

*The other 2 files in this area are clean - formatter pass only.*

### Root and support   7 of 14 files need work

Add the CI that does not exist - there is still no .github/ directory - commit a ruff config, fill the three missing environment variables, and untrack two files that should never have been committed.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | .env.example |  | missing CORS_ALLOWED_ORIGINS, XERO_CLIENT_ID, XERO_CLIENT_SECRET |
| P3 | docs/generate_db_design_pdf.py | PLR0915(1) PLR2004(2) T201(1) | Too many statements in 1 functions - extract named helpers. Name 2 magic numbers, or use http.HTTPStatus for status codes. Convert 1 print() to logger.debug. |
| P3 | pytest.ini |  | already configured, with a documented reason for --no-migrations |
| P3 | requirements.txt |  | all 11 runtime deps verified in use - nothing to remove |
| P4 | .DS_Store |  | DELETE and untrack - a macOS artefact committed to the repository. Add it to .gitignore in the same commit. |
| P4 | .claude/settings.local.json |  | DELETE and untrack - machine-local editor configuration, committed by accident. It is '.local' by naming convention and should never have been tracked. |
| P4 | CODE_CLEANSE_NOTES.md |  | cross-check, then fold in or delete |

*The other 7 files in this area are clean - formatter pass only.*

## Method and totals

File lists from `git ls-files` in each working tree on 2 September 2026. Per-file codes from a single `ruff check` run over each Python repository with the rule set in the legend; the run reproduces the previous revision's counts exactly on blueprints/xero/services/publish.py, blueprints/entity/routes/settings.py and blueprints/report/routes/api.py, so the two revisions are directly comparable. Console counts, line counts and orphan checks were re-run, not carried over. TypeScript notes are from reference-graph sweeps and manual reading.

Minty 642 tracked files, billing-backend 109, billing-frontend 148, onboarding 49. Two repositories - billing-frontend and onboarding - still have no test files at all, and none of the four runs tests in CI.

*Generated from the Minty Stack Inventory. One document per repository; the other three cover billing-backend, billing-frontend, onboarding and Minty respectively.*
