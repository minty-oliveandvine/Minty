"""Petty Cash Settings' account-code rule (``entity/services/xero_mapping.py``), pinned through Flask's
settings page (``/entity/settings/entity/<id>``) until Flask's HTML frontend was deleted
(2026-10-20); the page now hands over to minty-petty-cash-web, and the rule is driven through the
Petty Cash API's ``PUT /settings/xero/account-codes``.

The API's own answers (at least one code, no live Xero, a cashier, the mapping, the country) are
tests/test_petty_cash_api_xero_settings.py's and tests/test_petty_cash_api_settings.py's; what is
left here is what those do not pin: a code the company does not have never counts as the one
ticked, and a refused save changes no tick.
"""

from __future__ import annotations

import pytest
from test_petty_cash_api_settings import call, shop  # noqa: F401  (fixtures)
from test_petty_cash_api_xero_settings import lists, xero  # noqa: F401  (fixtures)
from test_report_submit_state import db  # noqa: F401  (fixture)

pytestmark = pytest.mark.char


def ticks(app, entity_id) -> dict:
    """code -> ticked, as the expense form will read them."""
    from models.db import AccountInfo, EntityAccountXero, db as _db

    with app.app_context():
        rows = (
            _db.session.query(AccountInfo.xero_code, EntityAccountXero.is_active)
            .join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .all()
        )
    return {code: active for code, active in rows}


@pytest.mark.parametrize("codes", [["999"], [" "], ["999", " "]])
def test_a_code_the_company_does_not_have_does_not_count(app, client, db, shop, lists, xero, codes):  # noqa: F811
    owner, entity = shop
    before = ticks(app, entity.id)

    resp = call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": codes})

    assert resp.status_code == 422 and resp.get_json() == {"error": "Pick at least one account code."}
    assert ticks(app, entity.id) == before == {"400": True, "404": False}


def test_a_known_code_beside_an_unknown_one_is_the_one_ticked(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop

    resp = call(app, client, "PUT", entity, owner, "/settings/xero/account-codes", json={"codes": ["404", "999"]})

    assert resp.status_code == 200, resp.get_json()
    assert ticks(app, entity.id) == {"400": False, "404": True}
