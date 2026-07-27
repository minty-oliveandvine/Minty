# Cash Denomination Migration — Deployment Runbook

**Goal:** adding a cash denomination becomes a single `INSERT` into
`pettycashv2.cash_info` — no schema change, no code change. Entities choose
which denominations they log.

**Status:** SQL written, not yet run. Models + service layer written. Routes,
template and settings API not yet changed.

This runbook is self-contained. You should not need any prior context to follow it.

Companion to `docs/sales_method_migration_runbook.md` — same structure, same
discipline. The two are **independent**; neither blocks the other.

---

## Files

| File | Purpose | Written? |
|---|---|---|
| `migrations/d1a01_d3a03_cash_denomination_catalog.sql` | The Supabase script (steps 1–3 + checks) | ✅ |
| `migrations/versions/d1a01_cash_denomination_catalog.py` | Alembic equivalent — step 1 | ✅ |
| `migrations/versions/d2a02_cash_count_detail_and_entity_denominations.py` | Alembic equivalent — step 2 | ✅ |
| `blueprints/entity/models/cash_info.py` | Updated model (char(2), display_order, is_active) | ✅ |
| `blueprints/entity/models/entity_cash_denomination.py` | New — per-entity toggle | ✅ |
| `blueprints/report/models/report_cash_count_detail.py` | New — per-denomination counts | ✅ |
| `blueprints/report/services/cash_denominations.py` | New — resolve / total / save | ✅ |
| Step 3a — `ending.py` three read blocks | converted to `get_cash_count_total` | ✅ |
| Step 3b — `cash_count.py` write path | catalog loop + dual write | ✅ |
| Step 3c — `templates/report/cash_count.html` | — | ❌ |
| Step 3d — `export_screenshot.py` / `deposit.py` | — | ❌ |
| Step 5 settings API | — | ❌ |

> **Backend is done; the template is not.** Until Step 3c lands, the form still
> posts the same nine fields it always did — which the new loop reads correctly
> for the HK defaults, so nothing is broken. But a *custom* denomination will
> not appear on the form, and the HK$200 note still has no visible input.

**Run the `.sql` OR the `.py` migrations — never both.** The guards make a
double-run harmless, but `alembic_version` would not record the SQL path.

> The `.py` files are also a **merge point**: `d1a01` has
> `down_revision = ("s4a04_backfill_sales", "e5b7d9f1a3c6")`, resolving two of
> the repo's divergent Alembic heads. This work needs both branches —
> `country_info`'s `char(2)` key from one, the catalog conventions from the
> other.

---

## Background you need

Five things that are easy to get wrong later.

### 1. The face values are hardcoded in FOUR places, not one

| File | Line | What |
|---|---|---|
| `blueprints/report/routes/cash_count.py` | 300–309 | the save path |
| `blueprints/report/services/ending.py` | ~666 | `total_actual_cash` |
| `blueprints/report/services/ending.py` | ~1157 | `total_actual_cash` again |
| `blueprints/report/services/ending.py` | ~1279 | `total_cash_count` at submit validation |

Four copies of `1000, 500, 100, 50, 20, 10, 5, 2, 1` is four chances to
disagree. Step 4 replaces all four with one call.

### 2. `cash_info` already exists — and is read by nothing

Created in `0001_full_schema.py:452`, FK'd to `country_info`, related from
`entity_cash_detail_v2` and `report_cash_detail`. **Never seeded, never
queried.** This migration is *activating* a dormant table, not inventing one.

### 3. `actual_cash_total` feeds the NEXT DAY's opening balance

`blueprints/report/routes/opening.py:1044` and
`blueprints/report/routes/create.py:284` both do:

```python
if last_cashcount and last_cashcount.actual_cash_total is not None:
    opening_balance = last_cashcount.actual_cash_total
```

**This is why Step 5 is gated harder than the sales equivalent.** A wrong
total does not affect one report — it propagates forward through every
subsequent day's opening balance.

### 4. The nine columns have FIVE readers

Not just `cash_count.py`:

