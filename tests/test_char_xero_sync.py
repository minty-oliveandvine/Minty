"""Characterisation: the Xero sync tables (C5) - ``account_info`` / ``entity_account_xero``,
``xero_contact_sync``, ``xero_report_sync`` - through the services that write them and the
pages that read them. Xero is stubbed at the integration functions, which is where the
transport already ends (``get_accounts_from_xero`` / ``get_contacts_from_xero``).

Pins: a chart-of-accounts sync records each active Xero account once and drops the ones Xero
no longer lists; a contact sync inserts and updates but never removes; an expense line links
to the synced account and contact and the page shows their code and name; a publish leaves
ONE ``xero_report_sync`` row per report that the republish flow reads back; that row goes
with the report when the report is deleted (schema: ``fk_xrs_report ... ON DELETE CASCADE``).

Written 2026-09-17 on the pre-C5 models with two strict xfails, both closed by C5:
``_upsert_account_info`` was a Postgres-only INSERT ... ON CONFLICT naming the constraint the
old schema had (now the schema's ``uq_account_entity_xero``, with a get-or-update elsewhere),
and the sync row survived a report deletion (r9a09's SET NULL; the schema cascades).
"""

from __future__ import annotations

import uuid

import pytest

import char_factories as F
from test_char_report_lifecycle import REPORT_DATE, add_expense, open_report, post_report

pytestmark = pytest.mark.char

ORG = "org-aaaa-1111"


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
    """An admin and a company connected to Xero org ORG."""
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country, status="connected")
        from models.db import Entity

        Entity.query.filter_by(id=entity.id).update({"xero_org_id": ORG})
        db.session.commit()
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=())
    return owner, entity


XERO_ACCOUNTS = [
    {"AccountID": "acc-0001", "Code": "400", "Name": "Advertising", "Type": "EXPENSE", "Class": "EXPENSE", "Status": "ACTIVE"},
    {"AccountID": "acc-0002", "Code": "090", "Name": "Business Bank", "Type": "BANK", "Class": "ASSET",
     "Status": "ACTIVE", "BankAccountNumber": "123-456", "BankAccountType": "BANK"},
]
XERO_CONTACTS = [
    {"ContactID": "con-0001", "Name": "ABC Supplies"},
    {"ContactID": "con-0002", "Name": "Taxi Co"},
]


def stub_xero(monkeypatch, *, accounts=None, contacts=None):
    from blueprints.xero.services import integration

    monkeypatch.setattr(integration, "get_accounts_from_xero", lambda *a, **k: list(accounts or []))
    monkeypatch.setattr(integration, "get_contacts_from_xero", lambda *a, **k: list(contacts or []))


def synced_accounts(app, entity_id) -> dict[str, str]:
    """xero account id -> code, as account_info holds them for the company."""
    from models.db import AccountInfo

    with app.app_context():
        return {r.xero_account_id: r.xero_code for r in AccountInfo.query.filter_by(entity_id=entity_id).all()}


def synced_contacts(app, entity_id) -> dict[str, str]:
    from models.db import XeroContactSync

    with app.app_context():
        return {r.xero_contact_id: r.name for r in XeroContactSync.query.filter_by(entity_id=entity_id).all()}


# ---- chart of accounts -------------------------------------------------------------------


def test_a_chart_of_accounts_sync_records_each_active_xero_account_once(shop, app, monkeypatch):
    owner, entity = shop
    stub_xero(monkeypatch, accounts=XERO_ACCOUNTS)
    from blueprints.entity.services.settings import sync_xero_accounts_to_db

    with app.app_context():
        sync_xero_accounts_to_db(entity.id, "tok", ORG)
        sync_xero_accounts_to_db(entity.id, "tok", ORG)  # a second sync changes nothing
    assert synced_accounts(app, entity.id) == {"acc-0001": "400", "acc-0002": "090"}

    # Xero archived the bank account: it leaves account_info
    stub_xero(monkeypatch, accounts=XERO_ACCOUNTS[:1])
    with app.app_context():
        sync_xero_accounts_to_db(entity.id, "tok", ORG)
    assert synced_accounts(app, entity.id) == {"acc-0001": "400"}


# ---- contacts -----------------------------------------------------------------------------


