"""The card on the dialog that takes the money.

"Subscribe to Super Minty" is the one screen in the flow where the charge happens as the
dialog closes, and it used to be the only card surface with no say in the matter: a
read-only line reading "visa ending 5556" — a fourth way of naming a card, on the last
moment the choice is free to make.

Two things are pinned here, and only the second is cosmetic:

* NOMINATION BEFORE CHARGE. The purchase routes accept the card the dialog named and put
  the company on it before anything bills. The other order charges whatever the company
  was already on, which — on a dialog where the payer is looking at a different card — is
  a charge against a card they were not shown.
* One vocabulary. The preview's card string is built from the same helper the picker rows
  use, so the two cannot drift into "Visa •••• 5556" here and "visa ending 5556" there.
"""
from __future__ import annotations

import pytest


# --- the string -------------------------------------------------------------


@pytest.mark.parametrize(
    "brand, last4, expected",
    [
        ("visa", "5556", "Visa •••• 5556"),
        ("mastercard", "7068", "Mastercard •••• 7068"),
        ("amex", "0005", "Amex •••• 0005"),
        # A wallet Stripe hands back with no card object still has to be nameable.
        ("visa", None, "Visa"),
        (None, "4242", "Card •••• 4242"),
    ],
)
def test_the_preview_names_a_card_the_way_every_row_does(app, monkeypatch, brand, last4, expected):
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(checkout.store, "card_for_entity", lambda eid: "pm_1")
    monkeypatch.setattr(
        checkout, "payment_method_display", lambda pm: {"brand": brand, "last4": last4}
    )

    assert checkout._preview_card_display("u1", "e1") == expected


def test_the_preview_never_says_ending(app, monkeypatch):
    """The old wording, gone for good — it is the one that made this a fourth vocabulary."""
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(checkout.store, "card_for_entity", lambda eid: "pm_1")
    monkeypatch.setattr(
        checkout, "payment_method_display", lambda pm: {"brand": "visa", "last4": "5556"}
    )

    assert "ending" not in checkout._preview_card_display("u1", "e1")


def test_a_stripe_hiccup_does_not_stop_the_purchase(app, monkeypatch):
    """This only decorates a dialog. A card that cannot be read is a missing line, not a
    customer who cannot subscribe."""
    from blueprints.subscription.services import checkout

    def _boom(_eid):
        raise RuntimeError("stripe is down")

    monkeypatch.setattr(checkout.store, "card_for_entity", _boom)

    assert checkout._preview_card_display("u1", "e1") is None


# --- nomination before charge ------------------------------------------------


def test_the_purchase_routes_nominate_before_they_charge():
    """Order, read off the source: the nomination call must precede the checkout call in
    both routes. A test that only asserted "it nominates" would pass on code that billed
    the old card first and moved the company after."""
    routes = open("blueprints/entity/routes/settings.py", encoding="utf-8").read()

    for start, end, charge in [
        ("def entity_settings_module_checkout(", "def entity_settings_module_checkout_complete(", "start_modules_checkout("),
        ("def entity_settings_module_confirm_billing(", "def entity_settings_module_checkout_complete(", "confirm_modules_checkout("),
    ]:
        body = routes[routes.index(start) : routes.index(end, routes.index(start))]
        assert "_nominate_if_given" in body, start
        assert body.index("_nominate_if_given") < body.index(charge), start


def test_nominating_goes_through_the_ownership_proof():
    """``set_for_entity`` is what proves the method is the caller's AND the caller is the
    company's payer. Nominating any other way would let an admin who pays nothing move
    someone else's billing onto a card of their choosing."""
    routes = open("blueprints/entity/routes/settings.py", encoding="utf-8").read()
    body = routes[
        routes.index("def _nominate_if_given(") : routes.index("def entity_settings_module_checkout(")
    ]

    assert "payment_methods.set_for_entity" in body
    assert "PaymentMethodError" in body, "and its refusal reaches the client verbatim"


def test_an_absent_card_leaves_the_company_where_it_is():
    """The key is OPTIONAL. Every caller sent no card before the dialog grew a picker, and
    those calls must still mean "bill whatever this company is already on"."""
    routes = open("blueprints/entity/routes/settings.py", encoding="utf-8").read()
    body = routes[
        routes.index("def _nominate_if_given(") : routes.index("def entity_settings_module_checkout(")
    ]

    assert "if not pm_id:" in body
    # Against the CALL, not the docstring's mention of it a few lines above.
    assert body.index("if not pm_id:") < body.index("payment_methods.set_for_entity(")


# --- the dialog ---------------------------------------------------------------


def _scripts(app) -> str:
    from flask import render_template

    class _Org:
        id = "org-1"
        name = "Acme"

    with app.test_request_context():
        return render_template(
            "entity/partials/module_subscription_scripts.html",
            org=_Org(), module_cards=[], subscription_summary={}, subscription_panel={},
            can_manage_modules=True, subscription_payer=None, dev_tools=False,
        )


