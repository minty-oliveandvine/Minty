"""Characterisation: the petty-cash report lifecycle, through the routes.

Pins what a user sees while a report goes draft -> posted, so the schema redesign
(``report`` loses 12 columns; sales become ``report_sale`` rows summed into
``nocashsale_total``; ``shop_expense`` becomes ``report_expense``; every money column
becomes ``numeric``) can be applied underneath without changing any of it.

Nothing here reads a model attribute. Totals are read back through
``/api/get_draft_totals``, the history page and the report detail page.
See docs/modernisation/modernisation_plan.md, Part 1 B3 group 1.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

import char_factories as F

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    """Empty tables before and after; NO app context is held across the test body.

    Holding one makes Flask reuse it for every simulated request, so ``g`` (and
    flask-login's cached user) leaks from one request into the next and the session
    teardown detaches it. Seeding and lookups open their own short context instead.
    """
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    """An admin, an active entity with Petty Cash on, HKD denominations and three sales methods."""
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa", "Alipay"), delivery=("Foodpanda",))
    return owner, entity


REPORT_DATE = date(2026, 9, 1)


def _post(client, url, **form):
    """POST a wizard form; the wizard answers a redirect on success and re-renders (200) on a
    validation error, so anything else is a crash."""
    resp = client.post(url, data=form, follow_redirects=False)
    assert resp.status_code in (200, 302), (url, resp.status_code, resp.data[:300])
    return resp


def open_report(client, entity, day=REPORT_DATE, *, opening="1000.00", addition="0"):
    return _post(client, "/report/opening", entity_id=entity.id, transaction_date=F.iso(day),
                 opening_balance=opening, cash_addition=addition, action_type="save_next")


def post_sales(client, entity, day, *, cash="0", by_method=None):
    """``by_method`` maps value_name -> amount for the entity's enabled methods."""
    methods = F.enabled_sales_methods(client.application, entity.id)
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "action_type": "save_next",
            "sales[shop_sales][cash]": cash}
    for value_name, amount in (by_method or {}).items():
        mtype, _ = methods[value_name]
        bucket = "delivery_sales" if str(mtype) == "delivery" else "shop_sales"  # sale_type enum word
        # the form names the method without its "_sales" suffix (templates/report/sales.html)
        form[f"sales[{bucket}][{value_name.replace('_sales', '')}]"] = amount
    return _post(client, "/report/sale", **form)


def add_expense(client, entity, day, item, amount, *, remarks=""):
    """One line, the way the page's "Add" button does it (/report/expense/add). Every line
    must carry a receipt; the S3 client is the FakeS3."""
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "item": item,
            "amount": amount, "remarks": remarks, "files[0][0]": F.receipt(f"{item}.jpg")}
    resp = client.post("/report/expense/add", data=form, content_type="multipart/form-data")
    assert resp.status_code == 200, (resp.status_code, resp.data[:300])
    body = resp.get_json()
    assert body["status"] == "success", body
    return body


def post_expenses(client, entity, day, items):
    """Add each line, then move the wizard on (the section save with no new lines)."""
    for item, amount in items:
        add_expense(client, entity, day, item, amount)
    return _post(client, "/report/expense", entity_id=entity.id, transaction_date=F.iso(day),
                 action_type="save_next")


def post_deposit(client, entity, day, amount):
    return _post(client, "/report/deposit", entity_id=entity.id, transaction_date=F.iso(day),
                 bank_deposit=amount, action_type="save_next")


def post_cash_count(client, entity, day, counts, *, safe_box="0", discrepancy="0", dtype="none", reason=""):
    """``counts`` maps face value -> quantity; unlisted denominations are 0."""
    fields = F.denomination_fields(client.application, entity.id)
    assert fields, "entity has no denominations - seed_currency not applied"
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "action_type": "save_next",
            "safe_box_balance": safe_box, "discrepancy_amount": discrepancy,
            "discrepancy_type": dtype, "discrepancy_reason": reason}
    for field, face in fields.items():
        form[f"actual_cash[{field}]"] = str(counts.get(face, 0))
    return _post(client, "/report/cash_count", **form)


def post_ending(client, entity, day):
    return _post(client, "/report/ending", entity_id=entity.id, transaction_date=F.iso(day),
                 action_type="submit")


