"""Characterisation: an expense's receipts - stored, listed, and gone with the line.

C4 moves the receipt from two text columns on the expense (``files``, ``s3_key`` - a
comma-separated list of keys) to rows: ``attachment`` + ``report_expense_attachment``. What
the user sees must not move:

* adding a line stores its receipt's bytes in the bucket under a key minted from the day, the
  item and the amount;
* the Expenses step lists the same receipt per line;
* deleting the line deletes its receipt from the bucket; deleting the report deletes every
  receipt (F2, asserted in test_char_report_lifecycle).

Driven through the Jinja Expenses page and its routes (``/report/expense/*``, ``/download``,
``/preview``) until Flask's HTML frontend was deleted (2026-10-20); now through the Expenses
service and the Petty Cash API (a receipt's bytes by id: tests/test_petty_cash_api_expenses.py).

Finding F6 (2026-09-17, writing these): the draft / update / delete endpoints crashed on
``expense.report_draft`` (the relationship is ``report``). Fixed in C4, with the receipts
becoming ``attachment`` rows, and deleting a line deletes its receipt from the store (F2).

The S3 client is the FakeS3 at ``get_s3_client`` (tests/char_factories.py).
"""

from __future__ import annotations

from datetime import date

import pytest

import char_factories as F
import pg_harness
from test_char_report_lifecycle import add_expense, open_report, post_sales

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=())
    return owner, entity


DAY = date(2026, 9, 1)


@pytest.fixture
def day(shop, client, s3):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, DAY, opening="1000.00")
    post_sales(client, entity, DAY, cash="100")
    return owner, entity


def _api(client, owner, entity):
    return f"/api/petty-cash/v1/companies/{entity.id}", F.petty_cash_headers(client.application, owner.id)


def expense_step_receipts(client, owner, entity) -> dict[str, list]:
    """expense id -> its receipts' names, as the Expenses step lists them per line."""
    base, headers = _api(client, owner, entity)
    resp = client.get(f"{base}/reports/expenses", query_string={"transaction_date": F.iso(DAY)}, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return {line["id"]: [r["name"] for r in line["receipts"]] for line in resp.get_json()["lines"]}


def test_an_added_expense_carries_its_receipt_and_the_bytes_are_stored(day, client, s3):
    owner, entity = day
    body = add_expense(client, entity, DAY, "Tape", "12.50")

    files = body["expense"]["files"]
    assert len(files) == 1
    key = files[0]["s3_key"]
    # the stored name is minted from the day, the item and the amount: 01_SEP_2026_TAPE_12.jpg
    assert "TAPE" in key.upper() and key.endswith(".jpg")
    assert key in s3.objects, (key, list(s3.objects))
    assert s3.objects[key] == b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_the_expense_step_lists_the_receipt(day, client, s3):
    owner, entity = day
    expense_id = add_expense(client, entity, DAY, "Milk", "7.25")["expense"]["id"]

    listed = expense_step_receipts(client, owner, entity)

    assert listed == {expense_id: ["Milk.jpg"]}


def test_patching_a_draft_line_moves_its_amount_exactly(app, day, client, s3):
    """The Expenses step's edit of one line, only the fields sent. The amount lands as exact
    money in the database (``Money()`` reads it back as a float by the C4 decision, so the
    exactness check is on the stored text)."""
    from models.db import db

    owner, entity = day
    expense_id = add_expense(client, entity, DAY, "Stamps", "3.10")["expense"]["id"]
    base, headers = _api(client, owner, entity)

    resp = client.patch(f"{base}/expense-lines/{expense_id}", data={"amount": "1,234.56", "remarks": ""},
                        content_type="multipart/form-data", headers=headers)

    assert resp.status_code == 200, resp.get_json()
    with app.app_context():
        stored = db.session.execute(
            db.text(f"SELECT CAST(amount AS TEXT) FROM {pg_harness.APP_SCHEMA}.report_expense WHERE id = :id"),
            {"id": expense_id},
        ).scalar()
        assert stored == "1234.56", stored  # numeric(14,2): exactly, no float residue
    # a line that is not there is a 404, not a 500
    assert client.patch(f"{base}/expense-lines/{F.new_id()}", data={"remarks": "x"},
                        content_type="multipart/form-data", headers=headers).status_code == 404


def test_a_receipt_is_stored_under_a_normalised_name(day, client, s3):
    """The stored key is minted from the expense item and is ``[A-Z0-9_]`` only: no comma
    ("Meal, Transport etc" used to split the receipt in two on the way back), no ``&``."""
    import re

    owner, entity = day
    body = add_expense(client, entity, DAY, "Staff Welfare - Meal, Transport & etc", "547.00")
    (file,) = body["expense"]["files"]
    key = file["s3_key"]
    assert re.fullmatch(r"expenses/[0-9a-f-]{36}/01_SEP_2026_STAFF_WELFARE_MEAL_TRANSPORT_AND_ETC_547\.jpg", key), key
    assert key in s3.objects
    # the step lists ONE receipt for the line
    assert len(expense_step_receipts(client, owner, entity)[body["expense"]["id"]]) == 1


def test_deleting_the_line_deletes_its_receipt(day, client, s3):
    owner, entity = day
    keep = add_expense(client, entity, DAY, "Keep", "1.00")["expense"]
    gone = add_expense(client, entity, DAY, "Gone", "2.00")["expense"]
    gone_key = gone["files"][0]["s3_key"]
    assert gone_key in s3.objects
    base, headers = _api(client, owner, entity)

    resp = client.delete(f"{base}/expense-lines/{gone['id']}", headers=headers)

    assert resp.status_code == 200, resp.get_json()
    assert gone_key not in s3.objects, "the receipt outlived its expense"
    assert keep["files"][0]["s3_key"] in s3.objects
    assert set(expense_step_receipts(client, owner, entity)) == {keep["id"]}


def test_a_line_may_carry_two_receipts(app, day, client, s3):
    from io import BytesIO

    from werkzeug.datastructures import FileStorage

    from blueprints.report.services.expenses import add_expense as add
    from blueprints.report.services.opening import find_draft
    from models.db import User, db

    owner, entity = day
    with app.app_context():
        files = [FileStorage(BytesIO(b"\xff\xd8\xff" + name.encode()), filename=name, content_type="image/jpeg")
                 for name in ("bill.jpg", "card-slip.jpg")]
        line = add(find_draft(entity.id, DAY), db.session.get(User, owner.id), item="Dinner", amount=300.0, remarks="",
                   contact_id=None, contact_name=None, account_id=None, account_code=None, files=files)
        keys = line.receipt_keys

    assert len(keys) == 2 and len(set(keys)) == 2, keys
    assert all(k in s3.objects for k in keys)
    assert sorted(expense_step_receipts(client, owner, entity)[str(line.id)]) == ["bill.jpg", "card-slip.jpg"]
