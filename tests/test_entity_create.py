from __future__ import annotations

import uuid

import pytest
from werkzeug.security import generate_password_hash


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


def _make_user(db):
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email="creator@test.com",
        username="creator@test.com",
        first_name="Normal",
        last_name="User",
        password=generate_password_hash("password123"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_normal_user_can_create_entity_and_becomes_entity_admin(app, client, db_session):
    from models.db import Entity, EntitySaleSetting, User, UserEntity

    with app.app_context():
        creator = _make_user(db_session)
        creator_id = creator.id

    _login(client, creator_id)

    response = client.post(
        "/entity/create",
        data={
            "entity_name": "Creator Admin Entity",
            "country_code": "HK",
            "currency_code": "HKD",
            "contact_phone": "12345678",
            "business_email": "entity@test.com",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/entity/success")

    with app.app_context():
        created_entity = Entity.query.filter_by(name="Creator Admin Entity").one()
        membership = UserEntity.query.filter_by(
            user_id=creator_id, entity_id=created_entity.id
        ).one()
        refreshed_creator = User.query.get(creator_id)

        assert membership.role == "admin"
        assert refreshed_creator is not None
        assert not hasattr(refreshed_creator, "company")
        assert EntitySaleSetting.query.filter_by(entity_id=created_entity.id).count() > 0
