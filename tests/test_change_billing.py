"""Unit tests for mid-period change billing.

The expected figures are ORACLE values — what Stripe actually charged on a test clock
while it was still the biller, captured before the cutover. They are the reason this can
be trusted: the in-house arithmetic reproduces them exactly.

    28.00  upgrade 280 -> 400, 7 of 30 days   (-65.33 credit + 93.33 charge)
   373.33  new line joining mid-period, 28 of 30 days
"""
from __future__ import annotations

# The price catalog is patched BY DOTTED PATH, not via an imported reference:
# conftest re-imports project modules mid-session, so a module object captured at
# import time is not the one the code under test ends up calling.
_CATALOG = "blueprints.subscription.services.catalog"

from datetime import datetime, timezone

from blueprints.subscription.services.billing import Period

UTC = timezone.utc


class _Plan:
    def __init__(self, name, amount, currency="HKD"):
        self.display_name = name
        self.amount = amount
        self.currency = currency


PLANS = {
    "BILL": _Plan("Payment Request", 28000),
    "PETTY_CASH": _Plan("Petty Cash", 28000),
    "BILL+PETTY_CASH": _Plan("Super Minty", 40000),
}


def _wire(monkeypatch, plans=None):
    from blueprints.subscription.services import changes, store
    catalog = PLANS if plans is None else plans
    monkeypatch.setattr(
        store, "billing_plan_for_codes",
        lambda codes: catalog.get("+".join(sorted(str(c).upper() for c in codes))),
    )
    return changes


# --- ORACLE: figures Stripe actually charged -----------------------------------


def test_oracle_upgrade_credits_the_old_price_and_charges_the_new(monkeypatch):
    """28.00 net = -65.33 unused Petty Cash + 93.33 remaining bundle, 7 of 30 days.

    Both lines are kept rather than the net: a customer shown only "28.00" cannot
    reconcile it against the 280.00 they paid three weeks earlier."""
    changes = _wire(monkeypatch)
    period = Period(datetime(2026, 9, 8, 13, tzinfo=UTC),
                    datetime(2026, 10, 8, 13, tzinfo=UTC))

    invoice = changes.build_change(
        "e1", "Alpha Co", ["PETTY_CASH"], ["PETTY_CASH", "BILL"],
        period, datetime(2026, 10, 1, 13, tzinfo=UTC),
    )

    assert [line.amount for line in invoice.lines] == [-6533, 9333]
    assert invoice.total == 2800


def test_oracle_a_new_line_joining_mid_period_has_nothing_to_credit(monkeypatch):
    """373.33 for 28 of 30 days. The entity was not paying for this period at all, so
    crediting anything would refund money never taken."""
    changes = _wire(monkeypatch)
    period = Period(datetime(2026, 11, 8, 13, tzinfo=UTC),
                    datetime(2026, 12, 8, 13, tzinfo=UTC))

    invoice = changes.build_change(
        "e2", "Beta Co", [], ["PETTY_CASH", "BILL"],
        period, datetime(2026, 11, 10, 13, tzinfo=UTC),
    )

    assert len(invoice.lines) == 1
    assert invoice.total == 37333


# --- what must NOT be billed ---------------------------------------------------


def test_a_downgrade_bills_nothing_and_credits_nothing(monkeypatch):
    """Access continues to what was already paid for. Crediting the unused time would
    refund days the customer still gets — the cancel path owns that decision and
    charges a prorated extension instead."""
    changes = _wire(monkeypatch)
    period = Period(datetime(2026, 9, 8, 13, tzinfo=UTC),
                    datetime(2026, 10, 8, 13, tzinfo=UTC))

    assert changes.build_change(
        "e1", "Alpha Co", ["PETTY_CASH", "BILL"], ["BILL"],
        period, datetime(2026, 10, 1, 13, tzinfo=UTC),
    ) is None


def test_no_change_bills_nothing(monkeypatch):
    changes = _wire(monkeypatch)
    period = Period(datetime(2026, 9, 8, 13, tzinfo=UTC),
                    datetime(2026, 10, 8, 13, tzinfo=UTC))

    assert changes.build_change(
        "e1", "Alpha Co", ["BILL"], ["BILL"], period,
        datetime(2026, 10, 1, 13, tzinfo=UTC),
    ) is None


