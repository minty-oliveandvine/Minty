# The daily petty-cash report (the wizard)

One report per company per day, walked in seven pages. Everything about it lives in
`blueprints/report/` (routes per page, services under `services/`, models under `models/`)
and the pages are Jinja templates under `templates/report/` with a lot of inline
JavaScript — the browser suite (`e2e/02_report_wizard.spec.ts`) is the only thing that runs
that JavaScript; the pytest suite renders the templates but executes none of it.

## The pages, in order

| Step | Route | What is entered | Where it goes |
|---|---|---|---|
| Opening | `GET/POST /entity/<co>/reports/new/opening` (a new day; `.../reports/<id>/opening` for an existing report) | the float carried forward, a cash addition/withdrawal and its source ("withdrawal from": bank or director) | `report.opening_balance`, `cash_addition`, `withdrawal_from` |
| Sales | `.../reports/new/sale`, `.../reports/<id>/sale` | one amount per sales method — cash, the electronic methods and the delivery platforms the company set up (`sales[<bucket>][<method>]`) | `report_sale` rows (one per method; the class is still importable as `ReportSaleDetail`) |
| Expenses | `.../reports/new/expense`, `.../reports/<id>/expense` | one line per receipt: supplier (a synced Xero contact), account (a synced expense account), amount, remarks, the receipt file(s) | `report_expense` rows + attachment rows |
| Deposit | `.../reports/new/deposit`, `.../reports/<id>/deposit` | the cash banked today (the page shows the cash on hand before it) | `report.bank_deposit` |
| Cash count | `.../reports/new/cash-count`, `.../reports/<id>/cash-count` | denominations counted (the calculator modal), the actual cash balance, a discrepancy reason when the count and the book disagree | `report_cash_count` rows, `discrepancy_*` |
| Ending | `.../reports/new/ending`, `.../reports/<id>/ending` | the summary; **Finish** posts the report | `status = submitted`, `submitted_at` |
| Submitted | `/report/<id>/submitted?entity_id=…` | export, share, **Publish to Xero** | see [xero-integration.md](xero-integration.md) |

A day starts as a **draft** (`report.status = draft`, `ReportStatus` in
`blueprints/shared/enums.py`): `GET /create` and `/entity/<co>/reports/resume` open or resume the
current draft, `GET /report/<id>/<page>` re-opens a page of a specific report, and
`/api/get_draft_totals?entity_id&transaction_date` is what the pages poll for the running
figures. The draft is one row that fills in page by page; **there is no separate draft
table** any more (the redesign folded `shop_expense_draft` etc. into the live tables — the
expense line *is* the `report_expense` row from the moment it is added).

The next report's date is the day after the last submitted one (`next_transaction_date`);
a company cannot skip or duplicate a day. `POST /report/<id>/convert-to-draft` reopens a
submitted report as the draft again (only the most recent one).

## Expenses in detail

- `POST /report/expense/add` persists **one line immediately** (multipart, files under
  `files[0][n]`) — that is why the page can keep adding without one huge upload at the end;
  `submit_all` is the legacy all-at-once path. `update/<id>`, `delete/<id>`,
  `draft/<id>` (GET/PATCH) edit a line; `validate_drafts` checks every line of the day
  carries a receipt (**every expense must have one**).
- The supplier and account pickers are searchable inputs over the company's synced
  contacts and active expense accounts (`xero_contact_sync`, `entity_account_xero` ⨝
  `account_info`); a new supplier can be created in Xero from the form
  (`/report/expense/create_contact`).
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
the counted total against it and records the discrepancy (`discrepancy_type` short/over,
the amount, and the reason).

## After a report is posted

- Edits that do not change balances stay allowed on a submitted report: the discrepancy
  reason (`POST /report/<id>/edit/discrepancy-reason`), the withdrawal source
  (`…/edit/withdrawal`), an expense line's non-balance fields
  (`POST /report/expense/edit/<id>`). An edit after a Xero publish clears
  `xero_integrated` so the page offers a fresh publish, but `publishing_status` keeps the
  record that it has been to Xero, so the page warns about duplicates
  (`tests/test_char_report_lifecycle.py::test_an_edit_after_a_xero_publish_…`).
- `POST /report/delete/<id>` deletes the report and its lines, cash counts, history and
  **the receipts in the bucket** (`delete_expense_with_receipts`); `report_history` keeps
  an audit trail of the day's actions (`services/history.log_history`).
- `GET /report/edit/<id>` is the older whole-report edit form (only the most recent report).

## Statuses

`draft` → `submitted` → `published` (written only when the Xero publish completes) →
`void`. `publishing_status` is the publish job's own state (`unpublished` / `publishing`
/ `completed` / `failed`, NOT NULL — `unpublished` is the never-published state, which is
why "was it published before" must not be `is not None`).

## Where it is tested

`tests/test_char_report_lifecycle.py` walks the whole wizard through the real routes on
Postgres (opening → sales → expenses with a receipt → deposit → cash count → ending →
submitted; history, CSV, detail, delete, the publish hand-off, the receipt links);
`tests/test_char_expense_attachments.py` covers the expense lines and their files;
`tests/test_delete_report_cleanup.py` the delete cascade. In the browser,
`e2e/02_report_wizard.spec.ts` (every page, the receipt preview, the calculator modal)
and `e2e/04_xero_publish.spec.ts` when `E2E_XERO=1`.
