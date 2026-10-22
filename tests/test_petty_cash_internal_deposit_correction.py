"""``POST /api/internal/xero/deposit-correction`` (``blueprints/xero/routes/routes.py``): the deposit
correction minty-petty-cash-api forwards, because it holds no Xero credentials. The caller is a
service with a signed 60-second assertion naming the company and the person; the answer is the
Petty Cash API's own (``petty_cash_api/routes/home.py::correct_deposit``, shared with
``POST /deposit-correction``). The correction itself is tests/test_report_deposit_change.py's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from test_petty_cash_api_home import _member, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

URL = "/api/internal/xero/deposit-correction"
SCOPE = "petty-cash-deposit-correction"
BODY = {"kind": "change", "date": "2026-10-13", "amount": 12.5}


@pytest.fixture
def delegate(monkeypatch):
    """Stand in for the shared correction (its own behaviour: tests/test_report_deposit_change.py)."""
    from blueprints.report.routes import legacy

    calls = []

    def fake(entity_id, correction):
        calls.append((entity_id, correction))
        return fake.answer

    fake.answer = ({"status": "success", "message": "Previous day's deposit updated successfully.", "id": 7,
                    "bank_deposit": 12.5, "redirect_url": "/flask/opening"}, 200)
    monkeypatch.setattr(legacy, "correct_previous_deposit", fake)
    fake.calls = calls
    return fake


def _assertion(app, *, entity_id, user_id, scope=SCOPE, seconds=60, secret=None, drop=()):
    now = datetime.now(timezone.utc)
    claims = {"scope": scope, "entity_id": str(entity_id), "user_id": str(user_id), "iat": now,
              "exp": now + timedelta(seconds=seconds)}
    for name in drop:
        claims.pop(name)
    return jwt.encode(claims, secret or app.config["SECRET_KEY"], algorithm="HS256")


def _post(app, client, shop, body=BODY, user_id=None, **assertion):  # noqa: F811
    token = _assertion(app, entity_id=shop["entity"].id, user_id=user_id or shop["owner"].id, **assertion)
    return client.post(URL, json=body, headers={"Authorization": f"Bearer {token}"})


def test_the_correction_is_answered_as_the_petty_cash_api_answers_it(app, client, shop, delegate):  # noqa: F811
    resp = _post(app, client, shop)

    assert resp.status_code == 200, resp.get_json()
    assert delegate.calls == [(shop["entity"].id, BODY)]
    body = resp.get_json()
    assert body["status"] == "success" and body["id"] == "7" and body["next_transaction_date"] == "2026-10-14"
    assert "redirect_url" not in body


def test_a_refusal_from_the_correction_is_the_apis_refusal(app, client, shop, delegate):  # noqa: F811
    delegate.answer = ({"status": "error", "message": "That deposit is larger than the previous one."}, 400)

    resp = _post(app, client, shop)

    assert resp.status_code == 400 and resp.get_json() == {"error": "That deposit is larger than the previous one."}


@pytest.mark.parametrize("assertion", [
    {"scope": "xero-access-token"},  # the token route's scope is not this route's
    {"seconds": -120},  # past the 60 s clock skew every backend allows
    {"secret": "not-the-key-flask-and-the-django-service-share"},
    {"drop": ("user_id",)},
    {"drop": ("entity_id",)},
])
def test_a_caller_without_a_good_assertion_is_refused(app, client, shop, delegate, assertion):  # noqa: F811
    resp = _post(app, client, shop, **assertion)

    assert resp.status_code == 401 and resp.get_json() == {"error": "unauthorized"}
    assert delegate.calls == []


def test_no_assertion_at_all_is_refused(app, client, shop, delegate):  # noqa: F811
    resp = client.post(URL, json=BODY)

    assert resp.status_code == 401 and delegate.calls == []


def test_the_person_is_checked_again_here(app, client, db, shop, delegate):  # noqa: F811
    cashier = _member(app, db, shop, "cashier@test.com", "cashier")
    assert _post(app, client, shop, user_id=cashier.id).status_code == 403

    from models.db import User

    with app.app_context():
        User.query.filter_by(id=shop["owner"].id).update({"approved": False})
        db.session.commit()
    assert _post(app, client, shop).status_code == 401
    assert delegate.calls == []


def test_bad_input_is_refused_before_anything_changes(app, client, shop, delegate):  # noqa: F811
    resp = _post(app, client, shop, body={"kind": "no", "date": "2026-10-13", "amount": 5})

    assert resp.status_code == 422 and resp.get_json() == {"error": "No deposit means an amount of 0."}
    assert delegate.calls == []


def test_the_route_takes_no_csrf_token(app):
    """The caller is a service with no cookie: without the exemption a POST is turned away."""
    csrf = app.extensions["csrf"]
    assert "blueprints.xero.routes.routes.internal_deposit_correction" in csrf._exempt_views
