# Report Consolidation — Step 4 Implementation Plan

**Scope:** Step 4 only. Steps 1–3 are deployed; Step 3.5 is code-complete and
awaits `r7a07` + browser verification. Companion to
`docs/archive/runbooks/report_consolidation_runbook.md`, which stays the index.

**Written:** 3 Aug 2026, against the working tree on
`report/step-3.5-implementation`.

---

## Implementation status — updated 3 Aug 2026

| Unit | State |
|---|---|
| 4a-1 `ReportDetail` / `ReportExpenseDetail` | **DONE** (nothing to do — Step 3.5 cleared them) |
| 4a-2 `ReportV2` | **DONE** |
| 4a-3 `ShopExpenseDraft` | **DONE** — incl. the publish.py cross-tenant fix |
| 4a-4 `ReportHistoryDraft` | **DONE** — G5 now passes |
| 4a-5 `ReportCashCountDraft` | **DONE** — fallback removed; currency check was clean |
| 4a-6 `ReportDraft` | **DONE** — all 27 sites |
| 4b models | **DONE** — 7 model files + registries deleted; mapper gate passes |
| 4c `r10a10` drops | **RUN ON LOCALHOST** — 9 tables dropped. NOT run on production |
| 4d `r9a09` Xero PKs | **DONE** — option B, applied locally and verified |

### 🔴 Two findings from running 4c locally

**1. Two tables the runbook believed were gone still existed.**
`report_cash_detail` and `report_history_v2` both still FK'd `report_v2`, and
P3 blocked the drop. `r0`'s PART 2 header states they "were dead and were
removed in Stage 0" — they were not. Both were empty (0 rows) and unmapped by
the application, so `r10a10` now drops them as PART 0, with an emptiness guard
that aborts if either turns out to be populated on another environment.

**2. The ending page raised `AttributeError: actual_cash_total`.**
`ending.py`'s `with_entities(...)` Row did not select `Report.actual_cash_total`,
which 4a-5 reads to decide whether a report was counted at all. Tests and
`import main` both passed; only driving the route surfaced it. Fixed by adding
the column to the select.

**This is the argument for running 4c locally before production.** Neither
finding was reachable by the test suite, ruff, or the mapper-configuration
gate — both needed a real `DROP TABLE` plus a real request.

**Revision numbering corrected.** This doc originally assigned `r8a08` to the
drops, but `r8a08_repoint_rcc_fk` was already taken — it fixes the
`report_cash_count.report_id` FK that `r6a06` missed (a live bug; see the
parent runbook). The chain is now:

    r7a07_backfill_actual_cash -> r8a08_repoint_rcc_fk -> r9a09_reshape_xero_pks -> r10a10 (drops, unwritten)

`r9a09` deliberately precedes `r10a10`: it is reversible and independent, and
the drops should be the last thing that ever runs.

### ✅ 4a-5 is NOT blocked — the currency check is clear

The query in 4a-5 **over-reports**, the same way the parent runbook's P1 does.
`save_cash_count_details` stores **no row** for a denomination counted as zero,
so an all-zero cash count correctly has no `report_cash_count` rows — while its
wide columns are `0`, not NULL, so `IS NOT NULL` still matches.

Run against the live schema on 3 Aug 2026: the query as written returned 5 rows
for one currency; filtering to a **non-zero column total** returned **none**.
Only HKD and one `ALL` entity are in use. Use this form instead:

```sql
SELECT COALESCE(cu.currency_code,'(none)'), count(*) AS wide_only_nonzero
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r   ON r.id = c.report_id
  JOIN pettycashv2.entities e ON e.id = r.company
  LEFT JOIN pettycashv2.currency_info cu ON cu.id = e.currency_id
 WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report_cash_count rc
                    WHERE rc.report_id = c.report_id)
   AND (COALESCE(c.thousand_note,0)*1000 + COALESCE(c.fivehundred_note,0)*500
       +COALESCE(c.onehundred_note,0)*100 + COALESCE(c.fifty_note,0)*50
       +COALESCE(c.twenty_note,0)*20  + COALESCE(c.ten_note,0)*10
       +COALESCE(c.five_coin,0)*5     + COALESCE(c.two_coin,0)*2
       +COALESCE(c.one_coin,0)*1) > 0
 GROUP BY 1;
```

