"""The "Your subscription" panel: what the settings page shows about the money.

Moved out of ``entity.services.modules``. What a company is paying, when the next invoice
lands, what a cancellation still owes and which notice belongs at the top of the panel are
all subscription questions; they were in the entity blueprint only because the module
cards they are built from were.

Takes the cards and summary it renders from as ARGUMENTS rather than fetching them, which
is why this module needs almost nothing from the entity side: the only thing it reads back
is ``BUNDLE_DISPLAY_NAME``, through the module object at call time like every other
constant that stayed behind. See ``notices.py`` for why that indirection is load-bearing
rather than stylistic.

Money and dates are formatted through ``services.money`` and ``services.display`` -- the
five helpers this code used to call in ``modules`` were retired into those two, which is
what left this cut clean enough to make.
"""
from __future__ import annotations

from decimal import Decimal

from blueprints.entity.services import modules as entity_modules
from blueprints.subscription.services import money


def _empty_panel_next_invoice(cards: list[dict], fmt) -> dict | None:
    """The next-invoice line for a panel with nothing enabled.

    Nothing renews and no trial converts, so the only thing that can still be charged is
    a cancel-extension already recorded and not yet collected. Cancelling the LAST module
    is precisely how an entity reaches this panel, and it is the case that most often
    owes one — reporting "nothing will be billed" over the top of a pending charge would
    be the panel's worst possible lie.

    The date is the payer's cycle end, which a winding-down module still carries (it
    reports ``subscription_status`` "active" until its access runs out).
    """
    extensions = sum((c.get("extension_amount") or Decimal(0) for c in cards), Decimal(0))
    if extensions <= 0:
        return None
    on = next((c.get("period_end_long") for c in cards if c.get("period_end_long")), None)
    return {
        "date": on,
        "amount": fmt(extensions),
        "overdue": False,
        "includes_extension": True,
    }


def _winding_notices(cards: list[dict], bundle_codes, bundle_name: str) -> list[dict]:
    """The "X cancelled — active until DATE" lines, one per cancellation the customer made.

    Grouped by what was CANCELLED, not by module: cancelling a two-module bundle is one
    decision and reads as one sentence naming the plan, rather than the same date printed
    twice under two module names.

    ``past_due`` is excluded for the reason it is excluded everywhere else here: it
    carries the same winding-down flag but is in arrears, not cancelled, and telling a
    customer their module is "cancelled" while dunning still retries the charge would be
    wrong in the direction that loses the account.
    """
    winding = [
        c
        for c in cards
        if c.get("pending_cancel")
        and c.get("access_end_long")
        and c.get("subscription_status") != "past_due"
    ]
    if not winding:
        return []

    # A cancelled TRIAL is a different sentence from a cancelled subscription: nothing was
    # bought, nothing is being ended early, and the free days run out on the date they
    # were always going to. Calling that "cancelled" describes a purchase the customer
    # never made. Mixed groups read as the paid case, which is the one with money in it.
    def kind(cards_):
        return "trial" if all(c.get("trial_cancelled") for c in cards_) else "paid"

    codes = sorted((c["code"] or "").upper() for c in winding)
    wanted = sorted((code or "").upper() for code in (bundle_codes or []))
    if wanted and len(winding) > 1 and codes == wanted:
        return [
            {
                "label": bundle_name,
                "date": winding[0]["access_end_long"],
                "kind": kind(winding),
            }
        ]
    return [
        {"label": c["name"], "date": c["access_end_long"], "kind": kind([c])}
        for c in winding
    ]


