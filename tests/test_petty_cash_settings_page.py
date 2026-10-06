"""Petty Cash Settings (``/entity/settings/entity/<id>``, ``entity_settings_entity``): the one Flask
settings page that stays, redrawn on 2026-10-01 from the ``?from=bills`` page.

Pins:

* a save that ticks no account code is refused BEFORE anything is written - every code would
  otherwise be switched off (``entity_account_xero.is_active``), and a petty cash expense can
  only use the codes ticked here. Rows without a code do not count either way (the save keys
  on the code), and a company with no codes saves as before;
* the first-ever save keeps the ticks (it used to switch every code on) and still opens the
  dashboard;
* one page whichever way in: its "‹ Back" (static/js/back_link.js) returns to the page the
  person came from, falling back to the company's home; an old link's ``?from=bills`` changes
  nothing (the flag went 2026-10-05);
* the account codes reach the page as data (the page script draws them as text), never as
  markup; a view-only member gets no working Save;
* without a live Xero connection (never connected, disconnected in Minty, or a dead token) the
  Xero-fed cards - the mapping and the account codes - show only a "Xero isn't connected" notice,
  and a save leaves the cached ticks and the mapping alone.
"""

from __future__ import annotations

import json
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
    """An admin and a Petty Cash company that never connected to Xero (no Xero calls)."""
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Vine")
        entity = F.make_entity(db, owner, name="Corner Shop", currency=currency, country=country)
    return owner, entity


def add_account(app, db, entity_id, code, name, *, ticked=True, kind="EXPENSE"):
    """An ``account_info`` row with its ``entity_account_xero`` tick - the page's own list."""
    from models.db import AccountInfo, EntityAccountXero

    with app.app_context():
        account = AccountInfo(entity_id=entity_id, type=kind, name=name, xero_code=code,
                              xero_account_id=F.new_id(), status="ACTIVE")
        db.session.add(account)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=account.id, name=name, type=kind,
                                         xero_account_id=account.xero_account_id, is_active=ticked))
        db.session.commit()


def ticks(app, entity_id) -> dict:
    """code -> ticked, as the expense form will read them."""
    from models.db import AccountInfo, EntityAccountXero, db

    with app.app_context():
        rows = (
            db.session.query(AccountInfo.xero_code, EntityAccountXero.is_active)
            .join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .all()
        )
    return {code: active for code, active in rows}


def company_country(app, entity_id):
    from models.db import Entity

    with app.app_context():
        return Entity.query.get(entity_id).country_code


def mapping_saved(app, entity_id) -> bool:
    from models.db import EntityPettycashSettings

    with app.app_context():
        return EntityPettycashSettings.query.filter_by(entity_id=entity_id).first() is not None


def flashes(client) -> list:
    """(category, message) pairs waiting in the session (it stores them as lists)."""
    with client.session_transaction() as sess:
        return [tuple(flashed) for flashed in sess.get("_flashes", [])]


def page_config(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="pcs-config">(.*?)</script>', html, re.S)
    assert found, "the page config is missing"
    return json.loads(found.group(1))


# ---- the account-code rule ------------------------------------------------------------------


def test_a_save_with_no_code_ticked_is_refused_and_writes_nothing(shop, xero_live, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    add_account(app, db, entity.id, "404", "Bank Fees")
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={
        "country_code": "SG",
        "main_bank": "acc-bank",
        "deposit_bank": "acc-other",
    })

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"{F.co(client, entity.id)}/settings/petty-cash")
    assert ("danger", "Pick at least one account code.") in flashes(client)
    assert ticks(app, entity.id) == {"400": True, "404": True}
    assert company_country(app, entity.id) == "HK"
    assert not mapping_saved(app, entity.id)


def test_a_code_the_company_does_not_have_does_not_count(shop, xero_live, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={"account_codes[]": ["999", " "]})

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"{F.co(client, entity.id)}/settings/petty-cash")
    assert ticks(app, entity.id) == {"400": True}


