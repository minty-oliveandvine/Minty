"""The expired-session hook must never redirect the login page to itself.

``before_request_middleware`` (pettycash/core/hooks.py) catches a session cookie
that still names a user Flask-Login can no longer resolve, and sends the person
back to ``auth.home`` to sign in again. ``auth.home`` is ``/``, and the hook is
an app-wide ``before_request``, so it runs on ``/`` as well: without an
exemption, ``/`` answers its own request with a 302 to ``/``, forever.

That is not a logged-out user. That is a locked-out browser — every URL on the
domain gives ERR_TOO_MANY_REDIRECTS, ``/logout`` included, and the only way out
is clearing site data by hand. These two tests are the difference between the
two states, and are worth keeping green above anything else in this file.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def db_session(app):
    """These requests touch the user table through load_user; empty it afterwards."""
    from models.db import db

    yield db

    with app.app_context():
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


@pytest.fixture
def ghost(client, db_session):
    """A cookie naming a user that no longer resolves — a row deleted straight
    out of the database, or a session carried across environments."""
    with client.session_transaction() as session:
        session["_user_id"] = str(uuid.uuid4())
        session["_fresh"] = True
    return client


# --------------------------------------------------------------------------
# LOCK-OUT SAFETY
# --------------------------------------------------------------------------

def test_the_login_page_does_not_redirect_to_itself(ghost):
    """The whole bug in one line. ``auth.home`` is the hook's redirect target
    AND is guarded by the hook, so a redirect here has no exit."""
    response = ghost.get("/", follow_redirects=False)

    assert response.status_code == 200, (
        "/ redirected instead of rendering — the login page is redirecting to "
        "itself, which is ERR_TOO_MANY_REDIRECTS in a browser"
    )


def test_a_dead_session_is_cleared_not_just_redirected(ghost):
    """Redirecting without clearing leaves the next request in the same branch.

    This is what made the loop terminal rather than a one-off bounce: the hook
    decided the session was unusable and then left it in the cookie.
    """
    ghost.get("/entity", follow_redirects=False)

    with ghost.session_transaction() as session:
        assert "_user_id" not in session, (
            "the unusable identity survived the request, so every following "
            "request re-enters the expired-session branch"
        )


def test_an_invite_link_on_a_dead_session_terminates(ghost):
    """End-to-end shape of the original report: tapping the invite link on the
    phone that still holds the stale cookie. Follow the chain and assert it
    reaches something that is not another redirect."""
    response = ghost.get(
        "/invitation/accept/some-token", follow_redirects=True
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------
# The hook still does its job
# --------------------------------------------------------------------------

def test_a_real_page_still_bounces_to_login(ghost):
    """Clearing the session must not turn the guard off: a page request on a
    dead session still goes to the login page, it just gets there once."""
    response = ghost.get("/entity", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_a_json_caller_still_gets_401_not_a_redirect(ghost):
    """Background requests need a code they can act on — a redirect sent to
    fetch() fails silently and the user sees nothing happen."""
    response = ghost.get(
        "/minty/api/invitation/some-entity/pending",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "session_expired"


def test_a_live_session_is_untouched(client, db_session, app):
    """The exemption keys on the endpoint, not on being logged out — a signed-in
    user must still reach / and be forwarded to their companies."""
    from models.db import User, db

    with app.app_context():
        uid = str(uuid.uuid4())
        db.session.add(
            User(
                id=uid,
                username=f"live-{uuid.uuid4().hex[:8]}@test.com",
                email=f"live-{uuid.uuid4().hex[:8]}@test.com",
                first_name="Still",
                last_name="Here",
                password="x",
                approved=True,
            )
        )
        db.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = uid
        session["_fresh"] = True

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert "/entity" in response.headers["Location"]

    with client.session_transaction() as session:
        assert session["_user_id"] == uid
