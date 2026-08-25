"""The module-settings templates + the shared subscription partials must parse."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "entity/settings_module.html",
        "entity/settings_module_bills_ui.html",
        "entity/partials/module_subscription_section.html",
        "entity/partials/module_subscription_scripts.html",
    ],
)
def test_module_template_parses(app, name):
    # get_template compiles the Jinja source, raising TemplateSyntaxError on a
    # malformed tag/expression.
    app.jinja_env.get_template(name)


class _FakeOrg:
    id = "org-123"
    name = "Acme"


def test_section_and_scripts_render(app):
    """Render the partials so every url_for endpoint (checkout / manage-billing /
    save / shell alias) is resolved — a wrong endpoint name raises BuildError."""
    from flask import render_template

    with app.test_request_context():
        scripts = render_template(
            "entity/partials/module_subscription_scripts.html", org=_FakeOrg()
        )
        section = render_template(
            "entity/partials/module_subscription_section.html",
            org=_FakeOrg(),
            module_cards=[],
            subscription_summary=None,
            can_manage_modules=True,
        )

    # The action endpoints resolved to real URLs.
    assert "/checkout" in scripts
    assert "/manage-billing" in scripts
    # Access is Stripe-driven now: no on/off toggle or Save button in the section.
    assert "save-modules-button" not in section
    assert "module-toggle" not in section


def _trial_card(code, name):
    """A module card mid-free-trial, with the keys both partials read."""
    from decimal import Decimal

    return {
        "code": code, "name": name, "description": "", "image": "x.png",
        "learn_more": "#", "subscription_status": "trialing",
        "amount": Decimal("280"), "can_cancel": True, "pending_cancel": False,
        "trial_cancelled": False, "trial_eligible": False,
        "period_end_short": "19 Aug", "period_end_long": "19 Aug 2026",
        "access_end_long": None, "needs_card": True, "needs_consent_only": False,
    }


_TRIAL_PANEL = {
    "is_empty": False, "currency": "HK$", "lines": [], "note": None,
    "total": "HK$400", "winding_down": [], "upcoming_charges": [], "footer": "",
    "primary_action": "subscribe_stripe", "subscribe_codes": ["PETTY_CASH", "BILL"],
}


def _render_trial(app, **overrides):
    from flask import render_template

    ctx = dict(
        org=_FakeOrg(),
        module_cards=[_trial_card("PETTY_CASH", "Petty Cash"),
                      _trial_card("BILL", "Payment Request")],
        subscription_summary={"currency": "HK$", "bundle_amount": 400,
                              "bundle_codes": ["BILL", "PETTY_CASH"],
                              "bundle_name": "Super Minty"},
        subscription_panel=_TRIAL_PANEL,
        can_manage_modules=True,
        dev_tools=True,
    )
    ctx.update(overrides)
    with app.test_request_context():
        return (
            render_template("entity/partials/module_subscription_section.html", **ctx),
            render_template("entity/partials/module_subscription_scripts.html", **ctx),
        )


def _paid_card(code, name):
    """The same card, once the trial has converted and it is being billed."""
    card = _trial_card(code, name)
    card.update({"subscription_status": "active", "needs_card": False})
    return card


def _keep_input(scripts, code):
    """The decision modal's <input> for one module."""
    import re

    for tag in re.findall(r"<input[^>]*>", scripts):
        if f'data-keep-code="{code}"' in tag:
            return tag
    raise AssertionError(f"no decision-modal row rendered for {code}")


def test_trial_is_decided_in_the_modal_not_on_the_cards(app):
    """A running trial offers no per-card Cancel: what it still needs — a card, this
    company's consent — is settled in the decision modal the panel's button opens."""
    section, scripts = _render_trial(app)

    # Nothing on the card cancels the trial any more.
    assert "cancelSubscription" not in section
    # The panel's primary action opens the modal instead of jumping to checkout.
    assert "openSubscriptionDecision" in section
    assert "Subscribe to Minty" in section
    # And the modal carries one row per trialing module.
    assert 'data-keep-code="PETTY_CASH"' in scripts
    assert 'data-keep-code="BILL"' in scripts
    assert scripts.count('data-keep-state="trial"') == 2