def test_a_save_with_one_code_ticked_keeps_exactly_that_one(shop, xero_live, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    add_account(app, db, entity.id, "404", "Bank Fees")
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={"account_codes[]": ["404"]})

    assert resp.status_code == 302
    assert ("success", "Entity settings saved!") in flashes(client)
    assert ticks(app, entity.id) == {"400": False, "404": True}


def test_a_company_with_no_codes_still_saves(shop, xero_live, app, db, client):
    owner, entity = shop
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={})

    assert resp.status_code == 302
    assert ("success", "Entity settings saved!") in flashes(client)


def test_rows_without_a_code_do_not_count(shop, xero_live, app, db, client):
    # They cannot be ticked back on (the save keys on the code), so they never block a save
    owner, entity = shop
    add_account(app, db, entity.id, None, "Uncoded")
    add_account(app, db, entity.id, "  ", "Blank code")
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={})

    assert resp.status_code == 302
    assert ("success", "Entity settings saved!") in flashes(client)


def test_the_first_ever_save_keeps_the_ticks_and_opens_the_dashboard(shop, xero_live, app, db, client):
    # The first mapping save used to switch every code on and leave for the dashboard before
    # the ticks were saved; now the ticks land first, then it goes to the dashboard as before.
    from models.db import AccountInfo, XeroContactSync

    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    add_account(app, db, entity.id, "404", "Bank Fees")
    with app.app_context():
        for xero_id, kind, code, name in (("acc-pc", "BANK", "", "Petty Cash"),
                                          ("acc-dep", "BANK", "", "Business Bank"),
                                          ("acc-sales", "REVENUE", "200", "Sales"),
                                          ("acc-owner", "CURRLIAB", "800", "Director Loan")):
            db.session.add(AccountInfo(entity_id=entity.id, type=kind, name=name, xero_code=code,
                                       xero_account_id=xero_id, status="ACTIVE"))
        db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id="con-1", name="Cash Customer"))
        db.session.commit()
    F.login(client, owner)
    assert not mapping_saved(app, entity.id)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={
        "main_bank": "acc-pc", "deposit_bank": "acc-dep", "discrepancy_bank": "acc-pc",
        "cashsale_account": "200", "cashsale_contact": "con-1",
        "owners_account": "800", "owners_contact": "con-1",
        "discrepancy_account": "400", "discrepancy_contact": "con-1",
        "account_codes[]": ["404"],
    })

    assert resp.status_code == 302
    assert "success=true" in resp.headers["Location"]
    assert mapping_saved(app, entity.id)
    assert ticks(app, entity.id) == {"400": False, "404": True}
    assert flashes(client).count(("success", "Entity settings saved!")) == 1


# ---- one page, two ways in --------------------------------------------------------------------


def test_back_leads_where_the_person_came_from_falling_back_to_the_dashboard(shop, app, db, client):
    owner, entity = shop
    F.login(client, owner)

    html = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)

    assert re.search(
        rf'<a href="{F.co(client, entity.id)}/petty-cash" class="pcs-back" data-back-link>\s*<span[^>]*>chevron_left</span>Back', html
    )
    assert "js/back_link.js" in html
    assert f'href="{F.co(client, entity.id)}/settings/users" class="pcs-pill">Users</a>' in html
    assert f'href="{F.co(client, entity.id)}/settings/modules" class="pcs-pill">Modules</a>' in html
    assert '<span class="pcs-pill" aria-current="page">Petty Cash Settings</span>' in html
    assert 'name="_from"' not in html
    assert "?from=bills" not in html


def test_an_old_from_bills_link_opens_the_same_page(shop, app, db, client):
    owner, entity = shop
    F.login(client, owner)

    plain = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)
    old = client.get(f"{F.co(client, entity.id)}/settings/petty-cash?from=bills").get_data(as_text=True)

    strip_csrf = lambda html: re.sub(r'name="csrf_token" value="[^"]*"', "", html)
    assert strip_csrf(old) == strip_csrf(plain)
    assert "from=bills" not in old and 'name="_from"' not in old


