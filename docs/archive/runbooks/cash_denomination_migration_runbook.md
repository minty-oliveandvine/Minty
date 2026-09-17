# Cash Denomination Migration — Deployment Runbook

**Goal:** adding a cash denomination becomes a single `INSERT` into
`pettycashv2.cash_info` — no schema change, no code change. Entities choose
which denominations they log.

**Target:** the live `pettycashv2` schema.

**Design:** merges the naming and structure of the proposed v3 schema
(`01_schema.sql` section F) with four corrections. Rationale for each is in
`docs/archive/runbooks/cash_denomination_schema_review.md`. This migration is a **step toward**
v3, not away from it.

This runbook is self-contained. You should not need any prior context.

Companion to `docs/archive/runbooks/sales_method_migration_runbook.md` — same structure, same
discipline. The two are **independent**; neither blocks the other.

---

## Naming (v3-aligned)

| Table | Role | v3 equivalent |
|---|---|---|
| `cash_info` | denomination catalog, keyed on `currency_id` | same |
| `entity_cash_setting` | per-entity selection | *new — v3 has no cash equivalent* |
| `report_cash_count` | per-report quantities | same |

Python classes: `CashInfo`, `EntityCashSetting`, `ReportCashCount`.

### Deviations from v3, forced by the live schema

| Deviation | Why | Resolves at v3 cutover |
|---|---|---|
| `cash_info` keeps its integer `cash_id` PK (v3 uses UUID `id`) | `entity_cash_detail_v2` and `report_cash_detail` both FK it | rekey with the cutover |
| `report_cash_count.report_id` → `report_draft(id)` | pettycashv2 still splits report / report_draft / report_v2 | re-point at `report(id)`, no data change |
| `desc` not renamed to `description` | referenced by the existing `CashInfo` model | rename with the cutover |

### Four corrections applied on top of v3

1. **`UNIQUE (currency_id, cash_value, type)`** — v3 omits `type`, which
   silently blocks HKD's $10 note and $10 coin from coexisting.
2. **`entity_cash_setting` exists** — v3 has `entity_sale_setting` for sales
   channels but no cash equivalent, so an entity cannot hide a denomination it
   never handles.
3. **`report_cash_count.cash_value` snapshot** — without it, revaluing a
   denomination silently re-totals every published historical report.
4. **`cash_info.is_active` + `display_order`** — v3 omits both, so a withdrawn
   note can never be retired (deletion is blocked by the `RESTRICT` FK).

---

## Files

| File | Purpose | Written? |
|---|---|---|
| `migrations/c1a01_c3a03_cash_denomination_catalog.sql` | The Supabase script (steps 1–3 + checks) | ✅ |
| `blueprints/entity/models/cash_info.py` | Updated — `currency_id`, `display_order`, `is_active` | ✅ |
| `blueprints/entity/models/entity_cash_setting.py` | New | ✅ |
| `blueprints/report/models/report_cash_count.py` | New | ✅ |
| `blueprints/report/services/cash_denominations.py` | New — resolve / total / save | ✅ |
| Step 3a — `ending.py` three read blocks | converted to `get_cash_count_total` | ✅ |
| Step 3b — `cash_count.py` write path | catalog loop + dual write | ✅ |
| Step 3c — `templates/report/cash_count.html` | — | ❌ |
| Step 3d — `export_screenshot.py` / `deposit.py` | — | ❌ |
| Step 5 — settings API | — | ❌ |

> **Backend is done; the template is not.** Until Step 3c lands, the form still
> posts the same nine fields it always did — which the new loop reads correctly
> for the HKD defaults, so nothing is broken. But a *custom* denomination will
> not appear on the form, and neither will the HK$200 note or HK$10 coin.

> There is no Alembic equivalent. The earlier `d1a01`/`d2a02` revisions were
> removed when the design moved to v3 naming. Run the `.sql`.

---

## Background you need

Six things that are easy to get wrong later.

### 1. The face values are hardcoded in FOUR places, not one

| File | Line | What |
|---|---|---|
| `blueprints/report/routes/cash_count.py` | 300–309 | the save path |
| `blueprints/report/services/ending.py` | ~666 | `total_actual_cash` |
| `blueprints/report/services/ending.py` | ~1157 | `total_actual_cash` again |
| `blueprints/report/services/ending.py` | ~1279 | `total_cash_count` at submit validation |

Four copies of `1000, 500, 100, 50, 20, 10, 5, 2, 1` is four chances to
disagree. Step 3 replaces all four with one call.

### 2. `cash_info` already exists — and is read by nothing

