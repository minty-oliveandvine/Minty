# Cash Denomination: `01_schema.sql` vs the `pettycashv2` migration work

Two independent designs for the same problem — normalising the nine hardcoded
note/coin columns on `report_cashcount_draft` into a denomination catalog plus
per-denomination counts.

**They agree on the core design.** This document covers only where they differ,
and which side is right in each case.

* `01_schema.sql` — proposed v3 rewrite (`pettycash_test`), not yet applied.
* `migrations/d1a01_d3a03_cash_denomination_catalog.sql` — incremental
  migration against the live `pettycashv2` schema.

---

## Where they agree

Arrived at independently, which is good evidence the shape is right:

| Decision | Both |
|---|---|
| Denomination catalog table | `cash_info` |
| Per-(report, denomination) counts | one row each |
| Uniqueness on the count table | `UNIQUE (report_id, cash_id)` |
| Delete behaviour | report `CASCADE`, denomination `RESTRICT` |
| Count is a quantity, multiplied by a face value | yes |
| `entity_cash_detail(_v2)` left alone as stock-on-hand | yes |

The `RESTRICT` on `cash_id` matters and both got it: deleting a denomination
must never silently delete the historical counts referencing it.

---

## Where `01_schema.sql` is better — adopt these

### 1. `cash_info` keyed on currency, not country

```sql
-- 01_schema.sql
currency_id UUID NOT NULL REFERENCES currency_info(id) ON DELETE RESTRICT
```
```sql
-- pettycashv2 migration
country_code CHAR(2) REFERENCES country_info(country_code)
```

A denomination is a property of the **currency**, not the country. Two
countries sharing a currency would duplicate every row under the country model.
The migration used `country_code` only because that FK already existed on the
legacy table.

**`01_schema.sql` wins.** Any future version should key on `currency_id`.

### 2. UUID primary keys

`cash_info.id UUID DEFAULT gen_random_uuid()` sidesteps an entire class of
problem. The legacy `cash_id` is a bare integer whose default varies by
environment — running the migration against a database where it was already
`serial` fails with:

```
ERROR: 55000: column "cash_id" of relation "cash_info" already has a default value
```

The migration now detects and tolerates that. With UUIDs the situation cannot
arise.

### 3. `cash_type` as an enum

`CREATE TYPE cash_type AS ENUM ('coin','note')` — the migration uses
`VARCHAR(10)` and relies on convention. The enum is strictly better.

### 4. `desc` renamed to `description`

`desc` is a reserved word; every reference in the migration SQL has to be
quoted as `"desc"`. Renaming is correct.

### 5. Report-level fields consolidated onto `report`

`safe_box_balance`, `discrepancy_amount`, `discrepancy_type`,
`discrepancy_reason` sit on `report` directly. Today they are duplicated across
**both** `report_cashcount_draft` and `report_draft`, written twice on every
save (`cash_count.py`) — a real source of drift. Consolidating is right.

---

## Where the migration work is better — please consider these

### 1. `UNIQUE (currency_id, cash_value)` blocks note+coin of equal value

```sql
-- 01_schema.sql
CONSTRAINT cash_info_currency_value_key UNIQUE (currency_id, cash_value)
```

HKD circulates **both a $10 note and a $10 coin**. This constraint permits only
one of them. The `type` column exists but is not part of the key.

The migration uses `UNIQUE (country_code, cash_value, type)`.

**Suggested fix:**
```sql
CONSTRAINT cash_info_currency_value_key UNIQUE (currency_id, cash_value, type)
```

This is live today: `templates/report/cash_count.html` has a `10coins` input
(id, but no `name`, so it never posts) sitting alongside the `note10` field.

### 2. No per-entity denomination selection

`01_schema.sql` has `entity_sale_setting` for sales channels but no cash
equivalent. `entity_cash_detail` is stock-on-hand — a different thing; treating
absence as "not tracked" would conflate it with "not stocked", and enabling a
denomination would invent a stock figure.

So a shop that never handles HK$1,000 notes cannot hide that row.

**Suggested addition**, mirroring `entity_sale_setting` exactly:
```sql
CREATE TABLE pettycash_test.entity_cash_setting (
  entity_id     UUID    NOT NULL,
  cash_id       UUID    NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NULL,
  CONSTRAINT entity_cash_setting_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecs_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecs_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE CASCADE
);
```

A row exists **only** where an entity diverges from its currency default, so a
new entity needs no seeding and picks up denominations added later. Same
convention `entity_sale_setting` already uses.

### 3. `report_cash_count` has no face-value snapshot

```sql
-- 01_schema.sql
quantity INTEGER NOT NULL DEFAULT 0
-- total must be recomputed as quantity * cash_info.cash_value
```

If a denomination is ever revalued or retired, **every historical report
silently re-totals**. The migration denormalises the face value onto the count
row:

```sql
cash_value NUMERIC(12,2) NOT NULL  -- as at the time of counting
```

Low likelihood, but the failure mode is silent corruption of published reports,
and the cost is one column.

### 4. No `is_active` on `cash_info`

There is no way to retire a denomination. Deleting is blocked by the `RESTRICT`
FK (correctly), so a withdrawn note stays on the form forever.

**Suggested addition:** `is_active BOOLEAN NOT NULL DEFAULT TRUE`, plus
`display_order INTEGER` — `sale_info` has both, and the cash count form needs
the same ordering control.

---

## Consequences for the current migration work

If `01_schema.sql` is adopted, these files are obsolete — they target the
`pettycashv2` shape (integer keys, `report_draft`, `country_code`):

```
migrations/d1a01_d3a03_cash_denomination_catalog.sql
migrations/versions/d1a01_cash_denomination_catalog.py
migrations/versions/d2a02_cash_count_detail_and_entity_denominations.py
blueprints/entity/models/entity_cash_denomination.py
blueprints/report/models/report_cash_count_detail.py
```

Still useful regardless of which schema wins:

* `blueprints/report/services/cash_denominations.py` — the read/write layer.
  Table and column names change; the logic (resolve per entity, total from
  detail rows, fall back to legacy columns) does not.
* The `ending.py` / `cash_count.py` edits removing **four** duplicated
  hardcoded multiplier blocks.
* `docs/cash_denomination_migration_runbook.md` — the sequencing, the
  verification gates, and the two bugs documented below.

---

## Two live bugs, independent of which schema wins

Both are in `templates/report/cash_count.html` and neither schema fixes them on
its own — they need the form to render from the catalog.

**HK$200 note.** No form field and no column. `cash_count.py` used to parse
`actual_cash[note200]` and add it to the running total, so the value appeared
in the browser and was dropped on save. (The catalog rewrite removed that
phantom parse.)

**HK$10 coin.** `templates/report/cash_count.html` defines
`{ id: '10coins', value: 10 }` with an `id` but **no `name`** — it adds to the
total the cashier sees and never posts.

Both are one catalog row away once the form loops over the denominations —
provided the uniqueness constraint in point 1 above allows the coin to exist.
