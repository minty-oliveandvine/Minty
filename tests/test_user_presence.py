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


def test_the_users_tab_poll_does_not_count_as_activity(app, db_session):
    """A tab left open on Settings > Users polls every 20 seconds all night. If
    that counted as the person being around, they would never age off the list —
    which is the one thing last_seen_at exists to prevent. The endpoint is listed
    as presence-inert in hooks; this pins that the list still has it."""
    from pettycash.core.hooks import PRESENCE_INERT_ENDPOINTS

    assert "entity.entity_settings_users_presence" in PRESENCE_INERT_ENDPOINTS


def test_the_poll_endpoint_exists_under_that_name(app):
    """Guards the string above against a rename — a typo there fails silently, by
    quietly refreshing presence on every poll forever."""
    assert "entity.entity_settings_users_presence" in app.view_functions


def test_the_page_can_build_the_poll_url(app):
    """The Users tab builds this with url_for. A wrong endpoint name here does not
    fail quietly — it 500s the whole page — so it is worth one line."""
    from flask import url_for

    with app.test_request_context("/"):
        url = url_for("entity.entity_settings_users_presence", org_id="abc-123")
    assert url.endswith("/entity/settings/users/abc-123/presence")


def test_the_roster_renders_members_and_its_one_empty_state(app, db_session):
    """The upper section: everyone in the company, with what may be done to them.

    Empty here can only mean nobody has been invited — the two-way empty state was
    needed when this list showed who was signed in, where empty also meant
    "everyone is out". That question now has its own section.
    """
    from flask import render_template

    user = _make_user(db_session, username="roster.user")
    with app.test_request_context("/"):
        rows = render_template(
            "entity/settings_users_rows.html",
            users=[(user, "admin")],
            is_view_only=False,
        )
        assert "roster.user" in rows
        assert 'data-role="admin"' in rows

        empty = render_template(
            "entity/settings_users_rows.html", users=[], is_view_only=False
        )
        assert "inviting your first user" in empty


def test_the_signed_in_fragment_stands_up_on_its_own(app, db_session):
    """The lower section is what the poll re-renders, so it has to render with
    nothing but ``signed_in`` — the poll passes no roster values at all."""
    from flask import render_template

    user = _make_user(db_session, username="present.user")
    with app.test_request_context("/"):
        listed = render_template(
            "entity/settings_users_signed_in.html", signed_in=[(user, "admin")]
        )
        assert "present.user" in listed
        # Read-only by design: the actions live on the roster above, so there is
        # exactly one place to remove a person from.
        assert "openDeleteUserModal" not in listed
        assert "openEditUserModal" not in listed

        empty = render_template(
            "entity/settings_users_signed_in.html", signed_in=[]
        )
        assert "No one's signed in at the moment." in empty


def test_presence_is_a_fact_about_the_person_not_the_company(app, db_session):
    """Schema item 14 (docs/schema/01_schema_rebased.sql): ``user.current_entity_id`` is gone,
    so Settings > Users answers "who is signed in to Minty" - a person who opened one company
    is listed in every company they belong to. This test pins that decision and its cost;
    it replaces the per-company assertions that held while the column existed."""
    from services.user_presence import is_signed_in_clause, resume_presence
    from models.db import User

    user = _make_user(db_session, username="twoco.user")
    with app.test_request_context("/"):
        resume_presence(user, "entity-one")

        def present_in(entity_id):
            rows = (
                db_session.session.query(User.id)
                .filter(is_signed_in_clause(entity_id))
                .all()
            )
            return user.id in {r[0] for r in rows}

        assert present_in("entity-one") is True
        assert present_in("entity-two") is True, "item 14: presence is not narrowed by company"

        resume_presence(user, "entity-two")
        assert present_in("entity-one") is True
        assert present_in("entity-two") is True


def test_signing_in_lists_you_everywhere_you_belong(app, db_session):
    """A fresh session is signed in to Minty; with no per-company record there is nothing
    for it to inherit or to shed."""
    from services.user_presence import (is_signed_in_clause, mark_signed_in,
                                        resume_presence)
    from models.db import User

    user = _make_user(db_session, username="fresh.user")
    with app.test_request_context("/"):
        resume_presence(user, "entity-one")
        mark_signed_in(user)  # a new session begins

        rows = (
            db_session.session.query(User.id)
            .filter(is_signed_in_clause("entity-one"))
            .all()
        )
        assert user.id in {r[0] for r in rows}
        assert _reload(db_session, user.id).signed_in_at is not None


