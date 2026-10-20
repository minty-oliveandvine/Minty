# The daily petty-cash report (the Daily Closing) - the rules

One report per company per day. **The screens are minty-petty-cash-web's** (the dashboard, the
five stages, Close, the outcome page and the Daily Report; its `docs/features/`), over
**minty-petty-cash-api** in production. Flask's Jinja pages, their session AJAX routes and its
Excel / docx / screenshot exports were deleted on 2026-10-20. What is left here is the
request-free services in `blueprints/report/services/` (models in `blueprints/report/models/`)
that Flask's own bearer copy of the API (`blueprints/petty_cash_api/`,
[petty-cash-api.md](petty-cash-api.md)) and the internal routes call. minty-petty-cash-api holds
the same rules in Django; a rule change goes in both.

## Five stages over six sections

Part 15.9 / 15.15 names five stages - **Addition to Drawer · Sales · Expenses · Cash Count ·
Close** - and folds Bank Deposit into Cash Count (D15-05). The report's
`report.current_section` / `completed_sections` keys did not change:
`blueprints/report/services/daily_closing.py` draws the five stages over the six keys (`deposit`
and `cash_count` are both Cash Count, which is done once `cash_count` is).

| Stage | Service | What is entered | Where it goes |
|---|---|---|---|
| Addition to Drawer | `services/opening.py` (`opening_state`, `save_opening`) | the cash added to the drawer and where it came from ("Company bank" / "Personal"); the starting balance is the server's (a company's first report: the onboarding opening balance from `entity_pettycash_settings`) | `report.opening_balance`, `cash_addition`, `cash_addition_type` |
| Sales | `services/sales.py` | one amount per sales method (electronic, delivery, cash) | `report_sale` rows (one per method; the class is still importable as `ReportSaleDetail`) |
| Expenses | `services/expenses.py`, a new supplier through `entity/services/suppliers.py` | entries: the receipt, amount, supplier, account, description | `report_expense` rows + attachment rows, saved as each entry is added |
| Cash Count | `services/cash.py` (`save_deposit`, `save_cash_count`, `save_deposit_and_count`) | the optional cash taken to the bank, the count by notes and coins, the safe box, and **a reason for any difference** | `report.bank_deposit`, `report_cash_count` rows, `safe_box_balance`, `discrepancy_*` - in one commit |
| Close | `services/submit.py` (`submit_problem`, `submit_report`) | nothing: a check, then submit | `status = submitted`, `submitted_at` |

A day starts as a **draft** (`report.status = draft`, `ReportStatus` in
`blueprints/shared/enums.py`). The draft is one row that fills in stage by stage; **there is no
separate draft table** (the expense line *is* the `report_expense` row from the moment it is
added). The next report's date is the day after the last submitted one (`next_transaction_date`,
`opening.new_report_date_problem`); a company cannot skip or duplicate a day, a first report
cannot be before `entity_pettycash_settings.start_date`, and no report can be in the future.

**Addition to Drawer's withdrawal source** (`company` / `personal`, stored as
`report.cash_addition_type`) is saved on every save. The bank account is the company's
petty-cash setting, never per report.

**Sales** writes a `report_sale` row for every method shown (an emptied field is zero) and
recomputes the closing balance after the rows. A Sales save makes the saver the report's creator
(`uploaded_by`, "track last editor"), on purpose.

**A difference needs a reason (the user, 2026-10-14; Part 15.15d).** The count and the deposit are
saved, but moving on with a difference and no reason is refused (`field: "discrepancy_reason"`).
Saving to exit keeps a count without one.

**The previous day's deposit** can be corrected before a day starts ("Before You Start"):
`report/routes/legacy.py::correct_previous_deposit`, reached through
`POST /api/internal/xero/deposit-correction` (minty-petty-cash-api forwards it; it may reverse or
update the deposit in Xero) and the bearer API's `POST /deposit-correction`.

## Expenses

- **Every expense must have a receipt** (one PDF / JPEG / PNG of at most 10 MB, judged by its
  bytes); a line of a report that is no longer a draft cannot be deleted; two lines alike (same
  day, account and rounded amount) never share one stored receipt.
- The supplier and account are the company's synced Xero contacts and active expense accounts
  (`xero_contact_sync`, `entity_account_xero` ⨝ `account_info`). A supplier added while entering a
  line is created in Xero and kept as a synced contact (`entity/services/suppliers.py`).
- The line links to the synced rows by their **row ids**; `contact_id`, `contact_name`,
  `account_id`, `account_code` on the model are properties that read through them (see
  [receipts-and-attachments.md](receipts-and-attachments.md) for the file side, and the
  note in `blueprints/report/models/shop_expense.py`).
- System accounts (bank, petty cash, the mapped control accounts) are refused as expense
  accounts at publish time (`xero/services/publish.py::validate_expenses_for_system_accounts`).
