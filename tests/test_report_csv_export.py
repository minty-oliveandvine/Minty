"""Report history's movements CSV: the Jinja export (``report.download_reports_csv``) and the
Petty Cash API's ``GET /reports/export.csv``, both through ``report/services/report_csv.py``.

The first block pins what the Jinja route answered before the service existed (characterisation);
the FIXED tests name what changed on purpose. The API's door is tests/test_petty_cash_api_door.py's.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import char_factories as F
import pytest
from test_report_submit_state import D3, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

HEADER = ["Date", "Account Code", "Amount", "Description", "Reference", "Check Number"]


def _account(db, entity, code, name):  # noqa: F811
    from models.db import AccountInfo

    row = AccountInfo(entity_id=entity.id, type="EXPENSE", name=name, xero_account_id=str(uuid.uuid4()),
                      xero_code=code, status="ACTIVE")
    db.session.add(row)
    db.session.flush()
    return row


@pytest.fixture
def books(app, db, shop):  # noqa: F811
    """Two submitted days and a draft before them, with every account role configured:
    petty cash 090, owner's account 880, cash sales 200, cash difference 870."""
    from models.db import EntityPettycashSettings, Report, ShopExpense

    owner, entity = shop
    with app.app_context():
        petty, director = _account(db, entity, "090", "Petty Cash"), _account(db, entity, "880", "Owner")
        sale, difference = _account(db, entity, "200", "Sales"), _account(db, entity, "870", "Difference")
        tape = _account(db, entity, "445", "Tape")
        db.session.add(EntityPettycashSettings(
            entity_id=entity.id, pettycash_account_id=petty.id, director_account_id=director.id,
            cash_sale_account_id=sale.id, discrepancy_account_id=difference.id))

        def report(days_back, status="submitted", **fields):
            row = Report(entity_id=entity.id, transaction_date=D3 - timedelta(days=days_back), status=status,
                         created_by=owner.id, opening_balance=0, closing_balance=0, **fields)
            db.session.add(row)
            db.session.flush()
            return row

        base = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)

        def line(row, minutes, item, amount, remarks, account=None):
            db.session.add(ShopExpense(report_id=row.id, item=item, amount=amount, remarks=remarks, account=account,
                                       created_at=base + timedelta(minutes=minutes)))

        draft = report(2, status="draft", cash_sales=99)
        line(draft, 0, "Draft line", 7, "Draft")
        first = report(1, cash_addition=20, cash_addition_type="personal", cash_sales=300, bank_deposit=500,
                       discrepancy_amount=2.5, discrepancy_type="short")
        # added out of order: the export lists them as they were entered
        line(first, 2, "Blank", 10, "No description")
        line(first, 1, "Tape", 25.10, "Tape, the wide roll", tape)
        line(first, 3, "Dash", 0, "-")
        second = report(0, cash_addition=50, cash_addition_type="company", discrepancy_amount=1,
                        discrepancy_type="over")
        line(second, 0, "Tea", 12.5, "Café 茶")
        db.session.commit()
        ids = {"draft": str(draft.id), "first": str(first.id), "second": str(second.id)}
    return owner, entity, ids


def _jinja(client, entity, **query):
    return client.get(f"{F.co(client, entity.id)}/petty-cash/reports/download-csv", query_string=query)


def _rows(resp):
    return list(csv.reader(io.StringIO(resp.get_data().decode("utf-8"))))


def _range(days_back_start=2, days_back_end=0):
    return {"start_date": F.iso(D3 - timedelta(days=days_back_start)),
            "end_date": F.iso(D3 - timedelta(days=days_back_end))}


def _day(days_back):
    return F.iso(D3 - timedelta(days=days_back))


