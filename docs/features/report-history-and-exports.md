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
  `/download/<key>` signs a link only for a receipt of a report the person may see
  (`can_view_report`): the key's attachment row names its report, and a key not yet on a
  line is `expenses/<report_id>/...`. Unknown key 404, someone else's 403, both logged.
  Before 2026-10-05 it signed ANY key for any signed-in user.
- `GET /report/<id>/ending` / `/entity/<id>/ending/<report_id>` — the same summary the
  wizard shows at the end, usable after posting.
- `GET /report/<id>/submitted?entity_id=` — export options and the Xero publish.

## Exports

| Export | Route | How it is made |
|---|---|---|
| Movements CSV | `GET /entity/<id>/reports/download-csv?start_date&end_date` | one line per movement of every report in the range: the float (director account), each expense (its remark and account code), the cash sale, the deposit (booked against the petty-cash account's code); `Date,Account Code,Amount,Description,Reference,Check Number` |
| Daily report `.docx` / PDF | `GET /report/<id>/export` | fills `static/doc/Daily_Report_Template.docx` with `docxtpl` (the nine legacy column names and the `qty*` denomination placeholders are what the template addresses) and converts it (`services/helpers/docx.py`) |
| Ending screenshot | `GET /report/<id>/screenshot` | Selenium + headless Chrome renders the ending page and captures `#ending-content` as PNG |
| Receipts zip | `POST /download_attachments` | every receipt of the period from the bucket, `<date>/<filename>`; **superuser only** (it spans every company) |
| Statements | `GET/POST /admin/download_statements` | the cross-company statement download; **superuser only** (both were open to any signed-in user before 2026-10-05) |
| Spreadsheet | `GET /report/download/<id>` | the report as a pandas-built Excel file (`services/report_download.py`); `can_view_report`, as is the CSV's `?report_id=` |

## Share links

`POST /api/generate_share_link` (`services/share.py`) creates or renews **one `share_link`
row per company-day**, looked up by `(entity_id, transaction_date)`. The link is valid for
**30 days** (720 h); sharing the same day again renews it and keeps the same URL. The public
URL is

    /Minty_Report/{initials}/{dd_Mon_yyyy}/{secret}/

`{secret}` is 32 random url-safe characters (`secrets.token_urlsafe(24)`), and it is what
grants access. The initials and date are cosmetic: a name with no Latin letters gets
`Report`. `GET /Minty_Report/<path>/` (`legacy.py`) finds a row only by the full path. It
then checks the stored signed token against the row's company **and** day, and renders the
ending summary of a submitted report without a login.

Until 2026-10-01 the URL had no secret. Anyone could edit the date and open other days, and
two companies with the same initials (e.g. "Dine at Venus" / "Dine at Venus 2") shared one
row, so the second company to share took over the first one's link. Those two-part URLs are
now refused outright (`is_share_path`), even while their row still exists. On the
`pettycashv3` schema, no link opened at all before that date either: a naive-vs-aware
`expires_at` comparison crashed and was shown as "This link doesn't look right" (see
CODE_CLEANSE_NOTES). A refused or
unknown path is logged as `share link refused` with the caller's IP, and a successful open
as `share link opened` with the link id, so access is traceable from then on.

The old `?token=` entries - `/Minty_Report_<entity_and_date>/ending?token=` and
`entity_ending`'s `?token=` branch - were **deleted on 2026-10-05**: their 30-day HMAC token
ignored the ShareLink row, so revoking a link did nothing. `/entity/<id>/ending` is
signed-in only now. `/insert_xero_transaction` (a no-login GET that wrote a fixture row) went
the same day. `POST /api/check-dept-bank-yest/<entity_id>` (the dashboard's correction of the
previous day's bank deposit, pushed to Xero when published) took GET and NO login until
2026-10-05; it now needs a signed-in member with `REPORT_EDIT_ENTITY`.

## Tests

`tests/test_char_report_lifecycle.py` (history rows and badges, the detail's figures, the
CSV's movement lines, the receipt links, delete), `tests/test_cashier_report_history.py`
(what a cashier may see), `tests/test_report_export_permissions.py`,
`tests/test_share_link_access.py`;
`e2e/02_report_wizard.spec.ts` (history and detail after posting) and
`e2e/03_settings.spec.ts` (the CSV).
