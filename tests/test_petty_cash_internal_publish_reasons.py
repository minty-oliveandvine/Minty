"""``POST /api/internal/xero/publish-reasons`` (``blueprints/xero/routes/routes.py``): why a
company's failed reports didn't publish, for minty-petty-cash-api's history list, which holds no
Xero code. The reasons are the history page's own (``history_query.publish_reasons``, pinned by
tests/test_petty_cash_api_history.py); the caller is a service with a signed 60-second assertion
naming the company.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from test_report_actions_state import _older
from test_report_submit_state import db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

URL = "/api/internal/xero/publish-reasons"
SCOPE = "petty-cash-publish-reasons"
REASON = {"text": "No account code for Cleaning", "resolved": False, "resolvable": True}


@pytest.fixture
def resolution(monkeypatch):
    """The reasons as the history list would work them out (the resolution's own tests: Flask's)."""
    calls = []

    def fake(entity_id, items, report_id=None, cache=None):
        calls.append(str(report_id))
        return [REASON]

    monkeypatch.setattr("blueprints.report.services.history_query.annotate_resolution", fake)
    return calls


def _post(app, client, entity_id, body, scope=SCOPE, secret=None):
    now = datetime.now(timezone.utc)
    token = jwt.encode({"scope": scope, "entity_id": str(entity_id), "iat": now, "exp": now + timedelta(seconds=60)},
                       secret or app.config["SECRET_KEY"], algorithm="HS256")
    return client.post(URL, json=body, headers={"Authorization": f"Bearer {token}"})


def test_the_failed_reports_reasons_come_back_and_no_others(app, client, db, shop, resolution):  # noqa: F811
    owner, entity = shop
    failed = _older(app, db, entity, owner, days_back=1, publishing_status="failed")
    fine = _older(app, db, entity, owner, days_back=0)

    resp = _post(app, client, entity.id, {"report_ids": [failed, fine]})

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"reasons": {failed: [{"text": REASON["text"], "resolved": False}], fine: []}}
    assert resolution == [failed]  # only a failed report is worked out


def test_another_companys_report_is_left_out(app, client, db, shop, resolution):  # noqa: F811
    from char_factories import make_entity, make_user

    owner, entity = shop
    with app.app_context():
        stranger = make_user(db, "stranger@test.com")
        theirs = make_entity(db, stranger, name="Their Shop")
    failed = _older(app, db, entity, owner, days_back=0, publishing_status="failed")

    resp = _post(app, client, theirs.id, {"report_ids": [failed]})

    assert resp.status_code == 200 and resp.get_json() == {"reasons": {}}
    assert resolution == []


@pytest.mark.parametrize("body", [{}, {"report_ids": "x"}, {"report_ids": ["not-a-uuid"]},
                                  {"report_ids": [str(uuid.uuid4()) for _ in range(101)]}, ["x"]])
def test_bad_input_is_refused(app, client, db, shop, resolution, body):  # noqa: F811
    _owner, entity = shop

    resp = _post(app, client, entity.id, body)

    assert resp.status_code == 422 and resp.get_json()["error"]


@pytest.mark.parametrize("assertion", [{"scope": "petty-cash-deposit-correction"},
                                       {"secret": "not-the-key-flask-and-the-django-service-share"}])
def test_a_caller_without_a_good_assertion_is_refused(app, client, db, shop, resolution, assertion):  # noqa: F811
    _owner, entity = shop

    resp = _post(app, client, entity.id, {"report_ids": []}, **assertion)

    assert resp.status_code == 401 and resp.get_json() == {"error": "unauthorized"}


def test_the_route_takes_no_csrf_token(app):
    assert "blueprints.xero.routes.routes.internal_publish_reasons" in app.extensions["csrf"]._exempt_views
