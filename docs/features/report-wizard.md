# The daily petty-cash report (the Daily Closing)

One report per company per day. Everything about it lives in `blueprints/report/` (routes per
page, services under `services/`, models under `models/`); the pages are Jinja templates under
`templates/report/`, drawn to the owner's design guidelines (Parts 13-15) since 2026-10-14 - see
[petty-cash-design.md](petty-cash-design.md) for the shell, the components and the scripts. The
browser suite (`e2e/02_report_wizard.spec.ts`) is the only thing that runs the pages'
JavaScript; the pytest suite renders the templates but executes none of it.

## The Daily Closing: five stages over six wizard sections

Part 15.9 / 15.15 names five stages - **Addition to Drawer · Sales · Expenses · Cash Count ·
Close** - and folds Bank Deposit into Cash Count (D15-05). The routes, their URLs, the
`action_type` POST contract and the wizard's `report.current_section` / `completed_sections`
keys did not change: `blueprints/report/services/daily_closing.py` draws the five stages over
the six keys (`deposit` and `cash_count` are both Cash Count, which is done once `cash_count` is).

| Stage | Route (template) | What is entered | Where it goes |
|---|---|---|---|
| Addition to Drawer | `GET/POST /entity/<co>/petty-cash/reports/new/opening` (`.../reports/<id>/opening` for an existing report) - `report/opening.html` | the cash added to the drawer and where it came from ("Company bank" / "Personal"); the starting balance is the server's (a company's first report: the onboarding opening balance from `entity_pettycash_settings`) | `report.opening_balance`, `cash_addition`, `cash_addition_type` |
| Sales | `.../reports/new/sale`, `.../reports/<id>/sale` - `report/sales.html` | one amount per sales method in three grouped sections (electronic, delivery, cash) with live sub-totals and the total (`sales[<bucket>][<method>]`) | `report_sale` rows (one per method; the class is still importable as `ReportSaleDetail`) |
| Expenses | `.../reports/new/expense`, `.../reports/<id>/expense` - `report/expense.html` | an entry list; each entry opens in a Drawer (480, full screen on a phone): the receipt (or a photo), amount, supplier, account, description | `report_expense` rows + attachment rows, saved as each entry is added |
| Cash Count | `.../reports/new/cash-count`, `.../reports/<id>/cash-count` - `report/cash_count.html` | the optional **cash taken for bank deposit** first, then the count by notes and coins, the safe box, the Check block (Expected in drawer, Counted, Difference "HKD 20.00 short"), and **a reason for any difference** | `report.bank_deposit`, `report_cash_count` rows, `safe_box_balance`, `discrepancy_*` - in one commit |
| Close | `.../reports/new/ending` - `report/close.html` | the work verification: every stage read-only with an Edit link, the totals and the difference; **Submit Daily Report** posts it | `status = submitted`, `submitted_at` |

Then the outcome page (`.../reports/<id>/submitted`, `report/submitted.html`, Part 15.12e):
the outcome, three facts from the server (cash counted, the difference, Xero), Publish to Xero
behind a confirmation ([xero-integration.md](xero-integration.md)), View report, Back to home
and Start the next day. A saved report reads as the **Daily Report** (`.../reports/<id>/summary`,
`report/ending.html`, Part 15.7): three KPIs (Total sales, Total expenses, Cash position), the
difference as a Warning alert, collapsible Sales by method / Expenses / Receipts / Cash, the
audit line, Share and More (Edit report / Delete report on the latest; Edit details on an older
one). The public share link draws the same page without actions or navigation.

