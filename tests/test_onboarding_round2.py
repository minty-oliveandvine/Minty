"""Onboarding round 2 (2026-10-13): what the setup checks, the company list and the wizard's
later steps read and write.

* The dashboard's "what's missing" list names all six petty-cash accounts and three contacts -
  it used to skip the discrepancy bank account, so a company missing only that saw "Setup
  Required" with nothing listed.
* ``GET /api/me/entities`` takes every listed company's module flags in one query
  (``entity_setup_summary``), not two per company.
* A contact created from step 7 carries the Xero organisation it was made in, so an
  organisation switch clears it like every other cached contact.
* Step 8 can mark one ticked bill account code as the default.
* Step 3 can resend an invitation (``POST /api/onboarding/invite/resend``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest

import char_factories as F

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)
        from blueprints.shared.schema import SCHEMA

        _db.session.execute(_db.text(f"DELETE FROM {SCHEMA}.entity_bill_account_xero"))
        _db.session.commit()


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db, "HKD", denominations=(200, 100, 10, 1))
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country,
                               modules=("PETTY_CASH", "PAYMENT_REQUEST"))
    return SimpleNamespace(owner=owner, entity=entity, currency=currency, country=country)


def bearer(app, user_id):
    payload = {"user_id": str(user_id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
               "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


def _connect(app, db, entity_id, org="org-1"):
    from models.db import Entity

    with app.app_context():
        e = Entity.query.get(entity_id)
        e.xero_org_id = org
        e.status = "connected"
        db.session.commit()


# ---- setup checks ------------------------------------------------------------------------


def test_the_missing_list_names_the_discrepancy_bank_account(app, db, shop):
    from blueprints.xero.services.settings import (check_entity_xero_settings_complete,
                                                   get_missing_xero_settings_fields)
    from models.db import AccountInfo, EntityPettycashSettings, XeroContactSync

    with app.app_context():
        acc = [AccountInfo(entity_id=shop.entity.id, type="BANK", name=f"A{i}") for i in range(5)]
        con = [XeroContactSync(entity_id=shop.entity.id, xero_contact_id=f"c{i}", name=f"C{i}") for i in range(3)]
        db.session.add_all(acc + con)
        db.session.flush()
        db.session.add(EntityPettycashSettings(
            entity_id=shop.entity.id,
            pettycash_account_id=acc[0].id, bank_account_id=acc[1].id, cash_sale_account_id=acc[2].id,
            discrepancy_account_id=acc[3].id, director_account_id=acc[4].id,
            cash_sale_contact_id=con[0].id, director_contact_id=con[1].id, discrepancy_contact_id=con[2].id,
        ))
        db.session.commit()

        assert check_entity_xero_settings_complete(shop.entity.id) is False
        assert get_missing_xero_settings_fields(shop.entity.id) == ["Discrepancy Bank Account"]


# ---- the company list ------------------------------------------------------------------------


def _queries_for_list(app, client, user_id) -> int:
    from sqlalchemy import event

    from models.db import db

    count = {"n": 0}

    def _count(*_a, **_kw):
        count["n"] += 1

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        F.hub_list(client, app, user_id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return count["n"]


def test_the_company_list_does_not_query_per_company(app, client, db, shop, monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")
    one = _queries_for_list(app, client, shop.owner.id)
    with app.app_context():
        for i in range(4):
            F.make_entity(db, shop.owner, name=f"More {i} Ltd", currency=shop.currency, country=shop.country,
                          modules=("PETTY_CASH", "PAYMENT_REQUEST"))
    five = _queries_for_list(app, client, shop.owner.id)

    assert five == one
    listed = F.hub_list(client, app, shop.owner.id)
    assert len(listed) == 5


# ---- step 7: a created contact keeps its organisation ------------------------------------


def test_a_contact_created_in_step_7_carries_its_organisation(app, db, shop, monkeypatch):
    from blueprints.xero.services import publish
    from models.db import XeroContactSync

    _connect(app, db, shop.entity.id, org="org-7")
    monkeypatch.setattr(publish.requests, "post", lambda *_a, **_kw: SimpleNamespace(
        status_code=200, json=lambda: {"Contacts": [{"ContactID": "xc-1", "Name": "Cash Sales"}]},
    ))

    with app.app_context():
        publish.create_xero_contact(shop.entity.id, "Cash Sales", "token", "org-7")
        row = XeroContactSync.query.filter_by(entity_id=shop.entity.id, xero_contact_id="xc-1").one()
        assert row.xero_org_id == "org-7"


# ---- step 8: the default bill account code ----------------------------------------------


def _bill_codes(app, db, entity_id):
    from blueprints.shared.schema import SCHEMA

    with app.app_context():
        for code in ("400", "410", "420"):
            db.session.execute(db.text(f"INSERT INTO {SCHEMA}.entity_bill_account_xero "
                                       "(entity_id, account_code) VALUES (:e, :c)"),
                               {"e": entity_id, "c": code})
        db.session.commit()


def _defaults(app, db, entity_id):
    from blueprints.shared.schema import SCHEMA

    with app.app_context():
        return [r[0] for r in db.session.execute(db.text(
            f"SELECT account_code FROM {SCHEMA}.entity_bill_account_xero "
            "WHERE entity_id = :e AND is_default ORDER BY account_code"), {"e": entity_id})]


def test_step_8_marks_one_default_code(app, client, db, shop):
    _connect(app, db, shop.entity.id)
    _bill_codes(app, db, shop.entity.id)
    headers = bearer(app, shop.owner.id)

    resp = client.post("/api/onboarding/bill-codes", json={
        "entity_id": shop.entity.id, "selected_codes": ["400", "410"], "default_code": "410",
    }, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert _defaults(app, db, shop.entity.id) == ["410"]

    client.post("/api/onboarding/bill-codes", json={
        "entity_id": shop.entity.id, "selected_codes": ["400", "410"], "default_code": "400",
    }, headers=headers)
    assert _defaults(app, db, shop.entity.id) == ["400"]


def test_a_default_code_must_be_one_of_the_ticked_codes(app, client, db, shop):
    _connect(app, db, shop.entity.id)
    _bill_codes(app, db, shop.entity.id)

    resp = client.post("/api/onboarding/bill-codes", json={
        "entity_id": shop.entity.id, "selected_codes": ["400"], "default_code": "420",
    }, headers=bearer(app, shop.owner.id))

    assert resp.status_code == 400
    assert _defaults(app, db, shop.entity.id) == []


# ---- step 3: invitation expiry and resend --------------------------------------------------


def _invite(client, app, shop):
    resp = client.post("/api/onboarding/invite", json={
        "entity_id": shop.entity.id, "email": "new@test.com", "role": "cashier",
        "first_name": "New", "last_name": "Person",
    }, headers=bearer(app, shop.owner.id))
    assert resp.status_code in (200, 201), resp.data[:300]
    listed = client.get(f"/api/onboarding/invite?entity_id={shop.entity.id}",
                        headers=bearer(app, shop.owner.id)).get_json()["invitations"]
    return listed[0]


def test_the_invite_list_says_when_each_invitation_expires(app, client, db, shop, monkeypatch):
    F.install_fake_mail(monkeypatch)
    invitation = _invite(client, app, shop)
    assert invitation["expires_at"] and invitation["expired"] is False


def test_an_invitation_can_be_resent(app, client, db, shop, monkeypatch):
    from blueprints.invitation.services import invite as invite_service

    mail = F.install_fake_mail(monkeypatch)
    invitation = _invite(client, app, shop)
    headers = bearer(app, shop.owner.id)

    soon = client.post("/api/onboarding/invite/resend", json={"invitation_id": invitation["id"]}, headers=headers)
    assert soon.status_code == 429 and soon.get_json()["retry_after"] > 0

    monkeypatch.setattr(invite_service, "resend_cooldown_remaining", lambda *_a: 0)
    sent_before = len(mail.messages)
    resp = client.post("/api/onboarding/invite/resend", json={"invitation_id": invitation["id"]}, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert len(mail.messages) == sent_before + 1


def test_a_stranger_cannot_resend(app, client, db, shop, monkeypatch):
    F.install_fake_mail(monkeypatch)
    invitation = _invite(client, app, shop)
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")

    resp = client.post("/api/onboarding/invite/resend", json={"invitation_id": invitation["id"]},
                       headers=bearer(app, stranger.id))
    assert resp.status_code == 403
