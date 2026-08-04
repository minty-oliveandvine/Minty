# Report Consolidation — Step 3.5 (implemented)

**Status: CODE COMPLETE, NOT DEPLOYED.** Written after the fact, on 3 Aug 2026,
to record what Step 3.5 actually did — an earlier draft of this file was lost
in a rebase, and `report_consolidation_step_4_runbook.md` §4a-5 depends on
knowing exactly which fallbacks were deliberately left in place and why.

Companion to `docs/report_consolidation_runbook.md` (the index) and
`docs/report_consolidation_step_4_runbook.md` (what comes next).

**Baseline:** `17c6bcd2`, which contains `fe87216a` (Steps 1–3).

---

## What Step 3.5 removed

All writers to three tables. `grep -rn "ReportCashCountDraft(\|ReportDetail(\|
ReportExpenseDetail(" blueprints/` now returns only the model definitions.

| Table | Was | Now |
|---|---|---|
| `report_expense_detail` | 4 writes, 1 real read | no writers, no readers |
| `report_detail` | 4 writes, **0** real readers | no writers |
| `report_cashcount_draft` | 5 writes, 14 reads | no writers; reads reduced to the legacy fallback |

### Where each value went

| Was on `report_cashcount_draft` | Now |
|---|---|
| `thousand_note` … `one_coin` | `report_cash_count` rows, via `save_cash_count_details()` |
| `safe_box_balance`, `discrepancy_*` | `report` |
| `actual_cash_total` | `report` — **this needed a new writer**, see below |

`report_expense_detail` mapped onto `shop_expense` one-for-one
(`expense_id`→`id`, `description`→`remarks`, `info_filepath`→`files`;
`create_at` had no counterpart and was unused). Its only genuine reader,
`validate_expenses_for_system_accounts` in `publish.py`, reads `ShopExpense`
directly now — a wider net, not a narrower one, since `shop_expense` exists
from data entry after Step 3.

`report_detail` had **no readers at all**. The comment claiming
"Xero/exports read ReportDetail" was stale — `publish.py`, the download path
and the export-screenshot path all read `report`. Verified across `.py`,
`.sql`, `.js` and `.html`. **Supabase views were not checked** — do that before
the `r10a10` drop.

---

## Four defects found and fixed along the way

None were caused by Step 3.5. All were live on `fe87216a`.

### 1. `report.actual_cash_total` had no writer — `r7a07`

Every assignment targeted `cashcount_draft`; the draft→report mirror excluded
the column by design. So `opening.py`'s "prefer the `report` column" never once
took its primary branch — it always found NULL and fell through.

This matters because `actual_cash_total` seeds the **next** report's opening
balance whenever the previous report has no `closing_balance`. Deleting the
draft-table write without adding a `report` write would have silently zeroed it.

Fixed in two halves, both required:
* `cash_count.py` now assigns `current_draft.actual_cash_total` (which *is* the
  `report` row since Step 2).
* `migrations/r7a07_backfill_actual_cash_total.sql` fills the history.

`create.py` also gained the `report`-first preference that `opening.py` already
had, and `opening.py`'s second branch (the no-selected-date path) gained it too
— it had never been given the `r1a01` treatment.

### 2. `ending.py` joined through a table Step 2 stopped writing

```python
Report.query.outerjoin(ReportDraft, ReportDraft.id == Report.id)
    .outerjoin(ReportCashCountDraft,
               ReportCashCountDraft.report_id == ReportDraft.id)   # via the draft
```

Step 2 re-pointed this exact join in `cash_count.py` and `deposit.py` and left
a comment saying so. `ending.py` was missed. Since no `report_draft` rows are
created any more, the first join yields NULL for every report created after
31 Jul 2026 — so the second never matches.

Worse, `completed_sections`, `current_section` and `status` were **also**
coalesced off `ReportDraft` in the same query, so the ending page saw
`completed_sections = []` for those reports. All now read `Report` directly and
both joins are gone.

### 3. `deposit.py` was running a cartesian product

Step 2 removed the `ReportCashCountDraft` join but left 13 of its columns in
`with_entities`. Selecting from an unjoined table cross-joins it — so those
values came from an arbitrary **other** report's cash count. Nothing read them,
which is why it was invisible. Columns removed.

### 4. `report_cash_count.report_id` FK'd `report_draft` — `r8a08`

`r6a06` re-pointed three tables and missed this one: the new source-of-truth
table for denominations still pointed at the table being retired.