def draft_totals(client, entity, day):
    resp = client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date={F.iso(day)}")
    assert resp.status_code == 200, resp.data[:300]
    return resp.get_json()


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def dollar_figures(html: str) -> set[Decimal]:
    """Every ``$1,234.5``-style amount on a page, as exact money. Formatting (one decimal
    today, two after the numeric change) is not the behaviour being pinned; the amounts are."""
    return {money(m.replace(",", "")) for m in re.findall(r"\$\s*(-?[\d,]+(?:\.\d+)?)", html)}


# ---------------------------------------------------------------------------------


def test_opening_creates_a_draft_visible_in_draft_totals(shop, client):
    owner, entity = shop
    F.login(client, owner)

    resp = open_report(client, entity, opening="1000.00", addition="50.00")

    assert resp.status_code == 302, resp.data[:300]
    assert "/reports/new/sale" in resp.headers["Location"], resp.headers["Location"]
    totals = draft_totals(client, entity, REPORT_DATE)
    assert totals["status"] == "success", totals


def test_the_withdrawal_source_is_kept_on_every_save_of_the_opening(shop, client, app):
    # Re-saving an existing draft stored the choice only when the form also carried a hidden
    # bank_account, which was empty for a company with no petty-cash account set (2026-10-05).
    from models.db import Report

    owner, entity = shop
    F.login(client, owner)

    def source():
        with app.app_context():
            row = Report.query.filter_by(entity_id=entity.id, transaction_date=REPORT_DATE).one()
            return row.cash_addition_type

    _post(client, "/report/opening", entity_id=entity.id, transaction_date=F.iso(REPORT_DATE),
          opening_balance="1000.00", cash_addition="50.00", withdrawal="company", action_type="save_next")
    assert source() == "company"

    _post(client, "/report/opening", entity_id=entity.id, transaction_date=F.iso(REPORT_DATE),
          opening_balance="1000.00", cash_addition="50.00", withdrawal="personal", action_type="save_next")
    assert source() == "personal"


def test_draft_totals_404_before_any_report_exists(shop, client):
    owner, entity = shop
    F.login(client, owner)
    resp = client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    assert resp.status_code == 404
    assert resp.get_json()["status"] == "error"


def test_sales_by_method_roll_up_into_totals(shop, client):
    """Non-cash total = sum of the per-method amounts; that sum is what survives the
    redesign (``nocashsale_total`` over ``report_sale`` rows)."""
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00")
    methods = F.enabled_sales_methods(client.application, entity.id)
    visa = next(v for v, (t, n) in methods.items() if n == "Visa")
    alipay = next(v for v, (t, n) in methods.items() if n == "Alipay")
    foodpanda = next(v for v, (t, n) in methods.items() if n == "Foodpanda")

    post_sales(client, entity, REPORT_DATE, cash="150.10",
               by_method={visa: "200.20", alipay: "0.30", foodpanda: "99.99"})

    page = client.get(f"{F.co(client, entity.id)}/reports/new/sale?transaction_date={F.iso(REPORT_DATE)}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for amount in ("150.1", "200.2", "0.3", "99.99"):
        assert amount in html, f"{amount} not shown on the sales page"


def test_expenses_total_is_the_sum_of_the_lines(shop, client):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00")
    post_sales(client, entity, REPORT_DATE, cash="100")

    post_expenses(client, entity, REPORT_DATE, [("Tape", "12.50"), ("Milk", "7.25"), ("Taxi", "80.00")])

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["total_expenses"]) == money("99.75"), totals


def test_expense_amounts_add_exactly(shop, client):
    """0.10 ten times is 1.00, not 0.9999999999999999 - the Float -> numeric change is the
    one type finding that is a bug, and this pins the arithmetic the user sees."""
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00")
    post_sales(client, entity, REPORT_DATE, cash="100")

    post_expenses(client, entity, REPORT_DATE, [(f"Item {i}", "0.10") for i in range(10)])

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["total_expenses"]) == money("1.00"), totals


def test_deposit_closes_the_balance(shop, client):
    """closing = opening + addition + cash sales - expenses - deposit."""
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00", addition="50.00")
    post_sales(client, entity, REPORT_DATE, cash="300.00")
    post_expenses(client, entity, REPORT_DATE, [("Tape", "25.00")])

    post_deposit(client, entity, REPORT_DATE, "500.00")

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["bank_deposit"]) == money("500.00"), totals
    assert money(totals["closing_balance"]) == money("825.00"), totals
    page = client.get(f"{F.co(client, entity.id)}/reports/new/deposit?transaction_date={F.iso(REPORT_DATE)}")
    assert page.status_code == 200


