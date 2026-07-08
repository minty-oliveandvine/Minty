from __future__ import annotations

import uuid

import pytest
from werkzeug.security import generate_password_hash


_schema_attached = False


@pytest.fixture
def db_session(app):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
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
    created after the emailed code is verified — see the OTP verify test below."""
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

    # The page just re-renders so the JS OTP flow can run; no user is created.
    assert response.status_code == 200
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

    verify = client.post(
        "/auth/email/verify-code",
        json={
            "email": email,
            "code": sent["code"],
            "first_name": "New",
            "last_name": "User",
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


def test_register_page_no_longer_exposes_role_or_company_input(client):
    response = client.get("/register")

    assert response.status_code == 200
    assert b'name="role"' not in response.data
    assert b'name="company"' not in response.data
    assert b"Select your role" not in response.data


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
