"""``account_info.status`` means "still active in Xero"; Petty Cash's code ticks live on
``entity_account_xero.is_active`` only (2026-10-01).

Until then the tick save also wrote ``status``: every account outside BANK/EQUITY/OTHERINCOME/
SALES/REVENUE went INACTIVE and only the ticked codes came back. The mapping dropdowns list only
ACTIVE accounts, so a liability account (the Director choice) and an unticked code (a Discrepancy
choice) vanished. With Xero connected a background re-sync hid it; disconnected, the saved
Discrepancy account had no option, the page could not select it, and the save was refused with
"Please select: Discrepancy account code".

Pins: a tick save leaves ``status`` alone; the Xero refresh writes no ticks; onboarding step 5
ticks from its posted codes; a saved mapping choice is always among its field's options.
"""

from __future__ import annotations

import re

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
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def add_account(app, db, entity_id, xero_id, kind, code, name, *, status="ACTIVE", ticked=None):
    """An ``account_info`` row; with ``ticked`` also its ``entity_account_xero`` tick."""
    from models.db import AccountInfo, EntityAccountXero

    with app.app_context():
        account = AccountInfo(entity_id=entity_id, type=kind, name=name, xero_code=code,
                              xero_account_id=xero_id, status=status)
        db.session.add(account)
        db.session.flush()
        if ticked is not None:
            db.session.add(EntityAccountXero(account_id=account.id, name=name, type=kind,
                                             xero_account_id=xero_id, is_active=ticked))
        db.session.commit()
        return account.id


def statuses(app, entity_id) -> dict:
    from models.db import AccountInfo

    with app.app_context():
        return {a.xero_code: a.status for a in AccountInfo.query.filter_by(entity_id=entity_id)}


def ticks(app, entity_id) -> dict:
    from models.db import AccountInfo, EntityAccountXero, db

    with app.app_context():
        rows = (
            db.session.query(AccountInfo.xero_code, EntityAccountXero.is_active)
            .join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .all()
        )
    return {code: active for code, active in rows}


def test_a_tick_save_leaves_account_status_alone(shop, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising", ticked=True)
    add_account(app, db, entity.id, "acc-fees", "EXPENSE", "404", "Bank Fees", ticked=True)
    add_account(app, db, entity.id, "acc-loan", "CURRLIAB", "800", "Director Loan")
    F.login(client, owner)

    resp = client.post(f"/entity/settings/entity/{entity.id}", data={"account_codes[]": ["404"]})

    assert resp.status_code == 302
    assert ticks(app, entity.id) == {"400": False, "404": True}
    assert statuses(app, entity.id) == {"400": "ACTIVE", "404": "ACTIVE", "800": "ACTIVE"}


def test_the_xero_refresh_writes_no_ticks(shop, app, db, monkeypatch):
    from blueprints.entity.services.settings import sync_expense_account_info_from_xero
    from blueprints.xero.services import integration

    owner, entity = shop
    add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising", ticked=False)
    add_account(app, db, entity.id, "acc-loan", "CURRLIAB", "800", "Director Loan", status="INACTIVE")
    monkeypatch.setattr(integration, "get_accounts_from_xero", lambda *a, **k: [
        {"AccountID": "acc-ads", "Type": "EXPENSE", "Code": "400", "Name": "Advertising", "Status": "ACTIVE"},
        {"AccountID": "acc-loan", "Type": "CURRLIAB", "Code": "800", "Name": "Director Loan", "Status": "ACTIVE"},
        {"AccountID": "acc-new", "Type": "OVERHEADS", "Code": "469", "Name": "Rent", "Status": "ACTIVE"},
    ])

    with app.app_context():
        sync_expense_account_info_from_xero(entity.id, "tok", "org-1111")
        db.session.commit()

    assert statuses(app, entity.id) == {"400": "ACTIVE", "800": "ACTIVE", "469": "ACTIVE"}
    assert ticks(app, entity.id) == {"400": False}


def test_onboarding_ticks_come_from_the_posted_codes(shop, app, db):
    from blueprints.entity.services.settings import sync_entity_account_xero_active

    owner, entity = shop
    add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising")
    add_account(app, db, entity.id, "acc-fees", "EXPENSE", "404", "Bank Fees", ticked=True)
    add_account(app, db, entity.id, "acc-loan", "CURRLIAB", "800", "Director Loan")

    with app.app_context():
        sync_entity_account_xero_active(entity.id, "org-1111", [" 400 ", ""])

    assert ticks(app, entity.id) == {"400": True, "404": False}
    assert statuses(app, entity.id) == {"400": "ACTIVE", "404": "ACTIVE", "800": "ACTIVE"}


def test_a_saved_choice_is_always_among_its_options(shop, app, db, client):
    # Rows left INACTIVE by the old tick save (healed only by a connected re-sync)
    from models.db import EntityPettycashSettings

    owner, entity = shop
    disc = add_account(app, db, entity.id, "acc-ads", "EXPENSE", "400", "Advertising",
                       status="INACTIVE", ticked=False)
    loan = add_account(app, db, entity.id, "acc-loan", "CURRLIAB", "800", "Director Loan",
                       status="INACTIVE")
    add_account(app, db, entity.id, "acc-cogs", "DIRECTCOSTS", "310", "Cost of Goods Sold", ticked=True)
    with app.app_context():
        db.session.add(EntityPettycashSettings(entity_id=entity.id, discrepancy_account_id=disc,
                                               director_account_id=loan))
        db.session.commit()
    F.login(client, owner)

    html = client.get(f"/entity/settings/entity/{entity.id}").get_data(as_text=True)

    discrepancy = re.search(r'<select name="discrepancy_account".*?</select>', html, re.S).group(0)
    assert '<option value="400">Advertising - 400</option>' in discrepancy
    assert '<option value="310">Cost of Goods Sold - 310</option>' in discrepancy
    director = re.search(r'<select name="owners_account".*?</select>', html, re.S).group(0)
    assert re.search(r'<option value="[^"]*">Director Loan - 800</option>', director)
