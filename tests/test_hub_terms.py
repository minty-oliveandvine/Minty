"""minty-web's Terms modal: ``GET /api/me/terms`` and ``POST /api/me/terms/accept``
(``blueprints/legal/routes/hub.py``).

The same gate as the Jinja panel, drawn by another app: what is owed is
``services/gate.terms_owed``, accepting is ``services/consent.accept_current_terms`` (the
checks ``POST /legal/accept`` makes), the fingerprint comes from the registry, and the row
says ``source = "hub"``. Bearer-only, through ``blueprints/shared/hub_api.py``.

Imports of project modules happen inside tests (the conftest ``app`` fixture re-imports the
blueprints).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")


@pytest.fixture
def olive(app, db):
    with app.app_context():
        return F.make_user(db, "olive@test.com", first_name="Olive", last_name="Vine")


def _auth(app, user_id) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "entity_id": "", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
        app.config["SECRET_KEY"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}", "Origin": HUB, "User-Agent": "hub-test-agent"}


def _live_version():
    from legal import registry

    return registry.current_version(registry.TERMS)


def _consents(app, user_id):
    from blueprints.legal.models.terms_consent import TermsConsent

    with app.app_context():
        return [(c.terms_version, c.source, c.document_hash, c.user_agent)
                for c in TermsConsent.query.filter_by(user_id=user_id).all()]


# --- what is owed ----------------------------------------------------------------------


def test_a_first_time_reader_is_told_which_version_is_owed(app, client, olive, hub):
    """The version and its FINGERPRINT - no wording and no links.

    The documents moved to minty-web on 2026-10-12: it holds the text and the public pages,
    this app names the version and the hash it will record. The `sha256` is what lets the
    client check that the document it is about to show is the one being asked for.
    """
    body = client.get("/api/me/terms", headers=_auth(app, olive.id)).get_json()

    from legal import registry

    entry = registry.get_current(registry.TERMS)
    assert body["owed"] is True
    assert body["document"] == {
        "version": entry.version,
        "effective_date": entry.effective_date,
        "sha256": entry.sha256,
        "show_draft_notice": entry.show_draft_notice,
    }
    assert body["is_update"] is False and body["previous_version"] is None
    # No wording, and no links to pages this app no longer serves.
    assert "html" not in body["document"]
    assert "links" not in body


def test_nothing_is_owed_once_agreed(app, client, olive, hub, db):
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        record_consent(olive.id, source="gate")
        db.session.commit()
    assert client.get("/api/me/terms", headers=_auth(app, olive.id)).get_json() == {"owed": False}


def test_an_older_agreement_reads_as_an_update_naming_the_version_agreed(
    app, client, olive, hub, db, monkeypatch
):
    """Agreed to an older version: asked again, and told which one.

    The LINK to that older version is minty-web's own page (`/terms/<version>`), built from
    `previous_version` - this app no longer serves it, so it no longer names it.
    """
    from dataclasses import replace

    from blueprints.legal.services.consent import record_consent
    from legal import registry

    with app.app_context():
        record_consent(olive.id, source="gate")
        db.session.commit()
    live = _live_version()
    # a newer version goes live, with a manifest entry of its own
    entry = registry.get_version(registry.TERMS, live)
    monkeypatch.setattr(registry, "CURRENT_TERMS_VERSION", "beta-next")
    monkeypatch.setitem(
        registry.MANIFEST,
        (registry.TERMS, "beta-next"),
        replace(entry, version="beta-next", sha256="e" * 64),
    )

    body = client.get("/api/me/terms", headers=_auth(app, olive.id)).get_json()
    assert body["owed"] is True
    assert body["is_update"] is True and body["previous_version"] == live
    assert body["document"]["version"] == "beta-next"
    assert body["document"]["sha256"] == "e" * 64


# --- accepting -------------------------------------------------------------------------


def test_accepting_records_a_hub_consent_with_the_manifests_fingerprint(app, client, olive, hub):
    from legal import registry

    expected = registry.get_current(registry.TERMS).sha256
    resp = client.post(
        "/api/me/terms/accept",
        # The client says which document it showed; this app records its OWN hash.
        json={"accepted": True, "terms_version": _live_version(), "document_hash": expected},
        headers=_auth(app, olive.id),
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "terms_version": _live_version()}
    assert resp.headers["Access-Control-Allow-Origin"] == HUB
    assert _consents(app, olive.id) == [
        (_live_version(), "hub", expected, "hub-test-agent")
    ]
    # and nothing is owed any more - here, and at Flask's own gate
    assert client.get("/api/me/terms", headers=_auth(app, olive.id)).get_json() == {"owed": False}


def test_a_client_that_showed_other_wording_is_refused(app, client, olive, hub):
    """The canary, since the client now genuinely holds the document (2026-10-12).

    A `document_hash` that is not the manifest's means minty-web is serving wording this app
    would misrecord - a stale bundle, or a curl. Refused, and NOTHING is written: a consent
    row naming wording nobody was shown is worse than no row. The hash is never stored, and
    the value sent proves nothing on its own - this is a canary, not an integrity control.
    """
    resp = client.post(
        "/api/me/terms/accept",
        json={"accepted": True, "terms_version": _live_version(), "document_hash": "f" * 64},
        headers=_auth(app, olive.id),
    )

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "document_mismatch"}
    assert _consents(app, olive.id) == []


def test_a_client_too_old_to_send_a_hash_is_still_accepted(app, client, olive, hub):
    """Omitted is not wrong: a bundle that predates the check is not a bundle showing the
    wrong document, and refusing it would lock those readers out of agreeing at all."""
    resp = client.post(
        "/api/me/terms/accept",
        json={"accepted": True, "terms_version": _live_version()},
        headers=_auth(app, olive.id),
    )

    assert resp.status_code == 200
    assert len(_consents(app, olive.id)) == 1


def test_accepting_twice_keeps_one_record(app, client, olive, hub):
    for _ in range(2):
        resp = client.post("/api/me/terms/accept", json={"accepted": True, "terms_version": _live_version()},
                           headers=_auth(app, olive.id))
        assert resp.status_code == 200
    assert len(_consents(app, olive.id)) == 1


def test_an_acceptance_here_passes_flasks_own_gate(app, client, olive, hub):
    """The gate falls back to the database when its session cache has no answer, so an
    agreement given in minty-web holds on the person's next Flask page."""
    F.login(client, olive, accepted_terms=False)
    # a JSON page: the gate answers it 403 terms_acceptance_required while one is owed
    blocked = client.get("/minty/api/users/me")
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "terms_acceptance_required"

    # the session cookie rides along here, as it would on a same-origin deployment: the gate
    # must not refuse the route that takes the acceptance
    accepted = client.post("/api/me/terms/accept", json={"accepted": True, "terms_version": _live_version()},
                           headers=_auth(app, olive.id))
    assert accepted.status_code == 200, accepted.get_json()
    after = client.get("/minty/api/users/me")
    assert after.status_code == 200, after.get_json()


