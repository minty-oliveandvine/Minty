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


def _card(app, monkeypatch, *, paid_through):
    import blueprints.entity.services.modules as modules_mod
    from blueprints.subscription.services import store

    monkeypatch.setattr(modules_mod, "EntityFunction", _FakeEntityFunction)
    monkeypatch.setattr(modules_mod, "MODULE_CODES", ("PETTY_CASH",))
    monkeypatch.setattr(modules_mod, "_entity_customer_id", lambda eid: None)
    monkeypatch.setattr(store, "module_rows_for_entity", lambda eid: [_PaidRow()])
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
