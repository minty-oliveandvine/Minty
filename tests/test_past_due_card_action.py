"""Reactivating a past-due module is refused by the backend.

(The Jinja card tests that lived here - a past-due card offers payment, not Renew - went
with Flask's module page on 2026-10-01; minty-web's page draws the card now.)

``card.pending_cancel`` is one "winding down" flag serving two different states: a
scheduled cancellation and a failed renewal. They read alike (access still runs, to a
date) and need opposite actions:

  scheduled cancel  -> Renew, which un-cancels it (checkout.reactivate_module)
  past due          -> pay, because it was never cancelled and the money is owed

The template branched on the shared flag and offered Renew to both, so every past-due
card called ``reactivate_module`` — which requires ``phase == scheduled_cancel`` and
answered "Module PETTY_CASH isn't scheduled to cancel." A button that cannot work.

Dunning already retries the charge on billing_policy.retry_offsets_days; the only lever
the customer has is the card that retry will use.
"""
from __future__ import annotations

from decimal import Decimal


def _card(code, name, *, status, pending_cancel=False, access_end_long=None,
          trial_cancelled=False, can_cancel=False, trial_eligible=False):
    """The subset of a module card the action block reads."""
    return {
        "code": code,
        "name": name,
        "description": "",
        "image": "img/cash_reg.webp",
        "learn_more": "#",
        "amount": Decimal("280"),
        "currency_code": "HKD",
        "subscription_status": status,
        "pending_cancel": pending_cancel,
        "trial_cancelled": trial_cancelled,
        "can_cancel": can_cancel,
        "trial_eligible": trial_eligible,
        "is_subscribed": True,
        "has_access": True,
        "needs_card": False,
        "needs_consent_only": False,
        "period_end": None,
        "period_end_short": "28 Jul",
        "period_end_long": "28 Jul 2026",
        "formatted_period_end": "July 28, 2026",
        "access_end_date": access_end_long,
        "access_end_long": access_end_long,
        "extension_amount": Decimal(0),
        "conversion_charge": Decimal(0),
        "subscription_id": None,
    }


# Currency supplied so the panel never falls through to a currency_info lookup, which
# the bare test database has no table for.
SUMMARY = {"currency": "HKD", "currency_code": "HKD"}


def test_reactivate_refuses_past_due_with_a_useful_message(app, monkeypatch):
    """A stale tab can still post it, so the answer must name the fix."""
    from blueprints.subscription.services import checkout, store

    class _Row:
        phase = "past_due"
        payer_user_id = "u1"
        first_billed_at = None

    monkeypatch.setattr(store, "module_row", lambda eid, code: _Row())

    with app.app_context():
        try:
            checkout.reactivate_module(
                type("E", (), {"id": "e1"})(), type("U", (), {"id": "u1"})(), "PETTY_CASH"
            )
        except checkout.CheckoutError as exc:
            assert exc.status == 409
            assert "past due" in exc.message.lower()
            assert "payment method" in exc.message.lower()
        else:
            raise AssertionError("reactivating a past-due module must be refused")