| File | Line | Reads |
|---|---|---|
| `blueprints/report/services/ending.py` | 666, 1157, 1279 | all nine, three times |
| `blueprints/report/routes/export_screenshot.py` | 142–155 | all nine (`drawer_set1` / `drawer_set2`) |
| `blueprints/report/routes/deposit.py` | 108–116 | all nine (`with_entities` projection) |
| `blueprints/report/routes/cash_count.py` | 100–108, 370–433 | read + write |
| `templates/report/cash_count.html` | 237–245 | nine hidden inputs |

The sales columns were less entangled than this. Do not assume the sales
runbook's risk level transfers.

### 5. A report and its draft share one id

`ending.py:445` creates the revert draft with `id=full_report.id`. So one set
of detail rows serves both, and `report_cashcount_detail.report_id` FKs
`report_draft.id`. **Do not add a separate `report_draft_id`** — same trap the
sales runbook warns about for `report_sale_detail`.

---

## STEP 1 — Run the SQL

**Risk:** low. Additive + a type widen on an empty table. No code changes
needed. App keeps working exactly as before.

1. Open Supabase → SQL Editor → **confirm you are on the right project**.
2. Paste all of `migrations/d1a01_d3a03_cash_denomination_catalog.sql`.
3. Run. Wrapped in `BEGIN`/`COMMIT` — if anything fails, nothing applies.
4. Run the post-run checks at the bottom of that file (A, B, C, D, E).

**What it does:**

- reshapes `cash_info`: `country_code` `varchar(3)` → `char(2)`, `cash_id` →
  identity, adds `display_order` + `is_active`, adds a uniqueness constraint
- seeds **10 HKD denominations** (incl. the HK$200 note — see below)
- creates `report_cashcount_detail` (per-report, per-denomination counts)
- creates `entity_cash_denomination` (per-entity choice)
- **backfills the nine columns into detail rows**

### Why the three `cash_info` fixes are mandatory

| Fix | Why it blocks seeding without it |
|---|---|
| `country_code` → `char(2)` | `c8e0a2b4d6f8` rebuilt `country_info` with a `char(2)` PK. The FK was restored verbatim (valid reference), but the column can't hold a clean `'HK'` comparison. Table is empty, so this is a free change. |
| `cash_id` → identity | It was a bare integer PK with **no default**. Every INSERT had to supply its own id; adding a denomination from the app would need a `MAX(cash_id)+1` race. |
| `display_order` + `is_active` | Order is what the form renders in. `is_active` retires a denomination **without deleting the historical counts** that reference it. |

**Expected check results:**

| Check | Expected | If not |
|---|---|---|
| A — catalog seeded | 9 HK rows | re-run; `ON CONFLICT` makes it safe |
| B — rows well-formed | 9 rows, `display_order` 1..9, no NULL `cash_id` | identity step didn't apply — investigate |
| C — entities with no denominations | **0 rows** | those entities render an EMPTY cash count form. Fix their `country_code` before Step 4 |
| D — column vs detail totals | **0 rows** | **STOP.** See Step 6 |
| E — `actual_cash_total` vs detail | **0 rows** | **STOP.** This one propagates to next-day opening balances |

> The backfill only touches reports with **no** detail rows at all. Per-report,
> not per-denomination — a per-denomination guard would insert missing rows
> alongside app-written ones and silently disagree with what is displayed.

**Rollback:** commented block at the bottom of the SQL file. The nine columns
are never cleared, so dropping backfilled rows loses nothing.

---

## STEP 2 — Verify the seed matches reality

**Risk:** none. Read-only. **Do this before any code change.**

```sql
SELECT cash_id, type, cash_value, cash_name, display_order, is_active
FROM pettycashv2.cash_info
WHERE country_code = 'HK'
ORDER BY display_order;
```

Expect exactly nine rows — the same nine the cash count form can post:

