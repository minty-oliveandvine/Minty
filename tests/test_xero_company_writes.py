from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

from blueprints.xero.routes import routes as xero_routes


class _QueryStub:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _SessionStub:
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        raise AssertionError("rollback should not be called in the happy path")


class _ThreadStub:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def test_xero_entity_connect_callback_does_not_assign_user_company(monkeypatch):
    app = _build_app()
    session = _SessionStub()
    fake_entity = SimpleNamespace(
        id="entity-1",
        xero_org_id=None,
        status=None,
        last_connected_at=None,
    )
    fake_user = SimpleNamespace(
        id="user-1",
        username="member@test.com",
        xero_entity_id=None,
    )

    class FakeUser:
        username = object()
        query = _QueryStub(fake_user)

    class FakeEntity:
        created_at = object()
        query = _QueryStub(fake_entity)

    def fake_decode_jwt(token):
        if token == "id-token":
            return {"preferred_username": "member@test.com"}
        return {"authentication_event_id": "auth-event"}

    def fake_requests_get(*_args, **_kwargs):
        return SimpleNamespace(json=lambda: [{"tenantId": "tenant-1"}])

    monkeypatch.setattr(xero_routes, "User", FakeUser)
    monkeypatch.setattr(xero_routes, "Entity", FakeEntity)
    monkeypatch.setattr(xero_routes, "current_user", SimpleNamespace(username="member@test.com"))
    monkeypatch.setattr(
        xero_routes,
        "get_auth_token",
        lambda *_args, **_kwargs: {
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(xero_routes, "decode_jwt", fake_decode_jwt)
    monkeypatch.setattr(xero_routes, "requests", SimpleNamespace(get=fake_requests_get))
    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(xero_routes, "desc", lambda value: value)
    monkeypatch.setattr(xero_routes, "threading", SimpleNamespace(Thread=_ThreadStub))
    monkeypatch.setattr(xero_routes, "time", SimpleNamespace(sleep=lambda *_args, **_kwargs: None))
    monkeypatch.setattr(
        xero_routes,
        "sync_all_accounts_and_contacts_background",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(xero_routes, "login_user", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(xero_routes, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(xero_routes, "url_for", lambda endpoint, **_kwargs: f"/{endpoint}")
    monkeypatch.setattr(
        xero_routes,
        "redirect",
        lambda location: SimpleNamespace(status_code=302, location=location),
    )

    with app.test_request_context("/callback?state=entity_connect&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert response.location == "/entity.entity_list"
    assert fake_entity.xero_org_id == "tenant-1"
    assert fake_entity.status == "connected"
    assert fake_user.xero_entity_id == "tenant-1"
    assert session.commit_calls == 1
