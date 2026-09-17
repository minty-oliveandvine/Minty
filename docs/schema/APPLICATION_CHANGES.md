# Application changes required by `pettycash_test`

Generated, not hand-written. Regenerate after any schema or model change:

```
python docs/schema/generators/audit_models.py     # the raw findings
python docs/schema/generators/mkdoc.py            # this document
.venv/Scripts/python.exe docs/schema/generators/mkdocx.py   # the .docx beside it
```

It compares every model in **Minty** (SQLAlchemy) and **billing-backend** (Django)
against the schema `01_schema_rebased.sql` builds, and reports three things: a
model whose table no longer exists under that name, a model column the schema
does not have, and a declared type that no longer matches the column.

Paths are relative to each repo root — `c:\dev\Minty` and `c:\dev\billing-backend`.

**217 findings: 9 table, 64 column, 144 type.**

> The audit reads source with `utf-8-sig`. Several of these files carry a BOM,
> and an earlier version used `utf-8`, so `ast.parse` raised and the file was
> skipped silently — which hid the entire `User` model and 57 other findings.
> The script now reports any file it cannot parse instead of skipping quietly.

---

## 0. Six open decisions — the code side

The schema files carry these as **D1–D6** (`DECISIONS REQUIRED AT REVIEW` in
`01_schema_rebased.sql`, and again beside the statement each one lands on in `02`/`03`).
This is what each costs *here*, in the application.

The enums were widened so the merge would be lossless. The consequence is that where the
merged data and the code disagree, **the database accepts both and nothing raises** — the
feature just returns nothing. None of these is a crash; all of them are silent.

