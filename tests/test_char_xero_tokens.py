"""Characterisation: Xero OAuth tokens - stored, refreshed, handed to services, cleared.

C1 of docs/modernisation/modernisation_plan.md moves the six token columns off ``user`` and makes
``user_token`` the only store (the schema already says so; the code keeps a shadow copy on
the user row and hydrates it). Everything here is observed through the endpoints and the
service that hand tokens out, with the Xero identity server stubbed at ``requests`` -
never by reading a column:

* ``POST /api/internal/xero/token`` - what billing-backend and onboarding-backend call
  (they never refresh; Minty is the only service that may, because Xero rotates the
  refresh token on use);
* ``GET /api/refresh_xero_token`` - the signed-in user's own refresh;
* ``GET /entity/settings/xero/disconnect``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

import char_factories as F

pytestmark = pytest.mark.char

TENANT = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def connected(app, db):
    """An entity connected to Xero by its admin, holding a fresh token bundle."""
    with app.app_context():
        currency = F.seed_currency(db, denominations=())  # no cash count here
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.connect_xero(db, owner, entity, tenant_id=TENANT,
                       tokens={"access_token": "access-1", "refresh_token": "refresh-1",
                               "id_token": "id-1", "expires_in": 1800})
    return owner, entity


class XeroIdentity:
    """Stand-in for identity.xero.com and api.xero.com at the ``requests`` boundary.

    Records every call. ``refresh_response`` is what /connect/token answers; set it to a
    failure to make the next refresh fail. Nothing in our own code is patched.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.refresh_response = {"status": 200, "json": {
            "access_token": "access-2", "refresh_token": "refresh-2", "id_token": "id-2", "expires_in": 1800}}
        self.connections = [{"id": "conn-1", "tenantId": TENANT, "tenantName": "E2E Org"}]

    class _Resp:
        def __init__(self, status, payload=None, text=""):
            self.status_code, self._payload, self.text = status, payload, text

        def json(self):
            return self._payload

    def post(self, url, data=None, headers=None, timeout=None, **kw):
        self.calls.append(("POST", url, dict(data or {})))
        if "connect/token" in url:
            r = self.refresh_response
            return self._Resp(r["status"], r.get("json"), r.get("text", ""))
        return self._Resp(404, {}, "unexpected")

    def get(self, url, headers=None, timeout=None, **kw):
        self.calls.append(("GET", url, {}))
        if "connections" in url:
            return self._Resp(200, self.connections)
        return self._Resp(404, {}, "unexpected")

    def delete(self, url, headers=None, timeout=None, **kw):
        self.calls.append(("DELETE", url, {}))
        return self._Resp(204, None)

    def refreshes(self):
        return [c for c in self.calls if c[0] == "POST" and "connect/token" in c[1]]


@pytest.fixture
def xero(monkeypatch):
    fake = XeroIdentity()
    import requests

    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr(requests, "delete", fake.delete)
    return fake


def service_jwt(app, entity_id, *, scope="xero-access-token", minutes=5):
    payload = {"entity_id": entity_id, "scope": scope,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def internal_token(client, app, entity_id, **kw):
    return client.post("/api/internal/xero/token",
                       headers={"Authorization": "Bearer " + service_jwt(app, entity_id, **kw)})


# ---- handing tokens to services --------------------------------------------------------------


def test_service_gets_the_connectors_live_token(connected, client, app, xero):
    owner, entity = connected
    resp = internal_token(client, app, entity.id)
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body == {"access_token": "access-1", "xero_org_id": TENANT}
    assert xero.refreshes() == [], "a fresh token is handed out without touching Xero"


def test_expired_token_is_refreshed_once_and_the_new_one_is_reused(connected, client, app, db, xero):
    owner, entity = connected
    with app.app_context():
        F.age_xero_token(db, owner, seconds=3600)  # obtained an hour ago, 1800 s lifetime

    first = internal_token(client, app, entity.id)
    assert first.status_code == 200, first.data[:300]
    assert first.get_json()["access_token"] == "access-2"
    assert len(xero.refreshes()) == 1
    assert xero.refreshes()[0][2]["refresh_token"] == "refresh-1", "the stored refresh token was presented"

    second = internal_token(client, app, entity.id)
    assert second.get_json()["access_token"] == "access-2"
    assert len(xero.refreshes()) == 1, "the refreshed token is stored, not refreshed again"


def test_failed_refresh_answers_reconnect_required_and_keeps_the_old_refresh_token(connected, client, app, db, xero):
    owner, entity = connected
    with app.app_context():
        F.age_xero_token(db, owner, seconds=3600)
    xero.refresh_response = {"status": 400, "json": {"error": "invalid_grant"}, "text": "invalid_grant"}

    resp = internal_token(client, app, entity.id)
    assert resp.status_code == 409, resp.data[:300]
    assert resp.get_json()["status"] == "reconnect_required"

    # nothing was overwritten: when Xero recovers, the SAME refresh token is presented
    xero.refresh_response = {"status": 200, "json": {
        "access_token": "access-3", "refresh_token": "refresh-3", "id_token": "id-3", "expires_in": 1800}}
    resp = internal_token(client, app, entity.id)
    assert resp.status_code == 200, resp.data[:300]
    assert xero.refreshes()[-1][2]["refresh_token"] == "refresh-1"


def test_entity_nobody_connected_answers_reconnect_required(app, db, client, xero):
    with app.app_context():
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner)
    resp = internal_token(client, app, entity.id)
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "reconnect_required"