| cash_id | type | cash_value | cash_name | display_order |
|---|---|---|---|---|
| * | note | 1000 | $1,000 | 1 |
| * | note | 500 | $500 | 2 |
| * | note | 100 | $100 | 3 |
| * | note | 50 | $50 | 4 |
| * | note | 20 | $20 | 5 |
| * | note | 10 | $10 | 6 |
| * | coin | 5 | $5 | 7 |
| * | coin | 2 | $2 | 8 |
| * | coin | 1 | $1 | 9 |

### The seed matches the form on purpose

The catalog holds exactly what the form can record. Two real HKD denominations
are **deliberately not seeded**, because the form has no working input for them
and listing a denomination a cashier cannot record would be worse than omitting
it:

| Denomination | Why it can't be recorded today |
|---|---|
| **HK$200 note** | `cash_count.py` used to parse `actual_cash[note200]` and add it to the running total, but no form field and no column ever existed — it was dropped on save. The Step 3b rewrite removed that phantom parse. |
| **HK$10 coin** | `cash_count.html` has a `10coins` input with an `id` but **no `name`**, so it adds to the total the cashier sees in the browser and then never posts. |

Both are one `INSERT` away once the form renders from this catalog — and
`form_field_for` already maps them to `note200` / `10coins`, so the field names
will be right. **Seed them at the same time as the template work, not before.**

---

## STEP 3 — Point the read path at the database

**Risk:** medium. This is the actual work, and what buys the "one INSERT" goal.
Until it's done, adding a catalog row won't surface a denomination anywhere.

All four hardcoded blocks get replaced by
`blueprints/report/services/cash_denominations.py`, which is already written:

```python
from blueprints.report.services.cash_denominations import (
    get_cash_count_total, resolve_denominations_for_entity,
    save_cash_count_details, counts_to_legacy_columns, form_field_for)
```

| Function | Replaces |
|---|---|
| `resolve_denominations_for_entity(entity_id)` | the implicit "these nine, in this order" |
| `get_cash_count_total(report_id, fallback_draft=...)` | all four multiplier blocks |
| `save_cash_count_details(report_id, {cash_id: count})` | the nine column assignments |
| `counts_to_legacy_columns({cash_id: count})` | keeps the nine columns in sync |
| `form_field_for(denomination)` | maps a row to its form field name |

Suggested order — each is independently shippable:

### 3a. `ending.py` — the three read-only blocks

Lines ~666, ~1157, ~1279. Each becomes:

```python
total_actual_cash = get_cash_count_total(report.id, fallback_draft=cashcount_draft)
```

Lowest risk: read-only, and the fallback returns the identical number for any
report that has no detail rows. **Ship this first and watch it for a day** —
if totals stay stable, the read path is proven before anything writes.

### 3b. `cash_count.py` — the write path

Replace lines 262–323 (the ten `safe_float` reads and ten multiplications) with
a loop over `resolve_denominations_for_entity(entity_id)`, reading
`request.form.get(f"actual_cash[{form_field_for(d)}]")`.

Then **write both stores**:

```python
save_cash_count_details(current_draft.id, counts_by_cash_id)
for column, count in counts_to_legacy_columns(counts_by_cash_id).items():
    setattr(cashcount_draft, column, count)
cashcount_draft.actual_cash_total = get_cash_count_total(current_draft.id)
```

> **Keep writing the nine columns.** They have five readers. `counts_to_legacy_columns`
> always returns all nine keys, so a denomination dropped to zero is written
> back as `0` rather than left stale.

**Also fix here:** line 341 computes
`discrepancy = (total_cash_count - expected) + safe_box_balance`. Confirm the
sign convention is intended before touching it — a surplus adding the safe box
reads oddly, but changing it alters every discrepancy in the system. Out of
scope for this migration; note it and move on.

### 3c. `templates/report/cash_count.html` — render from the catalog

**Not yet done.** Larger than it looks — the denominations are hardcoded in
**five** separate places in this one file:

| Lines | What |
|---|---|
| 237–245 | nine hidden inputs (the ones that actually POST) |
| ~1749–1813 | the visible number inputs, one block per denomination |
| ~724 | `calculateTotals` denomination array |
| ~882–903 | `getDiscrepancyAmount` note + coin arrays |
| ~943–954 | `updateDiscrepancyOnInput` listener arrays |
| ~1296, 1400, 1413 | `coinInputs = ['10coins', '5coins', '2coins', '1coins']` |

