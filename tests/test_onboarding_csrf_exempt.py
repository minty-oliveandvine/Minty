"""Every bearer-only write - /api/onboarding/* and the hub's /api/me/* - must be CSRF-exempt.

The onboarding app and minty-web are separate origins authenticating with a Bearer JWT,
not a session cookie — they have no CSRF token to send. CSRFProtect is on globally, so a
write route that isn't registered in ``bootstrap.py``'s exempt list is rejected *before*
the view runs. From the app that surfaces as an opaque failure with nothing in the app
logs, which is a miserable thing to debug — so assert the contract rather than trusting
the hand-maintained list.

The hub half was added on 2026-10-09, after ``/api/me/company/xero/release`` shipped
unexempt: the browser's fetch got a redirect to Flask's sign-in page instead of the
move it asked for, while every test passed (see below for why).

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


def _hub_write_views(app):
    """(path, dotted view name) for every registered ``/api/me/*`` write rule.

    The hub's bearer surface (``blueprints/shared/hub_api.py``): the entity list, My Profile,
    the Terms modal and a company's Users and Entity & Integration tabs. Every one is
    bearer-only and reads no session cookie, so every write on it must be exempt - there is
    no ``/api/me/*`` route a browser form posts to with a token.
    """
    views = []
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith("/api/me/"):
            continue
        if not {"POST", "PATCH", "PUT", "DELETE"} & (rule.methods or set()):
            continue
        view = app.view_functions[rule.endpoint]
        views.append((path, f"{view.__module__}.{view.__name__}"))
    return sorted(set(views))


def test_there_are_hub_write_routes(app):
    """Guard the guard, as above."""
    assert _hub_write_views(app)


def test_every_hub_write_is_csrf_exempt(app):
    exempt = _csrf(app)._exempt_views
    missing = [path for path, dotted in _hub_write_views(app) if dotted not in exempt]
    assert not missing, (
        "These hub write routes are not CSRF-exempt, so CSRFProtect rejects them before "
        "the view runs - minty-web's fetch gets Flask's sign-in redirect instead of an "
        "answer. Add them to csrf.exempt(...) in "
        f"services/app_runtime/legacy/bootstrap.py: {missing}"
    )

