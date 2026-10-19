"""Petty Cash Settings' Xero account mapping save (``entity/services/xero_account_mapping_post.py``)
before its checks move into a service the Jinja page and the Petty Cash API share
(``entity/services/xero_mapping.py``). Xero is never called: the live check is the conftest's
``xero_live`` and the resolvers' live fetch is stubbed to find nothing.

Characterisation, green before and after; tests marked FIXED pin what changed deliberately.
"""
from __future__ import annotations

import char_factories as F
import pytest
from test_petty_cash_settings_page import MAPPING, db, flashes, mapping_saved, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char


@pytest.fixture
def xero_data(app, db):  # noqa: F811
    """The Xero rows the mapping chooses from, as a sync leaves them; Xero's own fetch finds nothing."""
    def seed(entity):
        from models.db import AccountInfo, XeroContactSync

        with app.app_context():
            for xero_id, kind, code, name in (("acc-pc", "BANK", "", "Petty Cash"),
                                              ("acc-dep", "BANK", "", "Business Bank"),
                                              ("acc-sales", "REVENUE", "200", "Sales"),
                                              ("acc-owner", "CURRLIAB", "800", "Director Loan"),
                                              ("acc-adv", "EXPENSE", "400", "Advertising")):
                db.session.add(AccountInfo(entity_id=entity.id, type=kind, name=name, xero_code=code,
                                           xero_account_id=xero_id, status="ACTIVE"))
            db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id="con-1", name="Cash Customer"))
            db.session.commit()
    return seed


@pytest.fixture
def no_xero_fetch(monkeypatch):
    monkeypatch.setattr("blueprints.entity.services.xero_account_mapping_post.get_account", lambda *a, **k: None)
    monkeypatch.setattr("blueprints.entity.services.xero_account_mapping_post.get_contact", lambda *a, **k: None)


def _save(client, owner, entity, **changes):
    F.login(client, owner)
    return client.post(f"{F.co(client, entity.id)}/settings/petty-cash", data={"section": "mapping", **MAPPING, **changes})


def _counts(app, entity_id):
    from models.db import AccountInfo, XeroContactSync

    with app.app_context():
        return (AccountInfo.query.filter_by(entity_id=entity_id).count(),
                XeroContactSync.query.filter_by(entity_id=entity_id).count())


def test_a_whole_mapping_is_saved(app, client, db, shop, xero_live, xero_data, no_xero_fetch):  # noqa: F811
    owner, entity = shop
    xero_data(entity)

    resp = _save(client, owner, entity)

    assert resp.status_code == 302
    assert mapping_saved(app, entity.id)
    assert ("success", "Xero account mapping saved.") in flashes(client)


@pytest.mark.parametrize("changes, words", [
    ({"deposit_bank": "acc-pc"}, "can't be the same"),
    ({"cashsale_contact": ""}, "Please select: Cash Sales contact"),
])
def test_a_mapping_that_does_not_add_up_is_refused(app, client, db, shop, xero_live, xero_data, no_xero_fetch,  # noqa: F811
                                                   changes, words):
    owner, entity = shop
    xero_data(entity)

    _save(client, owner, entity, **changes)

    assert not mapping_saved(app, entity.id)
    assert any(words in message for _, message in flashes(client))


@pytest.mark.parametrize("changes, label", [
    ({"deposit_bank": "acc-ghost"}, "Deposit Bank Account"),
    ({"discrepancy_account": "999"}, "Discrepancy account code"),
    ({"owners_contact": "con-ghost"}, "Director / Responsible person"),
])
def test_fixed_only_the_company_s_own_choices_are_saved(app, client, db, shop, xero_live, xero_data, no_xero_fetch,  # noqa: F811
                                                        changes, label):
    """FIXED: an id the page never offered (a stale page, or a forged post) was looked up in Xero
    and, when Xero had nothing either, saved as an "Unknown Account" / "Unknown Contact" row made up
    on the spot - the publish then failed on it."""
    owner, entity = shop
    xero_data(entity)
    before = _counts(app, entity.id)

    _save(client, owner, entity, **changes)

    assert not mapping_saved(app, entity.id)
    assert _counts(app, entity.id) == before
    assert any(f"Choose the {label} from the list." in message for _, message in flashes(client))
