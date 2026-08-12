"""A module whose period has lapsed must stop presenting as a live subscription.

The phase is not "is this live". A row stays ``active`` until something writes it, while
access ends on a DATE that passes unattended — nothing fires at the boundary, which is
why ``sweep_expired_module_access`` exists to reconcile the gate afterwards.

Reading the phase alone meant a module that had lapsed, and whose access the sweep had
just revoked, still rendered as:

    Petty Cash                       active
                          [ Cancel Subscription ]
                          valid until 28 Jul 2026     <- a date in the PAST

— the card claiming a subscription the request gate would refuse, and offering to cancel
something already gone. ``granted`` now gates the paid branch the same way it always
gated the trial one.

NOTE: imports are done INSIDE each test and the catalog is patched BY DOTTED PATH — the
conftest ``app`` fixture clears and re-imports project modules mid-session, so a module
object captured at import time is not the one the code under test calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_CATALOG = "blueprints.subscription.services.catalog"
UTC = timezone.utc


class _Fn:
    id = "fn_pc"
    function_code = "PETTY_CASH"
    function_name = "Petty Cash"
    description = "d"
    is_active = True


class _Query:
    def filter(self, *a, **k):
        return self

    def all(self):
        return [_Fn()]


class _Column:
    """Stands in for the mapped column so ``.in_(...)`` builds without SQLAlchemy."""

    def in_(self, _values):
        return None


class _FakeEntityFunction:
    query = _Query()
    function_code = _Column()


class _PaidRow:
    """A module that was converted and has been billing ever since."""

    entity_id = "e1"
    function_code = "PETTY_CASH"
    payer_user_id = "u1"
    phase = "active"
    trial_end = None
    app_access_until = None
    extension_amount = None
    extension_state = None

    def __init__(self):
        self.first_billed_at = datetime.now(UTC) - timedelta(days=60)


class _TrialRow:
    """A trial whose term has passed and that no pass has closed out yet.

    Nothing has been billed, the phase is still ``trial`` because only ``close-trials``
    rewrites it, and ``app_access_until`` was stamped equal to ``trial_end`` when the trial
    started — so the date rules already say access is over while the gate has not been
    told.
    """

    entity_id = "e1"
    function_code = "PETTY_CASH"
    payer_user_id = "u1"
    phase = "trial"
    extension_amount = None
    extension_state = None
    first_billed_at = None

    def __init__(self, *, ended_ago=timedelta(minutes=20)):
        self.trial_end = datetime.now(UTC) - ended_ago
        self.app_access_until = self.trial_end


def _card(app, monkeypatch, *, paid_through, row=None, has_access=False):
    import blueprints.entity.services.modules as modules_mod
    from blueprints.subscription.services import store

    monkeypatch.setattr(modules_mod, "EntityFunction", _FakeEntityFunction)
    monkeypatch.setattr(modules_mod, "MODULE_CODES", ("PETTY_CASH",))
    monkeypatch.setattr(modules_mod, "_entity_customer_id", lambda eid: None)
    monkeypatch.setattr(modules_mod, "_enabled_state",
                        lambda eid: {"PETTY_CASH": has_access})
    monkeypatch.setattr(store, "module_rows_for_entity",
                        lambda eid: [row if row is not None else _PaidRow()])
    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: paid_through)
    monkeypatch.setattr(f"{_CATALOG}.available_plans", lambda: [])
    monkeypatch.setattr(
        "blueprints.subscription.services.stripe_client.customer_default_payment_method",
        lambda cid: None,
    )

    with app.app_context():
        return modules_mod.get_module_cards("e1")[0]


def test_a_lapsed_paid_module_does_not_present_as_active(app, monkeypatch):
    """Period ended six days ago and the phase was never rewritten."""
    card = _card(app, monkeypatch, paid_through=datetime.now(UTC) - timedelta(days=6))

    assert card["subscription_status"] is None, "not a live subscription any more"
    assert card["can_cancel"] is False, "nothing live to cancel"
    # No stale promise: "valid until <past date>" came from period_end_long.
    assert card["period_end_long"] is None
    assert card["formatted_period_end"] is None


def test_a_paid_module_inside_its_period_still_presents_as_active(app, monkeypatch):
    """The mirror case — the fix must not switch off a healthy subscription."""
    card = _card(app, monkeypatch, paid_through=datetime.now(UTC) + timedelta(days=20))

    assert card["subscription_status"] == "active"
    assert card["can_cancel"] is True
    assert card["period_end_long"] is not None


def test_a_payer_with_no_paid_through_has_no_live_paid_module(app, monkeypatch):
    """Nothing has ever been billed, so there is no period the phase can be live within.

    Reached when a row is written by hand or a conversion half-completed; the card must
    not invent a subscription from the phase alone.
    """
    card = _card(app, monkeypatch, paid_through=None)

    assert card["subscription_status"] is None
    assert card["can_cancel"] is False


def test_a_used_up_trial_says_so_under_not_active(app, monkeypatch):
    """"not active" alone reads as "never had this", and leaves the customer wondering
    why the card offers Subscribe instead of a free trial. A module whose PAID
    subscription ended is a different sentence — never_billed is what separates them."""
    from flask import render_template

    card = {
        "code": "PETTY_CASH", "name": "Petty Cash", "description": "", "image": "x.png",
        "learn_more": "#", "subscription_status": None, "amount": 280,
        "pending_cancel": False, "trial_cancelled": False, "trial_eligible": False,
        "trial_expired": True, "needs_card": False, "needs_consent_only": False,
        "period_end_long": None, "period_end_short": None, "access_end_long": None,
    }
    with app.test_request_context():
        html = render_template(
            "entity/partials/module_subscription_section.html",
            module_cards=[card], subscription_summary=None, subscription_panel=None,
            org=type("O", (), {"id": "e1", "name": "Co"})(), can_manage_modules=True,
        )

    # Split at the panel: its hidden staged-cart button is captioned "Start free trial"
    # until renderCart relabels it, so a whole-page search would always match.
    cards_html = html.split("<aside", 1)[0]
    assert "not active" in cards_html
    assert "free trial expired" in cards_html
    # The trial is spent, so the action is the paid one.
    assert "Start free trial" not in cards_html
    assert "Subscribe" in cards_html

    card["trial_expired"] = False
    with app.test_request_context():
        html = render_template(
            "entity/partials/module_subscription_section.html",
            module_cards=[card], subscription_summary=None, subscription_panel=None,
            org=type("O", (), {"id": "e1", "name": "Co"})(), can_manage_modules=True,
        )
    assert "free trial expired" not in html


def test_a_trial_past_its_term_is_closing_not_expired(app, monkeypatch):
    """The window between the term ending and the pass closing it out.

    ``trial_end`` passes unattended, so until the subscription pass runs the row is still
    ``phase = trial`` while the date rules have already gone false. The card used to fall
    straight through to ``trial_expired`` and tell the customer their free trial was used
    up — while the request gate was still letting them work, and while a trial with a card
    and consent was about to CONVERT rather than expire.
    """
    card = _card(
        app, monkeypatch, paid_through=None, row=_TrialRow(), has_access=True
    )
    assert card["subscription_status"] == "trial_closing"
    # Not "expired": nothing has decided yet, and the module still opens.
    assert card["trial_expired"] is False
    assert card["has_access"] is True
    # Not offered as a fresh trial either — they are inside it.
    assert card["trial_eligible"] is False


def test_a_trial_past_its_term_with_access_gone_is_expired(app, monkeypatch):
    """The bound on the transitional state.

    It needs the gate to still say yes. Once anything reconciles — close-trials expiring
    the row, or the sweep revoking a module whose ``grants_access`` is already false — the
    card must go back to telling the plain truth. Without this, a scheduler that stopped
    would leave "finalising" on screen forever.
    """
    card = _card(
        app, monkeypatch, paid_through=None, row=_TrialRow(), has_access=False
    )
    assert card["subscription_status"] is None
    assert card["trial_expired"] is True


def test_a_running_trial_is_untouched(app, monkeypatch):
    """The new state must not swallow trials that are simply still running."""
    card = _card(
        app,
        monkeypatch,
        paid_through=None,
        row=_TrialRow(ended_ago=timedelta(days=-3)),  # ends in three days
        has_access=True,
    )
    assert card["subscription_status"] == "trialing"
    assert card["trial_expired"] is False


def test_the_closing_card_reads_active_and_offers_no_cancel(app):
    """What the customer sees. It works, so the badge says so; the outcome is pending, so
    nothing is offered to act on."""
    from flask import render_template

    card = {
        "code": "PETTY_CASH", "name": "Petty Cash", "description": "", "image": "x.png",
        "learn_more": "#", "subscription_status": "trial_closing", "amount": 280,
        "pending_cancel": False, "trial_cancelled": False, "trial_eligible": False,
        "trial_expired": False, "needs_card": False, "needs_consent_only": False,
        "period_end_long": None, "period_end_short": None, "access_end_long": None,
        "has_access": True,
    }
    with app.test_request_context():
        html = render_template(
            "entity/partials/module_subscription_section.html",
            module_cards=[card], subscription_summary=None, subscription_panel=None,
            org=type("O", (), {"id": "e1", "name": "Co"})(), can_manage_modules=True,
        )
    cards_html = html.split("<aside", 1)[0]
    assert "active" in cards_html
    assert "trial ended - finalising" in cards_html
    assert "free trial expired" not in cards_html
    # Nothing settled to cancel, and no trial to start.
    assert "Cancel Subscription" not in cards_html
    assert "Start free trial" not in cards_html
