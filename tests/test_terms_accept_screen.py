"""Phase 3 of the Terms of Use work: the blocking accept screen.

Two properties matter more than the rest and are tested first:

  * a person who refuses can still log out — otherwise the screen is a trap;
  * the server, not the tick box, decides whether agreement happened.
"""

from __future__ import annotations

import uuid

import pytest

from legal import registry

_schema_attached = False


@pytest.fixture
def db_session(app, tmp_path_factory):
    """See tests/test_terms_consent.py for why this attaches a file, not
    ``':memory:'``."""
    global _schema_attached
    from sqlalchemy import event

    from models.db import db

    with app.app_context():
        engine = db.engine
        if not _schema_attached:
            schema_path = str(
                tmp_path_factory.mktemp("schema") / "pettycashv3.sqlite"
            ).replace("\\", "/")

            @event.listens_for(engine, "connect")
            def _attach_schema(dbapi_connection, _record):  # noqa: ANN001
                try:
                    dbapi_connection.execute(
                        f"ATTACH DATABASE '{schema_path}' AS pettycashv3"
                    )
                except Exception:
                    pass

            engine.dispose()
            _schema_attached = True

        db.create_all()

    # Yield OUTSIDE the app context. Holding one open across client requests
    # makes every request share a single session: the first request's commit
    # then expunges `current_user`, and the second request fails on a detached
    # instance. Production pushes a fresh context per request; so does this.
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
def user_id(app, db_session):
    """Returns the id, not the ORM object.

    ``client.session_transaction()`` pushes and pops its own app context, and
    Flask-SQLAlchemy removes the session on teardown — which detaches any
    instance held across it. A plain string sidesteps that entirely.
    """
    from models.db import User

    with app.app_context():
        row = User(
            id=str(uuid.uuid4()),
            username=f"gate-{uuid.uuid4().hex[:8]}@test.com",
            email=f"gate-{uuid.uuid4().hex[:8]}@test.com",
            first_name="Gate",
            last_name="User",
            password="x",
            approved=True,
        )
        db_session.session.add(row)
        db_session.session.commit()
        return row.id


@pytest.fixture
def logged_in(client, user_id):
    """A session carrying this user, without going through a login route."""
    with client.session_transaction() as session:
        session["_user_id"] = user_id
        session["_fresh"] = True
    return client


def _in_app(app, fn):
    """Run a bit of ORM work in its own app context.

    Needed because the db_session fixture deliberately does not hold one open
    — see its docstring.
    """
    with app.app_context():
        return fn()


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------

def test_accept_page_requires_a_login(client, db_session):
    response = client.get("/legal/accept", follow_redirects=False)
    assert response.status_code in (301, 302)


def test_accept_page_shows_the_terms_and_a_logout_link(logged_in, db_session):
    """The log-out link is not decoration.

    Someone who refuses to agree must always be able to leave. Without it this
    screen is a trap, and Phase 4's gate would make it inescapable.
    """
    body = logged_in.get("/legal/accept").get_data(as_text=True)
    assert "Accept &amp; Continue" in body
    # "Cancel" IS the way out — it points at logout. The label has changed twice
    # with the redesigns; what must never change is that the link is there.
    assert "/logout" in body
    assert "Cancel" in body


def test_the_tick_box_is_gated_on_reading_to_the_end(logged_in, db_session):
    """The box unlocks only once the document has been scrolled to its end.

    The lock itself is client-side — the server cannot tell whether anyone
    scrolled, and does not try to. What this asserts is that the affordance is
    present and wired: the hint the box points at via aria-describedby, and the
    two guards that stop the pattern locking people out (a document shorter
    than its box, and the pixel tolerance at the bottom).
    """
    body = logged_in.get("/legal/accept").get_data(as_text=True)

    # Screen-reader only — deliberately not shown on screen. Without it a blind
    # user meets a disabled checkbox with no stated reason.
    assert 'id="accept-scroll-hint"' in body
    assert 'class="tc-sr-only"' in body
    assert 'aria-describedby="accept-scroll-hint"' in body
    # Rendered enabled, disabled by the script: a script that fails to load
    # must leave the box usable rather than trap everyone behind it.
    assert "disabled" not in body.split('id="accept-box"')[1].split(">")[0]
    assert "scrollHeight <= doc.clientHeight" in body
    assert "<= 4" in body