def test_a_contact_sync_inserts_and_updates_but_never_removes(shop, app, monkeypatch):
    owner, entity = shop
    stub_xero(monkeypatch, contacts=XERO_CONTACTS)
    from blueprints.entity.services.settings import sync_contacts_if_changed
    from services.helpers.xero_bridge import resolve_contact_name

    with app.app_context():
        first = sync_contacts_if_changed(entity.id, "tok", ORG)
    assert first["inserted"] == 2 and not first["aborted"]
    assert synced_contacts(app, entity.id) == {"con-0001": "ABC Supplies", "con-0002": "Taxi Co"}

    # renamed in Xero, and the taxi firm vanished from the response: rename lands, nothing goes
    stub_xero(monkeypatch, contacts=[{"ContactID": "con-0001", "Name": "ABC Supplies Ltd"}])
    with app.app_context():
        second = sync_contacts_if_changed(entity.id, "tok", ORG)
        assert second["updated"] == 1 and second["inserted"] == 0
        assert resolve_contact_name(entity.id, "con-0002") == "Taxi Co"
    assert synced_contacts(app, entity.id) == {"con-0001": "ABC Supplies Ltd", "con-0002": "Taxi Co"}


# ---- an expense line and its synced account / contact --------------------------------------


def test_an_expense_line_shows_the_synced_account_code_and_contact_name(shop, client, app, monkeypatch):
    owner, entity = shop
    stub_xero(monkeypatch, accounts=XERO_ACCOUNTS, contacts=XERO_CONTACTS)
    from blueprints.entity.services.settings import sync_contacts_if_changed

    with app.app_context():
        # the account rows the way settings writes them (the upsert is Postgres-only until C5)
        from models.db import AccountInfo, db

        for acc in XERO_ACCOUNTS:
            db.session.add(AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id=acc["AccountID"],
                                       xero_code=acc["Code"], name=acc["Name"], type=acc["Type"], status="ACTIVE"))
        db.session.commit()
        sync_contacts_if_changed(entity.id, "tok", ORG)

    F.login(client, owner)
    open_report(client, entity, REPORT_DATE, opening="100.00")
    form = {"entity_id": entity.id, "transaction_date": F.iso(REPORT_DATE), "item": "Flyers", "amount": "12.50",
            "remarks": "", "accountId": "acc-0001", "contactId": "con-0001", "files[0][0]": F.receipt("Flyers.jpg")}
    resp = client.post("/report/expense/add", data=form, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["expense"]["account_code"] == "400"
    assert body["expense"]["contact_name"] == "ABC Supplies"

    page = client.get(f"/report/expense?entity_id={entity.id}&transaction_date={F.iso(REPORT_DATE)}")
    html = page.get_data(as_text=True)
    assert 'data-expense-account-code="400"' in html
    assert 'data-expense-account-id="acc-0001"' in html
    assert 'data-expense-contact-name="ABC Supplies"' in html


# ---- the publish record --------------------------------------------------------------------


def test_a_publish_leaves_one_sync_row_per_report_that_the_republish_reads_back(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    from blueprints.xero.services import publish_record
    from models.db import XeroReportSync

    with app.app_context():
        publish_record.record_object(report_id, ORG, "deposit", "bt-0001", object_type="BANK_TRANSFER", amount=500.0)
        publish_record.record_object(report_id, ORG, "cash_sale", "tx-0001", object_type="BANK_TRANSACTION", amount=300.0)

        rows = XeroReportSync.query.filter_by(report_id=report_id).all()
        assert len(rows) == 1
        assert rows[0].completed_at is not None and rows[0].reported_at is not None
        record = publish_record.load_record(report_id, ORG)
        assert publish_record.recorded_id(record, "deposit") == "bt-0001"
        assert publish_record.recorded_id(record, "cash_sale") == "tx-0001"
        # an org switch makes the record worthless: nothing known was published THERE
        assert publish_record.recorded_id(publish_record.load_record(report_id, "org-other"), "deposit") is None


def test_deleting_the_report_deletes_its_sync_row(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    from blueprints.xero.services import publish_record
    from models.db import XeroReportSync

    with app.app_context():
        publish_record.record_object(report_id, ORG, "deposit", "bt-0001", object_type="BANK_TRANSFER", amount=500.0)

    resp = client.post(f"/report/delete/{report_id}")
    assert resp.status_code == 302, resp.data[:300]
    with app.app_context():
        assert XeroReportSync.query.filter_by(report_id=report_id).count() == 0
        assert XeroReportSync.query.count() == 0, "no orphaned sync row either"
