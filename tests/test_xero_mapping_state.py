"""Petty Cash Settings' Xero account mapping save, through the Petty Cash API's ``PUT
/settings/xero/mapping`` (``entity/services/xero_mapping.py``; the Jinja page that also posted it
went with Flask's HTML on 2026-10-20 - the API's other answers are
tests/test_petty_cash_api_xero_settings.py's). Xero is never called: the live check and the refresh
are stubbed, and the resolvers' live fetch is stubbed to find nothing.

Characterisation; tests marked FIXED pin what changed deliberately.
"""
from __future__ import annotations

import pytest
from test_petty_cash_api_settings import call, shop  # noqa: F401  (fixtures)
from test_petty_cash_api_xero_settings import MAPPING, lists, xero  # noqa: F401  (fixtures)
from test_report_submit_state import db  # noqa: F401  (fixture)

pytestmark = pytest.mark.char


@pytest.fixture
def no_xero_fetch(monkeypatch):
    monkeypatch.setattr("blueprints.entity.services.xero_account_mapping_post.get_account", lambda *a, **k: None)
    monkeypatch.setattr("blueprints.entity.services.xero_account_mapping_post.get_contact", lambda *a, **k: None)


def _counts(app, entity_id):
    from models.db import AccountInfo, XeroContactSync

    with app.app_context():
        return (AccountInfo.query.filter_by(entity_id=entity_id).count(),
                XeroContactSync.query.filter_by(entity_id=entity_id).count())


@pytest.mark.parametrize("changes, label", [
    ({"deposit_bank": "acc-ghost"}, "Deposit Bank Account"),
    ({"discrepancy_account": "acc-ghost"}, "Discrepancy account code"),
    ({"owners_contact": "con-ghost"}, "Director / Responsible person"),
])
def test_fixed_only_the_company_s_own_choices_are_saved(app, client, db, shop, lists, xero, no_xero_fetch,  # noqa: F811
                                                        changes, label):
    """FIXED: an id the page never offered (a stale page, or a forged post) was looked up in Xero
    and, when Xero had nothing either, saved as an "Unknown Account" / "Unknown Contact" row made up
    on the spot - the publish then failed on it."""
    owner, entity = shop
    before = _counts(app, entity.id)

    resp = call(app, client, "PUT", entity, owner, "/settings/xero/mapping", json={**MAPPING, **changes})

    assert resp.status_code == 422
    assert resp.get_json() == {"error": f"Choose the {label} from the list."}
    assert _counts(app, entity.id) == before
    assert call(app, client, "GET", entity, owner, "/settings/xero").get_json()["mapping_saved"] is False