def _extension_charges(cards: list[dict], fmt, bundle_codes=None, bundle_name="") -> list[dict]:
    """One upcoming-charge row per CANCELLATION — not per module.

    A cancellation extends access to the later of the paid period and 30 days, and bills
    the days BEYOND what was paid for on the payer's next invoice
    (renewals._pending_extension_lines). That is a different charge from a renewal and a
    different charge from a trial conversion: it is one-off, it belongs to a module that
    is going away, and it is the only line here the customer did not choose to keep
    paying for.

    Folding it into the renewal's figure made both unreadable — a "Renewal HKD 400" that
    is really 280 of subscription and 120 of cancellation, with a footnote to explain the
    arithmetic. Worse, when the cancelled module was the entity's LAST paid one there was
    no renewal row to fold it into, and the charge disappeared from a list titled
    "upcoming charges" while remaining perfectly real.

    Cancelling a bundle is ONE decision and the two modules share the bundle price for
    those days, split unevenly between their rows (checkout._leaving_marginal), so it is
    one line naming the plan and carrying the whole figure — two uneven rows the customer
    cannot reconcile against the dialog they confirmed, or against the invoice, is the
    same mistake the renewal line used to make by folding the extension in.

    The date is the module's own period end — the extension rides the invoice raised for
    the cycle it is already inside.
    """
    charged = [c for c in cards if (c.get("extension_amount") or Decimal(0)) > 0]
    if not charged:
        return []

    total = sum((c["extension_amount"] for c in charged), Decimal(0))
    note = "Extra days after your paid period — charged once, not monthly."
    codes = sorted((c["code"] or "").upper() for c in charged)
    wanted = sorted((code or "").upper() for code in (bundle_codes or []))
    if wanted and len(charged) > 1 and codes == wanted and bundle_name:
        return [
            {
                "at": charged[0].get("period_end"),
                "date": charged[0].get("period_end_long"),
                "label": f"{bundle_name} cancellation",
                "amount": fmt(total),
                "overdue": False,
                "note": note,
            }
        ]
    return [
        {
            "at": c.get("period_end"),
            "date": c.get("period_end_long"),
            "label": f"{c['name']} cancellation",
            "amount": fmt(c["extension_amount"]),
            "overdue": False,
            "note": note,
        }
        for c in charged
    ]

