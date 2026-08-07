"""Module 2's billing JWT ran out; ``billing-relogin`` sends the user to Minty's
own landing page.

The regression these cover: the route used to redirect to ``next`` on Minty's
origin. ``next`` is a Module 2 path, so the payer portal's ``/profile`` landed on
a 404 here — after the frontend had already cleared its cookie, which left every
request on that stranded page failing with "you're signed out".
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

ENTITY_ID = "entity-1"


@pytest.fixture
def module_routes(app):
    """The route module, imported only once the app has built the blueprint."""
    from blueprints.entity.routes import modules

    return modules


def _signed_in(monkeypatch, module_routes, *, authenticated=True):
    monkeypatch.setattr(
        module_routes,
        "current_user",
        SimpleNamespace(is_authenticated=authenticated, id="user-1"),
    )


def test_relogin_lands_on_minty_home(app, module_routes, monkeypatch):
    """Signed in on this origin — ``auth.home`` forwards to the entity list."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context("/billing-relogin"):
        response = module_routes.billing_relogin()

    assert response.status_code == 302
    assert response.location == "/"


def test_scoped_relogin_lands_in_the_same_place(app, module_routes, monkeypatch):
    """Module 2 puts the entity in the path when it has one; it changes nothing."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context(f"/entity/{ENTITY_ID}/billing-relogin"):
        response = module_routes.billing_relogin(ENTITY_ID)

    assert response.status_code == 302
    assert response.location == "/"


def test_relogin_without_a_session_still_lands_on_home(app, module_routes, monkeypatch):
    """``auth.home`` renders the login form when there is no session to reuse."""
    _signed_in(monkeypatch, module_routes, authenticated=False)

    with app.test_request_context("/billing-relogin"):
        response = module_routes.billing_relogin()

    assert response.status_code == 302
    assert response.location == "/"


@pytest.mark.parametrize(
    "hostile", ["%2Fprofile", "%2F%2Fevil.example", "https%3A%2F%2Fevil.example"]
)
def test_relogin_ignores_next_entirely(app, module_routes, monkeypatch, hostile):
    """Nothing Module 2 sends decides where this route goes — not the page the
    user was on, and not a URL that would make this an open redirect."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context(f"/billing-relogin?next={hostile}"):
        response = module_routes.billing_relogin()

    assert response.location == "/"


def test_module_reenter_still_targets_minty_and_rejects_protocol_relative(
    app, module_routes, monkeypatch
):
    """``/enter`` is the other direction — the payer portal jumping INTO Minty —
    so it does still honour ``next``, as a path on this origin only."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context(
        f"/entity/{ENTITY_ID}/enter?next=%2Fentity%2F{ENTITY_ID}%2Fsettings"
    ):
        ok = module_routes.module_reenter(ENTITY_ID)
    with app.test_request_context(f"/entity/{ENTITY_ID}/enter?next=%2F%2Fevil.example"):
        blocked = module_routes.module_reenter(ENTITY_ID)

    assert ok.location == f"/entity/{ENTITY_ID}/settings"
    assert blocked.location.startswith("/")
    assert "evil.example" not in blocked.location
