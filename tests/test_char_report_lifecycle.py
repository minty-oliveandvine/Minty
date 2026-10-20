"""Characterisation: the petty-cash report lifecycle, draft -> posted.

Pins what a user sees while a report goes draft -> posted, so the schema redesign
(``report`` loses 12 columns; sales become ``report_sale`` rows summed into
``nocashsale_total``; ``shop_expense`` becomes ``report_expense``; every money column
becomes ``numeric``) can be applied underneath without changing any of it.
See docs/modernisation/modernisation_plan.md, Part 1 B3 group 1.

Driven through the Jinja wizard until Flask's HTML frontend was deleted (2026-10-20); now through
the Petty Cash API (``/api/petty-cash/v1/companies/<id>/...``) as the person ``F.login`` signed in.
Two steps go straight to their service, because the API decides what the old form could choose: the
Opening (``save_opening`` with the form's opening for a first report, as the page saved it) and an
expense line (``add_expense`` with a free item; the API takes only the company's synced supplier and
account). The helpers keep their names for the files that import them. Totals are read back through
the API's Close read (``draft_totals``), the Daily Report and the report history.
"""

from __future__ import annotations

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


def _signed_in(client) -> str:
    """The id of the person ``F.login`` signed in on this client."""
    with client.session_transaction() as sess:
        return sess["_user_id"]


def _api(client, method, path, **kwargs):
    entity_id, _, rest = path.partition("/")
    headers = F.petty_cash_headers(client.application, _signed_in(client))
    return client.open(f"/api/petty-cash/v1/companies/{entity_id}/{rest}", method=method, headers=headers, **kwargs)


def _step(client, entity, step, day, **body):
    """PUT one wizard step (Save & Next); anything but a 200 is a failure of the walk."""
    resp = _api(client, "PUT", f"{entity.id}/reports/{step}", json={"transaction_date": F.iso(day), "action": "next", **body})
    assert resp.status_code == 200, (step, resp.status_code, resp.get_json())
    return resp


def open_report(client, entity, day=REPORT_DATE, *, opening="1000.00", addition="0", withdrawal="personal"):
    """The Opening step, through ``report/services/opening.py::save_opening`` - with ``opening`` for
    a company's first report unless onboarding set one, as the Jinja page saved it (the API
    always opens at the server's figure). Returns the draft's id."""
    from blueprints.report.services.opening import find_draft, first_report_opening, save_opening
    from models.db import User, db

    with client.application.app_context():
        user = db.session.get(User, _signed_in(client))
        balance = first_report_opening(entity.id, day)
        balance = float(balance) if balance is not None else float(opening)
        draft = save_opening(entity.id, user, day, balance, float(addition), withdrawal, "save_next",
                             existing_draft=find_draft(entity.id, day))
        return str(draft.id)


def post_sales(client, entity, day, *, cash="0", by_method=None):
    """``by_method`` maps value_name -> amount for the entity's enabled methods."""
    return _step(client, entity, "sales", day, cash_sales=float(cash),
                 amounts={v: float(a) for v, a in (by_method or {}).items()})


def add_expense(client, entity, day, item, amount, *, remarks=""):
    """One line with one receipt, through ``report/services/expenses.py::add_expense`` (the S3
    client is the FakeS3). Returns ``{"status", "expense": {"id", "files": [{"s3_key"}]}}``."""
    from io import BytesIO

    from werkzeug.datastructures import FileStorage

    from blueprints.report.services.expenses import add_expense as add
    from blueprints.report.services.opening import find_draft
    from models.db import User, db

    with client.application.app_context():
        user = db.session.get(User, _signed_in(client))
        receipt = FileStorage(BytesIO(b"\xff\xd8\xff\xe0fake-jpeg-bytes"), filename=f"{item}.jpg", content_type="image/jpeg")
        line = add(find_draft(entity.id, day), user, item=item, amount=float(amount), remarks=remarks, contact_id=None,
                   contact_name=None, account_id=None, account_code=None, files=[receipt])
        return {"status": "success",
                "expense": {"id": str(line.id), "files": [{"s3_key": key} for key in line.receipt_keys]}}


def post_expenses(client, entity, day, items):
    """Add each line, then move the wizard on (the step's save)."""
    for item, amount in items:
        add_expense(client, entity, day, item, amount)
    return _step(client, entity, "expenses", day)


def post_deposit(client, entity, day, amount):
    return _step(client, entity, "deposit", day, bank_deposit=float(amount))


