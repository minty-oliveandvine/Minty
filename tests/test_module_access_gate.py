"""Access is a PROJECTION of the subscription row, and every unknown answers no.

``entity_module_subscription`` is the record of truth; ``entity_function_map.is_enabled``
only caches it so a request costs one indexed lookup instead of a join. One rule is
load-bearing here:

* **The gate fails closed.** No map row, or no catalog row, means NO. It used to fall
  through to the catalog's ``is_active``, which granted a module to every entity that
  had never subscribed to it.

The sweep that revokes what nothing backs is minty-subscription-api's (``manage.py
subscriptions sweep-access``), tested there.
"""
from __future__ import annotations

import uuid
from datetime import timezone

import pytest

UTC = timezone.utc


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


def _entity(db, *, status="disconnected", name="Acme"):
    from models.db import Entity

    row = Entity(id=str(uuid.uuid4()), name=name, status=status)
    db.session.add(row)
    db.session.commit()
    return row


def _function(db, code, *, is_active):
    """A catalog row. ``is_active`` is deliberately varied in these tests — the gate
    must ignore it entirely when deciding who may use a module."""
    from models.db import EntityFunction

    row = EntityFunction(
        id=str(uuid.uuid4()),
        function_code=code,
        function_name=code.title(),
        is_active=is_active,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _grant(db, entity, fn, *, enabled=True, actor=None):
    # ``actor`` is accepted for the callers' readability only: entity_function_map.created_by
    # is the person (a user id or NULL, schema section 4), never a label.
    from models.db import EntityFunctionMap

    row = EntityFunctionMap(
        entity_id=entity.id,
        entity_function_id=fn.id,
        is_enabled=enabled,
        created_by=None,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _payer(db):
    from models.db import User

    row = User(
        id=str(uuid.uuid4()),
        email="payer@test.com",
        username="payer@test.com",
        first_name="Pay",
        last_name="Er",
        password="x",
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _sub_row(db, entity, code, *, phase, trial_end=None, app_access_until=None):
    from models.db import EntityModuleSubscription

    row = EntityModuleSubscription(
        id=str(uuid.uuid4()),
        entity_id=entity.id,
        function_code=code,
        payer_user_id=_payer(db).id,
        phase=phase,
        trial_end=trial_end,
        app_access_until=app_access_until,
    )
    db.session.add(row)
    db.session.commit()
    return row


# --- the gate ---------------------------------------------------------------


def test_no_map_row_denies_even_when_the_catalog_says_active(app, db_session):
    """The catalog's is_active says whether a module is OFFERED, never who may use it.

    This is the exact shape of the production bug: PETTY_CASH sat is_active=TRUE, so
    every entity without a map row resolved to ENABLED for free.
    """
    from blueprints.entity.routes.modules import _is_module_enabled

    with app.app_context():
        entity = _entity(db_session)
        _function(db_session, "PETTY_CASH", is_active=True)

        assert _is_module_enabled(entity.id, "PETTY_CASH") is False


def test_missing_catalog_row_denies(app, db_session):
    """Used to return True on the theory that the function row predated the gating
    table. A typo'd or not-yet-seeded code then opened the module to everyone."""
    from blueprints.entity.routes.modules import _is_module_enabled

    with app.app_context():
        entity = _entity(db_session)

        assert _is_module_enabled(entity.id, "NOT_A_MODULE") is False


def test_map_row_is_what_decides(app, db_session):
    from blueprints.entity.routes.modules import _is_module_enabled

    with app.app_context():
        entity = _entity(db_session)
        # is_active FALSE throughout: an explicit grant must still win.
        fn = _function(db_session, "PAYMENT_REQUEST", is_active=False)

        _grant(db_session, entity, fn, enabled=True)
        assert _is_module_enabled(entity.id, "PAYMENT_REQUEST") is True

        row = fn.entity_mappings[0]
        row.is_enabled = False
        db_session.session.commit()
        assert _is_module_enabled(entity.id, "PAYMENT_REQUEST") is False


def test_entity_creation_grants_nothing(app, db_session):
    """A new entity holds no module until a trial or subscription starts one."""
    from blueprints.entity.services.modules import (DEFAULT_MODULE_STATE,
                                                    apply_default_modules)
    from blueprints.entity.routes.modules import _is_module_enabled

    assert DEFAULT_MODULE_STATE == {"PETTY_CASH": False, "PAYMENT_REQUEST": False}

    with app.app_context():
        entity = _entity(db_session)
        _function(db_session, "PETTY_CASH", is_active=True)
        _function(db_session, "PAYMENT_REQUEST", is_active=True)

        _data, status = apply_default_modules(entity.id)
        assert status == 200

        assert _is_module_enabled(entity.id, "PETTY_CASH") is False
        assert _is_module_enabled(entity.id, "PAYMENT_REQUEST") is False
