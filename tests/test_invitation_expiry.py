"""Tests for invitation expiry (7-day TTL, Hong Kong time).

Covered:
  * create_invitation stamps expires_at ~7 days out (HK tz).
  * accept_invitation rejects an expired pending invite and marks it expired.
  * create_invitation lets an expired pending invite be superseded by a resend.
  * A non-expired invite still accepts normally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest


# --------------------------------------------------------------------------- #
# Helpers / fixtures (mirrors tests/test_invitation.py)
# --------------------------------------------------------------------------- #

def _make_user(db, User, email, role="cashier", approved=True):
    from werkzeug.security import generate_password_hash

    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        email=email,
        username=email,
        first_name="Test",
        last_name="User",
        password=generate_password_hash("password123"),
        system_role=User.legacy_role_to_system_role(role),
        approved=approved,
    )
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    user._cached_id = uid
    return user


def _make_entity(db, Entity, name="Test Corp"):
    eid = str(uuid.uuid4())
    entity = Entity(
        id=eid,
        name=name,
        country_code="HK",
        currency_code="HKD",
        status="disconnected",
    )
    db.session.add(entity)
    db.session.commit()
    db.session.refresh(entity)
    entity._cached_id = eid
    return entity


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


@pytest.fixture
def models(app):
    from blueprints.invitation.models.invitation import Invitation
    from models.db import Entity, User, UserEntity

    return {
        "User": User,
        "Entity": Entity,
        "UserEntity": UserEntity,
        "Invitation": Invitation,
    }


def _localize(dt):
    """Normalize a possibly-naive HK datetime to tz-aware for comparison."""
    from models.db import tz

    if dt is None:
        return None
    return tz.localize(dt) if dt.tzinfo is None else dt


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_create_invitation_sets_expires_at_about_7_days(app, db_session, models):
    from models.db import tz

    with app.app_context():
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, models["User"], email="admin@test.com", role="admin")

        from blueprints.invitation.services.invite import create_invitation

        inv, err = create_invitation(entity.id, "new@test.com", "cashier", inviter.id)
        assert err is None and inv is not None
        assert inv.expires_at is not None

        delta = _localize(inv.expires_at) - datetime.now(tz)
        # ~7 days, allowing slack for execution time.
        assert timedelta(days=6, hours=23) < delta <= timedelta(days=7, minutes=1)


def test_accept_expired_invitation_is_rejected(app, db_session, models):
    from models.db import tz

    with app.app_context():
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, models["User"], email="admin2@test.com", role="admin")
        invitee = _make_user(db_session, models["User"], email="late@test.com", role="cashier")

        from blueprints.invitation.services.invite import (
            accept_invitation,
            create_invitation,
        )

        inv, _ = create_invitation(entity.id, "late@test.com", "cashier", inviter.id)

        # Force expiry into the past.
        inv.expires_at = datetime.now(tz) - timedelta(minutes=1)
        db_session.session.commit()

        entity_id, err, hint = accept_invitation(inv.token, invitee.id)
        assert entity_id is None
        assert err is not None and "expired" in err.lower()

        refreshed = models["Invitation"].query.get(inv.id)
        assert refreshed.status == "expired"
        # No membership should have been created.
        assert models["UserEntity"].query.filter_by(
            user_id=invitee.id, entity_id=entity.id
        ).first() is None


def test_expired_pending_does_not_block_resend(app, db_session, models):
    from models.db import tz

    with app.app_context():
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, models["User"], email="admin3@test.com", role="admin")

        from blueprints.invitation.services.invite import create_invitation

        first, err = create_invitation(entity.id, "resend@test.com", "cashier", inviter.id)
        assert err is None and first is not None

        # Expire the first invite, then resend.
        first.expires_at = datetime.now(tz) - timedelta(minutes=1)
        db_session.session.commit()

        second, err2 = create_invitation(entity.id, "resend@test.com", "cashier", inviter.id)
        assert err2 is None
        assert second is not None
        assert second.token != first.token

        # The stale one is marked expired, not left pending.
        assert models["Invitation"].query.get(first.id).status == "expired"


def test_accept_valid_invitation_within_window(app, db_session, models):
    with app.app_context():
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, models["User"], email="admin4@test.com", role="admin")
        invitee = _make_user(db_session, models["User"], email="ontime@test.com", role="cashier")

        from blueprints.invitation.services.invite import (
            accept_invitation,
            create_invitation,
        )

        inv, _ = create_invitation(entity.id, "ontime@test.com", "shop_manager", inviter.id)
        entity_id, err, _hint = accept_invitation(inv.token, invitee.id)

        assert err is None
        assert entity_id == entity.id
        assert models["Invitation"].query.get(inv.id).status == "accepted"
