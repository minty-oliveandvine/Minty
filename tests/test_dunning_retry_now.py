"""Customer-initiated collection: settle a past-due account on the spot.

Automatic retries run on a 1/4/7/10/13-day schedule. Without a manual path a customer
fixes their card and then waits up to three days, still locked out, with nothing to press —
``addPaymentMethod`` saves a card and settles nothing by itself.

``retry_now`` is ``collect_due``'s per-account body minus ONE thing, the schedule gate.
These tests pin exactly that: the pacing is skipped, and every guard around it is not.

  skipped   should_attempt_now  — paces the cron, has no business blocking the customer
  KEPT      should_give_up      — collection must never outlive access
  KEPT      the attempt budget  — bounds how often a card can be hit, however triggered
  KEPT      settle-then-clear   — entitle them to what they just paid for

It keys on the DEBT — the open invoice — not on ``dunning_started_at``. The stamp is
bookkeeping for the schedule; the invoice is what is owed. Asking the stamp first told a
payer with a real unpaid invoice "no outstanding payment" while the page beside the button
read "payment due".

And a payer with NO card is never charged: the attempt cannot succeed, so spending a
retry slot on it would burn the budget one press at a time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

FAILED_AT = datetime(2027, 2, 9, 13, tzinfo=UTC)
PAID_THROUGH = datetime(2027, 2, 8, 13, tzinfo=UTC)
# One day in: BEFORE the first scheduled retry slot at +1 day would fire on its own, and
# well inside the 15-day window.
NOW = FAILED_AT + timedelta(hours=2)


class _Account:
    def __init__(self, *, started=FAILED_AT, attempts=0, paid_through=PAID_THROUGH):
        self.user_id = "u1"
        self.anchor_at = datetime(2027, 1, 8, 13, tzinfo=UTC)
        self.paid_through = paid_through
        self.stripe_customer_id = "cus_u1"
        self.dunning_started_at = started
        self.dunning_attempts = attempts


def _wire(app, monkeypatch, *, account, invoices=None, paid=True, reason="ok",
          card="pm_1"):
    """Point the store, the gateway and the card lookup at fakes; return (dunning, calls)."""
    from blueprints.subscription.services import billing_gateway, clock, dunning, store

    calls = {"attempts": 0, "ended": [], "settled": [], "retried": []}

    monkeypatch.setattr(clock, "now", lambda: NOW)
    monkeypatch.setattr(store, "customer_mapping_for_user", lambda uid: account)
    # Patched BY DOTTED PATH: retry_now imports it inside the function, so a reference
    # captured here would not be the one it ends up calling.
    monkeypatch.setattr(
        "blueprints.subscription.services.stripe_client."
        "customer_default_payment_method",
        lambda cid: card,
    )

    def _attempt(uid):
        calls["attempts"] += 1
        account.dunning_attempts = int(account.dunning_attempts or 0) + 1
        return account.dunning_attempts

    monkeypatch.setattr(store, "record_dunning_attempt", _attempt)
    monkeypatch.setattr(
        store, "end_dunning",
        lambda uid, *, status="active": calls["ended"].append((uid, status)),
    )
    monkeypatch.setattr(
        dunning, "_settle_period",
        lambda acct, inv: calls["settled"].append(inv["id"] if inv else None),
    )
    monkeypatch.setattr(
        billing_gateway, "open_invoices",
        lambda cid: [] if invoices is None else invoices,
    )

    def _retry(invoice_id):
        calls["retried"].append(invoice_id)
        return paid, reason

    monkeypatch.setattr(billing_gateway, "retry_invoice", _retry)
    return dunning, calls


INVOICES = [{"id": "in_1"}]


def test_it_charges_even_when_no_scheduled_slot_is_due(app, monkeypatch):
    """THE point. Two hours after the failure no automatic retry is due, and the cron
    would do nothing — the customer pressing Pay now must still be collected."""
    from blueprints.subscription.services import dunning as _d

    account = _Account()
    dunning, calls = _wire(app, monkeypatch, account=account, invoices=INVOICES)

    with app.app_context():
        # Guard the premise: the scheduled path really would decline to act right now.
        assert _d.should_attempt_now(NOW, FAILED_AT, 0, (1, 3, 5, 7), 10) is False

        result = dunning.retry_now("u1")

    assert result["status"] == "paid"
    assert calls["retried"] == ["in_1"]
    assert calls["ended"] == [("u1", "active")]


def test_a_successful_retry_settles_the_period_before_clearing_dunning(app, monkeypatch):
    """Order matters: clearing first would collect the money and leave them unentitled
    until the next monthly run adopted the invoice."""
    dunning, calls = _wire(app, monkeypatch, account=_Account(), invoices=INVOICES)

    with app.app_context():
        dunning.retry_now("u1")

    assert calls["settled"] == ["in_1"]
    assert calls["ended"] == [("u1", "active")]


def test_a_decline_leaves_the_account_in_dunning(app, monkeypatch):
    """Still recoverable — they can try another card, and the cron keeps its remaining
    slots. Closing here would end the subscription on one refused attempt."""
    dunning, calls = _wire(
        app, monkeypatch, account=_Account(), invoices=INVOICES,
        paid=False, reason="card_declined",
    )

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "failed"
    assert result["reason"] == "card_declined"
    assert calls["ended"] == [], "a decline must not close collection"
    assert calls["settled"] == []


def test_the_attempt_is_counted_against_the_same_budget(app, monkeypatch):
    """A manual retry is a charge attempt like any other. Sharing the budget is what
    bounds how many times a card can be hit, however the retry was triggered."""
    account = _Account(attempts=1)
    dunning, calls = _wire(app, monkeypatch, account=account, invoices=INVOICES)

    with app.app_context():
        result = dunning.retry_now("u1")

    assert calls["attempts"] == 1
    assert result["attempts"] == 2


def test_it_refuses_past_the_give_up_deadline(app, monkeypatch):
    """Collection must never outlive access. Past the deadline this closes the account
    exactly as the cron would, rather than charging a card for someone locked out."""
    account = _Account(started=FAILED_AT - timedelta(days=30))
    dunning, calls = _wire(app, monkeypatch, account=account, invoices=INVOICES)

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "gave_up"
    assert calls["retried"] == [], "no card may be charged past the deadline"
    assert calls["ended"] == [("u1", "closed")]


def test_nothing_owed_closes_dunning_rather_than_charging(app, monkeypatch):
    """Settled elsewhere — a portal payment, a manual charge. Same handling as the
    scheduled path, or the customer has paid and stays locked out."""
    dunning, calls = _wire(app, monkeypatch, account=_Account(), invoices=[])

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "nothing_owed"
    assert calls["retried"] == []
    assert calls["ended"] == [("u1", "active")]
    assert calls["settled"] == [None]


def test_an_unpaid_invoice_is_collected_even_with_no_dunning_stamp(app, monkeypatch):
    """The reported bug. A past-due module whose account carries no dunning stamp was
    told "There's no outstanding payment on this account" — while the card beside the
    button said "payment due".

    The debt is the open invoice. The stamp only schedules retries, and its absence
    means "nobody has started chasing this", not "nothing is owed".
    """
    dunning, calls = _wire(
        app, monkeypatch, account=_Account(started=None), invoices=INVOICES
    )

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "paid"
    assert calls["retried"] == ["in_1"]
    assert calls["settled"] == ["in_1"]
    # Nothing to clear: collection was never running.
    assert calls["ended"] == []


def test_no_card_is_reported_without_spending_an_attempt(app, monkeypatch):
    """A charge with nothing to charge cannot succeed, so it must not be made.

    Counting a slot for it would spend the retry budget on a guaranteed decline, and
    every press would spend another — leaving the customer fewer automatic retries for
    having tried to help.
    """
    account = _Account(attempts=1)
    dunning, calls = _wire(
        app, monkeypatch, account=account, invoices=INVOICES, card=None
    )

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "no_card"
    assert result["invoice"] == "in_1", "still names the debt it could not collect"
    assert calls["retried"] == [], "no charge may be attempted with no card"
    assert calls["attempts"] == 0, "and no slot may be spent on it"
    assert account.dunning_attempts == 1
    assert calls["ended"] == [], "still owed, so collection stays open"


def test_a_decline_reports_the_processors_reason(app, monkeypatch):
    """"insufficient funds" and "card expired" need different things from the customer."""
    dunning, _ = _wire(
        app, monkeypatch, account=_Account(), invoices=INVOICES,
        paid=False, reason="Your card has insufficient funds.",
    )

    with app.app_context():
        result = dunning.retry_now("u1")

    assert result["status"] == "failed"
    assert result["reason"] == "Your card has insufficient funds."


def test_no_billing_account_is_not_an_error(app, monkeypatch):
    dunning, calls = _wire(app, monkeypatch, account=None, invoices=INVOICES)

    with app.app_context():
        assert dunning.retry_now("u1")["status"] == "nothing_owed"
    assert calls["retried"] == []