def build_subscription_panel(cards: list[dict], summary: dict | None, anchor_display: str | None) -> dict | None:
    """The "Your subscription" panel model, from the already-built cards + summary.

    Pure — it re-uses ``get_module_cards`` / ``get_subscription_summary`` output rather
    than re-querying, so the panel and the cards can never disagree about what's enabled.

    Unlike ``get_subscription_summary`` (which only counts modules being billed forward,
    and so is empty during a trial), this reflects what the enabled modules cost whether
    they're trialing or paid — the trial panel has to preview the price the trial will
    convert to. The billing anchor decides the mode: no anchor yet ⇒ still on trial
    ("Subscribe to Minty", "first charge … on <trial end>"); anchor set ⇒ paid
    ("Manage subscription", "Billed …/mo · next payment <date>"). ``anchor_display`` is
    only ever read as that switch — the anchor is a past date and is never shown; the
    footer names ``next_invoice_on``, the date the cycle actually bills next.

    ALWAYS returns a panel. With nothing enabled it returns an ``is_empty`` one that
    still names every module and prices the total at zero, rather than None — the panel
    used to disappear entirely, so the page silently lost a column exactly when the
    answer mattered most (right after cancelling the last module, the customer was left
    with no statement of what they are and aren't being billed for). "Nothing" is a
    state worth rendering, not an absence.
    """
    summary = summary or {}
    symbol = summary.get("currency") or ""
    currency_code = summary.get("currency_code")
    if not symbol or not currency_code:
        for card in cards:
            if card.get("currency_code"):
                symbol = symbol or money.symbol(card["currency_code"])
                currency_code = currency_code or card["currency_code"]
                break

    # Resolved once for the whole panel: every figure below is in the same currency, so
    # re-deriving it per line is a lookup for nothing and a chance for two to disagree.
    places = money.decimal_places(currency_code)

    def fmt(amount) -> str:
        return money.format_trimmed(symbol, amount, places)

    # One name for the bundle everywhere it is spoken about: the priced line, its note,
    # the cancellation notices below, and the decision modal.
    bundle_name = summary.get("bundle_name") or entity_modules.BUNDLE_DISPLAY_NAME

    # "Enabled" = will be on the NEXT invoice: a running trial or a live paid line, but
    # NOT one that's winding down. A cancelled module keeps access until its period ends
    # yet is billed no further, so it must drop out of the future-invoice total the moment
    # it's cancelled — exactly as get_subscription_summary excludes it via is_billing_forward.
    #
    # PAST_DUE is the exception, and it has to be spelled out. The card sets
    # ``pending_cancel`` for it too, because a failed renewal and a scheduled cancellation
    # share one "winding down" flag that drives the Renew button. Billing is a different
    # question: a past-due subscription has NOT ended and the money IS still owed, which
    # is precisely what ``access.is_billing_forward`` says. Reading pending_cancel alone
    # dropped it, and the panel then said "No modules enabled — nothing will be billed"
    # to a customer in arrears, at the moment they owe most.
    def billed_forward(card) -> bool:
        status = card.get("subscription_status")
        if status == "past_due":
            return True
        return status in ("trialing", "active") and not card.get("pending_cancel")

    enabled = [c for c in cards if billed_forward(c)]
    if not enabled:
        # Nothing billed forward — no live module, or every one of them winding down.
        # Same shape as a live panel so the template needs no second layout: every
        # module named and marked unbilled, and a real formatted zero rather than a
        # blank, which would read as "we couldn't work it out" instead of "nothing".
        owed = _empty_panel_next_invoice(cards, fmt)
        return {
            "state": "empty",
            "is_empty": True,
            "currency": symbol,
            "lines": [
                {
                    "kind": "module",
                    "label": card["name"],
                    "amount": None,
                    "billed": False,
                }
                for card in cards
            ],
            "is_bundle": False,
            "note": None,
            "total": fmt(Decimal(0)),
            # Nothing enabled means nothing renews and no trial converts. A pending
            # cancel-extension can still be owed here, so it is surfaced rather than
            # silently dropped — that is a real charge on a panel that otherwise reads
            # "nothing will be billed".
            "next_invoice": owed,
            "trial_conversions": [],
            # Nothing renews and no trial converts, so the list is the owed extensions or
            # nothing at all — named per module, exactly as on a live panel. Calling it
            # "Renewal" here was wrong twice: nothing is renewing, and the one thing that
            # IS charged is the cancellation that emptied the panel.
            "upcoming_charges": _extension_charges(
                cards, fmt, summary.get("bundle_codes"), bundle_name
            ),
            # A module winding down is excluded from the total — it bills no further —
            # but the customer still HAS it until its access runs out. Saying only
            # "nothing will be billed" over the top of that reads as "you have nothing",
            # which is wrong on the exact screen they opened to check.
            "winding_down": [
                {"label": c["name"], "date": c.get("access_end_long")}
                for c in cards
                if c.get("pending_cancel")
                and c.get("access_end_long")
                # past_due carries pending_cancel too (one "winding down" flag serves
                # both), but it is NOT billing no further — it is in arrears and will be
                # retried. Listing it here printed "Not billed again" directly above the
                # overdue charge for the same module.
                and c.get("subscription_status") != "past_due"
            ],
            # What the panel actually renders for those: one sentence per cancellation
            # rather than one row per module — see _winding_notices.
            "winding_notices": _winding_notices(
                cards, summary.get("bundle_codes"), bundle_name
            ),
            "footer": "No modules enabled — nothing will be billed.",
            # The panel button is the ONLY way into the decision modal, so an empty panel
            # still needs one whenever there is something to decide:
            #   * a module winding down — re-ticking it is the undo, and withholding the
            #     button would leave a cancellation with no way back;
            #   * a module that could be taken up — an entity whose trials are spent has
            #     nothing enabled and nothing cancelled, and this is its way back in. The
            #     modal lists untried modules too; ticking one starts its free trial
            #     rather than buying it, so this button is right either way.
            # Only a company with no modules at all in the catalog gets no action.
            "primary_action": (
                "manage"
                if any(c.get("pending_cancel") for c in cards)
                else ("subscribe_stripe" if cards else None)
            ),
            "subscribe_codes": [],
        }

    # The anchor is pinned at the first charge, so its presence is exactly "has this
    # entity started paying" — the one bit that separates the trial panel from the paid.
    state = "active" if anchor_display else "trialing"

    # ...which is the wrong question for the BUTTON, twice over. The anchor lives on the
    # payer's ACCOUNT, so a payer already charged for another company gives this one an
    # anchor on day one; and a trial that already has a card and this company's consent
    # needs nothing from the customer — it converts on its own.
    #
    # So "Subscribe to Minty" is offered for exactly one condition: a running trial that
    # will NOT convert as things stand, because there is no card or this company was
    # never authorised for the saved one. That is what needs_card means (see
    # get_module_cards); needs_consent_only says which of the two it is. Everything else
    # — trials that will convert, and paying entities — is "Manage subscription".
    needs_billing_setup = any(c.get("needs_card") for c in cards)

    enabled_codes = sorted((c["code"] or "").upper() for c in enabled)
    bundle_codes = sorted((code or "").upper() for code in (summary.get("bundle_codes") or []))
    bundle_amount = summary.get("bundle_amount") or Decimal(0)
    # The bundle IS the discount: when the enabled set is exactly the bundle's, it bills
    # at the single bundle price. Mirrors get_subscription_summary / checkout.
    is_bundle = bool(bundle_codes and len(enabled) > 1 and enabled_codes == bundle_codes)

    subtotal = sum((c["amount"] for c in enabled), Decimal(0))
    total = bundle_amount if is_bundle else subtotal
    saving = (subtotal - total) if is_bundle else Decimal(0)

    lines: list[dict] = []
    if is_bundle:
        lines.append(
            {
                "kind": "bundle",
                "label": bundle_name,
                "sublabel": " & ".join(c["name"] for c in enabled),
                "original": fmt(subtotal),
                "amount": fmt(total),
            }
        )
    else:
        # One line per canonical module — an unenabled one reads "Not billed" rather
        # than vanishing, so the panel always shows the full picture.
        for card in cards:
            on = billed_forward(card)
            lines.append(
                {
                    "kind": "module",
                    "label": card["name"],
                    "amount": (fmt(card["amount"]) + "/mo") if on else None,
                    "billed": on,
                }
            )

    # The highlighted context line — what the price actually is, in plain words.
    #
    # The bundle line reads the same whether trialing or paid. It used to append "vs
    # HK$280 each" once billing had started, which quoted a per-module price for a plan
    # nobody is billed per module on — and the saving beside it already carries the
    # comparison.
    if is_bundle:
        note = f"{bundle_name} price — save {fmt(saving)}"
    else:
        module = enabled[0]
        price = fmt(module["amount"])
        if state == "trialing":
            after = module.get("period_end_short")
            note = (
                f"{module['name']} free trial — {price}/mo after {after}"
                if after
                else f"{module['name']} free trial — {price}/mo"
            )
        else:
            note = f"{module['name']} subscription — {price}/mo."

    total_fmt = fmt(total)

    # --- What actually lands on the next invoice -------------------------------
    #
    # NOT the same set as ``total``. ``total`` is what the enabled modules COST per
    # month, trials included, because the trial panel has to preview the price it will
    # convert to. The invoice bills what ``access.is_billing_forward`` allows on the DAY
    # IT IS RAISED — so a trial still running then is in the total and not on the bill.
    # Quoting one figure for both would misstate whichever the customer was asking about.
    paid = [
        c for c in enabled if c.get("subscription_status") in ("active", "past_due")
    ]
    # The date the payer's cycle next bills: paid_through, carried on any active or
    # past_due card. Absent while the entity has only trials — there is no cycle yet.
    next_invoice_at = next(
        (c.get("period_end") for c in paid if c.get("period_end")), None
    )
    next_invoice_on = next(
        (c.get("period_end_long") for c in paid if c.get("period_end_long")), None
    )

    # A trial that CONVERTS BEFORE the invoice date is active by the time it is raised,
    # so the renewal bills it too — ``billable_codes_by_entity`` reads phases when the
    # run fires, not when this page was rendered. Leaving them out quoted one module's
    # price for an invoice that will charge the bundle: a trial ending 20 Aug is paid
    # for by the 28 Aug invoice, and the panel said 280 against a real 400.
    converts_before_invoice = [
        c
        for c in enabled
        if c.get("subscription_status") == "trialing"
        and not c.get("needs_card")
        and c.get("period_end")
        and next_invoice_at is not None
        and c["period_end"] <= next_invoice_at
    ]
    on_invoice = paid + converts_before_invoice
    invoiced_codes = sorted((c["code"] or "").upper() for c in on_invoice)
    invoiced_is_bundle = bool(
        bundle_codes and len(on_invoice) > 1 and invoiced_codes == bundle_codes
    )
    recurring = (
        bundle_amount
        if invoiced_is_bundle
        else sum((c["amount"] for c in on_invoice), Decimal(0))
    )
    # Cancel-extensions ride the same invoice (renewals._pending_extension_lines), and
    # they sit on modules that are winding down — which is exactly the set ``enabled``
    # excludes. Read them off every card, or the figure understates what is charged.
    extensions = sum((c.get("extension_amount") or Decimal(0) for c in cards), Decimal(0))
    invoice_amount = recurring + extensions

    next_invoice = None
    if next_invoice_on and invoice_amount > 0:
        next_invoice = {
            "date": next_invoice_on,
            "amount": fmt(invoice_amount),
            # past_due means the date has already passed and the money is owed now.
            "overdue": any(
                c.get("subscription_status") == "past_due" for c in paid
            ),
            "includes_extension": extensions > 0,
        }

    # Trial conversions are listed SEPARATELY, one per trialing module, rather than
    # folded into the next-invoice line. Two modules trialled on different days convert
    # on different days, and an entity can hold a trial beside a paid module — so there
    # are genuinely several dates, and collapsing them to one drops real information.
    #
    # The amount is quoted either way — it is what the module costs when the trial ends,
    # and that is the number the customer is deciding against. ``will_convert`` carries
    # whether it is actually going to be taken (no card, or no consent for this entity,
    # means it expires instead), so the row can say "converts" versus "trial ends" and
    # qualify the figure rather than withhold it. Hiding the price left the row reading
    # "Not charged" with nothing to weigh the decision against.
    trial_conversions = [
        {
            "label": c["name"],
            "date": c.get("period_end_long"),
            # WHAT IS CHARGED THAT DAY — not the monthly rate. For the conversion that
            # starts the cycle those are the same number; for one landing mid-period they
            # are not, and the monthly rate is the wrong one. A trial converting into a
            # running cycle pays only the days left in it (the 65.83 shape), so quoting
            # "280/mo" against that date named money that is not taken.
            #
            # A trial that will NOT convert keeps the monthly price: nothing is charged,
            # so there is no day's figure, and the price is still what the decision to
            # add a card is being weighed against.
            "amount": fmt(
                c["conversion_charge"]
                if not c.get("needs_card")
                else c["amount"]
            ),
            "will_convert": not c.get("needs_card"),
        }
        for c in enabled
        if c.get("subscription_status") == "trialing" and c.get("period_end_long")
    ]

    # --- One date-ordered list of what will be charged, and when ----------------
    #
    # A trial converting mid-cycle and the renewal that follows are TWO charges on two
    # dates, and both are real: the conversion collects the days between it and the cycle
    # end, then the renewal bills the full month. Presenting them as separate blocks left
    # the reader working out the order and whether one included the other; a single
    # chronological list answers "what leaves my card, and when" in one pass.
    #
    # Non-converting trials are absent by construction — nothing is charged for a trial
    # that expires, so it is not an upcoming charge. It still appears in the footer,
    # which is where "add a card or lose this" belongs.
    #
    # GROUPED BY DAY, and a day whose conversions are exactly the bundle is ONE row naming
    # the plan. Two modules converting together are billed as the bundle, not as two
    # modules: the forecasts are computed sequentially, so the first carries a full period
    # (280) and the second the net of the change into the bundle (120), and only their SUM
    # (400) is a number the customer will recognise. Printed as two rows they had to add
    # up a 280 and a 120 that appear nowhere on the invoice to check the 400 that does.
    # Same rule the cancellation rows already follow (_extension_charges).
    converting_by_day: dict = {}
    for card in enabled:
        if (
            card.get("subscription_status") == "trialing"
            and not card.get("needs_card")
            and card.get("period_end")
        ):
            converting_by_day.setdefault(card["period_end"], []).append(card)

    upcoming_charges = []
    for at, same_day_cards in converting_by_day.items():
        day_codes = sorted((c["code"] or "").upper() for c in same_day_cards)
        day_amount = sum(
            (c.get("conversion_charge") or Decimal(0) for c in same_day_cards), Decimal(0)
        )
        if bundle_codes and len(same_day_cards) > 1 and day_codes == bundle_codes:
            rows = [(bundle_name, day_amount)]
        else:
            rows = [
                (c["name"], c.get("conversion_charge") or Decimal(0))
                for c in same_day_cards
            ]
        upcoming_charges.extend(
            {
                "at": at,
                "date": same_day_cards[0].get("period_end_long"),
                "label": f"{label} converts",
                "amount": fmt(amount),
                "overdue": False,
                "note": None,
            }
            for label, amount in rows
        )
    # The renewal quotes the RECURRING figure only. Any cancel-extension riding the same
    # invoice is listed beside it as its own row, so each line is one thing the customer
    # can recognise; ``next_invoice`` still carries the combined total, because that is
    # what the invoice will say.
    if next_invoice_on and next_invoice_at and recurring > 0:
        upcoming_charges.append(
            {
                "at": next_invoice_at,
                "date": next_invoice_on,
                "label": "Renewal",
                "amount": fmt(recurring),
                "overdue": bool(next_invoice and next_invoice["overdue"]),
                "note": None,
            }
        )
    # Cancellations are charged whether or not anything renews — including when the
    # cancelled module was the last paid one, which is precisely when the panel used to
    # drop the charge entirely.
    upcoming_charges.extend(
        _extension_charges(cards, fmt, summary.get("bundle_codes"), bundle_name)
    )
    # Sorted on the raw datetime — the formatted date sorts alphabetically, which would
    # put 11 Sep before 28 Aug. A row with no date at all (an extension on a module whose
    # period end never made it onto the card) goes last rather than blowing up the sort.
    _dated = [e for e in upcoming_charges if e["at"] is not None]
    _dated.sort(key=lambda e: e["at"])
    upcoming_charges = _dated + [e for e in upcoming_charges if e["at"] is None]

    if state == "trialing":
        # Every trial here is pre-anchor, so "will any of them actually charge" decides
        # whether the footer may name a figure at all.
        converting = [
            c
            for c in enabled
            if c.get("subscription_status") == "trialing"
            and c.get("period_end_long")
            and not c.get("needs_card")
        ]
        if not trial_conversions:
            footer = f"You're on a free trial — first charge {total_fmt} when the trial ends."
        elif not converting:
            # Still names the price: "nothing will be charged" alone told them the
            # outcome but not the stake, on the one screen where adding a card is the
            # decision in front of them.
            footer = (
                f"Your free trial ends {trial_conversions[0]['date']} — "
                f"{total_fmt}/mo after that, once a card is added."
            )
        else:
            # The FIRST charge is the earliest conversion, and it bills only the modules
            # converting on that DAY — not the combined total. Two trials started a
            # fortnight apart convert a fortnight apart, so quoting the bundle price
            # against the earlier date names money that is not taken until the later one.
            # Sorted on the raw datetime; the formatted string sorts alphabetically.
            #
            # Summed from the per-module forecasts rather than re-priced here, so the
            # footer and the rows above it cannot disagree about the same day's charge.
            first_at = min(
                c["period_end"] for c in converting if c.get("period_end")
            ) if any(c.get("period_end") for c in converting) else None
            same_day = [
                c
                for c in converting
                if first_at is None or c.get("period_end") == first_at
            ] or converting
            first_charge_on = same_day[0]["period_end_long"]
            first_amount = sum(
                (c.get("conversion_charge") or Decimal(0) for c in same_day), Decimal(0)
            )
            footer = (
                f"You're on a free trial — first charge {fmt(first_amount)} "
                f"on {first_charge_on}."
            )
    else:
        # NO FOOTER once billing has started — both halves of the old sentence are now
        # said better elsewhere on the page. "Billed HK$400/mo" repeated the Total row
        # directly above it, and "· next payment 28 Aug 2026" repeated the date card at
        # the top of the page, which is where a customer looks for it. The template skips
        # the paragraph entirely rather than printing an empty one.
        #
        # The trial and empty states keep theirs: those say something no other element
        # on the panel does (when the first charge lands, or that nothing is billed).
        footer = ""

    return {
        "state": state,
        "is_empty": False,
        "currency": symbol,
        "lines": lines,
        "is_bundle": is_bundle,
        "note": note,
        "total": total_fmt,
        # {date, amount, overdue, includes_extension} or None when the cycle has
        # nothing to bill — see the block above for why this is not ``total``.
        "next_invoice": next_invoice,
        # One entry per trialing module: {label, date, amount, will_convert}. Kept as the
        # underlying fact — the footer composes from it, including the trials that will
        # NOT convert and so never reach upcoming_charges.
        "trial_conversions": trial_conversions,
        # What the panel actually renders: every charge, in the order it happens.
        "upcoming_charges": upcoming_charges,
        # Modules that still grant access but bill no further — see the empty panel.
        "winding_down": [
            {"label": c["name"], "date": c.get("access_end_long")}
            for c in cards
            if c.get("pending_cancel")
            and c.get("access_end_long")
            # past_due carries pending_cancel too (one "winding down" flag serves both),
            # but it is NOT billing no further — it is in arrears and will be retried.
            # Listing it here printed "Not billed again" directly above the overdue
            # charge for the very same module.
            and c.get("subscription_status") != "past_due"
        ],
        "winding_notices": _winding_notices(
            cards, summary.get("bundle_codes"), bundle_name
        ),
        "footer": footer,
        # Both captions open the same decision modal — this only says which question the
        # entity is being asked. "Subscribe" when billing still has to be set up for a
        # trial to convert; "Manage" once there is nothing missing.
        "primary_action": "subscribe_stripe" if needs_billing_setup else "manage",
        "subscribe_codes": [c["code"] for c in enabled],
    }