| | column | if the DATA wins (map on the way in) | if the CODE wins (change these) |
|---|---|---|---|
| **D3** | `report.status` — 3,724 rows say `published`, code says `posted` | one mapping in `03` | [ending.py:483](blueprints/report/services/ending.py#L483), [:1568](blueprints/report/services/ending.py#L1568), [history_query.py:90](blueprints/report/services/history_query.py#L90), [:111](blueprints/report/services/history_query.py#L111), [report.py:51](blueprints/report/models/report.py#L51) |
| **D4** | `sale_info.type` — data `electric`/`delivery`, code `Electronic`/`Delivery` | one mapping in `03` | **46 Python sites** — [onboarding_state.py:166](blueprints/entity/services/onboarding_state.py#L166), [:172-173](blueprints/entity/services/onboarding_state.py#L172-L173), [payment_methods.py:89](blueprints/entity/services/payment_methods.py#L89), [:209](blueprints/entity/services/payment_methods.py#L209), [:268](blueprints/entity/services/payment_methods.py#L268), [sale_info.py:109](blueprints/entity/models/sale_info.py#L109) — **plus five** `electronic_delivery_*` templates |
| **D5** | `invitation.status` — 40 rows say `revoked`, code writes `cancelled` | one mapping in `02` | one site |

**D1** and **D2** have no code side. They are data already lost upstream, in the schema-2
build, before `02`/`03` read it — 460 `report.discrepancy_type` rows flattened to `none`,
and 9 entities folded into `onboarding`. Recovering them means fixing that build; leaving
them means the code keeps writing values the migrated data never shows.

D4 is the one to look at twice. `electric` is a misspelling of *electronic*, so letting the
data win writes a typo permanently into 46 call sites and five templates.

---

## D6 — fix the schema, not the code

One finding is the schema's fault and should not be worked around in the app.

### `user.system_role` does not exist

`01_schema_rebased.sql` declares the enum —
`CREATE TYPE pettycash_test.system_role AS ENUM ('normal','admin','superadmin')` —
but **the column is commented out** in the `user` table, at both the live
definition and the dead `/* */` block above it. No column anywhere uses that type.

It was commented out in the original `01_schema 2.sql`, with no reason given, and
the rebase inherited it. The application depends on it:

| | |
|---|---|
| declared | [blueprints/auth/models/user.py:41](blueprints/auth/models/user.py#L41) |
| gates superuser at login | [blueprints/auth/routes/login.py:31](blueprints/auth/routes/login.py#L31), [blueprints/auth/routes/email_auth.py:48](blueprints/auth/routes/email_auth.py#L48) |
| written | [blueprints/invitation/services/invite.py:82](blueprints/invitation/services/invite.py#L82) |
| read | [blueprints/user_management/routes/admin_dashboard.py:38](blueprints/user_management/routes/admin_dashboard.py#L38), [blueprints/legal/routes/accept.py:134](blueprints/legal/routes/accept.py#L134) |
| mirrored in billing-backend | [shared_models/models.py:13](shared_models/models.py#L13) |

There is nowhere else to put a global superuser flag — `user_entity.role` is
per-entity and `role` is a different concept. Uncommenting the column is the fix;
the enum is already there and already correct. Until then the superuser gate has
no backing store.

---

## 1. Renamed tables — 9

`__tablename__` / `db_table` no longer resolves. Nothing on these models works.

| repo | old | new | declared at |
|---|---|---|---|
| Minty | `entity_cash_detail_v2` | `entity_cash_detail` | [blueprints/entity/models/entity_cash_detail_v2.py:4](blueprints/entity/models/entity_cash_detail_v2.py#L4) |
| Minty | `invitations` | `invitation` | [blueprints/invitation/models/invitation.py:6](blueprints/invitation/models/invitation.py#L6) |
| Minty | `permissions` | `permission` | [blueprints/user_management/models/permissions.py:7](blueprints/user_management/models/permissions.py#L7) |
| Minty | `report_sale_detail` | `report_sale` | [blueprints/report/models/report_sale_detail.py:6](blueprints/report/models/report_sale_detail.py#L6) |
| Minty | `role_permissions` | `role_permission` | [blueprints/user_management/models/role_permissions.py:7](blueprints/user_management/models/role_permissions.py#L7) |
| Minty | `roles` | `role` | [blueprints/user_management/models/roles.py:7](blueprints/user_management/models/roles.py#L7) |
| Minty | `shop_expense` | `report_expense` | [blueprints/report/models/shop_expense.py:6](blueprints/report/models/shop_expense.py#L6) |
| billing-backend | `audit` | `bill_audit` | [bills/models.py:97](bills/models.py#L97) |
| billing-backend | `bill_line_item` | `bill_line` | [bills/models.py:65](bills/models.py#L65) |

The class names follow the table where it reads oddly otherwise —
`ShopExpense` becomes report_expense, `ReportSaleDetail` becomes report_sale.
Both are more than renames: check the column lists in section 2 before assuming
a one-line change.

---

## 2. Model columns the schema does not have — 64

**These break every SELECT on the model**, not just writes: an ORM selects all
mapped columns, so one stale attribute takes the whole table down. Fix these first.

#### `user` — blueprints/auth/models/user.py (Minty)

- `xero_entity_id` — line 40
- `system_role` — line 41
- `xero_token` — line 51
- `access_token` — line 52
- `refresh_token` — line 53
- `id_token` — line 54
- `expires_in` — line 55
- `token_created_at` — line 56
- `current_entity_id` — line 82

#### `cash_info` — blueprints/entity/models/cash_info.py (Minty)

- `cash_id` — line 20
- `country_code` — line 25
- `desc` — line 33

#### `entities` — blueprints/entity/models/entity.py (Minty)

- `minimum_qty` — line 19
- `deposit_frequency` — line 20
- `deposit_day` — line 21
- `xero_short_code` — line 29
- `period_lock_date` — line 52
- `end_of_year_lock_date` — line 53

#### `entity_function_map` — blueprints/entity/models/entity_function.py (Minty)

- `id` — line 27

#### `entity_sale_setting` — blueprints/entity/models/entity_sale_setting.py (Minty)

- `type` — line 12
- `sale_name` — line 13
- `value_name` — line 14
- `sale_info_id` — line 19
- `create_date` — line 25
- `updated_at` — line 26
- `enabled` — line 30

#### `sale_info` — blueprints/entity/models/sale_info.py (Minty)

- `entity_id` — line 37
- `code` — line 42
- `name` — line 43
- `legacy_column` — line 46
- `is_active` — line 47

#### `user_entity` — blueprints/entity/models/user_entity.py (Minty)

- `create_at` — line 21

#### `report` — blueprints/report/models/report.py (Minty)

- `date` — line 14
- `cash_sales` — line 18
- `shop_sales` — line 19
- `delivery_sales` — line 20
- `expenses` — line 25
- `receipt_files` — line 30
- `uploaded_by` — line 31
- `company` — line 34
- `xero_integrated_yes` — line 39
- `withdrawal_type` — line 58
- `withdrawal_bank_account` — line 59
- `actual_cash_total` — line 62

#### `report_history` — blueprints/report/models/report_history.py (Minty)

- `company` — line 15
- `timestamp` — line 23

#### `xero_bank_transaction` — blueprints/xero/models/xero_bank_transaction.py (Minty)

- `create_at` — line 25

#### `xero_report_sync` — blueprints/xero/models/xero_report_sync.py (Minty)

- `sync_statuc` — line 22
- `xero_reponse_text` — line 25

#### `bill` — bills/models.py (billing-backend)

- `xero_contact_id` — line 30
- `currency_code` — line 41
- `uploaded_by` — line 48

#### `payment` — bills/models.py (billing-backend)

- `currency_code` — line 157

#### `entity_function_map` — bills/models.py (billing-backend)

- `id` — line 335

#### `user` — shared_models/models.py (billing-backend)

- `system_role` — line 13
- `access_token` — line 15
- `refresh_token` — line 16
- `id_token` — line 17
- `expires_in` — line 18
- `token_created_at` — line 19
- `xero_entity_id` — line 21

#### `entities` — shared_models/models.py (billing-backend)

- `xero_short_code` — line 48
- `period_lock_date` — line 52
- `end_of_year_lock_date` — line 53

---

## 3. Declared types that no longer match — 144

| schema type | count | what the models declare |
|---|---|---|
| `uuid` | 102 | `db.String(36)` / `models.CharField(max_length=36)` |
| `numeric` | 14 | `db.Float` — money, so this one is a correctness fix, not cosmetic |
| enums | 17 | `db.String` / `models.CharField(choices=...)` |
| `timestamp with time zone` | 4 | `db.DateTime` with no `timezone=True` |
| other | 7 | `character`, `smallint`, `jsonb`, `date` |

None of these stops the app the way section 2 does — Postgres casts a great deal
on the way in. They matter for a different reason:

- **`uuid` vs `String(36)`** — comparisons still work, but an index on a uuid
  column is not used the same way when the parameter arrives as text, and a
  malformed value fails at the database rather than in validation.
- **`numeric` vs `Float`** — this one is a real bug. Binary floating point cannot
  represent money exactly; the schema moved to `numeric` deliberately and a model
  still declaring `Float` reintroduces the rounding the change was meant to remove.
- **enum vs `String`** — the database now rejects a value outside the enum. That is
  the point, but it turns a silent bad write into a 500, so it wants testing.
- **`DateTime` without `timezone=True`** — the column is `timestamptz`; a naive
  datetime is normalised to the *session* timezone, not to UTC.

Full list, grouped by file:

<details><summary><code>blueprints/auth/models/email_otp.py</code> (Minty) — 1</summary>

- line 11: id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/auth/models/user.py</code> (Minty) — 2</summary>

- line 27: id -> declared String, schema is uuid
- line 46: reset_token_expiry -> declared DateTime, schema is timestamp with time zone

</details>

<details><summary><code>blueprints/auth/models/user_token.py</code> (Minty) — 2</summary>

- line 17: id -> declared String, schema is uuid
- line 18: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/cash_info.py</code> (Minty) — 1</summary>

- line 29: type -> declared String, schema is cash_type

</details>

<details><summary><code>blueprints/entity/models/currency_info.py</code> (Minty) — 1</summary>

- line 23: decimal_places -> declared Integer, schema is smallint

</details>

<details><summary><code>blueprints/entity/models/entity.py</code> (Minty) — 4</summary>

- line 11: id -> declared String, schema is uuid
- line 33: status -> declared String, schema is entity_status
- line 47: last_accessed_by_user_id -> declared String, schema is uuid
- line 62: connected_by_user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/entity_cash_setting.py</code> (Minty) — 2</summary>

- line 15: entity_id -> declared String, schema is uuid
- line 20: cash_id -> declared Integer, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/entity_function.py</code> (Minty) — 5</summary>

- line 10: id -> declared String, schema is uuid
- line 28: entity_id -> declared String, schema is uuid
- line 29: entity_function_id -> declared String, schema is uuid
- line 33: settings_json -> declared JSON, schema is jsonb
- line 34: created_by -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/entity_pettycash_settings.py</code> (Minty) — 10</summary>

- line 8: entity_id -> declared String, schema is uuid
- line 14: pettycash_account_id -> declared String, schema is uuid
- line 19: bank_account_id -> declared String, schema is uuid
- line 24: cash_sale_account_id -> declared String, schema is uuid
- line 29: discrepancy_bank_account_id -> declared String, schema is uuid
- line 34: discrepancy_account_id -> declared String, schema is uuid
- line 39: director_account_id -> declared String, schema is uuid
- line 45: cash_sale_contact_id -> declared String, schema is uuid
- line 50: director_contact_id -> declared String, schema is uuid
- line 55: discrepancy_contact_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/entity_sale_setting.py</code> (Minty) — 2</summary>

- line 10: sale_id -> declared String, schema is uuid
- line 11: entity_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/entity/models/sale_info.py</code> (Minty) — 2</summary>

- line 36: id -> declared String, schema is uuid
- line 45: type -> declared String, schema is sale_type

</details>

<details><summary><code>blueprints/entity/models/user_entity.py</code> (Minty) — 3</summary>

- line 9: user_id -> declared String, schema is uuid
- line 15: entity_id -> declared String, schema is uuid
- line 20: role -> declared String, schema is entity_role

</details>

<details><summary><code>blueprints/legal/models/terms_consent.py</code> (Minty) — 1</summary>

- line 60: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/report/models/report.py</code> (Minty) — 13</summary>

- line 11: id -> declared String, schema is uuid
- line 15: opening_balance -> declared Float, schema is numeric
- line 16: cash_addition -> declared Float, schema is numeric
- line 17: adjusted_opening_balance -> declared Float, schema is numeric
- line 21: total_sales -> declared Float, schema is numeric
- line 26: bank_deposit -> declared Float, schema is numeric
- line 29: closing_balance -> declared Float, schema is numeric
- line 40: safe_box_balance -> declared Float, schema is numeric
- line 41: discrepancy_amount -> declared Float, schema is numeric
- line 43: discrepancy_type -> declared String, schema is discrepancy_type
- line 44: publishing_status -> declared String, schema is publish_status
- line 53: status -> declared String, schema is report_status
- line 55: completed_sections -> declared JSON, schema is jsonb

</details>

<details><summary><code>blueprints/report/models/report_cash_count.py</code> (Minty) — 3</summary>

- line 20: id -> declared String, schema is uuid
- line 25: report_id -> declared String, schema is uuid
- line 30: cash_id -> declared Integer, schema is uuid

</details>

<details><summary><code>blueprints/report/models/report_history.py</code> (Minty) — 3</summary>

- line 9: id -> declared Integer, schema is uuid
- line 10: report_id -> declared String, schema is uuid
- line 16: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/report/models/share_link.py</code> (Minty) — 3</summary>

- line 9: id -> declared String, schema is uuid
- line 12: entity_id -> declared String, schema is uuid
- line 13: transaction_date -> declared String, schema is date

</details>

<details><summary><code>blueprints/subscription/models/entity_billing_consent.py</code> (Minty) — 2</summary>

- line 49: entity_id -> declared String, schema is uuid
- line 56: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/entity_billing_group.py</code> (Minty) — 2</summary>

- line 50: entity_id -> declared String, schema is uuid
- line 56: payer_user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/entity_module_subscription.py</code> (Minty) — 2</summary>

- line 38: entity_id -> declared String, schema is uuid
- line 45: payer_user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/payer_billing_group.py</code> (Minty) — 1</summary>

- line 66: payer_user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/subscription_audit_log.py</code> (Minty) — 5</summary>

- line 28: entity_id -> declared String, schema is uuid
- line 32: payer_user_id -> declared String, schema is uuid
- line 35: actor_user_id -> declared String, schema is uuid
- line 53: payer_before -> declared String, schema is uuid
- line 54: payer_after -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/subscription_email_log.py</code> (Minty) — 1</summary>

- line 42: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/subscription_invoice.py</code> (Minty) — 2</summary>

- line 44: payer_user_id -> declared String, schema is uuid
- line 133: entity_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/subscription_transfer.py</code> (Minty) — 3</summary>

- line 72: entity_id -> declared String, schema is uuid
- line 81: from_user_id -> declared String, schema is uuid
- line 82: to_user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/subscription/models/user_stripe_customer.py</code> (Minty) — 1</summary>

- line 24: user_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/xero/models/account_info.py</code> (Minty) — 2</summary>

- line 16: id -> declared String, schema is uuid
- line 17: entity_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/xero/models/entity_account_xero.py</code> (Minty) — 2</summary>

- line 9: id -> declared String, schema is uuid
- line 10: account_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/xero/models/xero_bank_transaction.py</code> (Minty) — 7</summary>

- line 9: id -> declared String, schema is uuid
- line 10: sync_report_id -> declared String, schema is uuid
- line 14: unit_amount -> declared Float, schema is numeric
- line 15: quantity -> declared Float, schema is numeric
- line 21: subtotal -> declared Float, schema is numeric
- line 22: total_tax -> declared Float, schema is numeric
- line 23: total -> declared Float, schema is numeric

</details>

<details><summary><code>blueprints/xero/models/xero_bank_transfer.py</code> (Minty) — 4</summary>

- line 9: id -> declared String, schema is uuid
- line 14: sync_report_id -> declared String, schema is uuid
- line 21: amount -> declared Float, schema is numeric
- line 22: transfer_date -> declared DateTime, schema is timestamp with time zone

</details>

<details><summary><code>blueprints/xero/models/xero_contact_sync.py</code> (Minty) — 2</summary>

- line 9: id -> declared String, schema is uuid
- line 10: entity_id -> declared String, schema is uuid

</details>

<details><summary><code>blueprints/xero/models/xero_report_sync.py</code> (Minty) — 4</summary>

- line 9: id -> declared String, schema is uuid
- line 17: report_id -> declared String, schema is uuid
- line 23: reported_at -> declared DateTime, schema is timestamp with time zone
- line 24: completed_at -> declared DateTime, schema is timestamp with time zone

</details>

<details><summary><code>bills/models.py</code> (billing-backend) — 33</summary>

- line 27: id -> declared CharField, schema is uuid
- line 28: entity_id -> declared CharField, schema is uuid
- line 31: status -> declared CharField, schema is bill_status
- line 42: published -> declared CharField, schema is publish_state
- line 149: id -> declared CharField, schema is uuid
- line 159: payment_status -> declared CharField, schema is payment_status
- line 167: created_by -> declared CharField, schema is uuid
- line 185: id -> declared CharField, schema is uuid
- line 194: uploaded_by -> declared CharField, schema is uuid
- line 220: id -> declared CharField, schema is uuid
- line 231: attachment_role -> declared CharField, schema is bill_attachment_role
- line 250: created_by -> declared CharField, schema is uuid
- line 273: id -> declared CharField, schema is uuid
- line 284: attachment_role -> declared CharField, schema is payment_attachment_role
- line 297: created_by -> declared CharField, schema is uuid
- line 314: id -> declared CharField, schema is uuid
- line 336: entity_id -> declared CharField, schema is uuid
- line 346: created_by -> declared CharField, schema is uuid
- line 363: id -> declared CharField, schema is uuid
- line 364: entity_id -> declared CharField, schema is uuid
- line 373: created_by -> declared CharField, schema is uuid
- line 393: currency_code -> declared CharField, schema is character
- line 396: decimal_places -> declared IntegerField, schema is smallint
- line 415: id -> declared CharField, schema is uuid
- line 416: entity_id -> declared CharField, schema is uuid
- line 425: created_by -> declared CharField, schema is uuid
- line 458: id -> declared CharField, schema is uuid
- line 464: sync_direction -> declared CharField, schema is sync_direction
- line 469: sync_status -> declared CharField, schema is sync_status
- line 512: requested_by -> declared CharField, schema is uuid
- line 532: id -> declared CharField, schema is uuid
- line 576: id -> declared CharField, schema is uuid
- line 602: id -> declared CharField, schema is uuid

</details>

<details><summary><code>shared_models/models.py</code> (billing-backend) — 13</summary>

- line 7: id -> declared CharField, schema is uuid
- line 40: id -> declared CharField, schema is uuid
- line 45: country_code -> declared CharField, schema is character
- line 49: status -> declared CharField, schema is entity_status
- line 75: role -> declared CharField, schema is entity_role
- line 95: id -> declared CharField, schema is uuid
- line 96: entity_id -> declared CharField, schema is uuid
- line 98: payer_user_id -> declared CharField, schema is uuid
- line 99: phase -> declared CharField, schema is subscription_phase
- line 117: id -> declared CharField, schema is uuid
- line 118: entity_id -> declared CharField, schema is uuid
- line 135: id -> declared CharField, schema is uuid
- line 136: entity_id -> declared CharField, schema is uuid

</details>

---

## 4. Behavioural change: `entity_function_map.created_by`

Not a type mismatch — the audit passes it, because the model and the schema now
disagree about *meaning* rather than about type. Recorded as item 10 of the
decision register in `01_schema_rebased.sql`.

The column is a foreign key to `user`. The code writes an actor **label**:

| | |
|---|---|
| the only write site | [blueprints/entity/services/modules.py:534](blueprints/entity/services/modules.py#L534), inside `_write_pairs` at [:497](blueprints/entity/services/modules.py#L497) |
| the labels | [blueprints/entity/services/modules.py:60-62](blueprints/entity/services/modules.py#L60-L62) — `onboarding`, `cli`, `entity_create` |
| callers | [blueprints/entity/routes/create.py:1169](blueprints/entity/routes/create.py#L1169), [blueprints/entity/services/modules.py:393](blueprints/entity/services/modules.py#L393), [blueprints/entity/routes/settings.py:1921](blueprints/entity/routes/settings.py#L1921) (`"subscription"`) |
| model | [blueprints/entity/models/entity_function.py:34](blueprints/entity/models/entity_function.py#L34) — `String(36)`, no ForeignKey |
| tests | `tests/test_module_access_gate.py:86`, `tests/test_onboarding_module_state.py:77` |

`_write_pairs` needs a user id parameter. Two of the four callers — `cli` and
`subscription` — are jobs with no user, so their rows land `NULL` and the four
paths stop being distinguishable. A nullable `actor VARCHAR(20)` beside the column
keeps that provenance if it is wanted; not assumed here.

---

## Order to do this in

0. **Settle D1–D5** (section 0). Two of them change what the data says, so anything
   built against the current values may be built against the wrong ones.
1. **Uncomment `user.system_role`** — D6, its own section above. A schema edit, and
   everything else is easier once the schema is settled.
2. **Section 2, the missing columns.** Nothing can be tested until an ORM query
   against these tables runs at all.
3. **Section 1, the renames.** Mechanical once the columns are right.
4. **Section 3's `numeric` rows.** The money bug is the only type finding that is
   wrong rather than merely untidy.
5. **Section 4**, whenever — the column accepts `NULL`, so nothing breaks meanwhile.
6. The rest of section 3 as tidy-up.

