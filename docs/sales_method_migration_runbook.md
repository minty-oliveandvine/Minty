# Sales Method Migration — Deployment Runbook

**Goal:** adding a new sales method becomes a single `INSERT` into
`pettycashv2.sales_method` — no schema change, no code change.

**Status:** SQL written, not yet run. No code changed yet.

This runbook is self-contained. You should not need any prior context to follow it.

---

## Files

| File | Purpose |
|---|---|
| `migrations/s1a01_s4a04_sales_method_catalog.sql` | The Supabase script (steps 1–3.5 + checks) |
| `migrations/versions/s1a01_create_sales_method_catalog.py` | Alembic equivalent — step 1 |
| `migrations/versions/s2a02_link_sale_info_to_sales_method.py` | Alembic equivalent — step 2 |
| `migrations/versions/s3a03_link_report_sale_detail.py` | Alembic equivalent — step 3 |
| `migrations/versions/s4a04_backfill_sales_columns_to_detail.py` | Alembic equivalent — step 3.5 |

**Run the `.sql` OR the `.py` migrations — never both.** The guards make a
double-run harmless, but `alembic_version` would not record the SQL path.

---

## Background you need

Three things that are easy to get wrong later:

1. **`report_sale_detail` already exists and already works.** It stores one row
   per (report, method, amount). `ending.py` already reads sales *only* from it
   ("Use ONLY amounts from ReportSaleDetail — no fallback to Report model",
   `blueprints/report/services/ending.py:591`). This migration is *finishing* a
   half-done refactor, not starting one.

2. **A report and its draft share one id.** `ending.py:445` creates the revert
   draft with `id=full_report.id`. So one set of detail rows serves both. Do not
   add `report_draft_id` to `report_sale_detail` — it would double every sum.

3. **Four columns survive.** `cash_sales` (separate concept), and
   `shop_sales` / `delivery_sales` / `total_sales` (aggregates, not methods).
   Only the **11 method columns** get dropped.

---

## STEP 1 — Run the SQL

**Risk:** low. Purely additive. No code changes needed. App keeps working.

1. Open Supabase → SQL Editor → **confirm you are on the right project**.
2. Paste all of `migrations/s1a01_s4a04_sales_method_catalog.sql`.
3. Run. It is wrapped in `BEGIN`/`COMMIT` — if anything fails, nothing applies.
4. Run the post-run checks at the bottom of that file (A, B, C, D).

**What it does:**
- creates `pettycashv2.sales_method`, seeds 11 global rows
- adds `sale_info.sales_method_id` (nullable FK) + backfills it
- adds `report_sale_detail.sales_method_id` (nullable FK) + backfills it
- **backfills the 11 columns from `report` + `report_draft` into detail rows**

**Expected check results:**

| Check | Expected | If not |
|---|---|---|
| A — catalog seeded | 11 global + N custom | re-run; `ON CONFLICT` makes it safe |
| B — unlinked `sale_info` | **0** | investigate before continuing |
| C — unlinked detail rows | 0, or small | non-zero = `sale_info` row was hard-deleted **before** this ran. Pre-existing loss, not caused by this |
| D — column vs detail mismatch | **0 rows** | **STOP.** See Step 4 |

> The backfill only touches reports with **no** detail rows at all. Reports that
> already have some are skipped entirely — mixing sources per-method is how you
> get half-doubled totals.

**Rollback:** commented block at the bottom of the SQL file. Only removes
backfill artefacts (rows with `sales_method_id` but no `sale_id` — the app never
creates those).

---

## STEP 2 — Set the FK on the 7 insert sites

**Risk:** low. **Do this soon after Step 1** — until it's done, every new row
gets a NULL FK and check B silently climbs from 0.

Each site must resolve the catalog row and set `sales_method_id`.

### `sale_info` inserts (4)

| File | Line | Function |
|---|---|---|
| `blueprints/entity/services/shared.py` | ~184 | `create_default_entity_settings` (electronic) |
| `blueprints/entity/services/shared.py` | ~197 | `create_default_entity_settings` (delivery) |
| `blueprints/entity/services/payment_methods.py` | ~154 | `add_payment_method` |
| `blueprints/entity/services/payment_methods.py` | ~314 | `replace_sales_methods` |

For `replace_sales_methods`: a user-typed name that matches no catalog row must
**mint a custom row** (`entity_id` set, `legacy_column` NULL, `code` prefixed
`CUSTOM_`) — same shape the SQL used for the backfill. Otherwise custom methods
regress to NULL FKs.

### `report_sale_detail` inserts (3)

| File | Lines |
|---|---|
| `blueprints/report/routes/sales.py` | ~534, ~738, ~905 |

Set `sales_method_id` from the `SaleInfo` row already in scope
(`sale.sales_method_id`).

**Verify:** re-run checks B and C — both should still be 0 after exercising
onboarding and the settings page.

---

## STEP 3 — Rewrite the 5 hardcoded sites to loop

**Risk:** medium. This is the actual work, and what buys the "one INSERT" goal.
Until it's done, adding a catalog row still won't surface a new method anywhere.

