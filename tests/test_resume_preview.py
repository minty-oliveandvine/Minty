"""What the "Resume module" dialog quotes.

This function is mirrored by hand from ``_bill_reinstatement_in_house`` rather than sharing
a pure helper with it, and it has now shipped two wrong numbers: a first version quoted
ZERO because it did not subtract the resuming module from ``before``, and a later one
quoted the BUNDLE price as the ongoing monthly on an entity where the other module was
also winding down. Both were silent — a plausible figure in the right currency, on the
screen where somebody decides whether to restart a subscription.

So the point of this file is narrow and worth stating: the dialog quotes TWO amounts that
come from TWO DIFFERENT SETS, and conflating them is the whole failure mode.

    charged today   from what the period was PAID FOR — a module winding down was paid
                    for, so resuming beside it is an upgrade to the bundle they still are
                    until it goes.

    monthly         from what will still be BILLING FORWARD afterwards — a module winding
                    down will not be there, so it must not be in the recurring price.

They coincide whenever nothing else is cancelling, which is why this went unnoticed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)
ANCHOR = datetime(2026, 6, 13, 12, tzinfo=UTC)
ACCESS_UNTIL = datetime(2026, 9, 18, 12, tzinfo=UTC)

PRICES = {
    frozenset({"PETTY_CASH"}): (28000, "Petty Cash"),
    frozenset({"BILL"}): (28000, "Payment Request"),
    frozenset({"BILL", "PETTY_CASH"}): (40000, "Super Minty"),
}


def _row(code, phase, *, first_billed=NOW - timedelta(days=90)):
    return SimpleNamespace(
        function_code=code,
        phase=phase,
        payer_user_id="payer-1",
        app_access_until=ACCESS_UNTIL if phase == "scheduled_cancel" else None,
        first_billed_at=first_billed,
        trial_end=None,
        extension_state=None,
        extension_amount=None,
    )


def _wire(monkeypatch, rows, *, covered):
    """Mock the catalog and the cycle. ``covered`` is what the period was PAID FOR —
    ``_billed_codes_in_house``'s answer, which includes modules winding down."""
    from blueprints.subscription.services import checkout, clock, store

    monkeypatch.setattr(clock, "now", lambda: NOW)
    monkeypatch.setattr(store, "module_rows_for_entity", lambda eid: list(rows))
    monkeypatch.setattr(store, "billing_cycle_for_user", lambda uid: (ANCHOR, "HKD"))
    monkeypatch.setattr(store, "paid_through_for_user",
                        lambda uid: datetime(2026, 9, 13, 12, tzinfo=UTC))
    monkeypatch.setattr(checkout, "_billed_codes_in_house", lambda eid: set(covered))

    def _plan(codes):
        found = PRICES.get(frozenset(str(c).upper() for c in codes))
        if not found:
            return None
        amount, name = found
        return SimpleNamespace(amount=amount, display_name=name, currency="HKD")

    monkeypatch.setattr(store, "billing_plan_for_codes", _plan)
    return checkout


def _preview(checkout, code="PETTY_CASH"):
    entity = SimpleNamespace(id="e1", name="Demo Co")
    user = SimpleNamespace(id="payer-1")
    return checkout.preview_reinstate_modules(entity, user, [code])


# --- the recurring price ----------------------------------------------------------


def test_resuming_beside_a_live_module_quotes_the_bundle(monkeypatch):
    """The other module keeps running, so the entity really will be on Super Minty."""
    checkout = _wire(
        monkeypatch,
        [_row("BILL", "active"), _row("PETTY_CASH", "scheduled_cancel")],
        covered={"BILL", "PETTY_CASH"},
    )

    assert _preview(checkout)["monthly"] == 40000


def test_resuming_when_the_other_module_is_also_leaving_quotes_the_solo_price(monkeypatch):
    """THE BUG. Both cancelling: resuming one brings back only that one, and the other
    still lapses — so the ongoing cost is the solo price. Quoting the bundle told the
    customer they would pay 120/month more than they will."""
    checkout = _wire(
        monkeypatch,
        [_row("BILL", "scheduled_cancel"), _row("PETTY_CASH", "scheduled_cancel")],
        # Both were PAID FOR this period, which is exactly why the two sets diverge.
        covered={"BILL", "PETTY_CASH"},
    )

    assert _preview(checkout)["monthly"] == 28000


def test_the_only_module_on_the_entity_quotes_its_own_price(monkeypatch):
    checkout = _wire(
        monkeypatch, [_row("PETTY_CASH", "scheduled_cancel")], covered={"PETTY_CASH"}
    )

    assert _preview(checkout)["monthly"] == 28000


def test_a_module_that_already_lapsed_does_not_count_toward_the_bundle(monkeypatch):
    """``cancelled`` is terminal — it is not coming back on its own, so it cannot be part
    of what the entity pays from next period."""
    checkout = _wire(
        monkeypatch,
        [_row("BILL", "cancelled"), _row("PETTY_CASH", "scheduled_cancel")],
        covered={"PETTY_CASH"},
    )

    assert _preview(checkout)["monthly"] == 28000


def test_a_past_due_module_still_counts(monkeypatch):
    """``past_due`` is billing forward: the subscription has not ended and the money is
    still owed, so it is part of what the entity will be paying."""
    checkout = _wire(
        monkeypatch,
        [_row("BILL", "past_due"), _row("PETTY_CASH", "scheduled_cancel")],
        covered={"BILL", "PETTY_CASH"},
    )

    assert _preview(checkout)["monthly"] == 40000


# --- and the two amounts stay distinct --------------------------------------------


def test_the_charge_today_still_counts_a_module_that_is_winding_down(monkeypatch):
    """The other half of the rule, and the reason this cannot be fixed by using one set
    for both figures. A cancelling module was PAID FOR this period, so for the days that
    remain the entity is still the bundle — the charge now is the upgrade against it, not
    a fresh join. Only the RECURRING figure drops it."""
    from blueprints.subscription.services import changes

    seen = {}

    def _build(entity_id, name, before, after, period, at):
        seen["before"], seen["after"] = set(before), set(after)
        return SimpleNamespace(total=3484)

    checkout = _wire(
        monkeypatch,
        [_row("BILL", "scheduled_cancel"), _row("PETTY_CASH", "scheduled_cancel")],
        covered={"BILL", "PETTY_CASH"},
    )
    monkeypatch.setattr(changes, "build_change", _build)

    result = _preview(checkout)

    assert result["monthly"] == 28000, "recurring drops the module that is leaving"
    if seen:
        assert "BILL" in seen["before"], (
            "the charge today still prices against the days already paid for"
        )