def _denomination_ids(app, entity) -> dict:
    """face value -> the denomination id the API takes."""
    from blueprints.report.services.cash_denominations import resolve_denominations_for_entity

    with app.app_context():
        return {float(d.cash_value): str(d.cash_id) for d in resolve_denominations_for_entity(entity.id)}


def post_cash_count(client, entity, day, counts, *, safe_box="0", reason=""):
    """``counts`` maps face value -> quantity; unlisted denominations are 0. The difference is the
    server's (counted + safebox - expected)."""
    ids = _denomination_ids(client.application, entity)
    assert ids, "entity has no denominations - seed_currency not applied"
    return _step(client, entity, "cash-count", day, counts={ids[float(f)]: int(n) for f, n in counts.items()},
                 safe_box_balance=float(safe_box), discrepancy_reason=reason)


def post_ending(client, entity, day):
    resp = _api(client, "POST", f"{entity.id}/reports/submit", json={"transaction_date": F.iso(day)})
    assert resp.status_code == 200, resp.get_json()
    return resp


def draft_totals(client, entity, day):
    """The day's draft as the Close read shows it; ``closing_balance`` is the expected cash (no
    difference), as Flask's old draft-totals read worked it out."""
    resp = _api(client, "GET", f"{entity.id}/reports/close", query_string={"transaction_date": F.iso(day)})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return {"status": "success", "opening_balance": body["opening_balance"], "cash_addition": body["cash_addition"],
            "cash_sales": body["sales"]["cash"], "total_sales": body["sales"]["total"],
            "total_expenses": body["expenses"]["total"], "bank_deposit": body["cash"]["bank_deposit"],
            "closing_balance": body["cash"]["expected"], "difference": body["cash"]["difference"],
            "discrepancy_amount": body["cash"]["difference"]["amount"]}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def dollar_figures(body) -> set[Decimal]:
    """Every amount in a JSON answer (nested), as the exact Decimal it was sent as - so a float
    that drifted off the cent (0.30000000000000004) is not in the set as 0.30."""
    found = set()

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            found.add(Decimal(str(node)))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body)
    return found


def history(client, entity) -> list[dict]:
    """The report history's rows (``GET /reports``)."""
    resp = _api(client, "GET", f"{entity.id}/reports", query_string={"per_page": 100})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["reports"]


def history_badges(client, entity) -> list[str]:
    """The Status pill each row shows (Part 14 Status pill: the words carry the meaning)."""
    return [r["status_label"] for r in history(client, entity)]


# ---------------------------------------------------------------------------------


def test_opening_creates_a_draft_visible_in_draft_totals(shop, client):
    owner, entity = shop
    F.login(client, owner)

    open_report(client, entity, opening="1000.00", addition="50.00")

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["opening_balance"]) == money("1000.00") and money(totals["cash_addition"]) == money("50.00")


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

    _step(client, entity, "opening", REPORT_DATE, cash_addition=50, withdrawal="company")
    assert source() == "company"

    _step(client, entity, "opening", REPORT_DATE, cash_addition=50, withdrawal="personal")
    assert source() == "personal"


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

    page = _api(client, "GET", f"{entity.id}/reports/sales", query_string={"transaction_date": F.iso(REPORT_DATE)})
    assert page.status_code == 200
    body = page.get_json()
    shown = {m["value_name"]: money(m["amount"]) for m in body["methods"]}
    assert (shown[visa], shown[alipay], shown[foodpanda]) == (money("200.20"), money("0.30"), money("99.99"))
    assert money(body["cash_sales"]) == money("150.10")
    assert money(draft_totals(client, entity, REPORT_DATE)["total_sales"]) == money("450.59")


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


def test_exact_cash_count_has_no_discrepancy(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()

    post_cash_count(client, entity, REPORT_DATE, count_exactly(expected_closing, faces))

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["closing_balance"]) == expected_closing, totals
    assert totals["difference"]["kind"] == "none"


