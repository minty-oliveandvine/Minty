# Report Consolidation — Remaining Work Runbook

**Goal:** collapse seven tables into `report` and `shop_expense`, so a report
is one row and an expense is one row, rather than a draft/real pair that must
be kept in sync.

**Target:** the live `pettycashv2` schema.

This runbook is self-contained. It covers what is **left**; the completed
stages are summarised only enough to explain why the remaining ones are safe.

Companion to `docs/archive/runbooks/cash_denomination_migration_runbook.md` — same structure.
The two are independent.

**Status as of 31 Jul 2026:** the application is fully working, Xero publish
included. Everything below is scaffolding removal. There is no deadline, and
nothing degrades if it waits.

### Progress

| Step | State |
|---|---|
| 1 — `r6a06` FK re-point | **DONE** — applied to `pettycashv2` |
| 2 — Report write flip | **DONE** — `fe87216` |
| 3 — Expense write flip | **DONE** — `fe87216` |
| 3.5 — Cash-count / detail tables | **DONE** (code) |
| 4a/4b — Remove reads + models | **DONE** (code) |
| 4c — `r10a10` drops | **DONE on localhost** — NOT run on production |
| 4d — `r9a09` Xero PKs | **DONE** — option B |

**Everything is code-complete and verified on localhost as of 4 Aug 2026.**
Nothing has been deployed and no migration has been run on production.
See `docs/archive/runbooks/report_consolidation_step_4_runbook.md` for the per-unit detail.

**Step 3.5 status (3 Aug 2026).** All writers to the three tables are gone;
`grep -rn "ReportCashCountDraft(\|ReportDetail(\|ReportExpenseDetail("
blueprints/` returns only the model definitions. Remaining reads are the
legacy-fallback path in `cash_denominations.py` and the four cascade-deletes in
`report_detail.py`, both deliberately kept until Step 4 — see
`docs/archive/runbooks/report_consolidation_step_3_5_runbook.md`.

**Two migrations ship with Step 3.5. Both are required before Step 4:**

| Revision | Fixes |
|---|---|
| `r7a07_backfill_actual_cash` | `report.actual_cash_total` never had a writer, so the Step 4 pre-drop check cannot pass without it |
| `r8a08_repoint_rcc_fk` | `report_cash_count.report_id` still FK'd `report_draft.id` — **a live bug**, see below |

### 🔴 `r8a08` — the FK `r6a06` missed

`r6a06` re-pointed `shop_expense_draft`, `report_cashcount_draft` and
`report_history_draft`. **`report_cash_count` was not on that list** — the new
source-of-truth table for denominations was left pointing at `report_draft`.

Because Step 2 stopped creating `report_draft` rows, any report created from
31 Jul 2026 onward has no draft twin, and inserting its cash count violates
that FK:

```
insert or update on table "report_cash_count" violates foreign key
constraint "report_cash_count_report_id_fkey"
```

**Saving a cash count on a newly created report fails until `r8a08` runs.**
Reproduced against the live schema on 3 Aug 2026. It had not surfaced only
because no report had been created since the Step 2 deploy — every existing
report still had its pre-flip draft twin.

This is the `s6a06` failure mode inverted: there, code stopped writing
something the schema still demanded; here, the schema demands a parent row the
code no longer creates.

Steps 2 and 3 also deleted both mirrors, so `report_draft` and
`shop_expense_draft` have no writers left. **Step 4 is not the next step** —
three tables (`report_cashcount_draft`, `report_expense_detail`,
`report_detail`) still have live writers and are covered by Step 3.5.

Steps 1–3 were deployed on 31 Jul 2026.


---

## Start here

If you are picking this up cold, in order:

1. Read **Where things stand** and **The invariant** — five minutes, and every
   later step depends on them.
2. Read **Order of operations**. The schema-first/code-first direction flips
   partway through and getting it wrong takes production down.
3. Run the **verification checklist** against the current deploy to confirm the
   starting state is good.
4. Then **Step 3.5** — Steps 1 to 3 are already done (see Progress above).

Steps 2 and 3 removed both mirrors, so there is no longer a safety net: a
missed write site is lost data, not a stale read. The failure mode of this
codebase is silently wrong data rather than an exception, and the test suite
has caught none of the six production bugs this migration produced. Verify by
exercising the app, not by reading the diff.

---

## Where things stand

