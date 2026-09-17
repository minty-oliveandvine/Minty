"""Tests for the entity_connect / entity_connect_onboarding callback branch.

Regression suite for the race condition where two users onboarding
simultaneously could have their Xero orgs assigned to each other's entity.

Root cause (now fixed): the callback used
    Entity.query.order_by(desc(Entity.created_at)).first()
which returns the globally most-recently-created entity — not the current
user's entity.

Fix: the entity_id is embedded in the OAuth state param
("entity_connect:<uuid>") so the callback resolves exactly that entity via
Entity.query.get(entity_id).
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

from blueprints.xero.routes import routes as xero_routes


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _SessionStub:
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        raise AssertionError("rollback should not be called")


class _ThreadStub:
    def __init__(self, target=None, args=(), daemon=None):
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


class _OrderByStub:
    """Wraps a fixed result for .order_by(...).first() chains."""
    def __init__(self, result):
        self._result = result

    def first(self):
        return self._result

    def order_by(self, *_args):
        return self

    def filter(self, *_args):
        return self


class _UserQuery:
    """Mimics User.query — .filter(...).first() always returns the same user."""
    def __init__(self, user):
        self._user = user

    def filter(self, *_args):
        return _OrderByStub(self._user)

    def order_by(self, *_args):
        return _OrderByStub(self._user)

    def get(self, *_args):
        return self._user


class _EntityQuery:
    """Mimics Entity.query.
    .get(id) → by_id dict lookup
    .order_by(...).first() → latest entity
    .filter(...).first() → latest entity
    """
    def __init__(self, by_id: dict, latest):
        self._by_id = by_id
        self._latest = latest

    def get(self, entity_id):
        return self._by_id.get(entity_id)

    def order_by(self, *_args):
        return _OrderByStub(self._latest)

    def filter(self, *_args):
        return _OrderByStub(self._latest)


class _FakeUserClass:
    """Stands in for the User SQLAlchemy model class."""
    username = object()

    def __init__(self, query):
        self.query = query


class _FakeEntityClass:
    """Stands in for the Entity SQLAlchemy model class."""
    created_at = object()

    def __init__(self, query):
        self.query = query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def _make_entity(entity_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=entity_id,
        xero_org_id=None,
        xero_tenant_name=None,
        status=None,
        last_connected_at=None,
        connected_by_user_id=None,
    )


def _make_user(user_id: str, username: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        username=username,
    )


def _patch_all(monkeypatch, *, user, by_id: dict, latest, session, from_onboarding=False):
    """Apply all monkeypatches needed for the entity_connect callback branch."""
    fake_user_class = _FakeUserClass(_UserQuery(user))
    fake_user_class.username = object()

    fake_entity_class = _FakeEntityClass(_EntityQuery(by_id, latest))
    fake_entity_class.created_at = object()

    monkeypatch.setattr(xero_routes, "User", fake_user_class)
    monkeypatch.setattr(xero_routes, "Entity", fake_entity_class)
    # the callback resolves the Xero login through identity.resolve_user_by_email (a real
    # User query); this suite has no database, so the stubbed user is the answer
    monkeypatch.setattr(xero_routes, "resolve_user_by_email", lambda _email: user)
    # the one-org-one-entity guard and the org-switch cache invalidation query Entity for
    # real; neither is what this suite pins (test_xero_org_claim*.py / test_xero_org_switch_*.py)
    monkeypatch.setattr(xero_routes, "_live_org_claimant", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "invalidate_entity_xero_cache", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "current_user", SimpleNamespace(username=user.username))
    monkeypatch.setattr(
        xero_routes,
        "get_auth_token",
        lambda *_a, **_kw: {
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        xero_routes,
        "decode_jwt",
        lambda token: (
            {"preferred_username": user.username}
            if token == "id-token"
            else {"authentication_event_id": "auth-event"}
        ),
    )
    monkeypatch.setattr(
        xero_routes,
        "requests",
        SimpleNamespace(
            get=lambda *_a, **_kw: SimpleNamespace(
                json=lambda: [{"tenantId": "xero-tenant-abc", "tenantName": "Acme Ltd"}]
            )
        ),
    )
    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(xero_routes, "desc", lambda v: v)
    monkeypatch.setattr(xero_routes, "threading", SimpleNamespace(Thread=_ThreadStub))
    monkeypatch.setattr(xero_routes, "time", SimpleNamespace(sleep=lambda *_a, **_kw: None))
    monkeypatch.setattr(xero_routes, "sync_all_accounts_and_contacts_background", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "login_user", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "flash", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "url_for", lambda endpoint, **_kw: f"/{endpoint}")
    monkeypatch.setattr(xero_routes, "redirect", lambda loc: SimpleNamespace(status_code=302, location=loc))
    monkeypatch.setattr(xero_routes, "upsert_user_token", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        xero_routes,
        "_onboarding_xero_return",
        lambda *_a, **_kw: SimpleNamespace(status_code=302, location="/onboarding"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_entity_resolved_by_id_in_state(monkeypatch):
    """When entity_id is embedded in the state param, the callback must assign
    the Xero org to that exact entity — not the globally latest one."""
    app = _build_app()
    session = _SessionStub()

    user_a = _make_user("user-a", "alice@example.com")
    entity_a = _make_entity("entity-a")
    entity_b = _make_entity("entity-b")  # more recently created (concurrent user)

    _patch_all(monkeypatch, user=user_a, by_id={"entity-a": entity_a, "entity-b": entity_b}, latest=entity_b, session=session)

    with app.test_request_context("/callback?state=entity_connect:entity-a&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity_a.xero_org_id == "xero-tenant-abc"
    assert entity_a.status == "connected"
    assert entity_a.xero_tenant_name == "Acme Ltd"
    assert entity_b.xero_org_id is None
    assert entity_b.status is None
    assert session.commit_calls == 1


def test_race_condition_two_concurrent_users(monkeypatch):
    """User A's callback fires while entity_b (User B's) is the most recently
    created entity. With the fix, entity_a — not entity_b — must be assigned."""
    app = _build_app()
    session = _SessionStub()

    user_a = _make_user("user-a", "alice@example.com")
    entity_a = _make_entity("entity-a")
    entity_b = _make_entity("entity-b")  # User B's entity, created after entity_a

    _patch_all(monkeypatch, user=user_a, by_id={"entity-a": entity_a, "entity-b": entity_b}, latest=entity_b, session=session)

    with app.test_request_context("/callback?state=entity_connect:entity-a&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity_a.xero_org_id == "xero-tenant-abc", (
        "entity_a must receive User A's Xero org, not be skipped due to the race"
    )
    assert entity_b.xero_org_id is None, (
        "entity_b must NOT be touched by User A's callback — race condition regression"
    )


def test_both_users_get_correct_entity_under_concurrent_onboarding(monkeypatch):
    """Fire both User A's and User B's callbacks in sequence (simulating the
    interleaved timing of a real race) and assert each entity ends up linked
    to the right Xero org.

    This is the scenario that was broken before the fix:
    - entity_b was created after entity_a (User B onboarded a fraction later).
    - The old code used order_by(created_at desc).first() — both callbacks
      would return entity_b, so entity_a would never be connected and
      entity_b would be overwritten with User A's Xero org on A's callback.
    - With the fix, each callback carries its own entity_id in state, so
      both entities are resolved independently and correctly.
    """
    app = _build_app()

    user_a = _make_user("user-a", "alice@example.com")
    user_b = _make_user("user-b", "bob@example.com")
    entity_a = _make_entity("entity-a")
    entity_b = _make_entity("entity-b")

    by_id = {"entity-a": entity_a, "entity-b": entity_b}

    # Both entities exist in the shared DB from the start.
    # entity_b is "latest" (created a moment after entity_a).

    # ---- User A's callback fires first ----
    session_a = _SessionStub()
    _patch_all(
        monkeypatch,
        user=user_a,
        by_id=by_id,
        latest=entity_b,   # <-- what the old code would have returned for both
        session=session_a,
    )
    monkeypatch.setattr(
        xero_routes,
        "requests",
        SimpleNamespace(
            get=lambda *_a, **_kw: SimpleNamespace(
                json=lambda: [{"tenantId": "xero-tenant-A", "tenantName": "Alice Corp"}]
            )
        ),
    )
    with app.test_request_context("/callback?state=entity_connect:entity-a&code=code-a"):
        xero_routes.xero_callback()

    # ---- User B's callback fires second ----
    session_b = _SessionStub()
    _patch_all(
        monkeypatch,
        user=user_b,
        by_id=by_id,
        latest=entity_b,
        session=session_b,
    )
    monkeypatch.setattr(
        xero_routes,
        "requests",
        SimpleNamespace(
            get=lambda *_a, **_kw: SimpleNamespace(
                json=lambda: [{"tenantId": "xero-tenant-B", "tenantName": "Bob Ltd"}]
            )
        ),
    )
    with app.test_request_context("/callback?state=entity_connect:entity-b&code=code-b"):
        xero_routes.xero_callback()

    # Each entity must be linked to its own Xero org, not the other user's.
    assert entity_a.xero_org_id == "xero-tenant-A", (
        "entity_a must be linked to Alice's Xero org — old code would have assigned xero-tenant-A to entity_b instead"
    )
    assert entity_a.xero_tenant_name == "Alice Corp"
    assert entity_b.xero_org_id == "xero-tenant-B", (
        "entity_b must be linked to Bob's Xero org"
    )
    assert entity_b.xero_tenant_name == "Bob Ltd"


def test_old_code_would_have_corrupted_data_regression_proof(monkeypatch):
    """Demonstrate what the old code did wrong, then show the fix prevents it.

    Old behaviour: both callbacks called order_by(created_at desc).first()
    which always returned entity_b (the latest). So:
    - User A's callback overwrote entity_b with xero-tenant-A.
    - User B's callback then also picked entity_b and overwrote it with xero-tenant-B.
    - entity_a was never connected.

    This test sets latest=entity_b for both callbacks (as before) and confirms
    that with the fix, entity_a is still correctly assigned to A.
    """
    app = _build_app()

    user_a = _make_user("user-a", "alice@example.com")
    entity_a = _make_entity("entity-a")
    entity_b = _make_entity("entity-b")
    by_id = {"entity-a": entity_a, "entity-b": entity_b}

    session_a = _SessionStub()
    _patch_all(monkeypatch, user=user_a, by_id=by_id, latest=entity_b, session=session_a)
    monkeypatch.setattr(
        xero_routes,
        "requests",
        SimpleNamespace(
            get=lambda *_a, **_kw: SimpleNamespace(
                json=lambda: [{"tenantId": "xero-tenant-A", "tenantName": "Alice Corp"}]
            )
        ),
    )

    with app.test_request_context("/callback?state=entity_connect:entity-a&code=code-a"):
        xero_routes.xero_callback()

    # entity_a must be connected, not entity_b (what the old code would have done)
    assert entity_a.xero_org_id == "xero-tenant-A", (
        "REGRESSION: old code would have assigned to entity_b (latest), leaving entity_a unconnected"
    )
    assert entity_b.xero_org_id is None, (
        "REGRESSION: old code would have wrongly written xero-tenant-A onto entity_b"
    )


def test_onboarding_state_variant(monkeypatch):
    """entity_connect_onboarding:<uuid> resolves the exact entity, but — unlike
    the non-onboarding flow — must NOT flip status to "connected". The entity
    stays "onboarding" so the resume flow keeps working; only
    /api/onboarding/finalize clears it."""
    app = _build_app()
    session = _SessionStub()

    user = _make_user("user-x", "user@example.com")
    entity = _make_entity("entity-x")
    entity.status = "onboarding"

    _patch_all(monkeypatch, user=user, by_id={"entity-x": entity}, latest=None, session=session, from_onboarding=True)

    with app.test_request_context("/callback?state=entity_connect_onboarding:entity-x&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity.xero_org_id == "xero-tenant-abc"
    # Mid-onboarding: Xero connects but status is preserved for resume.
    assert entity.status == "onboarding"


def test_legacy_fallback_no_entity_id_in_state(monkeypatch):
    """When no entity_id is in state (old flow, no entity_id param), the callback
    falls back to the latest-created entity so backward compat is preserved."""
    app = _build_app()
    session = _SessionStub()

    user = _make_user("user-legacy", "legacy@example.com")
    entity_latest = _make_entity("entity-latest")

    _patch_all(monkeypatch, user=user, by_id={}, latest=entity_latest, session=session)

    with app.test_request_context("/callback?state=entity_connect&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity_latest.xero_org_id == "xero-tenant-abc"
    assert entity_latest.status == "connected"


def test_entity_not_found_returns_error_redirect(monkeypatch):
    """If the entity_id in state has no matching entity, redirect to entity list
    without committing any data."""
    app = _build_app()
    session = _SessionStub()

    user = _make_user("user-a", "alice@example.com")

    _patch_all(monkeypatch, user=user, by_id={}, latest=None, session=session)

    with app.test_request_context("/callback?state=entity_connect:entity-a&code=test-code"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert "entity_list" in response.location or "entity.entity_list" in response.location
    assert session.commit_calls == 0, "no commit should happen when entity is not found"


def when_is_submit_entity_called():
    "submitting the entity into the db should be when "