Re-run on production before deleting the fallback, but the shape holds.

### ⚠️ 4a-2 and 4d were coupled — resolved

4a-2 as originally specified would have **defeated 4d entirely**.
`_delete_report_children` (renamed from `_delete_report_v2_cascade`) explicitly
deleted `xero_report_sync` and `xero_bank_transfer` rows. Reshaping their FKs to
`SET NULL` preserves nothing if the application deletes the rows itself first.

Both halves shipped together: the two explicit deletes were removed in 4a-2
(a no-op while the FKs still CASCADE) and `r9a09` flips the FKs. Verified by
deleting a report and confirming the audit row survives with a NULL
`report_id`.

---

## The headline: Step 4 is not "drop seven tables"

The parent runbook lists Step 4 as *Drops (schema)*. That is the last 10% of
it. A source sweep of the current tree finds the legacy models still
referenced in **~120 live code sites across 22 files** — not comments, not
imports, actual queries:

| Table / model | Live code sites outside `models/` | Where |
|---|---|---|
| `ReportDraft` | **~75** (27 distinct query sites) | `sales.py`, `report_detail.py` (routes + services), `expense.py`, `ending.py`, `history_query.py`, `shared.py`, `publish.py`, `create.py`, `cash_count.py`, `deposit.py`, `api.py`, `module_guard.py` |
| `ShopExpenseDraft` | 8 | `publish.py:494–501`, `module_guard.py:85/92` |
| `ReportCashCountDraft` | 14 | `cash_count.py`, `create.py`, `opening.py`, `export_screenshot.py`, `ending.py`, `cash_denominations.py`, 4 deletes in `report_detail.py` |
| `ReportHistoryDraft` | 1 writer + 1 relationship | `history.py:85` (`log_history_draft`), `user.py:48` |
| `ReportV2` | 1 read + 1 delete + 1 relationship | `entity/services/shared.py:248`, `report_detail.py:382`, `entity.py:54` |
| `ReportDetail` | **0** | model + registry only |
| `ReportExpenseDetail` | **0** | model + registry only |

`DROP TABLE` on a table a mapper still points at does not fail at deploy time.
It fails at the first request that touches it, with a `ProgrammingError` from
the middle of a route. **The code has to go first**, and that is the bulk of
the work.

So Step 4 splits into three units, in this order:

| Unit | Change | Type | Deploy |
|---|---|---|---|
| **4a** | Remove the remaining reads | Code | Code only |
| **4b** | Remove the models and registry entries | Code | Code only |
| **4c** | `r10a10` — drop the seven tables | Schema | **After 4a+4b have soaked** |
| **4d** | Xero PK reshape (a decision, not a given) | Schema | Optional, independent |

Direction is **code first, then schema** for all of it — the opposite of
Step 1. The schema must keep satisfying the old code until that code is gone.

---

## Gate — do not start 4a until all of these are true

| # | Condition | How to check |
|---|---|---|
| G1 | `r7a07` applied to `pettycashv2` | `SELECT count(*) FROM pettycashv2.report WHERE actual_cash_total IS NOT NULL;` > 0, and the check in G2 passes |
| G2 | No report would lose `actual_cash_total` | the pre-drop query below returns `0` |
| G3 | Step 3.5 verified in the browser | full wizard walk: opening → sales → expense → deposit → cash count → submit → Xero publish |
| G4 | Step 3.5 soaked in production ≥ 3 days | deploy log |
| G5 | Zero writers to all seven tables | grep block below returns nothing |
| G6 | Backup taken | before 4c only, but take it early |

