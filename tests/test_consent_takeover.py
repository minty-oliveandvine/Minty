"""What the settings page renders once a trial has lapsed.

Three states, and the requirement for each is about what is ABSENT as much as present:

* takeover — the module cards and the "Your subscription" panel must be GONE. Replacing
  the content is the requirement; drawing a restart box above an intact page would be
  the panel, not the takeover. The ordinary scripts must go with them, because that is
  what makes the screen genuinely non-dismissible — the decision modal and its handlers
  are not on the page to reach.
* panel — the restart box AND the whole ordinary page, because the live trial that put
  us in this mode still needs its own controls.
* co-admin — neither, in either mode. ``require_subscription_payer`` would refuse the
  write, so a form here would be one they could fill in and never submit.

Rendered through ``module_main_content.html``, the switch both parent templates include,
so the two cannot drift apart.
"""
from __future__ import annotations

import pytest


class _FakeOrg:
    id = "org-123"
    name = "Acme"


class _FakePayer:
    first_name = "Dana"
    last_name = "Reed"
    username = "dana@example.com"


_CARD = {
    "code": "PETTY_CASH", "name": "Petty Cash", "description": "d",
    "image": "img/cash_reg.webp", "learn_more": "", "price_formatted": "HK$280",
    "currency_code": "HKD", "price_amount": 280, "subscription_status": "trialing",
    "is_enabled": True, "can_cancel": False, "pending_cancel": False,
    "formatted_period_end": "19 Aug 2026", "conversion_charge": None,
    "extension_formatted": None, "extension_state": None, "app_trial": True,
    "app_trial_closing": False, "trial_end_long": "19 Aug 2026",
    "trial_cancelled": False, "trial_eligible": False,
    "period_end_short": "19 Aug", "period_end_long": "19 Aug 2026",
    "access_end_long": None, "needs_card": True, "needs_consent_only": False,
}

_PANEL = {
    "is_empty": False, "currency": "HK$", "lines": [], "note": None,
    "total": "HK$400", "winding_down": [], "upcoming_charges": [], "footer": "",
    "primary_action": "subscribe_stripe", "subscribe_codes": ["PETTY_CASH", "BILL"],
}


def _takeover(mode="takeover", *, can_act=True, single=True):
    lapsed = [{"code": "PETTY_CASH", "name": "Petty Cash",
               "lapsed_on": None, "lapsed_on_long": "19 Aug 2026"}]
    if not single:
        lapsed.append({"code": "BILL", "name": "Payment Request",
                       "lapsed_on": None, "lapsed_on_long": "2 Sep 2026"})
    return {
        "mode": mode,
        "can_act": can_act,
        "lapsed": lapsed,
        "payer_user_id": "u1",
        "has_card": False,
        "single": single,
        "names": [item["name"] for item in lapsed],
        "quote": {"charged_today_formatted": "HK$400",
                  "monthly_formatted": "HK$400", "card": "Visa •••• 4242"},
        "methods": {"has_account": True, "default_id": "pm_1", "total": 1,
                    "methods": [{"id": "pm_1", "label": "Visa •••• 4242",
                                 "brand": "Visa", "expiry": "04/2030"}]},
    }


def _two_cards():
    """A payer with more than one saved card — the case the list collapses for."""
    state = _takeover()
    state["methods"]["methods"].append(
        {"id": "pm_2", "label": "Mastercard •••• 4444", "brand": "Mastercard",
         "expiry": "04/2031"}
    )
    state["methods"]["total"] = 2
    return state


def _render(app, consent_takeover, **overrides):
    from flask import render_template

    ctx = dict(
        org=_FakeOrg(),
        module_cards=[dict(_CARD)],
        subscription_summary={"currency": "HK$", "bundle_amount": 400,
                              "bundle_codes": ["BILL", "PETTY_CASH"],
                              "bundle_name": "Super Minty"},
        subscription_panel=_PANEL,
        can_manage_modules=True,
        subscription_payer=None,
        dev_tools=False,
        consent_takeover=consent_takeover,
    )
    ctx.update(overrides)
    with app.test_request_context():
        return render_template("entity/partials/module_main_content.html", **ctx)


@pytest.mark.parametrize(
    "name",
    [
        "entity/partials/module_main_content.html",
        "entity/partials/module_restart_body.html",
        "entity/partials/module_restart_panel.html",
        "entity/partials/module_restart_scripts.html",
    ],
)
def test_restart_template_parses(app, name):
    app.jinja_env.get_template(name)


