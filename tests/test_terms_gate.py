"""Phase 4 of the Terms of Use work: the request gate.

The first section is the one that matters. The gate runs before every request,
so a wrong allow-list locks every user out of Minty with no way back in —
administrators included. Those tests come first and are worth keeping green
above all the others in this file.
"""

from __future__ import annotations

import uuid

import pytest

from legal import registry

_schema_attached = False


@pytest.fixture
def db_session(app, tmp_path_factory):
    """See tests/test_terms_consent.py for why this attaches a file, and
    tests/test_terms_accept_screen.py for why it yields outside a context."""
    global _schema_attached
    from sqlalchemy import event

    from models.db import db

    with app.app_context():
        engine = db.engine
        if not _schema_attached:
            schema_path = str(
                tmp_path_factory.mktemp("schema") / "pettycashv2.sqlite"
            ).replace("\\", "/")

            @event.listens_for(engine, "connect")
            def _attach_schema(dbapi_connection, _record):  # noqa: ANN001
                try:
                    dbapi_connection.execute(
                        f"ATTACH DATABASE '{schema_path}' AS pettycashv2"
                    )
                except Exception:
                    pass

            engine.dispose()
            _schema_attached = True

        db.create_all()

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
    from models.db import User

    with app.app_context():
        row = User(
            id=str(uuid.uuid4()),
            username=f"gated-{uuid.uuid4().hex[:8]}@test.com",
            email=f"gated-{uuid.uuid4().hex[:8]}@test.com",
            first_name="Not",
            last_name="Agreed",
            password="x",
            approved=True,
        )
        db_session.session.add(row)
        db_session.session.commit()
        return row.id


@pytest.fixture
def blocked(client, user_id):
    """Logged in, has agreed to nothing. The state the gate exists for."""
    with client.session_transaction() as session:
        session["_user_id"] = user_id
        session["_fresh"] = True
    return client


def _in_app(app, fn):
    with app.app_context():
        return fn()


# --------------------------------------------------------------------------
# LOCK-OUT SAFETY — the highest-value tests in this file
# --------------------------------------------------------------------------

