# Archive — migration runbooks (superseded 2026-09-17)

Deployment runbooks for the `c`/`s`/`r` alembic revisions, written when each was to be
run by hand against the live `pettycashv2` schema with manual pre-flight checks.

Nobody follows them any more: under `docs/modernisation/modernisation_plan.md` those revisions run
inside `flask db upgrade` in step 2 of `scripts/schema_migration/rehearse.py`, against a
copy of production, and the 2026-09-17 rehearsal took production's `f3a1c2b4d6e8` to
`v1a01_billing_account` clean. They are kept because they are the only prose record of
why the chain is shaped as it is, and `cash_denomination_schema_review.md` is still cited
from the `c1a01` and `c2a02` migration docstrings.

| File | What it was |
|---|---|
| `cash_denomination_migration_runbook.md`, `cash_denomination_schema_review.md` | `c1a01`–`c4a04`: denominations become rows in `cash_info`; the review holds the four corrections to the v3 draft. |
| `sales_method_migration_runbook.md` | `s1a01`–`s7a07`: sales methods become rows in `sales_method`. |
| `report_consolidation_runbook.md` (index), `..._step_3_5_runbook.md`, `..._step_4_runbook.md` | `r0`–`r10a10`: seven report tables collapse into `report` and `shop_expense`. |
