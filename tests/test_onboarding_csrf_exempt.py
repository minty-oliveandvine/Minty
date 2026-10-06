"""Every /api/onboarding/* POST must be CSRF-exempt.

The onboarding app is a separate origin and authenticates with a Bearer JWT, not a
session cookie — it has no CSRF token to send. CSRFProtect is on globally, so a POST
route that isn't registered in ``bootstrap.py``'s exempt list is rejected with a
plain-HTML 400 *before* the view runs. From the wizard that surfaces as an opaque
failure with nothing in the app logs, which is a miserable thing to debug — so
assert the contract rather than trusting the hand-maintained list.

This checks the exemption REGISTRY, not the response: the test app sets
``WTF_CSRF_ENABLED = False`` (conftest), so CSRF never actually fires here and a
behavioural "POST returns 401 not 400" test would pass even when the route is
unexempt — i.e. it would be vacuous. ``csrf._exempt_views`` is what governs
production, so that's what we assert on.
"""
from __future__ import annotations


def _csrf(app):
    csrf = app.extensions.get("csrf")
    assert csrf is not None, "CSRFProtect is not initialised on the app"
    return csrf


def _onboarding_post_views(app):
    """(path, dotted view name) for every registered /api/onboarding/* POST rule."""
    views = []
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith("/api/onboarding/"):
            continue
        if "POST" not in (rule.methods or set()):
            continue
        view = app.view_functions[rule.endpoint]
        views.append((path, f"{view.__module__}.{view.__name__}"))
    return sorted(set(views))


def test_there_are_onboarding_post_routes(app):
    """Guard the guard: if this ever finds nothing, the test below is vacuous."""
    assert _onboarding_post_views(app)


def test_every_onboarding_post_is_csrf_exempt(app):
    exempt = _csrf(app)._exempt_views
    missing = [
        path
        for path, dotted in _onboarding_post_views(app)
        if dotted not in exempt
    ]
    assert not missing, (
        "These onboarding POST routes are not CSRF-exempt, so CSRFProtect will "
        "reject them with a 400 before the view runs. Add them to csrf.exempt(...) "
        f"in services/app_runtime/legacy/bootstrap.py: {missing}"
    )

