"""Handing a subscription to a new payer — the refusals, and the three failure windows.

The accept cannot be one transaction: ``store``'s helpers each commit their own unit of
work, and by the time a card declines the invoice row is already on disk. So the guarantee
is ORDER — charge first, flip second — and the offer row is the journal that closes the
gap between the two.

These run against the real model on SQLite rather than a mocked session, because the
things worth proving are the journal's state transitions and the partial unique index, and
a stubbed session proves neither. Only the CHARGE is mocked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc
NOW = datetime(2027, 8, 20, tzinfo=UTC)
PAID_THROUGH = datetime(2027, 9, 12, tzinfo=UTC)
PERIOD_END = datetime(2027, 10, 1, tzinfo=UTC)

OLD, NEW = "payer-old", "payer-new"
ENTITY = "entity-1"

_attached = False


@pytest.fixture
def db_session(app):
    global _attached
    from models.db import db

    with app.app_context():
        if not _attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _attached = True
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


def _user(User, uid, email, approved):
    """A minimally valid ``user`` row — password/first/last are NOT NULL."""
    return User(id=uid, username=email, email=email, password="x",
                first_name="A", last_name="B", approved=approved)


class _Row:
    """An ``entity_module_subscription`` stand-in — only the fields the rules read."""

    def __init__(self, code="BILL", phase="active", ext_state=None, ext_amount=None):
        self.entity_id = ENTITY
        self.function_code = code
        self.phase = phase
        self.payer_user_id = OLD
        self.extension_state = ext_state
        self.extension_amount = ext_amount
        self.billed_through = None


def _wire(monkeypatch, db, *, rows=None, payer=OLD, dunning=(), admin=True,
          approved=True, card=True, charge=None):
    """Mock what sits either side of the service; return (transfers, calls)."""
    from blueprints.subscription.services import checkout, clock, store, transfers
    from models.db import User, UserEntity

    calls = {"charges": [], "consent": [], "audit": [], "flips": [], "swept": []}

    monkeypatch.setattr(clock, "now", lambda: NOW)
    monkeypatch.setattr(transfers.clock, "now", lambda: NOW)
    monkeypatch.setattr(store, "rows_for_entity",
                        lambda eid: list(rows if rows is not None else [_Row()]))
    monkeypatch.setattr(store, "payer_for_entity", lambda eid: payer)
    monkeypatch.setattr(store, "payer_is_dunning", lambda uid: uid in dunning)
    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: PAID_THROUGH)
    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: "cus_new")
    monkeypatch.setattr(
        store, "transfer_entity_payer",
        lambda eid, new, **kw: calls["flips"].append((eid, new, kw.get("billed_through"))),
    )
    monkeypatch.setattr(
        store, "record_billing_consent",
        lambda eid, uid, src: calls["consent"].append((eid, uid, src)),
    )
    monkeypatch.setattr(
        store, "record_action",
        lambda **kw: calls["audit"].append(kw),
    )
    monkeypatch.setattr(
        "blueprints.subscription.services.stripe_client.customer_default_payment_method",
        lambda cid: "pm_1" if card else None,
    )
    monkeypatch.setattr(
        "blueprints.entity.services.modules.sweep_expired_module_access",
        lambda payer_user_id=None: calls["swept"].append(payer_user_id),
    )

    def _charge(entity_id, payer_user_id, customer_id, codes, *, at, idempotency_key):
        calls["charges"].append({"at": at, "key": idempotency_key})
        if callable(charge):
            return charge(len(calls["charges"]))
        return charge or {"paid": True, "period_end": PERIOD_END, "invoice_id": "in_1",
                          "amount": 19000, "currency": "HKD", "reason": None}

    monkeypatch.setattr(checkout, "_bill_transfer_in_house", _charge)

    # A real, approved admin membership for the nominee unless a test says otherwise.
    db.session.add(_user(User, NEW, "new@test.com", approved))
    db.session.add(_user(User, OLD, "old@test.com", True))
    if admin:
        db.session.add(UserEntity(user_id=NEW, entity_id=ENTITY,
                                  role="admin", approved=True))
    db.session.commit()
    return transfers, calls


def _offer(db, transfers, *, status="pending", attempt=0, key=None, expires=None):
    from models.db import SubscriptionTransfer

    row = SubscriptionTransfer(
        id="t1", entity_id=ENTITY, from_user_id=OLD, to_user_id=NEW,
        status=status, charge_attempt=attempt, charge_key=key,
        expires_at=expires or (NOW + timedelta(days=7)),
        accepted_billed_through=PAID_THROUGH if status != "pending" else None,
    )
    db.session.add(row)
    db.session.commit()
    return row


# --- the refusals ------------------------------------------------------------------


def test_only_the_current_payer_may_hand_the_company_over(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session)
    reasons = transfers.transfer_blockers(ENTITY, from_user_id="someone", to_user_id=NEW)
    assert any("Only the person currently being billed" in r for r in reasons)


def test_an_entity_nobody_pays_for_has_nothing_to_hand_over(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session, payer=None)
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("Nobody is being billed" in r for r in reasons)


def test_a_payer_mid_dunning_cannot_hand_the_debt_off(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session, dunning={OLD})
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("still being collected on this account" in r for r in reasons)


def test_a_recipient_mid_dunning_cannot_take_one_on(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session, dunning={NEW})
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("can't take on" in r for r in reasons)


def test_an_unbilled_cancellation_charge_blocks_it(db_session, monkeypatch):
    """The debt rides the row, so moving the row moves it onto the new payer's invoice
    and makes it uncollectable from whoever actually incurred it."""
    transfers, _ = _wire(
        monkeypatch, db_session,
        rows=[_Row(ext_state="pending", ext_amount=2746)],
    )
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("unbilled cancellation charge" in r for r in reasons)


def test_a_module_on_trial_blocks_it(db_session, monkeypatch):
    """It would convert onto the new card against the OLD payer's consent, with no
    warning email — the trial notice is deduped per entity and already went out."""
    transfers, _ = _wire(monkeypatch, db_session, rows=[_Row(phase="trial")])
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("still on trial" in r for r in reasons)


def test_a_non_admin_cannot_be_handed_the_bill(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session, admin=False)
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("needs to be an admin" in r for r in reasons)


def test_a_deactivated_account_cannot_be_handed_the_bill(db_session, monkeypatch):
    """``_admin_candidates`` checks the membership flags but not ``User.approved``, so a
    deactivated admin is still on the list this validates against."""
    transfers, _ = _wire(monkeypatch, db_session, approved=False)
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("isn't active" in r for r in reasons)


def test_no_saved_card_blocks_it(db_session, monkeypatch):
    """Without one nothing can be charged at all — ``start_billing_cycle`` silently
    no-ops for a payer with no customer row, so the accept would fail at the charge
    having already promised to succeed."""
    transfers, _ = _wire(monkeypatch, db_session, card=False)
    reasons = transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW)
    assert any("saved payment method" in r for r in reasons)


def test_a_clean_handover_has_no_blockers(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session)
    assert transfers.transfer_blockers(ENTITY, from_user_id=OLD, to_user_id=NEW) == []


# --- the offer ----------------------------------------------------------------------


def test_only_one_offer_may_be_open_per_company(db_session, monkeypatch):
    """The partial unique index is the real guard; the pre-check only makes the message
    better. Both are exercised here."""
    transfers, _ = _wire(monkeypatch, db_session)

    ok, _msg, _ = transfers.offer_transfer(OLD, ENTITY, NEW)
    assert ok is True
    ok2, msg2, _ = transfers.offer_transfer(OLD, ENTITY, NEW)
    assert ok2 is False and "already a handover waiting" in msg2


def test_you_cannot_hand_a_company_to_yourself(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session)
    ok, msg, _ = transfers.offer_transfer(OLD, ENTITY, OLD)
    assert ok is False and "already the one being billed" in msg


# --- accept: the money and the ordering ----------------------------------------------


def test_accept_charges_then_flips(db_session, monkeypatch):
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    ok, _msg, result = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is True
    assert len(calls["charges"]) == 1
    assert calls["flips"] == [(ENTITY, NEW, PERIOD_END)]
    assert calls["consent"] == [(ENTITY, NEW, "transfer")]
    assert offer.status == "accepted"
    assert result["invoice_id"] == "in_1"


def test_the_handover_instant_is_read_at_accept_not_quoted_at_offer(db_session, monkeypatch):
    """``paid_through`` advances on every successful renewal, so an offer that outlives a
    cycle would otherwise bill a window the old payer has since paid for."""
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    moved = datetime(2027, 10, 12, tzinfo=UTC)
    from blueprints.subscription.services import store

    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: moved)

    transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert calls["charges"][0]["at"] == moved


def test_a_decline_leaves_the_company_where_it_was(db_session, monkeypatch):
    transfers, calls = _wire(
        monkeypatch, db_session,
        charge={"paid": False, "period_end": None, "invoice_id": None, "amount": 0,
                "currency": None, "reason": "That payment didn't go through."},
    )
    offer = _offer(db_session, transfers)

    ok, msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is False and "didn't go through" in msg
    assert calls["flips"] == [], "the pointer must not move"
    assert calls["consent"] == []
    assert offer.status == "pending", "back to pending so it can be retried"
    assert offer.charge_attempt == 1


def test_a_retry_after_a_decline_uses_a_fresh_key(db_session, monkeypatch):
    """THE trap. Voiding an invoice deliberately keeps its row and its key claimed, so a
    key that did not change between attempts would be refused as "already claimed" and
    the customer could never retry after fixing their card."""
    outcomes = {1: {"paid": False, "period_end": None, "invoice_id": None, "amount": 0,
                    "currency": None, "reason": "declined"},
                2: {"paid": True, "period_end": PERIOD_END, "invoice_id": "in_2",
                    "amount": 19000, "currency": "HKD", "reason": None}}
    transfers, calls = _wire(monkeypatch, db_session, charge=lambda n: outcomes[n])
    offer = _offer(db_session, transfers)

    assert transfers.respond_to_transfer(NEW, offer.id, accept=True)[0] is False
    assert transfers.respond_to_transfer(NEW, offer.id, accept=True)[0] is True

    keys = [c["key"] for c in calls["charges"]]
    assert keys == ["transfer-t1-1", "transfer-t1-2"], keys
    assert len(set(keys)) == 2, "a retry must not reuse the claimed key"


def test_an_accept_that_died_after_the_charge_is_finished_not_recharged(db_session, monkeypatch):
    """The crash window. The row says ``charged``, so the money is in and only the flip
    is missing — a retried accept must complete it and charge nothing."""
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers, status="charged", attempt=1,
                   key="transfer-t1-1")

    ok, _msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is True
    assert calls["charges"] == [], "the money was already taken"
    assert calls["flips"] == [(ENTITY, NEW, PAID_THROUGH)]
    assert offer.status == "accepted"


def test_the_repair_step_finishes_a_stranded_handover(db_session, monkeypatch):
    """The push half of the same recovery, for when nobody ever clicks again."""
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers, status="charged", attempt=1,
                   key="transfer-t1-1")

    result = transfers.repair_stranded(NOW)

    assert result["completed"] == [offer.id]
    assert calls["charges"] == []
    assert calls["flips"] == [(ENTITY, NEW, PAID_THROUGH)]
    assert offer.status == "accepted"


def test_the_repair_step_does_nothing_when_nothing_is_stranded(db_session, monkeypatch):
    """It reads a partial index that is empty in the normal case, so the nightly pass
    costs nothing."""
    transfers, calls = _wire(monkeypatch, db_session)
    _offer(db_session, transfers, status="pending")

    assert transfers.repair_stranded(NOW) == {
        "completed": [], "released": [], "waiting": []
    }
    assert calls["flips"] == []


def test_a_charging_row_the_processor_never_saw_is_released(db_session, monkeypatch):
    """Reserved, never confirmed, and the processor has no record — so the key is free
    again and the offer goes back to pending for a clean retry."""
    from blueprints.subscription.services import renewals

    transfers, calls = _wire(monkeypatch, db_session)
    monkeypatch.setattr(renewals, "_already_invoiced", lambda cid, key, **kw: None)
    offer = _offer(db_session, transfers, status="charging", attempt=1,
                   key="transfer-t1-1")

    result = transfers.repair_stranded(NOW)

    assert result["released"] == [offer.id]
    assert offer.status == "pending"
    assert calls["flips"] == []


def test_an_unpaid_raised_invoice_is_left_alone(db_session, monkeypatch):
    """Forcing it either way here would either bill twice or give the company away."""
    from blueprints.subscription.services import renewals

    transfers, calls = _wire(monkeypatch, db_session)
    monkeypatch.setattr(renewals, "_already_invoiced", lambda cid, key, **kw: "open")
    offer = _offer(db_session, transfers, status="charging", attempt=1,
                   key="transfer-t1-1")

    result = transfers.repair_stranded(NOW)

    assert result["waiting"] == [offer.id]
    assert offer.status == "charging"
    assert calls["flips"] == []


# --- expiry, decline, cancel ---------------------------------------------------------


def test_an_expired_offer_cannot_be_accepted(db_session, monkeypatch):
    """Checked HERE, not only by a sweep — otherwise "expires in 7 days" quietly means
    "expires whenever something next looks at it"."""
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers, expires=NOW - timedelta(days=1))

    ok, msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is False and "expired" in msg
    assert offer.status == "expired"
    assert calls["charges"] == []


def test_an_offer_sent_to_someone_else_cannot_be_accepted(db_session, monkeypatch):
    transfers, _ = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    ok, msg, _ = transfers.respond_to_transfer("interloper", offer.id, accept=True)

    assert ok is False and "sent to someone else" in msg


def test_declining_closes_the_offer_and_moves_nothing(db_session, monkeypatch):
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    ok, _msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=False)

    assert ok is True and offer.status == "declined"
    assert calls["charges"] == [] and calls["flips"] == []


def test_the_initiator_can_withdraw_a_pending_offer(db_session, monkeypatch):
    """Without this their own exit depends indefinitely on someone else answering."""
    transfers, _ = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    ok, _msg = transfers.cancel_transfer(OLD, offer.id)

    assert ok is True and offer.status == "cancelled"


def test_a_handover_being_charged_cannot_be_withdrawn(db_session, monkeypatch):
    """Cancelling mid-charge would strand money already being collected."""
    transfers, _ = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers, status="charging", attempt=1)

    ok, msg = transfers.cancel_transfer(OLD, offer.id)

    assert ok is False and "already being processed" in msg


def test_a_nominee_demoted_since_the_offer_invalidates_it(db_session, monkeypatch):
    """Re-checked at ACCEPT, not only when the list was drawn. Otherwise the pointer
    could be aimed at someone who is no longer a member at all."""
    transfers, calls = _wire(monkeypatch, db_session, admin=False)
    offer = _offer(db_session, transfers)

    ok, msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is False and "needs to be an admin" in msg
    assert offer.status == "cancelled", "permanently invalid, not merely deferred"
    assert calls["charges"] == []


def test_a_temporary_blocker_leaves_the_offer_standing(db_session, monkeypatch):
    """A debt clears on its own; the offer should still be there when it does."""
    transfers, _ = _wire(monkeypatch, db_session, dunning={OLD})
    offer = _offer(db_session, transfers)

    ok, _msg, _ = transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert ok is False
    assert offer.status == "pending"


# --- the audit trail -------------------------------------------------------------------


def test_the_handover_is_recorded_with_both_parties(db_session, monkeypatch):
    """A transfer is the first action here with two of them, and a row naming one loses
    the only question anyone asks afterwards."""
    transfers, calls = _wire(monkeypatch, db_session,
                             rows=[_Row("BILL"), _Row("PETTY_CASH")])
    offer = _offer(db_session, transfers)

    transfers.respond_to_transfer(NEW, offer.id, accept=True)

    accepted = [a for a in calls["audit"] if a["action"] == "transfer_accepted"]
    assert {a["function_code"] for a in accepted} == {"BILL", "PETTY_CASH"}
    assert all(a["payer_before"] == OLD and a["payer_after"] == NEW for a in accepted)


def test_module_access_is_resynced_after_the_flip(db_session, monkeypatch):
    """Nothing else does it at a handover — dunning re-syncs on recovery, the light pass
    only for payers it touched."""
    transfers, calls = _wire(monkeypatch, db_session)
    offer = _offer(db_session, transfers)

    transfers.respond_to_transfer(NEW, offer.id, accept=True)

    assert calls["swept"] == [NEW]
