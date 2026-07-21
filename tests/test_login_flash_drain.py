"""Tests for stale-flash draining in the password-login (``auth.login``) path.

Regression: a flash queued by a pre-login request (e.g. a stale deep link that
flashed "Entity not found" then redirected) survives redirects because Flask
keeps flashes in the session until a rendered page consumes them. The dashboard
/ layout templates render the ``danger`` category, so without draining, that old
error toast pops up next to the "Login Successful!" toast after a fresh login.

Fix: ``login()`` calls ``get_flashed_messages()`` right after ``login_user()``
to drain any leftover flashes before flashing its own success message — the same
defensive pattern used in the Xero callback, auth/logout.py and register.py.

These tests patch the view's collaborators (form, user lookup, password check,
login_user, url_for/redirect, current_user) but deliberately leave the real
``flash`` / ``get_flashed_messages`` / Flask ``session`` in place so the drain
behaviour is exercised for real.
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Flask, session

from blueprints.auth.routes import login as login_route


# Flask stores flashes as (category, message) tuples in session["_flashes"].
SUCCESS = ("success", "Login Successful!")
STALE = ("danger", "Entity not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def _make_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="user-1",
        username="alice",
        approved=True,
        password="hashed",
        system_role="user",
    )


def _patch_login_view(monkeypatch, *, user) -> None:
    """Patch only the external collaborators of ``login()``, leaving
    flash / get_flashed_messages / session untouched."""
    # A form that validates as a submitted POST with the expected credentials.
    fake_form = SimpleNamespace(
        username=SimpleNamespace(data="alice"),
        password=SimpleNamespace(data="pw"),
        validate_on_submit=lambda: True,
    )
    monkeypatch.setattr(login_route, "LoginForm", lambda *a, **kw: fake_form)

    # User.query.filter_by(username=...).first() -> user
    query = SimpleNamespace(
        filter_by=lambda **_kw: SimpleNamespace(first=lambda: user)
    )
    monkeypatch.setattr(
        login_route,
        "User",
        SimpleNamespace(query=query, SYSTEM_ROLE_SUPERUSER="superuser"),
    )

    monkeypatch.setattr(login_route, "check_password_hash", lambda *_a, **_kw: True)
    monkeypatch.setattr(login_route, "login_user", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        login_route, "current_user", SimpleNamespace(is_authenticated=False)
    )
    monkeypatch.setattr(login_route, "url_for", lambda endpoint, **_kw: f"/{endpoint}")
    monkeypatch.setattr(
        login_route,
        "redirect",
        lambda loc: SimpleNamespace(status_code=302, location=loc),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stale_flash_drained_on_login(monkeypatch):
    """A leftover "Entity not found" flash queued before login must NOT survive
    into the post-login render — only the login-success flash remains."""
    app = _build_app()
    user = _make_user()
    _patch_login_view(monkeypatch, user=user)

    with app.test_request_context("/login", method="POST"):
        # Simulate a flash carried in from a pre-login request via the cookie.
        session["_flashes"] = [STALE]

        response = login_route.login()

        assert response.status_code == 302
        remaining = session.get("_flashes", [])

    assert STALE not in remaining, "stale 'Entity not found' flash should be drained"
    assert remaining == [SUCCESS], "only the login-success flash should be queued"


def test_login_success_flash_present_without_stale(monkeypatch):
    """No leftovers: the login-success flash is queued exactly once (no
    regression from the drain call)."""
    app = _build_app()
    user = _make_user()
    _patch_login_view(monkeypatch, user=user)

    with app.test_request_context("/login", method="POST"):
        response = login_route.login()

        assert response.status_code == 302
        remaining = session.get("_flashes", [])

    assert remaining == [SUCCESS]


def test_login_user_called_before_drain(monkeypatch):
    """The drain must run after login_user so it clears the pre-login flashes,
    not before (ordering guard)."""
    app = _build_app()
    user = _make_user()
    _patch_login_view(monkeypatch, user=user)

    calls = []
    monkeypatch.setattr(
        login_route, "login_user", lambda *_a, **_kw: calls.append("login_user")
    )
    real_get_flashed = login_route.get_flashed_messages

    def _tracking_get_flashed(*a, **kw):
        calls.append("get_flashed_messages")
        return real_get_flashed(*a, **kw)

    monkeypatch.setattr(login_route, "get_flashed_messages", _tracking_get_flashed)

    with app.test_request_context("/login", method="POST"):
        session["_flashes"] = [STALE]
        login_route.login()

    assert calls == ["login_user", "get_flashed_messages"]