# ---- through to posted ----------------------------------------------------------------


def walk_to_cash_count(client, entity, day=REPORT_DATE, *, opening="1000.00", cash="300.00",
                       expenses=(("Tape", "25.00"),), deposit="500.00"):
    """Opening -> sales -> expenses -> deposit; returns the expected closing balance."""
    open_report(client, entity, day, opening=opening)
    post_sales(client, entity, day, cash=cash)
    post_expenses(client, entity, day, list(expenses))
    post_deposit(client, entity, day, deposit)
    return money(opening) + money(cash) - sum(money(a) for _, a in expenses) - money(deposit)


def count_exactly(amount: Decimal, faces) -> dict:
    """Denomination quantities that add up to ``amount`` using the entity's faces (largest first)."""
    counts, left = {}, amount
    for face in sorted(faces, reverse=True):
        q = int(left // Decimal(str(face)))
        if q:
            counts[face] = q
            left -= q * Decimal(str(face))
    assert left == 0, f"cannot make {amount} from {faces}"
    return counts


def history_rows(client, entity):
    page = client.get(f"{F.co(client, entity.id)}/reports")
    assert page.status_code == 200, page.data[:300]
    return page.get_data(as_text=True)


def history_badges(client, entity) -> list[str]:
    """The status word each row's badge shows (the JS on the page also says "Published")."""
    html = history_rows(client, entity)
    return re.findall(r'inline-flex items-center [^"]*">(Published|Publish failed|Submitted|Draft)', html)


def test_exact_cash_count_has_no_discrepancy(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()

    resp = post_cash_count(client, entity, REPORT_DATE, count_exactly(expected_closing, faces))

    assert resp.status_code == 302, resp.data[:300]
    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["closing_balance"]) == expected_closing, totals
    page = client.get(f"{F.co(client, entity.id)}/reports/new/cash-count?transaction_date={F.iso(REPORT_DATE)}")
    assert page.status_code == 200


def test_short_cash_count_records_a_shortage(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()
    counted = expected_closing - money("20.00")

    post_cash_count(client, entity, REPORT_DATE, count_exactly(counted, faces),
                    discrepancy="20.00", dtype="shortage", reason="till float short")

    page = client.get(f"{F.co(client, entity.id)}/reports/new/ending?transaction_date={F.iso(REPORT_DATE)}")
    assert page.status_code == 200
    assert "short" in page.get_data(as_text=True).lower()


def post_report(client, entity, day=REPORT_DATE, **walk):
    """The whole wizard, ending with the report posted. Returns (report id, closing balance)."""
    expected_closing = walk_to_cash_count(client, entity, day, **walk)
    faces = F.denomination_fields(client.application, entity.id).values()
    post_cash_count(client, entity, day, count_exactly(expected_closing, faces))
    resp = post_ending(client, entity, day)
    assert resp.status_code == 302, resp.data[:300]
    location = resp.headers["Location"]
    m = re.search(r"/reports/([0-9a-f-]{36})/submitted", location)
    assert m, f"ending did not land on the submitted page: {location}"
    return m.group(1), expected_closing


def test_ending_posts_the_report_and_lands_on_submitted(shop, client):
    owner, entity = shop
    F.login(client, owner)

    report_id, closing = post_report(client, entity)

    page = client.get(f"{F.co(client, entity.id)}/reports/{report_id}/submitted")
    assert page.status_code == 200
    assert report_id in history_rows(client, entity)
    # once posted there is no draft for that date any more
    resp = client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    assert resp.status_code == 404


def test_submitted_page_offers_a_first_publish_until_the_report_has_been_to_xero(shop, client, app):
    """publishing_status is NOT NULL since the redesign ('unpublished' is the never-published
    state): a fresh report gets the plain Publish button; only a report that has been through
    a publish (completed, or failed half-way) gets the republish warning."""
    from models.db import Report, db

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    html = client.get(f"{F.co(client, entity.id)}/reports/{report_id}/submitted").get_data(as_text=True)
    assert 'id="publishButton"' in html and 'id="republishButton"' not in html

    with app.app_context():
        report = db.session.get(Report, report_id)
        assert report.publishing_status == "unpublished"
        report.publishing_status = "failed"
        db.session.commit()
    html = client.get(f"{F.co(client, entity.id)}/reports/{report_id}/submitted").get_data(as_text=True)
    assert 'id="republishButton"' in html and 'id="publishButton"' not in html


def test_publish_locks_the_report_and_hands_it_to_the_background_worker(shop, client, app, monkeypatch):
    """The publish route takes a SELECT ... FOR UPDATE NOWAIT on the report. Since C4 the
    report eager-loads its creator (and the creator their token) through outer joins, and
    Postgres refuses to lock the nullable side of an outer join - the lock has to name the
    report table (``of=Report``). Xero itself is stubbed out; the DB is real."""
    import sys
    from types import SimpleNamespace

    from models.db import Report, db

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    route = sys.modules["blueprints.report.routes.submitted"]  # the module the app registered
    started = []
    monkeypatch.setattr(route, "resolve_xero_token", lambda entity_id, user: SimpleNamespace(access_token="tok", username=user.username))
    monkeypatch.setattr(route, "check_entity_xero_settings_complete", lambda entity_id: True)
    monkeypatch.setattr(route, "sync_entity_xero_status", lambda entity_id, **kw: None)
    monkeypatch.setattr(route, "validate_expenses_for_system_accounts", lambda *a, **kw: [])
    monkeypatch.setattr(route, "process_xero_integration_background", lambda *args: started.append(args))

    resp = client.post(f"/report/submitted/publish_to_xero?entity_id={entity.id}&report_id={report_id}")

    assert resp.status_code == 202, resp.data[:400]
    assert resp.get_json()["status"] == "publishing"
    with app.app_context():
        assert db.session.get(Report, report_id).publishing_status == "publishing"
    deadline = __import__("time").time() + 5
    while not started and __import__("time").time() < deadline:
        __import__("time").sleep(0.05)
    assert started and str(started[0][2]) == report_id, "the background worker was not handed the report"


def test_the_publish_finds_its_expense_line_by_the_xero_ids(shop, client, app):
    """A line links to the company's synced account and contact rows; the Xero ids the
    publish holds (account code, ContactID) live on those rows, so the lookup joins them.
    Filtering on the model's ``contact_id`` / ``account_code`` properties compiled to
    WHERE false after the redesign: no line found, so no receipt reached Xero."""
    import uuid
    from decimal import Decimal

    from blueprints.xero.services.publish import (expense_line_for_contact, expense_lines_for_contact,
                                                  find_expense_line)
    from models.db import AccountInfo, ShopExpense, XeroContactSync, db

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity, expenses=(("Light, Power, Heating", "25.10"),))
    xero_contact = str(uuid.uuid4())
    with app.app_context():
        account = AccountInfo(entity_id=entity.id, type="EXPENSE", name="Light, Power, Heating",
                              xero_account_id=str(uuid.uuid4()), xero_code="445", status="ACTIVE")
        contact = XeroContactSync(entity_id=entity.id, xero_contact_id=xero_contact, name="ABC Furniture")
        db.session.add_all([account, contact])
        db.session.flush()
        line = ShopExpense.query.filter_by(report_id=report_id).one()
        line.account = account
        line.contact = contact
        db.session.commit()
        line_id = line.id

        found = find_expense_line(report_id, item="Light, Power, Heating", amount=Decimal("25.10"),
                                  account_code="445", contact_id=xero_contact)
        assert found is not None and found.id == line_id
        assert find_expense_line(report_id, item="Light, Power, Heating", amount=Decimal("25.10"), account_code="445").id == line_id
        assert find_expense_line(report_id, item="Light, Power, Heating", amount=Decimal("25.10"), account_code="429") is None
        assert find_expense_line(report_id, item="Light, Power, Heating", amount=Decimal("25.10"),
                                 account_code="445", contact_id=str(uuid.uuid4())) is None
        assert expense_line_for_contact(report_id, xero_contact).id == line_id
        assert [e.id for e in expense_lines_for_contact(xero_contact)] == [line_id]


def test_posted_report_detail_shows_the_same_totals(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity, opening="1000.00", cash="300.00",
                                     expenses=(("Tape", "25.00"),), deposit="500.00")

    page = client.get(f"/report/{report_id}")
    assert page.status_code == 200, page.data[:300]
    html = page.get_data(as_text=True)
    shown = dollar_figures(html)
    for figure in ("1000.00", "300.00", "25.00", "500.00", "775.00"):
        assert money(figure) in shown, f"{figure} missing from the report detail; shown: {sorted(shown)}"
    assert "owner@test.com" in html or "Olive" in html, "creator not shown"


def test_history_csv_lists_the_days_movements(shop, client):
    """The CSV is a movement export: one line per expense, cash sale and deposit."""
    owner, entity = shop
    F.login(client, owner)
    post_report(client, entity)

    resp = client.get(f"{F.co(client, entity.id)}/reports/download-csv?start_date={F.iso(REPORT_DATE)}&end_date={F.iso(REPORT_DATE)}")

    assert resp.status_code == 200, resp.data[:300]
    rows = [r.split(",") for r in resp.get_data(as_text=True).splitlines() if r.strip()]
    assert rows[0][:3] == ["Date", "Account Code", "Amount"], rows[0]
    movements = {(r[3].strip(), money(r[2])) for r in rows[1:]}
    assert movements == {("Expense", money("-25.00")), ("Cash Sale (Pettycash)", money("300.00")),
                         ("Bank Deposit", money("-500.00"))}, movements
    assert all(r[0] == F.iso(REPORT_DATE) for r in rows[1:])


def test_history_csv_without_a_date_range_is_refused(shop, client):
    owner, entity = shop
    F.login(client, owner)
    resp = client.get(f"{F.co(client, entity.id)}/reports/download-csv")
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_convert_to_draft_reopens_the_report_at_opening(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    resp = client.post(f"/report/{report_id}/convert-to-draft")

    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["status"] == "success" and body["draft_id"] == report_id, body
    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["opening_balance"]) == money("1000.00")
    assert money(totals["cash_sales"]) == money("300.00")
    assert money(totals["bank_deposit"]) == money("500.00")
    resume = client.get(f"{F.co(client, entity.id)}/reports/resume?transaction_date={F.iso(REPORT_DATE)}")
    assert resume.status_code == 302 and "/opening" in resume.headers["Location"]


def test_convert_to_draft_keeps_the_expenses(shop, client):
    """F1 (fixed in C4): reverting no longer deletes the expense lines."""
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    client.post(f"/report/{report_id}/convert-to-draft")

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["total_expenses"]) == money("25.00"), totals
    assert money(totals["closing_balance"]) == closing, totals


