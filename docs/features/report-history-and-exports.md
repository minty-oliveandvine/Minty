# Report history, detail pages and exports

Code: `blueprints/report/routes/history.py`, `report_detail.py`, `download.py`,
`export_screenshot.py`, `legacy.py`; services `history_query.py`, `report_download.py`,
`share.py`.

## History

`GET /entity/<id>/reports` lists the company's reports newest first, ten a page
(`start_date` / `end_date` filters), each with its status badge (Draft / Submitted /
Published) and a **View Report** link to the ending summary
(`/entity/<id>/ending/<report_id>`). `REPORT_VIEW_ENTITY` sees everything; a cashier sees
only the reports they created (`REPORT_VIEW_OWN`, `can_view_report`).

## Detail

- `GET /report/<id>` — the read-only detail: sales breakdown, expense lines with one
  download link per receipt (`/download/<key>`), the cash count, the history log.
- `GET /report/<id>/ending` / `/entity/<id>/ending/<report_id>` — the same summary the
  wizard shows at the end, usable after posting.
- `GET /report/<id>/submitted?entity_id=` — export options and the Xero publish.

## Exports

| Export | Route | How it is made |
|---|---|---|
| Movements CSV | `GET /entity/<id>/reports/download-csv?start_date&end_date` | one line per movement of every report in the range: the float (director account), each expense (its remark and account code), the cash sale, the deposit (booked against the petty-cash account's code); `Date,Account Code,Amount,Description,Reference,Check Number` |
| Daily report `.docx` / PDF | `GET /report/<id>/export` | fills `static/doc/Daily_Report_Template.docx` with `docxtpl` (the nine legacy column names and the `qty*` denomination placeholders are what the template addresses) and converts it (`services/helpers/docx.py`) |
| Ending screenshot | `GET /report/<id>/screenshot` | Selenium + headless Chrome renders the ending page and captures `#ending-content` as PNG |
| Receipts zip | `POST /download_attachments` | every receipt of the period from the bucket, `<date>/<filename>` |
| Statements | `GET/POST /admin/download_statements` | the superuser's cross-company statement download |
| Spreadsheet | `GET /report/download/<id>` | the report as a pandas-built Excel file (`services/report_download.py`) |

## Share links

`POST /api/generate_share_link` creates (or renews) a `share_link` row for one company-day:
a readable path segment plus a signed token, valid **30 days** (720 h). The public URLs
`GET /Minty_Report/<entity_and_date>/` and `/Minty_Report_<entity_and_date>/ending`
(`legacy.py`) look the segment up, verify the token and render the ending summary without
a login. `legacy.py` also keeps `/insert_xero_transaction` and
`/api/check-dept-bank-yest/<entity_id>` for old integrations.

## Tests

`tests/test_char_report_lifecycle.py` (history rows and badges, the detail's figures, the
CSV's movement lines, the receipt links, delete), `tests/test_cashier_report_history.py`
(what a cashier may see), `tests/test_report_export_permissions.py`,
`tests/test_share_link_access.py`;
`e2e/02_report_wizard.spec.ts` (history and detail after posting) and
`e2e/03_settings.spec.ts` (the CSV).
