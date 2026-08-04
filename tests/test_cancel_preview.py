"""The cancellation confirmation dialog quotes what cancelling will actually do.

``preview_cancel_module`` feeds the dialog the two facts it exists to state: when access
ends, and what is still owed. Cancelling can put money on the next invoice, so a preview
that drifts from the commit is worse than no dialog — it is a quoted figure the customer
was never charged, or was charged without being shown.

The load-bearing property, and the reason ``_paid_cancel_terms`` was extracted, is that
preview and commit share ONE calculation. ``test_preview_matches_what_cancelling_records``
is what holds that: it previews, then cancels, and asserts the recorded row carries the
previewed date and amount.

Marginal pricing is the part most easily got wrong. Dropping Petty Cash from a 400 bundle
leaves Payment Request at 280, so Petty Cash was worth 120 — not its 280 list price — and
the extension is prorated off that 120.
"""
from __future__ import annotations

_CATALOG = "blueprints.subscription.services.catalog"

from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc

# Anchor and "now" pinned: the extension is a proration off the period containing
# paid_through, so a floating clock makes the amount unreproducible.
_ANCHOR = datetime(2027, 1, 8, 13, tzinfo=UTC)
_NOW = datetime(2027, 1, 20, 13, tzinfo=UTC)
_PAID_THROUGH = datetime(2027, 2, 8, 13, tzinfo=UTC)


class _FakeEntity:
    id = "e1"
    name = "Acme"


class _FakeUser:
    id = "u1"
    email = "u1@example.com"


class _Row:
    def __init__(self, code="PETTY_CASH", phase="active", trial_end=None, payer="u1"):
        self.entity_id = "e1"
        self.function_code = code
        self.payer_user_id = payer
        self.phase = phase
        self.trial_end = trial_end
        self.app_access_until = None
        self.first_billed_at = None


class _Plan:
    def __init__(self, amount):
        self.amount = amount
        self.display_name = "plan"
        self.currency = "HKD"


def _setup(monkeypatch, *, row, siblings=None, paid_through=_PAID_THROUGH):
    """Wire the store around one entity holding ``siblings`` (default: the bundle)."""
    from blueprints.subscription.services import checkout, store
    from blueprints.subscription.services import clock as clock_mod

    monkeypatch.setattr(clock_mod, "now", lambda: _NOW)

    rows = siblings if siblings is not None else [
        _Row("PETTY_CASH"), _Row("BILL"),
    ]
    calls = {"writes": [], "access": [], "audit": []}

    monkeypatch.setattr(store, "module_row", lambda eid, code: row)
    monkeypatch.setattr(store, "module_rows_for_entity", lambda eid: rows)
    monkeypatch.setattr(store, "billing_cycle_for_user", lambda uid: (_ANCHOR, "HKD"))
    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: paid_through)
    monkeypatch.setattr(
        store, "billing_plan_for_codes",
        lambda codes: _Plan(40000 if len(set(codes)) > 1 else 28000),
    )
    monkeypatch.setattr(
        store, "upsert_module_row",
        lambda e, code, payer, **f: calls["writes"].append((e, code, payer, f)),
    )
    monkeypatch.setattr(
        store, "record_action", lambda **kw: calls["audit"].append(kw)
    )
    monkeypatch.setattr(
        checkout, "_set_module_access",
        lambda eid, code, enabled: calls["access"].append((eid, code, enabled)),
    )
    # money.format_minor reads currency_info for decimal places; pin it so the
    # formatted strings below don't depend on a seeded table.
    from blueprints.subscription.services import money
    monkeypatch.setattr(money, "decimal_places", lambda code: 2)
    return checkout, calls


# --- the property that matters -------------------------------------------------


def test_preview_matches_what_cancelling_records(monkeypatch):
    """Preview, then cancel: the row must carry the previewed date and amount.

    This is the whole point of sharing ``_paid_cancel_terms``. If these ever diverge,
    the dialog is quoting a number the customer will not be billed.
    """
    checkout, calls = _setup(monkeypatch, row=_Row("PETTY_CASH"))

    preview = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")
    checkout.cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")

    _e, _code, _payer, fields = calls["writes"][0]
    assert fields["app_access_until"] == preview["access_end"]
    assert fields["extension_amount"] == preview["amount"]
    assert preview["amount"] > 0  # otherwise this asserts nothing


