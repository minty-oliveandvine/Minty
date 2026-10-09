from __future__ import annotations

import uuid

import pytest
from werkzeug.security import generate_password_hash



@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def test_register_post_does_not_create_user_without_otp(app, client, db_session):
    """Registration is OTP-gated: a plain form POST to /register must NOT create
    an account (that would be an unverified-email bypass). The account is only
    created after the emailed code is verified — see the OTP verify test below.
    Since phase 2 the route only forwards to minty-web's sign-up."""
    from models.db import User

    response = client.post(
        "/register",
        data={
            "first_name": "New",
            "last_name": "User",
            "email": "new.user@test.com",
        },
        follow_redirects=False,
    )

    # Forwarded to the hub's sign-up; no user is created.
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/signup")
    with app.app_context():
        assert User.query.filter_by(email="new.user@test.com").first() is None


def test_register_otp_verify_creates_normal_approved_user(app, client, db_session, monkeypatch):
    """The full OTP path: request a code, then verify it with name + email. That
    verify (POST /auth/email/verify-code) is what creates the passwordless,
    approved, normal-role account and returns a login handoff URL."""
    import blueprints.auth.services.email_auth as email_auth
    from models.db import User

    # Don't actually send mail in tests.
    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: True)
    # Capture the generated code so we can verify with it.
    sent = {}
    real_gen = email_auth.generate_otp

    def _capture():
        sent["code"] = real_gen()
        return sent["code"]

    monkeypatch.setattr(email_auth, "generate_otp", _capture)

    email = "new.user@test.com"
    req = client.post("/auth/email/request-code", json={"email": email})
    assert req.status_code == 200

    from legal import registry

    verify = client.post(
        "/auth/email/verify-code",
        json={
            "email": email,
            "code": sent["code"],
            "first_name": "New",
            "last_name": "User",
            # Sign-up now refuses to create an account without an explicit
            # agreement to the live Terms (REQUIRE_TERMS_AT_SIGNUP). The real
            # clients send these; so does this test.
            "terms_accepted": True,
            "terms_version": registry.current_version(registry.TERMS),
        },
    )
    assert verify.status_code == 200
    body = verify.get_json()
    assert body["status"] == "success"
    assert body.get("redirect_url")

    with app.app_context():
        created_user = User.query.filter_by(email=email).one()
        assert created_user.system_role == User.SYSTEM_ROLE_NORMAL
        assert created_user.approved is True
        assert not hasattr(created_user, "company")

        # The consent row lands in the same transaction as the account, so a
        # successful sign-up always leaves both.
        from blueprints.legal.services.consent import has_consent

        assert has_consent(created_user.id) is True


def test_register_otp_verify_refuses_without_terms_agreement(
    app, client, db_session, monkeypatch
):
    """Phase 6: no agreement, no account.

    The old request shape — no terms fields — is now rejected outright rather
    than creating an account that the acceptance gate would have to catch later.
    """
    import blueprints.auth.services.email_auth as email_auth
    from models.db import User

    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: True)
    sent = {}
    real_gen = email_auth.generate_otp

    def _capture():
        sent["code"] = real_gen()
        return sent["code"]

    monkeypatch.setattr(email_auth, "generate_otp", _capture)

    email = "no.terms@test.com"
    assert client.post("/auth/email/request-code", json={"email": email}).status_code == 200

    verify = client.post(
        "/auth/email/verify-code",
        json={
            "email": email,
            "code": sent["code"],
            "first_name": "No",
            "last_name": "Terms",
        },
    )
    assert verify.status_code == 400
    assert "Terms of Use" in verify.get_json()["message"]

    with app.app_context():
        assert User.query.filter_by(email=email).first() is None


def test_register_otp_verify_rejects_wrong_code(app, client, db_session, monkeypatch):
    """A wrong code does not create an account and returns an error."""
    import blueprints.auth.services.email_auth as email_auth
    from models.db import User

    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: True)

    email = "wrong.code@test.com"
    client.post("/auth/email/request-code", json={"email": email})
    verify = client.post(
        "/auth/email/verify-code",
        json={
            "email": email,
            "code": "000000",
            "first_name": "Wrong",
            "last_name": "Code",
        },
    )
    assert verify.status_code in (400, 429)
    with app.app_context():
        assert User.query.filter_by(email=email).first() is None