Created in `0001_full_schema.py:452`, FK'd to `country_info`, related from
`entity_cash_detail_v2` and `report_cash_detail`. **Never seeded, never
queried.** This migration activates a dormant table.

### 3. `actual_cash_total` feeds the NEXT DAY's opening balance

`blueprints/report/routes/opening.py:1044` and
`blueprints/report/routes/create.py:284` both do:

```python
if last_cashcount and last_cashcount.actual_cash_total is not None:
    opening_balance = last_cashcount.actual_cash_total
```

**This is why the column drop is gated harder than the sales equivalent.** A
wrong total does not affect one report — it propagates forward through every
subsequent day's opening balance.

### 4. The nine columns have FIVE readers

| File | Line | Reads |
|---|---|---|
| `blueprints/report/services/ending.py` | 409–417 | `with_entities` projection |
| `blueprints/report/routes/export_screenshot.py` | 142–155 | all nine (`drawer_set1` / `drawer_set2`) |
| `blueprints/report/routes/deposit.py` | 108–116 | `with_entities` projection |
| `blueprints/report/routes/cash_count.py` | 100–108 | `with_entities` projection |
| `templates/report/cash_count.html` | 237–245 | nine hidden inputs |

The three `with_entities` projections name the columns directly in the SELECT,
so dropping a column fails the query immediately — not subtly.

### 5. A report and its draft share one id

`ending.py:445` creates the revert draft with `id=full_report.id`. So one set
of count rows serves both. **Do not add a separate `report_draft_id`** — same
trap the sales runbook warns about for `report_sale_detail`.

### 6. Currency resolution has a fallback

`entities.currency_id` is authoritative, but
`resolve_currency_id()` falls back to `country_info.currency_id` for any entity
where it was never backfilled. Check C below finds entities where neither
resolves.

---

## STEP 1 — Run the SQL

**Risk:** low. Additive. No code changes needed beyond what is already in the
tree. App keeps working.

1. Open Supabase → SQL Editor → **confirm you are on the right project and
   schema.** The script hardcodes `pettycashv2` in every reference. If you are
   targeting a clone, replace *every* occurrence — a partial rewrite would read
   one schema and write another.
2. Paste all of `migrations/c1a01_c3a03_cash_denomination_catalog.sql`.
3. Run. Wrapped in `BEGIN`/`COMMIT` — if anything fails, nothing applies.
4. Run the post-run checks at the bottom of that file (A, B, C, D, E).

**What it does:**

- adds `cash_info.currency_id` (FK → `currency_info`) and backfills it via
  `country_info.currency_id`
- adds `display_order` + `is_active`, and `UNIQUE (currency_id, cash_value, type)`
- makes `cash_id` self-assigning **only if it has no default** (a database where
  it is already `serial` is left alone — adding an identity on top raises
  `55000: column "cash_id" ... already has a default value`)
- seeds **9 HKD denominations**
- creates `report_cash_count` and `entity_cash_setting`
- **backfills the nine columns into count rows**

**Expected check results:**

| Check | Expected | If not |
|---|---|---|
| A — catalog seeded | 9 HKD rows | re-run; `ON CONFLICT` makes it safe |
| B — rows well-formed | 9 rows, `display_order` 1..9, no NULL `currency_id` | investigate before continuing |
| C — entities with no denominations | **0 rows** | those entities render an EMPTY cash count form. Fix their `currency_id` before Step 3 |
| D — column vs count-row totals | **0 rows** | **STOP.** See Step 4 |
| E — `actual_cash_total` vs count rows | **0 rows** | **STOP.** This one propagates to next-day opening balances |

> The backfill only touches reports with **no** count rows at all. Per-report,
> not per-denomination — a per-denomination guard would insert missing rows
> alongside app-written ones and silently disagree with what is displayed.

**Rollback:** commented block at the bottom of the SQL file. The nine columns
are never cleared, so dropping the count rows loses nothing.

---

## STEP 2 — Verify the seed matches reality

**Risk:** none. Read-only. **Do this before trusting Step 3.**

```sql
SELECT ci.cash_id, ci.type, ci.cash_value, ci.cash_name, ci.display_order
FROM pettycashv2.cash_info ci
JOIN pettycashv2.currency_info cu ON cu.id = ci.currency_id
WHERE cu.currency_code = 'HKD'
ORDER BY ci.display_order;
```

Expect exactly nine rows — the same nine the form can post:

