"""Tests for stale-flash draining in the Xero login (``auth``) callback branch.

Regression: a flash queued by a pre-login request (e.g. a stale deep link that
flashed "Hmm, I looked everywhere but couldn't find that one." then redirected) survives redirects because Flask
keeps flashes in the session until a rendered page consumes them. The dashboard
template (entity_dashboard_v2.html) is the one page that renders the ``danger``
category, so without draining, that old error toast pops up next to the
"Logged in successfully" toast after a fresh Xero login.

Fix: the ``auth`` branch of ``xero_callback()`` calls ``get_flashed_messages()``
right after ``login_user()`` to drain any leftover flashes before flashing its
own success message — the same defensive pattern used in auth/logout.py and
register.py.

These tests patch the login branch's collaborators (token exchange, user
lookup, db, login_user, url_for/redirect) but deliberately leave the real
``flash`` / ``get_flashed_messages`` / Flask ``session`` in place so the
drain behaviour is exercised for real.
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Flask, session

from blueprints.xero.routes import routes as xero_routes


# Flask stores flashes as (category, message) tuples in session["_flashes"].
SUCCESS = ("success", "You're signed in with Xero.")
STALE = ("danger", "Hmm, I looked everywhere but couldn't find that one.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def _make_user() -> SimpleNamespace:
    """A user row that resolve_user_by_email returns; the branch mutates these
    token attributes before committing."""
    return SimpleNamespace(
        id="user-1",
        xero_email=None,
        access_token=None,
        id_token=None,
        expires_in=None,
        refresh_token=None,
        token_created_at=None,
        xero_entity_id=None,
    )


def _patch_login_branch(monkeypatch, *, user) -> None:
    """Patch only the external collaborators of the ``auth`` branch, leaving
    flash / get_flashed_messages / session untouched."""
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
        xero_routes, "decode_jwt", lambda *_a, **_kw: {"email": "user@example.com"}
    )
    monkeypatch.setattr(xero_routes, "resolve_user_by_email", lambda *_a, **_kw: user)
    monkeypatch.setattr(
        xero_routes,
        "db",
        SimpleNamespace(session=SimpleNamespace(commit=lambda: None)),
    )
    monkeypatch.setattr(xero_routes, "upsert_user_token", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "login_user", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "url_for", lambda endpoint, **_kw: f"/{endpoint}")
    monkeypatch.setattr(
        xero_routes,
        "redirect",
        lambda loc: SimpleNamespace(status_code=302, location=loc),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stale_flash_drained_on_login(monkeypatch):
    """A leftover "Hmm, I looked everywhere but couldn't find that one." flash queued before login must NOT survive
    into the post-login render — only the login-success flash remains."""
    app = _build_app()
    user = _make_user()
    _patch_login_branch(monkeypatch, user=user)

    with app.test_request_context("/callback?state=auth&code=test-code"):
        # Simulate a flash carried in from a pre-login request via the cookie.
        session["_flashes"] = [STALE]

        response = xero_routes.xero_callback()

        assert response.status_code == 302
        remaining = session.get("_flashes", [])

    assert STALE not in remaining, "stale 'Hmm, I looked everywhere but couldn't find that one.' flash should be drained"
    assert remaining == [SUCCESS], "only the login-success flash should be queued"


def test_login_success_flash_present_without_stale(monkeypatch):
    """No leftovers: the login-success flash is queued exactly once (no
    regression from the drain call)."""
    app = _build_app()
    user = _make_user()
    _patch_login_branch(monkeypatch, user=user)

    with app.test_request_context("/callback?state=auth&code=test-code"):
        response = xero_routes.xero_callback()

        assert response.status_code == 302
        remaining = session.get("_flashes", [])

    assert remaining == [SUCCESS]


def test_drain_does_not_clobber_redirect_to_next_after_login(monkeypatch):
    """Draining happens, the success flash is queued, and the user is still
    redirected to next_after_login (the deep link they were headed to)."""
    app = _build_app()
    user = _make_user()
    _patch_login_branch(monkeypatch, user=user)

    with app.test_request_context("/callback?state=auth&code=test-code"):
        session["next_after_login"] = "/entity/abc/dashboard"
        session["_flashes"] = [STALE]

        response = xero_routes.xero_callback()

        remaining = session.get("_flashes", [])

    assert response.location == "/entity/abc/dashboard"
    assert remaining == [SUCCESS]


def test_login_user_called_before_drain(monkeypatch):
    """The drain must run after login_user so it clears the pre-login flashes,
    not before (ordering guard)."""
    app = _build_app()
    user = _make_user()
    _patch_login_branch(monkeypatch, user=user)

    calls = []
    monkeypatch.setattr(
        xero_routes, "login_user", lambda *_a, **_kw: calls.append("login_user")
    )
    real_get_flashed = xero_routes.get_flashed_messages

    def _tracking_get_flashed(*a, **kw):
        calls.append("get_flashed_messages")
        return real_get_flashed(*a, **kw)

    monkeypatch.setattr(xero_routes, "get_flashed_messages", _tracking_get_flashed)

    with app.test_request_context("/callback?state=auth&code=test-code"):
        session["_flashes"] = [STALE]
        xero_routes.xero_callback()

    assert calls == ["login_user", "get_flashed_messages"]
