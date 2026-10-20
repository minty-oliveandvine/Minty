"""Creating a company makes its creator the company's admin - through the onboarding wizard's
``POST /api/onboarding/create`` (Flask's ``POST /entity/create`` form went 2026-10-20; both used
``create_entity_for_user``)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from werkzeug.security import generate_password_hash


def _onboarding_bearer(app, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    payload = {"user_id": user_id, "scope": "onboarding", "exp": now + timedelta(minutes=10), "iat": now}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}



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

    import char_factories as F

    with app.app_context():
        creator_id = _make_user(db_session).id
        F.seed_country(db_session, F.seed_currency(db_session))

    response = client.post(
        "/api/onboarding/create",
        json={
            "entity_name": "Creator Admin Entity",
            "country_code": "HK",
            "currency_code": "HKD",
            "contact_phone": "12345678",
            "business_email": "entity@test.com",
        },
        headers=_onboarding_bearer(app, creator_id),
    )

    assert response.status_code == 201, response.get_json()

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
