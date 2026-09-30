"""The payer portal read model and its gate.

Two things are worth pinning down here, and the table layout is neither.

* **The status a module gets is the one the entity's own card would give it.** The
  portal derives status from ``access.py`` rather than from the phase column, because a
  phase stays ``active`` until something writes it while access ends on a date that
  passes unattended. Every branch of that derivation is exercised below, including the
  two that look like duplicates and are not: a cancelled TRIAL keeps its free days, a
  cancelled PAID module keeps days it was charged for.

* **The gate is the payer, and there is no id to tamper with.** The endpoint takes no
  entity, filters on ``payer_user_id``, and therefore cannot be pointed at somebody
  else's companies. What the tests can check is the other half: that a token without a
  user is refused, and that an entity-scoped token is NOT refused — profile is reached
  with an unscoped one, so requiring the claim would break the only path the UI uses.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest

UTC = timezone.utc
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _row(code, phase, **fields):
    """A module row with the optional dates absent — set only what the branch needs."""
    return SimpleNamespace(
        entity_id=fields.pop("entity_id", "e1"),
        function_code=code,
        phase=phase,
        trial_end=fields.pop("trial_end", None),
        app_access_until=fields.pop("app_access_until", None),
        first_billed_at=fields.pop("first_billed_at", None),
        **fields,
    )


# --- Status derivation -------------------------------------------------------


def _state(row, *, paid_through=None):
    from blueprints.subscription.services import portal

    return portal._module_state(
        row, now=NOW, paid_through=paid_through, grace_days=7
    )


def test_no_row_reads_not_subscribed(app):
    from blueprints.subscription.services import portal

    state = _state(None)
    assert state["status"] == portal.STATUS_NOT_SUBSCRIBED
    assert state["date"] is None


def test_running_trial_shows_its_own_end_date(app):
    from blueprints.subscription.services import portal

    ends = NOW + timedelta(days=9)
    state = _state(_row("PAYMENT_REQUEST", "trial", trial_end=ends))
    assert state["status"] == portal.STATUS_TRIALING
    assert state["date_label"] == "Trial ends"
    assert state["date"] == ends


def test_active_module_shows_the_payers_paid_through(app):
    """"Next billing" is an ACCOUNT fact. One payer, one cycle, one date — so it comes
    from paid_through and not from anything on the module row."""
    from blueprints.subscription.services import portal

    paid_to = NOW + timedelta(days=20)
    state = _state(
        _row("PETTY_CASH", "active", first_billed_at=NOW - timedelta(days=40)),
        paid_through=paid_to,
    )
    assert state["status"] == portal.STATUS_ACTIVE
    assert state["date_label"] == "Next billing"
    assert state["date"] == paid_to


def test_cancelled_paid_module_expires_on_its_bought_days(app):
    from blueprints.subscription.services import portal

    until = NOW + timedelta(days=38)
    state = _state(
        _row(
            "PETTY_CASH",
            "scheduled_cancel",
            app_access_until=until,
            first_billed_at=NOW - timedelta(days=40),
        ),
        paid_through=NOW + timedelta(days=20),
    )
    assert state["status"] == portal.STATUS_CANCELLED
    assert state["date_label"] == "Expires"
    assert state["date"] == until


def test_cancelled_trial_keeps_its_free_days_and_says_so(app):
    """Same phase as the case above and a different sentence. Nothing was bought, so the
    date is the trial's own end — printing "Expires" against a paid-through it never had
    would invent a purchase."""
    from blueprints.subscription.services import portal

    ends = NOW + timedelta(days=5)
    state = _state(
        _row("PAYMENT_REQUEST", "scheduled_cancel", trial_end=ends, app_access_until=ends)
    )
    assert state["status"] == portal.STATUS_CANCELLED
    assert state["date_label"] == "Trial ends"
    assert state["date"] == ends


def test_past_due_is_never_folded_into_active(app):
    from blueprints.subscription.services import portal

    paid_to = NOW - timedelta(days=2)
    state = _state(
        _row("PAYMENT_REQUEST", "past_due", first_billed_at=NOW - timedelta(days=40)),
        paid_through=paid_to,
    )
    assert state["status"] == portal.STATUS_PAST_DUE
    assert state["date_label"] == "Access ends"
    # Paid-through plus the grace window, not paid-through itself.
    assert state["date"] == paid_to + timedelta(days=7)


def test_lapsed_paid_module_reads_ended_not_not_subscribed(app):
    """A phase left at ``active`` past its paid-through. It grants no access, and the
    honest line is the date it stopped: "not subscribed" would tell a customer they
    never bought something they did."""
    from blueprints.subscription.services import portal

    state = _state(
        _row("PETTY_CASH", "active", first_billed_at=NOW - timedelta(days=90)),
        paid_through=NOW - timedelta(days=30),
    )
    assert state["status"] == portal.STATUS_ENDED
    assert state["date_label"] == "Ended"
    # The day it really stopped: the paid period it ran out of, already behind us.
    assert state["date"] == NOW - timedelta(days=30)
    # The mirror image of the test below: a module that was PAID for must never be
    # described as an expired trial, which would deny the purchase outright.
    assert state["status"] != portal.STATUS_TRIAL_EXPIRED


def test_a_module_cut_off_early_prints_no_date_rather_than_the_accounts(app):
    """Terminated on the spot: ``cancelled``, access cut, no ``app_access_until`` of its own.
    The last date to fall back on was the billing ACCOUNT's paid-through - still ahead,
    because the account renews for its other companies - so the list read "Ended 18 Oct
    2026", a date to come under a word that says it is past. It prints none instead."""
    from blueprints.subscription.services import portal

    state = _state(
        _row("PETTY_CASH", "cancelled", first_billed_at=NOW - timedelta(days=60)),
        paid_through=NOW + timedelta(days=23),
    )
    assert state["status"] == portal.STATUS_ENDED
    assert state["date"] is None
    assert state["date_label"] is None

    # Its own access end, once passed, is still printed.
    until = NOW - timedelta(days=4)
    ran_out = _state(
        _row("PETTY_CASH", "cancelled", first_billed_at=NOW - timedelta(days=60),
             app_access_until=until),
        paid_through=NOW + timedelta(days=23),
    )
    assert (ran_out["date_label"], ran_out["date"]) == ("Ended", until)


