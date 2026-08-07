"""Where Module 2 goes when its billing JWT runs out: Minty's landing page.

The regression: Module 2 used to ask ``billing-relogin`` to return it to the page
it was on, and that path — Module 2's, replayed on this origin — was a 404 here
for the payer portal's ``/profile``. The frontend had already cleared its cookie
by then, so every request on the stranded page failed with "you're signed out".

Module 2 now navigates straight to ``/``. The route below survives only for
browsers still running an older build, and it lands in the same place.
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


def test_relogin_lands_on_the_minty_landing_page(app, module_routes, monkeypatch):
    """``/`` forwards to ``/entity`` while the Flask session is alive."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context(f"/entity/{ENTITY_ID}/billing-relogin"):
        response = module_routes.billing_relogin(ENTITY_ID)

    assert response.status_code == 302
    assert response.location == "/"


def test_relogin_without_a_session_lands_there_too(app, module_routes, monkeypatch):
    """Same URL, and ``/`` renders the login form when there is no session."""
    _signed_in(monkeypatch, module_routes, authenticated=False)

    with app.test_request_context(f"/entity/{ENTITY_ID}/billing-relogin"):
        response = module_routes.billing_relogin(ENTITY_ID)

    assert response.status_code == 302
    assert response.location == "/"


@pytest.mark.parametrize(
    "hostile", ["%2Fprofile", "%2F%2Fevil.example", "https%3A%2F%2Fevil.example"]
)
def test_relogin_ignores_next_entirely(app, module_routes, monkeypatch, hostile):
    """Nothing Module 2 sends decides where this route goes — not the page the
    user was on, and not a URL that would make this an open redirect."""
    _signed_in(monkeypatch, module_routes)

    with app.test_request_context(
        f"/entity/{ENTITY_ID}/billing-relogin?next={hostile}"
    ):
        response = module_routes.billing_relogin(ENTITY_ID)

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
