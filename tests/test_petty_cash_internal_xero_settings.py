"""``POST /api/internal/xero/petty-cash-settings`` (``blueprints/xero/routes/routes.py``):
minty-petty-cash-api, which holds no Xero code, forwards Petty Cash Settings' Xero cards here. The
answers are the Petty Cash API's own (``petty_cash_api/routes/settings.py::xero_settings_answer``,
pinned by tests/test_petty_cash_api_xero_settings.py); the caller is a service with a signed
60-second assertion naming the company and the person.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import char_factories as F
import jwt
import pytest
from test_petty_cash_api_settings import cashier, shop  # noqa: F401  (fixtures)
from test_petty_cash_api_xero_settings import MAPPING, lists, xero  # noqa: F401  (fixtures)
from test_report_submit_state import db  # noqa: F401  (fixture)

pytestmark = pytest.mark.char

URL = "/api/internal/xero/petty-cash-settings"


def _post(app, client, entity_id, user_id, payload, scope="petty-cash-xero-settings"):
    now = datetime.now(timezone.utc)
    claims = {"scope": scope, "entity_id": str(entity_id), "user_id": str(user_id), "iat": now,
              "exp": now + timedelta(seconds=60)}
    token = jwt.encode(claims, app.config["SECRET_KEY"], algorithm="HS256")
    return client.post(URL, json=payload, headers={"Authorization": f"Bearer {token}"})


def test_each_action_answers_as_the_api(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop

    read = _post(app, client, entity.id, owner.id, {"action": "read"})
    assert read.status_code == 200 and read.get_json()["live"] is True
    saved = _post(app, client, entity.id, owner.id, {"action": "mapping", "body": MAPPING})
    assert saved.status_code == 200 and saved.get_json()["message"] == "Xero account mapping saved."
    codes = _post(app, client, entity.id, owner.id, {"action": "account-codes", "body": {"codes": []}})
    assert codes.status_code == 422 and codes.get_json() == {"error": "Pick at least one account code."}


def test_a_bad_action_or_caller_is_refused(app, client, db, shop, lists, xero):  # noqa: F811
    owner, entity = shop
    assert _post(app, client, entity.id, owner.id, {"action": "delete"}).status_code == 422
    assert _post(app, client, entity.id, owner.id, {"action": "read"}, scope="petty-cash-publish").status_code == 401
    assert _post(app, client, entity.id, F.new_id(), {"action": "read"}).status_code == 401
    person = cashier(app, db, entity)
    assert _post(app, client, entity.id, person.id, {"action": "mapping", "body": MAPPING}).status_code == 403