@pytest.mark.parametrize(
    "body, status, answer",
    [
        ({"accepted": False, "terms_version": None}, 400, {"error": "Please tick the box to continue."}),
        ({"terms_version": None}, 400, {"error": "Please tick the box to continue."}),
        ({"accepted": "yes", "terms_version": None}, 400, {"error": "Please tick the box to continue."}),
        ({"accepted": True, "terms_version": "beta-0"}, 409, {"error": "version_changed", "terms_version": None}),
    ],
)
def test_a_refusal_records_nothing(app, client, olive, hub, body, status, answer):
    body = {**body, "terms_version": body["terms_version"] or ("beta-0" if status == 409 else _live_version())}
    resp = client.post("/api/me/terms/accept", json=body, headers=_auth(app, olive.id))
    expected = {**answer, "terms_version": _live_version()} if status == 409 else answer
    assert resp.status_code == status
    assert resp.get_json() == expected
    assert _consents(app, olive.id) == []


# --- the door --------------------------------------------------------------------------


def test_no_token_no_terms(client, olive, hub):
    for method, path in (("get", "/api/me/terms"), ("post", "/api/me/terms/accept")):
        resp = getattr(client, method)(path, headers={"Origin": HUB})
        assert resp.status_code == 401
        assert resp.headers["Access-Control-Allow-Origin"] == HUB


def test_the_preflight_allows_the_post(client, hub):
    resp = client.options(
        "/api/me/terms/accept",
        headers={"Origin": HUB, "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 204
    assert "POST" in resp.headers["Access-Control-Allow-Methods"]


def test_the_accept_needs_no_csrf_token_it_is_bearer_only(app):
    assert "blueprints.legal.routes.hub.hub_terms_accept" in app.extensions["csrf"]._exempt_views


def test_hub_is_a_consent_source(app):
    from blueprints.legal.models.terms_consent import CONSENT_SOURCES, SOURCE_HUB

    assert SOURCE_HUB == "hub" and SOURCE_HUB in CONSENT_SOURCES