```sql
-- G2 — must be 0
SELECT count(*)
  FROM pettycashv2.report_cashcount_draft c
  JOIN pettycashv2.report r ON r.id = c.report_id
 WHERE c.actual_cash_total IS NOT NULL
   AND r.actual_cash_total IS NULL;
```

```bash
# G5 — must return nothing but the model definitions themselves
grep -rn "ReportDraft(\|ShopExpenseDraft(\|ReportCashCountDraft(\|ReportDetail(\|ReportExpenseDetail(\|ReportHistoryDraft(\|ReportV2(" \
  blueprints/ | grep -v "^blueprints/report/models/" | grep -v import
```

> **G5 now PASSES** — `log_history_draft` was deleted in 4a-4 (below). The
> original note is kept for context:
>
> **G5 previously FAILED.** `blueprints/report/services/history.py:85` still
> constructs `ReportHistoryDraft(...)` inside `log_history_draft`. The parent
> runbook records `report_history_draft` as "write-free (callers redirected)"
> — the *callers* were redirected, but the function was left behind. It has no
> remaining callers (`grep -rn "log_history_draft" blueprints/` finds only its
> own definition and two comments), so this is a dead function, not a live
> writer. **Delete the function in Unit 4a-4** and G5 passes.

---

## Unit 4a — remove the remaining reads

Order the tables by risk, cheapest and safest first, so the expensive one lands
last with the most confidence behind it. **One function at a time**, and
exercise the affected page in the browser before moving on — the parent
runbook's core lesson is that the test suite has caught none of the six
production bugs this migration produced.

### 4a-1 · `ReportDetail` and `ReportExpenseDetail` — nothing to do

Zero code sites. Step 3.5 already cleared them. They go straight to 4b.

### 4a-2 · `ReportV2` — 3 sites, all dead

| Site | Action |
|---|---|
| `entity/services/shared.py:246` `display_deposit_balance()` | **Delete the function.** `r2a02`'s own header records it as never called; confirmed — only its definition and a comment reference it. Drop the `ReportV2` import. |
| `report_detail.py:375–382` `delete_report_v2_cascade()` | Delete the `ReportV2.query.filter_by(report_id=...).delete()` and the helper, once `test_delete_report_cleanup.py` stops asserting on it |
| `entity/models/entity.py:53–55` `report_v2` relationship | Delete. Follows the same reasoning as the `ReportDetail` relationship already removed above it |

`tests/test_delete_report_cleanup.py` greps source *text* for
`ReportV2\.query\.filter_by\(.*report_id.*\)\.delete\(\)` (line 152) and for
`"ReportV2" in source` (line 116). Those assertions must be deleted, not
re-pointed — there is no successor table. Same pattern as the
`ReportExpenseDetail` removal already done in Step 3.5 (see its note at
line 96).

### 4a-3 · `ShopExpenseDraft` — 2 real sites

| Site | Action |
|---|---|
| `module_guard.py:85` | `ShopExpenseDraft.query.get(expense_id)` → `ShopExpense.query.get(...)`. The ids are equal by the invariant, so this is a lookup-target change with no behaviour change |
| `module_guard.py:92` | same, for `draft_id` |
| `publish.py:494–501` | The draft-report branch of `_find_expense`. Since Step 3 the expense row *is* the `ShopExpense`, and `report_draft_id` → `report_id`. Collapse the two branches into one `ShopExpense` query |
| `publish.py:287` and the `report_id=None` comment | Once the branches collapse, the parameter's "None for draft reports" contract is gone. Simplify the signature |

`publish.py` is the highest-consequence file in this unit — the lifecycle
lesson in the parent runbook ("no status filter in the publish path") was
learned here. Do not add a status predicate while collapsing these branches.

### 4a-4 · `ReportHistoryDraft` — 2 sites

| Site | Action |
|---|---|
| `services/history.py:63–102` `log_history_draft()` | **Delete the whole function** and the `ReportHistoryDraft` import. No callers |
| `auth/models/user.py:48` `report_history_drafts` relationship | Delete |