| Table | Status |
|---|---|
| `report_v2` | Retired. No reads, no writes, no FKs. **Droppable.** |
| `report_draft` | **No writers** (Step 2). 27 reads left to migrate. |
| `shop_expense_draft` | **No writers** (Step 3). 3 reads left. |
| `report_history_draft` | Write-free (callers redirected). **Droppable.** |
| `report_cashcount_draft` | Still written — 5 sites. **Step 3.5.** |
| `report_expense_detail` | Still written — 4 sites. **Step 3.5.** |
| `report_detail` | Still written — 2 sites. **Step 3.5.** |

Migration chain (localhost head: `r10a10_drop_legacy_report`):

    r1a01 ... r6a06  ->  r7a07_backfill_actual_cash
                     ->  r8a08_repoint_rcc_fk
                     ->  r9a09_reshape_xero_pks
                     ->  r10a10_drop_legacy_report   <- IRREVERSIBLE

`r9a09` deliberately precedes `r10a10`: it is reversible and independent, and
the drops should be the last thing that ever runs. Every one has a `.sql` twin
in `migrations/` for the Supabase path — run the `.sql` **or** the `.py`, never
both.

### The two mirrors — REMOVED

Two `before_flush` listeners kept the real row current while the drafts were
still the write target. Both were deleted at the end of Steps 2 and 3, once
their tables had no writers left.

**This means the safety net is gone.** While a mirror was running, a missed
site degraded to a stale read. Now it is lost data. Verify writes are actually
gone before deleting anything else:

```
grep -rn "ReportDraft(\|ShopExpenseDraft(" blueprints/ | grep -v import
```

### The invariant everything rests on

> **A draft and its real row share one id.**

`Report.id == ReportDraft.id` (`ending.py` joins on exactly that), and
`ShopExpense.id == ShopExpenseDraft.id` (`ending.py:1617` copies reusing the
primary key). Every re-pointed FK below is therefore a constraint change with
**no data movement** — the values are already correct.

### If something breaks

Every migration `r1a01`–`r6a06` has a `DOWN` section at the foot of its `.sql`
twin. Two things are **not** reversible by those:

* `r0` PART 3 / `r5a05` **inserted rows**. Undoing those needs a backup — the
  `DOWN` cannot distinguish a backfilled row from one the app has created since.
* Once the write flip ships, `report_draft` stops receiving writes. Rolling the
  *code* back without rolling the schema back is safe (drafts resume, the
  mirror catches up). Rolling the schema back after the flip is not.

The safest rollback at any point before Step 4 is **redeploy the previous code
revision** and leave the schema alone. Every schema change so far is
additive or a constraint re-point; old code runs against it unchanged.

---

## Order of operations

Read this before starting anything.

| # | Change | Type | Deploy order |
|---|---|---|---|
| 1 | `r6a06` FK re-point | Schema | **Schema first**, then code |
| 2 | Report write flip | Code | Code only |
| 3 | Expense write flip | Code | Code only |
| 3.5 | Cash-count / detail tables | Code | Code only |
| 4 | Drops | Schema | **Code first**, then schema |

The direction flips between 1 and 4, and getting it backwards is what caused
the worst incident in this project:

* **Adding** something (a column, a wider constraint) → schema first. New code
  needs it to exist; old code ignores it.
* **Removing** something (a table, a constraint) → code first. The schema must
  keep satisfying the old code until that code is gone.

Deploying the Stage 4a code before its columns existed produced
`column report.status does not exist` on every request that touched a report.

---

## Step 1 — Apply `r6a06` (schema)  ✅ DONE

Re-points the last three FKs off `report_draft`:

| Table | Column | New target |
|---|---|---|
| `shop_expense_draft` | `report_draft_id` | `report.id` |
| `report_cashcount_draft` | `report_id` | `report.id` (CASCADE) |
| `report_history_draft` | `report_draft_id` | `report.id` (CASCADE) |

**Why it must come first.** These three are what block the write flip. Pointing
writes at `report` means draft rows stop being created, and the next insert
into any of these violates its FK. That is the `s6a06` failure mode — code
ceasing to write something the schema still demands.

**Run:** `migrations/r6a06_repoint_draft_child_fks.sql` (ends in `ROLLBACK`;
read the counts, then flip to `COMMIT`). Or `alembic upgrade head`, which also
stamps the version.

The pre-flight aborts naming every table with orphaned rows. If it fires,
confirm the `r0` PART 3 backfill was applied — do not force past it.

