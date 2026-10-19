"""The Petty Cash API's Expenses step (``blueprints/petty_cash_api/routes/expenses.py``): the page's
read, adding and deleting a line, a receipt's bytes and the step's save, through the same service
the Jinja page's routes use (``report/services/expenses.py``; pinned by
tests/test_report_expenses_state.py). The door (token, membership, module, CORS) is
tests/test_petty_cash_api_door.py's.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from io import BytesIO

import char_factories as F
import pytest

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _hk_today():
    from models.db import tz

    return datetime.now(tz).date()


D3 = _hk_today() - timedelta(days=1)


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


def _company(db, owner, name):
    from models.db import AccountInfo, CountryInfo, CurrencyInfo, EntityAccountXero, XeroContactSync

    currency = CurrencyInfo.query.filter_by(currency_code="HKD").first() or F.seed_currency(db)
    country = CountryInfo.query.filter_by(country_code="HK").first() or F.seed_country(db, currency)
    entity = F.make_entity(db, owner, name=name, currency=currency, country=country)
    for xero_id, contact in (("con-0002", "Taxi Co"), ("con-0001", "ABC Supplies")):
        db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id=xero_id, name=contact))
    for xero_id, code, account, active in (("acc-0001", "400", "Advertising", True), ("acc-0002", "429", "General", False)):
        row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id=xero_id, xero_code=code,
                          name=account, type="EXPENSE", status="ACTIVE")
        db.session.add(row)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=row.id, name=account, type="EXPENSE", xero_account_id=xero_id,
                                         is_active=active))
    db.session.commit()
    return entity


@pytest.fixture
def shop(app, db):
    with app.app_context():
        owner = F.make_user(db, "owner@test.com")
        entity = _company(db, owner, "Acme Shop")
    return owner, entity


def _draft(app, db, entity, owner, day=D3, **fields):
    from models.db import Report

    values = {"opening_balance": 100, "cash_addition": 20, "adjusted_opening_balance": 120, "cashsale_total": 50,
              "closing_balance": 170, "completed_sections": ["opening", "sales"], "current_section": "expenses"}
    values.update(fields)
    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=day, status=values.pop("status", "draft"),
                     created_by=owner.id, **values)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def _row(app, report_id):
    from models.db import Report, db

    with app.app_context():
        row = db.session.get(Report, report_id)
        return {"expenses": row.expense_total, "closing": row.closing_balance, "section": row.current_section,
                "completed": row.completed_sections}


def _headers(app, who):
    return F.petty_cash_headers(app, who.id, origin=WEB)


def _base(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}"


def _get(app, client, who, entity, day=D3):
    return client.get(f"{_base(entity)}/reports/expenses", query_string={"transaction_date": F.iso(day)},
                      headers=_headers(app, who))


def _add(app, client, who, entity, *, receipt=JPEG, name="till-slip.jpg", claimed="image/jpeg", **over):
    form = {"transaction_date": F.iso(D3), "amount": "1,012.50", "remarks": "Flyers",
            "supplier_id": "con-0001", "account_id": "acc-0001"}
    form.update(over)
    if receipt is not None:
        form["receipt"] = (BytesIO(receipt), name, claimed)
    return client.post(f"{_base(entity)}/reports/expenses/lines", data=form, content_type="multipart/form-data",
                       headers=_headers(app, who))


# --- GET ---------------------------------------------------------------------------------------------


def test_the_page_brings_the_lines_and_what_a_line_may_use(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    _add(app, client, owner, entity)

    resp = _get(app, client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["transaction_date"] == F.iso(D3) and body["currency_code"] == "HKD"
    assert body["draft"]["id"] == draft and body["draft"]["completed_sections"] == ["opening", "sales"]
    assert body["suppliers"] == [{"id": "con-0001", "name": "ABC Supplies"}, {"id": "con-0002", "name": "Taxi Co"}]
    assert body["accounts"] == [{"id": "acc-0001", "code": "400", "name": "Advertising"}]
    assert body["total"] == 1012.5
    [line] = body["lines"]
    assert line["item"] == "Advertising" and line["amount"] == 1012.5 and line["remarks"] == "Flyers"
    assert line["supplier"] == {"id": "con-0001", "name": "ABC Supplies"}
    assert line["account"] == {"id": "acc-0001", "code": "400", "name": "Advertising"}
    assert [(r["name"], r["mime_type"]) for r in line["receipts"]] == [("till-slip.jpg", "image/jpeg")]
    assert body["permissions"] == {"create_supplier": True}


def test_with_no_draft_the_page_goes_back_to_opening(app, client, db, shop):
    owner, entity = shop
    resp = _get(app, client, owner, entity)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "I don't see a draft yet - let's start with the opening entry.",
                               "to": "opening"}


def test_a_bad_date_and_a_member_without_the_right_are_refused(app, client, db, shop):
    from models.db import UserEntity

    owner, entity = shop
    assert client.get(f"{_base(entity)}/reports/expenses", headers=_headers(app, owner)).status_code == 422
    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    _draft(app, db, entity, owner)
    assert _get(app, client, base, entity).status_code == 403
    assert _add(app, client, base, entity).status_code == 403


# --- adding a line -----------------------------------------------------------------------------------


def test_a_line_is_stored_with_its_receipt_as_its_bytes_say(app, client, db, shop, s3):
    from models.db import ShopExpense

    owner, entity = shop
    draft = _draft(app, db, entity, owner, bank_deposit=5)

    resp = _add(app, client, owner, entity, receipt=PNG, name="scan.pdf", claimed="application/pdf")

    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["total"] == 1012.5 and body["line"]["receipts"][0]["mime_type"] == "image/png"
    assert _row(app, draft)["closing"] == 100 + 20 + 50 - 1012.5 - 5
    with app.app_context():
        [line] = ShopExpense.query.filter_by(report_id=draft).all()
        assert line.contact_name == "ABC Supplies" and line.account_code == "400"
        assert line.receipt_keys[0] in s3.objects


@pytest.mark.parametrize("over, message", [
    ({"amount": "0"}, "Enter the amount as a number above 0"),
    ({"amount": "-5"}, "Enter the amount as a number above 0"),
    ({"amount": "twelve"}, "Enter the amount as a number above 0"),
    ({"amount": "100000000000"}, "up to 99,999,999,999.99"),
    ({"remarks": "x" * 301}, "Keep the description to 300 characters or fewer."),
    ({"supplier_id": "con-unknown"}, "Choose a supplier from the list."),
    ({"supplier_id": ""}, "Choose a supplier from the list."),
    ({"account_id": "acc-0002"}, "Choose an account code from the list."),  # switched off
    ({"receipt": None}, "Attach the receipt to add this expense."),
    ({"receipt": b"GIF89a-not-allowed"}, "Attach a PDF, JPEG or PNG file."),
    ({"receipt": b""}, "That file is empty. Attach the receipt again."),
    ({"receipt": b"%PDF" + b"0" * (10 * 1024 * 1024)}, "Attach a file of 10 MB or less."),
    ({"transaction_date": "14/10/2026"}, "That date doesn't look quite right!"),
])
def test_bad_input_is_a_422_and_nothing_is_stored(app, client, db, shop, s3, over, message):
    from models.db import ShopExpense

    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _add(app, client, owner, entity, **over)

    assert resp.status_code == 422
    assert message in resp.get_json()["error"]
    with app.app_context():
        assert ShopExpense.query.filter_by(report_id=draft).count() == 0
    assert s3.objects == {}


def test_a_line_without_a_draft_goes_back_to_opening(app, client, db, shop):
    owner, entity = shop
    resp = _add(app, client, owner, entity)

    assert resp.status_code == 409 and resp.get_json()["to"] == "opening"


def test_a_line_on_a_submitted_day_is_refused(app, client, db, shop):
    from models.db import Report

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    with app.app_context():
        db.session.get(Report, draft).status = "submitted"
        db.session.commit()

    # the day has no draft any more: the app goes back to Opening, which refuses the day
    assert _add(app, client, owner, entity).status_code == 409


# --- deleting a line ---------------------------------------------------------------------------------


def test_deleting_a_line_answers_the_new_total(app, client, db, shop, s3):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    gone = _add(app, client, owner, entity, amount="10").get_json()["line"]
    _add(app, client, owner, entity, amount="15")

    resp = client.delete(f"{_base(entity)}/expense-lines/{gone['id']}", headers=_headers(app, owner))

    assert resp.status_code == 200 and resp.get_json() == {"total": 15.0}
    assert _row(app, draft)["expenses"] == 15
    assert len(s3.deleted) == 1


def test_a_line_of_another_company_or_a_submitted_report_is_left_alone(app, client, db, shop):
    from models.db import Report

    owner, entity = shop
    with app.app_context():
        other = _company(db, owner, "Other Shop")
    _draft(app, db, other, owner)
    theirs = _add(app, client, owner, other, amount="10").get_json()["line"]["id"]
    assert client.delete(f"{_base(entity)}/expense-lines/{theirs}", headers=_headers(app, owner)).status_code == 404
    assert client.delete(f"{_base(entity)}/expense-lines/not-a-uuid", headers=_headers(app, owner)).status_code == 404

    draft = _draft(app, db, entity, owner)
    mine = _add(app, client, owner, entity, amount="10").get_json()["line"]["id"]
    with app.app_context():
        db.session.get(Report, draft).status = "submitted"
        db.session.commit()
    resp = client.delete(f"{_base(entity)}/expense-lines/{mine}", headers=_headers(app, owner))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "This report isn't a draft anymore, so I can't change its expenses."


# --- a receipt's bytes -------------------------------------------------------------------------------


def test_a_receipt_comes_back_by_its_id_with_the_type_its_bytes_say(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, receipt=PNG, name="scan.png", claimed="image/png").get_json()["line"]
    receipt = line["receipts"][0]["id"]

    resp = client.get(f"{_base(entity)}/expense-lines/{line['id']}/receipts/{receipt}", headers=_headers(app, owner))

    assert resp.status_code == 200
    assert resp.data == PNG and resp.headers["Content-Type"] == "image/png"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Access-Control-Allow-Origin"] == WEB
    wrong = client.get(f"{_base(entity)}/expense-lines/{line['id']}/receipts/{uuid.uuid4()}", headers=_headers(app, owner))
    assert wrong.status_code == 404


# --- the step's save ---------------------------------------------------------------------------------


def test_save_next_marks_expenses_done_and_save_exit_records_nothing(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    url = f"{_base(entity)}/reports/expenses"

    exit_ = client.put(url, json={"transaction_date": F.iso(D3), "action": "exit"}, headers=_headers(app, owner))
    assert exit_.status_code == 200 and exit_.get_json()["next"] == "dashboard"
    assert _row(app, draft)["completed"] == ["opening", "sales"]

    nxt = client.put(url, json={"transaction_date": F.iso(D3), "action": "next"}, headers=_headers(app, owner))
    assert nxt.status_code == 200
    assert nxt.get_json()["next"] == "deposit" and nxt.get_json()["current_section"] == "deposit"
    assert _row(app, draft)["completed"] == ["opening", "sales", "expenses"]

    bad = client.put(url, json={"transaction_date": F.iso(D3), "action": "later"}, headers=_headers(app, owner))
    assert bad.status_code == 422


# --- editing a draft's line (PATCH /expense-lines/<id>) ----------------------------------------------


def _edit(app, client, who, entity, line_id, *, receipt=None, name="new.png", claimed="image/png", **form):
    data = dict(form)
    if receipt is not None:
        data["receipt"] = (BytesIO(receipt), name, claimed)
    return client.patch(f"{_base(entity)}/expense-lines/{line_id}", data=data, content_type="multipart/form-data",
                        headers=_headers(app, who))


def _second_receipt(app, line_id, s3, key="expenses/second.jpg"):
    """A second receipt on a line (the Jinja page can add several; the API adds one)."""
    from models.db import ShopExpense, db

    s3.objects[key] = JPEG
    with app.app_context():
        line = db.session.get(ShopExpense, line_id)
        attachment = line.add_receipt(key, original_name="second.jpg", mime_type="image/jpeg")
        db.session.commit()
        return str(attachment.id)


def test_a_draft_line_is_changed_in_place_and_the_totals_follow(app, client, db, shop, s3):
    from models.db import AccountInfo, EntityAccountXero

    owner, entity = shop
    with app.app_context():
        row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id="acc-0003", xero_code="461",
                          name="Printing", type="EXPENSE", status="ACTIVE")
        db.session.add(row)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=row.id, name="Printing", type="EXPENSE",
                                         xero_account_id="acc-0003", is_active=True))
        db.session.commit()
    draft = _draft(app, db, entity, owner, bank_deposit=5)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]
    _add(app, client, owner, entity, amount="15")

    resp = _edit(app, client, owner, entity, line["id"], amount="1,234.50", remarks="  Posters ",
                 supplier_id="con-0002", account_id="acc-0003")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["total"] == 1249.5
    changed = body["line"]
    assert changed["id"] == line["id"] and changed["amount"] == 1234.5 and changed["remarks"] == "Posters"
    assert changed["item"] == "Printing"  # a new account renames the line
    assert changed["supplier"] == {"id": "con-0002", "name": "Taxi Co"}
    assert changed["account"] == {"id": "acc-0003", "code": "461", "name": "Printing"}
    assert changed["receipts"] == line["receipts"]  # no file sent: the receipt is kept
    assert _row(app, draft)["expenses"] == 1249.5
    assert _row(app, draft)["closing"] == 100 + 20 + 50 - 1249.5 - 5
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_fields_not_sent_stay_and_an_empty_description_clears(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]

    resp = _edit(app, client, owner, entity, line["id"], remarks="")

    assert resp.status_code == 200
    changed = resp.get_json()["line"]
    assert changed["remarks"] == "" and changed["amount"] == 10.0
    assert changed["supplier"] == line["supplier"] and changed["account"] == line["account"]


def test_a_new_receipt_replaces_the_line_s_and_the_old_file_goes(app, client, db, shop, s3):
    from models.db import ShopExpense

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]
    with app.app_context():
        old_key = db.session.get(ShopExpense, line["id"]).receipt_keys[0]

    resp = _edit(app, client, owner, entity, line["id"], receipt=PNG, name="scan.pdf", claimed="application/pdf")

    assert resp.status_code == 200, resp.get_json()
    [receipt] = resp.get_json()["line"]["receipts"]
    assert receipt["name"] == "scan.pdf" and receipt["mime_type"] == "image/png"  # typed by its bytes
    assert receipt["id"] != line["receipts"][0]["id"]
    assert old_key in s3.deleted
    with app.app_context():
        [row] = ShopExpense.query.filter_by(report_id=draft).all()
        assert s3.objects[row.receipt_keys[0]] == PNG


def test_a_receipt_can_be_removed_but_never_the_last_one(app, client, db, shop, s3):
    owner, entity = shop
    _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]
    first = line["receipts"][0]["id"]
    second = _second_receipt(app, line["id"], s3)

    resp = _edit(app, client, owner, entity, line["id"], remove_receipt_ids=second)

    assert resp.status_code == 200, resp.get_json()
    assert [r["id"] for r in resp.get_json()["line"]["receipts"]] == [first]
    assert "expenses/second.jpg" in s3.deleted

    last = _edit(app, client, owner, entity, line["id"], remove_receipt_ids=first)
    assert last.status_code == 422
    assert last.get_json()["error"] == (
        "Every expense needs its receipt. Attach a new receipt before removing the last one.")
    stranger = _edit(app, client, owner, entity, line["id"], remove_receipt_ids=str(uuid.uuid4()))
    assert stranger.status_code == 422 and "isn't on this expense" in stranger.get_json()["error"]

    # removing the last one WITH a replacement is a replacement
    swap = _edit(app, client, owner, entity, line["id"], remove_receipt_ids=first, receipt=PNG)
    assert swap.status_code == 200
    assert [r["mime_type"] for r in swap.get_json()["line"]["receipts"]] == ["image/png"]


@pytest.mark.parametrize("over, message", [
    ({"amount": "0"}, "Enter the amount as a number above 0"),
    ({"amount": "-5"}, "Enter the amount as a number above 0"),
    ({"amount": ""}, "Enter the amount as a number above 0"),
    ({"amount": "twelve"}, "Enter the amount as a number above 0"),
    ({"amount": "100000000000"}, "up to 99,999,999,999.99"),
    ({"remarks": "x" * 301}, "Keep the description to 300 characters or fewer."),
    ({"supplier_id": "con-unknown"}, "Choose a supplier from the list."),
    ({"account_id": "acc-0002"}, "Choose an account code from the list."),  # switched off
    ({"receipt": b"GIF89a-not-allowed"}, "Attach a PDF, JPEG or PNG file."),
    ({"receipt": b""}, "That file is empty. Attach the receipt again."),
    ({"receipt": b"%PDF" + b"0" * (10 * 1024 * 1024)}, "Attach a file of 10 MB or less."),
])
def test_bad_input_for_an_edit_is_a_422_and_nothing_changes(app, client, db, shop, s3, over, message):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]
    stored = dict(s3.objects)

    resp = _edit(app, client, owner, entity, line["id"], **over)

    assert resp.status_code == 422
    assert message in resp.get_json()["error"]
    page = _get(app, client, owner, entity).get_json()
    assert page["lines"] == [line] and _row(app, draft)["expenses"] == 10
    assert s3.objects == stored and s3.deleted == []


def test_two_receipts_in_one_edit_are_refused(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner)
    line = _add(app, client, owner, entity, amount="10").get_json()["line"]

    resp = client.patch(f"{_base(entity)}/expense-lines/{line['id']}",
                        data={"receipt": [(BytesIO(PNG), "a.png"), (BytesIO(PNG), "b.png")]},
                        content_type="multipart/form-data", headers=_headers(app, owner))

    assert resp.status_code == 422 and resp.get_json()["error"] == "Attach one receipt per expense."


def test_an_edit_is_refused_for_another_company_a_submitted_report_or_no_right(app, client, db, shop):
    from models.db import Report, UserEntity

    owner, entity = shop
    with app.app_context():
        other = _company(db, owner, "Other Shop")
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    _draft(app, db, other, owner)
    theirs = _add(app, client, owner, other, amount="10").get_json()["line"]["id"]
    assert _edit(app, client, owner, entity, theirs, amount="99").status_code == 404
    assert _edit(app, client, owner, entity, "not-a-uuid", amount="99").status_code == 404
    assert _edit(app, client, owner, entity, str(uuid.uuid4()), amount="99").status_code == 404

    draft = _draft(app, db, entity, owner)
    mine = _add(app, client, owner, entity, amount="10").get_json()["line"]["id"]
    refused = _edit(app, client, base, entity, mine, amount="99")
    assert refused.status_code == 403
    assert refused.get_json()["error"] == "You do not have permission to edit reports for this entity."

    with app.app_context():
        db.session.get(Report, draft).status = "submitted"
        db.session.commit()
    resp = _edit(app, client, owner, entity, mine, amount="99")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "This report isn't a draft anymore, so I can't change its expenses."
    assert _row(app, draft)["expenses"] == 10
