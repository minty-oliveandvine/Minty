"""The onboarding wizard's view of enabled modules must match the request gate.

Two code paths answer one question -- "is this module on for this entity" -- and they
have drifted before. ``onboarding_state._enabled_modules`` resolved the map itself and,
where an entity had no map row, fell back to the catalog's ``is_active`` (which defaults
True); ``routes.modules._is_module_enabled`` denies. So a fresh entity reported BOTH
modules enabled to the wizard, ``_derive_current_step`` skipped past STEP_MODULE, and the
user landed beyond the module selection they had not made -- on modules the gate then
refused.

What is pinned here is AGREEMENT between the two, not any one answer. A third
implementation is exactly how the drift happened, so the assertions compare the two
callers against each other rather than against a hardcoded list.
"""
from __future__ import annotations

import uuid

import pytest

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


def _catalog(db):
    """Both canonical modules present and OFFERED (``is_active=True``).

    is_active True is the point: it is the value the dropped fallback keyed on, so this
    is the state in which a permissive resolver wrongly grants.
    """
    from models.db import EntityFunction

    rows = {}
    for code in ("PETTY_CASH", "PAYMENT_REQUEST"):
        row = EntityFunction(
            id=str(uuid.uuid4()),
            function_code=code,
            function_name=code.title(),
            is_active=True,
        )
        db.session.add(row)
        rows[code] = row
    db.session.commit()
    return rows


def _grant(db, entity_id, function_row, *, enabled: bool):
    from models.db import EntityFunctionMap

    db.session.add(
        EntityFunctionMap(
            entity_id=entity_id,
            entity_function_id=function_row.id,
            is_enabled=enabled,
        )
    )
    db.session.commit()


def _both_views(entity_id):
    """(wizard answer, gate answer) as comparable sorted lists of codes."""
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import MODULE_CODES
    from blueprints.entity.services.onboarding_state import _enabled_modules

    wizard = sorted(_enabled_modules(entity_id))
    gate = sorted(c for c in MODULE_CODES if _is_module_enabled(entity_id, c))
    return wizard, gate


def test_no_map_rows_means_nothing_is_enabled(app, db_session):
    """The regression itself: offered-but-never-granted must read as OFF on both sides."""
    _catalog(db_session)
    entity_id = str(uuid.uuid4())

    with app.app_context():
        wizard, gate = _both_views(entity_id)

    assert wizard == [], "a module nobody granted must not show as enabled to the wizard"
    assert wizard == gate


def test_an_explicit_grant_shows_on_both_sides(app, db_session):
    catalog = _catalog(db_session)
    entity_id = str(uuid.uuid4())
    _grant(db_session, entity_id, catalog["PETTY_CASH"], enabled=True)

    with app.app_context():
        wizard, gate = _both_views(entity_id)

    assert wizard == ["PETTY_CASH"]
    assert wizard == gate


def test_an_explicitly_disabled_grant_is_off_on_both_sides(app, db_session):
    catalog = _catalog(db_session)
    entity_id = str(uuid.uuid4())
    _grant(db_session, entity_id, catalog["PETTY_CASH"], enabled=False)
    _grant(db_session, entity_id, catalog["PAYMENT_REQUEST"], enabled=True)

    with app.app_context():
        wizard, gate = _both_views(entity_id)

    assert wizard == ["PAYMENT_REQUEST"]
    assert wizard == gate


def test_the_wizard_lands_on_the_module_step_when_nothing_is_granted(app, db_session):
    """The user-visible half of the bug, pinned at the step it decides.

    ``_derive_current_step`` is documented as conservative -- "a user who stopped after
    basic information lands back on the module step" -- which is precisely what the
    permissive resolver defeated.
    """
    from blueprints.entity.services import onboarding_state

    _catalog(db_session)
    entity_id = str(uuid.uuid4())
    entity = type("_E", (), {"status": "onboarding"})()

    with app.app_context():
        modules = onboarding_state._enabled_modules(entity_id)
        step = onboarding_state._derive_current_step(
            entity, modules, {"connected": False}, False
        )

    assert step == onboarding_state.STEP_MODULE