def test_a_trial_that_ran_out_says_so_rather_than_just_ended(app):
    """Free days that expired, with nothing ever charged. ``first_billed_at`` is the only
    thing separating this from the lapsed PAID module above — they reach the same branch
    and need opposite words."""
    from blueprints.subscription.services import portal

    ended = NOW - timedelta(days=3)
    state = _state(_row("PAYMENT_REQUEST", "trial", trial_end=ended))

    assert state["status"] == portal.STATUS_TRIAL_EXPIRED
    assert portal.STATUS_LABELS[state["status"]] == "trial expired"
    assert state["date_label"] == "Trial ended"
    assert state["date"] == ended


# --- The assembled table -----------------------------------------------------


@pytest.fixture
def payer_portal(app, monkeypatch):
    """Drive ``build_payer_subscriptions`` off synthetic rows.

    Every model query and store read is replaced. What is under test is the assembly —
    grouping by entity, searching, sorting, paging — and going through real tables would
    need the second schema attached on the builder's own connection for no gain.
    """
    from blueprints.subscription.services import portal

    def _install(rows, entities, *, paid_through=None, anchor=None):
        by_id = {e["id"]: e for e in entities}

        class _Query:
            def __init__(self, values):
                self._values = values

            def filter(self, *_args, **_kwargs):
                return self

            def all(self):
                return self._values

        monkeypatch.setattr(
            portal,
            "Entity",
            SimpleNamespace(
                query=_Query(
                    [
                        SimpleNamespace(
                            id=e["id"], name=e["name"], country_code=e.get("country")
                        )
                        for e in entities
                    ]
                ),
                id=SimpleNamespace(in_=lambda *_: None),
            ),
        )
        monkeypatch.setattr(
            portal,
            "EntityFunction",
            SimpleNamespace(
                query=_Query(
                    [
                        SimpleNamespace(
                            function_code="PETTY_CASH", function_name="Petty Cash"
                        ),
                        SimpleNamespace(
                            function_code="PAYMENT_REQUEST", function_name="Bill Payment"
                        ),
                    ]
                ),
                function_code=SimpleNamespace(in_=lambda *_: None),
            ),
        )
        monkeypatch.setattr(
            portal,
            "CountryInfo",
            SimpleNamespace(
                query=_Query(
                    [
                        SimpleNamespace(country_code="HK", country_name_en="Hong Kong"),
                        SimpleNamespace(country_code="SG", country_name_en="Singapore"),
                    ]
                ),
                country_code=SimpleNamespace(in_=lambda *_: None),
            ),
        )
        monkeypatch.setattr(
            portal,
            "User",
            SimpleNamespace(
                query=SimpleNamespace(
                    get=lambda _id: SimpleNamespace(
                        first_name="Harry", last_name="Kim", email="hk@example.com"
                    )
                )
            ),
        )

        from blueprints.subscription.services import clock, policy
        from blueprints.subscription.services import store as sub_store

        monkeypatch.setattr(clock, "now", lambda: NOW)
        monkeypatch.setattr(
            policy, "current", lambda: SimpleNamespace(past_due_window_days=7)
        )
        monkeypatch.setattr(sub_store, "module_rows_for_payer", lambda _u: rows)
        monkeypatch.setattr(
            sub_store, "paid_through_for_user", lambda _u: paid_through
        )
        # The screen reads it PER COMPANY now — each is billed on the card it was put on,
        # and two rows of one payer can hold two different dates. Same value here: these
        # cases describe an account with one card.
        monkeypatch.setattr(
            sub_store, "paid_through_for_entity", lambda _e: paid_through
        )
        monkeypatch.setattr(
            sub_store, "billing_cycle_for_user", lambda _u: (anchor, "HKD")
        )
        return by_id

    return _install


def _entity(portal_result, name):
    return next(e for e in portal_result["entities"] if e["entity_name"] == name)


