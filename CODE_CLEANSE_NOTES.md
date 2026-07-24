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

## Next up: blueprint #2 = `invitation` (926 LOC, 8 files)
Same 3-step recipe. Remember the dependency-injection lesson above.

## Not yet started
- Blueprints: `invitation`, `auth`, `xero`, `entity`, `report` — same 3-step recipe.
- Optional deeper dead-code sweep: `vulture` is **not installed**; would need
  `pip install vulture` (ask owner before adding to the env).
