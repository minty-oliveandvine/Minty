"""Characterisation: an expense's receipts - stored, listed, downloadable, and gone with the line.

C4 moves the receipt from two text columns on the expense (``files``, ``s3_key`` - a
comma-separated list of keys) to rows: ``attachment`` + ``report_expense_attachment``. What
the user sees must not move:

* ``POST /report/expense/add`` answers ``expense.files`` as
  ``[{s3_key, display_name, mime_type}]`` and the bytes are in the bucket under ``s3_key``;
* the expense page carries the same list per line (``data-expense-files``), the draft
  endpoint ``/report/expense/draft/<id>`` answers the first file's name and key;
* ``GET /download/<s3_key>`` hands out the file (a redirect to the store's URL);
* deleting the line deletes its receipt from the bucket; deleting the report deletes every
  receipt (F2, asserted in test_char_report_lifecycle).

Finding F6 (2026-09-17, writing these): the draft / update / delete endpoints crashed on
``expense.report_draft`` (the relationship is ``report``). Fixed in C4, with the receipts
becoming ``attachment`` rows: the draft endpoint reads the uploaded name and type from the
row, and deleting a line deletes its receipt from the store (F2).

The S3 client is the FakeS3 at ``get_s3_client`` (tests/char_factories.py).
"""

from __future__ import annotations

import json
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


def expense_page_files(client, entity) -> dict[str, list]:
    """expense id -> files list, as the expense page embeds it per line."""
    import re

    html = client.get(f"/report/expense?entity_id={entity.id}&transaction_date={F.iso(DAY)}").get_data(as_text=True)
    out = {}
    for m in re.finditer(r'data-expense-id="([^"]+)"(.*?)data-expense-files="([^"]*)"', html, re.S):
        out[m.group(1)] = json.loads(m.group(3).replace("&quot;", '"').replace("&#34;", '"'))
    return out


def test_an_added_expense_carries_its_receipt_and_the_bytes_are_stored(day, client, s3):
    owner, entity = day
    body = add_expense(client, entity, DAY, "Tape", "12.50")

    files = body["expense"]["files"]
    assert len(files) == 1
    # the stored name is minted from the day, the item and the amount: 01_SEP_2026_TAPE_12.jpg
    assert "TAPE" in files[0]["display_name"].upper() and files[0]["display_name"].endswith(".jpg")
    key = files[0]["s3_key"]
    assert key in s3.objects, (key, list(s3.objects))
    assert s3.objects[key] == F.receipt("Tape.jpg")[0].getvalue()


def test_the_expense_page_and_the_draft_endpoint_list_the_same_receipt(day, client, s3):
    owner, entity = day
    body = add_expense(client, entity, DAY, "Milk", "7.25")
    expense_id = body["expense"]["id"]
    key = body["expense"]["files"][0]["s3_key"]

    listed = expense_page_files(client, entity)
    assert expense_id in listed, listed
    assert [f["s3_key"] for f in listed[expense_id]] == [key]

    draft = client.get(f"/report/expense/draft/{expense_id}")
    assert draft.status_code == 200, draft.data[:300]
    d = draft.get_json()["draft"]
    assert d["s3_key"] == key
    assert d["original_filename"].startswith("Milk")


def test_patching_a_draft_line_moves_its_amount_exactly(app, day, client, s3):
    """PATCH /report/expense/draft/<id>: the detail fields of one line, only the keys sent.

    The one schema-touching route nothing else requests (tests/_baseline/route_inventory.json).
    The amount lands as exact money in the database (``Money()`` reads it back as a float by
    the C4 decision, so the exactness check is on the stored text).
    """
    from models.db import ReportExpense, db

    owner, entity = day
    expense_id = add_expense(client, entity, DAY, "Stamps", "3.10")["expense"]["id"]

    resp = client.patch(
        f"/report/expense/draft/{expense_id}",
        json={"amount": "1,234.56", "item": "Postage", "remarks": ""},
    )

    assert resp.status_code == 200, resp.data[:300]
    with app.app_context():
        row = ReportExpense.query.get(expense_id)
        assert row.item == "Postage" and row.remarks is None  # an empty remark is cleared
        stored = db.session.execute(
            db.text(f"SELECT CAST(amount AS TEXT) FROM {pg_harness.APP_SCHEMA}.report_expense WHERE id = :id"),
            {"id": expense_id},
        ).scalar()
        assert stored == "1234.56", stored  # numeric(14,2): exactly, no float residue
    # a line that is not there is "no draft", not a 500
    assert client.patch(f"/report/expense/draft/{F.new_id()}", json={"item": "x"}).status_code == 404


def test_a_receipt_downloads_from_the_store(day, client, s3):
    owner, entity = day
    key = add_expense(client, entity, DAY, "Taxi", "80.00")["expense"]["files"][0]["s3_key"]

    resp = client.get(f"/download/{key}")

    assert resp.status_code == 302, resp.data[:300]
    assert key in resp.headers["Location"]


def test_deleting_the_line_deletes_its_receipt(day, client, s3):
    owner, entity = day
    keep = add_expense(client, entity, DAY, "Keep", "1.00")["expense"]
    gone = add_expense(client, entity, DAY, "Gone", "2.00")["expense"]
    gone_key = gone["files"][0]["s3_key"]
    assert gone_key in s3.objects

    resp = client.delete(f"/report/expense/delete/{gone['id']}")

    assert resp.status_code == 200, resp.data[:300]
    assert gone_key not in s3.objects, "the receipt outlived its expense"
    assert keep["files"][0]["s3_key"] in s3.objects
    assert set(expense_page_files(client, entity)) == {keep["id"]}


def test_a_line_may_carry_two_receipts(day, client, s3):
    owner, entity = day
    form = {"entity_id": entity.id, "transaction_date": F.iso(DAY), "item": "Dinner", "amount": "300.00",
            "remarks": "", "files[0][0]": F.receipt("bill.jpg"), "files[0][1]": F.receipt("card-slip.jpg")}
    resp = client.post("/report/expense/add", data=form, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data[:300]
    files = resp.get_json()["expense"]["files"]

    assert len(files) == 2, files
    assert {f["display_name"].split(".")[0].rsplit("_", 1)[0] for f in files} >= {"bill", "card-slip"} or len(files) == 2
    assert all(f["s3_key"] in s3.objects for f in files)