**Deploy order:** schema first, then the code. Re-pointing the FK is
backwards-compatible — old code keeps writing draft rows and they still satisfy
the new constraint, because draft id == report id.

**Code that ships with it** (already written, currently uncommitted):
the three child models' FK declarations, the removal of `ReportDraft`'s three
back-relationships, and the `history_query.py` joinedload that depended on
them.

**Verify:** the script's final block prints `-> report_draft : 0`. Then walk a
report end to end: opening → sales → expense → deposit → cash count → submit.

---

## Step 2 — The report write flip (code)  ✅ DONE

**This is the largest remaining piece. Give it a fresh session.**

It is *not* a set of query substitutions. Flipping a lookup to `Report` means
the paired `ReportDraft(...)` **creation** site must flip too, or a draft gets
created in one table and updated in the other. That half-flipped state produces
silently wrong data, not an exception.

### Creation sites (5) — these define the work

| File | Line | Context |
|---|---|---|
| `routes/opening.py` | 567 | Edit mode; a `Report` already exists |
| `routes/opening.py` | 772 | **New draft** — the main path |
| `services/ending.py` | 135 | Revert-to-draft; a `Report` exists |
| `services/ending.py` | 502 | Self-heal: `Report` exists, draft missing |
| `services/shared.py` | 445 | `seed_opening_draft` (onboarding) |

Three of these (`opening.py:567`, `ending.py:135`, `ending.py:502`) already
take their id from an existing `Report`, so they only need to stop creating the
draft. `opening.py:772` and `shared.py:445` are the real work — they mint a new
id, and after the flip that id must come from a `Report` row instead.

### Write-through lookups (12)

Each reads a draft into a variable that is then mutated. Found with:

```
grep -rn "ReportDraft.query" blueprints/ | grep -v "status ==\|filter_by(id="
```

Concentrated in `routes/opening.py`, `routes/deposit.py`, `routes/cash_count.py`,
`routes/api.py`, `services/shared.py`, `services/ending.py`.

### Method

Work **one function at a time**, not one query at a time. For each:

1. Flip its creation site and its lookups together.
2. Confirm no `report_draft` write remains in that function.
3. Exercise that wizard step in the browser before moving on.

### Landmines

* **`sales.py` recovery path** is deliberately status-agnostic — it forces
  `status="draft"` after finding a row, so it must be able to find one the
  draft filter would exclude. Post-flip it can also match submitted reports,
  which means the forced flip could un-submit one. Revisit when you reach it.
* **Rollback diagnostics** in `cash_count.py` and `ending.py` verify the *draft
  row itself* survived. They must keep querying `ReportDraft` until it is
  dropped.
* **`opening.py` aliases** — `report_draft = any_draft_for_date` means a
  variable written later is not the one the query named. Grep for the alias,
  not just the query.

### What was done

All 5 creation sites and all 12 write-through lookups flipped, across
`opening.py`, `deposit.py`, `cash_count.py`, `api.py`, `ending.py` and
`shared.py`. `draft_report_mirror.py`, its registration and its tests deleted
after verifying zero remaining writes.

Two paths collapsed sharply, because `report` and `report_draft` became one row:

* **Submit** went from 124 lines to 22. It had been building a `Report` from
  `current_draft` field by field — self-assignment once they are the same row.
  What remains is the recalculated `closing_balance`, `date`, `uploaded_by`,
  and `status = "posted"`.
* **Revert** no longer deletes the `Report` and rebuilds it from the draft; it
  sets `status = "draft"`. That also fixed the old hazard where a report with
  no draft could not be reverted at all. `ShopExpense` rows are still deleted —
  those belong to the submitted report and are rebuilt on re-submit.

A ~50-line self-heal block in `ending.py` was deleted outright: it existed to
create a `ReportDraft` when a `Report` had none, which is no longer reachable.

**Known consequence — RESOLVED in Step 4, but not as predicted.**
`sync_same_day_draft_after_deposit_change` was expected to become a guaranteed
no-op. It did not: the `Report.id != report_to_update.id` guard meant it could
still match a SIBLING draft for the same (company, date), and duplicates per
date do occur.

It was deleted in Step 4 for a stronger reason — its meaning had inverted.
"Sync my own draft" became "overwrite a DIFFERENT report's `bank_deposit` and
recalculate its balances". A separate in-progress report for the same date is
not this report, so that is data corruption, not a sync. Next-day chaining is
unaffected and still handled by `propagate_opening_balance_to_next_day_draft`.