# --- takeover -----------------------------------------------------------------


def test_the_takeover_sits_on_top_of_the_ordinary_page(app):
    """It does NOT replace the page any more. A payer who wants to read what they had,
    or reach another control, can dismiss it and do so."""
    html = _render(app, _takeover())

    assert "restartScreen" in html, "the restart dialog renders"
    assert "subscription-panel" in html, "and the ordinary page is still underneath"
    assert "openSubscriptionDecision" in html, "including its scripts"


def test_the_takeover_is_a_dialog(app):
    html = _render(app, _takeover())

    assert 'id="restartModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-labelledby="restartTitle"' in html
    assert "bg-[rgba(15,23,27,0.45)]" in html, "the same dim as the dialogs inside it"


def test_the_takeover_can_be_dismissed(app):
    html = _render(app, _takeover())

    assert 'id="restartClose"' in html
    assert "closeRestartModal" in html


def _restart_card(html: str) -> str:
    """The restart dialog's own card, without the two dialogs that open from inside it.

    Scoped because the ORDINARY PAGE now renders behind this one, and it has its own
    long-standing decision modal with its own "Not now" — searching the whole document
    for a control would find that one and say nothing about this dialog at all.
    """
    return html[html.index('id="restartScreen"') : html.index('id="restartConfirm"')]


def test_dismissing_remembers_nothing(app):
    """THE point of the design. Closing hides it for this view; the next load renders it
    again. Anything that persisted the dismissal would turn "let me look at the page"
    into "I have dealt with this", which the payer has not."""
    html = _render(app, _takeover())
    script = html.split("closeRestartModal", 1)[1][:1200]

    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "document.cookie" not in script
    # And no server round-trip pretending to be one either.
    assert "fetch(" not in script


def test_dismissing_is_not_offered_as_a_deferral(app):
    """"Not now" and "Remind me later" both promise a memory this deliberately does not
    keep. It is a close button and says so."""
    card = _restart_card(_render(app, _takeover()))

    assert "Not now" not in card
    assert "Remind me later" not in card
    assert "Do it later" not in card
    assert 'aria-label="Close"' in card


def test_panel_mode_is_the_same_dialog(app):
    """Both modes are one dialog now. Panel mode used to be an in-flow banner, which put
    two different presentations of one decision on the same page."""
    html = _render(app, _takeover("panel"))

    assert 'id="restartModal"' in html
    assert 'id="restartClose"' in html, "and it dismisses, like the other mode"
    assert "subscription-panel" in html, "over an intact page"


def test_panel_mode_scopes_itself_to_what_lapsed(app):
    """A dialog about an expired module, in front of a page with a live trial on it,
    reads as a threat to both unless it says otherwise."""
    html = _render(app, _takeover("panel"))

    assert "Your other free trial is unaffected" in html


def test_takeover_mode_makes_no_such_claim(app):
    """Nothing is still running in that mode, so the sentence would be false."""
    card = _restart_card(_render(app, _takeover()))

    assert "unaffected" not in card


def test_escape_unwinds_one_layer_at_a_time(app):
    """Dialogs stack. Closing two on one press would dismiss the whole thing while the
    payer was only backing out of the confirmation."""
    html = _render(app, _takeover())

    block = html.split("event.key !== 'Escape'", 1)[1][:900]
    assert block.index("closeConfirm") < block.index("closeRestartModal"), "innermost first"
    assert "return;" in block, "and one per press"
    # The card dialog owns its own Escape, guarded on whether it is the one open, so it
    # is deliberately NOT arbitrated here.
    assert "closeCardModal" not in block


def test_the_takeover_says_what_lapsed_and_when(app):
    html = _render(app, _takeover())

    assert "Petty Cash" in html
    assert "19 Aug 2026" in html


def test_the_takeover_says_the_money_lands_today(app):
    """This screen charges, unlike every other consent surface in the app, so it has to
    say so before the button rather than after it."""
    html = _render(app, _takeover())

    assert "HK$400" in html
    assert "charged now" in html


def test_two_lapsed_modules_get_a_box_each(app):
    """Forcing the bundle would sell a module the customer may have deliberately let go."""
    html = _render(app, _takeover(single=False))

    assert html.count('class="restart-code') == 2
    assert 'value="PETTY_CASH"' in html
    assert 'value="BILL"' in html


def test_one_lapsed_module_is_a_fixed_line_not_a_choice(app):
    """A tick box that cannot be unticked is a worse control than a statement."""
    html = _render(app, _takeover(single=True))

    assert html.count('class="restart-code') == 1
    assert 'data-fixed="1"' in html