def test_the_purchase_dialog_offers_the_card_list(app):
    scripts = _scripts(app)

    body = scripts[scripts.index("async function confirmSubscribe(") :]
    body = body[: body.index("async function doCheckout(")]
    assert "await loadWallet()" in body
    assert "cards: cards.length ? cards : null" in body
    # The read-only line survives ONLY as the fallback for a wallet that would not load.
    assert "card: cards.length ? null : (p.needs_consent ? p.card : null)" in body


def test_the_chosen_card_reaches_both_purchase_posts(app):
    scripts = _scripts(app)

    body = scripts[scripts.index("async function doCheckout(") :]
    body = body[: body.index("window.confirmBillingForEntity")]
    assert "ok && ok.card ? { payment_method: ok.card } : {}" in body
    # Both the charge and the confirm-billing follow-up carry it; the second is the one
    # that runs when the server answers needs_confirmation.
    assert body.count("Object.assign({ codes: codes }, card)") == 2


# --- the decision modal's Save ------------------------------------------------


def test_saving_an_unchanged_selection_does_not_reload_the_page(app):
    """Reopening "Choose your modules" and pressing Save without touching a box.

    Every list is empty, so there is nothing to cancel, resume, start or buy — and the
    function used to fall all the way through to ``window.location.reload()``. A full page
    load to redraw the state already on screen, which on a slow connection is a long blank
    pause after a button that looked like it did nothing.

    It is also why the button never showed "Please wait…": with no work there is not a
    single ``await`` between setting the label and reloading, so the browser never gets a
    frame to paint it in. The guard fixes both — the label now only appears when there is
    something to wait for.
    """
    scripts = _scripts(app)

    body = scripts[scripts.index("async function commitSubDecision(") :]
    body = body[: body.index("window.location.reload();")]

    # Asserted in two halves so the test does not depend on where the condition wraps.
    head = "if (!remove.length && !renew.length && !keptTrials.length"
    tail = "&& !startTrials.length && !add.length) {"
    assert head in body and tail in body, "the no-op guard is there"
    assert body.index(head) < body.index("btn.textContent = 'Please wait"), (
        "and it returns BEFORE the label is set, so the label means work is happening"
    )


def test_the_no_op_guard_names_every_kind_of_work(app):
    """A branch left out of the guard is a real change that silently does nothing — the
    worst failure this file can have, because the modal would close as if it had saved."""
    scripts = _scripts(app)

    body = scripts[scripts.index("async function commitSubDecision(") :]
    body = body[: body.index("window.location.reload();")]

    # Each of these gates a block of real work further down the function.
    for kind in ("remove", "renew", "keptTrials", "startTrials", "add"):
        assert "!" + kind + ".length" in body, kind
        assert "if (" + kind + ".length)" in body or "for (const item of " + kind + ")" in body, kind


# --- the button while the Subscribe dialog is being opened --------------------


def test_the_button_goes_busy_before_the_first_await(app):
    """"Save changes" on a module the entity has already used its trial on.

    ``confirmSubscribe`` reads the payer's wallet AND prices the purchase before its
    dialog appears — two network round-trips — and the button used to sit through both of
    them enabled and still reading "Save changes". Long enough to look broken on a slow
    connection, and long enough to press twice and start the flow again.

    Seen on "Scenario 7 - Both Trial Expired", where both modules are `expired`: expired
    is not trial-eligible, so ticking them is a purchase and takes this branch.
    """
    scripts = _scripts(app)

    body = scripts[scripts.index("async function doCheckout(") :]
    body = body[: body.index("window.confirmBillingForEntity")]

    assert body.index("btn.textContent = 'Please wait") < body.index("await confirmSubscribe("),         "the label is set BEFORE the awaits that open the dialog, not after them"


def test_the_decision_modal_hands_the_button_over_still_busy(app):
    """The add branch used to call ``restore()`` first, which re-enabled the button and
    put "Save changes" back — creating the gap above. It now hands the button to
    doCheckout still disabled, with the label to put back passed alongside it."""
    scripts = _scripts(app)

    body = scripts[scripts.index("if (add.length) {") :]
    body = body[: body.index("window.location.reload();")]

    assert "restore();" not in body, "the button is not restored before the purchase runs"
    assert "doCheckout(add.map(function (i) { return i.code; }), btn, orig)" in body
    # The full-screen loader DOES go: a priced dialog must not open behind it.
    assert body.index("hideBlockingLoader();") < body.index("await doCheckout(")


def test_a_cancelled_purchase_puts_the_original_label_back(app):
    """Pressing "Not now" leaves the page up, so the button has to become usable again —
    and reading textContent for that would restore "Please wait…" onto a button that has
    finished waiting."""
    scripts = _scripts(app)

    body = scripts[scripts.index("async function doCheckout(") :]
    body = body[: body.index("showBlockingLoader(")]

    assert "restoreLabel !== undefined" in body, "the caller's label wins when given"
    assert "btn.disabled = false; btn.textContent = orig;" in body