def test_an_unpriceable_TARGET_is_refused_not_guessed(monkeypatch):
    """Summing standalone prices would silently overcharge by the bundle discount."""
    changes = _wire(monkeypatch, plans={"BILL": PLANS["BILL"]})
    period = Period(datetime(2026, 9, 8, 13, tzinfo=UTC),
                    datetime(2026, 10, 8, 13, tzinfo=UTC))

    assert changes.build_change(
        "e1", "Alpha Co", [], ["BILL", "PETTY_CASH"], period,
        datetime(2026, 10, 1, 13, tzinfo=UTC),
    ) is None


def test_an_unpriceable_CURRENT_set_is_refused_too(monkeypatch):
    """Without the old price there is no way to know what to credit — billing the full
    new price on top of one the customer already paid would double-charge them."""
    changes = _wire(monkeypatch, plans={"BILL+PETTY_CASH": PLANS["BILL+PETTY_CASH"]})
    period = Period(datetime(2026, 9, 8, 13, tzinfo=UTC),
                    datetime(2026, 10, 8, 13, tzinfo=UTC))

    assert changes.build_change(
        "e1", "Alpha Co", ["PETTY_CASH"], ["BILL", "PETTY_CASH"], period,
        datetime(2026, 10, 1, 13, tzinfo=UTC),
    ) is None


# --- billing twice -------------------------------------------------------------


def test_the_change_key_distinguishes_two_changes_in_the_same_minute(monkeypatch):
    """A customer can legitimately make two different changes to one entity moments
    apart; a key on time alone would silently swallow the second."""
    changes = _wire(monkeypatch)
    at = datetime(2026, 10, 1, 13, tzinfo=UTC)

    assert changes.change_key("e1", at, ["BILL"]) != changes.change_key(
        "e1", at, ["BILL", "PETTY_CASH"]
    )
    # ...and is stable for the same change, so a retry after a crash is recognised.
    assert changes.change_key("e1", at, ["PETTY_CASH", "BILL"]) == changes.change_key(
        "e1", at, ["BILL", "PETTY_CASH"]
    )


def test_an_already_invoiced_change_is_not_charged_again(monkeypatch):
    changes = _wire(monkeypatch)
    from blueprints.subscription.services import billing_gateway

    issued = []
    monkeypatch.setattr(
        billing_gateway, "find_invoice_by_metadata",
        lambda cid, k, v: {"id": "in_old", "status": "paid"},
    )
    monkeypatch.setattr(
        billing_gateway, "issue_invoice",
        lambda *a, **k: issued.append(a) or {"id": "in_new"},
    )
    period = Period(datetime(2026, 11, 8, 13, tzinfo=UTC),
                    datetime(2026, 12, 8, 13, tzinfo=UTC))

    result = changes.issue_change(
        "cus_1", "e2", "Beta Co", [], ["PETTY_CASH", "BILL"],
        period, datetime(2026, 11, 10, 13, tzinfo=UTC),
    )

    assert result["id"] == "in_old"
    assert issued == []          # nothing charged


# --- where "before" comes from --------------------------------------------------
#
# The arithmetic above was already right. What was wrong was its INPUT: the callers
# derived "what this entity already bills" from the payer's Stripe subscription items,
# which do not exist once billing is in-house. Every upgrade therefore arrived here with
# before=set(), took the join branch, and charged the standalone price on top of the
# period the customer had already paid for.
#
# A live run billed 65.33 for adding Payment Request to an entity already on Petty Cash,
# where the oracle above says 28.00. These tests pin the derivation, not the sums —
# passing before_codes in by hand (as every test above does) cannot catch it.


class _Row:
    def __init__(self, code, phase="active", first_billed_at=datetime(2026, 7, 28, tzinfo=UTC)):
        self.function_code = code
        self.phase = phase
        self.payer_user_id = "u1"
        # None = never charged for. It is what separates a cancelled PAID module (whose
        # period is bought and paid for) from a cancelled TRIAL (which bought nothing).
        self.first_billed_at = first_billed_at


def _stub_rows(monkeypatch, rows, paid_through=datetime(2026, 8, 28, 13, tzinfo=UTC)):
    """Module rows + the payer's paid-through, which _billed_codes_in_house needs to know
    whether a module winding down is still inside the period it paid for."""
    from blueprints.subscription.services import checkout, store

    monkeypatch.setattr(store, "module_rows_for_entity", lambda eid: rows)
    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: paid_through)
    monkeypatch.setattr(checkout.clock, "now", lambda: datetime(2026, 8, 20, 13, tzinfo=UTC))


