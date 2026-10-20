"""The report wizard's Expenses step (``report/services/expenses.py``), pinned through the Jinja page
and its line routes (``/report/expense/add``, ``/report/expense/delete/<id>``,
``/report/expense/update/<id>``) before the logic moved into that service (minty-petty-cash-web's
port, 2026-10-14). Flask's HTML frontend was deleted 2026-10-20: the step's page, lines, receipts
and save are tests/test_petty_cash_api_expenses.py's now; what is left here is what that file does
not pin (the history a line writes, two lines alike, the update racing a submit), driven through the
Petty Cash API. The fixtures and ``_draft`` / ``_lines`` are shared with the report tests that
import them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from io import BytesIO

import char_factories as F
import pytest

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
         remarks="Flyers"):
    """Add a line with one JPEG receipt through the Petty Cash API (the item is the account's name)."""
    form = {"transaction_date": F.iso(day), "amount": amount, "remarks": remarks, "supplier_id": contact,
            "account_id": account, "receipt": (BytesIO(b"\xff\xd8\xff\xe0fake-jpeg-bytes"), "receipt0.jpg", "image/jpeg")}
    return client.post(f"/api/petty-cash/v1/companies/{entity.id}/reports/expenses/lines", data=form,
                       content_type="multipart/form-data",
                       headers=F.petty_cash_headers(client.application, owner.id))


# --- adding a line -----------------------------------------------------------------------------------


def test_adding_a_line_writes_it_to_the_report_s_history(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    assert _add(client, owner, entity, amount="1,012.50").status_code == 201

    with app.app_context():
        assert [h.new_value for h in ReportHistory.query.filter_by(report_id=draft).all()] == [
            "Added expense: Advertising ($1012.5)"]


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


# --- updating a line ---------------------------------------------------------------------------------


def test_an_update_racing_a_submit_rechecks_the_locked_report(app, client, db, shop):
    # Security review 2026-10-19: the draft check read the Report loaded at the start of the
    # request, so a submit landing in between let the amount change on a submitted report.
    # update_expense now re-reads the report under a row lock before it writes.
    from sqlalchemy import text

    from blueprints.report.services.expenses import ExpenseRefused, update_expense
    from models.db import Report, ReportExpense, User

    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    line_id = _add(client, owner, entity, amount="10").get_json()["line"]["id"]
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