`history_query.py:127` already documents that draft history lands in
`report_history`. Nothing reads the draft table.

### 4a-5 · `ReportCashCountDraft` — 14 sites, two distinct shapes

**Shape A — the four cascade deletes** (`report_detail.py:397/422/496/512).
Deliberately kept through Step 3.5. They become no-ops the moment the table is
dropped, and the FK is `ON DELETE CASCADE` off `report.id` anyway (r6a06), so
the database would clean up regardless. **Delete all four** plus the import.

**Shape B — the legacy read fallback.** These read the nine wide columns when a
report has no `report_cash_count` rows:

| Site | Role |
|---|---|
| `cash_denominations.py:186` | `get_cash_count_total()` implicit fallback lookup |
| `cash_denominations.py:275+` | `legacy_column_counts_for_report()` fallback |
| `export_screenshot.py:69` | passes `fallback_draft=` into the export |
| `cash_count.py:112`, `:222` | page-render fallbacks |
| `ending.py:643` (`legacy_cashcount`), `:895` | ending-page fallbacks |
| `create.py:312`, `opening.py:1119`, `:1166` | `actual_cash_total` fallback for the next report's opening balance |

Handle these in two groups, because they fail differently:

* **The `actual_cash_total` group** (`create.py`, `opening.py`) is fully
  covered once `r7a07` is applied and Step 3.5's writer is live. Delete the
  fallback branch — the `report` column now always has the value. This is the
  one group where G1/G2 are load-bearing.

* **The denomination group** (`cash_denominations.py` and its callers) is
  **not** fully covered. `c2a02` backfilled **HKD only**. Any entity on
  another currency has wide-column data with no `report_cash_count` rows, and
  removing the fallback silently zeroes their historical cash counts and
  404s their exports (`legacy_column_counts_for_report` returns `None`).

  **Run this before deleting the fallback:**

  ```sql
  -- Reports whose cash count exists ONLY as wide columns, by currency.
  -- Any non-zero row = a report that loses its count. Investigate before
  -- removing the fallback; backfill as r10a10 PART 0 if non-empty.
  SELECT e.currency_id, count(*) AS wide_only
    FROM pettycashv2.report_cashcount_draft c
    JOIN pettycashv2.report r  ON r.id = c.report_id
    JOIN pettycashv2.entities e ON e.id = r.company
   WHERE NOT EXISTS (SELECT 1 FROM pettycashv2.report_cash_count rc
                      WHERE rc.report_id = c.report_id)
     AND (c.thousand_note IS NOT NULL OR c.onehundred_note IS NOT NULL)
   GROUP BY e.currency_id;
  ```

  If it returns rows, the fallback removal is **blocked** until those counts
  are migrated to `report_cash_count`. That backfill is a `c5a05`-shaped job
  belonging to the cash-denomination runbook, not this one — and it is the
  single most likely thing to push Step 4 out. Check it first, not last.

### 4a-6 · `ReportDraft` — 27 query sites, the real work

Give this its own session, the way Step 2 got one.

Almost all of it is one recurring shape. Since Stage 4a a draft and its report
are **one row**, so:

```python
Report.query.join(ReportDraft, ReportDraft.id == Report.id, full=True)
    .with_entities(db.func.coalesce(Report.id, ReportDraft.id).label("id"), ...)
    .filter(db.or_(Report.company == entity_id, ReportDraft.company == entity_id))
```

collapses to a plain `Report.query.filter(Report.company == entity_id)`. The
full outer join, every `coalesce`, and every `or_` disappear.

**Full-outer-join sites (5):** `ending.py:689–703`,
`services/report_detail.py:565–589`, `sales.py:158–163`, `expense.py:235–260`,
`cash_count.py:123–126`, `deposit.py:125–128`.

**Plain draft lookups (13):** `api.py:1614`, `create.py:127–131`,
`expense.py:347–352`, `module_guard.py:72`, `report_detail.py:388/413/493/502/540/553/738/745`,
`sales.py:253/259/271/452/767/769`, `services/report_detail.py:292/620`,
`services/shared.py:529/619/624`, `history_query.py:49–67`,
`publish.py:460/481`.

**Rollback diagnostics (2):** `cash_count.py:402`, `ending.py:1669`. These
verify "the draft row itself survived". Post-drop there is no separate draft
row — **delete them**, do not re-point them at `Report` (that would assert the
row we just committed exists, which is vacuous).

**Dead imports (2):** `entity/services/onboarding_state.py:30`,
`entity/routes/list.py:19` import `ReportDraft` and never use it. Free wins.

**Template comment:** `templates/components/report_draft_header_badge.html:3`
mentions `ReportDraft` in a comment only — update the wording, nothing else.

**Tests:** `test_delete_report_cleanup.py:226/234` assert on the literal
strings `ReportDraft.id != report_draft.id` and `ReportDraft.id != report.id`.
Those source-text assertions must be re-pointed at whatever the collapsed
`report_detail.py` sibling-draft query becomes — or deleted if the sibling
query itself disappears (it likely does: "another draft for the same
company+date" is now "another report for the same company+date with
status='draft'").

#### The three landmines that survive into 4a-6

1. **Status filters are where the bugs are.** Every one of the 27 sites reads
   `report_draft`, which *implied* `status == 'draft'` by virtue of the table.
   Collapsing onto `Report` makes that implication vanish and you must state it
   explicitly — or deliberately not state it. The parent runbook's table is
   the checklist: date-sequence guards want submitted-only, balance chaining
   wants any status, data entry wants `status == 'draft'`, **and the Xero
   publish path wants no status filter at all** because it runs after submit.
   `publish.py:460/481` is in this list. That exact site broke every Xero
   publish once already.

2. **NULL-safety.** `status != 'draft'` is NULL for a NULL-status row and
   silently drops it. Use `db.or_(Report.status.is_(None), Report.status != "draft")`.
   NULL-status rows exist — `r0` PART 1 left them.

3. **`sales.py` recovery path** (`:452`, `:767–769`) is deliberately
   status-agnostic and forces `status="draft"` after finding a row. Post-flip
   it can match a *submitted* report and un-submit it. The parent runbook
   flagged this for Step 2 and it is still there. Fix it here: constrain the
   recovery lookup to `status == 'draft'` before it can force the flip.

4. **`publish.py:461` cross-tenant lookup.** Matches on `transaction_date`
   alone with no company filter. Pre-existing, not caused by this work, but
   4a-6 rewrites the exact lines. Fix it while you are in there — add
   `Report.company == entity_id` — and give it a test. It is a data-leak bug
   between tenants, and it will be cheaper here than ever again.

---

## Unit 4b — remove the models

Only after 4a is merged and every grep is clean. Purely mechanical:

1. Delete the seven model files under `blueprints/report/models/`:
   `report_draft.py`, `shop_expense_draft.py`, `report_cash_count_draft.py`,
   `report_detail.py`, `report_expense_detail.py`, `report_history_draft.py`,
   `report_v2.py`.
2. Remove their imports and `__all__` entries from
   `blueprints/report/models/__init__.py` (13 → 6 entries) and
   `models/db.py` (lines 25/27/28/29/31/33/36 and the seven `__all__` strings).
3. `python -c "import app"` — a stale `db.relationship("ReportV2", ...)`
   anywhere raises `InvalidRequestError` at mapper configuration, which is the
   cheapest possible detection of a missed site. **This import check is the
   gate for 4b.**
4. Full grep sweep:

   ```bash
   grep -rn "ReportDraft\|ShopExpenseDraft\|ReportCashCountDraft\|ReportDetail\|ReportExpenseDetail\|ReportHistoryDraft\|ReportV2" \
     blueprints/ models/ tests/ templates/ | grep -v pycache
   ```

   Only comments should remain, and prefer rewording those too — a comment
   naming a table that no longer exists is a trap for the next reader.

**Deploy 4a+4b together or 4a first — never 4b first.** 4b alone is safe (the
tables still exist, nothing reads them); the ordering matters only for review
sanity.

### Soak

Let 4a+4b run in production for **at least 3 days** before 4c. The tables are
still there, so any missed read still works — this window is precisely the
safety margin that `DROP TABLE` removes.

---

## Unit 4c — `r10a10`, the drops (IRREVERSIBLE)

**Take a backup immediately before running this.** Nothing below can be undone
without one. Write it as a twin pair matching every prior migration:
`migrations/versions/r10a10_drop_legacy_report_tables.py` and
`migrations/r10a10_drop_legacy_report_tables.sql`, revising
`r9a09_reshape_xero_pks` (the current head).

The `.sql` must end in `ROLLBACK;` with the change-to-`COMMIT` banner, per
house style (`r6a06`, `r7a07`).

### Pre-flight (aborts the transaction on any failure)

| # | Check | Expect |
|---|---|---|
| P1 | `actual_cash_total` would not be lost (the G2 query) | `0` |
| P2 | No cash count exists only as wide columns (the 4a-5 currency query) | empty |
| P3 | No FK anywhere still references any of the seven tables | empty |
| P4 | No view / materialized view depends on them | empty |

```sql
-- P3 — any FK still pointing at a table we are about to drop
SELECT cl.relname AS child, con.conname, rcl.relname AS parent
  FROM pg_constraint con
  JOIN pg_class cl      ON cl.oid  = con.conrelid
  JOIN pg_namespace ns  ON ns.oid  = cl.relnamespace
  JOIN pg_class rcl     ON rcl.oid = con.confrelid
 WHERE con.contype = 'f'
   AND ns.nspname = 'pettycashv2'
   AND rcl.relname IN ('report_draft','shop_expense_draft',
                       'report_cashcount_draft','report_history_draft',
                       'report_detail','report_expense_detail','report_v2');
```

### Drop order — children before parents

```sql
DROP TABLE pettycashv2.report_history_draft;
DROP TABLE pettycashv2.shop_expense_draft;
DROP TABLE pettycashv2.report_cashcount_draft;   -- P1 must have passed
DROP TABLE pettycashv2.report_expense_detail;
DROP TABLE pettycashv2.report_detail;
DROP TABLE pettycashv2.report_draft;
DROP TABLE pettycashv2.report_v2;
```

Use bare `DROP TABLE`, **never `CASCADE`**. If a drop fails on a dependency,
that dependency is something P3 missed and you want to know about it — not
have it silently removed.

### `DOWN`

Recreates the seven empty tables from their original DDL, for schema shape
only. **It does not restore data.** Say so in the header in the same terms
`r7a07` uses. Realistically the rollback for 4c is *restore the backup*; the
`DOWN` exists so `alembic downgrade` does not error.

---

## Unit 4d — the Xero PK reshape (a decision)

`xero_report_sync.report_id` and `xero_bank_transfer.sync_report_id` each sit
**inside a composite primary key** (confirmed in both models) and carry
`ON DELETE CASCADE`, given in `r4a04` *only because* a PK column cannot be
`SET NULL`.

These two tables are the audit trail of what was pushed to Xero — the record
that detects a double-publish. Today, deleting a local report erases that
record.

Three options:

| Option | Effect | Cost |
|---|---|---|
| **A — leave it** | Deleting a report erases its Xero audit trail | none |
| **B — reshape** | Drop the composite PK, keep `id` as sole PK, make the FK column nullable, re-point to `ON DELETE SET NULL` | one migration, both tables; `id` already exists with a `uuid4` default, so no data movement |
| **C — decouple** | Drop the FK entirely; keep `report_id` as a plain column | loses referential integrity, gains full independence |

**Recommendation: B.** `id` is already a populated `String(36)` primary-key
column on both tables, so the reshape is a constraint change with no data
migration — the same class of change as `r6a06`. It preserves the audit trail
across report deletion, which is the behaviour the trail exists for.

This is **independent of 4a–4c** and can ship before or after. Do not bundle
it into `r10a10` — an irreversible drop and a reversible constraint change do
not belong in one transaction. Give it `r9a09`.

---

## Verification

Run the parent runbook's full checklist after **each** of 4a+4b and 4c, not
just at the end. Additionally, specific to Step 4:

| Check | Expect | Why it is here |
|---|---|---|
| Next report's opening balance | equals previous closing balance, not `0` | the `actual_cash_total` fallback removal (4a-5) is the only thing that can break this, and it breaks silently |
| Open a **pre-`c2a02`, non-HKD** report's cash count | denominations render, export does not 404 | the fallback removal; the single highest-risk item in 4a |
| Report history page for a draft | entries appear | `log_history_draft` deletion (4a-4) |
| Delete a draft | vanishes from dashboard and history, stays gone | the four cascade deletes removed in 4a-5 |
| Publish to Xero — a **draft-origin** report | `publishing_status` reaches `completed` | `publish.py` branch collapse (4a-3) and the status-filter landmine |
| Publish the **same** report twice | second attempt detected as already published | the Xero audit trail; relevant if 4d ships |
| Two entities, same transaction date, both publish | each gets its own report | the `publish.py:461` cross-tenant fix |
| `python -c "import app"` | no `InvalidRequestError` | catches a missed mapper reference (4b) |

Capture the test baseline before starting and diff after, per the parent
runbook. The suite sits at 56 failed / 286 passed; the only expected
*intentional* change is `test_delete_report_cleanup.py`, whose `ReportV2` and
`ReportDraft` source-text assertions are removed or re-pointed in 4a-2 and
4a-6.

---

## Rollback

| Unit | Rollback |
|---|---|
| 4a, 4b | Redeploy the previous code revision. The schema is untouched and still satisfies it. Safe at any point |
| 4c | **Restore the backup.** The `DOWN` recreates empty tables only |
| 4d | `alembic downgrade` — a constraint change, fully reversible |

The safe stopping point is **after 4b**. If 4c has to wait weeks, nothing
degrades: seven unread tables cost nothing but confusion, and the confusion is
what this document is for.

---

## Estimate and sequencing

| Unit | Sites | Shape | Suggested session |
|---|---|---|---|
| 4a-1 | 0 | — | folds into 4b |
| 4a-2 `ReportV2` | 3 | delete dead code | ½ session |
| 4a-3 `ShopExpenseDraft` | 4 | branch collapse in `publish.py` | 1 session |
| 4a-4 `ReportHistoryDraft` | 2 | delete dead code | ½ session |
| 4a-5 `ReportCashCountDraft` | 14 | **blocked on the currency check** | 1–2 sessions |
| 4a-6 `ReportDraft` | 27 | join collapse + status semantics | **2–3 sessions, fresh** |
| 4b | 7 files + 2 registries | mechanical | ½ session |
| 4c `r10a10` | 1 migration | irreversible | ½ session + soak |
| 4d `r9a09` | 1 migration | independent | ½ session |

**Do the currency check in 4a-5 first, before writing any code.** It is the
one thing that can block Step 4 outright, it takes one query, and finding out
late means throwing away a finished unit.

---

## Open questions for the maintainer

1. **Non-HKD wide-column cash counts** — does the 4a-5 query return rows? If
   yes, a backfill has to precede Step 4, and it belongs in the cash
   denomination runbook.
2. **4d** — reshape the Xero PKs (B), or accept that deleting a report erases
   its publish audit trail (A)?
3. **`docs/archive/runbooks/report_consolidation_step_3_5_runbook.md`** is referenced by the
   parent runbook at line 34 but **does not exist** in `docs/`. If it was
   written and not committed, it should land before Step 4 begins — 4a-5
   depends on knowing exactly which fallbacks Step 3.5 deliberately left in
   place and why.