The route now passes **`denomination_rows`** — a list of dicts with
`cash_id`, `field`, `label`, `value`, `type`, `count`. Replace all five sites
with loops over it, and emit it once as JSON for the JS:

```html
<script>const DENOMINATIONS = {{ denomination_rows|tojson }};</script>
```

Then every array above derives from `DENOMINATIONS` instead of being retyped.

Keep the existing field names (`note1000`, `5coins`, …) — `form_field_for`
returns exactly those for the HK defaults, so saved markup and browser autofill
keep working. Custom denominations get `cash{cash_id}`.

The template already receives `currency_symbol` from the context processor at
`pettycash/core/hooks.py:214`, so the symbol is per-entity correct already.

> **Second silent-loss bug found here.** Line 724 and 900 define
> `{ id: '10coins', value: 10 }` — commented *"Read-only coin (no database
> table yet)"*. It has an `id` but **no `name`**, so it contributes to the
> total the cashier sees in the browser and then never posts. Same family as
> the HK$200 bug. Both close when the form renders from the catalog.

### 3d. `export_screenshot.py` and `deposit.py`

`export_screenshot.py:142-155` hardcodes `drawer_set1` / `drawer_set2` splits.
`deposit.py:108-116` projects the nine columns via `with_entities`.

Both can stay on the columns for now — they read, never write, and the columns
are still maintained. Convert them in Step 5 alongside the column drop.

**Verify after 3a–3c:** re-run checks D and E. Both must still be 0 after
entering a cash count through the UI.

---

## STEP 4 — Verify checks D and E return zero

**This is the gate. Do not skip it.**

Run checks D and E from the bottom of the SQL file.

- **Zero rows → safe to proceed.**
- **Any rows → STOP.** The two stores disagree. Investigate *while the columns
  still exist* — after Step 6 they are gone and you cannot compare.

Expected legitimate exception: a report counted with **HK$200** after Step 3b
ships will show in check D, because the column side has no `note200` term.
Confirm the delta equals exactly `200 × (quantity counted)` before dismissing it.

Let this sit through **at least one deploy cycle with real traffic** before
Step 6. Steps 1–3 are reversible; Step 6 is not.

---

## STEP 5 — Settings API for customization

**Risk:** low. Purely additive — an entity with no override rows keeps its
country defaults.

Mirror `blueprints/entity/services/payment_methods.py` and
`blueprints/entity/routes/payment.py`:

| Endpoint | Purpose |
|---|---|
| `GET /api/entities/<id>/denominations` | list resolved denominations |
| `PATCH /api/entities/<id>/denominations/<cash_id>` | toggle `enabled` |
| `POST /api/entities/<id>/denominations/reorder` | set `display_order` |

Writes go to `entity_cash_denomination`, **never** to `cash_info` — the catalog
is shared by every entity in the country.

Add permissions alongside the `SALES_METHOD_*` set in
`services/permission_policy.py:40-44`. Suggested: `CASH_DENOMINATION_VIEW`
(Cashier), `CASH_DENOMINATION_UPDATE` (Accountant) — matching the existing
view/update split.

> **Guardrail:** disabling a denomination must not delete its historical
> counts. `report_cashcount_detail.cash_id` is `ON DELETE RESTRICT` for exactly
> this reason. Disabling hides it from *future* forms only.

---

## STEP 6 — Drop the nine columns

**Risk:** HIGH — irreversible. A down-migration recreates the columns but not
their data. **Take a database backup first.**

Preconditions, all required:

- [ ] Check D returns zero rows (or only explained HK$200 deltas)
- [ ] Check E returns zero rows
- [ ] Step 3 complete — `ending.py`, `cash_count.py`, the template all use the service
- [ ] `export_screenshot.py` and `deposit.py` converted (Step 3d)
- [ ] Ran in production for at least one deploy cycle
- [ ] Backup taken