def test_an_edit_after_a_xero_publish_drops_the_report_back_to_submitted(shop, client, app):
    """draft -> submitted -> published; an edit that diverges from Xero is submitted again
    (publishable afresh), and the publish markers that warn about duplicates stay."""
    from datetime import datetime, timezone

    from blueprints.shared.enums import ReportStatus
    from models.db import Report, db

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    with app.app_context():
        report = db.session.get(Report, report_id)
        assert report.status == ReportStatus.SUBMITTED and report.submitted_at is not None
        # what a complete Xero publish writes (publish.py), without Xero
        report.status = ReportStatus.PUBLISHED
        report.published_at = datetime.now(timezone.utc)
        report.xero_integrated = True
        report.publishing_status = "completed"
        db.session.commit()
    assert history_badges(client, entity) == ["Published"]

    resp = client.post(f"/report/{report_id}/edit/discrepancy-reason", data={"discrepancy_reason": "recounted"})

    assert resp.status_code == 200, resp.data[:300]
    with app.app_context():
        report = db.session.get(Report, report_id)
        assert report.status == ReportStatus.SUBMITTED
        assert report.xero_integrated is False
        assert report.publishing_status == "completed" and report.published_at is not None
    assert history_badges(client, entity) == ["Submitted"]


def test_delete_posted_report_removes_it_from_history(shop, client, s3):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    resp = client.post(f"/report/delete/{report_id}")

    assert resp.status_code == 302, resp.data[:300]
    assert report_id not in history_rows(client, entity)
    assert client.get(f"/report/{report_id}").status_code == 404