SUBMITTED_ROWS = [
    [_day(1), "880", "20.0", "Cash Addition/Withdrawal From (Start)", " ", " "],
    [_day(1), "445", "-25.1", "Tape, the wide roll", " ", " "],
    [_day(1), "N/A", "-10.0", "Expense", " ", " "],
    [_day(1), "N/A", "0.0", "Expense", " ", " "],  # a zero line is 0.0, never -0.0
    [_day(1), "200", "300.0", "Cash Sale (Pettycash)", " ", " "],
    [_day(1), "090", "-500.0", "Bank Deposit", " ", " "],
    [_day(1), "870", "-2.5", "Discrepancy (short)", " ", " "],
    [_day(0), "090", "50.0", "Cash Addition/Withdrawal From (Start)", " ", " "],
    [_day(0), "N/A", "-12.5", "Café 茶", " ", " "],
    [_day(0), "870", "1.0", "Discrepancy (over)", " ", " "],
]


# --- what the Jinja export answered before the service (characterisation) ----------------------------


def test_the_range_export_lists_each_movement_in_day_order(app, client, books):
    owner, entity, ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, **_range(1, 0))

    assert resp.status_code == 200, resp.data[:300]
    assert resp.headers["Content-Type"] == "text/csv"
    assert resp.headers["Content-Disposition"] == f"attachment; filename=reports_{_day(1)}_to_{_day(0)}.csv"
    rows = _rows(resp)
    assert rows[0] == HEADER
    # the lines of a day came in no particular order (FIXED below: as entered)
    assert sorted(rows[1:]) == sorted(SUBMITTED_ROWS)


def test_the_export_is_utf8_without_a_byte_order_mark(app, client, books):
    owner, entity, _ids = books
    F.login(client, owner)

    body = _jinja(client, entity, **_range(1, 0)).get_data()

    assert body.startswith(b"Date,") and "Café 茶".encode("utf-8") in body
    assert b'"Tape, the wide roll"' in body  # a comma in a remark is quoted


def test_one_report_exports_by_id(app, client, books):
    owner, entity, ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, report_id=ids["second"])

    assert resp.status_code == 200, resp.data[:300]
    assert resp.headers["Content-Disposition"] == f"attachment; filename=report_{ids['second']}.csv"
    assert _rows(resp) == [HEADER] + SUBMITTED_ROWS[7:]


@pytest.mark.parametrize("query, message", [
    ({}, "I need both a start and an end date to do that."),
    ({"start_date": "2026-10-01"}, "I need both a start and an end date to do that."),
    ({"start_date": "2026-10-05", "end_date": "2026-10-02"},
     "Your start date lands after your end date — could you flip them around?"),
])
def test_the_range_export_refuses_a_missing_or_backwards_range(app, client, books, query, message):
    owner, entity, _ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, **query)

    assert resp.status_code == 400 and resp.get_json() == {"status": "error", "message": message}


def test_an_empty_range_is_404(app, client, books):
    owner, entity, _ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, start_date="2020-01-01", end_date="2020-01-31")

    assert resp.status_code == 404
    assert resp.get_json() == {"status": "error", "message": "No reports found in the specified date range."}


def test_someone_who_may_not_see_reports_is_refused(app, client, db, books):  # noqa: F811
    from models.db import UserEntity

    _owner, entity, _ids = books
    with app.app_context():
        base = F.make_user(db, "base@test.com", first_name="Bea")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    F.login(client, base)

    resp = _jinja(client, entity, **_range())

    assert resp.status_code == 403 and resp.get_json()["message"] == "You do not have access to this entity."


def test_no_settings_leave_the_codes_blank(app, client, db, books):  # noqa: F811
    from models.db import EntityPettycashSettings

    owner, entity, _ids = books
    with app.app_context():
        EntityPettycashSettings.query.filter_by(entity_id=entity.id).delete()
        db.session.commit()
    F.login(client, owner)

    rows = _rows(_jinja(client, entity, **_range(1, 0)))

    assert sorted(r[1] for r in rows[1:]) == sorted(["", "445", "N/A", "N/A", "", "", "", "", "N/A", ""])


# --- FIXED with the service (2026-10-16) ------------------------------------------------------------