The day starts from the **launch page** (`entity.report_dashboard`, `petty_cash/launch.html`,
Part 15.6a), which `blueprints/entity/services/launch.py` decides on the server: the open draft
(Continue Daily Closing, with its Step progress and "Saved 6:02 pm"), else the day after the last
submitted report (Start today's Daily Closing; a day before today is the gate, "Finish Sun 4 Oct
first"), else today's report is submitted (View report); a first use offers today. Starting a day
whose previous day banked a deposit asks **Before You Start** (was it deposited as stated? change
or remove it through `POST /api/check-dept-bank-yest/<co>`); the latest report's row in Recent
reports carries **Correct deposit** for the same correction outside the start. The calendar,
Quick Actions and the KPIs are gone (15.6a).

**Bank Deposit folded into Cash Count (2026-10-14).** The old deposit step's GET goes on to the
Cash Count page (302, the day and the edit flags carried) - the expenses step, the resume and old
links still name it. The Cash Count POST applies the deposit and the count in one commit through
`services/cash.py` (merged 2026-10-15 with the Petty Cash API's service, which replaced
`services/bank_deposit.py`: a drawer below zero before the deposit is refused, and so is a deposit
above the cash on hand), and on Save & Next marks both `deposit` and `cash_count` done. The deposit
POST still works on its own for an older client.

**A difference needs a reason (the user, 2026-10-14; Part 15.15d).** Save & Next stays off with
"Add a reason for the difference to continue." beside it while the count is out and the reason
empty, and the server refuses it too: the count and the deposit are still saved (nothing typed
is lost) but the day stays on Cash Count - a page post comes back with `?reason=needed` and the
message on the field, an XHR gets 422 `{field: "discrepancy_reason"}`. Save & Exit is never
refused for it. The expected-cash formula itself did not change (see Money).

A day starts as a **draft** (`report.status = draft`, `ReportStatus` in
`blueprints/shared/enums.py`): `GET /create` and `/entity/<co>/petty-cash/reports/resume` open or resume the
current draft, `GET /report/<id>/<page>` re-opens a page of a specific report, and
`/api/get_draft_totals?entity_id&transaction_date` is what the pages poll for the running
figures (the old Expenses page did; the redesigned stages draw everything from the server and
reload instead). The draft is one row that fills in page by page; **there is no separate draft
table** any more (the redesign folded `shop_expense_draft` etc. into the live tables — the
expense line *is* the `report_expense` row from the moment it is added).

**Addition to Drawer's withdrawal source** (`withdrawal` = `company` / `personal`, stored as
`report.cash_addition_type`) is saved on every save of the page. The bank account is the
company's petty-cash setting, never per report. Until 2026-10-05 a hidden `bank_account` field
had to be non-empty for a re-save to store the choice, so a company without that setting kept
its first choice. e2e `02` fails on any page error on that stage.

**Opening and Sales save through services** (`services/opening.py`, `services/sales.py`) that the
Petty Cash API shares ([petty-cash-api.md](petty-cash-api.md)). Sales writes a `report_sale` row
for every method the page shows (an emptied field is zero) and recomputes the closing balance
after the rows. Two bugs went with the extraction (2026-10-14): a re-save closed on the cash
typed the time before, and a method the page has no field for (an `other` one that is not Cash)
was zeroed by every save. A Sales save still makes the saver the report's creator
(`uploaded_by`, "track last editor"), on purpose.

**Expenses saves through `services/expenses.py`** (adding and deleting a line, the totals, the
step's save) and a new supplier through `entity/services/suppliers.py`, both shared with the Petty
Cash API. Fixed with the extraction (2026-10-14):
- a line of a report that is no longer a draft can no longer be deleted;
- the step's Save & Next commits its own progress (it relied on a later request hook's commit);
- two lines alike (same day, account and ROUNDED amount) no longer share one stored receipt - the
  second upload used to overwrite the first;
- a supplier added from the page is kept as a synced contact, so the line it was added for keeps it
  (it was stored with no supplier), and the page sends its own company with it (on the company
  address it sent none, and the add was refused);
- the add route no longer asks Xero for the account list on every line (the answer was ignored).
The Jinja routes still leave the line's own checks to the browser; the API makes them.

The next report's date is the day after the last submitted one (`next_transaction_date`);
a company cannot skip or duplicate a day. `POST /report/<id>/convert-to-draft` reopens a
submitted report as the draft again (only the most recent one) - see *After a report is posted*.

## Expenses in detail

- **Names never become markup.** The page's script (`static/js/pc_expenses.js`) builds the
  Suppliers / Account Code dropdowns, "+ Add '<q>' as a new contact" and the expense cards with
  `createElement` + `textContent`. Names reach it as JSON (`|tojson`), never as an HTML string.
  Before the old page escaped them (2026-10-15) they went in raw, so a Xero contact named
  `<img onerror=...>` ran script for every cashier who opened the page (stored XSS).
  `tests/test_expense_page_escaping.py` fails on any HTML sink in that script, or any
  interpolation in a markup literal.