def test_accept_page_checkbox_starts_unticked(logged_in, db_session):
    """A pre-ticked box is not agreement — the person must do something."""
    body = logged_in.get("/legal/accept").get_data(as_text=True)
    assert 'id="accept-box"' in body
    assert "checked" not in body.split('id="accept-box"')[1].split(">")[0]


def test_accept_page_redirects_when_already_agreed(app, logged_in, db_session, user_id):
    from blueprints.legal.services.consent import record_consent

    def _grant():
        record_consent(user_id, source="gate")
        db_session.session.commit()

    _in_app(app, _grant)

    response = logged_in.get("/legal/accept", follow_redirects=False)
    assert response.status_code == 302
    assert "/legal/accept" not in response.headers["Location"]


@pytest.fixture
def rewritten_terms():
    """Publish a second version, as a real Terms revamp would.

    Injects a `beta-2` document into the registry and points
    CURRENT_TERMS_VERSION at it, then puts everything back. This is the path
    the first genuine rewrite will take, so it is worth exercising rather than
    assuming.
    """
    from dataclasses import replace

    original_version = registry.CURRENT_TERMS_VERSION
    beta_1 = registry.get_document(registry.TERMS, "beta-1")
    beta_2 = replace(beta_1, version="beta-2", sha256="b" * 64)

    registry._DOCUMENTS[(registry.TERMS, "beta-2")] = beta_2
    registry.CURRENT_TERMS_VERSION = "beta-2"
    try:
        yield "beta-2"
    finally:
        registry.CURRENT_TERMS_VERSION = original_version
        registry._DOCUMENTS.pop((registry.TERMS, "beta-2"), None)


def test_a_returning_user_sees_the_what_changed_note(
    app, logged_in, db_session, user_id, rewritten_terms
):
    """Never-agreed and out-of-date are both blocked, but they read very
    differently to the person: one is being asked again, the other for the
    first time."""
    from blueprints.legal.services.consent import record_consent

    def _grant():
        record_consent(user_id, source="signup_otp", version="beta-1")
        db_session.session.commit()

    _in_app(app, _grant)

    body = logged_in.get("/legal/accept").get_data(as_text=True)

    assert "We have made a meaningful change" in body
    assert "You previously agreed to version" in body
    # The superseded version stays reachable, so they can see what they had
    # agreed to before.
    assert "/legal/terms/beta-1" in body


def test_a_first_time_user_does_not_see_the_what_changed_note(
    app, logged_in, db_session, user_id
):
    body = logged_in.get("/legal/accept").get_data(as_text=True)

    assert "We have made a meaningful change" not in body
    assert "You previously agreed to version" not in body


def test_an_out_of_date_user_is_asked_again(app, logged_in, db_session, user_id,
                                            rewritten_terms):
    """The whole point of versioning: agreeing to beta-1 must not satisfy beta-2."""
    from blueprints.legal.services.consent import has_consent, record_consent

    def _grant():
        record_consent(user_id, source="signup_otp", version="beta-1")
        db_session.session.commit()

    _in_app(app, _grant)

    # Not redirected away — they are shown the screen again.
    assert logged_in.get("/legal/accept", follow_redirects=False).status_code == 200
    assert _in_app(app, lambda: has_consent(user_id, version="beta-2")) is False

    response = logged_in.post(
        "/legal/accept", json={"accepted": True, "terms_version": "beta-2"}
    )
    assert response.status_code == 200
    assert _in_app(app, lambda: has_consent(user_id, version="beta-2")) is True
    # The earlier agreement is untouched — the table is an append-only trail,
    # not a current-value store.
    assert _in_app(app, lambda: has_consent(user_id, version="beta-1")) is True


# --------------------------------------------------------------------------
# Submitting
# --------------------------------------------------------------------------

def test_submitting_records_the_consent(app, logged_in, db_session, user_id):
    from blueprints.legal.services.consent import has_consent

    response = logged_in.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert _in_app(app, lambda: has_consent(user_id)) is True


