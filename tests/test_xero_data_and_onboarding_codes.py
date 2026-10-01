"""Two things fixed on 2026-10-01 beside Petty Cash Settings.

* ``GET /api/entity/<id>/xero-data`` (the lists Petty Cash Settings' Xero mapping fields offer):
  its database fallback - used when the company's Xero token no longer works - filtered
  ``xero_contact_sync`` on an ``is_active`` column the table does not have, so it always
  answered 500. And a bank account's label carried the FULL account number: the Xero fetch
  copied it into ``MaskedBankAccountNumber`` unmasked, and the raw ``BankAccountNumber`` was
  sent to the page too. Now the label is ``****`` + the last four, and the full number never
  leaves the server.
* onboarding step 5 (``save_account_codes``) refuses a save with no account code ticked, as
  Petty Cash Settings does; a company with no codes at all is not blocked.
* onboarding step 8 (``save_bill_codes``, the Payment Settings codes) does the same, as
  billing-backend's Payment Settings does (its 409).
"""

from __future__ import annotations

import pytest

import char_factories as F

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
def shop(app, db):
    """An admin and a company that was connected to a Xero organisation, its token gone."""
    from models.db import Entity

    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        Entity.query.filter_by(id=entity.id).update({"xero_org_id": "org-1111"})
        db.session.commit()
    return owner, entity


def add_account(app, db, entity_id, xero_id, kind, code, name, *, bank_number=None):
    from models.db import AccountInfo

    with app.app_context():
        db.session.add(AccountInfo(entity_id=entity_id, type=kind, name=name, xero_code=code,
                                   xero_account_id=xero_id, status="ACTIVE",
                                   bank_account_number=bank_number))
        db.session.commit()


# ---- /xero-data ---------------------------------------------------------------------------------


def test_the_database_fallback_answers_with_masked_bank_numbers(shop, app, db, client):
    from models.db import XeroContactSync

    owner, entity = shop
    add_account(app, db, entity.id, "acc-bank", "BANK", "", "Business Bank", bank_number="12-3456-7890123")
    add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising")
    with app.app_context():
        db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id="con-1", name="Taxi Co"))
        db.session.commit()
    F.login(client, owner)

    resp = client.get(f"/api/entity/{entity.id}/xero-data")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert [(b["Name"], b["MaskedBankAccountNumber"]) for b in body["bank_accounts"]] == [
        ("Business Bank", "****0123")
    ]
    assert "BankAccountNumber" not in body["bank_accounts"][0]
    assert "12-3456-7890123" not in resp.get_data(as_text=True)
    assert [c["Name"] for c in body["contacts"]] == ["Taxi Co"]
    assert [a["Code"] for a in body["discrepancy_account"]] == ["400"]


def test_the_xero_fetch_masks_a_bank_account_number(app, monkeypatch):
    from blueprints.xero.services import integration

    class Reply:
        def json(self):
            return {"Accounts": [
                {"AccountID": "acc-bank", "Type": "BANK", "Name": "Business Bank",
                 "BankAccountNumber": "12-3456-7890123"},
                {"AccountID": "acc-ads", "Type": "EXPENSE", "Name": "Advertising", "Code": "400"},
            ]}

    monkeypatch.setattr(integration.requests, "get", lambda *a, **k: Reply())
    with app.app_context():
        accounts = integration.get_accounts_from_xero("tok", "org-1111", token_validated=True)

    assert accounts[0]["MaskedBankAccountNumber"] == "****0123"
    assert "MaskedBankAccountNumber" not in accounts[1]


# ---- onboarding step 5 ----------------------------------------------------------------------------


def test_onboarding_refuses_a_save_with_no_code_ticked(shop, app, db):
    from blueprints.entity.services.onboarding_account_codes import save_account_codes
    from models.db import EntityPettycashSettings

    owner, entity = shop
    add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising")

    with app.app_context():
        data, status = save_account_codes(owner.id, entity.id, expense_codes=[" ", ""],
                                          mapping={"pettycash": "acc-bank"})
        assert (data, status) == ({"error": "Pick at least one account code."}, 400)
        assert EntityPettycashSettings.query.filter_by(entity_id=entity.id).first() is None


def test_onboarding_does_not_block_a_company_with_no_codes(shop, app, db):
    # it gets as far as the Xero token (gone here), so the codes rule let it through
    from blueprints.entity.services.onboarding_account_codes import save_account_codes

    owner, entity = shop
    add_account(app, db, entity.id, "acc-uncoded", "EXPENSE", None, "Uncoded")

    with app.app_context():
        data, status = save_account_codes(owner.id, entity.id, expense_codes=[], mapping={})

    assert status == 409
    assert data["connected"] is False


# ---- onboarding step 8 (Payment Settings codes) ---------------------------------------------------


def bill_ticks(app, db, entity_id):
    from sqlalchemy import text

    from blueprints.shared.schema import SCHEMA

    with app.app_context():
        rows = db.session.execute(
            text(f"SELECT account_code, is_active FROM {SCHEMA}.entity_bill_account_xero "
                 "WHERE entity_id = :eid AND is_deleted = false"),
            {"eid": entity_id},
        ).fetchall()
    return {code: active for code, active in rows}


def seed_bill_codes(app, db, entity_id, owner_id):
    from blueprints.entity.services.settings import sync_xero_coa_bill

    add_account(app, db, entity_id, "acc-ads", "EXPENSE", "400", "Advertising")
    add_account(app, db, entity_id, "acc-rent", "OVERHEADS", "469", "Rent")
    with app.app_context():
        sync_xero_coa_bill(entity_id, owner_id)
        db.session.commit()


def test_onboarding_payment_codes_refuse_a_save_with_none_ticked(shop, app, db):
    from blueprints.entity.services.onboarding_bill_codes import save_bill_codes

    owner, entity = shop
    seed_bill_codes(app, db, entity.id, owner.id)
    before = bill_ticks(app, db, entity.id)

    with app.app_context():
        data, status = save_bill_codes(owner.id, entity.id, [" ", "999"])

    assert (data, status) == ({"error": "Pick at least one account code."}, 400)
    assert bill_ticks(app, db, entity.id) == before == {"400": True, "469": True}


def test_onboarding_payment_codes_save_the_ticked_ones(shop, app, db):
    from blueprints.entity.services.onboarding_bill_codes import save_bill_codes

    owner, entity = shop
    seed_bill_codes(app, db, entity.id, owner.id)

    with app.app_context():
        data, status = save_bill_codes(owner.id, entity.id, ["469"])

    assert status == 200, data
    assert bill_ticks(app, db, entity.id) == {"400": False, "469": True}


def test_onboarding_payment_codes_do_not_block_a_company_with_no_codes(shop, app, db):
    from blueprints.entity.services.onboarding_bill_codes import save_bill_codes

    owner, entity = shop
    with app.app_context():
        data, status = save_bill_codes(owner.id, entity.id, [])

    assert status == 200, data