- `POST /report/expense/add` persists **one line immediately** (multipart, files under
  `files[0][n]`) — that is why the page can keep adding without one huge upload at the end;
  the redesigned page (`static/js/pc_expenses.js`) reloads the list from the server after every
  add, edit and delete and keeps no copy in the browser. `submit_all` is the legacy all-at-once
  path. `update/<id>`, `delete/<id>`,
  `draft/<id>` (GET/PATCH) edit a line; `validate_drafts` checks every line of the day has an
  amount, a supplier and an account (not its receipt: `/add` is what insists on one -
  **every expense must have one**).
- The supplier and account pickers are searchable inputs over the company's synced
  contacts and active expense accounts (`xero_contact_sync`, `entity_account_xero` ⨝
  `account_info`), drawn as text (a Xero name is never markup); a new supplier can be created in
  Xero from the form (`POST /entity/contact/create`, which needs the company's `entity_id` - the
  old page sent it from the query string, empty on a company address, so creating a supplier
  there always failed with "Missing 'entity_id'"). The new supplier is kept as a synced contact
  (`entity/services/suppliers.py`), so the line it was added for keeps it.
- The line links to the synced rows by their **row ids**; `contact_id`, `contact_name`,
  `account_id`, `account_code` on the model are properties that read through them (see
  [receipts-and-attachments.md](receipts-and-attachments.md) for the file side, and the
  note in `blueprints/report/models/shop_expense.py`).
- System accounts (bank, petty cash, the mapped control accounts) are refused as expense
  accounts at publish time (`validate_expenses_for_system_accounts`).
- With `EXPENSE_AI_ENABLED=1` the receipt is read by Gemini and the fields pre-filled as
  suggestions — [expense-ai.md](expense-ai.md).

## Money

