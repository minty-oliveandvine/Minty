# Report history, the movements CSV and share links

The history list, the Daily Report and the share page are **minty-petty-cash-web's** (`/reports`,
the report page, `/share/<path>`), over minty-petty-cash-api. Flask's history page, its Korean
`/report/<id>` detail, `/report/edit`, and the Excel (`/report/download`), docx-to-PDF
(`/report/<id>/export`, spire-doc) and screenshot (`/report/<id>/screenshot`, Selenium) exports,
`/download/<path>`, `/preview/<path>`, the superuser's `/download_attachments` and
`/admin/download_statements` were all deleted on 2026-10-20 (owner's decision, no replacement).
Code left here: `blueprints/report/routes/history.py` and `legacy.py` (redirects), services
`history_query.py`, `report_csv.py`, `share.py`.

## History

`services/history_query.py::get_entity_report_history` is the list
([report-wizard.md](report-wizard.md), "Report history"); the bearer API's `GET /reports` serves
it ([petty-cash-api.md](petty-cash-api.md)). `REPORT_VIEW_ENTITY` sees everything; a cashier sees
only the reports they created (`REPORT_VIEW_OWN`, `can_view_report`).

`GET /entity/<co>/petty-cash/reports` stays as an address (old links, the older front ends): it
hands over to minty-petty-cash-web's `/reports` through `/handoff/petty-cash-web`, its query
carried on (`report.entity_report_history`).

## The movements CSV

The one export left: the bearer API's `GET /reports/export.csv?start_date&end_date`
(`report/services/report_csv.py`; minty-petty-cash-api has its own). One line per movement of
every **submitted or published** report in the range (drafts are left out since 2026-10-16), by
day: the float (director account when it came from the owner), each expense as entered (its
remark and account code), the cash sale, the deposit (booked against the petty-cash account's
code), the cash difference; `Date,Account Code,Amount,Description,Reference,Check Number`, LF
line ends on every platform. Both dates `YYYY-MM-DD`, at most a year (366 days);
`REPORT_VIEW_ENTITY`.

## Share links

`services/share.py::create_share_link_for_report` (the bearer API's
`POST /reports/<id>/share-link`) creates or renews **one `share_link` row per company-day**, looked
up by `(entity_id, transaction_date)`. The link is valid for **30 days** (`SHARE_LINK_HOURS`, 720);
sharing the same day again renews it and keeps the same path:

    {initials}/{dd_Mon_yyyy}/{secret}

`{secret}` is 32 random url-safe characters (`secrets.token_urlsafe(24)`), and it is what
grants access. The initials and date are cosmetic: a name with no Latin letters gets
`Report`. minty-petty-cash-web shows the day at `/share/<path>`, reading it through the public
`GET /api/petty-cash/v1/public/share/<path>` ([petty-cash-api.md](petty-cash-api.md)).

**Old links** (`/Minty_Report/<path>/`, the address every share link sent before 2026-10-20 still
carries) 308 to `PETTY_CASH_WEB_URL/share/<path>` (`report/routes/legacy.py::minty_report_share`),
which refuses an unknown or expired one itself.

`share.resolve_share(path)` holds every check: the full path only (`is_share_path` refuses the
old two-part URLs that had no secret), an unexpired row, the stored signed token naming the row's
company **and** day, the company, a submitted report. It returns `(link, entity, report)` or raises
`ShareRefused(reason, message, category)`; the public read answers 404 for every reason but
`expired` (410). An expired row and one whose token fails its signature are deleted; a token
naming another company or day is refused and kept. A refused or unknown path is logged as
`share link refused` with the caller's IP, a successful open as `share link opened` with the link
id. The secret is never logged, and the access log blanks it (`http_hardening.SECRET_PATH_ARGS`:
`entity_and_date`, `share_path`).

## Tests

`tests/test_report_history_state.py`, `tests/test_petty_cash_api_history.py` (the list),
`tests/test_report_csv_export.py` (the CSV), `tests/test_petty_cash_api_public_share.py` (the
public read), `tests/test_petty_cash_web_handoff.py` (the history hand-off),
`tests/test_flask_backend_only.py` (the deleted pages and exports answering 404).