def test_a_running_trial_cannot_be_cancelled_from_the_ui(app):
    """There is no route to cancelling a free trial: not the module card, and not the
    decision modal, where the row is LOCKED ON.

    Disabled rather than removed. The modal's job is to state what the entity has, and
    dropping the trial row would leave a trial-only entity staring at an empty list. A
    disabled box still reports ``checked`` to every reader in the script, so the kept-trial
    path — card capture, billing consent — is untouched by this.
    """
    section, scripts = _render_trial(app)

    for code in ("PETTY_CASH", "BILL"):
        tag = _keep_input(scripts, code)
        assert "disabled" in tag, f"{code}'s trial row must not be untickable"
        assert "checked" in tag, f"{code} is live, so its row stays ticked"

    # The copy that reached the removed wiring is gone with it. Matched as the JS string
    # literal — single-quoted, as everything in this file is — so the comment recording
    # what was removed does not itself trip the assertion.
    assert "'Cancel free trial'" not in scripts
    assert "cancelSubscription" not in section


def _untried_card(code, name):
    """A module this entity has never held — its free trial is still available."""
    card = _trial_card(code, name)
    card.update({
        "subscription_status": None, "trial_eligible": True, "needs_card": False,
        "period_end_short": None, "period_end_long": None,
    })
    return card


def _spent_card(code, name):
    """Held a trial, used it up, never paid. No free days left, so it IS sellable."""
    card = _untried_card(code, name)
    card["trial_eligible"] = False
    return card


def test_an_untried_module_is_marked_as_still_having_its_trial(app):
    """The reported bug. "Manage subscription" charged for a module the entity had never
    held, while that module's own card — on the same page — offered the same module free
    for 30 days. One module, two routes, two prices.

    The row now carries the card's own ``trial_eligible``, so ``commitSubDecision`` sends
    it to the trial endpoint instead of checkout. Marking it here rather than re-deriving
    eligibility in JS is what makes the two routes agree by construction.
    """
    _section, scripts = _render_trial(
        app, module_cards=[_untried_card("PETTY_CASH", "Petty Cash")]
    )

    tag = _keep_input(scripts, "PETTY_CASH")
    assert 'data-keep-state="available"' in tag
    assert 'data-keep-trial-eligible="1"' in tag


def test_a_module_whose_trial_is_spent_is_still_a_purchase(app):
    """The other half, and the reason this is not "never charge for an available row": a
    spent trial or a lapsed paid module has no free days left, so taking it up again is a
    genuine purchase and still goes through checkout."""
    _section, scripts = _render_trial(
        app, module_cards=[_spent_card("PETTY_CASH", "Petty Cash")]
    )

    tag = _keep_input(scripts, "PETTY_CASH")
    assert 'data-keep-state="available"' in tag
    assert 'data-keep-trial-eligible=""' in tag


def test_the_modal_can_reach_the_trial_endpoint_at_all(app):
    """The route the fix depends on. Without this url_for the trial branch would post to
    the wrong place — and the failure would look like "nothing happened"."""
    _section, scripts = _render_trial(
        app, module_cards=[_untried_card("PETTY_CASH", "Petty Cash")]
    )

    assert "/start-trial" in scripts or "start_trial" in scripts


def test_a_paid_module_is_still_droppable_in_the_modal(app):
    """The other half, and the reason the lock is per-row rather than on the modal: a
    paid module is cancelled exactly as before, priced and confirmed against what
    remains."""
    _section, scripts = _render_trial(
        app, module_cards=[_paid_card("PETTY_CASH", "Petty Cash")]
    )

    tag = _keep_input(scripts, "PETTY_CASH")
    assert "disabled" not in tag
    assert "checked" in tag
    assert 'data-keep-state="paid"' in tag


