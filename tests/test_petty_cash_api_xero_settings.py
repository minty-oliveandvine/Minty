"""The Petty Cash API's Xero settings cards (``petty_cash_api/routes/settings.py``: ``GET
/settings/xero``, ``PUT /settings/xero/mapping``, ``PUT /settings/xero/account-codes``) over the
page's own service (``entity/services/xero_mapping.py``, pinned by tests/test_xero_mapping_state.py
and tests/test_petty_cash_settings_page.py). Xero is never called: the live check and the refresh
are stubbed, and the lists are the database's, as a sync leaves them."""
from __future__ import annotations

import pytest
from test_petty_cash_api_settings import call, cashier, shop  # noqa: F401  (fixtures)
from test_report_submit_state import db  # noqa: F401  (fixture)

pytestmark = pytest.mark.char

MAPPING = {"main_bank": "acc-pc", "deposit_bank": "acc-dep", "cashsale_account": "acc-sales",
           "cashsale_contact": "con-1", "owners_account": "acc-owner", "owners_contact": "con-1",
           "discrepancy_account": "acc-adv", "discrepancy_contact": "con-1"}


@pytest.fixture
def xero(monkeypatch):
    state = {"live": True, "refreshed": 0}

    def refresh(org, user, app):
        state["refreshed"] += 1

    monkeypatch.setattr("blueprints.entity.services.xero_mapping.is_live", lambda org, user: state["live"])
    monkeypatch.setattr("blueprints.entity.services.xero_mapping.refresh_from_xero", refresh)
    return state


@pytest.fixture
def lists(app, db, shop):  # noqa: F811
    """The company connected, with the accounts and the contact the mapping chooses from, and two
    Petty Cash codes (400 ticked, 404 not)."""
    from models.db import AccountInfo, Entity, EntityAccountXero, XeroContactSync

    _owner, entity = shop
    with app.app_context():
        row = db.session.get(Entity, entity.id)
        row.xero_org_id, row.xero_tenant_name = "org-1", "Corner Shop Ltd"
        for xero_id, kind, code, name, tick in (("acc-pc", "BANK", "", "Petty Cash", None),
                                                ("acc-dep", "BANK", "", "Business Bank", None),
                                                ("acc-sales", "REVENUE", "200", "Sales", None),
                                                ("acc-owner", "CURRLIAB", "800", "Director Loan", None),
                                                ("acc-adv", "EXPENSE", "400", "Advertising", True),
                                                ("acc-fee", "EXPENSE", "404", "Bank Fees", False)):
            account = AccountInfo(entity_id=entity.id, type=kind, name=name, xero_code=code,
                                  xero_account_id=xero_id, status="ACTIVE")
            db.session.add(account)
            db.session.flush()
            if tick is not None:
                db.session.add(EntityAccountXero(account_id=account.id, name=name, type=kind,
                                                 xero_account_id=xero_id, is_active=tick))
        db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id="con-1", name="Cash Customer"))
        db.session.commit()


def _field(body, key):
    return next(f for f in body["mapping"] if f["key"] == key)


def test_the_cards_read_the_lists_once_the_connection_is_live(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop
    body = call(app, client, "GET", entity, owner, "/settings/xero").get_json()

    assert (body["live"], body["organisation"], body["mapping_saved"], xero["refreshed"]) == (True, "Corner Shop Ltd", False, 1)
    assert [f["key"] for f in body["mapping"]] == list(MAPPING)
    assert {o["id"] for o in _field(body, "main_bank")["options"]} == {"acc-pc", "acc-dep"}
    assert _field(body, "cashsale_contact")["options"] == [{"id": "con-1", "name": "Cash Customer"}]
    assert body["account_codes"] == [{"code": "400", "name": "Advertising", "selected": True},
                                     {"code": "404", "name": "Bank Fees", "selected": False}]
    assert body["permissions"] == {"edit_mapping": True, "edit_account_codes": True}


def test_without_a_live_connection_the_cards_say_so_and_refuse_a_save(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop
    xero["live"] = False

    body = call(app, client, "GET", entity, owner, "/settings/xero").get_json()
    assert (body["live"], body["mapping"], body["account_codes"], xero["refreshed"]) == (False, None, None, 0)
    assert call(app, client, "PUT", entity, owner, "/settings/xero/mapping", json=MAPPING).status_code == 409
    assert call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": ["400"]}).status_code == 409


def test_the_mapping_is_saved_and_read_back(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "PUT", entity, owner, "/settings/xero/mapping", json=MAPPING)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert (body["message"], body["first_save"], body["mapping_saved"]) == ("Xero account mapping saved.", True, True)
    assert _field(body, "deposit_bank")["selected"] == "acc-dep" and _field(body, "owners_contact")["selected"] == "con-1"
    again = call(app, client, "PUT", entity, owner, "/settings/xero/mapping", json=MAPPING).get_json()
    assert again["first_save"] is False


@pytest.mark.parametrize("changes, message", [
    ({"cashsale_contact": ""}, "Choose the Cash Sales contact."),
    ({"deposit_bank": "acc-pc"}, "The Petty Cash Account and the Deposit Bank Account can't be the same. "
                                 "Choose a different one for each."),
    ({"deposit_bank": "acc-ghost"}, "Choose the Deposit Bank Account from the list."),
    ({"owners_contact": "con-ghost"}, "Choose the Director / Responsible person from the list."),
])
def test_a_mapping_that_does_not_add_up_is_refused(app, client, db, shop, lists, xero, changes, message):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "PUT", entity, owner, "/settings/xero/mapping", json={**MAPPING, **changes})

    assert resp.status_code == 422 and resp.get_json() == {"error": message}
    assert call(app, client, "GET", entity, owner, "/settings/xero").get_json()["mapping_saved"] is False


def test_the_account_codes_keep_at_least_one(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop
    done = call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": ["404"]})
    assert done.status_code == 200, done.get_json()
    assert [c["selected"] for c in done.get_json()["account_codes"]] == [False, True]

    refused = call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": []})
    assert refused.status_code == 422 and refused.get_json() == {"error": "Pick at least one account code."}
    bad = call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": "400"})
    assert bad.status_code == 422


def test_a_cashier_reads_but_changes_nothing(app, client, db, shop, lists, xero):  # noqa: F811
    _owner, entity = shop
    person = cashier(app, db, entity)
    body = call(app, client, "GET", entity, person, "/settings/xero").get_json()
    assert body["permissions"] == {"edit_mapping": False, "edit_account_codes": False}
    assert call(app, client, "PUT", entity, person, "/settings/xero/mapping", json=MAPPING).status_code == 403
    assert call(app, client, "PUT", entity, person, "/settings/xero/account-codes", json={"codes": ["400"]}).status_code == 403
