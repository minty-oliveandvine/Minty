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

## Next up: blueprint #4 = `xero` (5348 LOC, 17 files)

## Not yet started
- Blueprints: `xero`, `entity`, `report` — same 3-step recipe.
- Known pre-existing debt found along the way: `blueprints/entity/routes/settings.py`
  has **12 dead imports** (F401) already on HEAD — clean up in the entity pass.
- Optional deeper dead-code sweep: `vulture` is **not installed**; would need
  `pip install vulture` (ask owner before adding to the env).
