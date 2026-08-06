"""Access is a PROJECTION of the subscription row, and every unknown answers no.

``entity_module_subscription`` is the record of truth; ``entity_function_map.is_enabled``
only caches it so a request costs one indexed lookup instead of a join. That makes two
rules load-bearing, and neither had a test:

* **The gate fails closed.** No map row, or no catalog row, means NO. It used to fall
  through to the catalog's ``is_active``, which granted a module to every entity that
  had never subscribed to it.
* **The sweep revokes what nothing backs.** A module switched on with no subscription
  row is the one inconsistency no event can repair — trials and cancellations fire on
  writes, but "enabled and never subscribed" has no write to hang off. The sweep used
  to skip exactly that case, so it survived forever: the user was inside the module
  while its card still offered "Start free trial".

Mid-onboarding entities are the deliberate exception — the wizard records its Step 2
selection in the map and only starts the trials at finalize.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc

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


def _entity(db, *, status="active", name="Acme"):
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


def _grant(db, entity, fn, *, enabled=True, actor="entity_create"):
    from models.db import EntityFunctionMap

    row = EntityFunctionMap(
        id=str(uuid.uuid4()),
        entity_id=entity.id,
        entity_function_id=fn.id,
        is_enabled=enabled,
        created_by=actor,
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
        fn = _function(db_session, "BILL", is_active=False)

        _grant(db_session, entity, fn, enabled=True)
        assert _is_module_enabled(entity.id, "BILL") is True

        row = fn.entity_mappings[0]
        row.is_enabled = False
        db_session.session.commit()
        assert _is_module_enabled(entity.id, "BILL") is False


def test_entity_creation_grants_nothing(app, db_session):
    """A new entity holds no module until a trial or subscription starts one."""
    from blueprints.entity.services.modules import (DEFAULT_MODULE_STATE,
                                                    apply_default_modules)
    from blueprints.entity.routes.modules import _is_module_enabled

    assert DEFAULT_MODULE_STATE == {"PETTY_CASH": False, "BILL": False}

    with app.app_context():
        entity = _entity(db_session)
        _function(db_session, "PETTY_CASH", is_active=True)
        _function(db_session, "BILL", is_active=True)

        _data, status = apply_default_modules(entity.id)
        assert status == 200

        assert _is_module_enabled(entity.id, "PETTY_CASH") is False
        assert _is_module_enabled(entity.id, "BILL") is False


# --- the sweep --------------------------------------------------------------


def test_sweep_revokes_access_with_no_subscription_row(app, db_session):
    """The case that used to be skipped, and so never got repaired."""
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        entity = _entity(db_session)
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True)

        assert _is_module_enabled(entity.id, "PETTY_CASH") is True

        result = sweep_expired_module_access()

        assert {"entity_id": entity.id, "code": "PETTY_CASH"} in result["disabled"]
        assert _is_module_enabled(entity.id, "PETTY_CASH") is False


def test_sweep_exempts_entities_still_onboarding(app, db_session):
    """Between Step 2's selection and finalize's trial start, enabled-with-no-row is
    the expected state — revoking there would leave finalize nothing to start."""
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        entity = _entity(db_session, status="onboarding")
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True, actor="onboarding")

        result = sweep_expired_module_access()

        assert result["disabled"] == []
        assert _is_module_enabled(entity.id, "PETTY_CASH") is True


def _naive_clock(monkeypatch):
    """Make the sweep's clock naive for the duration of a test.

    SQLite drops tzinfo on the way back out, so a stored ``app_access_until`` returns
    naive while ``clock.now()`` is aware — and comparing them raises inside the sweep's
    per-entity ``except``, which swallows it and reports "nothing lapsed". The date
    branches are then untestable and, worse, quietly appear to pass. Production stores
    timestamptz and has neither problem, so this aligns the harness rather than the code.
    """
    from datetime import datetime as _dt

    from blueprints.subscription.services import clock as clock_mod

    monkeypatch.setattr(clock_mod, "now", lambda: _dt.now())


def test_sweep_terminates_a_cancellation_whose_access_ran_out(app, db_session, monkeypatch):
    """The date that ends access also ends the SUBSCRIPTION.

    Leaving the row on ``scheduled_cancel`` meant a module nobody could use still read
    as mid-cancellation forever — the panel offering Renew for something already over,
    and ``_in_cancellation_window`` refusing to let them buy it again. ``cancelled`` is
    terminal and re-purchasable, which is the state they are actually in.
    """
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        _naive_clock(monkeypatch)
        entity = _entity(db_session)
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True, actor="subscription")

        past = datetime.now() - timedelta(days=1)
        row = _sub_row(
            db_session, entity, "PETTY_CASH",
            phase="scheduled_cancel", app_access_until=past,
        )

        result = sweep_expired_module_access()

        assert {"entity_id": entity.id, "code": "PETTY_CASH"} in result["disabled"]
        assert _is_module_enabled(entity.id, "PETTY_CASH") is False
        db_session.session.refresh(row)
        assert row.phase == "cancelled"
        # Cleared: a leftover date on a terminal row is a trap for any reader that
        # checks dates before phases.
        assert row.app_access_until is None


def test_sweep_does_not_terminate_a_cancellation_still_running(app, db_session, monkeypatch):
    """Cancelled but still inside its paid days is NOT over — it is the one state where
    Renew is the right offer, and terminating it early would take that away."""
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        _naive_clock(monkeypatch)
        entity = _entity(db_session)
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True, actor="subscription")

        future = datetime.now() + timedelta(days=10)
        row = _sub_row(
            db_session, entity, "PETTY_CASH",
            phase="scheduled_cancel", app_access_until=future,
        )

        result = sweep_expired_module_access()

        assert result["disabled"] == []
        assert _is_module_enabled(entity.id, "PETTY_CASH") is True
        db_session.session.refresh(row)
        assert row.phase == "scheduled_cancel"


def test_sweep_leaves_an_ended_trial_to_the_trial_job(app, db_session, monkeypatch):
    """A trial past its end is NOT terminated here: convert-or-expire is a decision this
    job cannot make, and stamping ``cancelled`` over it would rob the trial-end job of
    the row it converts. Access still comes off — that part is a date, not a decision."""
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        _naive_clock(monkeypatch)
        entity = _entity(db_session)
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True, actor="subscription")

        past = datetime.now() - timedelta(days=1)
        row = _sub_row(
            db_session, entity, "PETTY_CASH",
            phase="trial", trial_end=past, app_access_until=past,
        )

        sweep_expired_module_access()

        db_session.session.refresh(row)
        assert row.phase == "trial"


def test_sweep_leaves_a_running_trial_alone(app, db_session):
    """Regression guard: the revoke-on-no-row branch must not swallow live trials."""
    from blueprints.entity.routes.modules import _is_module_enabled
    from blueprints.entity.services.modules import sweep_expired_module_access

    with app.app_context():
        entity = _entity(db_session)
        pc = _function(db_session, "PETTY_CASH", is_active=False)
        _function(db_session, "BILL", is_active=False)
        _grant(db_session, entity, pc, enabled=True, actor="subscription")

        future = datetime.now(UTC) + timedelta(days=10)
        _sub_row(
            db_session, entity, "PETTY_CASH",
            phase="trial", trial_end=future, app_access_until=future,
        )

        result = sweep_expired_module_access()

        assert result["disabled"] == []
        assert _is_module_enabled(entity.id, "PETTY_CASH") is True