| type | cash_value | cash_name | display_order |
|---|---|---|---|
| note | 1000 | $1,000 | 1 |
| note | 500 | $500 | 2 |
| note | 100 | $100 | 3 |
| note | 50 | $50 | 4 |
| note | 20 | $20 | 5 |
| note | 10 | $10 | 6 |
| coin | 5 | $5 | 7 |
| coin | 2 | $2 | 8 |
| coin | 1 | $1 | 9 |

### The seed matches the form on purpose

Two real HKD denominations are **deliberately not seeded**, because the form has
no working input for them:

| Denomination | Why it cannot be recorded today |
|---|---|
| **HK$200 note** | `cash_count.py` used to parse `actual_cash[note200]` and add it to the running total, but no form field and no column ever existed — it was dropped on save. The catalog rewrite removed that phantom parse. |
| **HK$10 coin** | `cash_count.html` has a `10coins` input with an `id` but **no `name`**, so it adds to the total the cashier sees and never posts. |

Both are one `INSERT` away once the form renders from the catalog, and
`form_field_for` already maps them to `note200` / `10coins`. The $10 coin is
only expressible because `type` is in the uniqueness constraint — v3's proposed
constraint would reject it.

**Seed them at the same time as the template work, not before.**

---

## STEP 3 — Point the read path at the database

**Risk:** medium. This is what buys the "one INSERT" goal.

`blueprints/report/services/cash_denominations.py` is already written:

| Function | Replaces |
|---|---|
| `resolve_denominations_for_entity(entity_id)` | the implicit "these nine, in this order" |
| `get_cash_count_total(report_id, fallback_draft=...)` | all four multiplier blocks |
| `save_cash_count_details(report_id, {cash_id: qty})` | the nine column assignments |
| `counts_to_legacy_columns({cash_id: qty})` | keeps the nine columns in sync |
| `build_denomination_rows(...)` | template rows with saved counts |
| `form_field_for(denomination)` | maps a row to its form field name |

### 3a. `ending.py` — the three read-only blocks ✅ DONE

Each became `get_cash_count_total(<id>, fallback_draft=cashcount_draft)`.
Lowest risk: read-only, and the fallback returns the identical number for any
report with no count rows.

### 3b. `cash_count.py` — the write path ✅ DONE

The ten form reads and ten multiplications became a loop over
`resolve_denominations_for_entity(entity_id)`. It **dual-writes**:
`save_cash_count_details()` for the count rows, `counts_to_legacy_columns()`
for the nine columns, both inside the existing transaction.

> **Keep writing the nine columns.** They have five readers.
> `counts_to_legacy_columns` always returns all nine keys, so a denomination
> dropped to zero is written back as `0` rather than left stale.

**Also noted here, not fixed:** `cash_count.py:341` computes
`discrepancy = (total_cash_count - expected) + safe_box_balance`. A surplus
adding the safe box reads oddly, but changing it alters every discrepancy in
the system. Out of scope — confirm the sign convention separately.

### 3c. `templates/report/cash_count.html` — render from the catalog ❌ TODO

Larger than it looks — denominations are hardcoded in **five** places:

| Lines | What |
|---|---|
| 237–245 | nine hidden inputs (the ones that actually POST) |
| ~1749–1813 | the visible number inputs, one block per denomination |
| ~724 | `calculateTotals` denomination array |
| ~882–903 | `getDiscrepancyAmount` note + coin arrays |
| ~943–954 | `updateDiscrepancyOnInput` listener arrays |
| ~1296, 1400, 1413 | `coinInputs = ['10coins', '5coins', '2coins', '1coins']` |

The route already passes **`denomination_rows`** — dicts with `cash_id`,
`field`, `label`, `value`, `type`, `count`. Replace all five sites with loops,
and emit it once as JSON for the JS:

```html
<script>const DENOMINATIONS = {{ denomination_rows|tojson }};</script>
```

Keep the existing field names — `form_field_for` returns exactly those for the
HKD defaults, so saved markup and browser autofill keep working. Custom
denominations get `cash{cash_id}`.

The template already receives `currency_symbol` from the context processor at
`pettycash/core/hooks.py:214`, so the symbol is per-entity correct already.

### 3d. `export_screenshot.py` and `deposit.py` ❌ TODO

Both can stay on the columns for now — they read, never write, and the columns
are still maintained. Convert alongside the column drop.

**Verify after 3c:** re-run checks D and E. Both must still be 0 after entering
a cash count through the UI.

---

## STEP 4 — Verify checks D and E return zero

**This is the gate. Do not skip it.**

- **Zero rows → safe to proceed.**
- **Any rows → STOP.** The two stores disagree. Investigate *while the columns
  still exist* — after Step 6 they are gone and you cannot compare.