def test_every_canonical_module_gets_a_line_even_when_never_held(
    app, payer_portal
):
    """The design's Amazon row: Petty Cash live, Bill Payment "not subscribed". A module
    with no row still needs a line, or the table silently implies it does not exist."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[
            _row(
                "PETTY_CASH",
                "active",
                entity_id="e1",
                first_billed_at=NOW - timedelta(days=40),
            )
        ],
        entities=[{"id": "e1", "name": "Amazon", "country": "HK"}],
        paid_through=NOW + timedelta(days=28),
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1")

    row = _entity(result, "Amazon")
    assert [m["code"] for m in row["modules"]] == ["PETTY_CASH", "PAYMENT_REQUEST"]
    assert row["modules"][0]["status_label"] == "active"
    assert row["modules"][1]["status_label"] == "not subscribed"
    assert row["modules"][1]["date"] is None
    assert row["country"] == "Hong Kong"
    assert row["settings_path"] == "/entity/settings/module/e1"


def test_search_matches_the_status_words_on_screen(app, payer_portal):
    """A customer looking for what is winding down types "cancelled" — the word the badge
    shows — so the haystack includes status labels, not just names."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[
            _row("PETTY_CASH", "active", entity_id="e1",
                 first_billed_at=NOW - timedelta(days=40)),
            _row("PETTY_CASH", "scheduled_cancel", entity_id="e2",
                 app_access_until=NOW + timedelta(days=10),
                 first_billed_at=NOW - timedelta(days=40)),
        ],
        entities=[
            {"id": "e1", "name": "Apple", "country": "HK"},
            {"id": "e2", "name": "Microsoft", "country": "HK"},
        ],
        paid_through=NOW + timedelta(days=28),
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1", query="cancelled")

    assert [e["entity_name"] for e in result["entities"]] == ["Microsoft"]
    assert result["total"] == 1


def test_status_sort_puts_what_needs_a_decision_first(app, payer_portal):
    """Ascending by status is only useful one way round: overdue above healthy."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[
            _row("PETTY_CASH", "active", entity_id="e1",
                 first_billed_at=NOW - timedelta(days=40)),
            _row("PETTY_CASH", "past_due", entity_id="e2",
                 first_billed_at=NOW - timedelta(days=40)),
            _row("PETTY_CASH", "trial", entity_id="e3",
                 trial_end=NOW + timedelta(days=5)),
        ],
        entities=[
            {"id": "e1", "name": "Apple", "country": "HK"},
            {"id": "e2", "name": "Microsoft", "country": "HK"},
            {"id": "e3", "name": "TSMC", "country": "SG"},
        ],
        paid_through=NOW + timedelta(days=28),
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1", sort="status")

    assert [e["entity_name"] for e in result["entities"]] == [
        "Microsoft",
        "TSMC",
        "Apple",
    ]


def test_paging_reports_the_full_total_not_the_window(app, payer_portal):
    """"Showing 1–2 of 5" needs both numbers; returning len(window) as the total would
    make the footer claim the payer has two companies."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[
            _row("PETTY_CASH", "trial", entity_id=f"e{i}",
                 trial_end=NOW + timedelta(days=i))
            for i in range(1, 6)
        ],
        entities=[
            {"id": f"e{i}", "name": f"Entity {i}", "country": "HK"}
            for i in range(1, 6)
        ],
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1", page=2, per_page=2)

    assert result["total"] == 5
    assert result["pages"] == 3
    assert result["page"] == 2
    assert [e["entity_name"] for e in result["entities"]] == ["Entity 3", "Entity 4"]


def test_page_past_the_end_clamps_rather_than_emptying(app, payer_portal):
    """A stale ?page=9 after a search narrows the set must not show a blank table."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[_row("PAYMENT_REQUEST", "trial", entity_id="e1", trial_end=NOW + timedelta(days=3))],
        entities=[{"id": "e1", "name": "Apple", "country": "HK"}],
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1", page=9, per_page=2)

    assert result["page"] == 1
    assert len(result["entities"]) == 1


def test_internal_sort_keys_never_reach_the_response(app, payer_portal):
    """``_date`` / ``_next_date`` exist only to sort on. Leaking a datetime into JSON
    would break serialisation and expose an unformatted field the client would use."""
    from blueprints.subscription.services import portal

    payer_portal(
        rows=[_row("PAYMENT_REQUEST", "trial", entity_id="e1", trial_end=NOW + timedelta(days=3))],
        entities=[{"id": "e1", "name": "Apple", "country": "HK"}],
    )

    with app.app_context():
        result = portal.build_payer_subscriptions("u1")

    entity = result["entities"][0]
    assert "_next_date" not in entity
    assert all("_date" not in m for m in entity["modules"])


# --- Invoices ----------------------------------------------------------------


def _line(entity_id, entity_name, product, amount, kind="full"):
    """``kind`` is what the description reads to tell a renewal from an upgrade:
    ``full`` whole period, ``remaining`` prorated charge, ``unused`` credit."""
    return SimpleNamespace(
        entity_id=entity_id,
        entity_name=entity_name,
        product_name=product,
        amount=amount,
        kind=kind,
    )


def _invoice(ref, *, status="paid", total=40000, lines=(), issued=None, ident="i1",
             memo=None):
    return SimpleNamespace(
        id=f"{ident}-0000-0000-0000-000000000000",
        external_id=ref,
        status=status,
        total=total,
        currency="HKD",
        issued_at=issued or NOW,
        created_at=issued or NOW,
        period_start=NOW - timedelta(days=30),
        period_end=NOW,
        memo=memo,
        lines=list(lines),
    )


@pytest.fixture
def payer_invoices(app, monkeypatch):
    """Drive ``build_payer_invoices`` off synthetic invoices."""
    from blueprints.subscription.models import subscription_invoice as model
    from blueprints.subscription.services import portal

    def _install(invoices):
        class _Query:
            def filter_by(self, **_kw):
                return self

            def order_by(self, *_a):
                return self

            def all(self):
                return invoices

        # Replace the CLASS on the module, not its `query` attribute: flask-sqlalchemy's
        # `query` is a descriptor that resolves a session the moment it is touched, so
        # setattr on it needs an app context that these tests deliberately do not have yet.
        # The order_by columns are read off the class, so the stand-in needs them too.
        monkeypatch.setattr(
            model,
            "SubscriptionInvoice",
            SimpleNamespace(
                query=_Query(),
                period_start=SimpleNamespace(desc=lambda: None),
                created_at=SimpleNamespace(desc=lambda: None),
            ),
        )
        # Money formatting reaches for currency_info; the symbol is not what is under test.
        monkeypatch.setattr(portal, "_money", lambda amt, cur: f"HK${amt / 100:,.2f}")
        return portal

    return _install


def test_filtering_by_entity_shows_that_entitys_share_not_the_invoice_total(
    app, payer_invoices
):
    """One invoice, two companies. Printing the whole total against one of them would
    overstate what that company cost by whatever the other one rode in on."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=68000,
                lines=[
                    _line("e1", "Acme", "Super Minty", 40000),
                    _line("e2", "Beta", "Petty Cash", 28000),
                ],
            )
        ]
    )

    with app.app_context():
        everything = portal.build_payer_invoices("u1")
        just_acme = portal.build_payer_invoices("u1", entity_id="e1")

    assert everything["invoices"][0]["amount"] == "HK$680.00"
    assert just_acme["invoices"][0]["amount"] == "HK$400.00"
    # ...and the description narrows with it, headline and detail together.
    assert everything["invoices"][0]["description"] == "Renewal · Super Minty, Petty Cash"
    assert everything["invoices"][0]["description_detail"] == (
        "7 Jul – 6 Aug 2026 · 2 entities"
    )
    assert just_acme["invoices"][0]["description"] == "Renewal · Super Minty"
    assert just_acme["invoices"][0]["description_detail"] == "7 Jul – 6 Aug 2026 · Acme"