def _bytes(rows) -> bytes:
    lines = [",".join(f'"{c}"' if "," in c else c for c in r) for r in [HEADER] + rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_fixed_the_file_is_the_same_bytes_on_every_platform_with_lines_as_entered(app, client, books):
    """pandas ended lines with os.linesep (CRLF on Windows, LF on Linux) and read a day's lines in no
    order; now LF everywhere and each day's lines as they were entered."""
    owner, entity, _ids = books
    F.login(client, owner)

    assert _jinja(client, entity, **_range(1, 0)).get_data() == _bytes(SUBMITTED_ROWS)


def test_fixed_a_draft_is_not_exported(app, client, books):
    """A draft's figures are a day still being counted: the range export took them, and one draft
    exported by id although the 404 already said "submitted or published" only."""
    owner, entity, ids = books
    F.login(client, owner)

    assert _rows(_jinja(client, entity, **_range(2, 0)))[1:] == SUBMITTED_ROWS
    only_draft = _jinja(client, entity, **_range(2, 2))
    assert only_draft.status_code == 404
    assert only_draft.get_json()["message"] == "No reports found in the specified date range."
    by_id = _jinja(client, entity, report_id=ids["draft"])
    assert by_id.status_code == 404
    assert by_id.get_json()["message"] == "I can only download submitted or published reports as CSV."


def test_fixed_a_report_id_from_another_company_or_malformed_is_404(app, client, db, books):  # noqa: F811
    """Another company's report came out under this company's address; a malformed id was a 500."""
    from models.db import Report

    owner, entity, _ids = books
    with app.app_context():
        theirs = F.make_entity(db, owner, name="Second Shop")
        row = Report(entity_id=theirs.id, transaction_date=D3, status="submitted", created_by=owner.id,
                     cash_sales=5)
        db.session.add(row)
        db.session.commit()
        other = str(row.id)
    F.login(client, owner)

    for report_id in (other, "not-a-uuid"):
        resp = _jinja(client, entity, report_id=report_id)
        assert resp.status_code == 404, (report_id, resp.data[:200])


@pytest.mark.parametrize("query, message", [
    ({"start_date": "01/10/2026", "end_date": "2026-10-02"},
     "That date doesn't look quite right — could you use YYYY-MM-DD?"),
    ({"start_date": "2025-01-01", "end_date": "2026-01-02"},
     "That range is longer than a year — could you choose 366 days or fewer?"),
])
def test_fixed_a_malformed_or_unbounded_range_is_refused(app, client, books, query, message):
    """A malformed date reached Postgres (a 500); a range had no limit."""
    owner, entity, _ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, **query)

    assert resp.status_code == 400 and resp.get_json() == {"status": "error", "message": message}


def test_a_year_of_366_days_is_allowed(app, client, books):
    owner, entity, _ids = books
    F.login(client, owner)

    resp = _jinja(client, entity, start_date=F.iso(D3 - timedelta(days=365)), end_date=F.iso(D3))

    assert resp.status_code == 200, resp.data[:300]


def test_fixed_the_range_takes_the_company_wide_view(app, client, db, books, monkeypatch):  # noqa: F811
    """The range holds everyone's reports, so it asks REPORT_VIEW_ENTITY, not REPORT_VIEW_OWN (both
    cashier today, so nobody's access changes)."""
    from models.db import UserEntity
    from services import permission_policy as policy

    _owner, entity, _ids = books
    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com", first_name="Cass")
        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
    F.login(client, cashier)
    assert _jinja(client, entity, **_range()).status_code == 200

    monkeypatch.setitem(policy.PERMISSION_RULES, policy.Permission.REPORT_VIEW_ENTITY,
                        policy.PermissionRule(policy.Role.SHOP_MANAGER))
    assert _jinja(client, entity, **_range()).status_code == 403


# --- the Petty Cash API: GET /reports/export.csv ------------------------------------------------------


def _api(app, client, entity, who, **query):
    headers = F.petty_cash_headers(app, who.id, origin="http://localhost:3010")
    return client.get(f"/api/petty-cash/v1/companies/{entity.id}/reports/export.csv", query_string=query,
                      headers=headers)