Let this sit through **at least one deploy cycle with real traffic** before
Step 6. Steps 1–3 are reversible; Step 6 is not.

---

## STEP 5 — Settings API for customization

**Risk:** low. Purely additive — an entity with no rows keeps its defaults.

Mirror `blueprints/entity/services/payment_methods.py` and
`blueprints/entity/routes/payment.py`:

| Endpoint | Purpose |
|---|---|
| `GET /api/entities/<id>/denominations` | list resolved denominations |
| `PATCH /api/entities/<id>/denominations/<cash_id>` | toggle `is_active` |
| `POST /api/entities/<id>/denominations/reorder` | set `display_order` |

Writes go to `entity_cash_setting`, **never** to `cash_info` — the catalog is
shared by every entity using that currency.

Add permissions alongside the `SALES_METHOD_*` set in
`services/permission_policy.py:40-44`. Suggested: `CASH_DENOMINATION_VIEW`
(Cashier), `CASH_DENOMINATION_UPDATE` (Accountant).

> **Guardrail:** disabling a denomination must not delete its historical
> counts. `report_cash_count.cash_id` is `ON DELETE RESTRICT` for exactly this
> reason. Disabling hides it from *future* forms only.

---

## STEP 6 — Drop the nine columns

**Risk:** HIGH — irreversible. A down-migration recreates the columns but not
their data. **Take a database backup first.**

Preconditions, all required:

- [ ] Checks D and E return zero rows
- [ ] Step 3 complete — including **3c and 3d**
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

**KEEP**: `actual_cash_total` (feeds the next day's opening balance — see
Background 3), `safe_box_balance`, `discrepancy_amount`, `discrepancy_type`,
`discrepancy_reason`.

Also remove the nine column definitions from
`blueprints/report/models/report_cash_count_draft.py`, and the
`LEGACY_COLUMN_DENOMINATIONS` / `counts_to_legacy_columns` fallback from
`cash_denominations.py`.

> **If the v3 cutover is imminent, skip Step 6 entirely.** v3 drops
> `report_cashcount_draft` wholesale.

---

## After: adding a new denomination

```sql
INSERT INTO pettycashv2.cash_info
    (currency_id, type, cash_value, cash_name, "desc", display_order, is_active)
SELECT id, 'coin', 10, '$10', 'HK$10 coin', 10, true
FROM pettycashv2.currency_info WHERE currency_code = 'HKD';
```

No migration, no code change, no deploy — once Step 3c lands.

### Seeding a new currency

```sql
INSERT INTO pettycashv2.cash_info
    (currency_id, type, cash_value, cash_name, "desc", display_order, is_active)
SELECT id, 'note', 1000, '$1,000', 'SGD 1,000 note', 1, true
FROM pettycashv2.currency_info WHERE currency_code = 'SGD';
```

Entities with that `currency_id` pick it up on their next cash count. The
`currency_symbol` context processor (`pettycash/core/hooks.py:157`) already
resolves the symbol per entity, so the form labels itself correctly.

---

## Path to the v3 schema

When `01_schema.sql` is adopted, this migration becomes a partial head start:

| Already aligned | Needs cutover work |
|---|---|
| Table names (`cash_info`, `entity_cash_setting`, `report_cash_count`) | `cash_id` integer → UUID `id` |
| `currency_id` keying | `report_id` → `report(id)` after the three report tables merge |
| Column names (`quantity`, `is_active`, `display_order`) | `desc` → `description` |
| Uniqueness, FK cascade semantics | `type` VARCHAR → `cash_type` enum |
| `cash_denominations.py` service logic | drop `country_code`, drop the legacy-column fallback |

`cash_denominations.py` survives the cutover with only its FK targets changed —
the resolve/total/save logic is schema-independent.

---

## Open items

1. **`report_cash_detail` has a broken primary key.** `0001_full_schema.py:736`
   makes `cash_id` alone the PK, so only one row per denomination can exist
   across the *entire table*. Almost certainly meant to be
   `(cash_id, report_id)`. Nothing writes to it today, so it is latent — but
   fix it before anything does. v3 replaces it with `report_cash_count`.

2. **Discrepancy sign convention.** `cash_count.py:341` adds `safe_box_balance`
   to a surplus. Verify this is intended; out of scope here.

3. **Feed the four corrections back to the v3 author** — see
   `docs/archive/runbooks/cash_denomination_schema_review.md`. Points 1 (the `type` in the
   uniqueness constraint) and 2 (`entity_cash_setting`) are the ones that
   change their DDL.
