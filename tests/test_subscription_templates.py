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


def test_trial_is_decided_in_the_modal_not_on_the_cards(app):
    """A running trial offers no per-card Cancel: it is kept or dropped by ticking
    it in the trial decision modal, which the panel's button opens."""
    section, scripts = _render_trial(app)

    # Nothing on the card cancels the trial any more.
    assert "cancelSubscription" not in section
    # The panel's primary action opens the modal instead of jumping to checkout.
    assert "openSubscriptionDecision" in section
    assert "Subscribe to Minty" in section
    # And the modal carries one tickable row per trialing module.
    assert 'data-keep-code="PETTY_CASH"' in scripts
    assert 'data-keep-code="BILL"' in scripts
    assert scripts.count('data-keep-state="trial"') == 2


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


def test_payment_method_banner_is_dev_only(app):
    """TEMPORARY dev affordance — it must not reach a production page, where the
    modal is the only route into add-card / confirm-billing."""
    on, _ = _render_trial(app)
    assert "Add payment method" in on

    off, _ = _render_trial(app, dev_tools=False)
    assert "Add payment method" not in off
    assert "Confirm billing" not in off


def test_stripe_portal_is_dev_only_too(app):
    """The billing PORTAL moved off the panel and into the same dev-only banner. The
    panel's own Manage subscription stays, but it opens the decision modal instead."""
    paid_card = _trial_card("PETTY_CASH", "Petty Cash")
    paid_card.update(subscription_status="active", needs_card=False)
    paid = dict(_TRIAL_PANEL, primary_action="manage", subscribe_codes=[])

    on, _ = _render_trial(app, module_cards=[paid_card], subscription_panel=paid)
    assert "openManageBilling" in on
    # In the banner, not the panel: the panel's action hook renders empty.
    assert on.index("openManageBilling") < on.index("subscription-panel")

    off, _ = _render_trial(
        app, module_cards=[paid_card], subscription_panel=paid, dev_tools=False
    )
    assert "openManageBilling" not in off
