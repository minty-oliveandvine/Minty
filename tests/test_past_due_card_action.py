"""A past-due card must not offer Renew — the backend refuses it.

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

import re
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


def _actions(app, cards):
    """The onclick handlers the LEFT column (module cards) offers."""
    from blueprints.entity.services import modules

    with app.test_request_context("/"):
        panel = modules.build_subscription_panel(cards, SUMMARY, "28 Jun 2026")
        html = app.jinja_env.get_template(
            "entity/partials/module_subscription_section.html"
        ).render(
            module_cards=cards, subscription_summary=SUMMARY,
            subscription_panel=panel, next_payment_date="28 Jun 2026",
            org=type("O", (), {"id": "e1", "name": "Company"})(),
            can_manage_modules=True,
        )
    left = html.split("<aside", 1)[0]
    return re.findall(r'onclick="(\w+)\(', left), left


def test_past_due_offers_payment_not_renew(app):
    """The reported bug: Renew on a past-due module 409s."""
    actions, html = _actions(app, [
        _card("PETTY_CASH", "Petty Cash", status="past_due",
              pending_cancel=True, access_end_long="7 Aug 2026"),
    ])

    assert "renewSubscription" not in actions
    assert "addPaymentMethod" in actions
    # The grace deadline is the useful half of the old "Access until" line.
    assert "Pay by 7 Aug 2026 to keep access" in html


def test_a_scheduled_cancellation_states_its_date_and_nothing_else(app):
    """The other half of the shared flag: un-cancelling moved to the decision modal
    (re-tick the module), so the card states the date and offers no action."""
    actions, html = _actions(app, [
        _card("PETTY_CASH", "Petty Cash", status="active",
              pending_cancel=True, access_end_long="12 Sep 2026"),
    ])

    assert "renewSubscription" not in actions
    assert "addPaymentMethod" not in actions
    # Still usable, not continuing, and the date is the point — so it is a Cancelled pill
    # and a red end date, not grey small print.
    assert "Cancelled" in html
    assert "ends 12 Sep 2026" in html


def test_a_cancelled_trial_states_its_date_and_nothing_else(app):
    actions, html = _actions(app, [
        _card("PETTY_CASH", "Petty Cash", status="trialing",
              pending_cancel=True, trial_cancelled=True),
    ])

    assert "renewSubscription" not in actions
    # A cancelled trial reads "Trial ending", not "Cancelled": nothing was bought, and
    # it ends on its own trial date rather than a paid-through it never had.
    assert "Trial ending" in html
    assert "Cancelled" not in html
    assert "ends 28 Jul 2026" in html


def test_a_wound_down_entity_can_still_reach_the_modal(app):
    """The panel button is the only way into the decision modal, and re-ticking there
    is the only undo — so an entity with everything cancelled must still get one."""
    from blueprints.entity.services import modules

    cards = [_card("PETTY_CASH", "Petty Cash", status="active",
                   pending_cancel=True, access_end_long="12 Sep 2026")]
    panel = modules.build_subscription_panel(cards, SUMMARY, "28 Jun 2026")

    assert panel["is_empty"] is True
    assert panel["primary_action"] == "manage"


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
