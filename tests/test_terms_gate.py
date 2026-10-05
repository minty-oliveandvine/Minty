"""Phase 4 of the Terms of Use work: the request gate.

The first section is the one that matters. The gate runs before every request,
so a wrong allow-list locks every user out of Minty with no way back in —
administrators included. Those tests come first and are worth keeping green
above all the others in this file.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

import pytest

from legal import registry


@pytest.fixture
def db_session(app):
    """Yields outside a context (see tests/test_terms_accept_screen.py for why)."""

    from models.db import db

    yield db

    import char_factories

    with app.app_context():
        char_factories.truncate_all(app)  # TRUNCATE ... CASCADE on Postgres


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
    # forwards to the hub's sign-up, ungated
    assert blocked.get("/register").status_code == 302


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


def test_an_invite_link_is_not_swallowed_by_the_gate(blocked, db_session):
    """The accept route renders nothing.

    It validates the token and bounces to the onboarding sign-in page, which
    carries its own Terms tick box — and acceptance is still enforced at
    auth.email_handoff and on every entity route afterwards. So gating it
    protects nothing; it only makes the invite link silently do nothing for
    people who have not agreed yet, which is most of the people who ever
    receive one.

    The failure being guarded is a 302 to /entity, which means the gate
    intercepted and the route never ran.
    """
    response = blocked.get(
        "/invitation/accept/nonexistent-token", follow_redirects=False
    )

    assert not response.headers.get("Location", "").endswith("/entity"), (
        "the Terms gate swallowed the invite link — the accept route never ran"
    )


def test_the_xero_not_connected_page_stays_gated(blocked, db_session):
    """Deliberately NOT allow-listed alongside the accept route: this one
    renders a template, so it is content like any other."""
    response = blocked.get(
        "/invitation/xero-not-connected/00000000-0000-0000-0000-000000000001",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/entity")


def test_a_blocked_user_can_reach_the_page_the_gate_sends_them_to(
    blocked, db_session
):
    """The redirect target must not itself be gated.

    This is the loop the runbook calls the biggest risk in the design: the gate
    sends people to /entity, and if /entity is gated too, /entity redirects to
    /entity forever and nobody without a consent row can reach any page at all
    — administrators included.

    Since phase 2 (2026-10-05) /entity hands the browser to minty-web's list, whose Terms gate
    shows the panel; what matters here is that the gate lets /entity answer - with that
    hand-over, not with another trip to itself. The enforcement is the tests below.
    """
    resp = blocked.get("/entity")
    assert resp.status_code == 302
    assert urlsplit(resp.headers["Location"]).path == "/landing"


@pytest.mark.parametrize(
    "path",
    [
        # Exactly what a company card links to — the first thing anyone would
        # click after deleting the modal in devtools.
        "/entity/00000000-0000-0000-0000-000000000001/modules",
        "/entity/00000000-0000-0000-0000-000000000001",
        "/entity/00000000-0000-0000-0000-000000000001/enter",
        "/entity/settings/users/00000000-0000-0000-0000-000000000001",
    ],
)
def test_removing_the_modal_gets_you_nowhere(blocked, db_session, path):
    """The modal is presentation; the gate is enforcement.

    Anyone can delete a div in devtools. What stops them is that every route
    behind it still refuses a user with no consent row, so clicking through
    lands straight back on /entity with the modal rendered again.

    If this ever starts returning 200, the acceptance screen has become
    decorative and the whole feature is theatre.
    """
    response = blocked.get(path, follow_redirects=False)

    assert response.status_code == 302, (
        f"{path} served content to a user who has not accepted the Terms"
    )
    assert response.headers["Location"].endswith("/entity")


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


def test_the_document_body_is_available_as_json(client):
    """The onboarding app shows the Terms inline so it can gate its tick box on
    reaching the end. It is a separate origin, so it cannot read the scroll
    position of an iframe — it needs the markup itself.

    No login: the person reading this has no account yet.
    """
    response = client.get("/legal/content/terms")
    assert response.status_code == 200

    body = response.get_json()
    assert body["version"] == registry.CURRENT_TERMS_VERSION
    assert body["sha256"] == registry.get_current(registry.TERMS).sha256
    assert "<p>" in body["html"]


def test_an_unknown_document_kind_is_not_served(client):
    assert client.get("/legal/content/nonsense").status_code == 404


def test_a_blocked_user_can_read_the_document_json(blocked, db_session):
    """Allow-listed like the other legal routes — otherwise the gate blocks the
    very text it is asking people to agree to."""
    assert blocked.get("/legal/content/terms").status_code == 200


# --------------------------------------------------------------------------
# Invite terms-status: don't ask someone who already agreed
# --------------------------------------------------------------------------

def test_invite_terms_status_defaults_to_required(app, client, db_session):
    """No token, unknown token, no such user — all answer 'still required'.

    Fails safe on purpose. Asking someone to accept twice is an annoyance;
    skipping someone who never agreed is a missing consent record, which is the
    thing this feature exists to prevent.
    """
    assert client.post("/legal/invite-terms-status", json={}).get_json()["terms_required"] is True
    assert (
        client.post("/legal/invite-terms-status", json={"invite": "not-a-real-token"})
        .get_json()["terms_required"]
        is True
    )
    # Even a database failure must answer "required" rather than 500 the
    # sign-in screen or wave someone through unasked.
    from unittest.mock import patch

    with app.app_context(), patch(  # reading ``Model.query`` to patch it needs a context
        "blueprints.invitation.models.invitation.Invitation.query",
        new_callable=lambda: property(lambda self: (_ for _ in ()).throw(RuntimeError("db down"))),
    ):
        response = client.post("/legal/invite-terms-status", json={"invite": "anything"})
    assert response.status_code == 200
    assert response.get_json()["terms_required"] is True


def test_invite_terms_status_is_false_once_that_user_has_agreed(
    app, db_session, user_id
):
    """The bug this fixes: an existing user, invited to another entity, was
    shown the tick box again for Terms they had already accepted."""
    import uuid as _uuid

    from blueprints.invitation.models.invitation import Invitation
    from blueprints.legal.services.consent import record_consent
    from models.db import User

    # a plain test client: the fixture's ``with app.test_client()`` keeps the request context
    # of a request made INSIDE the app context below alive past it, and the two contexts then
    # unwind out of order at teardown ("Working outside of application context")
    client = app.test_client()
    with app.app_context():
        email = User.query.get(user_id).email
        from models.db import Entity

        company = Entity(id=str(_uuid.uuid4()), name="Invite Co", status="disconnected")
        db_session.session.add(company)
        db_session.session.flush()  # invitation.entity_id is a real FK
        db_session.session.add(
            Invitation(
                id=str(_uuid.uuid4()),
                email=email,
                token="tok-" + _uuid.uuid4().hex,
                status="pending",
                entity_id=company.id,
                role="cashier",
            )
        )
        db_session.session.commit()
        token = Invitation.query.filter_by(email=email).first().token

        # Before agreeing: still required.
        assert client.post(
            "/legal/invite-terms-status", json={"invite": token}
        ).get_json()["terms_required"] is True

        record_consent(user_id, source="gate")
        db_session.session.commit()

        # After agreeing: not required — no second tick box.
        assert client.post(
            "/legal/invite-terms-status", json={"invite": token}
        ).get_json()["terms_required"] is False
