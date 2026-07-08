"""Tests for logout + 30-minute idle auto-logout.

Covers:
  * /logout — clears the Flask-Login session and lands the user on home.
  * Idle backstop in hooks.before_request — a request after the idle window is
    redirected to /logout (HTML) or gets 401 session_expired (AJAX), while a
    request inside the window is let through.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from werkzeug.security import generate_password_hash


_schema_attached = False


@pytest.fixture
def db_session(app):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _make_user(db_session, *, id_token=None, username="idle.user"):
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email=f"{username}@test.com",
        username=username,
        first_name="Idle",
        last_name="User",
        password=generate_password_hash("password123"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
        id_token=id_token,
    )
    db_session.session.add(user)
    db_session.session.commit()
    return user


def _login(client, username="idle.user"):
    resp = client.post(
        "/login",
        data={"username": username, "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return resp


# --------------------------------------------------------------------------- #
# /logout route
# --------------------------------------------------------------------------- #

def test_logout_non_xero_user_redirects_home(app, db_session):
    """Password-only user: logout ends the Flask-Login session and lands on
    home, with no Xero hand-off."""
    from flask_login import current_user, login_user

    from blueprints.auth.routes.logout import logout
    from models.db import User

    user = _make_user(db_session, id_token=None)
    with app.test_request_context("/logout"):
        login_user(User.query.get(user.id))
        resp = logout()

        assert resp.status_code == 302
        assert urlparse(resp.location).path == "/"
        assert "xero.com" not in (resp.location or "")
        # logout_user() took effect within this request context.
        assert not current_user.is_authenticated


# --------------------------------------------------------------------------- #
# Idle auto-logout backstop (hooks.before_request)
# --------------------------------------------------------------------------- #

def test_login_resets_idle_window_despite_stale_last_activity(app, client, db_session):
    """Regression: a stale ``last_activity`` left in a reused session must NOT
    log the user out immediately after a fresh login. The user_logged_in signal
    resets the idle window at login time."""
    _make_user(db_session)

    # Simulate a stale idle marker left over from a previous session (cookie
    # reused). Without the reset-on-login fix this triggers an instant logout.
    idle_limit = app.config.get("IDLE_TIMEOUT_SECONDS", 1800)
    with client.session_transaction() as sess:
        sess["last_activity"] = time.time() - (idle_limit + 10_000)

    _login(client)

    resp = client.get("/index", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.location or ""
    assert "/logout" not in location  # not bounced straight back out
    assert resp.status_code != 401


def test_idle_timeout_redirects_to_logout(app, client, db_session):
    """A request after the idle window is bounced to /logout?reason=idle."""
    _make_user(db_session)
    _login(client)

    idle_limit = app.config.get("IDLE_TIMEOUT_SECONDS", 1800)
    with client.session_transaction() as sess:
        sess["last_activity"] = time.time() - (idle_limit + 100)

    resp = client.get("/index", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.location or ""
    assert "/logout" in location
    assert "reason=idle" in location


def test_idle_timeout_ajax_returns_401_session_expired(app, client, db_session):
    """AJAX requests after the idle window get a 401 with a session_expired code
    and a redirect hint to /logout (so the client can end the Xero session)."""
    _make_user(db_session)
    _login(client)

    idle_limit = app.config.get("IDLE_TIMEOUT_SECONDS", 1800)
    with client.session_transaction() as sess:
        sess["last_activity"] = time.time() - (idle_limit + 100)

    resp = client.get(
        "/index",
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["code"] == "session_expired"
    assert "/logout" in body["redirect"]


def test_request_within_idle_window_is_allowed(app, client, db_session):
    """Recent activity keeps the session alive — no idle logout."""
    _make_user(db_session)
    _login(client)

    with client.session_transaction() as sess:
        sess["last_activity"] = time.time() - 5  # just now

    resp = client.get("/index", follow_redirects=False)
    # /index with no entity_id redirects to /entity — the point is it is NOT
    # the idle-logout redirect and NOT a 401.
    assert resp.status_code == 302
    location = resp.location or ""
    assert "/logout" not in location
    assert resp.status_code != 401
