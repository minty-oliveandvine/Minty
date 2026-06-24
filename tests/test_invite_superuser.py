"""Tests for auto-promoting the dailyminty view-all account to superuser.

When ``viewall@dailyminty.com`` is invited (or accepts), its User row must be a
system superuser. Covered:
  * _is_auto_superuser_email predicate (case-insensitive, default config).
  * create_invitation promotes an already-existing row for that email.
  * accept_invitation promotes the user (the create-at-accept path).
  * A normal invitee is NOT promoted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest


VIEWALL = "viewall@dailyminty.com"


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
        status="active",
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


# --------------------------------------------------------------------------- #
# Predicate
# --------------------------------------------------------------------------- #

def test_is_auto_superuser_email_matches_viewall(app):
    # Depend on ``app`` so the application module graph is imported first
    # (avoids a circular import when this test runs before any app fixture).
    from blueprints.invitation.services.invite import _is_auto_superuser_email

    assert _is_auto_superuser_email(VIEWALL) is True
    # Case-insensitive + surrounding whitespace tolerant.
    assert _is_auto_superuser_email("  ViewAll@DailyMinty.COM ") is True
    # Everything else is not auto-promoted.
    assert _is_auto_superuser_email("someone@test.com") is False
    assert _is_auto_superuser_email("") is False
    assert _is_auto_superuser_email(None) is False


# --------------------------------------------------------------------------- #
# create_invitation — promotes an existing row
# --------------------------------------------------------------------------- #

def test_create_invitation_promotes_existing_viewall_user(app, db_session, models):
    with app.app_context():
        User = models["User"]
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, User, email="admin@test.com", role="admin")
        # The view-all account already exists as a plain (non-super) user.
        viewall = _make_user(db_session, User, email=VIEWALL, role="cashier")
        assert viewall.system_role != User.SYSTEM_ROLE_SUPERUSER

        from blueprints.invitation.services.invite import create_invitation

        inv, err = create_invitation(entity.id, VIEWALL, "cashier", inviter.id)
        assert err is None and inv is not None

        promoted = User.query.get(viewall.id)
        assert promoted.system_role == User.SYSTEM_ROLE_SUPERUSER
        assert promoted.approved is True


# --------------------------------------------------------------------------- #
# accept_invitation — promotes the user (create-at-accept path)
# --------------------------------------------------------------------------- #

def test_accept_invitation_promotes_viewall_user(app, db_session, models):
    with app.app_context():
        User = models["User"]
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, User, email="admin2@test.com", role="admin")

        from blueprints.invitation.services.invite import (
            accept_invitation,
            create_invitation,
        )

        # Invite first; the User row for the view-all account is created
        # afterwards (mirrors the OTP / Xero create-at-accept flow).
        inv, err = create_invitation(entity.id, VIEWALL, "cashier", inviter.id)
        assert err is None and inv is not None

        invitee = _make_user(db_session, User, email=VIEWALL, role="cashier")
        assert invitee.system_role != User.SYSTEM_ROLE_SUPERUSER

        entity_id, err, _hint = accept_invitation(inv.token, invitee.id)
        assert err is None
        assert entity_id == entity.id

        promoted = User.query.get(invitee.id)
        assert promoted.system_role == User.SYSTEM_ROLE_SUPERUSER
        assert promoted.approved is True


def test_accept_invitation_does_not_promote_normal_user(app, db_session, models):
    with app.app_context():
        User = models["User"]
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(db_session, User, email="admin3@test.com", role="admin")
        invitee = _make_user(db_session, User, email="normal@test.com", role="cashier")

        from blueprints.invitation.services.invite import (
            accept_invitation,
            create_invitation,
        )

        inv, err = create_invitation(entity.id, "normal@test.com", "cashier", inviter.id)
        assert err is None and inv is not None

        entity_id, err, _hint = accept_invitation(inv.token, invitee.id)
        assert err is None

        not_promoted = User.query.get(invitee.id)
        assert not_promoted.system_role != User.SYSTEM_ROLE_SUPERUSER