def test_a_request_about_no_company_leaves_the_recorded_one_alone(app, db_session):
    """Most pages name no entity — the profile, the entity list, plain API calls.
    Treating each as "left the company" would flicker people off their colleagues'
    lists all day. Leaving is an explicit act."""
    from services.user_presence import (is_signed_in_clause, refresh_presence,
                                        resume_presence)
    from models.db import User

    user = _make_user(db_session, username="wanderer.user")
    with app.test_request_context("/"):
        resume_presence(user, "entity-one")
        refresh_presence(user)  # a page with no entity in its URL

        rows = (
            db_session.session.query(User.id)
            .filter(is_signed_in_clause("entity-one"))
            .all()
        )
        assert user.id in {r[0] for r in rows}


def test_opening_an_entity_puts_a_signed_out_user_back_on_the_list(app, db_session):
    """The reported bug: Log out on the billing profile, then go back into the
    company, and you stayed invisible.

    Log out leaves the Minty session alive by design, so re-entering fires no
    login signal and refresh_presence correctly refuses to revive a sign-out. That
    left no way back onto the list at all. Opening an entity is the deliberate act
    that means "I'm here", so it resumes presence.
    """
    from services.user_presence import (mark_signed_in, mark_signed_out,
                                        refresh_presence, resume_presence)

    user = _make_user(db_session, username="returning.user")
    with app.test_request_context("/"):
        mark_signed_in(user)
        mark_signed_out(user)
        # Landing on the entity list after logging out — still off the list.
        refresh_presence(user)
        assert user.id not in _signed_in_ids(db_session)

        # Clicking into a company.
        resume_presence(user, "entity-one")
        assert user.id in _signed_in_ids(db_session)


def test_opening_an_entity_keeps_an_existing_sign_in_time(app, db_session):
    """Switching company must not reset when you signed in."""
    from services.user_presence import mark_signed_in, resume_presence

    user = _make_user(db_session, username="switcher.user")
    with app.test_request_context("/"):
        mark_signed_in(user)
        original = _reload(db_session, user.id).signed_in_at

        resume_presence(user, "entity-one")

        assert _reload(db_session, user.id).signed_in_at == original


def test_leaving_a_company_keeps_the_session_but_drops_presence(app, client, db_session):
    """Log out from inside a company means "leave the company", not "leave Minty".

    Two steps out, one word: pressing it in a company lands you on the entity list
    still signed in, and pressing it again there ends the session for real. So this
    route must NOT log the user out — but it must take them off the company's
    signed-in list, because they are no longer there.
    """
    from blueprints.legal.services.consent import record_consent

    user_id = _make_user(db_session, username="leaver.user").id
    # someone inside a company has agreed to the Terms; without this the acceptance gate
    # answers /leave-entity itself (a redirect to the entity list) and the view never runs
    record_consent(user_id, source="gate")
    db_session.session.commit()
    client.post(
        "/login",
        data={"username": "leaver.user", "password": "password123"},
        follow_redirects=False,
    )
    assert user_id in _signed_in_ids(db_session)

    resp = client.get("/leave-entity", follow_redirects=False)

    assert resp.status_code == 302
    assert "/entity" in (resp.location or "")
    assert user_id not in _signed_in_ids(db_session)

    # Still signed in: an authenticated request is not bounced to login, and making
    # it does NOT re-adopt them onto the list (mark_signed_out stamps last_seen_at
    # for exactly this reason — see refresh_presence).
    follow = client.get("/index", follow_redirects=False)
    assert follow.status_code != 401
    assert "/login" not in (follow.location or "")
    assert user_id not in _signed_in_ids(db_session)


def test_leaving_a_company_is_not_the_same_route_as_logging_out(app):
    """Both exist, and they are different doors. Collapsing them is the bug this
    pair was built to fix — one word, two steps, two endpoints."""
    assert "auth.leave_entity" in app.view_functions
    assert "auth.logout" in app.view_functions


def test_logging_in_again_after_a_sign_out_relists(app, db_session):
    """The other half: a real login still puts them back, blank-vs-set aside."""
    from services.user_presence import mark_signed_in, mark_signed_out, refresh_presence

    user = _make_user(db_session, username="returned.user")
    with app.test_request_context("/"):
        mark_signed_in(user)
        mark_signed_out(user)
        refresh_presence(user)
        assert user.id not in _signed_in_ids(db_session)

        mark_signed_in(user)
        assert user.id in _signed_in_ids(db_session)
