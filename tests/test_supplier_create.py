"""Adding a supplier: the Petty Cash API's ``POST /suppliers``, through
``blueprints/entity/services/suppliers.py`` (Flask's ``POST /entity/contact/create`` went with its
HTML on 2026-10-20). Xero is stubbed at its HTTP call.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import char_factories as F
import pytest
import requests

pytestmark = pytest.mark.char

ORG = "org-0001"


def _hk_today():
    from models.db import tz

    return datetime.now(tz).date()


D3 = _hk_today() - timedelta(days=1)
WEB = "http://localhost:3010"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def shop(app, db):
    from models.db import Entity

    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country, status="connected")
        db.session.get(Entity, entity.id).xero_org_id = ORG
        db.session.commit()
    return owner, entity


class FakeXero:
    """Answers ``requests.post`` for the Contacts endpoint; records what it was sent."""

    def __init__(self, status=200, contacts=None):
        self.status = status
        self.contacts = [{"ContactID": "con-new", "Name": "Corner Bakery"}] if contacts is None else contacts
        self.sent = []

    def __call__(self, url, headers=None, json=None, **kwargs):
        self.sent.append({"url": url, "tenant": (headers or {}).get("Xero-Tenant-Id"), "json": json})
        return SimpleNamespace(status_code=self.status, text="stub", json=lambda: {"Contacts": self.contacts})


@pytest.fixture
def xero(monkeypatch):
    from services.auth import token_service

    fake = FakeXero()
    monkeypatch.setattr(requests, "post", fake)
    token_user = SimpleNamespace(access_token="tok")
    for name, value in (("get_xero_token_user_for_entity", lambda entity_id: token_user),
                        ("ensure_valid_token", lambda user: True),
                        ("auto_refresh_token", lambda user: False)):
        monkeypatch.setattr(token_service, name, value)
        import blueprints.entity.routes.settings as settings_routes

        if hasattr(settings_routes, name):
            monkeypatch.setattr(settings_routes, name, value)
    return fake


def _synced(app, entity):
    from models.db import XeroContactSync

    with app.app_context():
        return {r.xero_contact_id: r.name for r in XeroContactSync.query.filter_by(entity_id=entity.id).all()}


# --- the Petty Cash API ------------------------------------------------------------------------------


def _api(app, client, who, entity, body):
    return client.post(f"/api/petty-cash/v1/companies/{entity.id}/suppliers", json=body,
                       headers=F.petty_cash_headers(app, who.id, origin=WEB))


def test_the_api_adds_a_supplier_the_same_way(app, client, shop, xero):
    owner, entity = shop

    resp = _api(app, client, owner, entity, {"name": "  Corner Bakery "})

    assert resp.status_code == 201 and resp.get_json() == {"id": "con-new", "name": "Corner Bakery"}
    assert xero.sent[0]["json"]["Contacts"][0]["Name"] == "Corner Bakery"
    assert _synced(app, entity) == {"con-new": "Corner Bakery"}


@pytest.mark.parametrize("body, message", [
    ({"name": "  "}, "The supplier's name is still empty. Add the name to continue."),
    ({}, "The supplier's name is still empty. Add the name to continue."),
    ({"name": 7}, "The supplier's name is still empty. Add the name to continue."),
    ({"name": "x" * 151}, "Keep the supplier's name to 150 characters or fewer."),
])
def test_the_api_refuses_a_bad_name_before_calling_xero(app, client, shop, xero, body, message):
    owner, entity = shop

    resp = _api(app, client, owner, entity, body)

    assert resp.status_code == 422 and resp.get_json()["error"] == message
    assert xero.sent == []


def test_the_api_says_why_xero_refused(app, client, shop, xero):
    owner, entity = shop
    xero.status = 500

    resp = _api(app, client, owner, entity, {"name": "Corner Bakery"})

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "I couldn't add that contact to Xero. Mind trying again?"


def test_a_new_supplier_is_created_in_xero_and_kept_as_a_synced_contact(app, client, shop, xero):
    """The synced row is the fix (2026-10-14): without it a line saved with the new supplier stored
    no supplier at all."""
    owner, entity = shop

    resp = _api(app, client, owner, entity, {"name": "Corner Bakery"})

    assert resp.status_code == 201
    assert xero.sent == [{"url": "https://api.xero.com/api.xro/2.0/Contacts", "tenant": ORG,
                          "json": {"Contacts": [{"Name": "Corner Bakery", "IsCustomer": True, "IsSupplier": False}]}}]
    assert _synced(app, entity) == {"con-new": "Corner Bakery"}


def test_a_line_can_be_saved_with_the_new_supplier(app, client, db, shop, xero, monkeypatch):
    from models.db import AccountInfo, EntityAccountXero, Report, ShopExpense

    F.install_fake_s3(monkeypatch)
    owner, entity = shop
    with app.app_context():
        acc = AccountInfo(entity_id=entity.id, xero_account_id="acc-0001", xero_code="400", name="Advertising",
                          type="EXPENSE", status="ACTIVE")
        db.session.add(acc)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=acc.id, name="Advertising", type="EXPENSE",
                                         xero_account_id="acc-0001", is_active=True))
        draft = Report(entity_id=entity.id, transaction_date=D3,
                       status="draft", created_by=owner.id, opening_balance=0)
        db.session.add(draft)
        db.session.commit()
        day, draft_id = draft.transaction_date, str(draft.id)
    contact = _api(app, client, owner, entity, {"name": "Corner Bakery"}).get_json()["id"]

    resp = client.post(
        f"/api/petty-cash/v1/companies/{entity.id}/reports/expenses/lines",
        data={"transaction_date": F.iso(day), "amount": "9", "supplier_id": contact, "account_id": "acc-0001",
              "receipt": (BytesIO(JPEG), "slip.jpg", "image/jpeg")},
        content_type="multipart/form-data", headers=F.petty_cash_headers(app, owner.id, origin=WEB))

    assert resp.status_code == 201, resp.get_json()
    with app.app_context():
        [line] = ShopExpense.query.filter_by(report_id=draft_id).all()
        assert line.contact_name == "Corner Bakery"


def test_xero_refusing_is_said_and_nothing_is_kept(app, client, shop, xero):
    owner, entity = shop
    xero.status = 400

    resp = _api(app, client, owner, entity, {"name": "Corner Bakery"})

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "I couldn't add that contact to Xero. Mind trying again?"
    assert _synced(app, entity) == {}


def test_a_company_without_xero_cannot_add_one(app, client, db, shop, xero):
    from models.db import Entity

    owner, entity = shop
    with app.app_context():
        db.session.get(Entity, entity.id).xero_org_id = None
        db.session.commit()

    resp = _api(app, client, owner, entity, {"name": "Corner Bakery"})

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "This entity isn't connected to Xero yet. Could you ask an admin to connect it?"
    assert xero.sent == []