def test_request_code_saves_nothing_when_the_email_fails(app, client, db_session, monkeypatch):
    """A code whose email never went out must not be saved. Committed before the
    send, it told the user a code was coming, started the resend cooldown (so
    their retry was refused) and made a brand-new address look registered."""
    import blueprints.auth.services.email_auth as email_auth
    from blueprints.auth.models.email_otp import EmailOtp

    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: False)

    email = "mail.outage@test.com"
    req = client.post("/auth/email/request-code", json={"email": email})
    assert req.status_code == 400
    assert req.get_json() == {
        "status": "error",
        "message": "I couldn't send your sign-in code just now. Mind trying again in a moment?",
    }

    with app.app_context():
        assert EmailOtp.query.filter_by(email=email).first() is None

    # ...so log-in mode still reads the address as unknown.
    check = client.post("/auth/email/request-code", json={"email": email, "mode": "login"})
    assert check.status_code == 404


def test_failed_code_email_keeps_the_previous_code_and_allows_a_retry(
    app, client, db_session, monkeypatch
):
    """A failed send rolls the whole request back: the previous row returns with
    its carried failure count (a mail outage must not reset the brute-force
    counter) and its old created_at, which is past the resend cooldown - so an
    immediate retry goes through."""
    from datetime import datetime, timedelta, timezone

    import blueprints.auth.services.email_auth as email_auth
    from blueprints.auth.models.email_otp import EmailOtp

    email = "retry.after.outage@test.com"
    issued = datetime.now(timezone.utc) - timedelta(
        seconds=email_auth.RESEND_COOLDOWN_SECONDS + 120
    )
    previous_id = str(uuid.uuid4())
    with app.app_context():
        db_session.session.add(
            EmailOtp(
                id=previous_id,
                email=email,
                code_hash=generate_password_hash("123456", method="pbkdf2:sha256"),
                expires_at=issued + timedelta(seconds=email_auth.OTP_EXPIRY_SECONDS),
                attempts=2,
                created_at=issued,
            )
        )
        db_session.session.commit()

    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: False)
    failed = client.post("/auth/email/request-code", json={"email": email})
    assert failed.status_code == 400

    with app.app_context():
        rows = EmailOtp.query.filter_by(email=email).all()
        assert [(row.id, row.attempts, row.created_at) for row in rows] == [
            (previous_id, 2, issued)
        ]

    monkeypatch.setattr(email_auth, "_send_code_email", lambda *a, **k: True)
    retry = client.post("/auth/email/request-code", json={"email": email})
    assert retry.status_code == 200

    with app.app_context():
        rows = EmailOtp.query.filter_by(email=email).all()
        # The retry supersedes the old code and still carries its failure count.
        assert len(rows) == 1
        assert rows[0].id != previous_id
        assert rows[0].attempts == 2


def test_login_redirects_superuser_to_admin(app, client, db_session):
    from models.db import User

    with app.app_context():
        user = User(
            id=str(uuid.uuid4()),
            email="super.user@test.com",
            username="super.user",
            first_name="Super",
            last_name="User",
            password=generate_password_hash("password123"),
            system_role=User.SYSTEM_ROLE_SUPERUSER,
            approved=True,
        )
        db_session.session.add(user)
        db_session.session.commit()

    response = client.post(
        "/login",
        data={"username": "super.user", "password": "password123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/admin")


def test_login_redirects_normal_user_to_home(app, client, db_session):
    from models.db import User

    with app.app_context():
        user = User(
            id=str(uuid.uuid4()),
            email="normal.user@test.com",
            username="normal.user",
            first_name="Normal",
            last_name="User",
            password=generate_password_hash("password123"),
            system_role=User.SYSTEM_ROLE_NORMAL,
            approved=True,
        )
        db_session.session.add(user)
        db_session.session.commit()

    response = client.post(
        "/login",
        data={"username": "normal.user", "password": "password123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/index")
