from __future__ import annotations

import uuid

import pytest
from werkzeug.security import generate_password_hash


def _login(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = user_id



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

    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        creator = _make_user(db_session)
        creator_id = creator.id
        # a signed-in person has agreed to the Terms; otherwise the acceptance gate answers
        # the POST itself with a redirect to the entity list and the view never runs
        record_consent(creator_id, source="gate")
        db_session.session.commit()

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
    assert "/entity/success?entity_id=" in response.location  # the success page names the company

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