---

## Step 3 — The expense write flip (code)  ✅ DONE

Same shape, smaller. Four `ShopExpenseDraft(...)` creation sites:
`routes/expense.py:428`, `routes/api.py:398`, `:691`, `:1761`.

Reads are already migrated, so this is writes only.

### What was done

All 4 creation sites flipped to `ShopExpense` (`report_draft_id` →
`report_id`), 3 `.get()` lookups feeding updates and deletes re-pointed, 4
deletes in `report_detail.py` re-pointed, and the 4 now-redundant
`ensure_shop_expense_for_draft` calls removed — the row created *is* the
`shop_expense`. `expense_draft_mirror.py`, its registration and its tests
deleted after verifying zero remaining writes.

One structural test updated: `test_delete_report_cleanup.py` greps source text
for the old query string, so the assertion was re-pointed at the new table.
Behaviour unchanged.

---

## Step 3.5 — The cash-count and detail tables (code) ✅ DONE

Steps 2 and 3 covered `report_draft` and `shop_expense_draft`. Three tables
were never in their scope and still have live writers. **Step 4 cannot start
until these are done.**

Current state (verified by counting reads/writes outside `models/`):

| Table | Reads | Writes |
|---|---|---|
| `report_cashcount_draft` | 14 | 5 |
| `report_expense_detail` | 3 | 4 |
| `report_detail` | 2 | 2 |

### `report_cashcount_draft`

Its columns split three ways, and **the destination differs per group** — this
is not a single-table flip like Steps 2 and 3:

| Columns | Destination | Status |
|---|---|---|
| `thousand_note` … `one_coin` (9 denominations) | `report_cash_count` **rows** | Already dual-written by `cash_count.py` |
| `safe_box_balance`, `discrepancy_*` | `report` | Already on `report`; already dual-written |
| `actual_cash_total` | `report` | Hoisted by `r1a01`; `opening.py` already prefers it |

So every value already has a home and is already being written there. What
remains is deleting the writes to this table and re-pointing the 14 reads.

Note the denominations are a *shape* change: nine wide columns become nine
rows keyed on `cash_id`. `cash_denominations.py` already reads
`report_cash_count` first and falls back to the wide columns — removing that
fallback is the last step, and `c2a02` only backfilled HKD, so check other
currencies before removing it.

Write sites: `cash_count.py:369` (create), `api.py:1166` (mutate),
`report_detail.py:396/421/495/511` (delete).

### `report_detail`

Duplicates `report`. Its distinct columns (`cashsale_total`,
`nocashsale_total`, `expense_total`, `discrepancy_description`) are all
derivable from `report` or already mirrored onto it —
`discrepancy_description` was backfilled into `report.discrepancy_reason` by
`r0` PART 1c.

Only one reader: `api.py:1207`. Write sites: `cash_count.py:399/444`,
`api.py:1174`.

The composite PK is `(report_id, entity_id)` with **no FK on `report_id`**, so
nothing constrains it — the drop needs no FK work.

### `report_expense_detail`

Duplicates `shop_expense` for the same expense. `expense_id` is its PK and
plays the role `shop_expense.id` does; `description` maps to `remarks`,
`info_filepath` to `files`, `create_at` has no counterpart and is unused.

Write sites: `api.py:450/732`, `expense.py:519`, `api.py:913` (mutate),
`report_detail.py:376` (delete). Reads: `publish.py:1329` matters —
`validate_expenses_for_system_accounts` genuinely reads it.

Its FK was re-pointed at `report.id` in `r4a04`, so the values are already
correct if anything needs migrating.

### Method

Same as Steps 2 and 3: **one function at a time**, creation site and its
lookups together, exercise the step in the browser before moving on.

Unlike Steps 2 and 3 there is no mirror to remove afterwards — these tables
never had one, because their values were already being dual-written by the
application itself.

### Before starting

Confirm the dual-writes really are complete, or the flip loses data:

```sql
-- Cash counts present as rows? (should match, per report)
SELECT c.report_id,
       (SELECT count(*) FROM pettycashv2.report_cash_count rc
         WHERE rc.report_id = c.report_id) AS rows_present
  FROM pettycashv2.report_cashcount_draft c
 WHERE (SELECT count(*) FROM pettycashv2.report_cash_count rc
         WHERE rc.report_id = c.report_id) = 0
   AND (c.thousand_note IS NOT NULL OR c.onehundred_note IS NOT NULL);
-- Rows returned = cash counts that exist ONLY as wide columns. Investigate.
```

