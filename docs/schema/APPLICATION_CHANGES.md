# Application changes required by `pettycashv3`

Generated, not hand-written. Regenerate after any schema or model change:

```
python docs/schema/generators/audit_models.py     # the raw findings (AUDIT_DB=minty_cleanse, AUDIT_SCHEMA=pettycashv3 by default)
python docs/schema/generators/mkdoc.py            # this document
```

It compares every model in **Minty** (SQLAlchemy), **billing-backend** and
**onboarding-backend** (Django) against the schema `01_schema_rebased.sql` builds, and
reports three things: a model whose table no longer exists under that name, a model
column the schema does not have, and a declared type that no longer matches the column.

Paths are relative to each repo root — `c:\dev\Minty`, `c:\dev\billing-backend`,
`c:\dev\onboarding-backend`.

**0 findings: 0 table, 0 column, 0 type.**

Zero is the closed state of Part 1 phase C (`docs/modernisation/modernisation_plan.md`),
reached 2026-09-17 and held by `tests/test_zz_schema_audit.py`, which runs this audit
against the harness's fresh build of `01` on every Postgres test run. A finding here
again means a model was edited without the schema, or the schema without the model.

---

## 0. How the 287 findings were closed

The count at the start of phase C, measured against `minty_cleanse` (production data on
the new schema): **Minty 157, billing-backend 65, onboarding-backend 71**. The schema was
authoritative throughout — where code and schema disagreed, the code changed — and each
unit's gate was zero findings on its tables in all three repos. The running totals:

| unit | tables | Minty | billing-backend | onboarding-backend |
|---|---|---|---|---|
| start (2026-09-16) | | 157 | 65 | 71 |
| **C1** identity | `user`, `user_token`, `user_entity`, `email_otp` | 139 | 56 | 64 |
| **C2** entities and modules | `entities`, `entity_function`, `entity_function_map`, `country_info`, `currency_info` | 121 | 43 | 43 |
| **C3** sales catalogue | `sale_info`, `entity_sale_setting` | 105 | 43 | 27 |
| **C4** report core | `report`, `report_sale`, `report_expense`, `report_expense_attachment`, `attachment`, `report_cash_count`, `report_history`, `entity_cash_detail`, `entity_cash_setting`, `entity_pettycash_settings`, `cash_info`, `share_link` | 50 | 43 | 2 |
| **C5** Xero sync | `account_info`, `entity_account_xero`, `xero_contact_sync`, `xero_report_sync`, `xero_bank_transaction`, `xero_bank_transfer` | 26 | 39 | 2 |
| **C6** access | `role`, `permission`, `role_permission`, `invitation`, `terms_consent` | 21 | 39 | 1 |
| **C7** subscription and billing (Minty side) | the 13 `billing_*` / `subscription_*` / `entity_module_subscription` / `payer_billing_group` tables | **0** | 39 | **0** |
| **C8** billing-backend | `bill`, `bill_line`, `bill_audit`, `payment`, the attachment links, `xero_bill_*`, `entity_bill_*` | 0 | **0** | 0 |
| **C9** onboarding-backend | the mirrors, re-checked | 0 | 0 | 0 |
| **C10** close-out | audit 0 against the harness build and `minty_cleanse`; Minty 1674 passed on Postgres | 0 | 0 | 0 |

What each unit changed, decision by decision, is recorded in the unit's close-out in the
plan document; the vocabulary the code now writes (the enum words) is item 18 of the
decision register in `01_schema_rebased.sql`'s header. The three copies of that vocabulary
— `blueprints/shared/enums.py`, the two `shared_models/enums.py` — are checked against `01`
by `tests/test_enums_match_schema.py`.

Two findings the original audit could not see, both closed: **D6** `user.system_role` was
commented out in the schema (uncommented in phase A, enum `normal / admin / superadmin`,
the JWT claim `superuser` → `superadmin` across all three repos in C1); and
`entity_function_map.created_by` was written as an actor *label* where the schema has a
uuid FK to `user` (C2: `_write_pairs(..., user_id)` — the person, or NULL for a job).

---

## 1. Renamed tables — 0

None. The nine renames (`roles/permissions/role_permissions → role/permission/role_permission`,
`invitations → invitation`, `report_sale_detail → report_sale`, `shop_expense → report_expense`,
`entity_cash_detail_v2 → entity_cash_detail`, `audit → bill_audit`, `bill_line_item → bill_line`)
landed in C4, C6 and C8.

---

## 2. Model columns the schema does not have — 0

None.

---

## 3. Declared types that no longer match — 0

None. Every id is `MintyUuid` / `UUIDField`, every money column `Money()` /
`DecimalField(14, 2)`, every stamp `DateTime(timezone=True)` / `db_default=Now()`,
every enum a `pg_enum(...)` / `PgEnumField` over the shared vocabulary
(`blueprints/shared/column_types.py`, the two `shared_models/fields.py`).

---

## 4. What is deliberately NOT a finding

- **`Money()` reads back as `float`** (`asdecimal=False`). The database column is exact
  `numeric(14,2)`; the in-process arithmetic still runs in float in a few hundred places,
  and moving it to `Decimal` is a separate pass. `cents()` rounds every computed amount
  before it is written, and `tests/test_char_money.py` pins the stored values.
- **Behaviour the schema reversed** — the audit trail no longer survives a report's
  deletion (FK cascade), `entity_status` means the Xero connection state, `sale_info` is
  one global catalogue — is recorded per unit in the plan document, with the tests that
  were rewritten to the new meaning.
- **Alembic is frozen.** A schema change is an edit to `01_schema_rebased.sql` (ask first)
  plus `gen.py`, then `minty_cleanse` is rebuilt with `rehearse.py`; `Minty/migrations/` is
  deleted at the cutover (phase E) and `billing-backend/bills/migrations/` is already gone.

