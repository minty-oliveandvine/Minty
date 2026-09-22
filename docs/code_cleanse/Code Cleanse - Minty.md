CODE CLEANSE - WORK DOCUMENT

# Minty

Flask + Jinja  -  branch Minty-PettyCash  -  110824 LOC (py/html/js/css, excl. migrations and tests)

654 tracked files  -  513 listed here  -  164 need work

Revision 5 - re-measured 8 September 2026, branch Minty-PettyCash at commit 68e8657

Still three quarters of the whole cleanse, but the shape has shifted. The subscription blueprint has grown from 36 files to 42 as logic was pulled out of blueprints/entity/services/modules.py, and a decomposition pass has now cleared EVERY complexity finding in that blueprint except one. What is left there is a single rule repeated 71 times - blind exception handlers - which makes it a mechanical sweep rather than a refactor. The unfinished business is size: blueprints/subscription/services/checkout.py is 3,127 lines and is now the heaviest file in the codebase, ahead of blueprints/xero/services/publish.py. Fix blueprints/report/routes/__init__.py first - it still swallows route-module import failures.

## Where the work is

| Area | Files | Need work | P1 | P2 | P3 | P4 |
| --- | --- | --- | --- | --- | --- | --- |
| Root | 5 | 0 |  |  |  |  |
| blueprints/auth/ | 23 | 7 |  |  | 6 | 1 |
| blueprints/entity/ | 34 | 15 |  | 9 | 5 | 1 |
| blueprints/report/ | 38 | 26 | 2 | 16 | 6 | 2 |
| blueprints/subscription/ | 42 | 23 |  | 5 | 18 |  |
| blueprints/xero/ | 18 | 9 |  | 2 | 6 | 1 |
| blueprints/user_management/ | 18 | 3 |  |  | 2 | 1 |
| blueprints/legal/ | 11 | 3 |  |  | 3 |  |
| blueprints/invitation/ | 8 | 1 |  |  | 1 |  |
| blueprints/shared/ | 3 | 0 |  |  |  |  |
| services/ | 24 | 8 |  |  | 7 | 1 |
| pettycash/ | 5 | 2 |  | 1 | 1 |  |
| models/, utils/, legal/, cli/ | 17 | 5 | 1 |  | 4 |  |
| templates/ | 84 | 21 |  |  | 17 | 4 |
| static/ | 57 | 26 |  |  | 1 | 25 |
| tests/ | 99 | 3 |  |  | 2 | 1 |
| Root config and docs | 27 | 12 |  |  | 6 | 6 |
| Total | 513 | 164 | 3 | 33 | 85 | 43 |

## How to read the priority

| P1 | Correctness / exposure | Can produce a wrong answer, leak data, or fail silently in production. Do these first, one at a time, each with its own commit. |
| --- | --- | --- |
| P2 | Structural | Oversized or complex. Needs a plan and characterisation tests before anyone edits it. Do not fold these into a sweep. |
| P3 | Mechanical sweep | The same edit repeated. Safe, batchable, no design decisions. Best done per rule across the whole repo rather than per file. |
| P4 | Delete / untrack | Dead files and committed artefacts. Zero risk and immediate - do these before the sweep so their findings stop being counted. |

## Reading the annotations

| BLE001 | blind except Exception - narrow it, or log a reason before swallowing |
| --- | --- |
| S110 | try/except/pass - silent failure; give it a reason or let it raise |
| C901 / PLR0912 / PLR0915 | function too complex - guard clauses, early returns, or split it |
| PLR2004 | magic number - name it, or use http.HTTPStatus |
| S113 | requests call with no timeout - add timeout=10, the convention already exists |
| S608 | string-built SQL - bind parameters if any input comes from a request |
| S105 / S106 | hardcoded secret - move it to .env |
| T201 | print() - convert to logger.debug |
| S101 | assert in a route - it vanishes under python -O; raise instead |
| ERA001 | commented-out code - delete it, git is the archive |
| F401 / F841 | unused import or dead local - auto-fixable, except in models/db.py |
| E712 | == True - inside a SQLAlchemy filter this builds SQL; use .is_(True) |
| B904 | raise without from - add 'from exc' so the cause survives |
| TRY400 | logger.error inside except - use logger.exception to keep the traceback |
| DTZ | naive datetime - now()/utcnow() with no tzinfo. In a date-boundary system this is an off-by-one-day bug, not a style issue |

## What this covers

- Excluded everywhere: .venv/, node_modules/, .git/, __pycache__/, .next/, .pytest_cache/, lock files, and generated files such as next-env.d.ts.
- Tracked files only. Untracked working-tree files are out of scope for these listings - the one exception is noted in the database section, where an uncommitted script is the pending cutover step and has to be named.
- Migrations are listed but out of scope for the lint pass - 63 revisions in Minty, 19 in billing-backend. They are historical records of schema changes that have already run. What they imply for the code is covered in the database section instead.
- Minty's .archived/ is not listed. Those tracked files are slated for untracking rather than cleansing, and are enumerated in the runbook instead.

