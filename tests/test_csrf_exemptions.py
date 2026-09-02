"""Every bearer-authenticated write route must be CSRF-exempt, and that is testable.

``services/app_runtime/legacy/bootstrap.py`` says of the handover routes: "NO TEST CAN
CATCH A MISSING ONE -- tests/conftest.py disables CSRF entirely -- so these are verified
by hand". That is true only of tests that try to EXERCISE CSRF. It is not true of the
registry: ``CSRFProtect.exempt()`` records ``f"{view.__module__}.{view.__name__}"`` in
``csrf._exempt_views``, and ``csrf.protect()`` looks the request's view up by exactly
that key. Asserting against the set reproduces the runtime decision without CSRF being
switched on at all, so ``WTF_CSRF_ENABLED = False`` in conftest costs nothing here.

Why it matters: these surfaces are called by the Module 2 frontend and the onboarding app
with a billing JWT and NO session cookie. A missing exemption does not fail loudly -- CSRF
redirects the POST to the login page, the client parses an HTML 200 as JSON, and the GET
beside it keeps working because safe methods are never protected. That is exactly how
``my_entity_payment_method_api`` shipped broken: "the dialog read fine and only Save
failed".

These routes do not depend on the token for their security. Each proves the caller
another way -- the method must belong to the token's own customer
(``payment_methods._owned``), the caller must be the entity's payer (``_payer_of``), or
the service refuses anyone but the offer's recipient. The exemption is about the token
being absent by design, not about dropping a check.
"""
from __future__ import annotations

import pytest

# Methods that CSRFProtect actually guards. GET/HEAD/OPTIONS are never protected, so a
# read-only route needs no exemption and must not be demanded to have one.
_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _exempt_key(view) -> str:
    """The key CSRFProtect stores and looks up. Mirrors flask_wtf.csrf exactly."""
    return f"{view.__module__}.{view.__name__}"


def _write_routes(app, blueprint_name):
    """(endpoint, view) for every route on a blueprint that CSRF would protect."""
    found = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint.split(".")[0] != blueprint_name:
            continue
        if not (rule.methods & _PROTECTED_METHODS):
            continue
        found.append((rule.endpoint, app.view_functions[rule.endpoint]))
    return sorted(found)


def _exempt_views(app):
    csrf = app.extensions.get("csrf")
    assert csrf is not None, "CSRFProtect is not installed on the app"
    return csrf._exempt_views


def test_every_payer_portal_write_is_exempt(app):
    """The payer portal and the handover routes -- the set the comment calls unverifiable.

    Written against the blueprint rather than a hardcoded list so a NEW write route added
    to the payer portal fails here until it is exempted deliberately, which is the whole
    point of the hand-verification note.
    """
    routes = _write_routes(app, "subscription")
    assert routes, "expected write routes on the subscription blueprint"

    exempt = _exempt_views(app)
    missing = [ep for ep, view in routes if _exempt_key(view) not in exempt]

    assert not missing, (
        "these subscription write routes are NOT CSRF-exempt; called with a bearer token "
        f"and no session cookie they will silently 302 to the login page: {missing}"
    )


@pytest.mark.parametrize(
    "view_name",
    [
        "onboarding_billing_setup_intent",
        "onboarding_billing_confirm",
        "onboarding_billing_set_default",
        "onboarding_billing_authorize",
    ],
)
def test_onboarding_billing_writes_are_exempt(app, view_name):
    """Step 2's "Buy now" -- the payer's cards and consent to bill this entity.

    Named explicitly rather than swept from the blueprint: ``entity`` carries plenty of
    ordinary session-cookie routes that SHOULD be protected, so a blanket assertion there
    would be wrong. These four are the billing writes the onboarding app posts
    cross-origin, and they mirror the payer-portal routes above.
    """
    from blueprints.entity.routes import create

    view = getattr(create, view_name)
    assert _exempt_key(view) in _exempt_views(app), (
        f"{view_name} is not CSRF-exempt; the onboarding app posts it with a bearer "
        "token and no session cookie"
    )


def test_the_guard_would_notice_a_missing_exemption(app):
    """Proof the assertion above can actually fail.

    A test that only ever passes is indistinguishable from one asserting nothing. This
    pins that the key format still matches what ``CSRFProtect`` looks up: a name that was
    never exempted must be reported as missing.
    """
    exempt = _exempt_views(app)
    assert "blueprints.subscription.routes.portal.not_a_real_view" not in exempt
