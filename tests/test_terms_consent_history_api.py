"""Phase 6: the consent history API, and the gate's narrowed allow-list.

`GET /minty/api/users/<id>/consents` answers the only question the consent
table exists for — what did this person agree to, and when — without needing
database access.

It lives on the legal blueprint but is product functionality, not part of the
acceptance flow. The tests below pin that distinction: it is behind the gate,
unlike the documents and the accept screen.
"""

from __future__ import annotations

import uuid

import pytest

from legal import registry


@pytest.fixture
def db_session(app):

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


def _make_user(app, db_session, prefix="hist"):
    from models.db import User

    with app.app_context():
        row = User(
            id=str(uuid.uuid4()),
            username=f"{prefix}-{uuid.uuid4().hex[:8]}@test.com",
            email=f"{prefix}-{uuid.uuid4().hex[:8]}@test.com",
            first_name="Hist",
            last_name="User",
            password="x",
            approved=True,
        )
        db_session.session.add(row)
        db_session.session.commit()
        return row.id


@pytest.fixture
def user_id(app, db_session):
    return _make_user(app, db_session)


@pytest.fixture
def agreed(client, app, db_session, user_id):
    """Logged in AND has accepted — so the gate is not what is under test."""
    from blueprints.legal.services.consent import record_consent
    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY

    with app.app_context():
        record_consent(user_id, source="signup_otp")
        db_session.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = user_id
        session["_fresh"] = True
        session[TERMS_OK_SESSION_KEY] = registry.current_version(registry.TERMS)
    return client


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------

def test_you_can_see_your_own_consent_history(agreed, user_id):
    response = agreed.get(f"/minty/api/users/{user_id}/consents")
    assert response.status_code == 200

    body = response.get_json()
    assert body["user_id"] == user_id
    assert len(body["consents"]) == 1

    entry = body["consents"][0]
    assert entry["terms_version"] == registry.CURRENT_TERMS_VERSION
    assert entry["source"] == "signup_otp"
    # The fingerprint is returned so a record can be checked against the
    # document page, which prints the same value.
    assert entry["document_hash"] == registry.get_current(registry.TERMS).sha256
    assert entry["accepted_at"] is not None


def test_you_cannot_see_someone_elses_without_permission(
    agreed, app, db_session
):
    """Sharing no entity, holding no permission — nothing to see."""
    stranger_id = _make_user(app, db_session, prefix="stranger")

    response = agreed.get(f"/minty/api/users/{stranger_id}/consents")
    assert response.status_code == 403


def test_the_endpoint_requires_a_login(client, db_session, user_id):
    response = client.get(
        f"/minty/api/users/{user_id}/consents", follow_redirects=False
    )
    assert response.status_code in (301, 302, 401)


def test_a_user_with_no_consents_returns_an_empty_list(
    client, app, db_session
):
    """Empty is a real answer — it means they have agreed to nothing, which is
    exactly what the gate acts on."""
    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY

    lonely_id = _make_user(app, db_session, prefix="lonely")

    with client.session_transaction() as session:
        session["_user_id"] = lonely_id
        session["_fresh"] = True
        session[TERMS_OK_SESSION_KEY] = registry.current_version(registry.TERMS)

    response = client.get(f"/minty/api/users/{lonely_id}/consents")
    assert response.status_code == 200
    assert response.get_json()["consents"] == []


# --------------------------------------------------------------------------
# The gate's narrowed allow-list
# --------------------------------------------------------------------------

def test_the_history_api_is_behind_the_acceptance_gate(client, app, db_session):
    """It sits on the legal blueprint but is product functionality.

    An earlier version of the gate allow-listed the whole blueprint, which
    would have left this reachable by someone who had agreed to nothing.
    """
    blocked_id = _make_user(app, db_session, prefix="blocked")

    with client.session_transaction() as session:
        session["_user_id"] = blocked_id
        session["_fresh"] = True

    response = client.get(f"/minty/api/users/{blocked_id}/consents")
    assert response.status_code == 403
    assert response.get_json()["code"] == "terms_acceptance_required"


@pytest.mark.parametrize(
    "url",
    [
        "/legal/accept",
        "/legal/terms",
        "/legal/terms/beta-1",
        "/legal/privacy",
        "/legal/privacy/beta-1",
        "/legal/current",
    ],
)
def test_the_acceptance_flow_is_still_reachable_when_blocked(
    client, app, db_session, url
):
    """The narrowed allow-list must not have dropped any of these.

    Every one is load-bearing: without it the gate redirects to a page it
    blocks, which is a loop with no exit for every user in the system.
    """
    blocked_id = _make_user(app, db_session, prefix="blocked")

    with client.session_transaction() as session:
        session["_user_id"] = blocked_id
        session["_fresh"] = True

    assert client.get(url).status_code == 200
