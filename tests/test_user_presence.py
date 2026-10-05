"""Tests for sign-in presence — who Settings > Users lists.

The list shows the people currently signed in rather than everyone holding a
membership row, so the behaviour under test is a round trip: log in and you are
on it, log out and you are off it, log in again and you are back.

Covers:
  * user_logged_in stamps signed_in_at / last_seen_at.
  * user_logged_out clears signed_in_at but keeps last_seen_at as a record.
  * is_signed_in_clause() needs both columns — a logged-out user with a fresh
    last_seen_at, and a signed-in user gone stale, are each excluded.
  * The billing module's logout writes the same column Minty reads.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash



@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db

        import char_factories

        char_factories.truncate_all(app)  # TRUNCATE ... CASCADE on Postgres


@pytest.fixture
def client(app):
    """A client whose requests each start with a fresh Flask-Login cache.

    The ``db_session`` fixture above holds ONE app context open for the whole test, so
    every request shares its ``g`` - and Flask-Login caches the loaded user there. In
    production each request has its own ``g``; here the user cached by the login request
    would be read again by the next one after teardown detached it (DetachedInstanceError).
    """
    from flask import g
    from flask.testing import FlaskClient

    class FreshLoginCacheClient(FlaskClient):
        def open(self, *args, **kwargs):
            g.pop("_login_user", None)
            return super().open(*args, **kwargs)

    return FreshLoginCacheClient(app, app.response_class)


def _make_user(db_session, username="presence.user"):
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email=f"{username}@test.com",
        username=username,
        first_name="Presence",
        last_name="User",
        password=generate_password_hash("password123"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db_session.session.add(user)
    db_session.session.commit()
    return user


def _reload(db_session, user_id):
    from models.db import User

    db_session.session.expire_all()
    return db_session.session.get(User, user_id)


def _signed_in_ids(db_session):
    from models.db import User
    from services.user_presence import is_signed_in_clause

    rows = db_session.session.query(User.id).filter(is_signed_in_clause()).all()
    return {row[0] for row in rows}


# --------------------------------------------------------------------------- #
# Login / logout round trip
# --------------------------------------------------------------------------- #

def test_login_puts_user_on_the_signed_in_list(app, client, db_session):
    # The id is read before any request runs: teardown_request calls
    # db.session.remove(), which detaches this instance and makes `user.id` raise.
    user_id = _make_user(db_session).id
    assert user_id not in _signed_in_ids(db_session)

    resp = client.post(
        "/login",
        data={"username": "presence.user", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    stored = _reload(db_session, user_id)
    assert stored.signed_in_at is not None
    assert stored.last_seen_at is not None
    assert user_id in _signed_in_ids(db_session)


def test_logout_takes_user_off_the_signed_in_list(app, client, db_session):
    user_id = _make_user(db_session).id
    client.post(
        "/login",
        data={"username": "presence.user", "password": "password123"},
        follow_redirects=False,
    )
    assert user_id in _signed_in_ids(db_session)

    client.get("/logout", follow_redirects=False)

    stored = _reload(db_session, user_id)
    assert stored.signed_in_at is None
    # Kept: it is the record of when they were last around, and is inert for
    # presence without signed_in_at beside it.
    assert stored.last_seen_at is not None
    assert user_id not in _signed_in_ids(db_session)


def test_logging_back_in_returns_user_to_the_list(app, client, db_session):
    user_id = _make_user(db_session).id
    creds = {"username": "presence.user", "password": "password123"}

    client.post("/login", data=creds, follow_redirects=False)
    client.get("/logout", follow_redirects=False)
    assert user_id not in _signed_in_ids(db_session)

    client.post("/login", data=creds, follow_redirects=False)
    assert user_id in _signed_in_ids(db_session)


# --------------------------------------------------------------------------- #
# The clause needs both columns
# --------------------------------------------------------------------------- #

def test_stale_last_seen_drops_user_off_the_list(app, db_session):
    """A browser closed without logging out ages out of the presence window."""
    from services.user_presence import mark_signed_in, now, presence_window_seconds

    user = _make_user(db_session, username="stale.user")
    with app.test_request_context("/"):
        mark_signed_in(user)
        assert user.id in _signed_in_ids(db_session)

        stale = now() - timedelta(seconds=presence_window_seconds() + 60)
        stored = _reload(db_session, user.id)
        stored.last_seen_at = stale
        db_session.session.commit()

        assert user.id not in _signed_in_ids(db_session)


def test_last_seen_alone_does_not_list_anyone(app, db_session):
    """Presence is intent AND recency — a fresh last_seen_at is not enough."""
    from services.user_presence import now

    user = _make_user(db_session, username="ghost.user")
    with app.test_request_context("/"):
        stored = _reload(db_session, user.id)
        stored.last_seen_at = now()
        stored.signed_in_at = None
        db_session.session.commit()

        assert user.id not in _signed_in_ids(db_session)


# --------------------------------------------------------------------------- #
# Adopting a session that predates the feature
# --------------------------------------------------------------------------- #

def test_refresh_adopts_an_authenticated_session_with_no_sign_in_time(app, db_session):
    """Sessions open when this shipped have a NULL signed_in_at and will never see
    a login signal. A request from one counts as being signed in."""
    from services.user_presence import refresh_presence

    user = _make_user(db_session, username="adopted.user")
    assert user.id not in _signed_in_ids(db_session)

    with app.test_request_context("/"):
        refresh_presence(user)

        stored = _reload(db_session, user.id)
        assert stored.signed_in_at is not None
        assert user.id in _signed_in_ids(db_session)


def test_refresh_keeps_the_original_sign_in_time(app, db_session):
    """COALESCE, not overwrite: signed_in_at means when they signed in, not when
    they last clicked something."""
    from services.user_presence import mark_signed_in, refresh_presence

    user = _make_user(db_session, username="steady.user")
    with app.test_request_context("/"):
        mark_signed_in(user)
        original = _reload(db_session, user.id).signed_in_at

        refresh_presence(user)

        stored = _reload(db_session, user.id)
        assert stored.signed_in_at == original


def test_a_signed_out_user_is_not_adopted_back_onto_the_list(app, db_session):
    """The guard rail behind adoption, and the reason it is safe.

    Signing out of the billing module clears signed_in_at while the Minty session
    stays alive — that is what lets Log out return the browser to Minty's entity
    list instead of the login page. Every page they load afterwards is an
    authenticated request, so refresh_presence must NOT read the blank as
    never-stamped and undo the sign-out.
    """
    from services.user_presence import mark_signed_in, mark_signed_out, refresh_presence

    user = _make_user(db_session, username="stayed.out")
    with app.test_request_context("/"):
        mark_signed_in(user)
        mark_signed_out(user)

        # Browsing on, still authenticated.
        for _ in range(3):
            refresh_presence(user)

        stored = _reload(db_session, user.id)
        assert stored.signed_in_at is None
        # Still being tracked as around — just not listed.
        assert stored.last_seen_at is not None
        assert user.id not in _signed_in_ids(db_session)


# The Users tab's signed-in poll (``/entity/settings/users/<id>/presence``) and its Jinja
# partials went with Flask's Users page in phase 2 (2026-10-05); it was switched off before that.