## What needs work

Only the files that need a human are listed; every other file needs the formatter pass and nothing more. Rows are ordered by priority, not alphabetically - work down the table. Counts in brackets are occurrences of that rule in that file.

### blueprints/auth/   7 of 23 files need work

Unchanged since the last revision. forms.py still holds ten consecutive commented-out form fields - read them before deleting, they may be a deferred registration change. password_reset.py still has two print() calls: read those first, a printed reset token is a credential leak, not a style issue.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | blueprints/auth/forms.py | ERA001(10) | Delete 10 blocks of commented-out code; git is the archive. |
| P3 | blueprints/auth/routes/dashboard.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/auth/routes/email_auth.py | BLE001(1) C901(1) PLR0912(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. |
| P3 | blueprints/auth/routes/password_reset.py | BLE001(2) DTZ(2) T201(2) | CORRECTION: earlier revisions of this document called these prints a credential leak. They are not. Both print exception text on a failure path - `print(f"Error during password reset: {e}")` - not a token. Still worth fixing: an exception message can carry DB error detail, and print() goes to stdout unstructured. Convert both to logger.exception, which also clears the 2 blind catches in the same edit. |
| P3 | blueprints/auth/routes/tokens.py | BLE001(3) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/auth/services/email_auth.py | BLE001(1) DTZ(5) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. |
| P4 | blueprints/auth/schemas.py |  | DELETE - docstring only, zero importers (re-verified) |

*The other 16 files in this area are clean - formatter pass only.*

### blueprints/entity/   15 of 34 files need work

Now the third-heaviest area rather than the second - not because it improved, but because subscription grew. routes/settings.py is unchanged and still holds the worst function in the codebase at line 237 plus 30 blind exception handlers, in a 2,523-line file. services/modules.py has dropped to BLE001(2) only because its subscription logic moved out; about 101 of its 574 lines are now re-export shims, so grep lands on a wrapper rather than the code.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P2 | blueprints/entity/routes/create.py | C901(1) PLR0912(1) PLR0915(1) PLR2004(5) | 1,619 lines. The 5 magic numbers are trivial; the complexity is not. Extract the validation and the entity-provisioning steps into named helpers before the sweep. |
| P2 | blueprints/entity/routes/list.py | BLE001(2) C901(1) DTZ(3) ERA001(1) PLR0912(1) PLR0915(1) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 3 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Delete 1 blocks of commented-out code; git is the archive. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. |
| P2 | blueprints/entity/routes/settings.py | BLE001(30) C901(3) PLR0912(2) PLR0915(2) PLR2004(4) S113(3) | 2,523 lines, and it holds the worst function in the codebase: 46 branches and 168 statements at line 237. No direct test coverage. This is not a sweep target - characterisation tests first, then extract the per-section handlers one at a time. The 30 blind catches come last, once the function is small enough to see. |
| P2 | blueprints/entity/services/modules.py | BLE001(2) | 574 lines, of which roughly 101 (18%) are re-export shims: 12 lazy wrapper functions plus a module-level re-export forwarding to blueprints/subscription/services/. A grep for any moved function lands HERE, on the wrapper, not on the code. Before editing, check whether the function you want actually lives in the subscription blueprint. The 2 blind catches are in the real entity-side code. |
| P2 | blueprints/entity/services/onboarding_account_codes.py | C901(2) PLR0912(1) | Reduce complexity in 2 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. |
| P2 | blueprints/entity/services/onboarding_xero.py | C901(1) PLR0912(1) PLR0915(1) PLR2004(1) | Reduce complexity in 1 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Name 1 magic numbers, or use http.HTTPStatus for status codes. |
| P2 | blueprints/entity/services/payment_methods.py | C901(2) DTZ(8) E712(1) | Reduce complexity in 2 functions: guard clauses and early returns first, then split. 8 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Replace `== True` with `.is_(True)` - inside a SQLAlchemy filter this builds SQL. |
| P2 | blueprints/entity/services/settings.py | BLE001(22) C901(8) PLR0912(3) PLR0915(2) S608(5) | 1,561 lines, 8 complex functions, and 5 string-built SQL statements. The SQL is correct - it qualifies the table through a _TBL constant and binds its inputs - so do not rewrite it. Add noqa to the S608s, then attack the 8 functions with tests in place. |
| P2 | blueprints/entity/services/xero_account_mapping_post.py | BLE001(4) C901(1) PLR0912(1) PLR0915(1) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. |
| P3 | blueprints/entity/routes/billing_sync.py | BLE001(3) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/entity/routes/modules.py | BLE001(1) TRY400(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Swap logger.error for logger.exception in 1 except blocks to keep the stack. |
| P3 | blueprints/entity/services/onboarding_bill_codes.py | S608(3) | The 3 S608s are false positives for injection: the only interpolation is _TBL, a module-level constant holding 'pettycashv2.entity_bill_account_xero', and all user values are bound parameters. Verify once, add noqa with that reason, move on. Note this table is the ONLY one in the repo with no SQLAlchemy model, so nothing type-checks these strings - see the database document. |
| P3 | blueprints/entity/services/onboarding_state.py | PLR2004(2) | Name 2 magic numbers, or use http.HTTPStatus for status codes. |
| P3 | blueprints/entity/services/shared.py | BLE001(1) PLR2004(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Name 1 magic numbers, or use http.HTTPStatus for status codes. |
| P4 | blueprints/entity/schemas.py |  | DELETE - docstring only, zero importers (re-verified) |

*The other 19 files in this area are clean - formatter pass only.*

### blueprints/report/   26 of 36 files need work

Unchanged since the last revision. routes/api.py is still the second-worst file by lint count: 28 blind catches, 7 complex functions, 4 silent try/except/pass across 1,960 lines. But routes/__init__.py still comes first - it swallows route-module import failures, which is how export_screenshot went missing from the running app without anyone noticing.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P1 | blueprints/report/routes/__init__.py | BLE001(1) | FIX FIRST. It imports all 16 route modules in a loop and swallows any failure into logger.debug - the lowest level, invisible in production. This is not hypothetical: it is firing right now, and export_screenshot is currently NOT REGISTERED in the running app (see below). Re-raise in development and use logger.exception in production, so a broken route module fails loudly at boot instead of a page quietly 404ing. |
| P1 | blueprints/report/routes/export_screenshot.py | BLE001(5) C901(1) DTZ(1) PLR0912(1) PLR0915(2) | This module fails to import TODAY: it pulls in docxtpl/user_agents, which need pkg_resources, and pkg_resources is not installed. The loop above catches it, so both its routes are absent from the running app and every request to them 404s. Decide explicitly: either add setuptools and fix the import, or delete the module and its routes. It cannot stay as it is - silently dead. |
| P2 | blueprints/report/routes/api.py | BLE001(28) C901(7) DTZ(7) PLR0912(6) PLR0915(4) S110(4) S113(1) | 1,960 lines and the second-worst file by lint count. Its 4 S110 silent passes are all the same defensible `rollback() except: pass` guard inside an error handler - verify once and noqa them, do not 'fix' them. The real work is the 7 complex functions; split by route group, with tests first. |
| P2 | blueprints/report/routes/cash_count.py | BLE001(1) C901(1) DTZ(5) PLR0912(1) PLR0915(1) PLR2004(2) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Name 2 magic numbers, or use http.HTTPStatus for status codes. |
| P2 | blueprints/report/routes/create.py | BLE001(1) C901(1) DTZ(1) PLR0912(1) PLR0915(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 1 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. |
| P2 | blueprints/report/routes/deposit.py | BLE001(1) C901(1) DTZ(5) PLR0912(1) PLR0915(1) T201(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Convert 1 print() to logger.debug. |
| P2 | blueprints/report/routes/download.py | BLE001(4) C901(3) DTZ(5) PLR0912(1) PLR0915(1) T201(2) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 3 functions: guard clauses and early returns first, then split. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Convert 2 print() to logger.debug. |
| P2 | blueprints/report/routes/expense.py | BLE001(2) C901(1) DTZ(8) F401(1) PLR0912(1) PLR0915(1) S105(1) T201(2) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 8 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Remove 1 unused import - auto-fixable. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Move the hardcoded secret to .env, or confirm it is a test fixture and add noqa. Convert 2 print() to logger.debug. |
| P2 | blueprints/report/routes/expense_ai.py | C901(1) PLR0912(1) | NEW - the route layer for the AI expense feature. One complex function with too many branches; small enough to fix with guard clauses before the feature is switched on. |
| P2 | blueprints/report/routes/opening.py | BLE001(1) B904(1) C901(1) DTZ(5) F401(1) PLR0912(1) PLR0915(1) T201(8) | 1,254 lines with 8 print() calls - the largest T201 cluster in the repo. Convert the prints to logger.debug as a quick standalone win, then treat the complexity separately. |
| P2 | blueprints/report/routes/report_detail.py | BLE001(9) C901(3) DTZ(2) PLR0912(2) PLR0915(2) T201(3) | Narrow 9 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 3 functions: guard clauses and early returns first, then split. 2 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 2 functions - collapse with early returns. Too many statements in 2 functions - extract named helpers. Convert 3 print() to logger.debug. |
| P2 | blueprints/report/routes/sales.py | BLE001(4) C901(1) DTZ(15) E712(1) F401(1) PLR0912(1) PLR0915(1) S101(3) T201(4) | 15 naive datetime calls - the largest DTZ cluster in the codebase - in the sales entry path of a DAILY cash report. A naive now() near midnight files a report against the wrong day, and no test catches it because the test clock is naive too. Fix the timezone handling here before anything else in this file. The 3 asserts (S101) come second: they vanish under python -O, so a guard you think you have is absent in production. |
| P2 | blueprints/report/routes/submitted.py | BLE001(3) C901(1) PLR0912(1) PLR0915(1) S105(1) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Move the hardcoded secret to .env, or confirm it is a test fixture and add noqa. |
| P2 | blueprints/report/services/ending.py | BLE001(5) C901(2) DTZ(8) PLR0912(2) PLR0915(1) | 1,884 lines with 2 complex functions. Large but not badly rule-flagged - the size is the problem. Extract the calculation helpers before touching anything else. |
| P2 | blueprints/report/services/expense_ai.py | BLE001(7) C901(1) F401(1) PLR2004(8) | NEW since the last revision - 1,049 lines of AI receipt reading, landed with the feature flagged off by default. It arrives already among the larger files in the repo and carries 8 magic numbers and 7 blind catches. Because it is new and off by default, this is the cheapest moment to shape it: name the constants and narrow the catches now, before anything depends on its internals. Note tests/test_expense_ai.py (667 lines) already exists, so unlike most P2 work here you have a safety net. |
| P2 | blueprints/report/services/history_query.py | C901(1) DTZ(2) PLR0912(1) PLR0915(1) | Reduce complexity in 1 functions: guard clauses and early returns first, then split. 2 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. |
| P2 | blueprints/report/services/report_detail.py | BLE001(4) C901(3) DTZ(5) PLR0912(1) PLR0915(1) T201(2) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 3 functions: guard clauses and early returns first, then split. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 1 functions - collapse with early returns. Too many statements in 1 functions - extract named helpers. Convert 2 print() to logger.debug. |
| P2 | blueprints/report/services/shared.py | BLE001(4) C901(2) DTZ(4) PLR0912(2) TRY400(1) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 2 functions: guard clauses and early returns first, then split. 4 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many branches in 2 functions - collapse with early returns. Swap logger.error for logger.exception in 1 except blocks to keep the stack. |
| P3 | blueprints/report/routes/legacy.py | BLE001(3) C901(1) DTZ(4) PLR0915(1) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 4 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Too many statements in 1 functions - extract named helpers. |
| P3 | blueprints/report/routes/module_guard.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/report/services/file_downsize.py | BLE001(6) C901(1) PLR0912(1) PLR0915(1) PLR2004(1) S110(1) | Its single S110 is the same rollback guard pattern - noqa with a reason. The 6 blind catches join the report BLE001 batch. |
| P3 | blueprints/report/services/history.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/report/services/s3_storage.py | BLE001(2) C901(1) T201(3) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. Convert 3 print() to logger.debug. |
| P3 | blueprints/report/services/share.py | DTZ(2) | 2 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. |
| P4 | blueprints/report/schemas.py |  | DELETE - docstring only, zero importers (re-verified) |
| P4 | blueprints/report/services/report_download.py | BLE001(3) T201(3) | DELETE - 138 LOC with zero references anywhere (re-verified). Deleting it also clears 6 findings, so do it before the sweep rather than sweeping a dead file. |

*The other 12 files in this area are clean - formatter pass only.*

### blueprints/subscription/   23 of 42 files - was 36 need work

The area that changed most, and it is now the cleanest by rule variety. Six new files arrived as subscription logic was extracted out of blueprints/entity/services/modules.py, and a sustained decomposition pass has cleared every complexity finding in the blueprint except one - C901 in checkout.py. Everything else that remains here is a single rule: 71 blind exception handlers, 22 of them in the payment path (checkout, payment_methods). That makes this area a clean, mechanical sweep rather than a refactor. The trade is size: services/checkout.py is 3,127 lines and is now the heaviest file in the codebase, and services/panel.py arrived at 1,029. CORRECTION: three previous revisions told you to fix naive datetime handling here, naming renewals.py, checkout.py, store.py and clock.py. That was never measured - DTZ was not in the rule set the tables are built from - and it is wrong. Ruff reports ZERO naive datetime calls in this blueprint; it answers every time question through services/clock.py, a deliberate trusted clock. The 122 naive datetimes are in report (79), xero (11), entity (11) and auth (7). Do not look for them here.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P2 | blueprints/subscription/services/checkout.py | BLE001(17) C901(1) | 3,127 lines - the heaviest file in the codebase - and it has no direct test coverage. Write characterisation tests for the checkout path first. The natural seams are the Stripe-facing calls and the invoice assembly. Split, THEN take the 17 blind catches; doing them first just makes the split harder to review. |
| P2 | blueprints/subscription/services/panel.py | BLE001(3) | 1,029 lines on arrival - it was extracted from entity/services/modules.py rather than written here, so it landed already large. Its 3 blind catches are trivial; the size is the item. Worth splitting while the extraction is still fresh in mind. |
| P2 | blueprints/subscription/services/portal.py | BLE001(5) | 1,023 lines behind the payer portal API. 5 blind catches. Split by endpoint group. |
| P2 | blueprints/subscription/services/store.py | BLE001(1) | 1,347 lines and the subscription persistence layer - roughly 60 ORM operations, and every other subscription service depends on it. Only 1 blind catch, so this is purely a size and blast-radius item. Split by concern (customers, groups, invoices, dunning) with tests, or leave it alone until something else forces the issue. |
| P2 | blueprints/subscription/services/transfers.py | BLE001(9) | 980 lines. C901 was cleared by the recent helper extraction, so what is left is 9 blind catches and the size. The blocker-ordering contract matters here - callers show reasons[0] - so keep the order if you refactor. |
| P3 | blueprints/subscription/constants.py |  | the pattern to follow for report-status constants |
| P3 | blueprints/subscription/models/mixins.py |  | NEW and clean - CreatedAtMixin/TimestampMixin, now used by 10 sibling models |
| P3 | blueprints/subscription/services/access_sweep.py | BLE001(1) | NEW - 293 lines, moved out of entity/services/modules.py. C901 cleared in afc674e. Reconciles entity_function_map daily; see the database section |
| P3 | blueprints/subscription/services/billing_gateway.py | BLE001(4) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/subscription/services/cards.py | BLE001(6) | NEW - 753 lines, moved out of entity/services/modules.py |
| P3 | blueprints/subscription/services/catalog.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/subscription/services/clock.py |  | now completely clean - was BLE001(1) |
| P3 | blueprints/subscription/services/consent.py | BLE001(2) | lost C901 and PLR0912 since the last revision |
| P3 | blueprints/subscription/services/daily.py | BLE001(5) | Narrow 5 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/subscription/services/display.py |  | No findings. Listed because it is the single home for payer-facing date formatting: use it rather than re-spelling %-d, which is glibc-only and fails on the Windows host. |
| P3 | blueprints/subscription/services/dunning.py | BLE001(2) | 818 lines; C901 and PLR0915 both cleared by the helper extraction in 61bf0cf/afc674e |
| P3 | blueprints/subscription/services/money.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/subscription/services/notices.py |  | NEW and clean - dashboard notice logic, moved out of entity/services/modules.py |
| P3 | blueprints/subscription/services/notify.py | BLE001(3) | was BLE001(5) PLR2004(1) S110(1) |
| P3 | blueprints/subscription/services/payment_methods.py | BLE001(5) | lost B904(2) and PLR2004(2) since the last revision |
| P3 | blueprints/subscription/services/policy.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/subscription/services/renewals.py | BLE001(3) | 683 lines; C901, PLR0912 and PLR0915 ALL cleared in 61bf0cf/afc674e. Still one of the four files holding most of the naive datetime calls |
| P3 | blueprints/subscription/services/stripe_client.py | BLE001(2) | lost S110 |

*The other 19 files in this area are clean - formatter pass only.*

### blueprints/xero/   9 of 17 files need work

Unchanged since the last revision. services/publish.py still has 33 blind catches and 9 complex functions across 2,595 lines, having gained 658 in the Xero republish work - the codebase, but it is still the worst one. 18 of the 22 missing HTTP timeouts are in this area, and under gunicorn's 8 concurrent slots a hung Xero endpoint takes the app down.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P2 | blueprints/xero/routes/routes.py | BLE001(14) C901(3) DTZ(3) ERA001(2) PLR0912(2) PLR0915(2) PLR2004(2) S105(1) S113(4) | 1,886 lines with 4 missing HTTP timeouts. Same order as publish.py: timeouts first as their own commit, then the 2 commented-out blocks, then the complexity. |
| P2 | blueprints/xero/services/publish.py | BLE001(34) C901(12) DTZ(6) PLR0912(9) PLR0915(4) PLR2004(12) S113(3) | 2,595 lines - it GREW BY 658 in the Xero republish work and is now the second-largest file as well as the worst by lint count: 34 blind catches and 12 complex functions. 3 of the missing HTTP timeouts are here; add those FIRST as a standalone change, because under gunicorn's 8 concurrent slots a hung Xero endpoint takes the whole app down. Then split, then the catches. |
| P3 | blueprints/xero/routes/settings.py | BLE001(2) S113(2) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Add timeout=10 to 2 requests calls - the convention already exists here. |
| P3 | blueprints/xero/services/integration.py | BLE001(3) DTZ(1) PLR2004(2) S113(3) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. 1 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Name 2 magic numbers, or use http.HTTPStatus for status codes. Add timeout=10 to 3 requests calls - the convention already exists here. |
| P3 | blueprints/xero/services/publish_errors.py | C901(1) PLR0912(1) PLR2004(4) | Reduce complexity in 1 functions: guard clauses and early returns first, then split. Too many branches in 1 functions - collapse with early returns. Name 4 magic numbers, or use http.HTTPStatus for status codes. |
| P3 | blueprints/xero/services/publish_record.py | BLE001(1) DTZ(2) | NEW - 218 lines extracted during the Xero republish work. One blind catch; joins the xero BLE001 batch. |
| P3 | blueprints/xero/services/publish_resolution.py | BLE001(4) | Narrow 4 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/xero/services/settings.py | BLE001(6) DTZ(1) PLR2004(1) S113(3) | Narrow 6 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. 1 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Name 1 magic numbers, or use http.HTTPStatus for status codes. Add timeout=10 to 3 requests calls - the convention already exists here. |
| P4 | blueprints/xero/schemas.py |  | DELETE - docstring only, zero importers (re-verified) |

*The other 9 files in this area are clean - formatter pass only.*

### blueprints/user_management/   3 of 18 files need work

Almost nothing - one blind catch, one complex function, one dead schemas.py.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | blueprints/user_management/routes/admin_list.py | BLE001(1) C901(1) DTZ(2) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. 2 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. |
| P3 | blueprints/user_management/routes/create_user.py | DTZ(2) | 2 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. |
| P4 | blueprints/user_management/schemas.py |  | DELETE - docstring only, zero importers (re-verified) |

*The other 15 files in this area are clean - formatter pass only.*

### blueprints/legal/   3 of 11 files need work

Two blind catches and one unused import.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | blueprints/legal/routes/accept.py | F401(1) | Remove 1 unused import - auto-fixable. |
| P3 | blueprints/legal/routes/documents.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | blueprints/legal/routes/gate.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |

*The other 8 files in this area are clean - formatter pass only.*

### blueprints/invitation/   1 of 8 files need work

invite.py holds the reworded invitation message that several tests still assert the old version of.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | blueprints/invitation/services/invite.py | BLE001(2) DTZ(5) PLR2004(1) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. 5 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Name 1 magic numbers, or use http.HTTPStatus for status codes. |

*The other 7 files in this area are clean - formatter pass only.*

### services/   8 of 24 files need work

Unchanged. token_service.py is where the Xero credential leak lived - the logging line is fixed, but 12 blind catches and 2 silent handlers remain. xero_bridge.py holds 4 of the 22 missing timeouts.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P3 | services/app_runtime/legacy/bootstrap.py | BLE001(1) PLR0915(1) | also sets OAUTHLIB_INSECURE_TRANSPORT |
| P3 | services/app_runtime/scheduler.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | services/auth/token_service.py | BLE001(12) C901(1) PLR2004(1) S110(2) | The 2 S110s are both `try: db.session.rollback() except: pass` in an error path - a defensible guard, not a swallowed bug. Add a one-line noqa reason to each rather than 'fixing' them. The credential leak that once lived here is already fixed; the 12 blind catches remain and belong to the services BLE001 batch. |
| P3 | services/helpers/docx.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |
| P3 | services/helpers/xero_bridge.py | BLE001(6) C901(1) PLR2004(1) S113(4) | Narrow 6 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. Reduce complexity in 1 functions: guard clauses and early returns first, then split. Name 1 magic numbers, or use http.HTTPStatus for status codes. Add timeout=10 to 4 requests calls - the convention already exists here. |
| P3 | services/permission_policy.py |  | the str-Enum pattern to follow for status constants |
| P3 | services/user_presence.py | BLE001(4) S110(1) | Same rollback-guard S110 - noqa it. The 4 blind catches join the services batch. Note this file reads user.current_entity_id, which billing-backend does not mirror; see the database document before changing what it writes. |
| P4 | services/app_runtime/legacy/legacy_bootstrap.py |  | DELETE - a 7-line shim with no importers (re-verified). |

*The other 16 files in this area are clean - formatter pass only.*

### pettycash/   2 of 5 files need work

hooks.py holds the Datadog token fallback and 10 blind catches.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P2 | pettycash/core/hooks.py | BLE001(10) C901(2) PLR0915(2) | also holds the Datadog token fallback |
| P3 | pettycash/core/blueprint_loader.py | BLE001(3) | Narrow 3 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |

*The other 3 files in this area are clean - formatter pass only.*

### models/, utils/, legal/, cli/   5 of 16 files need work

models/db.py is the one to be careful with: it is a model-registration aggregator, and ruff --fix will strip its 'unused' UserToken import, which deregisters the mapper and fails at runtime.

| Pri | File | Ruff | What to do |
| --- | --- | --- | --- |
| P1 | models/db.py | F401(1) | DO NOT run `ruff --fix` on this file. It is the model-registration aggregator; the 'unused' UserToken import registers the mapper, and removing it breaks the app at runtime, not at import. The root cause is precise: __all__ lists 43 names and UserToken is not one of them, which is why ruff flags this import and none of the other 42. The correct fix is to ADD UserToken to __all__ - not to add a noqa, which earlier revisions of this document wrongly recommended. |
| P3 | cli/modules.py | PLR2004(1) | Name 1 magic numbers, or use http.HTTPStatus for status codes. |
| P3 | utils/__init__.py | BLE001(2) DTZ(4) PLR2004(1) | Narrow 2 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. 4 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. Name 1 magic numbers, or use http.HTTPStatus for status codes. |
| P3 | utils/entity.py | DTZ(1) | 1 naive datetime calls: add tzinfo - the app runs Asia/Hong_Kong via models.db.tz. In a daily-report system a naive now() near midnight files against the wrong day. |
| P3 | utils/report.py | BLE001(1) | Narrow 1 blind `except Exception`: name the exception each one expects, or log a reason before swallowing. |

*The other 12 files in this area are clean - formatter pass only.*

### templates/   21 of 84 files - was 83 need work

Console calls have grown from 468 to 526 and spread from 14 files to 17 - this is getting worse, not better. Four templates are orphaned and go. The five largest are 2,500+ lines each and mostly inline JavaScript, which is why ESLint over static/js/ alone would cover very little of what actually ships.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | templates/download_statements.html | 5 console calls - NEW, had none |
| P3 | templates/edit_report.html | 1 console call - NEW, had none |
| P3 | templates/entity/entity_dashboard_v2.html | 53 console calls (was 49) - 2,625 lines |
| P3 | templates/entity/partials/electronic_delivery_scripts.html | 37 console calls (was 29) |
| P3 | templates/entity/partials/xero_mapping_classic_script_fragment.html | 115 console calls (was 107) - 3,896 lines |
| P3 | templates/entity/settings.html | 122 console calls (was 113) - 4,870 lines |
| P3 | templates/entity/settings_entity.html | 45 console calls (was 34) - 2,903 lines |
| P3 | templates/entity/settings_users_scripts.html | 2 console calls (was 1), 1 open TODO |
| P3 | templates/login.html | 3 console calls - NEW, had none |
| P3 | templates/report/cash_count.html | 8 console calls - NEW, had none |
| P3 | templates/report/deposit.html | 2 console calls - NEW, had none |
| P3 | templates/report/ending.html | 5 console calls - NEW, had none. 2,093 lines |
| P3 | templates/report/expense.html | 84 console calls (was 65) - 4,522 lines |
| P3 | templates/report/opening.html | 6 console calls - NEW, had none |
| P3 | templates/report/sales.html | 17 console calls (was 10) |
| P3 | templates/report/submitted.html | 3 console calls - NEW, had none |
| P3 | templates/report_history/report_history.html | 18 console calls (was 7), 1 open TODO |
| P4 | templates/code.html | DELETE - 375 B, no inbound reference (re-verified) |
| P4 | templates/entity/entity_continue_report_v2.html | DELETE - superseded by entity_dashboard_v2.html (re-verified) |
| P4 | templates/report/index.html | DELETE - no inbound reference (re-verified) |
| P4 | templates/user approval.html | DELETE - the filename contains a space, so it is unroutable and nothing renders it (re-verified). One thing breaks: tests/test_entity_selection_flow.py:467 asserts the file exists. Update that test in the same commit. |

*The other 63 files in this area are clean - formatter pass only.*

### static/   26 of 56 files need work

Unchanged, and re-verified: all 24 orphans are still orphaned, 2.7 MB of the 3.5 MB. static/js/expense.js and static/js/opening.js now appear in a grep only because ERROR_MESSAGE_LEAKS.md mentions them by name - no template loads them. Delete them, but diff the three JavaScript files against the inline script in their matching template first, because the inline copy may have drifted.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | static/js/datadog-logs.js | the console channel to route stripped logs through |
| P4 | static/css/layout.css | DELETE - orphaned (re-verified) |
| P4 | static/img/cash_count.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/connect-blue.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/connect-blue.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/connect-white.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/connect-white.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/disconnect-blue.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/disconnect-blue.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/disconnect-white.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/disconnect-white.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/error.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/info.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/info.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/logo_v2.svg | DELETED 2026-09-22 with the rest of the old wordmark (logo_v2.webp/png, minty-logo.png, logo.png, minty_newlogo_word.png) - every page now uses img/minty-mark.png + img/favicon.ico |
| P4 | static/img/minty_important_update_bk.png | DELETE - orphaned (re-verified) |
| P4 | static/img/ov-logo.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/success.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/toast-close.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/warning.svg | DELETE - orphaned (re-verified) |
| P4 | static/img/warning.webp | DELETE - orphaned (re-verified) |
| P4 | static/img/xero-logo.svg | DELETE - orphaned (re-verified) |
| P4 | static/js/expense.js | DELETE - orphaned (re-verified; the only grep hit is ERROR_MESSAGE_LEAKS.md) |
| P4 | static/js/login.js | DELETE - orphaned (re-verified) |
| P4 | static/js/opening.js | DELETE - orphaned (re-verified; the only grep hit is ERROR_MESSAGE_LEAKS.md) |
| P4 | static/js/scripts.js | 28 console calls + commented-out JS - clean, do not delete |

*The other 31 files in this area are clean - formatter pass only.*

### tests/   3 of 96 files - was 94 need work

The suite is NOT green and the gap has widened: 90 non-passing at HEAD - 61 failed plus 29 errors against 1,387 passed, measured 2 September 2026 on a full-suite run. The previous revision recorded 64. That figure, not zero, is the bar a refactor has to hold. Two traps: compare a full run against a full run, never a single file; and grep for ERROR as well as FAILED, because 29 of the 90 are collection and fixture errors that a FAILED-only count misses entirely. Three new characterisation test files are still needed before any structural refactoring - the obvious targets are the three files this document names as split-first: subscription/services/checkout.py, entity/routes/settings.py and entity/services/settings.py, none of which has direct coverage.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | tests/test_csrf_exemptions.py | NEW since the last revision |
| P3 | tests/test_onboarding_module_state.py | NEW since the last revision |
| P4 | tests/test_entity_selection_flow.py | line 467 asserts templates/user approval.html exists - update it when that file is deleted |

*The other 96 files in this area are clean - formatter pass only.*

### Root config and docs   12 of 27 files need work

Resolve the three dependency manifests to one, regenerate .env.example from the code, add the CI and linter config that do not exist, and untrack the artefacts that were committed by accident.

| Pri | File | What to do |
| --- | --- | --- |
| P3 | .env.example | 28 variables missing, 5 stale - regenerate from the code |
| P3 | .github/workflows/teams-notification.yml | still the only workflow; posts a ClickUp comment and runs no tests |
| P3 | Procfile | binds ${PORT:-10000}, a Render convention |
| P3 | package.json | add lint and format scripts - prettier is installed but never invoked |
| P3 | pyproject.toml | add [tool.ruff.lint] and [tool.pytest.ini_options]; drop black/isort/autopep8/autoflake |
| P3 | pyrightconfig.json | re-enable reportOptionalMemberAccess and reportCallIssue |
| P4 | .ebextensions/mysqlclient.config | DELETE - it installs MySQL client libraries for an application that runs on PostgreSQL. Nothing else in .ebextensions/ is used. |
| P4 | CODE_CLEANSE_NOTES.md | prior audit output - cross-check, then fold in or delete |
| P4 | ERROR_MESSAGE_LEAKS.md | prior audit output - cross-check, then fold in or delete. Currently the only thing referencing two orphaned static files |
| P4 | pdfconversion.txt | scratch notes tracked at the repo root - fold in or delete |
| P4 | requirements.txt | delete or generate via uv export - Docker does not read it |
| P4 | tmp_test.sqlite 11.12.17 AM | DELETE and untrack. A SQLite test database committed to the repo root, with a non-breaking space in the filename. Add a .gitignore rule for tmp_test.sqlite* in the same commit so it cannot come back. |

*The other 15 files in this area are clean - formatter pass only.*

## Method and totals

File lists from `git ls-files` in each working tree on 2 September 2026. Per-file codes from a single `ruff check` run over each Python repository with the rule set in the legend; the run reproduces the previous revision's counts exactly on blueprints/xero/services/publish.py, blueprints/entity/routes/settings.py and blueprints/report/routes/api.py, so the two revisions are directly comparable. Console counts, line counts and orphan checks were re-run, not carried over. TypeScript notes are from reference-graph sweeps and manual reading.

Minty 642 tracked files, billing-backend 109, billing-frontend 148, onboarding 49. Two repositories - billing-frontend and onboarding - still have no test files at all, and none of the four runs tests in CI.

*Generated from the Minty Stack Inventory. One document per repository; the other three cover billing-backend, billing-frontend, onboarding and Minty respectively.*