# --- panel --------------------------------------------------------------------


def test_the_company_is_named_on_its_own_line(app):
    """Entity names are free text and routinely long enough to be a sentence. Spliced
    into one, a name like "Scenario 5 - Free Trial But ends in 5 days" left the copy
    reading "...to get Scenario 5 - Free Trial But ends in 5 days back"."""
    html = _render(app, _takeover())

    assert "get it back" in html
    assert "get Acme back" not in html
    assert ">Acme</p>" in html


# --- the add-a-card dialog ----------------------------------------------------


def test_adding_a_card_opens_a_dialog(app):
    html = _render(app, _takeover())

    assert 'id="cardCaptureModal"' in html
    assert 'aria-labelledby="cardCaptureTitle"' in html
    # Starts closed — the saved-card list is the default path.
    assert "hidden items-center justify-center" in html


def test_the_confirmation_is_not_nested_in_the_restart_modal(app):
    """REGRESSION, and an invisible one in markup review.

    ``backdrop-filter`` — the blur on #restartModal — creates a containing block for
    ``position: fixed`` descendants. Nested inside it, the confirmation anchored to the
    restart dialog's own scrolled box rather than the viewport: scroll the card list
    down, open it, and it appeared half off-screen with its backdrop covering only part
    of the page. Same trap for a transform or a filter on any ancestor.
    """
    html = _render(app, _takeover())

    modal = html.index('id="restartModal"')
    screen = html.index('id="restartScreen"')
    confirm = html.index('id="restartConfirm"')

    assert screen > modal, "the screen IS inside the modal"
    assert confirm > screen, "the confirmation comes after it"
    # And past the modal wrapper's own closing tag, not still inside it.
    assert html.count("</div>", screen, confirm) > html.count("<div", screen, confirm)


def test_the_card_dialog_can_be_closed_three_ways(app):
    """Cancelling an optional detour returns the payer to the saved-card list; the
    abandoned SetupIntent expires without leaving a customer behind."""
    html = _render(app, _takeover())

    assert 'id="cardCaptureClose"' in html
    assert 'id="cardCaptureCancel"' in html
    assert "settle({ saved: false })" in html


def test_the_card_dialog_carries_the_authorisation_sentence(app):
    """The sentence that says what saving a card lets Minty do LATER — the same wording
    onboarding uses, so a payer who saw it there is not asked to authorise twice in two
    different forms of words."""
    html = _render(app, _takeover())

    assert (
        "By providing your payment method, you authorise Minty to charge applicable"
        in html
    )
    assert "subscription fees in accordance with the Subscription Terms." in html


def test_stripes_own_mandate_is_suppressed(app):
    """Stripe renders its own mandate inside the iframe naming the STRIPE ACCOUNT rather
    than Minty — in test mode "you allow Cash sandbox to charge your card". It is turned
    off, which is only safe BECAUSE the dialog carries its own mandate sentence: the two
    are a pair and neither may be removed alone."""
    html = _render(app, _takeover())

    assert "terms: { card: 'never' }" in html
    assert "you authorise Minty to charge applicable" in html, "the replacement mandate"


def test_the_details_link_goes_nowhere_on_purpose(app):
    """There is no Subscription Terms document: legal/ holds only the Terms of Use and
    the Privacy Policy, and the Terms say Minty is free during beta (§11). Pointing this
    at /legal/terms would send someone about to be charged to a page saying the service
    is free, which is worse than an inert link."""
    html = _render(app, _takeover())

    details = html[html.index("(Details)") - 300 : html.index("(Details)")]
    assert 'href="#"' in details
    assert "/legal/terms" not in details


def test_the_card_dialog_says_where_the_card_number_goes(app):
    """One sentence, the same in all three apps.

    It used to say saving charges nothing — true, and it is what a form in front of a
    priced screen most obviously raises. It was unified away in favour of the question a
    card form raises everywhere it appears, which is where the number ends up; what may be
    charged, and when, is left to the mandate below it. If the reassurance is wanted back
    it belongs BESIDE this line, not instead of it.
    """
    html = _render(app, _takeover())

    assert "held by our payment provider, Stripe" in html
    # Not "never stored by Minty" — the template wraps mid-phrase, and an assertion that
    # spans the break breaks on a reflow that changed nothing a payer can see.
    assert "never stored" in html
    # The mandate is still the thing that says a charge may follow, and it is not optional
    # — Stripe's own is suppressed with terms.card:'never'.
    assert "you authorise Minty to charge applicable" in html