| File | Line | What's hardcoded |
|---|---|---|
| `blueprints/report/services/shared.py` | ~566 | `recalculate_report` sums 8 named columns |
| `blueprints/report/routes/create.py` | ~152 | 15 explicit kwargs on `Report(...)` at submit |
| `blueprints/report/routes/sales.py` | ~344, ~590 | one assignment per method |
| `blueprints/report/routes/report_detail.py` | ~231 | one assignment per method |
| `templates/index.html` + `templates/edit_report.html` | 11 rows each | hardcoded per-method markup |

Suggested order — each is independently shippable:

1. **`recalculate_report`** — replace the 8-column sum with a sum over detail
   rows grouped by `type`, plus `cash_sales`. Keep writing `shop_sales`,
   `delivery_sales`, `total_sales` (they stay as cached columns).
2. **Templates** — add a `sales_by_method` property to `Report` / `ReportDraft`
   returning `{code: amount}` from detail rows, then loop in the template.
   Do this *before* dropping columns so the swap happens once.
3. **`sales.py` / `report_detail.py` writes** — loop over the entity's catalog
   methods instead of naming each.
4. **`create.py` submit** — copy the draft's detail rows to the report instead
   of passing 15 kwargs.

### Known bug to fix here

`blueprints/report/routes/create.py:148` mints a **fresh uuid** for `Report` at
first submit, while the draft (and its detail rows) keep the draft's id. So a
first-time submitted report's detail rows stay keyed to the draft.

**Fix:** create `Report` with `id=draft.id`, matching what `ending.py:445`
already does in the reverse direction. Check for id collisions first:

```sql
SELECT count(*) FROM pettycashv2.report r
JOIN pettycashv2.report_draft d ON d.id = r.id;
```

---

## STEP 4 — Verify check D returns zero

**This is the gate. Do not skip it.**

Run check D from the bottom of the SQL file. It compares each report's column
sum against its detail-row sum.

- **Zero rows → safe to proceed.**
- **Any rows → STOP.** Those reports' two stores disagree. Investigate *while
  the columns still exist* — after Step 5 they are gone and you cannot compare.

Let this sit through **at least one deploy cycle with real traffic** before
Step 5. Steps 1–3 are reversible; Step 5 is not.

---

## STEP 5 — Drop the columns

**Risk:** HIGH — irreversible. A down-migration recreates the column but not its
data. Take a database backup first.

Preconditions, all required:

- [ ] Check D returns zero rows
- [ ] Step 3 complete — nothing reads the 11 columns
- [ ] Ran in production for at least one deploy cycle
- [ ] Backup taken

```sql
BEGIN;

ALTER TABLE pettycashv2.report
    DROP COLUMN visa_sales,      DROP COLUMN alipay_sales,
    DROP COLUMN wechat_sales,    DROP COLUMN master_sales,
    DROP COLUMN unionpay_sales,  DROP COLUMN amex_sales,
    DROP COLUMN octopus_sales,   DROP COLUMN foodpanda_sales,
    DROP COLUMN keeta_sales,     DROP COLUMN openrice_sales,
    DROP COLUMN deliveroo_sales;

ALTER TABLE pettycashv2.report_draft
    DROP COLUMN visa_sales,      DROP COLUMN alipay_sales,
    DROP COLUMN wechat_sales,    DROP COLUMN master_sales,
    DROP COLUMN unionpay_sales,  DROP COLUMN amex_sales,
    DROP COLUMN octopus_sales,   DROP COLUMN foodpanda_sales,
    DROP COLUMN keeta_sales,     DROP COLUMN openrice_sales,
    DROP COLUMN deliveroo_sales;

-- Transition bridges, no longer needed once nothing maps to physical columns.
ALTER TABLE pettycashv2.sales_method DROP COLUMN legacy_column;
ALTER TABLE pettycashv2.sale_info    DROP COLUMN value_name;
ALTER TABLE pettycashv2.sale_info    DROP COLUMN type;

COMMIT;
```

**KEEP** on `report` / `report_draft`: `cash_sales`, `shop_sales`,
`delivery_sales`, `total_sales`.

**KEEP** on `sale_info`: `sale_id` (it is the PRIMARY KEY, and
`report_sale_detail.sale_id` is a FK pointing at it) and `sale_name` (entities
rename methods for themselves).

Also remove the 11 column definitions from `blueprints/report/models/report.py`
and `blueprints/report/models/report_draft.py`.

Optionally make the FKs `NOT NULL` once Step 2 guarantees they are always set.

---

## After: adding a new sales method

```sql
INSERT INTO pettycashv2.sales_method
    (id, entity_id, code, name, type, legacy_column, is_active, display_order, created_at, updated_at)
VALUES
    (gen_random_uuid()::text, NULL, 'TAPNGO', 'Tap & Go', 'Electronic', NULL, TRUE, 8, NOW(), NOW());
```

That's it. No migration, no code change, no deploy.

---

## Open item

The repo has **5 divergent Alembic heads** (pre-existing, not caused by this
work). `alembic upgrade head` will fail until they are merged. The new `.py`
migrations chain off `c2e4a6b8d0f1`. Using the Supabase `.sql` path sidesteps
this, but the fork should be resolved regardless.
