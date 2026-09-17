from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)


def _login(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = user_id


_schema_attached = False


@pytest.fixture
def db_session(app):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv3"))
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


def _make_user(db, *, system_role: str) -> str:
    from models.db import User

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        email=f"{user_id}@test.com",
        username=f"{user_id}@test.com",
        first_name="Profile",
        last_name="Tester",
        password=generate_password_hash("password123"),
        system_role=system_role,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    return user_id


def _make_entity(db) -> str:
    from models.db import Entity

    entity_id = str(uuid.uuid4())
    entity = Entity(
        id=entity_id,
        name="Profile Entity",
        # no country: an FK to a reference row this test does not seed
        # currency_code left entities in C2 (currency_id FK)
    )
    db.session.add(entity)
    db.session.commit()
    return entity_id


def _add_membership(db, *, user_id: str, entity_id: str, role: str) -> None:
    from datetime import datetime

    from models.db import UserEntity

    membership = UserEntity(
        user_id=user_id,
        entity_id=entity_id,
        role=role,
        approved=True,
        joined_at=datetime.utcnow(),
    )
    db.session.add(membership)
    db.session.commit()


def test_my_profile_returns_system_role_and_memberships(app, db_session, monkeypatch):
    from blueprints.user_management.routes import roles as roles_routes
    from models.db import User

    with app.app_context():
        entity_id = _make_entity(db_session)
        user_id = _make_user(
            db_session,
            system_role=User.SYSTEM_ROLE_NORMAL,
        )
        _add_membership(
            db_session,
            user_id=user_id,
            entity_id=entity_id,
            role="accountant",
        )
        current_user = User.query.filter_by(id=user_id).one()

    monkeypatch.setattr(roles_routes, "current_user", current_user)

    with app.test_request_context("/minty/api/users/me", method="GET"):
        response, status = roles_routes.get_my_profile.__wrapped__()

    assert status == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "success"
    assert payload["user"]["system_role"] == "normal"
    assert "company" not in payload["user"]
    assert "role" not in payload["user"]
    assert payload["memberships"] == [
        {
            "entity_id": entity_id,
            "role": "accountant",
            "approved": True,
        }
    ]


@pytest.mark.parametrize(
    ("template_name", "expected_system_role_reference"),
    [
        ("admin.html", "current_user.system_role"),
        ("admin_dashboard.html", "user.system_role"),
        ("report_detail.html", "current_user.system_role"),
    ],
)
def test_templates_depend_on_system_role_not_legacy_role(
    template_name, expected_system_role_reference
):
    template_path = Path(__file__).resolve().parents[1] / "templates" / template_name
    contents = template_path.read_text(encoding="utf-8")

    assert expected_system_role_reference in contents
    assert "current_user.role" not in contents
    assert "user.role" not in contents