def test_the_card_dialog_matches_the_onboarding_sheet(app):
    """A payer who saved a card during onboarding meets this list again here, so it uses
    the same tokens rather than looking like a different product."""
    html = _render(app, _takeover())

    assert "bg-[rgba(15,23,27,0.45)]" in html, "the buynow-overlay dim"
    assert "backdrop-blur-[2px]" in html
    assert "max-w-[480px]" in html, "the buynow-sheet width"
    assert "from-[#00CBC6] to-[#00D5BF]" in html, "btn-primary"


def test_the_chosen_card_is_highlighted(app):
    """A bare radio dot on seven identical rows is hard to read, which is how a
    confirmation naming a card the payer had not chosen got as far as a screenshot."""
    html = _render(app, _takeover())

    assert "restart-pmrow" in html
    assert "paintChosen" in html
    assert "border-[#36c3b4]" in html, "the accent border on the chosen row"
    assert "bg-[#e6f7f4]" in html, "and accent-soft behind it"


def test_an_expired_saved_card_is_flagged(app):
    """It can still be selected and WOULD be charged, so it says so here rather than at
    the failed payment weeks later."""
    with_expired = _takeover()
    with_expired["methods"]["methods"][0]["expired"] = True
    html = _render(app, with_expired)

    assert "Expired" in html
    assert "text-[#b4231f]" in html


def test_an_empty_wallet_gets_its_own_way_in(app):
    """Behind a dialog the form needs a button, or a payer with no card has nothing to
    click."""
    empty = _takeover()
    empty["methods"] = {"has_account": False, "default_id": None,
                        "methods": [], "total": 0}
    html = _render(app, empty)

    assert 'id="restartAddCardToggle"' in html
    # The same words as every other picker's way in, empty wallet or full.
    assert "New billing account" in html
    assert "no card saved" in html


# --- the confirmation dialog --------------------------------------------------


def test_confirming_opens_a_dialog(app):
    """The last thing between the payer and a charge, so it is read in one place rather
    than in a panel below a long card list that can open off-screen."""
    html = _render(app, _takeover())

    assert 'id="restartConfirm"' in html
    assert 'aria-labelledby="restartConfirmTitle"' in html
    assert "openConfirm" in html


def test_the_confirmation_states_all_three_facts(app):
    """Modules, card and amount. A charge disclosed as two of the three is not
    disclosed."""
    html = _render(app, _takeover())

    assert 'id="restartConfirmModules"' in html
    assert 'id="restartConfirmCard"' in html
    assert 'id="restartConfirmAmount"' in html
    assert "charges your card now" in html


def test_the_confirmation_can_be_backed_out_of(app):
    """Back is not a way out of the restart — it returns to the selection, which is what
    someone who has just read the amount and changed their mind needs."""
    html = _render(app, _takeover())

    assert 'id="restartConfirmBack"' in html
    assert 'id="restartConfirmClose"' in html
    assert "closeConfirm" in html


def test_the_label_hooks_are_named_not_borrowed_utilities(app):
    """REGRESSION. The confirmation read the card name off '.font-medium'. Restyling the
    rows to font-semibold silently turned the named card into "your saved card" — a
    charge disclosed against a card the payer had not chosen."""
    html = _render(app, _takeover())

    assert "restart-pm-label" in html
    assert "restart-module-label" in html
    assert "querySelector('.font-medium')" not in html


def test_editing_the_selection_retracts_the_confirmation(app):
    """The confirm box quotes a module set, an amount and a card. Left up while the
    payer changes one of them it describes a charge they would not get — which is how
    a screenshot came to show "charge 27.61 to Visa 5556" with Unionpay selected."""
    html = _render(app, _takeover())

    assert "retractConfirm" in html
    # Both the module boxes and the card radios have to retract it, not just one.
    assert "restart-card" in html.split("retractConfirm", 1)[1]


def test_the_panel_keeps_the_whole_ordinary_page(app):
    """The live trial that put us in panel mode still needs its own controls."""
    html = _render(app, _takeover("panel"))

    assert "restartScreen" in html, "the restart box renders"
    assert "subscription-panel" in html, "and so does the ordinary page"
    assert "openSubscriptionDecision" in html, "including its scripts"


def test_the_panel_scopes_itself_to_what_lapsed(app):
    """A payer whose other trial is still running must be able to tell that only one
    module went dark, or the panel reads as a threat to everything."""
    html = _render(app, _takeover("panel"))

    assert "unaffected" in html


