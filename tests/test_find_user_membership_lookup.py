from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)


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

def _make_entity(db, *, name: str) -> str:
    from models.db import Entity

    entity_id = str(uuid.uuid4())
    entity = Entity(
        id=entity_id,
        name=name,
        country_code="HK",
        currency_code="HKD",
    )
    db.session.add(entity)
    db.session.commit()
    return entity_id


def _make_user(
    db,
    *,
    username: str,
    first_name: str,
    last_name: str,
    system_role: str,
) -> str:
    from models.db import User

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        email=f"{username}@test.com",
        username=username,
        first_name=first_name,
        last_name=last_name,
        password=generate_password_hash("password123"),
        system_role=system_role,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    return user_id


def _add_membership(db, *, user_id: str, entity_id: str, role: str) -> None:
    from models.db import UserEntity

    membership = UserEntity(
        user_id=user_id,
        entity_id=entity_id,
        role=role,
        approved=True,
        joined_at=datetime.utcnow(),
        create_at=datetime.utcnow(),
    )
    db.session.add(membership)
    db.session.commit()


def test_find_user_uses_membership_entity_lookup_instead_of_user_company(
    app, db_session, monkeypatch
):
    from blueprints.user_management.routes import find_user as find_user_routes
    from models.db import User

    with app.app_context():
        lookup_entity_id = _make_entity(db_session, name="Lookup Entity")
        admin_id = _make_user(
            db_session,
            username="finder.admin",
            first_name="Finder",
            last_name="Admin",
            system_role=User.SYSTEM_ROLE_NORMAL,
        )
        target_id = _make_user(
            db_session,
            username="target.user",
            first_name="Target",
            last_name="User",
            system_role=User.SYSTEM_ROLE_NORMAL,
        )
        _add_membership(
            db_session,
            user_id=admin_id,
            entity_id=lookup_entity_id,
            role="admin",
        )
        _add_membership(
            db_session,
            user_id=target_id,
            entity_id=lookup_entity_id,
            role="cashier",
        )
        current_user = User.query.filter_by(id=admin_id).one()

    monkeypatch.setattr(
        find_user_routes, "has_permission", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(find_user_routes, "current_user", current_user)
    monkeypatch.setattr(
        find_user_routes,
        "render_template",
        lambda template_name, **context: {"template": template_name, "context": context},
    )

    with app.test_request_context(
        "/find_user",
        method="POST",
        data={
            "first_name": "Target",
            "last_name": "User",
            "entity_id": lookup_entity_id,
        },
    ):
        response = find_user_routes.find_user.__wrapped__()

    assert response["template"] == "find_user.html"
    assert response["context"]["userid"].username == "target.user"