def test_an_invoice_with_no_line_for_that_entity_drops_out(app, payer_invoices):
    portal = payer_invoices(
        [
            _invoice("in_1", lines=[_line("e1", "Acme", "Super Minty", 40000)]),
            _invoice("in_2", ident="i2", lines=[_line("e2", "Beta", "Petty Cash", 28000)]),
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1", entity_id="e2")

    assert result["total"] == 1
    assert result["invoices"][0]["reference"] == "in_2"


def test_the_entity_dropdown_comes_from_history_not_current_subscriptions(
    app, payer_invoices
):
    """`entity_name` is a SNAPSHOT on the line. A company you have stopped paying for
    still has invoices and still belongs in the filter."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                lines=[
                    _line("e2", "Zeta", "Petty Cash", 28000),
                    _line("e1", "Acme", "Super Minty", 40000),
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert [e["name"] for e in result["entity_options"]] == ["Acme", "Zeta"]


def test_a_repeated_product_is_named_once(app, payer_invoices):
    """Two companies on the same plan is one product, not two identical words."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                lines=[
                    _line("e1", "Acme", "Super Minty", 40000),
                    _line("e2", "Beta", "Super Minty", 40000),
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Renewal · Super Minty"


def test_an_upgrade_is_described_by_what_was_bought_not_what_was_credited(
    app, payer_invoices
):
    """An upgrade carries both halves of the change: the old plan credited and the new
    one charged. Naming both read "Petty Cash · Super Minty" — which describes the
    transition, and on one entity looks like two subscriptions. Naming only the new one
    lost the change entirely: three invoices in a month all read "Super Minty"."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=12000,
                lines=[
                    _line("e1", "Acme", "Super Minty", 40000, kind="remaining"),
                    _line("e1", "Acme", "Petty Cash", -28000, kind="unused"),
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Upgrade · Petty Cash → Super Minty"
    assert result["invoices"][0]["description_detail"] == "7 Jul – 6 Aug 2026 · Acme"


def test_a_module_starting_mid_period_is_not_called_a_renewal(app, payer_invoices):
    """Prorated, nothing to credit — the customer bought something they did not have."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=10267,
                lines=[_line("e1", "Acme", "Payment Request", 10267, kind="remaining")],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "New subscription · Payment Request"


def test_an_extension_only_invoice_says_what_it_is(app, payer_invoices):
    """Access bought past a cancellation, and nothing else on the invoice. Reading
    "Petty Cash" here told a customer they had been billed for a subscription they had
    just cancelled."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=4000,
                lines=[
                    _line("e1", "Acme", "Petty Cash (access extension)", 4000,
                          kind="remaining")
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Access extension · Petty Cash"
    # Not repeated in the detail: the headline already said it.
    assert "extension" not in result["invoices"][0]["description_detail"]


def test_a_renewal_that_only_collects_an_extension_says_what_it_is(app, payer_invoices):
    """A card whose last company was cancelled still renews - to collect the extension that
    company was promised access for. The renewal runner writes that line as a WHOLE-PERIOD
    one (``Line.kind``'s default), and a whole-period line alone used to make the invoice a
    "Renewal · Petty Cash": the renewal of a module nobody has any more."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=4000,
                lines=[
                    _line("e1", "Acme", "Petty Cash (access after cancellation)", 4000,
                          kind="full")
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Access extension · Petty Cash"


def test_an_invoice_that_only_credits_still_names_its_product(app, payer_invoices):
    """Dropping negative lines must not leave a credit note with an empty description."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=-28000,
                lines=[_line("e1", "Acme", "Petty Cash", -28000, kind="unused")],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Credit · Petty Cash"


def test_a_renewal_carrying_an_extension_is_still_a_renewal_and_says_so(
    app, payer_invoices
):
    """The whole-period lines are why the invoice exists; the extension rides along. It
    is called out in the detail because a cancellation charge is the one line on a
    renewal a customer is not expecting.

    The "(access after cancellation)" suffix stays off the headline — summarised into one
    cell it makes the same product look like two, and dedupe cannot see it."""
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=32000,
                lines=[
                    _line("e1", "Acme", "Petty Cash", 28000),
                    # Whole-period, as the renewal runner writes an extension it collects.
                    _line("e2", "Beta", "Petty Cash (access after cancellation)", 4000,
                          kind="full"),
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["description"] == "Renewal · Petty Cash"
    assert result["invoices"][0]["description_detail"] == (
        "7 Jul – 6 Aug 2026 · 2 entities · 1 access extension"
    )


def test_the_memo_travels_with_the_row_rather_than_being_rebuilt(app, payer_invoices):
    """The only place the arithmetic behind a prorated figure is written down, and it was
    written when the biller knew the figures. Re-deriving it from the columns is how the
    two start disagreeing."""
    memo = (
        "Acme changed from Petty Cash to Super Minty on 20 Jun 2026, with 16 of 30 days "
        "left in the period. Unused Petty Cash credited 149.33; Super Minty charged "
        "213.33 for the same days. Net 64.00."
    )
    portal = payer_invoices(
        [
            _invoice(
                "in_1",
                total=6400,
                memo=memo,
                lines=[
                    _line("e1", "Acme", "Super Minty", 21333, kind="remaining"),
                    _line("e1", "Acme", "Petty Cash", -14933, kind="unused"),
                ],
            )
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["memo"] == memo


def test_statuses_are_translated_from_the_processors_vocabulary(app, payer_invoices):
    portal = payer_invoices(
        [
            _invoice("in_1", status="paid", lines=[_line("e1", "A", "Petty Cash", 1)]),
            _invoice("in_2", ident="i2", status="uncollectible",
                     lines=[_line("e1", "A", "Petty Cash", 1)]),
            _invoice("in_3", ident="i3", status="open",
                     lines=[_line("e1", "A", "Petty Cash", 1)]),
        ]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert [i["status_label"] for i in result["invoices"]] == ["Paid", "Failed", "Unpaid"]


def test_a_reserved_invoice_still_has_something_to_show(app, payer_invoices):
    """`external_id` is NULL when a row was reserved but nothing was ever sent. A blank
    reference column would be worse than a local one."""
    reserved = _invoice(None, lines=[_line("e1", "Acme", "Petty Cash", 28000)])
    portal = payer_invoices([reserved])

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    reference = result["invoices"][0]["reference"]
    assert reference == f"#{reserved.id[:8].upper()}"
    assert reference.strip("#")


def test_the_payment_method_is_not_guessed(app, payer_invoices):
    """Which card paid an invoice is not stored, and the account's CURRENT card is a
    different question. None, so the UI can say "not recorded" instead of a wrong card."""
    portal = payer_invoices(
        [_invoice("in_1", lines=[_line("e1", "Acme", "Petty Cash", 28000)])]
    )

    with app.app_context():
        result = portal.build_payer_invoices("u1")

    assert result["invoices"][0]["payment_method"] is None


def test_a_currency_code_is_spaced_off_the_amount(app, monkeypatch):
    """"HKD57.54" scans as one token rather than a currency and an amount.

    ``currency_info`` records no symbol for plenty of currencies and the lookup falls back
    to the bare code, so this is the ordinary case rather than the edge one. Same rule as
    ``modules._fmt_money``: a code is spaced, a glyph is not.
    """
    from blueprints.entity.models import currency_info
    from blueprints.subscription.services import portal

    monkeypatch.setattr(
        currency_info,
        "CurrencyInfo",
        SimpleNamespace(
            query=SimpleNamespace(
                filter_by=lambda **_k: SimpleNamespace(first=lambda: None)
            )
        ),
    )

    with app.app_context():
        assert portal._money(5754, "HKD") == "HKD 57.54"


def test_a_currency_glyph_is_not_spaced_off_the_amount(app, monkeypatch):
    """"HK$ 57.54" is not how a symbol is written.

    Patched on ``models.db`` because that is where the lookup reads it: the symbol
    resolution moved out of ``portal._money`` into ``money.symbol``, which imports
    ``CurrencyInfo`` from ``models.db`` like the rest of that module. Same class either
    way -- ``models.db`` re-exports it -- but patching a module attribute only
    intercepts the module that reads it.
    """
    import models.db as models_db
    from blueprints.subscription.services import portal

    monkeypatch.setattr(
        models_db,
        "CurrencyInfo",
        SimpleNamespace(
            query=SimpleNamespace(
                filter_by=lambda **_k: SimpleNamespace(
                    first=lambda: SimpleNamespace(symbol="HK$")
                )
            )
        ),
    )

    with app.app_context():
        assert portal._money(5754, "HKD") == "HK$57.54"


# --- Change subscriber (read only) -------------------------------------------


def _member(user_id, first, last, email):
    return SimpleNamespace(
        id=user_id, first_name=first, last_name=last, email=email, username=email
    )


@pytest.fixture
def subscriber_options(app, monkeypatch):
    """Drive ``build_subscriber_options`` off a synthetic entity, payer and members."""
    from blueprints.subscription.services import portal
    from blueprints.subscription.services import store as sub_store

    def _install(*, payer_id="u1", entity=("e1", "NVIDIA"), users=(), members=None):
        by_id = {u.id: u for u in users}
        monkeypatch.setattr(
            portal,
            "Entity",
            SimpleNamespace(
                query=SimpleNamespace(
                    get=lambda _id: (
                        SimpleNamespace(id=entity[0], name=entity[1])
                        if entity and _id == entity[0]
                        else None
                    )
                )
            ),
        )
        monkeypatch.setattr(
            portal,
            "User",
            SimpleNamespace(query=SimpleNamespace(get=lambda _id: by_id.get(_id))),
        )
        monkeypatch.setattr(sub_store, "payer_for_entity", lambda _e: payer_id)
        if members is not None:
            monkeypatch.setattr(
                portal, "_admin_candidates", lambda _e: [portal._person(m) for m in members]
            )
        return portal

    return _install


def test_only_the_payer_can_read_who_else_could_be_billed(app, subscriber_options):
    """The first payer-portal read with an entity id IN the request, so it is the first
    that could be pointed somewhere. Being the payer is the same test that gates changing
    the subscription at all."""
    portal = subscriber_options(payer_id="someone-else", users=[], members=[])

    with app.app_context():
        assert portal.build_subscriber_options("u1", "e1") is None


def test_an_entity_that_nobody_pays_for_is_not_readable(app, subscriber_options):
    portal = subscriber_options(payer_id=None, members=[])

    with app.app_context():
        assert portal.build_subscriber_options("u1", "e1") is None


def test_an_unknown_entity_is_not_readable(app, subscriber_options):
    portal = subscriber_options()

    with app.app_context():
        assert portal.build_subscriber_options("u1", "nope") is None


def test_the_current_payer_leads_the_list_and_the_rest_are_alphabetical(
    app, subscriber_options
):
    harry = _member("u1", "Harry", "Kim", "harry.kim@oliveandvine.com")
    others = [
        _member("u2", "Rebecca", "Park", "rebecca.park@oliveandvine.com"),
        _member("u3", "Jiwon", "Kim", "jiwon.kim@oliveandvine.com"),
        _member("u4", "Daniel", "Park", "daniel.park@oliveandvine.com"),
    ]
    portal = subscriber_options(users=[harry], members=[*others, harry])

    with app.app_context():
        result = portal.build_subscriber_options("u1", "e1")

    assert result["entity"] == {"entity_id": "e1", "entity_name": "NVIDIA"}
    assert result["current"]["name"] == "Harry Kim"
    assert [c["name"] for c in result["candidates"]] == [
        "Harry Kim",
        "Daniel Park",
        "Jiwon Kim",
        "Rebecca Park",
    ]
    assert [c["is_current"] for c in result["candidates"]] == [True, False, False, False]


def test_the_current_payer_is_listed_even_when_they_are_no_longer_an_admin(
    app, subscriber_options
):
    """A demoted payer is still the payer. Omitting them would contradict the banner
    above the list, which names them."""
    harry = _member("u1", "Harry", "Kim", "harry.kim@oliveandvine.com")
    portal = subscriber_options(
        users=[harry],
        members=[_member("u2", "Rebecca", "Park", "rebecca.park@oliveandvine.com")],
    )

    with app.app_context():
        result = portal.build_subscriber_options("u1", "e1")

    assert [c["name"] for c in result["candidates"]] == ["Harry Kim", "Rebecca Park"]
    assert result["candidates"][0]["is_current"] is True


def test_only_admins_are_offered(app, monkeypatch):
    """The business rule the screen states: a cashier cannot be made responsible for a
    company's bill, so offering one would be offering a choice that must be refused.
    ``super_admin`` outranks admin and is kept — dropping someone for being MORE senior
    than the bar reads as a missing user."""
    from blueprints.subscription.services import portal

    rows = [
        (_member("u1", "Harry", "Kim", "harry.kim@x.com"), "admin"),
        (_member("u2", "Rebecca", "Park", "rebecca.park@x.com"), "cashier"),
        (_member("u3", "Jiwon", "Kim", "jiwon.kim@x.com"), "accountant"),
        (_member("u4", "Daniel", "Park", "daniel.park@x.com"), "super_admin"),
        (_member("u5", "Sam", "Lee", "sam.lee@x.com"), "shop_manager"),
    ]

    class _Chain:
        def join(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return rows

    monkeypatch.setattr(
        portal,
        "db",
        SimpleNamespace(
            session=SimpleNamespace(query=lambda *_a: _Chain(), rollback=lambda: None)
        ),
    )

    with app.app_context():
        assert [c["email"] for c in portal._admin_candidates("e1")] == [
            "harry.kim@x.com",
            "daniel.park@x.com",
        ]


def test_losing_the_member_query_costs_the_list_and_not_the_page(app, monkeypatch):
    """Same posture as the rest of the portal's optional reads: roll back and answer
    nothing, so a Postgres error does not poison the transaction the caller is in."""
    from blueprints.subscription.services import portal

    rolled: list[bool] = []

    def _boom(*_a):
        raise RuntimeError("the database is having a moment")

    monkeypatch.setattr(
        portal,
        "db",
        SimpleNamespace(
            session=SimpleNamespace(query=_boom, rollback=lambda: rolled.append(True))
        ),
    )

    with app.app_context():
        assert portal._admin_candidates("e1") == []
    assert rolled == [True]


def test_the_subscriber_options_route_needs_an_entity(app):
    client = app.test_client()
    response = client.get(
        "/api/me/subscriptions/subscriber-options",
        headers={"Authorization": f"Bearer {_token(app, user_id='u1')}"},
    )
    assert response.status_code == 400


def test_a_company_you_do_not_pay_for_is_a_404_and_not_a_403(app, monkeypatch):
    """"You are not the payer" and "no such company" are the same answer to someone who
    should not be asking. Telling them apart would confirm an id."""
    from blueprints.subscription.services import portal as portal_service

    monkeypatch.setattr(
        portal_service, "build_subscriber_options", lambda *_a, **_k: None
    )

    client = app.test_client()
    response = client.get(
        "/api/me/subscriptions/subscriber-options?entity=e9",
        headers={"Authorization": f"Bearer {_token(app, user_id='u1')}"},
    )
    assert response.status_code == 404
    assert "Access-Control-Allow-Origin" in response.headers


# --- The gate ----------------------------------------------------------------


def _token(app, **claims):
    return jwt.encode(claims, app.config["SECRET_KEY"], algorithm="HS256")


def test_no_bearer_is_refused(app):
    client = app.test_client()
    assert client.get("/api/me/subscriptions").status_code == 401


def test_a_token_this_app_did_not_sign_is_refused(app):
    client = app.test_client()
    forged = jwt.encode({"user_id": "u1"}, "not-the-secret", algorithm="HS256")
    response = client.get(
        "/api/me/subscriptions", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401


def test_a_token_with_no_user_claim_is_refused(app):
    client = app.test_client()
    response = client.get(
        "/api/me/subscriptions",
        headers={"Authorization": f"Bearer {_token(app, entity_id='e1')}"},
    )
    assert response.status_code == 401


def test_an_entity_scoped_token_is_accepted(app, monkeypatch):
    """Profile is reached with an UNSCOPED token and the screen spans entities, so the
    ``entity_id`` claim is not a gate here. Pinning it would refuse the only path the UI
    actually uses."""
    import models.db as models_db
    from blueprints.subscription.services import portal as portal_service

    monkeypatch.setattr(
        models_db,
        "User",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(id="u1"))),
    )
    monkeypatch.setattr(
        portal_service,
        "build_payer_subscriptions",
        lambda *_a, **_k: {"entities": [], "total": 0},
    )

    client = app.test_client()
    response = client.get(
        "/api/me/subscriptions",
        headers={"Authorization": f"Bearer {_token(app, user_id='u1', entity_id='e9')}"},
    )
    assert response.status_code == 200
    assert response.get_json()["total"] == 0
    assert "Access-Control-Allow-Origin" in response.headers
    # Flask appends its own ``Cookie`` to Vary; what matters is that Origin is pinned,
    # so a response cached for one origin is never replayed to another.
    assert "Origin" in response.headers["Vary"]


def test_preflight_answers_without_a_token(app):
    client = app.test_client()
    response = client.open("/api/me/subscriptions", method="OPTIONS")
    assert response.status_code == 204
    assert "Access-Control-Allow-Origin" in response.headers


# --- The handover routes -------------------------------------------------------
#
# Four routes, one shared shell, and the thing worth pinning is that they all answer the
# same way: 401 without a bearer, 400 only for a MISSING routing id, 422 with a full
# sentence for a stated refusal, and CORS on every response including the errors.
#
# 422 and not 403: the service's refusals are written to be read by the person who
# clicked, and the client only shows the server's words when they look like prose.


def _post(app, path, body, **claims):
    return app.test_client().post(
        path,
        json=body,
        headers={"Authorization": f"Bearer {_token(app, **(claims or {'user_id': 'u1'}))}"},
    )


def test_initiating_a_handover_needs_a_bearer(app):
    response = app.test_client().post(
        "/api/me/subscriptions/transfer", json={"entity": "e1", "to_user": "u2"}
    )
    assert response.status_code == 401


def test_initiating_a_handover_needs_an_entity(app):
    response = _post(app, "/api/me/subscriptions/transfer", {"to_user": "u2"})
    assert response.status_code == 400
    assert "entity" in response.get_json()["error"]


def test_initiating_a_handover_needs_a_recipient(app):
    response = _post(app, "/api/me/subscriptions/transfer", {"entity": "e1"})
    assert response.status_code == 400


def test_a_refused_handover_is_a_422_with_the_reason_in_words(app, monkeypatch):
    """The client replaces anything that looks like a machine code with generic copy, so
    a refusal has to arrive as a sentence or the user is told nothing."""
    from blueprints.subscription.services import transfers

    monkeypatch.setattr(
        transfers, "offer_transfer",
        lambda *_a, **_k: (False, "That person needs to be an admin of this company first.", None),
    )

    response = _post(app, "/api/me/subscriptions/transfer",
                     {"entity": "e1", "to_user": "u2"})

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert " " in error and error[0].isupper()
    assert "Access-Control-Allow-Origin" in response.headers


def test_a_successful_offer_returns_it(app, monkeypatch):
    from blueprints.subscription.services import transfers

    monkeypatch.setattr(
        transfers, "offer_transfer",
        lambda *_a, **_k: (True, "The handover request has been sent.", {"id": "t1"}),
    )

    response = _post(app, "/api/me/subscriptions/transfer",
                     {"entity": "e1", "to_user": "u2"})

    assert response.status_code == 200
    assert response.get_json()["transfer"]["id"] == "t1"


def test_an_unexpected_failure_is_a_500_not_a_stack_trace(app, monkeypatch):
    from blueprints.subscription.services import transfers

    def _boom(*_a, **_k):
        raise RuntimeError("processor unreachable")

    monkeypatch.setattr(transfers, "offer_transfer", _boom)

    response = _post(app, "/api/me/subscriptions/transfer",
                     {"entity": "e1", "to_user": "u2"})

    assert response.status_code == 500
    assert "unreachable" not in response.get_json()["error"]
    assert "Access-Control-Allow-Origin" in response.headers


def test_responding_needs_a_transfer_id(app):
    response = _post(app, "/api/me/subscriptions/transfer/respond", {"accept": True})
    assert response.status_code == 400


def test_accepting_passes_the_flag_through(app, monkeypatch):
    from blueprints.subscription.services import transfers

    seen = {}

    def _respond(user_id, transfer_id, *, accept):
        seen.update(user=user_id, transfer=transfer_id, accept=accept)
        return True, "You're now the subscriber for this company.", {"id": transfer_id}

    monkeypatch.setattr(transfers, "respond_to_transfer", _respond)

    response = _post(app, "/api/me/subscriptions/transfer/respond",
                     {"transfer": "t1", "accept": True}, user_id="u2")

    assert response.status_code == 200
    assert seen == {"user": "u2", "transfer": "t1", "accept": True}


def test_declining_is_the_same_route_with_the_flag_off(app, monkeypatch):
    from blueprints.subscription.services import transfers

    seen = {}
    monkeypatch.setattr(
        transfers, "respond_to_transfer",
        lambda u, t, *, accept: (seen.update(accept=accept) or
                                 (True, "You've declined the handover.", None)),
    )

    response = _post(app, "/api/me/subscriptions/transfer/respond",
                     {"transfer": "t1", "accept": False}, user_id="u2")

    assert response.status_code == 200
    assert seen["accept"] is False


def test_cancelling_needs_a_transfer_id(app):
    response = _post(app, "/api/me/subscriptions/transfer/cancel", {})
    assert response.status_code == 400


def test_cancelling_reports_the_service_s_refusal(app, monkeypatch):
    from blueprints.subscription.services import transfers

    monkeypatch.setattr(
        transfers, "cancel_transfer",
        lambda *_a, **_k: (False, "That handover is already being processed."),
    )

    response = _post(app, "/api/me/subscriptions/transfer/cancel", {"transfer": "t1"})

    assert response.status_code == 422
    assert "already being processed" in response.get_json()["error"]


def test_the_inbox_is_scoped_to_the_token_not_the_request(app, monkeypatch):
    """The one recipient-scoped read in this file. Every other portal query filters on
    ``payer_user_id``; this one deliberately returns companies the caller does NOT pay
    for, so the scoping has to come from the token and nowhere else."""
    from blueprints.subscription.services import transfers

    seen = {}
    monkeypatch.setattr(
        transfers, "incoming_transfers_payload",
        lambda uid: seen.setdefault("uid", uid) and [] or [{"id": "t1"}],
    )

    response = app.test_client().get(
        "/api/me/subscriptions/transfers?user_id=someone-else",
        headers={"Authorization": f"Bearer {_token(app, user_id='u2')}"},
    )

    assert response.status_code == 200
    assert seen["uid"] == "u2", "the query string must not be able to redirect this"


def test_the_inbox_needs_a_bearer(app):
    response = app.test_client().get("/api/me/subscriptions/transfers")
    assert response.status_code == 401


def test_the_handover_routes_answer_preflight_without_a_token(app):
    for path in (
        "/api/me/subscriptions/transfer",
        "/api/me/subscriptions/transfer/respond",
        "/api/me/subscriptions/transfer/cancel",
        "/api/me/subscriptions/transfers",
    ):
        response = app.test_client().options(path)
        assert response.status_code == 204, path
        assert "Access-Control-Allow-Origin" in response.headers, path


def test_sorting_by_next_billing_mixes_dated_and_undated_rows(app):
    """A row with no next date must sort beside rows that have one.

    This is the crash the SQLite-backed suite cannot otherwise see. The dates behind
    ``_next_date`` come from ``trial_end`` / ``paid_through`` / ``app_access_until``,
    all declared ``DateTime(timezone=True)`` — so Postgres hands them back AWARE while
    SQLite hands them back naive. The undated rows are parked on a ``_NO_DATE``
    sentinel, and while that sentinel was ``datetime.max`` (naive) the comparison blew
    up with "can't compare offset-naive and offset-aware datetimes" the moment one
    company had nothing scheduled and another did — a 500 on
    ``GET /api/me/subscriptions?sort=next_billing`` in production only.

    Aware datetimes are used here deliberately: they are what the real query returns.
    """
    from blueprints.subscription.services import portal

    dated = {"_next_date": datetime(2026, 9, 1, tzinfo=timezone.utc)}
    undated = {"_next_date": None}
    rows = [undated, dated]

    rows.sort(key=portal._sort_key("next_billing"))

    assert rows == [dated, undated], "undated rows sort last, not first"
