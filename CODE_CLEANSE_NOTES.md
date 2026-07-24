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

## Blueprint #1: user_management — WORK DONE (staged, NOT committed)

Scope decided with owner: apply **dead-import removal + A (superuser gate) + B
(role-check helpers)**. **Skip C** (generic error-response helper). Formatting deferred.

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

### ⚠️ REGRESSION — 3 tests now fail (this is why we're paused on this file)
The **A (superuser gate) part is fine.** The **B (role helpers) part broke tests:**

- `test_user_management_membership_roles.py::test_updating_membership_role_...`
- `test_user_management_membership_roles.py::test_deleting_membership_role_...`
- `test_entity_selection_flow.py::test_admin_dashboard_passes_membership_summary_map`
  (verify this one — likely same root cause via admin_dashboard, or an import-time effect)

**Root cause (confirmed):** these are white-box tests. They call the route's
unwrapped inner fn directly (`roles_routes.delete_user_role.__wrapped__.__wrapped__(...)`)
and patch module-level names ON THE ROUTE MODULE:
`monkeypatch.setattr(roles_routes, "UserEntity", FakeUserEntity)` (lines ~143, ~171).
Moving the `UserEntity.query` into `services/roles.py` means the monkeypatch no
longer intercepts it → real query runs with no Flask app context →
`RuntimeError: current Flask app is not registered with this SQLAlchemy instance`.

**LESSON for the whole cleanup:** In this repo, extracting DB-touching logic out
of a route module into `services/` breaks tests that
`monkeypatch.setattr(<route_module>, "UserEntity"/"db"/"User", ...)`.
Before consolidating DB access, grep the tests for such patches.

### Two ways to resolve B (owner to choose)
1. **Revert B, keep A.** A is a clean win with no test breakage. Drop the role
   helpers (or keep them unused for later). Lowest risk to finish blueprint #1 now.
2. **Keep B, make it test-compatible.** Either:
   a. have helpers take the model/session as params so the route still owns the
      patched name, e.g. `find_membership_or_error(user_id, entity_id, model=UserEntity)`
      and call with the route-module `UserEntity`; **or**
   b. update the 2–3 tests to patch the new location
      (`services.roles.UserEntity`) — but this changes tests, which is a bigger ask.

Recommendation: **option 1 for now** (ship A), revisit B with approach 2a in a
dedicated pass once the pattern is proven on a smaller helper.

---

## Remaining for user_management (after B is resolved)
- Final formatting pass: `isort` + `black` on `blueprints/user_management/`.
  (~18 E501 long lines in `routes/roles.py`; awkward import continuation in
  `routes/create_user.py:8`.)
- Re-run regression check → expect "no new failures".

## Not yet started
- Blueprints: `invitation`, `auth`, `xero`, `entity`, `report` — same 3-step recipe.
- Optional deeper dead-code sweep: `vulture` is **not installed**; would need
  `pip install vulture` (ask owner before adding to the env).
