"""``POST /api/internal/xero/publish`` (``blueprints/xero/routes/routes.py``): minty-petty-cash-api,
which holds no Xero credentials, forwards a report's publish here. The answer is the Petty Cash
API's own (``petty_cash_api/routes/report.py::publish_answer``, pinned by
tests/test_petty_cash_api_report.py and tests/test_report_publish_state.py); the caller is a
service with a signed 60-second assertion naming the company and the person.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import char_factories as F
import jwt
import pytest
from test_report_actions_state import _submitted
from test_report_publish_state import _wait, xero  # noqa: F401  (Xero stubbed)
from test_report_submit_state import db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

URL = "/api/internal/xero/publish"
SCOPE = "petty-cash-publish"


def _post(app, client, entity_id, user_id, body, scope=SCOPE, secret=None):
    now = datetime.now(timezone.utc)
    claims = {"scope": scope, "entity_id": str(entity_id), "user_id": str(user_id), "iat": now,
              "exp": now + timedelta(seconds=60)}
    token = jwt.encode(claims, secret or app.config["SECRET_KEY"], algorithm="HS256")
    return client.post(URL, json=body, headers={"Authorization": f"Bearer {token}"})


def test_a_publish_is_started_for_the_named_person(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = _post(app, client, entity.id, owner.id, {"report_id": report})

    assert resp.status_code == 202, resp.get_json()
    assert resp.get_json()["publishing_status"] == "publishing"
    assert str(_wait(xero.started)[0][2]) == report


def test_the_refusals_come_back_as_the_api_s(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    xero.token = None

    resp = _post(app, client, entity.id, owner.id, {"report_id": report})

    assert resp.status_code == 400 and resp.get_json()["reconnect"] is True
    assert _post(app, client, entity.id, owner.id, {}).status_code == 422
    assert _post(app, client, entity.id, owner.id, {"report_id": "nope"}).status_code == 404


def test_a_caller_without_the_scope_or_the_key_is_refused(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    assert _post(app, client, entity.id, owner.id, {"report_id": report}, scope="petty-cash-publish-reasons").status_code == 401
    assert _post(app, client, entity.id, owner.id, {"report_id": report}, secret="x" * 40).status_code == 401
    assert _post(app, client, entity.id, F.new_id(), {"report_id": report}).status_code == 401
    assert not xero.started


def test_a_person_without_the_publish_right_is_refused(app, client, db, shop, xero):  # noqa: F811
    from models.db import UserEntity

    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com")
        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
        cashier_id = cashier.id

    assert _post(app, client, entity.id, cashier_id, {"report_id": report}).status_code == 403
    assert not xero.started


@pytest.mark.parametrize("view", ["internal_publish", "internal_xero_settings", "internal_deposit_correction",
                                  "internal_publish_reasons", "internal_xero_access_token"])
def test_every_internal_route_a_service_calls_takes_no_csrf_token(app, view):
    """A service calls with a signed assertion and no cookie, so no CSRF token: without the
    exemption Flask answers 400 "The CSRF token is missing." (the test app switches CSRF off, so
    only this pins it - the publish and Xero settings forwards shipped without it, 2026-10-16)."""
    assert f"blueprints.xero.routes.routes.{view}" in app.extensions["csrf"]._exempt_views