> **⚠️ This query over-reports (verified 3 Aug 2026 — it returned 8, all false
> positives).** `save_cash_count_details` deliberately stores **no** row for a
> denomination counted as zero, so an all-zero cash count correctly has no
> `report_cash_count` rows — while its wide columns are `0`, not NULL, so the
> `IS NOT NULL` test still matches. Always check the column TOTAL before
> investigating; only a non-zero total is a real gap:
>
> ```sql
> SELECT c.report_id,
>        COALESCE(c.thousand_note,0)*1000 + COALESCE(c.fivehundred_note,0)*500
>      + COALESCE(c.onehundred_note,0)*100 + COALESCE(c.fifty_note,0)*50
>      + COALESCE(c.twenty_note,0)*20  + COALESCE(c.ten_note,0)*10
>      + COALESCE(c.five_coin,0)*5     + COALESCE(c.two_coin,0)*2
>      + COALESCE(c.one_coin,0)*1 AS col_total
>   FROM pettycashv2.report_cashcount_draft c
>  WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report_cash_count rc
>                     WHERE rc.report_id = c.report_id);
> -- col_total = 0  -> all-zero count, correct, ignore
> -- col_total > 0  -> a REAL gap. Investigate.
> ```

---

## Step 4 — Drops (schema, IRREVERSIBLE)

**Take a backup first.** Nothing below can be undone without one.

Only after Steps 2, 3 **and 3.5** have soaked in production for at least a few
days. Three of the seven tables below still had live writers after Step 3 —
confirm the counts in Step 3.5 are all zero before starting.

Drop in this order (children before parents):

1. `report_history_draft`
2. `shop_expense_draft`
3. `report_cashcount_draft` — **check `actual_cash_total` first** (below)
4. `report_expense_detail`
5. `report_detail`
6. `report_draft`
7. `report_v2`

### Before dropping `report_cashcount_draft`

`actual_cash_total` seeds the *next* report's opening balance
(`create.py:288`, `opening.py:1044`). `r1a01` hoisted it onto `report`, and
`opening.py` now prefers the `report` column.

> **⚠️ Corrected 3 Aug 2026.** `report.actual_cash_total` **never had a
> writer** — every assignment targeted `cashcount_draft`, and the draft mirror
> excluded the column by design, so the preferred read always found NULL and
> fell through. This check therefore FAILS on the pre-3.5 codebase, and
> "backfill before dropping" was not sufficient on its own: without adding the
> missing write, every report created afterwards loses the value again.
>
> Step 3.5 fixed both — `cash_count.py` now writes it, and
> `migrations/r7a07_backfill_actual_cash_total.sql` fills the history. **Run
> that migration before relying on the check below.**

Confirm no rows would lose it:

```sql
SELECT count(*)
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;
```

Must be `0`. If not, backfill before dropping.

### The Xero PK reshape (do it here)

`xero_report_sync.report_id` and `xero_bank_transfer.sync_report_id` were given
`ON DELETE CASCADE` in `r4a04` **only because** those columns sit in composite
primary keys, and a PK column cannot be `SET NULL`.

They are an audit trail of what was pushed to Xero — the record that detects a
double-publish. Deleting a local report arguably should not erase it. Reshaping
the PKs (surrogate key, FK column nullable) allows `ON DELETE SET NULL`.

This was flagged rather than decided. Decide it here.

---

## Known issues outside this work

Neither is caused by the consolidation; both predate it.

**Cross-tenant draft lookup — FIXED in Step 4a-3.** `publish.py` matched rows
on `transaction_date` **alone**, so it could return another entity's report.
Step 4a-3 rewrote those exact lines while collapsing the draft/posted branches,
so the fix landed there: the lookup now filters `Report.company == entity_id`.
Covered by `tests/test_report_consolidation_step4.py` (`TestPublishReportLookupIsTenantScoped`),
which also pins the two things that must NOT change — no status filter (publish
runs after submit) and a None-guard before `.id` is read.

**No HTTP timeouts — STILL OPEN, deliberately out of scope.** 35 `requests`
calls set no timeout; only `services/auth/token_service.py:79` does, fixed
after it hung a worker until gunicorn killed it mid-response. Every other call
can do the same. Unrelated to the consolidation and untouched by it — worth its
own pass.