Amounts are `Money()` columns (`blueprints/shared/column_types.py`, NUMERIC(14,2)) and the
pages format in the company's currency (`entities.currency_id` → `currency_info`); the
cash count's denominations come from the currency's catalogue
(`blueprints/report/services/cash_denominations.py`, the currency row's denomination list). The closing balance is
`opening + cash_addition + cash_sales − expenses − bank_deposit`; the cash count compares
the counted total (plus the safe box) against it and records the discrepancy
(`discrepancy_type` short/over, the amount, and the reason). Part 15's A15-01 subtracts only
*cash* expenses; the code subtracts all of them. The redesign kept the code's formula - which one
is right is the owner's call.

The counted total is `Report.actual_cash_total` (`cash_summary(report_id)` adds the safe
box): None means never counted - the Ending page then shows the closing balance - and 0
means the cash-count step is done with every denomination zero (zero quantities store no
rows, so the model applies that rule; the `report_cash_summary` view reads NULL for both). The `.docx` export's
drawer total is the same figure, so a denomination outside the template's nine legacy HKD
slots still counts.

**Cash in stock** (`entity_cash_detail`) follows the latest submitted report: submitting,
reverting to draft and deleting the latest report each rebuild it (`refresh_cash_stock`); a
draft never touches it, and the Cash Count step only ever saves a draft's count.

**Submitting saves through `services/submit.py`** (2026-10-15), shared with the Petty Cash API's
`POST /reports/submit`; the Close page's POST calls it. Flask's rules are kept (every step done,
not a future day, the drawer not below zero, the closing = opening + addition + cash sales -
expenses - deposit + the difference, the submitter becomes the creator, the stock follows the
count). Changed: a failure rolls back and **never deletes the draft** - Flask's "clean-up" deleted
a day with no expense lines, and with lines only failed silently; a difference that no longer
matches the count (Deposit, Sales or Expenses changed after it) or has no reason is refused back to
Cash Count (the owner, 2026-10-15); an expense line with no item or amount is refused back to
Expenses; a refusal keeps the day in the address (it used to drop it); one commit under a row lock;
"submitted" is stored in `completed_sections` (it was appended in place and lost).

**Deposit and Cash Count save through `services/cash.py`**, shared with the Petty Cash API
(which can also save the two together, in one transaction, for Part 15's Cash Count stage). The
formulas are Flask's: cash on hand = opening + addition + cash sales - expenses; expected cash =
that less the deposit; difference = (counted - expected) + safebox, negative being short; the
deposit writes the closing balance without the difference and submit adds it. The owner's rules
of 2026-10-15, each a change from Flask:
- a deposit above the cash on hand is refused at Deposit (it used to be taken and only blocked
  at Cash Count);
- any difference counts, a single cent included (Flask's check was "more than 0.01", in the
  server and in the page's script alike);
- Save & Next needs a reason when there is a difference, checked on the server (the page only
  asked in the browser). Save & Exit still keeps a count without one.
Also with the extraction: counts are whole numbers of 0 or more (2.5 was stored as 2), a reason
is at most 300 characters (a database error before), each save commits once (the count committed
three times), a refused save sends the person back to the step with their company and day (two
error paths lost both), and the Deposit page no longer asks Xero for the account list on every
load (the answer was never used).

## After a report is posted

- Edits that do not change balances stay allowed on a submitted report: the discrepancy
  reason (`POST /report/<id>/edit/discrepancy-reason`), the withdrawal source
  (`…/edit/withdrawal`), an expense line's non-balance fields
  (`POST /report/expense/edit/<id>`). An edit after a Xero publish clears
  `xero_integrated` so the page offers a fresh publish, but `publishing_status` keeps the
  record that it has been to Xero, so the page warns about duplicates
  (`tests/test_char_report_lifecycle.py::test_an_edit_after_a_xero_publish_…`).
- **Reopening and deleting go through `services/report_actions.py`** (2026-10-15), shared with
  the Petty Cash API (`POST /reports/<id>/reopen`, `DELETE /reports/<id>`). Both act on the most
  recent report only and are refused while Xero is publishing it (the worker would mark a draft
  published, or find no report). Fixed with the extraction: reopening a draft wiped its progress
  (now 409); resubmitting a report reopened from Xero kept `xero_integrated`, so the changed day
  still read "Published to Xero" (submit now clears it; `publishing_status` keeps the record);
  the receipts were deleted from the bucket before the commit, so a failed delete lost them;
  an unknown id flashed against the wrong company; and the Daily Report and history pages delete
  with `fetch`, which followed every refusal's redirect to a 200 and said "deleted" - they now
  ask for JSON and show the refusal.
- `POST /report/delete/<id>` deletes the report and its lines, sales, cash counts, Xero sync
  rows and **the receipts in the bucket**; `report_history` keeps an audit trail of the day's
  actions (`services/history.log_history`). **A report that has been to Xero may be deleted**
  (the owner, 2026-10-15): the delete dialog warns that its entries stay in Xero, that
  publishing the day again adds a second copy, and to use Edit report to change it instead.
- `GET /report/edit/<id>` is the older whole-report edit form (only the most recent report).

## Statuses

`draft` → `submitted` → `published` (written only when the Xero publish completes) →
`void`. The pages show them as Part 13/14 Status pills (`daily_closing.report_status`): Draft
(Neutral), Submitted (Info), Published to Xero (Success - `xero_integrated`, so an edit after a
publish reads Submitted again), Publishing to Xero (Info), Publish failed (Danger). `publishing_status` is the publish job's own state (`unpublished` / `publishing`
/ `completed` / `failed`, NOT NULL — `unpublished` is the never-published state, which is
why "was it published before" must not be `is not None`).

## Where it is tested

`tests/test_char_report_lifecycle.py` walks the whole wizard through the real routes on
Postgres (opening → sales → expenses with a receipt → deposit → cash count → ending →
submitted; history, CSV, detail, delete, the publish hand-off, the receipt links);
`tests/test_petty_cash_cash_count_stage.py` the folded deposit and the reason rule;
`tests/test_petty_cash_launch.py` the launch page's states; `tests/test_petty_cash_report_pages.py`
Close, the outcome page, the Daily Report (and its share link) and history;
`tests/test_petty_cash_ui_foundation.py` the five stages and the status tones;
`tests/test_char_expense_attachments.py` covers the expense lines and their files;
`tests/test_delete_report_cleanup.py` the delete cascade; `tests/test_report_actions_state.py`
reopen and delete, `tests/test_petty_cash_api_report.py` their API routes. In the browser,
`e2e/02_report_wizard.spec.ts` (every stage, the expense Drawer and its refused submit, the
receipt viewer, the count and the reason gate, Close, history and the Daily Report) and
`e2e/04_xero_publish.spec.ts` when `E2E_XERO=1`.
