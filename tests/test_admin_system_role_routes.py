from __future__ import annotations

import uuid

import pytest
from werkzeug.security import generate_password_hash


def _login(client, user_id: str) -> None:
    from blueprints.legal.services.gate import TERMS_OK_SESSION_KEY
    from legal import registry

    with client.session_transaction() as sess:
        sess["_user_id"] = user_id
        # A logged-in user who has not accepted the Terms is redirected to
        # /legal/accept by the acceptance gate — correctly, and for every
        # product route. These tests are about admin role routes, so the
        # session carries the same "already agreed" marker a real accepted
        # user has.
        sess[TERMS_OK_SESSION_KEY] = registry.current_version(registry.TERMS)


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


def _make_user(db, *, email: str, system_role: str, approved: bool = True) -> str:
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        username=email,
        first_name="Admin",
        last_name="Tester",
        password=generate_password_hash("password123"),
        system_role=system_role,
        approved=approved,
    )
    db.session.add(user)
    db.session.commit()
    return user.id


@pytest.mark.parametrize("path", ["/admin", "/admin_dashboard"])
def test_normal_user_cannot_access_admin_pages(path, app, client, db_session):
    from models.db import User

    with app.app_context():
        user_id = _make_user(
            db_session,
            email=f"normal-{path.strip('/').replace('/', '-') or 'root'}@test.com",
            system_role=User.SYSTEM_ROLE_NORMAL,
        )

    _login(client, user_id)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/index")


@pytest.mark.parametrize("path", ["/admin", "/admin_dashboard"])
def test_superuser_can_access_admin_pages(path, app, client, db_session):
    from models.db import User

    with app.app_context():
        user_id = _make_user(
            db_session,
            email=f"super-{path.strip('/').replace('/', '-') or 'root'}@test.com",
            system_role=User.SYSTEM_ROLE_SUPERUSER,
        )

    _login(client, user_id)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("endpoint_template", "expected_approved"),
    [
        ("/approve_user/{user_id}", True),
        ("/reject_user/{user_id}", False),
    ],
)
def test_normal_user_cannot_change_admin_access_actions(
    endpoint_template, expected_approved, app, client, db_session
):
    from models.db import User

    with app.app_context():
        actor_id = _make_user(
            db_session,
            email="normal-admin-action@test.com",
            system_role=User.SYSTEM_ROLE_NORMAL,
        )
        target_id = _make_user(
            db_session,
            email=f"target-{expected_approved}@test.com",
            system_role=User.SYSTEM_ROLE_NORMAL,
            approved=not expected_approved,
        )

    _login(client, actor_id)

    response = client.post(
        endpoint_template.format(user_id=target_id),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/admin_dashboard")

    with app.app_context():
        target_user = User.query.filter_by(id=target_id).one()
        assert target_user.approved is (not expected_approved)


@pytest.mark.parametrize(
    ("endpoint_template", "starting_approved", "expected_approved"),
    [
        ("/approve_user/{user_id}", False, True),
        ("/reject_user/{user_id}", True, False),
    ],
)
def test_superuser_can_change_admin_access_actions(
    endpoint_template, starting_approved, expected_approved, app, client, db_session
):
    from models.db import User

    with app.app_context():
        actor_id = _make_user(
            db_session,
            email=f"super-admin-action-{expected_approved}@test.com",
            system_role=User.SYSTEM_ROLE_SUPERUSER,
        )
        target_id = _make_user(
            db_session,
            email=f"super-target-{expected_approved}@test.com",
            system_role=User.SYSTEM_ROLE_NORMAL,
            approved=starting_approved,
        )

    _login(client, actor_id)

    response = client.post(
        endpoint_template.format(user_id=target_id),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/admin_dashboard")

    with app.app_context():
        target_user = User.query.filter_by(id=target_id).one()
        assert target_user.approved is expected_approved
