# Archived planning docs

Superseded planning, refactoring, and status documents moved out of the repo
root on 2026-07-24. All of them describe work that has since been completed or
abandoned; none are referenced by application code.

They are kept (rather than deleted) because several record *why* a decision was
made — useful when the reasoning behind a schema or permission change is needed
later. The cross-references between these files still resolve, since they were
moved together as a group.

| File | Written | What it covers |
| --- | --- | --- |
| `plan.md` | 2026-03 | Centralising permission policy + authz decorator |
| `refactoring_plan.md` | 2026-03 | `User.role` → `User.system_role` migration |
| `refactoring_plan_2.md` | 2026-03 | Removing `User.company` in favour of `UserEntity` |
| `remove_user_role.md` | 2026-03-16 | Decision notes for the `User.role` cutover |
| `refactor_base.md` | 2026-03-04 | Baseline snapshot at commit `d49f18d` |
| `refactoring_output.md` | 2026-03 | Summary of the `blueprints/` module split |
| `legacy_app_refactoring_plan.md` | 2026-03-04 | `legacy_app.py` teardown checklist (109 → 31 lines) |
| `recommended_folder_structure.md` | 2026-03 | Proposed folder layout |
| `working_report.md` | 2026-03-10 | Status report for the `permission` branch |

Still active, and deliberately left in the repo root:

- `README.md` — project documentation
- `CODE_CLEANSE_NOTES.md` — resume notes for the in-progress `code-cleanse-blueprints` branch
- `ERROR_MESSAGE_LEAKS.md` — open error-message audit