def test_the_codes_reach_the_page_as_data_not_markup(shop, xero_live, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "400", '<img src=x onerror="alert(1)">')
    add_account(app, db, entity.id, "404", "Bank Fees", ticked=False)
    F.login(client, owner)

    html = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)

    assert "<img src=x" not in html
    config = page_config(html)
    assert config["codes"] == [
        {"code": "400", "name": '<img src=x onerror="alert(1)">', "selected": True},
        {"code": "404", "name": "Bank Fees", "selected": False},
    ]
    assert config["canEditCodes"] is True
    # Save starts off: the page script turns it on once the Xero lists have loaded and something changed
    assert re.search(r'<button type="submit" id="saveChangesBtn" class="pcs-save-btn" disabled>', html)
    # the browser tab names the company, as every app's company pages do
    assert f"<title>Petty Cash Settings - {entity.name}</title>" in html


def test_a_view_only_member_gets_no_working_save(shop, app, db, client):
    from models.db import UserEntity

    owner, entity = shop
    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com")
        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
    F.login(client, cashier)

    html = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)

    assert re.search(r'<button type="button" id="saveChangesBtn" class="pcs-save-btn" disabled data-view-only', html)
    assert "You have view-only access to these settings." in html
    assert re.search(r'id="ci_country_display"[^>]*disabled', html, re.S)
    assert page_config(html)["canEditCodes"] is False


# ---- without a live Xero connection ----------------------------------------------------------


NOT_CONNECTED = "Xero isn't connected. Connect it in"


def assert_xero_cards_hidden(html):
    # both Xero-fed cards keep their heading and show only the notice
    assert "Xero account mapping" in html and "Petty Cash Account Code" in html
    assert html.count(NOT_CONNECTED) == 2
    assert 'id="main_bank_select"' not in html
    assert 'id="accountCodeList"' not in html
    assert 'id="xeroRefreshNote"' not in html
    assert "loadXeroDataAsync" not in html  # the mapping script is not on the page
    config = page_config(html)
    assert config["xeroLive"] is False
    assert config["codes"] == []
    # the cards that do not need Xero stay
    assert 'id="ci_country_display"' in html and 'id="paymentMethodsList"' in html


def test_a_company_that_never_connected_sees_the_notice_not_the_lists(shop, app, db, client):
    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")  # cached from an earlier connection
    F.login(client, owner)

    html = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)

    assert_xero_cards_hidden(html)


def test_a_company_with_a_dead_connection_sees_the_notice_not_the_lists(shop, app, db, client):
    from models.db import Entity

    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    with app.app_context():
        # once connected to a Xero organisation, now without a token that resolves
        Entity.query.filter_by(id=entity.id).update({"xero_org_id": "org-gone-1111"})
        db.session.commit()
    F.login(client, owner)

    html = client.get(f"{F.co(client, entity.id)}/settings/petty-cash").get_data(as_text=True)

    assert_xero_cards_hidden(html)
    assert not any("disconnected from Xero" in message for _, message in flashes(client))


def test_a_save_without_xero_leaves_the_ticks_and_the_mapping_alone(shop, app, db, client):
    # The hidden cards post nothing: the cached codes must not be refused over or switched off,
    # and a stray mapping field must not be saved.
    owner, entity = shop
    add_account(app, db, entity.id, "400", "Advertising")
    add_account(app, db, entity.id, "404", "Bank Fees", ticked=False)
    F.login(client, owner)

    resp = client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={
        "country_code": "HK", "main_bank": "acc-bank",
    })

    assert resp.status_code == 302
    assert ("success", "Entity settings saved!") in flashes(client)
    assert ticks(app, entity.id) == {"400": True, "404": False}
    assert not mapping_saved(app, entity.id)