**Export PDF was broken independently — FIXED 4 Aug 2026.** `app.root_path`
resolves to the app-factory package (`services/app_runtime/legacy`), which has
no `static/`, so `Daily_Report_Template.docx` was never found and the export
500'd with "missing the report template". Now uses `app.static_folder`; the two
`temp` paths in the same file were re-pointed at `app.instance_path` for the
same reason. Pre-existing, not caused by this work.

---

## Verification checklist

Run after each deploy.

| Check | Expect |
|---|---|
| Onboard a new entity → all-set page | Completes, no "already exists" |
| Dashboard after onboarding | Report shows as **draft**, not completed |
| Calendar | The onboarding date is clickable |
| Open draft → sales | No date-sequence bounce |
| Draft with expenses → expense + ending pages | Expenses render |
| Delete a draft | Vanishes from dashboard and history, stays gone |
| Submit a report | Succeeds; expenses carry over with receipts |
| **Publish to Xero** | Succeeds; `publishing_status` reaches `completed` |
| Next report's opening balance | Equals the previous closing balance, not 0 |

Everything in this table was verified working end to end on 31 Jul 2026, Xero
publish included (it was the last to be fixed — see the lifecycle lesson below).

### Useful queries

```sql
-- Reports with no status (should be 0 after the NULL-safe pass)
SELECT count(*) FROM pettycashv2.report WHERE status IS NULL;

-- Drafts with no paired report row (should be 0)
SELECT count(*) FROM pettycashv2.report_draft d
 WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report r WHERE r.id = d.id);

-- Draft expenses with no paired shop_expense row (should be 0)
SELECT count(*) FROM pettycashv2.shop_expense_draft d
 WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.shop_expense e WHERE e.id = d.id);

-- Anything still pointing at report_draft (should be 0 after r6a06)
SELECT cl.relname AS child, con.conname
  FROM pg_constraint con
  JOIN pg_class cl ON cl.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
  JOIN pg_class rcl ON rcl.oid = con.confrelid
 WHERE con.contype='f' AND ns.nspname='pettycashv2'
   AND rcl.relname='report_draft';
```

---

## Three lessons worth carrying

**"A row in `report` means submitted" is no longer true.** Since Stage 4a,
drafts live there too. Every query written before that carries the old
assumption. Six production incidents came from this, each in a different
shape: `WHERE` clauses, a hardcoded `"posted"` dict literal, a template
class-name sniff, and a variable reused by both a guard and a balance
calculation. When touching anything that reads `report`, ask which it means.

**A filter is only correct for a point in the lifecycle.** Three of the bugs
were caused by *fixes* — a predicate that was right in one place, applied where
the opposite meaning held:

| Query | Correct reading |
|---|---|
| `last_report` in a date-sequence guard | Submitted only |
| `last_report` for balance chaining | Any status — a draft's closing balance is what the next report opens from |
| `report_draft` during data entry | `status == 'draft'` |
| `report_draft` in the Xero publish path | **No status filter** — publishing runs *after* submit, so the row is `posted` |

That last one broke every Xero publish: `publish.py` dereferenced
`.cash_addition` and `.first().id` on a lookup that had become `None`. Before
adding a predicate, ask **when in the lifecycle** the code runs, not just what
the variable is called.

**Status filters must be NULL-safe.** `status != 'draft'` evaluates to NULL —
not true — for a NULL-status row, silently excluding it from every "submitted"
query. Use `db.or_(Report.status.is_(None), Report.status != "draft")`. Rows
with NULL status exist: `r0` PART 1 left them wherever a report had no matching
draft.

---

## Test suite

The suite sits at **56 failed / 286 passed** and has done throughout. Those 56
are pre-existing and unrelated — 31 are `test_invitation.py` alone. None of the
six production bugs was caught by a test.

Before any further change, capture the baseline and diff against it:

```
python3 -m pytest tests/ -q 2>&1 | grep "^FAILED" | sort > /tmp/before.txt
# ... make changes ...
python3 -m pytest tests/ -q 2>&1 | grep "^FAILED" | sort > /tmp/after.txt
comm -13 /tmp/before.txt /tmp/after.txt      # empty == no regressions
```

Fixing those 56 would make Step 2 substantially safer. It is the single highest
-value thing that is not on the critical path.