# --- who may act --------------------------------------------------------------


@pytest.mark.parametrize("mode", ["takeover", "panel"])
def test_a_co_admin_gets_no_form_in_either_mode(app, mode):
    html = _render(
        app, _takeover(mode, can_act=False), subscription_payer=_FakePayer()
    )

    assert "restartScreen" not in html, "no form they could fill in and never submit"
    assert "Restart billing" not in html
    # The ordinary page is untouched for them.
    assert "subscription-panel" in html


def test_a_co_admin_is_told_who_has_to_act(app):
    """The one genuinely useful thing available to them: go and ask that person."""
    html = _render(
        app, _takeover("takeover", can_act=False), subscription_payer=_FakePayer()
    )

    assert "Dana" in html
    assert "dana@example.com" in html


def test_a_co_admin_with_no_named_payer_still_gets_the_notice(app):
    html = _render(app, _takeover("takeover", can_act=False), subscription_payer=None)

    assert "needs to restart billing" in html


# --- nothing lapsed -----------------------------------------------------------


def test_no_lapse_renders_the_ordinary_page_untouched(app):
    html = _render(app, None)

    assert "restartScreen" not in html
    assert "subscription-panel" in html
    assert "openSubscriptionDecision" in html


# --- choosing a card before paying --------------------------------------------
#
# The card is account-level today (the engine reads
# invoice_settings.default_payment_method and nothing else). Per-company cards are a
# planned change; these controls are already where they need to be for it, and only what
# they post to has to move when it lands.


def _scripts(app):
    from flask import render_template

    with app.test_request_context():
        return render_template(
            "entity/partials/module_subscription_scripts.html",
            org=_FakeOrg(), module_cards=[dict(_CARD)], subscription_panel=_PANEL,
            subscription_summary={}, can_manage_modules=True, dev_tools=False,
        )


def test_the_decision_modal_can_choose_a_card(app):
    """It used to authorise whatever the account default was, with no way to change it
    from there — the payer had to leave, change it elsewhere and come back."""
    scripts = _scripts(app)

    assert 'id="billingConfirmCardRows"' in scripts
    assert "payment_method: ok.card" in scripts


def test_the_card_choice_is_rows_and_not_a_dropdown(app):
    """A <select> described a card in its own vocabulary and could show no flags at all,
    so a payer could authorise a charge against an EXPIRED card with nothing saying so."""
    scripts = _scripts(app)

    assert "billingConfirmCardSelect" not in scripts, "the dropdown is gone"
    assert 'name="billing-confirm-card"' in scripts, "radio rows in its place"
    # The same pills, in the same order, as the restart screen and the payer portal.
    for flag in ("Billing this", "Default", "Expiring soon", "Expired"):
        assert flag in scripts, flag
    assert "pm.expired" in scripts


def test_the_card_is_chosen_before_the_charge_is_authorised(app):
    """The picker is inside the confirmation, so the card is settled BEFORE consent is
    recorded — and the route nominates it before recording, not after."""
    scripts = _scripts(app)

    assert scripts.index("billingConfirmCardRows") < scripts.index("payment_method: ok.card")

    routes = open("blueprints/entity/routes/settings.py", encoding="utf-8").read()
    body = routes[
        routes.index("def entity_settings_module_authorize_billing(") :
        routes.index("# --- The lapsed-trial restart screen")
    ]
    assert body.index("set_for_entity") < body.index("authorize_entity_billing(org")


def test_a_single_card_is_shown_in_the_same_list_as_several(app):
    """A confirmation that names no card asks the payer to agree to a charge they cannot
    check. It used to name a lone card in a read-only line, because a <select> holding one
    option is unusable — a row list is not, so one card gets the same list as seven and is
    described in the same words, with the same flags."""
    scripts = _scripts(app)

    assert "cards.length > 0" in scripts, "any saved card gets the list"
    assert "onlyCard" not in scripts, "no separate read-only line for a single card"
    # Only the COLLAPSE toggle is gated on there being more than one: "Change" over a
    # one-row list is a control that cannot do anything.
    assert "const many = cards.length > 1;" in scripts


def test_the_card_choice_does_not_change_the_old_confirm_contract(app):
    """openBillingConfirm is shared with the cancel and purchase flows, which all do
    `if (!ok)`. Resolving with an object keeps those working; resolving with a bare id
    would have made an empty selection read as a cancellation."""
    scripts = _scripts(app)

    assert "close(chosen ? { card: chosen } : true)" in scripts
    assert "function onCancel() { close(false); }" in scripts