def test_preview_writes_nothing(monkeypatch):
    """It runs on a dialog open — it must not schedule the cancellation it describes."""
    checkout, calls = _setup(monkeypatch, row=_Row("PETTY_CASH"))

    checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")

    assert calls["writes"] == []
    assert calls["access"] == []
    assert calls["audit"] == []


# --- paid ----------------------------------------------------------------------


def test_paid_preview_charges_the_marginal_price_not_the_list_price(monkeypatch):
    """Petty Cash out of a 400 bundle leaves Bill at 280, so it was worth 120.

    Access ends at max(paid_through, now + grace). With paid_through 19 days out and a
    30-day window, the window wins and the days BEYOND paid_through are what's owed.
    """
    checkout, _ = _setup(monkeypatch, row=_Row("PETTY_CASH"))

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")

    assert p["kind"] == "paid"
    assert p["currency"] == "HKD"
    assert p["remaining"] == ["BILL"]
    # Survivor's price, so the dialog can say what billing continues at.
    assert p["remaining_amount"] == "280.00"
    # Charged off 120 (400 - 280), never off 280.
    assert 0 < p["amount"] < 28000
    assert p["access_end"] > _PAID_THROUGH
    assert p["charged_now"] is False


def test_cancelling_the_last_module_reports_no_survivor(monkeypatch):
    """Nothing left to bill: the dialog says billing for the company ends."""
    checkout, _ = _setup(
        monkeypatch, row=_Row("PETTY_CASH"), siblings=[_Row("PETTY_CASH")]
    )

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")

    assert p["kind"] == "paid"
    assert p["remaining"] == []
    assert p["remaining_amount"] is None
    # With no survivor the whole line price is marginal, so there IS an extension.
    assert p["amount"] > 0


def test_nothing_owed_when_access_is_already_paid_through(monkeypatch):
    """A paid_through beyond the cancellation window adds no days, so no charge.

    The dialog then says "nothing further to pay" rather than showing a 0.00 amount.
    """
    far = _NOW + timedelta(days=120)
    checkout, _ = _setup(monkeypatch, row=_Row("PETTY_CASH"), paid_through=far)

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "PETTY_CASH")

    assert p["amount"] == 0
    assert p["amount_formatted"] is None
    assert p["access_end"] == far


# --- trials --------------------------------------------------------------------


def test_trial_preview_keeps_the_free_days_and_owes_nothing(monkeypatch):
    """Cancelling a trial means "don't convert me", not "end it now"."""
    trial_end = _NOW + timedelta(days=9)
    checkout, _ = _setup(
        monkeypatch, row=_Row("BILL", phase="trial", trial_end=trial_end)
    )

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "BILL")

    assert p["kind"] == "trial"
    assert p["access_end"] == trial_end
    assert p["amount"] == 0
    assert p["amount_formatted"] is None


def test_expired_trial_preview_has_nothing_left_to_keep(monkeypatch):
    checkout, _ = _setup(
        monkeypatch,
        row=_Row("BILL", phase="trial", trial_end=_NOW - timedelta(days=1)),
    )

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "BILL")

    assert p["kind"] == "trial_expired"
    assert p["access_end"] is None
    assert p["amount"] == 0


# --- guards --------------------------------------------------------------------


def test_preview_of_an_unsubscribed_module_reports_rather_than_raises(monkeypatch):
    """The dialog needs something to show; a 500 would just look broken."""
    checkout, _ = _setup(monkeypatch, row=None)

    p = checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "BILL")

    assert p["kind"] == "none"
    assert p["error"]


def test_preview_requires_a_code(monkeypatch):
    checkout, _ = _setup(monkeypatch, row=_Row("PETTY_CASH"))

    with pytest.raises(checkout.CheckoutError):
        checkout.preview_cancel_module(_FakeEntity(), _FakeUser(), "")
