# Code-cleansing: blueprints/ — progress & resume notes

Branch: `code-cleanse-blueprints` (off `Minty-PettyCash`).
**Do not push. Commits are done by the repo owner, not by the assistant.**

Last updated: 2026-07-24. Status: **PAUSED mid blueprint #1 (`user_management`).**

---

## Goal & rules

Code-cleansing the `blueprints/` folder:
1. **Dead code** — remove unused imports / functions / unreachable branches.
2. **Duplication → shared parent** — merge near-duplicate functions into one
   parametrized parent. Consolidate **within each blueprint's `services/`** first;
   only promote to `blueprints/shared/` if genuinely used across blueprints.
3. **Hygiene** — `isort` + `black`, as a **separate final pass** per blueprint
   (keeps logic diffs clean to review).

Decided workflow:
- One blueprint at a time, **smallest → largest**:
  `user_management` (732) → `invitation` (926) → `auth` (1347) → `xero` (5348)
  → `entity` (7961) → `report` (14447). (`shared` is empty.)
- **Verify after every step** with the baseline regression check (below).
- Pause after each blueprint for owner review + commit.

---

## Baseline & regression check (IMPORTANT)

The test suite is **NOT green at baseline** — 79 pre-existing failing/erroring
tests, from the suite's own debt, NOT from our cleanup. Examples:
- `test_invitation.py` (31): fixtures build `Entity(currency_code=...)` but the
  model dropped that field (schema drift).
- Various teardown/session-isolation errors.
- Local env noise only (not fatal): `pkg_resources` missing (setuptools >=81
  dropped it), `numpy 2.x` warnings. **Not** worth mutating the global anaconda env.

Because baseline is red, the rule is: **no test that passes today may start
failing.** Pre-existing red may stay red.

Baseline recorded at (scratchpad — may be cleared between sessions; regenerate if gone):
- `.../scratchpad/baseline_failing.txt` — the 79 failing nodeids
- `.../scratchpad/check.sh` — re-runs suite, diffs vs baseline, prints new failures

Regenerate baseline if the scratchpad file is gone:
```
python -m pytest -p no:randomly --tb=no -q 2>/dev/null \
  | grep -E "^(FAILED|ERROR) tests/" | sed -E 's/ +-.*//' | sort > baseline_failing.txt
```
Check for regressions after a change:
```
python -m pytest -p no:randomly --tb=no -q 2>/dev/null \
  | grep -E "^(FAILED|ERROR) tests/" | sed -E 's/ +-.*//' | sort > current_failing.txt
comm -13 baseline_failing.txt current_failing.txt   # any output = NEW regression
git checkout tmp_test.sqlite    # tests dirty this file; always revert it
```
Note: running tests modifies `tmp_test.sqlite` — always `git checkout` it after.

---

## Blueprint #1: user_management — ✅ COMPLETE

Scope decided with owner: apply **dead-import removal + A (superuser gate) + B
(role-check helpers)**. **Skip C** (generic error-response helper).

Final state: all three steps done (dead code, consolidation, formatting).
Regression check: **OK — no new failures beyond the 79 baseline.**

### Changes made
- **New** `blueprints/user_management/services/access_guards.py`
  - `require_superuser(redirect_endpoint, *, message=, category=, log_unauthorized=)`
    → returns `None` if superuser, else a redirect `Response`.
  - Replaces 4 duplicated superuser gates in:
    `admin_dashboard.py`, `approve_reject_access.py` (×2), `admin_list.py`
    (the last uses `log_unauthorized=True`).
- **Edited** `blueprints/user_management/services/roles.py`
  - Added `find_membership_or_error()`, `check_role_assignment_or_error()`,
    `check_can_manage_membership_or_error()` (byte-identical JSON/messages preserved).
  - Used by the 3 handlers in `routes/roles.py`.
- **Dead code removed:**
  - `routes/approve_reject_access.py`: unused `request` import.
  - `routes/admin_list.py`: two inline `from flask import ...` shims (one truly dead `flash`).

ruff `--select F` passes on all edited files. Modules import cleanly.

### ⚠️ THE KEY LESSON — dependency injection is required in this repo

The first attempt at the consolidation regressed 3 tests. **This will happen
again in every remaining blueprint, so read this before consolidating anything.**