def test_the_choice_is_not_described_as_account_wide(app):
    """It never was described that way, and now it must never be.

    The disclosure was deliberately left off while a payer had one card and every such
    choice really did repoint every company — a known interim state with the per-company
    change already planned, where a warning would have aged into a lie. It has aged out
    instead: choosing here nominates THIS company onto that card and moves nothing else,
    so the warning would now be false rather than merely premature. Kept as an assertion
    rather than deleted, because the sentence is still in git history and re-adding it
    would be a plausible-looking mistake.
    """
    card = _restart_card(_render(app, _takeover()))
    scripts = _scripts(app)

    assert "card for your whole billing account" not in card
    assert "card for your whole billing account" not in scripts
    assert "every company" not in card


# --- saving a card without leaving the page -----------------------------------


def _card_branch(scripts: str) -> str:
    """resolveTrialGap's no-card branch.

    The end anchor is searched FROM the branch, not from the top: the same
    showBlockingLoader call appears earlier in the file, and anchoring on the first hit
    silently produced an empty slice that made every assertion below it pass.
    """
    start = scripts.index("if (gap === 'card')")
    return scripts[start : scripts.index("showBlockingLoader('Confirming", start)]


def test_the_decision_modal_no_longer_redirects_to_save_a_card(app):
    """It used to POST for a hosted Stripe URL and navigate away, so a payer part-way
    through "keep my trial" lost the decision and had to make it again on their return.
    The card is now captured in page and the flow carries straight on to consent."""
    scripts = _scripts(app)

    card_branch = _card_branch(scripts)
    assert "openCardCapture" in card_branch
    assert "return 'redirected';" in card_branch, "kept only as a fallback"
    # The fallback is reached only when the component is absent, never by default.
    assert "typeof window.openCardCapture !== 'function'" in card_branch


def test_saving_a_card_falls_through_to_authorising(app):
    """Saving a card is NOT consent — the payer's card is shared across their companies
    — so the card branch must not return early on success. Both halves of "keep this
    trial" now happen in one go, which is the point of doing it in page."""
    scripts = _scripts(app)

    card_branch = _card_branch(scripts)
    assert "if (!saved || !saved.saved) return 'declined';" in card_branch
    # No success return: control reaches the authorisation below.
    assert "return 'done'" not in card_branch


def test_there_is_exactly_one_elements_integration_on_the_page(app):
    """Two would be two places for the mandate, the terms suppression and the mount
    ordering to drift apart."""
    html = _render(app, _takeover())

    assert html.count("elements.create('payment'") == 1
    assert html.count("js.stripe.com/v3") == 1
    assert html.count("terms: { card: 'never' }") == 1


def test_the_capture_dialog_is_available_without_a_lapse(app):
    """The decision modal runs on an ordinary page. Gating the dialog on a lapse would
    have left exactly the case this fixes still redirecting."""
    html = _render(app, None)

    assert 'id="cardCaptureModal"' in html
    assert "restartScreen" not in html, "and nothing else from the restart screen"


# --- the collapsed card list --------------------------------------------------


def test_the_card_list_collapses_to_the_chosen_card(app):
    """Seven saved cards made this dialog taller than the viewport and pushed the amount
    and the button off the bottom."""
    html = _render(app, _two_cards())

    assert 'id="restartCardToggle"' in html
    assert 'id="restartCardRows"' in html
    assert "paintCollapsed" in html
    assert 'aria-expanded="false"' in html, "starts collapsed"
    assert 'aria-controls="restartCardRows"' in html


def test_one_saved_card_gets_no_change_control(app):
    """Nothing to expand to — a toggle that reveals the row already on screen is a
    control that does nothing."""
    card = _restart_card(_render(app, _takeover()))

    assert 'id="restartCardToggle"' not in card


def test_every_row_is_rendered_even_when_collapsed(app):
    """Collapsed in JS, not server-side. The confirmation reads the chosen card's label
    out of the DOM, and a row that was never rendered could not be read."""
    html = _render(app, _two_cards())

    assert html.count('class="restart-pmrow') == 2
    assert "restart-pm-label" in html


def test_choosing_a_card_closes_the_list_again(app):
    """Picking is the whole reason it was open. Leaving it open would keep the button
    off-screen for the very next click."""
    html = _render(app, _two_cards())

    handler = html.split("classList.contains('restart-card')", 1)[1][:400]
    assert "expanded = false" in handler
    assert "paintCollapsed()" in handler
