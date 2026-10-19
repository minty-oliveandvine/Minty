"""What the report wizard's Expenses step shows and saves - the page (``report/routes/expense.py``)
and the line routes its script calls (``report/routes/api.py``: ``/report/expense/add`` and
``/report/expense/delete/<id>``) - pinned before the logic moves into a service that the Jinja page
and the Petty Cash API share (minty-petty-cash-web's port of the step, 2026-10-14).

Characterisation: today's behaviour, quirks included. Where a test pins a BUG it says so; the
service extraction fixes those deliberately and changes the test with it.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

import char_factories as F
import pytest
from flask import template_rendered

pytestmark = pytest.mark.char


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


@pytest.fixture
def shop(app, db):
    """A company that is not connected to Xero, with two synced suppliers and two expense
    accounts (one switched off for Petty Cash)."""
    from models.db import AccountInfo, EntityAccountXero, XeroContactSync

    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        for xero_id, name in (("con-0001", "ABC Supplies"), ("con-0002", "Taxi Co")):
            db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id=xero_id, name=name))
        for xero_id, code, name, active in (("acc-0001", "400", "Advertising", True), ("acc-0002", "429", "General", False)):
            row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id=xero_id, xero_code=code,
                              name=name, type="EXPENSE", status="ACTIVE")
            db.session.add(row)
            db.session.flush()
            db.session.add(EntityAccountXero(account_id=row.id, name=name, type="EXPENSE", xero_account_id=xero_id,
                                             is_active=active))
        db.session.commit()
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


def _lines(app, report_id):
    from models.db import ShopExpense

    with app.app_context():
        return [
            {"item": e.item, "amount": e.amount, "remarks": e.remarks, "contact": e.contact_name,
             "account": e.account_code, "keys": e.receipt_keys,
             "names": [a.original_name for a in e.attachments], "mimes": [a.mime_type for a in e.attachments]}
            for e in ShopExpense.query.filter_by(report_id=report_id).order_by(ShopExpense.created_at).all()
        ]


def _add(client, owner, entity, day=D3, *, amount="12.50", contact="con-0001", account="acc-0001",
         item="Advertising", remarks="Flyers", files=1):
    F.login(client, owner)
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "item": item, "amount": amount,
            "remarks": remarks, "accountId": account, "contactId": contact}
    for i in range(files):
        form[f"files[0][{i}]"] = F.receipt(f"receipt{i}.jpg")
    return client.post("/report/expense/add", data=form, content_type="multipart/form-data")


@contextmanager
def _captured(app):
    seen = []

    def record(_sender, template, context, **_extra):
        if template.name == "report/expense.html":
            seen.append({
                "contacts": context["xero_contacts"],
                "accounts": [(a["AccountID"], a["Code"], a["Name"]) for a in context["xero_accounts"]],
                "lines": [(e.item, e.amount) for e in context["existing_expenses"]],
                "draft_id": context["draft_id"],
                "completed": context["completed_sections"],
                "section": context["current_section"],
            })

    template_rendered.connect(record, app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, app)


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _cat, m in sess.get("_flashes", [])]


# --- the page ---------------------------------------------------------------------------------------


def test_the_page_lists_the_synced_suppliers_the_active_accounts_and_the_lines(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    assert _add(client, owner, entity).status_code == 200

    with _captured(app) as seen:
        resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/expense",
                          query_string={"transaction_date": F.iso(D3)})

    assert resp.status_code == 200
    ctx = seen[0]
    assert ctx["contacts"] == {"Contacts": [{"ContactID": "con-0001", "Name": "ABC Supplies"},
                                            {"ContactID": "con-0002", "Name": "Taxi Co"}]}
    assert ctx["accounts"] == [("acc-0001", "400", "Advertising")]  # the switched-off one is not offered
    assert ctx["lines"] == [("Advertising", 12.5)]
    assert str(ctx["draft_id"]) == draft
    assert ctx["completed"] == ["opening", "sales"] and ctx["section"] == "expenses"


def test_with_no_draft_the_page_sends_you_to_opening(app, client, db, shop):
    owner, entity = shop
    F.login(client, owner)
    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/expense",
                      query_string={"transaction_date": F.iso(D3)})

    assert resp.status_code == 302 and "/reports/new/opening" in resp.headers["Location"]
    assert _flashes(client) == ["I don't see a draft for today yet - let's start with the opening entry."]


# --- adding a line -----------------------------------------------------------------------------------


def test_adding_a_line_stores_it_with_its_receipt_and_moves_the_totals(app, client, db, shop, s3):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _draft(app, db, entity, owner, bank_deposit=5)

    resp = _add(client, owner, entity, amount="1,012.50")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success" and body["message"] == "Expense added successfully."
    assert body["expense"]["contact_name"] == "ABC Supplies" and body["expense"]["account_code"] == "400"
    assert body["totals"] == {"total_expenses": 1012.5, "closing_balance": 100 + 20 + 50 - 1012.5 - 5}
    [line] = _lines(app, draft)
    assert (line["item"], line["amount"], line["remarks"], line["contact"], line["account"]) == (
        "Advertising", 1012.5, "Flyers", "ABC Supplies", "400")
    assert line["names"] == ["receipt0.jpg"] and line["mimes"] == ["image/jpeg"]
    assert line["keys"][0] in s3.objects
    assert _row(app, draft)["expenses"] == 1012.5
    with app.app_context():
        assert [h.new_value for h in ReportHistory.query.filter_by(report_id=draft).all()] == [
            "Added expense: Advertising ($1012.5)"]


def test_a_line_needs_a_receipt(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _add(client, owner, entity, files=0)

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "Expense must have at least one valid file attached."
    assert _lines(app, draft) == []


def test_a_line_without_a_draft_is_refused(app, client, db, shop):
    owner, entity = shop
    resp = _add(client, owner, entity)

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "No draft found. Please start with the opening entry first."


def test_the_server_takes_whatever_amount_and_supplier_it_is_sent(app, client, db, shop):
    """BUG (fixed in the extraction): nothing is checked on the server - a negative amount is
    stored, and a supplier that is not synced is dropped silently (the line has no supplier)."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _add(client, owner, entity, amount="-30", contact="con-unknown")

    assert resp.status_code == 200
    [line] = _lines(app, draft)
    assert line["amount"] == -30 and line["contact"] is None