Because Step 2 stopped creating draft rows, **saving a cash count on any newly
created report raised `ForeignKeyViolation`.** Reproduced against the live
schema. It had not surfaced only because no report had been created since the
Step 2 deploy.

`r8a08_repoint_rcc_fk` re-points it at `report.id`. Verified: the insert that
previously failed now succeeds, and nothing references `report_draft` any more.

Two further latent crashes went with the same work: `ending.py` dereferenced
`cashcount_draft.discrepancy_*` with no None-guard, and rejected submit with
"Cash count data is missing" whenever that row was absent — both of which would
have become guaranteed failures the moment the writes were removed.

---

## What was deliberately LEFT IN — read this before Step 4a-5

Two things survive on purpose. Step 4 removes them.

### A. The legacy read fallback in `cash_denominations.py`

`get_cash_count_total()` and `legacy_column_counts_for_report()` fall back to
the nine wide columns when a report has no `report_cash_count` rows, for
reports predating the `c2a02` backfill. Callers passing `fallback_draft=`:
`cash_count.py` (×2), `ending.py` (×2), `export_screenshot.py`.

**Why it stayed:** `c2a02` backfilled **HKD only**. Removing the fallback while
non-HKD wide-column data exists silently zeroes those reports' cash totals and
404s their exports — no exception, just a wrong number.

**Status: unblocked.** The currency check returns nothing once all-zero counts
are excluded (see Step 4 doc §4a-5). Safe to remove in 4a-5, after re-running
that query on production.

### B. The four cascade deletes in `report_detail.py`

`ReportCashCountDraft.query.filter_by(...).delete()` at four sites. They only
remove **legacy** rows that still exist until the drop; removing them now would
orphan pre-Step-3.5 data for no gain. They go with `r10a10`.

### C. One thing NOT changed, on purpose

`cash_count.py`'s by-id `with_entities` deliberately does **not** select
`Report.status`, matching what it returned before. The template does
`current_draft.status != 'draft'` to decide readonly, and an absent attribute
makes that true — so that branch has always rendered read-only. Adding the
column would silently make the form editable. That is a behaviour change, not
scaffolding removal; it belongs in its own commit. There is a comment at the
site.

---

## New helper

`legacy_column_counts_for_report(report_id, fallback_draft=None)` in
`cash_denominations.py`. Returns `{legacy_column: quantity}` from count rows,
falling back to the wide columns, or `None` when neither source has anything.

It exists because the export renders a `.docx` via docxtpl whose placeholders
are addressed by face value (`qty1_1000`, `amt2_5`), so those keys had to
survive the migration verbatim. Matching is on `(value, type)` so the HK$10
note and HK$10 coin stay distinct — only the note lands in `ten_note`, exactly
as the wide columns behaved.

The `None` return is load-bearing: the export 404s on "no cash count" and must
**not** 404 on "counted, all zero".

---

## Migrations

| Revision | What |
|---|---|
| `r7a07_backfill_actual_cash` | fills `report.actual_cash_total` (fill-only, idempotent; `downgrade()` is a deliberate no-op) |
| `r8a08_repoint_rcc_fk` | `report_cash_count.report_id` → `report.id` |

Both applied to **localhost only** as of 3 Aug 2026. Production has neither.

---

## Verification state

| Check | Result |
|---|---|
| Test suite | 56 failed / 266 passed — same 56 as baseline, no regressions |
| `ruff --select F821,F401` | back to the pre-existing 7 / 11 |
| `python -c "import main"` | boots, 158 routes |
| Browser walkthrough | **NOT DONE** |
| Production deploy | **NOT DONE** |

Four tests were deleted, not weakened, because the requirements they encoded
were deliberately retired: two asserting `report_expense_detail` cleanup
(Step 3.5) and two asserting the Xero cascade deletes (Step 4a-2 / `r9a09`).

### Still to do

1. Re-run the preflight queries against **production** — P1 and the 4a-5
   currency check both over-report; filter to a non-zero column total.
2. Run `r7a07` then `r8a08` on production, **then** deploy the code. Schema
   first: both only widen what is accepted.
3. Browser-verify, since the suite covers none of this:
   * cash count save → reload
   * **ending page of a report created after 31 Jul** (blank denominations
     before defect 2's fix)
   * next-day opening balance where the previous report has no closing balance
   * export to PDF, including a report with an all-zero cash count
   * Xero publish with a system-account expense