These are **white-box tests**: they call the route's unwrapped inner function
directly (`roles_routes.delete_user_role.__wrapped__.__wrapped__(...)`) and
patch module-level names **on the route module**, e.g.:
```python
monkeypatch.setattr(roles_routes, "UserEntity", FakeUserEntity)
monkeypatch.setattr(roles_routes, "db", SimpleNamespace(session=session))
monkeypatch.setattr(admin_dashboard_routes, "current_user", SimpleNamespace(...))
monkeypatch.setattr(roles_routes, "can_manage_role_assignment_for_entity", ...)
```
If you move that name's usage into `services/`, the patch no longer intercepts
it → the real object is used → `RuntimeError: The current Flask app is not
registered with this 'SQLAlchemy' instance`, or an `AttributeError` when the
patched attribute no longer exists on the route module.

**THE FIX PATTERN (use this everywhere):** the shared parent takes the dependency
as a keyword arg defaulting to the real one; the route passes its own
module-level binding, so tests keep patching the route module.

```python
# services/ — the shared parent
def find_membership_or_error(user_id, entity_id, *, model=None):
    membership_model = model if model is not None else UserEntity
    ...

# routes/ — caller passes its own binding (the name tests patch)
membership, error = find_membership_or_error(user_id, entity_id, model=UserEntity)
```

Applied to: `model=` (UserEntity), `user=` (current_user), `user_model=` (User),
`policy=` (can_manage_role_assignment_for_entity).

**Before consolidating, always run:**
```
grep -rn "monkeypatch.setattr(<route_module_alias>" tests/
```
and inject every name the tests patch.

## Blueprint #2: invitation — ✅ COMPLETE

Regression check: **OK — no new failures beyond the 79 baseline.** ruff `F` clean.

### Changes made
- **Dead code:** `routes/accept.py` imported `accept_invitation` but never called
  it (only named in prose comments). The real callers — `blueprints/auth/routes/
  email_auth.py` and `blueprints/xero/routes/routes.py` — import it from the
  service themselves, so the import was genuinely dead.
- **Consolidation:** `cancel_invite` and `resend_invite` in `routes/api.py` were
  near-identical twins (resolve invitation → 404, `has_permission` → 403,
  `can_manage_role_assignment_for_entity` → 403, each with parallel log lines).
  Extracted `_load_invitation_for_management(invitation_id, action, role_denied_message)`
  → returns `(invitation, None)` or `(None, error_response)`.
  - `action` parametrizes the log prefix; verified the loguru positional
    template renders **byte-identically** to the originals.
  - All 4 user-facing messages preserved verbatim; each now appears once, not twice.
  - Lazy imports kept INSIDE the helper — `accept.py` documents that this is
    deliberate (a failed module-level import would drop the whole blueprint).
- **Formatting:** `isort` + `black`.

Like-for-like saving: 343 → 315 lines in `api.py` (28 lines) once formatting is
held constant. Raw line count rose only because black reflowed long `jsonify` calls.

### Note on validation
35 of the invitation tests are in the pre-existing red baseline (the
`Entity(currency_code=...)` fixture drift), so they could NOT validate this
change. Relied on: "no new failures" + byte-exact message/log preservation.
These tests use `unittest.mock.patch` with full dotted paths into
`services.invite`, NOT `monkeypatch.setattr` on route modules — so the
dependency-injection trap from blueprint #1 did not apply here.

## Blueprint #3: auth — ✅ COMPLETE (+ first cross-blueprint helper)

Regression check: **OK — no new failures beyond the 79 baseline.** ruff `F` clean.

Owner decided: **dead code + formatting only** for auth itself — `email_auth.py`
is long (332 lines) but it is sequential flow, NOT duplication. There was no
clean parent to extract, and it is auth-critical code. Don't force it.

### Changes in auth
- `routes/permissions.py`: removed unused `current_user` import.
- `models/__init__.py`: `EmailOtp` was imported but missing from `__all__`
  (while `User`/`UserToken` were listed). Added it rather than deleting the
  import — it was an intended re-export. Verified first that `EmailOtp`'s table
  registers via `models/db.py` regardless, so nothing depended on this file.
  (Nothing imports this package at all.)
- `isort` + `black`.

### Cross-blueprint: `blueprints/shared/entity_display.py` (NEW)
The entity-acronym computation was duplicated **13×** across 5 blueprints
(auth, entity, report ×7, invitation, plus `report/services/share.py`).

**⚠️ The variants were NOT equivalent** — `share.py` skipped words not starting
with a letter, the other 12 did not:

| name | the 12 copies | `share.py` |
|---|---|---|
| `Olive and Vine` | `OAV` | `OAV` |
| `7 Eleven Store` | `7ES` | **`ES`** |
| `&Co Bakery` | `&B` | **`B`** |

Naively merging them would have silently changed acronyms for entities whose
names start with a digit or symbol. Resolved (owner's call) with **one parent +
a flag**, so behavior is unchanged everywhere:

```python
build_entity_acronym(name)                     # the 12 sites → "7ES"
build_entity_acronym(name, letters_only=True)  # share.py     → "ES"
```

All 13 sites migrated; `_build_entity_acronym` deleted from `share.py`.
Equivalence to both originals verified over edge cases (None, empty, unicode,
digits, symbols).

**⚠️ LESSON — scripted import insertion:** inserting an import after "the last
line starting with `from models.`" broke 5 files, because that line was the
OPENING line of a parenthesized multi-line import. Caught only by a collection
ERROR. **Always `ast.parse` every file after a scripted edit** — ruff/black
won't run on a file that doesn't parse.

Note: only `isort` was run on the touched report/entity files, NOT `black` —
those blueprints have not had their formatting pass yet and reformatting them
now would bloat this diff. Their `black` pass comes with their own turn.

## Blueprint #4: xero — ✅ COMPLETE (dead code + token resolver)

Regression check: **OK — no new failures beyond the 79 baseline.** ruff `F` clean.

### Dead code removed
- `routes/routes.py`: `current_app as app` (verified unused — every other "app"
  match was prose in comments), `XeroContactSync`.
- `services/publish.py`: `EntityAccountXero`, now-orphaned `BytesIO`, 2 f-strings
  without placeholders, and 2 dead locals.
- `services/settings.py`: `EntityAccountXero`, `XeroContactSync`.

**Two dead locals needed real investigation — do NOT blind-`ruff --fix` this file:**
- `files` dict (attachment upload) *looked* like a dropped-attachment bug, since
  it's built right before an upload. It isn't: the upload uses `data=file_bytes`
  (raw PUT) and an adjacent comment confirms multipart was abandoned. Vestigial.
- `reference` in `xero_discrepancy` *looked* like a dropped Xero field, since
  sibling functions do send `"Reference"`. It isn't: `create_bank_transaction`
  derives the identical `"MT{date}Discrepancy"` internally from
  `type_of_transaction`. Left a comment there so the next reader doesn't re-ask.

### Consolidation: `_resolve_access_token(entity_id)`
The token-resolution preamble was duplicated **11×**. Owner's call was to extract
**only the identical lookup** and keep every call site's own failure handling —
this is the money path (it posts real transactions to Xero) and several xero
tests are already red at baseline, so the safety net is weak.

Returns `(access_token, None)` on success, else `(None, "no_token" | "no_user")`.
The two failure modes are kept DISTINCT because the original logged different
messages for each, and that distinction matters when debugging a failed publish.
All 10 no-token + 10 no-user log messages are preserved verbatim.

Call sites keep their own contracts, which is exactly why they weren't merged
further — three different return shapes:
| sites | returns | records error |
|---|---|---|
| 4 low-level `create_*` / upload | `False` | no |
| 5 module-level `xero_*` | `(0, 1)` | `_record_module_error` |
| 1 orchestrator | `_aggregate_error_result(...)` | no |

**9 of 11 sites migrated. 2 deliberately left alone** because their structure
genuinely differs:
- `xero_integrated_module` (~line 1402) — different return + comment placement.
- `update_xero_deposit_after_change` (~line 1708) — `except` precedes the
  `if not token_user` check and it returns `(bool, message)`, not a bare value.

### Formatting: intentionally SKIPPED for xero
`black` was NOT run here. `publish.py` (2023 LOC) and `routes/routes.py` (1872
LOC) would produce a reformat diff that swamps the logic change on the financial
path. Do this as its own isolated commit if wanted.

### ⚠️ LESSON — stop scripting after the second failure
Three scripted attempts at the preamble migration failed: one regex hit
catastrophic backtracking and hung for 120s (no file damage — it never reached
the write), then two line-based versions tripped over shape variants. What
actually worked: dump every site, look at them, then use explicit
full-text replacements for the uniform ones and hand-edit the odd ones.
Also note `timeout` is NOT available on macOS.

## Blueprint #5: entity — ✅ COMPLETE

Regression check: **OK — no new failures beyond the 79 baseline.** ruff `F` clean.
Net **−41 lines** (95 insertions / 136 deletions across 9 files).

### Dead code removed — 15 dead imports
- `routes/settings.py` ×10 (`Iterable`, `cast`, `pycountry`, `COA_EXCLUDED_TYPES`,
  `reconcile_account_info_status`, `sync_entity_account_xero_active`,
  `get_account`, `get_contact`, `has_entity_membership`, `is_superuser`)
- `services/shared.py` ×2 (`select`, `EntityAccountXero`)
- `services/xero_account_mapping_post.py` ×3 (`current_user`,
  `account_info_to_xero_format`, `contact_sync_to_xero_format`)

Verified none were monkeypatch targets before removing (the DI lesson).

### Consolidation: `_run_in_background(label, target, *args, entity_id, ...)`
Four `*_background` wrappers in `services/settings.py` shared an identical
skeleton (resolve `flask_app` → define `_run()` with app context + try/except
logging → spawn daemon thread → log start):
`sync_xero_accounts_to_db_background`, `sync_chart_of_accounts_if_changed_background`,
`sync_contacts_if_changed_background`, `backfill_lock_dates_if_needed_background`.

Variations preserved:
- only the first passes a thread name (`XeroAccountsSync-{entity_id}`) →
  `thread_name=` param, omitted entirely when not set (so `Thread()` still gets
  no `name` kwarg, as before);
- wrapped call signatures differ (chart-of-accounts also takes `user_id`) →
  `*args` passthrough.
- `label` is passed as a `%s` arg rather than baked into the format string;
  verified the rendered output is byte-identical, so log greps still work.

**All four public signatures are unchanged** (diffed against HEAD) — callers in
`routes/settings.py`, `routes/billing_sync.py` and `report/routes/expense.py`
are unaffected. `test_billing_sync_contacts.py` patches
`sync_contacts_if_changed_background` wholesale on the *route* module, so it
never executes the consolidated body — safe.

**NOT consolidated:** `sync_all_accounts_and_contacts_background` looks like a
fifth wrapper by name, but it runs inline and spawns NO thread. Merging it into
the helper would have wrongly moved it onto a background thread.

### Checked and rejected
The entity-not-found flash/redirect idiom looked like a candidate but is only
**3 sites**, one of which uses a different lookup (`func.trim(Entity.id)`).
Not worth a helper.

### Formatting: `isort` only (no `black`)
Same call as xero — `services/settings.py` (1585) and `routes/settings.py` (1385)
would produce a reformat diff that swamps the logic change.

## Blueprint #6: report — ✅ COMPLETE (final blueprint)

Regression check: **OK — no new failures beyond the 79 baseline.**
`ruff --select F` is now **clean across ALL blueprints**. Net **−49 lines**.

### Dead code removed (55 ruff fixes)
- ~20 unused imports (`AccountInfo`/`EntityAccountXero` repeated across
  deposit/download/opening/report_detail/report_download, `can_edit_report`
  across 6 files, `User` in api.py, `db` in report_download).
- ~35 f-strings without placeholders (nearly all in `services/ending.py`).
- 1 dead local (`entity_id` in `generate_share_link` — verified dead:
  `create_share_link_for_report` receives the whole `data` dict and extracts it).

### 🐛 BUG I INTRODUCED AND FIXED — `expense.py` NameError
`blueprints/report/routes/expense.py` called `build_entity_acronym()` with **no
import** — a guaranteed `NameError` on the expense page. I introduced this in
commit `d70c79f` (the auth-pass acronym migration): that file was hand-edited
rather than script-edited, and I added the call without the import.

**Why it slipped through:**
1. After the auth pass I ran `ruff --select F` only on the blueprints I thought
   I'd touched — but `expense.py` was collateral from a CROSS-blueprint change,
   and I never re-linted `report`.
2. The test suite doesn't cover that path, so the regression check stayed green.

**Rule going forward: after any cross-blueprint change, run
`ruff check blueprints/ --select F821` REPO-WIDE, not per-blueprint.**
F821 (undefined name) is the check that catches this class of error.

### 🐛 Pre-existing bug fixed — `create.py` missing `tz`
`routes/create.py:84` called `datetime.now(tz)` but never imported `tz` →
`NameError` in the report-creation future-date guard. Pre-existing (verified
present on the pre-cleanse base commit), NOT caused by this work. Fixed with
the one-word import that sibling files (`legacy.py`, the models) already use;
`tz` is `pytz.timezone("Asia/Hong_Kong")`, which matches the code comment.

### Consolidation: `entity_badge_data()` / `entity_badge_date()`
`get_entity_badge_data` was a **byte-identical closure defined 5×** (deposit,
expense, sales, cash_count, services/ending) — the cleanest duplication in the
whole project. The same badge-date logic also appeared inline 3× more
(opening.py, history_query.py, entity/routes/list.py) for 8 copies total.

Added to `blueprints/shared/entity_display.py`, next to the acronym helper they
already called. Equivalence verified against the original over datetime/date/
None-created_at/empty-name/None-entity cases.

### Left alone deliberately
9 model files under `report/models/` start with a **UTF-8 BOM** (U+FEFF).
Harmless to Python at runtime (the BOM is stripped on read) and pre-existing —
stripping them is cosmetic churn, so out of scope. Note that `ast.parse()` on
the decoded text DOES choke on them, which makes bare `ast.parse` checks report
false syntax errors for these 9 files.

### Formatting: `isort` only (no `black`)
Same call as xero/entity — `routes/api.py` (2025) and `services/ending.py`
(1998) would swamp the logic diff.

---

# ✅ ALL 6 BLUEPRINTS COMPLETE

| # | blueprint | LOC | outcome |
|---|---|---|---|
| 1 | user_management | 732 | superuser gate + role helpers (DI pattern established) |
| 2 | invitation | 926 | cancel/resend guard merged |
| 3 | auth | 1347 | dead code only + shared acronym helper (13 sites) |
| 4 | xero | 5348 | dead code + token resolver (9 of 11 sites) |
| 5 | entity | 7961 | 15 dead imports + background-thread runner |
| 6 | report | 14447 | 55 dead-code fixes + badge helper (5 identical closures) |

`ruff --select F` clean across all blueprints. No new test failures at any step.

## Remaining known debt (NOT addressed — deliberate)
- **The 79-test red baseline.** Chiefly `test_invitation.py` (31) failing on
  `Entity(currency_code=...)` fixture drift — the model dropped that field.
  This is test debt, not product debt, but it means the invitation blueprint is
  effectively untested. Worth its own effort.
- **`black` never run** on xero / entity / report (the 4 files over 1200 lines).
  Worth doing as an isolated formatting-only commit so it's easy to review.
- **UTF-8 BOMs** on 9 `report/models/*.py` files.
- Known pre-existing debt found along the way: `blueprints/entity/routes/settings.py`
  has **12 dead imports** (F401) already on HEAD — clean up in the entity pass.
- Optional deeper dead-code sweep: `vulture` is **not installed**; would need
  `pip install vulture` (ask owner before adding to the env).
- **Dead `?token=` share routes (found 2026-10-01; REMOVED 2026-10-05).**
  `/Minty_Report_<x>/ending?token=` and `entity_ending`'s `?token=` branch took a 30-day HMAC
  token that ignored the ShareLink row, so a revoked link still opened. Deleted in the URL
  security round, with `/insert_xero_transaction`, `/remove/connections/all`,
  `/api/refresh_xero_token`, `/mytoken`, `/event_id`, `/debug/xero-settings/<id>` and the dead
  `blueprints/xero/routes/settings.py` and `entity/services/settings.py::debug_xero_settings`.
- **Share links were silently dead on pettycashv3 (FIXED 2026-10-01, `4f91285`).**
  `minty_report_share` compared the TIMESTAMPTZ `expires_at` (tz-aware) with naive
  `datetime.now()`. The TypeError was swallowed by the route's blanket `except` and shown as
  "This link doesn't look right to me", so no link opened. The route now compares aware
  datetimes and logs the traceback (`logger.exception`).
- **NOT FIXED: two crashes on the report ending page (`report_ending`), found 2026-10-01.**
  1. `services/ending.py` (~line 663) adds `report.opening_balance` and subtracts
     `report.expenses` without coalescing. A submitted report with a NULL `expense_total`
     or `opening_balance` raises `TypeError: NoneType + int`.
  2. `templates/report/ending.html` (~line 391): when an entity has no sales methods
     (`sale_info`), the "hardcoded list" fallback calls `.format()` on
     `sales_data.foodpanda_sales`. That value is Jinja `Undefined`, and `is not none` is true
     for it, so the page raises `unsupported format string passed to Undefined.__format__`.
  Both surface through the share route as the generic "This link doesn't look right" flash
  and are now logged with a traceback.