def test_every_receipt_the_detail_page_shows_is_an_object_the_bucket_holds(shop, client, s3, app):
    """Receipts named before 2026-09-18 carry the expense item verbatim, commas included
    ("Staff Welfare - Meal, Transport etc" -> ``..._MEAL,_TRANSPORT_ETC_25.jpg``; 1,195 such
    keys in production). The comma-joined ``files`` value used to be split on every comma, so
    the pages asked the bucket for two halves no object has: a broken image ("Key not found").
    The key here is planted the way the loader stores such a row, whatever new uploads are
    named."""
    import zipfile
    from html import unescape
    from io import BytesIO
    from urllib.parse import unquote

    from models.db import ShopExpense, db

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity, expenses=(("Tape", "25.00"),))
    legacy_key = f"expenses/{report_id}/01_SEP_2026_STAFF_WELFARE_-_MEAL,_TRANSPORT_ETC_25.jpg"
    with app.app_context():
        expense = ShopExpense.query.filter_by(report_id=report_id).one()
        s3.objects[legacy_key] = s3.objects.pop(expense.receipt_keys[0])
        expense.files = legacy_key  # the comma-joined shape the old column had
        db.session.commit()
        assert expense.receipt_keys == [legacy_key]

    # the detail page links one download per receipt, and each download is a key the
    # bucket holds (the link redirects to the object's presigned URL)
    html = client.get(f"/report/{report_id}").get_data(as_text=True)
    links = [unquote(unescape(h)) for h in re.findall(r'href="(/download/[^"]+)"', html)]
    assert links == [f"/download/{legacy_key}"], f"receipt links {links}"
    resp = client.get(links[0])
    assert resp.status_code == 302 and resp.headers["Location"] == f"https://fake-s3.test/{legacy_key}", resp.headers.get("Location")

    # the attachments download: the same receipt, whole, inside the zip. It spans every
    # company, so only a superuser may run it (2026-10-05).
    from models.db import User

    with app.app_context():
        root = F.make_user(db, "root@test.com", system_role=User.SYSTEM_ROLE_SUPERUSER)
    F.login(client, root)
    resp = client.post("/download_attachments", data={"start_date": F.iso(REPORT_DATE), "end_date": F.iso(REPORT_DATE),
                                                       "company": entity.id})
    assert resp.status_code == 200, resp.data[:300]
    names = zipfile.ZipFile(BytesIO(resp.data)).namelist()
    assert names == [f"{F.iso(REPORT_DATE)}/{legacy_key.rsplit('/', 1)[-1]}"], names