def test_two_lines_alike_keep_their_own_receipts(app, client, db, shop, s3):
    """Fixed 2026-10-14: the stored name is the day, the item and the ROUNDED amount, so a second
    line like the first overwrote its receipt and both lines pointed at one file."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    _add(client, owner, entity, amount="12.40")
    _add(client, owner, entity, amount="12.10")

    first, second = _lines(app, draft)
    assert first["keys"] != second["keys"]
    assert all(key in s3.objects for key in first["keys"] + second["keys"])


# --- deleting a line ---------------------------------------------------------------------------------


def test_deleting_a_line_removes_its_receipt_and_moves_the_totals(app, client, db, shop, s3):
    from models.db import ShopExpense

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    _add(client, owner, entity, amount="10")
    keep = _add(client, owner, entity, amount="15").get_json()["expense"]["id"]
    with app.app_context():
        gone = next(str(e.id) for e in ShopExpense.query.filter_by(report_id=draft).all() if str(e.id) != str(keep))
        gone_key = db.session.get(ShopExpense, gone).receipt_keys[0]

    resp = client.delete(f"/report/expense/delete/{gone}")

    assert resp.status_code == 200 and resp.get_json()["message"] == "Expense deleted successfully."
    assert [line["amount"] for line in _lines(app, draft)] == [15]
    assert gone_key in s3.deleted
    assert _row(app, draft)["expenses"] == 15 and _row(app, draft)["closing"] == 100 + 20 + 50 - 15


def test_a_line_on_a_submitted_report_cannot_be_deleted(app, client, db, shop):
    """Fixed in the service extraction: there was no status check, so a posted report's
    expenses and closing balance could change."""
    from models.db import Report, ShopExpense

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    with app.app_context():
        db.session.get(Report, draft).status = "submitted"
        db.session.commit()

    resp = client.delete(f"/report/expense/delete/{line}")

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "This report isn't a draft anymore, so I can't change its expenses."
    with app.app_context():
        assert ShopExpense.query.filter_by(report_id=draft).count() == 1
    assert _row(app, draft)["expenses"] == 10


# --- the step's own save -----------------------------------------------------------------------------


def _step(client, owner, entity, action):
    F.login(client, owner)
    return client.post("/report/expense", data={"entity_id": entity.id, "transaction_date": F.iso(D3),
                                                "action_type": action})


def test_save_next_marks_expenses_done_and_goes_to_the_deposit_step(app, client, db, shop):
    """The route never commits its progress itself - a later request hook's commit carries it.
    Pinned as the outcome the page relies on; the service commits it explicitly."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _step(client, owner, entity, "save_next")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/petty-cash/reports/new/deposit?transaction_date={F.iso(D3)}")
    row = _row(app, draft)
    assert row["completed"] == ["opening", "sales", "expenses"] and row["section"] == "deposit"


def test_save_exit_comes_back_to_the_page(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner)

    resp = _step(client, owner, entity, "save_exit")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/petty-cash/reports/new/expense?transaction_date={F.iso(D3)}")