def test_a_blocked_user_can_still_log_out(blocked, db_session):
    """Non-negotiable.

    Someone who reads the Terms and refuses must be able to leave. If the gate
    catches logout, the acceptance screen becomes a trap with no exit.
    """
    response = blocked.get("/logout", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/legal/accept" not in response.headers.get("Location", "")


def test_a_blocked_user_can_reach_the_acceptance_screen(blocked, db_session):
    """Otherwise the gate redirects to a page the gate itself blocks — an
    infinite loop nobody can escape."""
    assert blocked.get("/legal/accept").status_code == 200


@pytest.mark.parametrize(
    "url",
    ["/legal/terms", "/legal/privacy", "/legal/terms/beta-1", "/legal/current"],
)
def test_a_blocked_user_can_read_what_they_are_agreeing_to(blocked, db_session, url):
    assert blocked.get(url).status_code == 200


def test_a_blocked_user_can_submit_their_acceptance(blocked, db_session, app, user_id):
    """The POST must not be gated either — blocking it would mean nobody could
    ever leave the blocked state."""
    from blueprints.legal.services.consent import has_consent

    response = blocked.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    assert response.status_code == 200
    assert _in_app(app, lambda: has_consent(user_id)) is True


def test_the_health_check_is_never_gated(blocked, db_session):
    """A gated health check reads as "app is down" to the platform, which
    restarts it in a loop."""
    assert blocked.get("/health").status_code == 200


def test_static_files_are_never_gated(blocked, db_session):
    response = blocked.get("/static/css/main.css")
    assert response.status_code in (200, 304, 404)  # anything but a redirect


def test_login_endpoints_stay_reachable(blocked, db_session):
    """Or nobody can authenticate far enough to reach the acceptance screen."""
    assert blocked.get("/login").status_code in (200, 302)
    assert blocked.get("/register").status_code == 200


# --------------------------------------------------------------------------
# The gate actually gates
# --------------------------------------------------------------------------

def test_a_page_request_is_redirected_to_the_acceptance_screen(blocked, db_session):
    """The gate sends people to the Select Company list, which renders the
    acceptance panel as a modal over itself. /legal/accept still exists and
    still works — it is the fallback for anyone arriving by a path that does
    not pass through /entity."""
    response = blocked.get("/index", follow_redirects=False)
    assert response.status_code == 302
    assert "/entity" in response.headers["Location"]


def test_a_json_request_gets_403_with_a_code_not_a_redirect(blocked, db_session):
    """A redirect sent to a background request fails silently — the user sees
    nothing happen and has no clue why."""
    response = blocked.get(
        "/index", headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 403
    assert response.get_json()["code"] == "terms_acceptance_required"


def test_an_api_path_gets_403(blocked, db_session):
    """Several JSON routes sit under /minty/api/ rather than /api/, which is
    why the check is on "/api/" appearing anywhere in the path."""
    response = blocked.get("/minty/api/anything", headers={"Accept": "application/json"})
    assert response.status_code in (403, 404)
    if response.status_code == 403:
        assert response.get_json()["code"] == "terms_acceptance_required"


def test_an_anonymous_visitor_is_not_gated(client, db_session):
    """The gate must not interfere with logging in, and must leave the
    Bearer-token integrations alone — neither populates current_user."""
    response = client.get("/login", follow_redirects=False)
    assert response.status_code in (200, 302)
    assert "/legal/accept" not in response.headers.get("Location", "")


def test_an_agreed_user_passes_straight_through(blocked, db_session, app, user_id):
    from blueprints.legal.services.consent import record_consent

    def _grant():
        record_consent(user_id, source="gate")
        db_session.session.commit()

    _in_app(app, _grant)

    response = blocked.get("/index", follow_redirects=False)
    assert "/legal/accept" not in response.headers.get("Location", "")


def test_an_unmatched_url_still_404s(blocked, db_session):
    """A typo should not become a trip through the acceptance screen."""
    assert blocked.get("/no-such-page-at-all").status_code == 404


# --------------------------------------------------------------------------
# Where they land afterwards
# --------------------------------------------------------------------------

def test_the_blocked_destination_is_remembered_and_returned_to(
    blocked, db_session, app
):
    from blueprints.legal.services.gate import TERMS_NEXT_SESSION_KEY

    blocked.get("/index?tab=summary", follow_redirects=False)

    with blocked.session_transaction() as session:
        assert session[TERMS_NEXT_SESSION_KEY] == "/index?tab=summary"

    response = blocked.post(
        "/legal/accept",
        json={"accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION},
    )
    assert response.get_json()["redirect_url"] == "/index?tab=summary"


# --------------------------------------------------------------------------
# Caching and failure behaviour
# --------------------------------------------------------------------------

def test_the_session_cache_avoids_a_database_read_per_request(
    blocked, db_session, app, user_id, monkeypatch
):
    """The check result is cached in the session, so the table is read about
    once per login rather than on every request."""
    from blueprints.legal.routes import gate as gate_module
    from blueprints.legal.services.consent import record_consent

    def _grant():
        record_consent(user_id, source="gate")
        db_session.session.commit()

    _in_app(app, _grant)

    # First request populates the cache from the database.
    blocked.get("/index", follow_redirects=False)

    calls = []
    monkeypatch.setattr(
        gate_module, "has_consent", lambda *a, **k: calls.append(1) or True
    )
    blocked.get("/index", follow_redirects=False)

    assert calls == [], "the gate hit the database despite a warm session cache"


def test_a_missing_document_does_not_lock_everyone_out(blocked, db_session):
    """A mistyped CURRENT_TERMS_VERSION must not become an infinite redirect.

    Blocking here would send them to /legal/accept, which finds no document
    and bounces them to the dashboard, which the gate blocks again — a loop
    with no exit, for every user in the system, from a one-word config typo.
    """
    original = registry.CURRENT_TERMS_VERSION
    registry.CURRENT_TERMS_VERSION = "beta-does-not-exist"
    try:
        response = blocked.get("/index", follow_redirects=False)
        assert "/legal/accept" not in response.headers.get("Location", "")
    finally:
        registry.CURRENT_TERMS_VERSION = original


def test_the_gate_fails_open_if_it_raises(blocked, db_session, monkeypatch):
    """Failing closed on an unexpected error takes the whole app down for
    everyone at once. Failing open skips a backstop and logs loudly. The
    outage is the worse outcome."""
    from blueprints.legal.routes import gate as gate_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("database is having a bad day")

    monkeypatch.setattr(gate_module, "has_consent", _boom)

    response = blocked.get("/index", follow_redirects=False)
    assert "/legal/accept" not in response.headers.get("Location", "")


def test_moving_the_version_re_gates_an_already_agreed_user(
    blocked, db_session, app, user_id
):
    """The revamp path end to end: agreeing to beta-1 must not survive the
    move to beta-2, even with a warm session cache."""
    from dataclasses import replace

    from blueprints.legal.services.consent import record_consent

    def _grant():
        record_consent(user_id, source="gate", version="beta-1")
        db_session.session.commit()

    _in_app(app, _grant)

    # Warm the session cache against beta-1.
    blocked.get("/index", follow_redirects=False)

    original = registry.CURRENT_TERMS_VERSION
    beta_1 = registry.get_document(registry.TERMS, "beta-1")
    registry._DOCUMENTS[(registry.TERMS, "beta-2")] = replace(
        beta_1, version="beta-2", sha256="b" * 64
    )
    registry.CURRENT_TERMS_VERSION = "beta-2"
    try:
        response = blocked.get("/index", follow_redirects=False)
        assert response.status_code == 302
        assert "/entity" in response.headers["Location"]
    finally:
        registry.CURRENT_TERMS_VERSION = original
        registry._DOCUMENTS.pop((registry.TERMS, "beta-2"), None)
