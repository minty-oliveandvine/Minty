"""``blueprints.subscription.services.store_ro`` - the subscription reads Flask still makes.

The engine is minty-subscription-api; these are the questions the rest of Flask asks before it
lets someone leave, be demoted or switch a module off, and the entity list's trial badge. Run
over real rows, because each one is a query whose filter IS the rule.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import char_factories as F

UTC = timezone.utc


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        payer = F.make_user(db, "payer@test.com")
        other = F.make_user(db, "other@test.com")
        entity = F.make_entity(db, payer, name="Corner Shop")
    return {"payer": payer, "other": other, "entity": entity}


def _row(db, entity_id, payer_id, *, code="PETTY_CASH", phase="active", billed=True,
         trial_end=None, access_until=None):
    from models.db import EntityModuleSubscription

    row = EntityModuleSubscription(
        entity_id=entity_id, function_code=code, payer_user_id=payer_id, phase=phase,
        first_billed_at=datetime.now(UTC) - timedelta(days=40) if billed else None,
        trial_end=trial_end, app_access_until=access_until,
    )
    db.session.add(row)
    db.session.commit()


def test_payer_and_rows(app, db, shop):
    from blueprints.subscription.services import store_ro

    eid, payer = shop["entity"].id, shop["payer"].id
    with app.app_context():
        assert store_ro.payer_for_entity(eid) is None
        assert store_ro.rows_for_entity(eid) == []
        _row(db, eid, payer)
        assert store_ro.payer_for_entity(eid) == payer
        assert [r.payer_user_id for r in store_ro.rows_for_entity(eid)] == [payer]
        assert store_ro.payer_for_entity("") is None


def test_entities_paid_for_by_names_every_company_whatever_its_phase(app, db, shop):
    from blueprints.subscription.services import store_ro

    with app.app_context():
        second = F.make_entity(db, shop["payer"], name="Annex")
        _row(db, shop["entity"].id, shop["payer"].id, phase="past_due")
        _row(db, second.id, shop["payer"].id, phase="cancelled", billed=False)
        assert store_ro.entities_paid_for_by(shop["payer"].id) == sorted(
            [(shop["entity"].id, "Corner Shop"), (second.id, "Annex")]
        )
        assert store_ro.entities_paid_for_by(shop["other"].id) == []


def test_only_an_open_handover_is_pending(app, db, shop):
    from blueprints.subscription.services import store_ro
    from models.db import SubscriptionTransfer

    eid = shop["entity"].id
    with app.app_context():
        assert store_ro.pending_transfer_for_entity(eid) is None
        for status in ("declined", "pending"):
            db.session.add(SubscriptionTransfer(
                entity_id=eid, from_user_id=shop["payer"].id, to_user_id=shop["other"].id,
                status=status, expires_at=datetime.now(UTC) + timedelta(days=7),
            ))
            db.session.commit()
        offer = store_ro.pending_transfer_for_entity(eid)
        assert offer is not None and offer.status == "pending"
        assert offer.to_user_id == shop["other"].id


@pytest.mark.parametrize(
    "phase, billed, paid",
    [
        ("active", True, True),
        ("past_due", True, True),
        ("scheduled_cancel", True, True),    # a paid module winding down
        ("scheduled_cancel", False, False),  # a cancelled trial
        ("trial", False, False),
        ("cancelled", True, False),
        ("expired", True, False),
    ],
)
def test_module_is_paid_locks_only_a_billed_module(app, db, shop, phase, billed, paid):
    from blueprints.subscription.services import store_ro

    eid = shop["entity"].id
    with app.app_context():
        _row(db, eid, shop["payer"].id, phase=phase, billed=billed)
        assert store_ro.module_is_paid(eid, "petty_cash") is paid
        assert store_ro.module_is_paid(eid, "PAYMENT_REQUEST") is False


def test_the_trial_badge(app, db, shop):
    from blueprints.subscription.services import store_ro

    payer = shop["payer"].id
    now = datetime.now(UTC)
    with app.app_context():
        running = shop["entity"].id
        closing = F.make_entity(db, shop["payer"], name="Closing").id
        lapsed = F.make_entity(db, shop["payer"], name="Lapsed").id
        paid = F.make_entity(db, shop["payer"], name="Paid").id
        _row(db, running, payer, phase="trial", billed=False, trial_end=now + timedelta(days=3))
        # past its end but inside the window the daily pass gets to close it out
        _row(db, closing, payer, phase="trial", billed=False, trial_end=now - timedelta(hours=1))
        _row(db, lapsed, payer, phase="trial", billed=False, trial_end=now - timedelta(days=2))
        _row(db, paid, payer, phase="active", trial_end=now - timedelta(days=60))

        badges = store_ro.trial_modules_for_entities([running, closing, lapsed, paid])

    assert badges == {running: {"PETTY_CASH"}, closing: {"PETTY_CASH"}}


def test_store_ro_never_writes():
    """Read-only by contract: a write here would be a second writer of the subscription tables,
    which minty-subscription-api owns."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "blueprints/subscription/services/store_ro.py").read_text(encoding="utf-8")
    session_calls = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "session"
    }
    # execute() reads the database clock; rollback() undoes a failed READ (see the badge).
    assert session_calls <= {"execute", "rollback"}, session_calls
    assert ".update(" not in source and ".delete(" not in source