def test_with_no_draft_the_step_sends_you_to_opening(app, client, db, shop):
    owner, entity = shop
    resp = _step(client, owner, entity, "save_next")

    assert resp.status_code == 302 and "/reports/new/opening" in resp.headers["Location"]
    assert _flashes(client) == ["I don't see a draft yet - let's start with the opening entry."]


# --- updating a line (``/report/expense/update/<id>``) -------------------------------------------
# Pinned 2026-10-19 before the update moved into ``expenses.update_expense``, which the Petty Cash
# API's ``PATCH /expense-lines/<id>`` shares.


def _update(client, owner, line_id, *, files=0, **form):
    F.login(client, owner)
    data = dict(form)
    for i in range(files):
        data[f"files[0][{i}]"] = F.receipt(f"new{i}.jpg")
    return client.post(f"/report/expense/update/{line_id}", data=data, content_type="multipart/form-data")


def test_updating_a_line_changes_its_fields_keeps_its_receipt_and_moves_the_totals(app, client, db, shop, s3):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _draft(app, db, entity, owner, bank_deposit=5)
    line = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    [before] = _lines(app, draft)

    resp = _update(client, owner, line, amount="1,234.50", remarks="Posters", item="Printing",
                   contactId="con-0002", accountId="acc-0001")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "success", "message": "Expense updated successfully."}
    [after] = _lines(app, draft)
    assert (after["item"], after["amount"], after["remarks"], after["contact"], after["account"]) == (
        "Printing", 1234.5, "Posters", "Taxi Co", "400")
    assert after["keys"] == before["keys"]  # no new file: the receipt is kept
    assert _row(app, draft)["expenses"] == 1234.5
    assert _row(app, draft)["closing"] == 100 + 20 + 50 - 1234.5 - 5
    with app.app_context():
        assert [h.new_value for h in ReportHistory.query.filter_by(report_id=draft).order_by(
            ReportHistory.created_at).all()][-1] == "updated to amount: $1234.5"


def test_updating_a_line_with_a_new_file_replaces_its_receipt(app, client, db, shop, s3):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    [before] = _lines(app, draft)

    resp = _update(client, owner, line, files=1)

    assert resp.status_code == 200
    [after] = _lines(app, draft)
    assert after["names"] == ["new0.jpg"] and after["keys"] != before["keys"]
    assert after["keys"][0] in s3.objects
    assert after["amount"] == 10  # fields not sent stay as they were
    # Fixed in the service extraction: the replaced file was left in the bucket.
    assert before["keys"][0] in s3.deleted


def test_a_line_on_a_submitted_report_cannot_be_updated(app, client, db, shop):
    from models.db import Report

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    with app.app_context():
        db.session.get(Report, draft).status = "submitted"
        db.session.commit()

    resp = _update(client, owner, line, amount="99")

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "This report isn't a draft anymore, so I can't change its expenses."
    assert _lines(app, draft)[0]["amount"] == 10


def test_an_update_racing_a_submit_rechecks_the_locked_report(app, client, db, shop):
    # Security review 2026-10-19: the draft check read the Report loaded at the start of the
    # request, so a submit landing in between let the amount change on a submitted report.
    # update_expense now re-reads the report under a row lock before it writes.
    from sqlalchemy import text

    from blueprints.report.services.expenses import ExpenseRefused, update_expense
    from models.db import Report, ReportExpense, User

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line_id = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    with app.app_context():
        report = db.session.get(Report, draft)
        line = db.session.get(ReportExpense, line_id)
        user = db.session.get(User, owner.id)
        assert report.status == "draft"  # what the request saw
        # A submit from another connection, committed while this request is still working.
        with db.engine.connect() as other:
            other.execute(text(f"UPDATE {Report.__table__.fullname} SET status = 'submitted' WHERE id = :id"),
                          {"id": draft})
            other.commit()

        with pytest.raises(ExpenseRefused):
            update_expense(report, line, user, item=line.item, amount=99, remarks=line.remarks,
                           contact_id=line.contact_id, contact_name=line.contact_name,
                           account_id=line.account_id, account_code=line.account_code)
        db.session.rollback()

    assert _lines(app, draft)[0]["amount"] == 10


def test_updating_needs_the_edit_right_and_a_line_that_exists(app, client, db, shop):
    from models.db import UserEntity

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line = _add(client, owner, entity, amount="10").get_json()["expense"]["id"]
    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()

    assert _update(client, base, line, amount="99").status_code == 403
    assert _update(client, owner, str(uuid.uuid4()), amount="99").status_code == 404
    assert _lines(app, draft)[0]["amount"] == 10