def test_the_api_answers_the_same_file(app, client, books):
    owner, entity, _ids = books

    resp = _api(app, client, entity, owner, **_range(2, 0))

    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_data() == _bytes(SUBMITTED_ROWS)
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert resp.headers["Content-Disposition"] == (
        f"attachment; filename=acme-shop_reports_{_day(2)}_to_{_day(0)}.csv")
    assert resp.headers["Access-Control-Expose-Headers"] == "Content-Disposition"
    assert resp.headers["Access-Control-Allow-Origin"] == "http://localhost:3010"
    assert resp.headers["Cache-Control"] == "no-store"


def test_the_export_is_not_taken_for_a_report_id(app):
    """``/reports/<report_id>`` is registered too; the static rule wins whatever the order."""
    adapter = app.url_map.bind("localhost")
    endpoint, _args = adapter.match(f"/api/petty-cash/v1/companies/{uuid.uuid4()}/reports/export.csv")
    assert endpoint == "petty_cash_api.report_export_csv"
    endpoint, _args = adapter.match(f"/api/petty-cash/v1/companies/{uuid.uuid4()}/reports/{uuid.uuid4()}")
    assert endpoint == "petty_cash_api.daily_report"


def test_a_company_name_outside_ascii_travels_as_filename_star(app, client, db, books):  # noqa: F811
    from models.db import Entity

    owner, entity, _ids = books
    with app.app_context():
        db.session.get(Entity, entity.id).name = "茶餐廳 & Co"
        db.session.commit()

    resp = _api(app, client, entity, owner, **_range(1, 1))

    tail = f"_reports_{_day(1)}_to_{_day(1)}.csv"
    assert resp.headers["Content-Disposition"] == (
        f"attachment; filename=and-co{tail}; filename*=UTF-8''%E8%8C%B6%E9%A4%90%E5%BB%B3-and-co{tail}")


@pytest.mark.parametrize("query, message", [
    ({}, "Choose both dates to export the reports between them."),
    ({"start_date": "2026-10-01"}, "Choose both dates to export the reports between them."),
    ({"start_date": "01/10/2026", "end_date": "2026-10-02"},
     "A date isn't in the YYYY-MM-DD form. Choose it from the calendar."),
    ({"start_date": "2026-10-05", "end_date": "2026-10-02"},
     "The start date is after the end date. Choose a start on or before the end."),
    ({"start_date": "2025-01-01", "end_date": "2026-01-02"},
     "The range is longer than a year. Choose 366 days or fewer."),
])
def test_the_api_refuses_a_bad_range(app, client, books, query, message):
    owner, entity, _ids = books
    resp = _api(app, client, entity, owner, **query)
    assert resp.status_code == 422 and resp.get_json() == {"error": message}


def test_the_api_says_when_there_is_nothing_to_export(app, client, books):
    owner, entity, _ids = books
    for query in ({"start_date": "2020-01-01", "end_date": "2020-01-31"}, _range(2, 2)):  # nothing; a draft only
        resp = _api(app, client, entity, owner, **query)
        assert resp.status_code == 404 and resp.get_json() == {
            "error": "There are no submitted reports between those dates. Choose another range."}


def test_the_api_needs_the_company_wide_view(app, client, db, books):  # noqa: F811
    from models.db import UserEntity

    _owner, entity, _ids = books
    with app.app_context():
        base = F.make_user(db, "base@test.com", first_name="Bea")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()

    resp = _api(app, client, entity, base, **_range())

    assert resp.status_code == 403 and resp.get_json() == {
        "error": "You don't have permission to export this company's reports."}


def test_another_companys_export_is_refused_at_the_door(app, client, db, books):  # noqa: F811
    owner, _entity, _ids = books
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com", first_name="Sam")
        theirs = F.make_entity(db, stranger, name="Their Shop")
    assert _api(app, client, theirs, owner, **_range()).status_code == 403