```sql
BEGIN;

ALTER TABLE pettycashv2.report_cashcount_draft
    DROP COLUMN thousand_note,    DROP COLUMN fivehundred_note,
    DROP COLUMN onehundred_note,  DROP COLUMN fifty_note,
    DROP COLUMN twenty_note,      DROP COLUMN ten_note,
    DROP COLUMN five_coin,        DROP COLUMN two_coin,
    DROP COLUMN one_coin;

COMMIT;
```

**KEEP** on `report_cashcount_draft`: `actual_cash_total` (feeds the next day's
opening balance — see Background 3), `safe_box_balance`, `discrepancy_amount`,
`discrepancy_type`, `discrepancy_reason`.

Also remove the nine column definitions from
`blueprints/report/models/report_cash_count_draft.py`, and the
`LEGACY_COLUMN_DENOMINATIONS` / `counts_to_legacy_columns` fallback from
`blueprints/report/services/cash_denominations.py`.

---

## After: adding a new denomination

```sql
INSERT INTO pettycashv2.cash_info
    (country_code, type, cash_value, cash_name, "desc", display_order, is_active)
VALUES
    ('HK', 'coin', 10, '$10', 'HK$10 coin', 11, true);
```

That's it. No migration, no code change, no deploy.

### Seeding a new country

```sql
-- Confirm the country exists and has a currency first.
SELECT ci.country_code, ci.country_name_en, cu.currency_code, cu.symbol
FROM pettycashv2.country_info ci
LEFT JOIN pettycashv2.currency_info cu ON cu.id = ci.currency_id
WHERE ci.country_code = 'SG';

INSERT INTO pettycashv2.cash_info
    (country_code, type, cash_value, cash_name, "desc", display_order, is_active)
VALUES
    ('SG', 'note', 1000, '$1,000', 'SGD 1,000 note', 1, true),
    ('SG', 'note',  100, '$100',   'SGD 100 note',   2, true);
    -- ...
```

Entities with that `country_code` pick it up on their next cash count. The
`currency_symbol` context processor (`pettycash/core/hooks.py:157`) already
resolves the symbol per entity, so the form labels itself correctly.

---

## Design notes — why it is shaped this way

**Why `cash_info` is per-country, not per-entity.** A face value is a property
of the currency. HK$500 is HK$500 for every HK entity, and a revaluation should
be one row, not N. Per-entity variation lives in `entity_cash_denomination`,
where a row exists **only** when an entity diverges from its country default —
so a new entity needs no seeding, and a denomination added to a country later
appears automatically.

**Why not merge this into `sales_method`.** Different scoping (country vs
entity), different semantics (`count × cash_value` vs a money `amount`),
different consumers (cash count vs sales + Xero). One table cannot be both
without nullable-column sprawl. They share the *pattern* — catalog →
per-entity choice → per-report detail → legacy columns behind a gate — not the
table.

**Why `entity_cash_detail_v2` was left alone.** It already has
`(entity_id, cash_id)` and looks like a fit, but it holds `cash_instock` — a
running quantity-on-hand. Overloading it would make a row's absence ambiguous
between "not stocked" and "not tracked", and enabling a denomination would
silently invent a stock figure.

**Why `cash_value` is duplicated onto `report_cashcount_detail`.** It is a
snapshot of the face value in force when the count was taken. If a
denomination is revalued or retired, historical reports must still total to
what was actually counted that day.

---

## Open items

1. **`report_cash_detail` has a broken primary key.** `0001_full_schema.py:736`
   makes `cash_id` alone the PK, so only one row per denomination can exist
   across the *entire table*. It is almost certainly meant to be
   `(cash_id, report_id)`, mirroring `entity_cash_detail_v2`. Nothing writes to
   this table today, so it is latent — but fix it before anything does.

2. **Discrepancy sign convention.** `cash_count.py:341` adds `safe_box_balance`
   to a surplus. Verify this is intended; out of scope here.

3. **Divergent Alembic heads.** `d1a01` merges two of them. Others remain
   (pre-existing, noted in the sales runbook too).