def test_service_endpoint_rejects_bad_tokens(connected, client, app):
    owner, entity = connected
    assert client.post("/api/internal/xero/token").status_code == 401
    assert internal_token(client, app, entity.id, scope="onboarding").status_code == 401
    assert internal_token(client, app, entity.id, minutes=-1).status_code == 401
    forged = jwt.encode({"entity_id": entity.id, "scope": "xero-access-token",
                         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, "not-the-secret", algorithm="HS256")
    assert client.post("/api/internal/xero/token", headers={"Authorization": "Bearer " + forged}).status_code == 401


# ---- the signed-in user's own refresh ---------------------------------------------------------


def test_signed_in_user_can_refresh_their_own_token(connected, client, app, xero):
    owner, entity = connected
    F.login(client, owner)
    resp = client.get("/api/refresh_xero_token")
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["access_token"] == "access-2"
    assert xero.refreshes()[0][2]["refresh_token"] == "refresh-1"



def test_the_token_check_answers_for_a_fresh_token(connected, client, app, xero):
    owner, entity = connected
    F.login(client, owner)
    resp = client.get("/check/token")
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_data(as_text=True) == "Valid Token"
    assert xero.refreshes() == [], "a fresh token is checked without touching Xero"


def test_the_token_check_says_expired_when_xero_refuses_to_renew(connected, client, app, db,
                                                                 xero):
    owner, entity = connected
    with app.app_context():
        F.age_xero_token(db, owner, seconds=3600)
    xero.refresh_response = {"status": 400, "json": {"error": "invalid_grant"}}
    F.login(client, owner)
    resp = client.get("/check/token")
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_data(as_text=True) == "expired_token"


def test_the_refresh_button_renews_an_aged_token(connected, client, app, db, xero):
    """``POST /refresh_token``. The renewal may happen in the request middleware before the
    view runs; the outcome is what is pinned - one refresh, presenting the stored refresh
    token, and the new access token handed out from then on."""
    owner, entity = connected
    with app.app_context():
        F.age_xero_token(db, owner, seconds=3600)
    F.login(client, owner)
    resp = client.post("/refresh_token")
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["status"] == "success"
    assert len(xero.refreshes()) == 1
    assert xero.refreshes()[0][2]["refresh_token"] == "refresh-1"
    assert internal_token(client, app, entity.id).get_json()["access_token"] == "access-2"

def test_refresh_without_a_connection_is_an_error_not_a_crash(app, db, client, xero):
    with app.app_context():
        user = F.make_user(db, "nobody@test.com")
        F.make_entity(db, user)
    F.login(client, user)
    resp = client.get("/api/refresh_xero_token")
    assert resp.status_code == 500
    assert "reconnect" in resp.get_json()["message"].lower()


def test_two_members_hold_separate_tokens(connected, client, app, db, xero):
    """The connector's refresh never touches another member's bundle."""
    owner, entity = connected
    with app.app_context():
        other = F.make_user(db, "other@test.com")
        from models.db import UserEntity

        db.session.add(UserEntity(user_id=other.id, entity_id=entity.id, role="accountant", approved=True))
        db.session.commit()
        F.store_xero_tokens(db, other, {"access_token": "other-access", "refresh_token": "other-refresh",
                                        "id_token": "other-id", "expires_in": 1800})
        F.age_xero_token(db, owner, seconds=3600)

    assert internal_token(client, app, entity.id).get_json()["access_token"] == "access-2"

    F.login(client, other)
    resp = client.get("/api/refresh_xero_token")
    assert resp.status_code == 200
    assert xero.refreshes()[-1][2]["refresh_token"] == "other-refresh", "the other member's own bundle was used"


# ---- disconnect ---------------------------------------------------------------------------------


def test_disconnect_revokes_at_xero_and_the_service_then_needs_a_reconnect(connected, client, app, xero):
    owner, entity = connected
    F.login(client, owner)

    resp = client.get(f"/entity/settings/xero/disconnect?entity_id={entity.id}")

    assert resp.status_code == 302, resp.data[:300]
    assert any(c[0] == "DELETE" and "connections/conn-1" in c[1] for c in xero.calls), xero.calls
    assert internal_token(client, app, entity.id).status_code == 409
    page = client.get(f"/entity/{entity.id}/settings/xero")
    assert page.status_code == 200
    assert "connect to xero" in page.get_data(as_text=True).lower()


def test_only_a_member_with_xero_rights_can_disconnect(connected, client, app, db, xero):
    owner, entity = connected
    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com")
        from models.db import UserEntity

        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
    F.login(client, cashier)
    resp = client.get(f"/entity/settings/xero/disconnect?entity_id={entity.id}")
    assert resp.status_code in (302, 403)
    assert not any(c[0] == "DELETE" for c in xero.calls)
    assert internal_token(client, app, entity.id).status_code == 200, "still connected"
