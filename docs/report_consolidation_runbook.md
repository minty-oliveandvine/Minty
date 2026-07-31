# Report Consolidation — Remaining Work Runbook

**Goal:** collapse seven tables into `report` and `shop_expense`, so a report
is one row and an expense is one row, rather than a draft/real pair that must
be kept in sync.

**Target:** the live `pettycashv2` schema.

This runbook is self-contained. It covers what is **left**; the completed
stages are summarised only enough to explain why the remaining ones are safe.

Companion to `docs/cash_denomination_migration_runbook.md` — same structure.
The two are independent.

**Status as of 31 Jul 2026:** the application is fully working, Xero publish
included. Everything below is scaffolding removal. There is no deadline, and
nothing degrades if it waits.
we have finished step 2 and it is currently being deployed, only need to dro pthe columnbs 


---

## Start here

If you are picking this up cold, in order:

1. Read **Where things stand** and **The invariant** — five minutes, and every
   later step depends on them.
2. Read **Order of operations**. The schema-first/code-first direction flips
   partway through and getting it wrong takes production down.
3. Run the **verification checklist** against the current deploy to confirm the
   starting state is good.
4. Then Step 1.

Do not start Step 2 at the end of a working day. It touches every wizard write
path, and the failure mode of this codebase is silently wrong data rather than
an exception — the test suite has caught none of the six production bugs this
migration produced.

---

## Where things stand

| Table | Status |
|---|---|
| `report_v2` | Retired. No reads, no writes, no FKs. **Droppable.** |
| `report_draft` | Still the WRITE target. Reads mostly migrated. |
| `shop_expense_draft` | Still the WRITE target. Reads migrated. |
| `report_history_draft` | Write-free (callers redirected). **Droppable.** |
| `report_cashcount_draft` | Still written by the cash-count step. |
| `report_expense_detail` | Written by expense routes; no longer read. |
| `report_detail` | Written by cash-count; read once in `api.py`. |

Applied migrations: `r1a01` → `r5a05`. Alembic head is `r5a05_backfill_expense`.
`r6a06` is **written but not yet applied** (see Step 1).

### The two mirrors

Two `before_flush` listeners keep the real row current while the draft is
still the write target:

* `blueprints/report/services/draft_report_mirror.py` — 27 columns,
  `report_draft` → `report`
* `blueprints/report/services/expense_draft_mirror.py` — 10 columns,
  `shop_expense_draft` → `shop_expense`

Both are **temporary scaffolding**. They are deleted in Step 3 once writes
land on the real tables directly. Both have tests
(`tests/test_draft_report_mirror.py`, `tests/test_expense_draft_mirror.py`) —
keep them passing until the mirrors are removed, because a listener that stops
firing raises nothing; reads just silently go stale.

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

## Step 1 — Apply `r6a06` (schema)

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

## Step 2 — The report write flip (code)

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

### When done

Delete `draft_report_mirror.py`, its registration in `models/db.py`, and
`tests/test_draft_report_mirror.py`.

---

## Step 3 — The expense write flip (code)

Same shape, smaller. Four `ShopExpenseDraft(...)` creation sites:
`routes/expense.py:428`, `routes/api.py:398`, `:691`, `:1761`.

Reads are already migrated, so this is writes only.

When done, delete `expense_draft_mirror.py`, its registration, and
`tests/test_expense_draft_mirror.py`.

---

## Step 4 — Drops (schema, IRREVERSIBLE)

**Take a backup first.** Nothing below can be undone without one.

Only after Steps 2 and 3 have soaked in production for at least a few days.

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
`opening.py` now prefers the `report` column. Confirm no rows would lose it:

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

**Cross-tenant draft lookup.** `blueprints/xero/services/publish.py:461` matches
rows on `transaction_date` **alone — no company filter**, so it can return
another entity's report. Left visible with a comment rather than silently
patched. Deserves its own fix and a test.

**No HTTP timeouts.** No `requests` call in the codebase sets one except
`services/auth/token_service.py:79`, fixed after it hung a worker until
gunicorn killed it mid-response. Every other call can do the same.

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
