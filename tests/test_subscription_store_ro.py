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


# --- the entity list's attention flags (minty-subscription-api's module card, mirrored) ----


def _card(db, entity_id, payer_id, *, paid_through, dunning_started_at=None):
    """The billing account ``payer_id`` pays ``entity_id`` from: its cycle and its dunning
    stamp (``payer_billing_group``), and the nomination that points the company at it."""
    from models.db import EntityBillingGroup, PayerBillingGroup

    group = PayerBillingGroup(payer_user_id=payer_id, stripe_payment_method_id="pm_test",
                              paid_through=paid_through, dunning_started_at=dunning_started_at)
    db.session.add(group)
    db.session.flush()
    db.session.add(EntityBillingGroup(entity_id=entity_id, payer_user_id=payer_id,
                                      billing_group_id=group.id, source="chosen"))
    db.session.commit()


def test_the_attention_flags_default_to_nothing(app, db, shop):
    from blueprints.subscription.services import store_ro

    with app.app_context():
        assert store_ro.subscription_attention_for_entities([]) == {}
        assert store_ro.subscription_attention_for_entities([shop["entity"].id]) == {}
        _row(db, shop["entity"].id, shop["payer"].id, phase="active")
        _card(db, shop["entity"].id, shop["payer"].id,
              paid_through=datetime.now(UTC) + timedelta(days=10))
        assert store_ro.subscription_attention_for_entities([shop["entity"].id]) == {
            shop["entity"].id: {"trials": {}, "payment_failed": False}
        }


def test_each_trial_carries_the_day_it_ends(app, db, shop):
    """The same rule as the badge - ``app_access_until`` (a cancelled trial's promise) before
    ``trial_end`` - with the instant, so the list can name the earliest."""
    from blueprints.subscription.services import store_ro

    eid, payer = shop["entity"].id, shop["payer"].id
    now = datetime.now(UTC).replace(microsecond=0)
    with app.app_context():
        _row(db, eid, payer, phase="trial", billed=False, trial_end=now + timedelta(days=9))
        _row(db, eid, payer, code="PAYMENT_REQUEST", phase="scheduled_cancel", billed=False,
             trial_end=now + timedelta(days=20), access_until=now + timedelta(days=4))
        trials = store_ro.subscription_attention_for_entities([eid])[eid]["trials"]

    assert trials == {"PETTY_CASH": now + timedelta(days=9),
                      "PAYMENT_REQUEST": now + timedelta(days=4)}


@pytest.mark.parametrize(
    "case, failed",
    [
        # dunning is running: the card was declined and the customer told
        ("declined, inside the window", True),
        # held past due while the PROCESSOR failed: nobody was asked, nothing failed
        ("processor hold, nobody told", False),
        # the window has run out: access has ended, the card says nothing more
        ("declined, window over", False),
        # no billing account behind the company: nothing paid through, no access to lose
        ("no account", False),
        # the paid-cancel promise still running keeps access, so it still shows
        ("declined, access promised", True),
        # a handover's parked first charge pays the company through later than its card
        ("declined, parked handover", True),
    ],
)
def test_payment_failed_is_the_module_cards_past_due(app, db, shop, case, failed):
    """minty-subscription-api's ``cards.get_module_cards`` says ``past_due`` only for a
    past-due module that still grants access (``access.grants_access``: paid-through plus
    the past-due window, or ``app_access_until``) on a card whose customer was TOLD
    (``dunning.told_of_failure``)."""
    from blueprints.subscription.services import store_ro
    from models.db import SubscriptionTransfer

    eid, payer = shop["entity"].id, shop["payer"].id
    now = datetime.now(UTC)
    with app.app_context():
        access_until = now + timedelta(days=3) if case == "declined, access promised" else None
        _row(db, eid, payer, phase="past_due", access_until=access_until)
        if case == "declined, inside the window":
            _card(db, eid, payer, paid_through=now - timedelta(days=2),
                  dunning_started_at=now - timedelta(days=2))
        elif case == "processor hold, nobody told":
            _card(db, eid, payer, paid_through=now - timedelta(days=2))
        elif case in ("declined, window over", "declined, access promised"):
            _card(db, eid, payer, paid_through=now - timedelta(days=20),
                  dunning_started_at=now - timedelta(days=20))
        elif case == "declined, parked handover":
            _card(db, eid, payer, paid_through=now - timedelta(days=20),
                  dunning_started_at=now - timedelta(days=20))
            db.session.add(SubscriptionTransfer(
                entity_id=eid, from_user_id=shop["other"].id, to_user_id=payer,
                status="accepted", expires_at=now + timedelta(days=7),
            ))
            db.session.commit()
            db.session.execute(
                db.text(f"UPDATE {store_ro.SCHEMA}.subscription_transfer SET collect_at = :at"),
                {"at": now - timedelta(days=5)},
            )
            db.session.commit()
        attention = store_ro.subscription_attention_for_entities([eid])

    assert attention[eid]["payment_failed"] is failed


def test_the_past_due_window_is_the_policy_rows(app, db, shop):
    """A shorter window (``billing_policy.past_due_window_days``) ends access sooner; an
    incoherent row falls back to the shipped 15 days, as ``policy._dunning_pair`` does."""
    from blueprints.subscription.services import store_ro
    from models.db import BillingPolicy

    eid, payer = shop["entity"].id, shop["payer"].id
    now = datetime.now(UTC)
    with app.app_context():
        _row(db, eid, payer, phase="past_due")
        _card(db, eid, payer, paid_through=now - timedelta(days=7),
              dunning_started_at=now - timedelta(days=7))
        assert store_ro.subscription_attention_for_entities([eid])[eid]["payment_failed"] is True

        db.session.add(BillingPolicy(id=1, past_due_window_days=5, retry_offsets_days="1,2,3"))
        db.session.commit()
        assert store_ro.subscription_attention_for_entities([eid])[eid]["payment_failed"] is False

        # last retry on day 4 of a 5-day window leaves under two days to settle: incoherent
        BillingPolicy.query.get(1).retry_offsets_days = "1,2,4"
        db.session.commit()
        assert store_ro.subscription_attention_for_entities([eid])[eid]["payment_failed"] is True


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