def test_delete_posted_report_removes_its_receipts_from_storage(shop, client, s3):
    """F2 (fixed in C4): the expense lines' receipts go with the report."""
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    assert s3.objects, "the expense receipt should have been stored"

    client.post(f"/report/delete/{report_id}")

    assert not s3.objects, f"receipts left behind: {list(s3.objects)}"


def test_resume_lands_on_the_next_incomplete_section(shop, client):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity)
    post_sales(client, entity, REPORT_DATE, cash="10")

    resp = client.get(f"{F.co(client, entity.id)}/reports/resume?transaction_date={F.iso(REPORT_DATE)}")

    assert resp.status_code == 302, resp.data[:300]
    assert "/expense" in resp.headers["Location"], resp.headers["Location"]


def test_next_day_opening_is_yesterdays_closing(shop, client):
    """Posting day 1 seeds day 2's opening balance."""
    owner, entity = shop
    F.login(client, owner)
    _, closing = post_report(client, entity, REPORT_DATE)
    day2 = REPORT_DATE + timedelta(days=1)

    page = client.get(f"{F.co(client, entity.id)}/reports/new/opening?transaction_date={F.iso(day2)}")

    assert page.status_code == 200, page.data[:300]
    html = page.get_data(as_text=True)
    assert f"{closing:,.2f}" in html or str(closing) in html, f"{closing} not offered as day-2 opening"


def test_a_second_report_for_the_same_day_is_refused(shop, client):
    owner, entity = shop
    F.login(client, owner)
    post_report(client, entity, REPORT_DATE)

    resp = open_report(client, entity, REPORT_DATE)

    # the wizard bounces with a flash rather than creating a duplicate
    assert resp.status_code == 302
    assert "/sale" not in resp.headers.get("Location", "")
    assert client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}").status_code == 404


def test_member_without_report_rights_cannot_open_the_wizard(shop, client, app, db):
    owner, entity = shop
    with app.app_context():
        viewer = F.make_user(db, "viewer@test.com")
        from models.db import UserEntity
        db.session.add(UserEntity(user_id=viewer.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    F.login(client, viewer)

    resp = open_report(client, entity)

    assert resp.status_code == 302
    assert "/sale" not in resp.headers.get("Location", "")