- With `EXPENSE_AI_ENABLED=1` the receipt is read by Gemini and the fields pre-filled as
  suggestions — [expense-ai.md](expense-ai.md).

## Money

Amounts are `Money()` columns (`blueprints/shared/column_types.py`, NUMERIC(14,2)) in the
company's currency (`entities.currency_id` → `currency_info`); the cash count's denominations
come from the currency's catalogue (`blueprints/report/services/cash_denominations.py`). The
closing balance is `opening + cash_addition + cash_sales − expenses − bank_deposit`; the cash
count compares the counted total (plus the safe box) against it and records the discrepancy
(`discrepancy_type` short/over, the amount, and the reason). Part 15's A15-01 subtracts only
*cash* expenses; the code subtracts all of them - which one is right is the owner's call.

The counted total is `Report.actual_cash_total` (`cash_summary(report_id)` adds the safe box):
None means never counted, and 0 means the cash-count step is done with every denomination zero
(zero quantities store no rows, so the model applies that rule; the `report_cash_summary` view
reads NULL for both).

**Cash in stock** (`entity_cash_detail`) follows the latest submitted report: submitting,
reverting to draft and deleting the latest report each rebuild it (`refresh_cash_stock`); a
draft never touches it, and the Cash Count step only ever saves a draft's count.

**Cash Count** (`services/cash.py`): cash on hand = opening + addition + cash sales - expenses;
expected cash = that less the deposit; difference = (counted - expected) + safebox, negative
being short; the deposit writes the closing balance without the difference and submit adds it.
The owner's rules of 2026-10-15: a deposit above the cash on hand is refused, and so is a drawer
already below zero; any difference counts, a single cent included; counts are whole numbers of 0
or more; a reason is at most 300 characters.

**Submitting** (`services/submit.py`): every step done, not a future day, the drawer not below
zero, an expense line with an item and an amount, and a difference that still matches the count
(Deposit, Sales or Expenses changed after it is refused back to Cash Count) with its reason. The
closing = opening + addition + cash sales - expenses - deposit + the difference; the submitter
becomes the creator; the stock follows the count. One commit under a row lock; a failure rolls
back and **never deletes the draft**.

## After a report is posted

- Edits that do not change balances stay allowed on a submitted report, through
  `services/report_edits.py`: the difference reason, the withdrawal source, and an expense
  line's non-balance fields. A draft or a report Xero is publishing is refused, a difference keeps
  its reason and a long one is refused rather than cut, a line's account and supplier must be the
  company's own, a new account renames the line, and a replaced receipt leaves the bucket. An edit
  after a Xero publish clears `xero_integrated` so a fresh publish is offered, but
  `publishing_status` keeps the record that it has been to Xero, so the app warns about
  duplicates.
- **Reopening and deleting** go through `services/report_actions.py`. Both act on the most recent
  report only and are refused while Xero is publishing it; reopening a draft is refused (409).
  Deleting removes the report and its lines, sales, cash counts, Xero sync rows and **the receipts
  in the bucket** (after the commit); `report_history` keeps an audit trail of the day's actions
  (`services/history.log_history`). **A report that has been to Xero may be deleted** (the owner,
  2026-10-15): the app warns that its entries stay in Xero, that publishing the day again adds a
  second copy, and to use Edit report instead.

## Report history

`services/history_query.py::get_entity_report_history` lists a company's reports, newest day
first, filtered, counted and paged **in SQL**: a status (`draft`, `submitted`, `published`,
`failed` - Publish failed and Publishing to Xero together), a date range (both dates), 10/25/50/100
a page. A failed row's publish reasons, which may ask Xero, are worked out only for the rows on
the page (`publish_reasons_for`, which `POST /api/internal/xero/publish-reasons` serves to
minty-petty-cash-api). The screens and the CSV export are [report-history-and-exports.md](report-history-and-exports.md).

## Statuses

`draft` → `submitted` → `published` (written only when the Xero publish completes) →
`void`. They are shown as Part 13/14 Status pills (`daily_closing.report_status`): Draft
(Neutral), Submitted (Info), Published to Xero (Success - `xero_integrated`, so an edit after a
publish reads Submitted again), Publishing to Xero (Info), Publish failed (Danger).
`publishing_status` is the publish job's own state (`unpublished` / `publishing` / `completed` /
`failed`, NOT NULL — `unpublished` is the never-published state, which is why "was it published
before" must not be `is not None`).

## Where it is tested

The service rules: `tests/test_report_opening_state.py`, `tests/test_report_sales_state.py`,
`tests/test_report_expenses_state.py`, `tests/test_report_deposit_cash_count_state.py`,
`tests/test_report_submit_state.py`, `tests/test_report_edits_state.py`,
`tests/test_report_actions_state.py`, `tests/test_report_history_state.py`,
`tests/test_delete_report_cleanup.py`; the bearer API over them, `tests/test_petty_cash_api_*.py`.
The screens are tested in minty-petty-cash-web.