def test_short_cash_count_records_a_shortage(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()
    counted = expected_closing - money("20.00")

    post_cash_count(client, entity, REPORT_DATE, count_exactly(counted, faces), reason="till float short")

    difference = draft_totals(client, entity, REPORT_DATE)["difference"]
    assert difference["kind"] == "short" and money(difference["amount"]) == money("-20.00")


def post_report(client, entity, day=REPORT_DATE, **walk):
    """The whole wizard, ending with the report posted. Returns (report id, closing balance)."""
    expected_closing = walk_to_cash_count(client, entity, day, **walk)
    faces = F.denomination_fields(client.application, entity.id).values()
    post_cash_count(client, entity, day, count_exactly(expected_closing, faces))
    resp = post_ending(client, entity, day)
    return resp.get_json()["report_id"], expected_closing


def test_ending_posts_the_report(shop, client):
    owner, entity = shop
    F.login(client, owner)

    report_id, closing = post_report(client, entity)

    outcome = _api(client, "GET", f"{entity.id}/reports/{report_id}/outcome")
    assert outcome.status_code == 200 and outcome.get_json()["submitted"] is True
    assert report_id in [r["id"] for r in history(client, entity)]
    # once posted there is no draft for that date any more
    resp = _api(client, "GET", f"{entity.id}/reports/close", query_string={"transaction_date": F.iso(REPORT_DATE)})
    assert resp.status_code == 409 and resp.get_json()["to"] == "submitted"


def test_the_publish_finds_its_expense_line_by_the_xero_ids(shop, client, app):
    """A line links to the company's synced account and contact rows; the Xero ids the
    publish holds (account code, ContactID) live on those rows, so the lookup joins them.
    Filtering on the model's ``contact_id`` / ``account_code`` properties compiled to
    WHERE false after the redesign: no line found, so no receipt reached Xero."""
    import uuid

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

    page = _api(client, "GET", f"{entity.id}/reports/{report_id}")
    assert page.status_code == 200, page.get_json()
    shown = dollar_figures(page.get_json())
    for figure in ("1000.00", "300.00", "25.00", "500.00", "775.00"):
        assert money(figure) in shown, f"{figure} missing from the Daily Report; shown: {sorted(shown)}"


def test_history_csv_lists_the_days_movements(shop, client):
    """The CSV is a movement export: one line per expense, cash sale and deposit."""
    owner, entity = shop
    F.login(client, owner)
    post_report(client, entity)

    resp = _api(client, "GET", f"{entity.id}/reports/export.csv",
                query_string={"start_date": F.iso(REPORT_DATE), "end_date": F.iso(REPORT_DATE)})

    assert resp.status_code == 200, resp.data[:300]
    rows = [r.split(",") for r in resp.get_data(as_text=True).splitlines() if r.strip()]
    assert rows[0][:3] == ["Date", "Account Code", "Amount"], rows[0]
    movements = {(r[3].strip(), money(r[2])) for r in rows[1:]}
    assert movements == {("Expense", money("-25.00")), ("Cash Sale (Pettycash)", money("300.00")),
                         ("Bank Deposit", money("-500.00"))}, movements
    assert all(r[0] == F.iso(REPORT_DATE) for r in rows[1:])


def test_reopening_puts_the_report_back_to_a_draft_at_opening(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    resp = _api(client, "POST", f"{entity.id}/reports/{report_id}/reopen")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["report_id"] == report_id and resp.get_json()["next"] == "opening"
    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["opening_balance"]) == money("1000.00")
    assert money(totals["cash_sales"]) == money("300.00")
    assert money(totals["bank_deposit"]) == money("500.00")


def test_reopening_keeps_the_expenses(shop, client):
    """F1 (fixed in C4): reverting no longer deletes the expense lines."""
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    _api(client, "POST", f"{entity.id}/reports/{report_id}/reopen")

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
    assert history_badges(client, entity) == ["Published to Xero"]

    resp = _api(client, "PUT", f"{entity.id}/reports/{report_id}/difference-reason", json={"reason": "recounted"})

    assert resp.status_code == 200, resp.get_json()
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

    resp = _api(client, "DELETE", f"{entity.id}/reports/{report_id}")

    assert resp.status_code == 200, resp.get_json()
    assert report_id not in [r["id"] for r in history(client, entity)]
    assert _api(client, "GET", f"{entity.id}/reports/{report_id}").status_code == 404


def test_a_legacy_receipt_key_with_commas_is_one_key(shop, client, s3, app):
    """Receipts named before 2026-09-18 carry the expense item verbatim, commas included
    ("Staff Welfare - Meal, Transport etc" -> ``..._MEAL,_TRANSPORT_ETC_25.jpg``; 1,195 such
    keys in production). The comma-joined ``files`` value used to be split on every comma, so
    the pages asked the bucket for two halves no object has: a broken image ("Key not found").
    The key here is planted the way the loader stores such a row, whatever new uploads are
    named. (The receipt's bytes: tests/test_petty_cash_api_expenses.py.)"""
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


def test_delete_posted_report_removes_its_receipts_from_storage(shop, client, s3):
    """F2 (fixed in C4): the expense lines' receipts go with the report."""
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    assert s3.objects, "the expense receipt should have been stored"

    _api(client, "DELETE", f"{entity.id}/reports/{report_id}")

    assert not s3.objects, f"receipts left behind: {list(s3.objects)}"


def test_next_day_opening_is_yesterdays_closing(shop, client):
    """Posting day 1 seeds day 2's opening balance."""
    owner, entity = shop
    F.login(client, owner)
    _, closing = post_report(client, entity, REPORT_DATE)
    day2 = REPORT_DATE + timedelta(days=1)

    page = _api(client, "GET", f"{entity.id}/reports/opening", query_string={"transaction_date": F.iso(day2)})

    assert page.status_code == 200, page.get_json()
    assert money(page.get_json()["starting_cash_balance"]) == closing


# ---- cash in stock (entity_cash_detail), 2026-10-13 ---------------------------------------
# A company's stock per denomination is the money its latest SUBMITTED report counted: rows are
# made on submit (one per active denomination of the company's current currency) and rebuilt on
# revert, delete and a submitted report's cash-count edit. Drafts never touch it.


def stock(app, entity) -> dict:
    """{face value: money in stock} for the company's entity_cash_detail rows."""
    from models.db import CashInfo, EntityCashDetail

    with app.app_context():
        rows = (EntityCashDetail.query.join(CashInfo, CashInfo.id == EntityCashDetail.cash_id)
                .filter(EntityCashDetail.entity_id == entity.id)
                .with_entities(CashInfo.cash_value, EntityCashDetail.cash_instock).all())
    return {money(face): money(amount or 0) for face, amount in rows}


def expected_stock(app, entity, counts) -> dict:
    faces = F.denomination_fields(app, entity.id).values()
    return {money(f): money(Decimal(str(f)) * counts.get(f, 0)) for f in faces}


def test_submitting_a_report_records_the_cash_in_stock(shop, client, app):
    owner, entity = shop
    F.login(client, owner)

    _report_id, closing = post_report(client, entity)

    faces = F.denomination_fields(app, entity.id).values()
    assert stock(app, entity) == expected_stock(app, entity, count_exactly(closing, faces))


def test_a_draft_cash_count_leaves_the_stock_alone(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(app, entity.id).values()

    post_cash_count(client, entity, REPORT_DATE, count_exactly(closing, faces))

    assert stock(app, entity) == {}


def test_reverting_the_only_report_empties_the_stock(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    _api(client, "POST", f"{entity.id}/reports/{report_id}/reopen")

    assert stock(app, entity) and set(stock(app, entity).values()) == {money("0")}


def test_deleting_the_latest_report_falls_back_to_the_one_before(shop, client, app, s3):
    owner, entity = shop
    F.login(client, owner)
    _first, first_closing = post_report(client, entity, REPORT_DATE)
    second_id, _ = post_report(client, entity, REPORT_DATE + timedelta(days=1),
                               opening=str(first_closing), cash="80.00")

    _api(client, "DELETE", f"{entity.id}/reports/{second_id}")

    faces = F.denomination_fields(app, entity.id).values()
    assert stock(app, entity) == expected_stock(app, entity, count_exactly(first_closing, faces))


def test_after_a_currency_change_the_stock_follows_the_new_currency(shop, client, app, db):
    from models.db import CashInfo, Entity

    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    with app.app_context():
        jpy = F.seed_currency(db, "JPY", denominations=(1000, 100))
        Entity.query.get(entity.id).currency_id = jpy.id
        db.session.commit()

    _api(client, "POST", f"{entity.id}/reports/{report_id}/reopen")

    with app.app_context():
        jpy_faces = {money(c.cash_value) for c in CashInfo.query.filter_by(currency_id=jpy.id)}
    assert stock(app, entity) == {face: money("0") for face in jpy_faces}


def test_an_all_zero_count_reads_as_counted_zero(shop, client, app):
    """No rows are stored for zero quantities; the done cash-count step makes it 0, not "never"."""
    from models.db import Report, db

    owner, entity = shop
    F.login(client, owner)
    walk_to_cash_count(client, entity)
    # an empty drawer against 775.00 expected is a difference, which needs a reason to be done
    post_cash_count(client, entity, REPORT_DATE, {}, reason="drawer emptied")

    with app.app_context():
        report = Report.query.filter_by(entity_id=entity.id, transaction_date=REPORT_DATE).one()
        assert report.actual_cash_total == 0.0
        sql_value = (db.session.query(Report.actual_cash_total)
                     .filter(Report.id == report.id).scalar())
        assert sql_value == 0