def test_an_unticked_box_is_refused_by_the_server(app, logged_in, db_session, user_id):
    """The tick box is a convenience; THIS is the check.

    A client can send whatever it likes, so a consent record must only exist
    when acceptance genuinely arrived.
    """
    from blueprints.legal.services.consent import has_consent

    response = logged_in.post(
        "/legal/accept",
        json={"accepted": False, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    assert response.status_code == 400
    assert _in_app(app, lambda: has_consent(user_id)) is False


def test_a_missing_accepted_field_is_refused(app, logged_in, db_session, user_id):
    from blueprints.legal.services.consent import has_consent

    response = logged_in.post(
        "/legal/accept", json={"terms_version": registry.CURRENT_TERMS_VERSION}
    )
    assert response.status_code == 400
    assert _in_app(app, lambda: has_consent(user_id)) is False


def test_a_stale_version_is_rejected_with_409(app, logged_in, db_session, user_id):
    """Someone left the page open while we published new Terms.

    Recording now would file an accurate record of the wrong wording.
    """
    from blueprints.legal.services.consent import has_consent

    response = logged_in.post(
        "/legal/accept", json={"accepted": True, "terms_version": "beta-0"}
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "version_changed"
    assert body["terms_version"] == registry.CURRENT_TERMS_VERSION
    assert _in_app(app, lambda: has_consent(user_id)) is False


def test_submitting_requires_a_login(client, db_session):
    response = client.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302, 401)


def test_accepting_twice_is_harmless(app, logged_in, db_session, user_id):
    from blueprints.legal.models.terms_consent import TermsConsent

    payload = {"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION}
    assert logged_in.post("/legal/accept", json=payload).status_code == 200
    assert logged_in.post("/legal/accept", json=payload).status_code == 200
    assert _in_app(app, lambda: TermsConsent.query.filter_by(user_id=user_id).count()) == 1


# --------------------------------------------------------------------------
# Where they land afterwards
# --------------------------------------------------------------------------

def test_accepting_returns_to_the_remembered_page(logged_in, db_session, user_id):
    from blueprints.legal.services.gate import TERMS_NEXT_SESSION_KEY

    with logged_in.session_transaction() as session:
        session[TERMS_NEXT_SESSION_KEY] = "/report/history"

    response = logged_in.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    assert response.get_json()["redirect_url"] == "/report/history"


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "/../../etc",
        "javascript:alert(1)",
        "/\\evil.example",
    ],
)
def test_a_hostile_destination_cannot_steer_the_return(
    logged_in, db_session, user_id, hostile
):
    """A redirect that can be steered off-site turns this screen into a
    phishing hop — someone lands on 'Minty', agrees, and is bounced somewhere
    else entirely."""
    from blueprints.legal.services.gate import TERMS_NEXT_SESSION_KEY

    with logged_in.session_transaction() as session:
        session[TERMS_NEXT_SESSION_KEY] = hostile

    response = logged_in.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    redirect_url = response.get_json()["redirect_url"]
    assert redirect_url != hostile
    assert redirect_url.startswith("/")
    assert not redirect_url.startswith("//")


# --------------------------------------------------------------------------
# The session cache
# --------------------------------------------------------------------------

def test_accepting_caches_the_version_not_a_flag(logged_in, db_session, user_id):
    """Storing the version is what makes a Terms revamp self-clearing.

    A boolean would leave every existing session believing it had agreed to
    whatever came next.
    """
    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY

    logged_in.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    with logged_in.session_transaction() as session:
        assert session[TERMS_OK_SESSION_KEY] == registry.CURRENT_TERMS_VERSION


def test_session_cache_stops_matching_when_the_version_moves(app, db_session):
    from blueprints.legal.services.gate import (mark_session_agreed,
                                                session_agreed_to_current)

    with app.test_request_context("/"):
        mark_session_agreed("beta-1")
        live = registry.CURRENT_TERMS_VERSION
        registry.CURRENT_TERMS_VERSION = "beta-1"
        try:
            assert session_agreed_to_current() is True
            registry.CURRENT_TERMS_VERSION = "beta-2"
            assert session_agreed_to_current() is False
        finally:
            registry.CURRENT_TERMS_VERSION = live


def test_logging_in_clears_a_previous_users_cached_agreement(app, db_session, user_id):
    """The session cookie outlives logout.

    Without this reset, a second person signing in on the same browser would
    inherit the first person's cached agreement and never see the gate.
    """
    from flask import session as flask_session
    from flask_login import user_logged_in

    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY
    from models.db import User

    with app.test_request_context("/"):
        flask_session[TERMS_OK_SESSION_KEY] = "beta-1"
        user_logged_in.send(app, user=User.query.get(user_id))
        assert TERMS_OK_SESSION_KEY not in flask_session