def test_manage_opens_the_same_modal_not_the_portal(app):
    """A paying entity gets "Manage subscription" in the panel, and it opens the
    decision modal. The Stripe portal is the dev-only button in the banner."""
    paid_card = _trial_card("PETTY_CASH", "Petty Cash")
    paid_card.update(subscription_status="active", needs_card=False)
    paid = dict(_TRIAL_PANEL, primary_action="manage", subscribe_codes=["PETTY_CASH"])

    section, scripts = _render_trial(
        app, module_cards=[paid_card], subscription_panel=paid
    )
    assert "Manage subscription" in section
    assert section.count("openSubscriptionDecision") == 1
    # A paid module keeps its own Cancel on the card; only trials moved entirely into
    # the modal. Both routes run the same preview + confirmation.
    assert "Cancel Subscription" in section
    # The paid module is tickable there too, and tagged so unticking it is priced+confirmed.
    assert 'data-keep-state="paid"' in scripts
    assert "cancel-preview" in scripts


def test_paid_variant_lists_modules_the_entity_does_not_have(app):
    """"Change your modules" is add-or-remove, so a module with no subscription is a
    row too — unticked, and tagged so ticking it goes through checkout."""
    paid_card = _trial_card("PETTY_CASH", "Petty Cash")
    paid_card.update(subscription_status="active", needs_card=False)
    available = _trial_card("BILL", "Payment Request")
    available.update(subscription_status=None, needs_card=False, trial_eligible=True)

    _, scripts = _render_trial(
        app,
        module_cards=[paid_card, available],
        subscription_panel=dict(_TRIAL_PANEL, primary_action="manage"),
    )
    assert 'data-keep-state="available"' in scripts
    assert 'data-keep-state="paid"' in scripts
    # Ticking an available row adds it; that is a purchase, hence checkout.
    assert "/checkout" in scripts


# The dev-only trial banner these two tests covered ("Add payment method" / "Confirm
# billing" / the Stripe portal button) is GONE, along with the tests. Its own comment
# said to delete it once those actions had real homes, and they now do: the decision
# modal drives add-card and confirm-billing during a trial, and the restart screen
# (module_restart_body.html) drives them once one has lapsed. ``dev_tools`` itself
# survives for the cancellation charge below, which is a different affordance.


def test_an_untried_module_says_its_free_trial_is_available(app):
    """"not active" is three different situations, and the card names which one.

    The two post-mortems were already there — the trial was used up, or a paid period
    ran out. The offer was not: a module the entity has never held still has its free
    trial, and the card said only "not active" beside it, which reads as the same dead
    end as the other two.
    """
    untried = _trial_card("BILL", "Payment Request")
    untried.update(subscription_status=None, needs_card=False, trial_eligible=True)

    section, _ = _render_trial(app, module_cards=[untried])

    assert "not active" in section
    assert "free trial available" in section
    # The offer is a STATEMENT, not a control: taking the module up is a tick in the
    # decision modal, which is the only place the subscription's shape is chosen.
    assert "Start free trial" not in section


def test_a_used_up_trial_is_not_offered_one(app):
    """The mirror of the above, and the reason the two cannot both render: a spent
    trial still has its subscription row, and ``trial_eligible`` requires no row."""
    spent = _trial_card("BILL", "Payment Request")
    spent.update(subscription_status=None, needs_card=False,
                 trial_eligible=False, trial_expired=True)

    section, _ = _render_trial(app, module_cards=[spent])

    assert "free trial expired" in section
    assert "free trial available" not in section


def test_the_cancellation_charge_on_the_card_is_dev_only(app):
    """The pending cancel-extension used to print on the card in production, on the
    argument that the module which owes money should not be the one place that never says
    so. It is now behind the dev gate, because the customer is told twice already — the
    panel carries an "Upcoming charges" row for it, and the dialog that confirms the
    cancellation states it as due on the next invoice.

    So this pins de-duplication, not concealment: gated on the card, and still computed,
    because the same figure feeds the panel row that replaced it."""
    cancelling = _trial_card("PETTY_CASH", "Petty Cash")
    cancelling.update(
        subscription_status="active",
        pending_cancel=True,
        trial_cancelled=False,
        needs_card=False,
        access_end_long="18 Sep 2026",
        extension_formatted="HKD 43.29",
    )

    on, _ = _render_trial(app, module_cards=[cancelling])
    assert "HKD 43.29 on your next invoice" in on

    off, _ = _render_trial(app, module_cards=[cancelling], dev_tools=False)
    assert "on your next invoice" not in off
    # The rest of the cancelled card is untouched — only the money line is gated.
    assert "Cancelled" in off
    assert "18 Sep 2026" in off