def test_billed_codes_come_from_the_module_rows_not_stripe(monkeypatch):
    """The whole bug in one assertion: an entity on Petty Cash must not look empty."""
    from blueprints.subscription.services import checkout

    _stub_rows(monkeypatch, [_Row("petty_cash")])

    assert checkout._billed_codes_in_house("e1") == {"PETTY_CASH"}


def test_a_trialing_module_is_not_billed_yet_so_does_not_count(monkeypatch):
    """Counting it would price the change against a plan nobody is paying for."""
    from blueprints.subscription.services import checkout

    _stub_rows(monkeypatch, [_Row("PETTY_CASH", "active"), _Row("BILL", "trial")])

    assert checkout._billed_codes_in_house("e1") == {"PETTY_CASH"}


def test_a_cancelling_module_counts_while_its_paid_period_runs(monkeypatch):
    """It is winding down, but the customer PAID for it to the period end — so for the
    days before that end the line holds it, and adding a module is an upgrade to the
    bundle rather than a fresh join. The re-price happens at the period end, on the
    renewal, which is where the cancelled module actually leaves."""
    from blueprints.subscription.services import checkout

    _stub_rows(monkeypatch, [_Row("PETTY_CASH", "scheduled_cancel")])

    assert checkout._billed_codes_in_house("e1") == {"PETTY_CASH"}


def test_a_cancelling_module_stops_counting_once_its_period_ends(monkeypatch):
    """Past paid_through it is gone: nothing covers those days, so a change priced then
    must not credit or bundle against it."""
    from blueprints.subscription.services import checkout

    _stub_rows(
        monkeypatch, [_Row("PETTY_CASH", "scheduled_cancel")],
        paid_through=datetime(2026, 8, 19, 13, tzinfo=UTC),   # yesterday
    )

    assert checkout._billed_codes_in_house("e1") == set()


def test_a_cancelled_trial_never_counts(monkeypatch):
    """Winding down like the one above, but nothing was ever charged for it — there is no
    covered period to price against, so counting it would discount against a plan the
    customer has never paid a penny for."""
    from blueprints.subscription.services import checkout

    _stub_rows(
        monkeypatch, [_Row("PETTY_CASH", "scheduled_cancel", first_billed_at=None)]
    )

    assert checkout._billed_codes_in_house("e1") == set()


def test_a_past_due_module_still_counts(monkeypatch):
    """The money is owed, not written off. Treating it as unbilled would charge the new
    module's standalone price on top of a period already invoiced."""
    from blueprints.subscription.services import checkout

    _stub_rows(monkeypatch, [_Row("PETTY_CASH", "past_due")])

    assert checkout._billed_codes_in_house("e1") == {"PETTY_CASH"}


def test_converting_a_trial_prices_it_against_what_the_entity_ALREADY_bills(monkeypatch):
    """The regression. Entity is live on Petty Cash; its Payment Request trial converts.

    The change must be measured 280 -> 400 (the bundle margin), never as a fresh join at
    Payment Request's standalone 280. Asserted at the seam where the live run went wrong:
    what the conversion hands to the biller.
    """
    from blueprints.subscription.services import checkout, store

    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: "cus_1")
    monkeypatch.setattr(checkout, "trial_payment_method", lambda cid: "pm_1")
    monkeypatch.setattr(store, "has_billing_consent", lambda eid: True)
    monkeypatch.setattr(f"{_CATALOG}.plan_for_module", lambda code: object())
    monkeypatch.setattr(checkout, "_finish_conversion", lambda *a, **k: None)
    monkeypatch.setattr(
        store, "module_rows_for_entity",
        lambda eid: [_Row("PETTY_CASH", "active"), _Row("BILL", "trial")],
    )

    seen = {}

    def _bill(entity_id, payer_user_id, customer_id, current, codes):
        seen["current"], seen["codes"] = set(current), set(codes)
        return datetime(2026, 10, 8, 13, tzinfo=UTC)

    monkeypatch.setattr(checkout, "_bill_module_change_in_house", _bill)

    billable, doomed = checkout._convert_due_trials("e1", [_Row("BILL", "trial")])

    assert seen["current"] == {"PETTY_CASH"}   # was set() — the bug
    assert seen["codes"] == {"BILL"}
    assert len(billable) == 1 and doomed == []
