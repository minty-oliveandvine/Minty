"""Unit tests for the renewal runner.

This is the code that takes money on Minty's own arithmetic, so the cases below are the
ways it could take the wrong amount, take it twice, or fail to take it at all.

Its first live exercise charged a real payer twice for catch-up periods — a global sweep
driven by a test clock belonging to a different customer. ``scope`` and
``test_billing_everyone_has_to_be_asked_for_explicitly`` exist because of that.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc
ANCHOR = datetime(2027, 1, 8, 13, tzinfo=UTC)
PAID_THROUGH = datetime(2027, 2, 8, 13, tzinfo=UTC)
NOW = datetime(2027, 2, 9, 13, tzinfo=UTC)


class _Account:
    def __init__(self, user_id="u1", paid_through=PAID_THROUGH):
        self.user_id = user_id
        self.anchor_at = ANCHOR
        self.paid_through = paid_through
        self.stripe_customer_id = f"cus_{user_id}"


class _Row:
    def __init__(self, entity_id="e1", code="BILL", phase="active"):
        self.entity_id = entity_id
        self.function_code = code
        self.phase = phase
        self.payer_user_id = "u1"


class _Plan:
    def __init__(self, name="Super Minty", amount=40000, currency="HKD"):
        self.display_name = name
        self.amount = amount
        self.currency = currency


class _Record:
    """A ``subscription_invoice`` row: the local record of an invoice already raised.

    ``external_id`` is what makes it authoritative. NULL means the key was claimed and
    nothing came back, so the row cannot say whether the processor has the invoice.
    """

    def __init__(self, id="inv_local", external_id="in_old", status="paid"):
        self.id = id
        self.external_id = external_id
        self.status = status


def _wire(monkeypatch, *, accounts=None, rows=None, plan=_Plan(), issued=None,
          existing=None, found=None, extensions=None):
    """Mock the store and the gateway; return (renewals, calls).

    ``existing`` is the LOCAL row for this period's key (the guard). ``found`` is what
    the processor returns if the runner ever has to fall back to scanning it.
    """
    from blueprints.subscription.services import billing_gateway, renewals, store

    accounts = accounts if accounts is not None else [_Account()]
    rows = rows if rows is not None else [_Row()]

    monkeypatch.setattr(store, "accounts_with_billing", lambda: accounts)
    monkeypatch.setattr(store, "module_rows_for_payer", lambda uid: rows)
    monkeypatch.setattr(store, "billing_plan_for_codes", lambda codes: plan)
    # Cancel-extensions owed but not yet collected; none unless a test says otherwise.
    monkeypatch.setattr(
        store, "pending_extensions_for_payer", lambda uid: extensions or []
    )
    monkeypatch.setattr(
        store, "billing_cycle_for_user", lambda uid: (ANCHOR, "HKD")
    )
    monkeypatch.setattr(
        renewals, "_entity_names", lambda ids: {str(i): f"Entity {i}" for i in ids}
    )

    calls = {"paid_through": [], "dunning": [], "issued": [], "lookups": [],
             "marked": [], "keys": [], "discarded": [], "settled": []}
    monkeypatch.setattr(
        store, "invoice_for_key",
        lambda key: calls["keys"].append(key) or existing,
    )
    monkeypatch.setattr(
        store, "discard_invoice", lambda rid: calls["discarded"].append(rid)
    )
    monkeypatch.setattr(
        store, "settle_invoice",
        lambda rid, **kw: calls["settled"].append((rid, kw)),
    )
    monkeypatch.setattr(
        store, "mark_extensions_invoiced",
        lambda ids: calls["marked"].append(list(ids)) or len(list(ids)),
    )
    monkeypatch.setattr(
        store, "set_paid_through",
        lambda uid, until: calls["paid_through"].append((uid, until)),
    )
    monkeypatch.setattr(
        store, "begin_dunning", lambda uid, when: calls["dunning"].append((uid, when))
    )
    monkeypatch.setattr(
        billing_gateway, "find_invoice_by_metadata",
        lambda cid, k, v: calls["lookups"].append((cid, v)) or found,
    )
    monkeypatch.setattr(
        billing_gateway, "issue_invoice",
        lambda cid, inv, **kw: calls["issued"].append((cid, inv, kw))
        or (issued if issued is not None else {"id": "in_1", "status": "paid"}),
    )
    return renewals, calls


# --- the blast radius ----------------------------------------------------------


def test_billing_everyone_has_to_be_asked_for_explicitly(monkeypatch):
    """Omitting ``scope`` must be an error, not a full sweep. A global run driven by an
    injected clock is what charged a real payer for periods that were not due."""
    renewals, _calls = _wire(monkeypatch)

    with pytest.raises(TypeError):
        renewals.run_renewals(NOW, issue=True)


def test_scope_limits_who_is_billed(monkeypatch):
    renewals, calls = _wire(
        monkeypatch,
        accounts=[_Account("u1"), _Account("u2")],
    )

    result = renewals.run_renewals(NOW, scope=["u2"], issue=True)

    assert [e["user_id"] for e in result["issued"]] == ["u2"]
    assert [c[0] for c in calls["paid_through"]] == ["u2"]


def test_all_payers_still_reaches_everyone(monkeypatch):
    renewals, _calls = _wire(monkeypatch, accounts=[_Account("u1"), _Account("u2")])

    result = renewals.run_renewals(NOW, scope=renewals.ALL_PAYERS, issue=True)

    assert {e["user_id"] for e in result["issued"]} == {"u1", "u2"}


# --- shadow --------------------------------------------------------------------


def test_shadow_mode_charges_nothing_and_records_nothing(monkeypatch):
    renewals, calls = _wire(monkeypatch)

    result = renewals.run_renewals(NOW, scope=renewals.ALL_PAYERS, issue=False)

    assert result["planned"] and not result["issued"]
    assert calls["issued"] == []
    assert calls["paid_through"] == []


# --- the amount ----------------------------------------------------------------


def test_one_line_per_entity_priced_by_the_module_SET(monkeypatch):
    """Two modules on one entity are the bundle price, not the sum — the bundle IS the
    discount, so summing standalone prices would overcharge."""
    renewals, calls = _wire(
        monkeypatch,
        rows=[_Row("e1", "BILL"), _Row("e1", "PETTY_CASH"), _Row("e2", "BILL")],
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    _cid, invoice, _kw = calls["issued"][0]
    assert len(invoice.lines) == 2          # one per entity, not per module
    assert invoice.total == 80000           # 2 x bundle, not 3 x standalone


def test_trials_and_cancelling_modules_are_not_billed(monkeypatch):
    """Charging either would bill for something the customer was told was not coming.

    Such a payer is filtered out by ``due_renewals`` rather than reaching the runner and
    being skipped — a payer with nothing billable is not due, which is the cleaner
    reading of the same rule."""
    renewals, calls = _wire(
        monkeypatch,
        rows=[_Row("e1", "BILL", phase="trial"),
              _Row("e2", "BILL", phase="scheduled_cancel")],
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == []
    assert result == {"planned": [], "issued": [], "failed": [], "skipped": []}


def test_an_unpriceable_combination_is_skipped_not_guessed(monkeypatch):
    """Falling back to a sum of standalone prices would silently overcharge by the
    bundle discount — the kind of error nobody notices until a customer does."""
    renewals, calls = _wire(monkeypatch, plan=None)

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == []
    assert result["skipped"]


# --- taking the money ----------------------------------------------------------


def test_paid_through_advances_only_after_a_successful_charge(monkeypatch):
    renewals, calls = _wire(monkeypatch)

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["paid_through"] == [("u1", datetime(2027, 3, 8, 13, tzinfo=UTC))]


def test_a_declined_renewal_does_not_advance_and_starts_dunning(monkeypatch):
    """Advancing first would skip the period forever — a free month nobody notices.
    Starting dunning is what turns a decline into the retry schedule rather than a
    silent lapse."""
    renewals, calls = _wire(monkeypatch, issued={"id": "in_1", "status": "open"})

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["paid_through"] == []
    assert calls["dunning"] == [("u1", NOW)]
    assert result["failed"]


def test_a_crash_mid_charge_still_starts_dunning(monkeypatch):
    renewals, calls = _wire(monkeypatch)
    from blueprints.subscription.services import billing_gateway

    def _boom(*a, **k):
        raise RuntimeError("processor unreachable")

    monkeypatch.setattr(billing_gateway, "issue_invoice", _boom)

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["paid_through"] == []
    assert calls["dunning"] == [("u1", NOW)]
    assert result["failed"]


# --- billing twice -------------------------------------------------------------


def test_a_period_already_invoiced_is_adopted_not_re_charged(monkeypatch):
    """The case a naive runner double-bills: the money was collected on an earlier run
    that died before recording it. Catching up costs nothing; re-issuing bills the
    customer twice for one month."""
    renewals, calls = _wire(monkeypatch, existing=_Record(status="paid"))

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == []                       # nothing charged
    assert calls["paid_through"] == [("u1", datetime(2027, 3, 8, 13, tzinfo=UTC))]
    assert result["skipped"][0]["reason"] == "already invoiced; adopted"


def test_an_existing_UNPAID_invoice_is_not_re_issued_either(monkeypatch):
    """It is already out there awaiting collection — a second one would ask twice."""
    renewals, calls = _wire(monkeypatch, existing=_Record(status="open"))

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == []
    assert calls["paid_through"] == []                 # nothing collected yet
    assert result["skipped"][0]["reason"] == "already invoiced; unpaid"


def test_the_guard_is_a_local_lookup_not_a_scan_of_the_processor(monkeypatch):
    """The point of ``subscription_invoice``. This used to LIST the payer's Stripe
    invoices and scan their metadata once per payer, every run — on the ordinary path
    where nothing has been billed yet and the scan can only ever come back empty."""
    renewals, calls = _wire(monkeypatch)

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["keys"] == ["renewal-u1-20270208"]    # asked the index
    assert calls["lookups"] == []                      # never asked Stripe
    assert calls["issued"]


def test_a_reservation_that_was_never_confirmed_sent_asks_the_processor(monkeypatch):
    """A row with no ``external_id`` means the key was claimed and nothing came back, so
    the local record cannot say whether the invoice exists. Assuming it does would leave
    the payer never billed for the period — so this is the one case that still scans."""
    renewals, calls = _wire(
        monkeypatch,
        existing=_Record(external_id=None, status="draft"),
        found={"id": "in_found", "status": "paid"},
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["lookups"] == [("cus_u1", "renewal-u1-20270208")]
    assert calls["issued"] == []                       # it was already charged
    assert result["skipped"][0]["reason"] == "already invoiced; adopted"
    # And the row is completed, so the next run needs no scan at all.
    assert calls["settled"] == [
        ("inv_local", {"external_id": "in_found", "status": "paid"})
    ]


def test_a_reservation_the_processor_never_saw_is_discarded_and_retried(monkeypatch):
    """The other half of that case. The claim has to be released, or the guard becomes a
    permanent hold on a charge nobody ever made — the payer is never billed again."""
    renewals, calls = _wire(
        monkeypatch,
        existing=_Record(external_id=None, status="draft"),
        found=None,
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["discarded"] == ["inv_local"]
    assert result["issued"], "the period must still get charged"
    assert calls["paid_through"] == [("u1", datetime(2027, 3, 8, 13, tzinfo=UTC))]


def test_the_period_key_is_stable_for_the_same_period(monkeypatch):
    """It is both the idempotency key and the invoice metadata, so it has to survive a
    process restart — anything derived from "now" would not."""
    from blueprints.subscription.services.billing import Period
    from blueprints.subscription.services import renewals

    period = Period(datetime(2027, 2, 8, 13, tzinfo=UTC),
                    datetime(2027, 3, 8, 13, tzinfo=UTC))

    assert renewals.period_key("u1", period) == renewals.period_key("u1", period)
    assert renewals.period_key("u1", period) != renewals.period_key("u2", period)


class _Extension:
    def __init__(self, entity_id="e1", code="BILL", amount=4258, id="ext_1"):
        self.id = id
        self.entity_id = entity_id
        self.function_code = code
        self.extension_amount = amount


def test_a_cancel_extension_rides_the_next_invoice(monkeypatch):
    """Cancelling records what is owed rather than charging it, so that an expired card
    cannot stop somebody leaving. The runner collects it — the role Stripe's anchor
    invoice used to play."""
    renewals, calls = _wire(monkeypatch, extensions=[_Extension(amount=4258)])

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    _cid, invoice, _kw = calls["issued"][0]
    assert invoice.total == 40000 + 4258            # renewal + extension
    assert any("cancellation" in line.description for line in invoice.lines)


def test_an_extension_line_is_named_from_the_catalog_not_from_the_code(monkeypatch):
    """It used to title-case the module CODE. "PETTY_CASH" happens to come out "Petty
    Cash", so the bug hid until a Payment Request extension printed "Bill" — a word the
    catalog does not use — on an invoice whose other lines said "Payment Request".

    Priced as a ONE-MODULE set: the extension is for the module that was cancelled, so
    naming it after the entity's bundle would claim a charge for something still held.
    """
    from blueprints.subscription.services import store

    renewals, calls = _wire(monkeypatch, extensions=[_Extension(code="BILL")])
    asked: list[list[str]] = []

    def _plan_for(codes):
        codes = [str(c).upper() for c in codes]
        asked.append(codes)
        return {
            ("BILL",): _Plan("Payment Request", 28000),
            ("PETTY_CASH",): _Plan("Petty Cash", 28000),
        }.get(tuple(sorted(codes)), _Plan())

    monkeypatch.setattr(store, "billing_plan_for_codes", _plan_for)

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    _cid, invoice, _kw = calls["issued"][0]
    extension = next(ln for ln in invoice.lines if "cancellation" in ln.description)
    assert extension.product_name == "Payment Request (access after cancellation)"
    assert "Bill (" not in extension.description
    assert ["BILL"] in asked, "the extension is priced per module, not per bundle"


def test_a_module_with_no_catalog_row_still_gets_billed(monkeypatch):
    """A label must never cost a collection. Falls back to the old title-cased code."""
    from blueprints.subscription.services import store

    renewals, calls = _wire(monkeypatch, extensions=[_Extension(code="PETTY_CASH")])
    monkeypatch.setattr(
        store, "billing_plan_for_codes",
        lambda codes: None if list(codes) == ["PETTY_CASH"] else _Plan(),
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    _cid, invoice, _kw = calls["issued"][0]
    extension = next(ln for ln in invoice.lines if "cancellation" in ln.description)
    assert extension.product_name == "Petty Cash (access after cancellation)"
    assert invoice.total == 40000 + 4258


def test_a_payer_whose_LAST_entity_was_cancelled_is_still_billed(monkeypatch):
    """The case this mechanism exists for. Nothing renews, so the payer has no billable
    modules at all — but they still owe the days they were promised. Filtering them out
    for having nothing to renew would give those days away."""
    renewals, calls = _wire(
        monkeypatch,
        rows=[_Row("e1", "BILL", phase="scheduled_cancel")],   # nothing billable
        extensions=[_Extension(amount=4258)],
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert result["issued"], "the extension must still be collected"
    _cid, invoice, _kw = calls["issued"][0]
    assert invoice.total == 4258                    # extension only
    assert invoice.currency == "hkd"                # from the payer, not a plan


def test_a_payer_who_is_not_due_is_left_alone(monkeypatch):
    renewals, calls = _wire(
        monkeypatch, accounts=[_Account("u1", paid_through=NOW + timedelta(days=5))]
    )

    result = renewals.run_renewals(NOW, scope=renewals.ALL_PAYERS, issue=True)

    assert calls["issued"] == []
    assert result == {"planned": [], "issued": [], "failed": [], "skipped": []}


# --- closing the extension out --------------------------------------------------
#
# pending_extensions_for_payer selects on extension_state == "pending", so an extension
# that is never moved off it is picked up by EVERY later renewal: the customer pays the
# same cancellation fee once a month, forever, for a module they already left.
#
# Found in live data, not here — a cancelled module sat at "pending" with its amount
# after the invoice carrying it had been paid. EXT_INVOICED existed in constants.py and
# was assigned nowhere in the codebase.


def test_a_collected_extension_is_closed_out_so_it_cannot_ride_again(monkeypatch):
    renewals, calls = _wire(monkeypatch, extensions=[_Extension(id="ext_9")])

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["marked"] == [["ext_9"]]


def test_an_extension_is_not_closed_out_until_the_money_is_collected(monkeypatch):
    """Marking on a failed charge drops the fee silently — the days were granted either
    way, so it would never be billed again. Same rule as paid_through."""
    renewals, calls = _wire(
        monkeypatch,
        extensions=[_Extension()],
        issued={"id": "in_1", "status": "open"},      # declined
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["marked"] == []
    assert calls["paid_through"] == []                # and neither moved


def test_an_adopted_invoice_still_closes_its_extensions(monkeypatch):
    """The crash-recovery path: an earlier run charged the customer and died before
    recording it. The extension rode THAT invoice, so leaving it pending would put it on
    the next one too — the double charge this whole mechanism guards against."""
    renewals, calls = _wire(
        monkeypatch,
        extensions=[_Extension(id="ext_3")],
        existing=_Record(status="paid"),
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == []                      # nothing re-charged
    assert calls["marked"] == [["ext_3"]]
    assert result["skipped"][0]["reason"] == "already invoiced; adopted"


def test_an_unpaid_adopted_invoice_leaves_the_extension_pending(monkeypatch):
    """An invoice that exists but is not paid has collected nothing, so the extension is
    still owed and must stay on the books."""
    renewals, calls = _wire(
        monkeypatch,
        extensions=[_Extension()],
        existing=_Record(status="open"),
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["marked"] == []


# --- an entity already charged for the period ----------------------------------
#
# A purchase or a trial conversion landing ON a period boundary bills its own entity for
# the whole of that period. The renewal for the same period must therefore skip THAT
# entity — and only that one. Getting either half wrong costs real money: re-billing it
# charges twice for the same days, and skipping the account wholesale (which is what
# advancing ``paid_through`` from the conversion used to do) leaves every sibling unbilled
# for the month, silently, because a payer who is not due raises no invoice to miss.


class _BilledRow(_Row):
    def __init__(self, entity_id="e1", code="BILL", phase="active", first_billed_at=None):
        super().__init__(entity_id, code, phase)
        self.first_billed_at = first_billed_at


def test_an_entity_billed_inside_the_period_is_not_renewed_for_it_again(monkeypatch):
    """It already paid for these days in its own invoice."""
    renewals, calls = _wire(
        monkeypatch,
        rows=[_BilledRow(entity_id="e1", first_billed_at=PAID_THROUGH)],
    )

    result = renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["issued"] == [], "the entity was charged twice for one period"
    assert result["skipped"][0]["reason"] == "already covered this period"


def test_its_SIBLINGS_are_still_billed_for_that_period(monkeypatch):
    """The bug this pair exists for.

    One entity converting on the boundary must not settle the account. Steady Co went a
    full month unbilled because a sibling's conversion advanced ``paid_through`` and the
    renewal then found the payer not due at all.
    """
    renewals, calls = _wire(
        monkeypatch,
        rows=[
            _BilledRow(entity_id="converted", first_billed_at=PAID_THROUGH),
            _BilledRow(entity_id="sibling", first_billed_at=ANCHOR),
        ],
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert len(calls["issued"]) == 1
    invoice = calls["issued"][0][1]
    assert [line.entity_id for line in invoice.lines] == ["sibling"]


def test_a_period_covered_by_someone_elses_invoice_still_advances_the_cycle(monkeypatch):
    """Otherwise the account is due forever and eventually lapses for non-payment.

    Nothing is billable, but the period IS paid for. Leaving ``paid_through`` behind
    would re-check the account every day and, past the grace window, revoke access over
    money that was collected.
    """
    renewals, calls = _wire(
        monkeypatch,
        rows=[_BilledRow(entity_id="e1", first_billed_at=PAID_THROUGH)],
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["paid_through"] == [("u1", datetime(2027, 3, 8, 13, tzinfo=UTC))]


def test_an_account_with_nothing_left_does_not_advance(monkeypatch):
    """"Nothing billable" and "already covered" are different nothings.

    A payer whose modules have all lapsed must not have their cycle rolled forward, or
    they collect free periods for as long as the job runs.
    """
    renewals, calls = _wire(monkeypatch, rows=[_BilledRow(phase="expired")])

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert calls["paid_through"] == []
    assert calls["issued"] == []


def test_a_past_period_does_not_exempt_an_entity_forever(monkeypatch):
    """``first_billed_at`` falls inside exactly one period; later ones renew normally."""
    renewals, calls = _wire(
        monkeypatch,
        rows=[_BilledRow(entity_id="e1", first_billed_at=ANCHOR - timedelta(days=400))],
    )

    renewals.run_renewals(NOW, scope=["u1"], issue=True)

    assert len(calls["issued"]) == 1
