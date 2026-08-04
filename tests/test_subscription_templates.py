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
