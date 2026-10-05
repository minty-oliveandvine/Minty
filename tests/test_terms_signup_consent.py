"""Phase 5 of the Terms of Use work: capturing agreement at sign-up.

The tick box spares a new user the acceptance gate. It does not replace it —
the gate is still what guarantees nobody uses Minty without agreeing, which is
why sign-up without the fields is allowed during the rollout window.

The property worth guarding hardest is the transaction one: the account and
the agreement land together, or neither does.
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


def _in_app(app, fn):
    with app.app_context():
        return fn()


def _signup(app, db_session, email, **extra):
    """Run the account-creating half of sign-up directly.

    Goes at `_create_passwordless_user` rather than through the OTP route so
    these tests are about consent capture, not about mocking out email codes.
    """
    from blueprints.auth.routes.email_auth import _create_passwordless_user

    with app.app_context():
        return _create_passwordless_user(
            email=email, first_name="New", last_name="Person", **extra
        )


# --------------------------------------------------------------------------
# Consent capture
# --------------------------------------------------------------------------

def test_signup_with_agreement_records_it(app, db_session):
    from blueprints.legal.services.consent import consents_for_user

    email = f"signup-{uuid.uuid4().hex[:8]}@test.com"
    user = _signup(
        app,
        db_session,
        email,
        consent_source="signup_otp",
        terms_version=registry.CURRENT_TERMS_VERSION,
    )
    assert user is not None

    rows = _in_app(app, lambda: consents_for_user(user.id))
    assert len(rows) == 1
    assert rows[0].source == "signup_otp"
    assert rows[0].terms_version == registry.CURRENT_TERMS_VERSION
    # Server-side hash, never the client's word for it.
    assert rows[0].document_hash == registry.get_current(registry.TERMS).sha256


def test_an_invited_user_is_recorded_as_such(app, db_session):
    """Source is what tells the two sign-up routes apart in the audit trail."""
    from blueprints.legal.services.consent import consents_for_user

    email = f"invited-{uuid.uuid4().hex[:8]}@test.com"
    user = _signup(
        app,
        db_session,
        email,
        consent_source="signup_invite",
        terms_version=registry.CURRENT_TERMS_VERSION,
    )
    rows = _in_app(app, lambda: consents_for_user(user.id))
    assert rows[0].source == "signup_invite"


def test_signup_without_agreement_still_creates_the_account(app, db_session):
    """The rollout window: the onboarding app may still be sending the old
    request shape. Refusing here would break every sign-up until it ships.

    The person is not let off — they meet the acceptance gate at their next
    request.
    """
    from blueprints.legal.services.consent import has_consent

    email = f"norollout-{uuid.uuid4().hex[:8]}@test.com"
    user = _signup(app, db_session, email)

    assert user is not None
    assert _in_app(app, lambda: has_consent(user.id)) is False


# --------------------------------------------------------------------------
# The request-level rules
# --------------------------------------------------------------------------

def test_agreement_to_the_live_version_is_accepted(app):
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    version, error = _terms_consent_for_signup(
        {"terms_accepted": True, "terms_version": registry.CURRENT_TERMS_VERSION}
    )
    assert version == registry.CURRENT_TERMS_VERSION
    assert error is None


@pytest.mark.parametrize("enforcing", [True, False])
def test_agreement_to_a_different_version_is_never_recorded(
    app, monkeypatch, enforcing
):
    """Filing a record against wording they did not see is worse than no
    record, because it looks genuine. True whether or not enforcement is on —
    only what happens NEXT differs."""
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    monkeypatch.setattr(registry, "REQUIRE_TERMS_AT_SIGNUP", enforcing)

    version, error = _terms_consent_for_signup(
        {"terms_accepted": True, "terms_version": "beta-0"}
    )
    assert version is None
    if enforcing:
        # Refused, and told to refresh — "you must accept the Terms" would read
        # as a bug to someone who just ticked the box.
        assert error and "updated" in error.lower()
    else:
        assert error is None  # allowed through; the gate asks them properly


def test_nothing_sent_is_allowed_while_the_flag_is_off(app, monkeypatch):
    """The rollback lever. Setting REQUIRE_TERMS_AT_SIGNUP=false restores the
    rollout behaviour without a code change — the fix to reach for if sign-ups
    start failing after a deploy."""
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    monkeypatch.setattr(registry, "REQUIRE_TERMS_AT_SIGNUP", False)

    version, error = _terms_consent_for_signup({})
    assert version is None
    assert error is None


def test_nothing_sent_is_refused_by_default(app):
    """Phase 6: enforcement is ON by default.

    Asserted without monkeypatching, so this fails if the default is ever
    quietly flipped back.
    """
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    assert registry.REQUIRE_TERMS_AT_SIGNUP is True

    version, error = _terms_consent_for_signup({})
    assert version is None
    assert error and "Terms of Use" in error


def test_an_explicit_refusal_is_refused(app):
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    version, error = _terms_consent_for_signup(
        {"terms_accepted": False, "terms_version": registry.CURRENT_TERMS_VERSION}
    )
    assert version is None
    assert error is not None


def test_agreeing_to_a_stale_version_is_refused_when_enforcing(app):
    """Stricter than the rollout behaviour, and deliberately so.

    While enforcement was off, a version mismatch quietly fell through to the
    gate. With it on, the sign-up is refused outright — because the alternative
    is creating the account while silently recording nothing, which is the
    exact state enforcement exists to prevent.
    """
    from blueprints.auth.routes.email_auth import _terms_consent_for_signup

    version, error = _terms_consent_for_signup(
        {"terms_accepted": True, "terms_version": "beta-0"}
    )
    assert version is None
    assert error is not None


# --------------------------------------------------------------------------
# The transaction guarantee
# --------------------------------------------------------------------------

def test_no_account_is_created_if_the_consent_write_fails(app, db_session,
                                                          monkeypatch):
    """One transaction: if either row fails, neither is saved.

    Otherwise a failure part-way leaves an account with no agreement — the
    exact state the whole design exists to prevent.
    """
    from blueprints.auth.routes import email_auth as email_auth_module
    from models.db import User

    def _boom(*_args, **_kwargs):
        raise RuntimeError("consent write failed")

    monkeypatch.setattr(email_auth_module, "record_consent", _boom, raising=False)

    email = f"atomic-{uuid.uuid4().hex[:8]}@test.com"

    # record_consent is imported inside the function, so patch it at source.
    from blueprints.legal.services import consent as consent_module

    monkeypatch.setattr(consent_module, "record_consent", _boom)

    user = _signup(
        app,
        db_session,
        email,
        consent_source="signup_otp",
        terms_version=registry.CURRENT_TERMS_VERSION,
    )

    assert user is None, "sign-up should fail when the consent write fails"
    assert _in_app(
        app, lambda: User.query.filter_by(username=email).first()
    ) is None, "an account was created without its agreement"


# --------------------------------------------------------------------------
# The login branch: an invitee who ALREADY has an account
# --------------------------------------------------------------------------

def _existing_user(app, db_session, email):
    from models.db import User

    with app.app_context():
        row = User(
            id=str(uuid.uuid4()),
            username=email,
            email=email,
            first_name="Already",
            last_name="Exists",
            password="x",
            approved=True,
        )
        db_session.session.add(row)
        db_session.session.commit()
        return row.id


def test_a_ticked_box_is_recorded_even_when_the_account_already_exists(
    app, client, db_session, monkeypatch
):
    """Regression: the invite tick box was being silently discarded.

    An invitee who already has a Minty account — invited before, or signed up
    and never finished — resolves to action == "login" rather than the sign-up
    branch. That branch logged them straight in and never looked at
    `terms_accepted`, so they ticked the box on the way in and were shown the
    acceptance gate immediately afterwards. It read as the tick box being
    broken, because from the user's side it was.
    """
    from blueprints.auth.routes import email_auth as route
    from blueprints.legal.services.consent import consents_for_user, has_consent

    email = f"reinvited-{uuid.uuid4().hex[:8]}@test.com"
    user_id = _existing_user(app, db_session, email)

    with app.app_context():
        from models.db import User

        user = User.query.get(user_id)
        monkeypatch.setattr(
            route,
            "verify_email_otp",
            lambda *_a, **_k: ({"action": "login", "user": user}, None, None),
        )

        response = client.post(
            "/auth/email/verify-code",
            json={
                "email": email,
                "code": "123456",
                "terms_accepted": True,
                "terms_version": registry.CURRENT_TERMS_VERSION,
            },
        )

        assert response.status_code == 200
        assert has_consent(user_id) is True

        rows = consents_for_user(user_id)
        assert len(rows) == 1
        assert rows[0].terms_version == registry.CURRENT_TERMS_VERSION
        # Server-side hash, never the client's word for it.
        assert rows[0].document_hash == registry.get_current(registry.TERMS).sha256


def test_a_plain_login_records_nothing(app, client, db_session, monkeypatch):
    """The other half: logging in must not manufacture an agreement.

    Only a request that actually carries a ticked box for the LIVE version is
    recorded. Without this, every login would file a consent row nobody gave.
    """
    from blueprints.auth.routes import email_auth as route
    from blueprints.legal.services.consent import has_consent

    email = f"plainlogin-{uuid.uuid4().hex[:8]}@test.com"
    user_id = _existing_user(app, db_session, email)

    with app.app_context():
        from models.db import User

        user = User.query.get(user_id)
        monkeypatch.setattr(
            route,
            "verify_email_otp",
            lambda *_a, **_k: ({"action": "login", "user": user}, None, None),
        )

        response = client.post(
            "/auth/email/verify-code",
            json={"email": email, "code": "123456"},
        )

        assert response.status_code == 200
        assert has_consent(user_id) is False


