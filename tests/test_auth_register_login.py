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


def test_register_creates_normal_approved_user_by_default(app, client, db_session):
    from models.db import User

    response = client.post(
        "/register",
        data={
            "first_name": "New",
            "last_name": "User",
            "username": "new.user",
            "password": "password123",
            "confirm_password": "password123",
            "email": "new.user@test.com",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/login")

    with app.app_context():
        created_user = User.query.filter_by(username="new.user").one()
        assert created_user.system_role == User.SYSTEM_ROLE_NORMAL
        assert created_user.approved is True
        assert not hasattr(created_user, "company")


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
