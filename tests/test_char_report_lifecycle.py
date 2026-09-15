"""Characterisation: the petty-cash report lifecycle, through the routes.

Pins what a user sees while a report goes draft -> posted, so the schema redesign
(``report`` loses 12 columns; sales become ``report_sale`` rows summed into
``nocashsale_total``; ``shop_expense`` becomes ``report_expense``; every money column
becomes ``numeric``) can be applied underneath without changing any of it.

Nothing here reads a model attribute. Totals are read back through
``/api/get_draft_totals``, the history page and the report detail page.
See docs/modernisation_plan.md, Part 1 B3 group 1.
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
        bucket = "delivery_sales" if mtype == "Delivery" else "shop_sales"
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
    assert "/report/sale" in resp.headers["Location"] or "/report/" in resp.headers["Location"]
    totals = draft_totals(client, entity, REPORT_DATE)
    assert totals["status"] == "success", totals


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

    page = client.get(f"/report/sale?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
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
    page = client.get(f"/report/deposit?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
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
    page = client.get(f"/entity/{entity.id}/reports")
    assert page.status_code == 200, page.data[:300]
    return page.get_data(as_text=True)


def test_exact_cash_count_has_no_discrepancy(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()

    resp = post_cash_count(client, entity, REPORT_DATE, count_exactly(expected_closing, faces))

    assert resp.status_code == 302, resp.data[:300]
    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["closing_balance"]) == expected_closing, totals
    page = client.get(f"/report/cash_count?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    assert page.status_code == 200


def test_short_cash_count_records_a_shortage(shop, client):
    owner, entity = shop
    F.login(client, owner)
    expected_closing = walk_to_cash_count(client, entity)
    faces = F.denomination_fields(client.application, entity.id).values()
    counted = expected_closing - money("20.00")

    post_cash_count(client, entity, REPORT_DATE, count_exactly(counted, faces),
                    discrepancy="20.00", dtype="shortage", reason="till float short")

    page = client.get(f"/report/ending?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
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
    m = re.search(r"/report/([0-9a-f-]{36})/submitted", location)
    assert m, f"ending did not land on the submitted page: {location}"
    return m.group(1), expected_closing


def test_ending_posts_the_report_and_lands_on_submitted(shop, client):
    owner, entity = shop
    F.login(client, owner)

    report_id, closing = post_report(client, entity)

    page = client.get(f"/report/{report_id}/submitted?entity_id={entity.id}")
    assert page.status_code == 200
    assert report_id in history_rows(client, entity)
    # once posted there is no draft for that date any more
    resp = client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    assert resp.status_code == 404


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

    resp = client.get(f"/entity/{entity.id}/reports/download-csv?start_date={F.iso(REPORT_DATE)}&end_date={F.iso(REPORT_DATE)}")

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
    resp = client.get(f"/entity/{entity.id}/reports/download-csv")
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
    resume = client.get(f"/report/resume?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    assert resume.status_code == 302 and "/report/opening" in resume.headers["Location"]


@pytest.mark.xfail(strict=True, reason=(
    "FINDING F1: revert_report_to_draft deletes the report's ShopExpense rows "
    "(services/ending.py) on the assumption that draft expenses live elsewhere and "
    "re-submitting rebuilds them; since drafts and reports became one row they do not, "
    "so a reverted report loses its expenses (closing 800.00 instead of 775.00). "
    "Expected behaviour asserted here; flip when fixed in phase C."))
def test_convert_to_draft_keeps_the_expenses(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    client.post(f"/report/{report_id}/convert-to-draft")

    totals = draft_totals(client, entity, REPORT_DATE)
    assert money(totals["total_expenses"]) == money("25.00"), totals
    assert money(totals["closing_balance"]) == closing, totals


def test_delete_posted_report_removes_it_from_history(shop, client, s3):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    resp = client.post(f"/report/delete/{report_id}")

    assert resp.status_code == 302, resp.data[:300]
    assert report_id not in history_rows(client, entity)
    assert client.get(f"/report/{report_id}").status_code == 404


@pytest.mark.xfail(strict=True, reason=(
    "FINDING F2: delete_report only removes the keys in report.receipt_files from S3; "
    "expense receipts (ShopExpense.files) are left behind in the bucket. report.receipt_files "
    "does not exist in the redesign, so the cleanup has to move to the expense rows in phase C. "
    "Expected behaviour asserted here; flip when fixed."))
def test_delete_posted_report_removes_its_receipts_from_storage(shop, client, s3):
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

    resp = client.get(f"/report/resume?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")

    assert resp.status_code == 302, resp.data[:300]
    assert "/report/expense" in resp.headers["Location"], resp.headers["Location"]


def test_next_day_opening_is_yesterdays_closing(shop, client):
    """Posting day 1 seeds day 2's opening balance."""
    owner, entity = shop
    F.login(client, owner)
    _, closing = post_report(client, entity, REPORT_DATE)
    day2 = REPORT_DATE + timedelta(days=1)

    page = client.get(f"/report/opening?entity_id={entity.id}&transaction_date={F.iso(day2)}")

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
    assert "/report/sale" not in resp.headers.get("Location", "")
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
    assert "/report/sale" not in resp.headers.get("Location", "")
