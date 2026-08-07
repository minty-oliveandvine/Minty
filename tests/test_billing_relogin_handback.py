"""Module 2 asks for a new billing JWT; it must be handed BACK to Module 2.

The regression these cover: ``billing-relogin`` used to redirect to ``next`` on
Minty's own origin. ``next`` is a Module 2 path, so the payer portal's ``/profile``
landed on a 404 here — after the frontend had already cleared its cookie, which
left every request on that page failing with "you're signed out".
"""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

FRONTEND = "http://frontend.test"
USER_ID = "user-1"
ENTITY_ID = "entity-1"


@pytest.fixture
def module_routes(app):
    """The route module, imported only once the app has built the blueprint."""
    from blueprints.entity.routes import modules

    return modules


def _patch_common(monkeypatch, module_routes, *, org=None, is_member=True):
    """Stand in for everything the handback reads: session, DB and token minting."""
    monkeypatch.setattr(
        module_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id=USER_ID),
    )
    monkeypatch.setattr(module_routes, "_frontend_origin", lambda: FRONTEND)
    monkeypatch.setattr(
        module_routes, "_generate_module_token", lambda *a, **k: "fresh-token"
    )
    monkeypatch.setattr(module_routes, "_resolve_user_entity_role", lambda *a: "admin")
    monkeypatch.setattr(module_routes, "_is_module_enabled", lambda *a: True)
    monkeypatch.setattr(module_routes, "is_superuser", lambda _u: False)
    monkeypatch.setattr(
        module_routes,
        "Entity",
        SimpleNamespace(
            id="entities.id",
            query=SimpleNamespace(filter=lambda *a: SimpleNamespace(first=lambda: org)),
        ),
    )
    monkeypatch.setattr(
        module_routes,
        "UserEntity",
        SimpleNamespace(
            user_id="user_entity.user_id",
            entity_id="user_entity.entity_id",
            query=SimpleNamespace(
                filter=lambda *a: SimpleNamespace(
                    first=lambda: object() if is_member else None
                )
            )
        ),
    )


def _landing(location: str):
    parsed = urlparse(location)
    return parsed, parse_qs(parsed.query)


def test_unscoped_relogin_returns_to_module_two_landing(app, module_routes, monkeypatch):
    """Select Company → My Profile has no entity, and used to land on Minty's root."""
    _patch_common(monkeypatch, module_routes)

    with app.test_request_context("/billing-relogin?next=%2Fprofile"):
        response = module_routes.billing_relogin()

    assert response.status_code == 302
    parsed, query = _landing(response.location)
    assert f"{parsed.scheme}://{parsed.netloc}" == FRONTEND
    assert parsed.path == "/landing"
    assert query["next"] == ["/profile"]
    assert query["token"] == ["fresh-token"]
    assert "entity_id" not in query


def test_scoped_relogin_carries_the_entity(app, module_routes, monkeypatch):
    _patch_common(
        monkeypatch, module_routes, org=SimpleNamespace(name="Acme Ltd", xero_org_id="x-1")
    )

    with app.test_request_context(
        f"/entity/{ENTITY_ID}/billing-relogin?next=%2Fprofile%2Fbilling"
    ):
        response = module_routes.billing_relogin(ENTITY_ID)

    assert response.status_code == 302
    parsed, query = _landing(response.location)
    assert parsed.path == "/landing"
    assert query["next"] == ["/profile/billing"]
    assert query["entity_id"] == [ENTITY_ID]
    assert query["entity_name"] == ["Acme Ltd"]


def test_relogin_downgrades_to_unscoped_when_access_is_gone(
    app, module_routes, monkeypatch
):
    """A company they no longer belong to must not keep them off their own profile."""
    _patch_common(
        monkeypatch,
        module_routes,
        org=SimpleNamespace(name="Acme Ltd", xero_org_id="x-1"),
        is_member=False,
    )

    with app.test_request_context(f"/entity/{ENTITY_ID}/billing-relogin?next=%2Fprofile"):
        response = module_routes.billing_relogin(ENTITY_ID)

    _, query = _landing(response.location)
    assert "entity_id" not in query
    assert query["token"] == ["fresh-token"]


def test_relogin_refuses_a_protocol_relative_next(app, module_routes, monkeypatch):
    """``//evil.example`` is a URL, not a path — it would be an open redirect
    arriving with a freshly minted token."""
    _patch_common(monkeypatch, module_routes)

    with app.test_request_context("/billing-relogin?next=%2F%2Fevil.example"):
        response = module_routes.billing_relogin()

    parsed, query = _landing(response.location)
    assert f"{parsed.scheme}://{parsed.netloc}" == FRONTEND
    assert query["next"] == ["/profile"]


def test_relogin_without_a_session_goes_to_the_login_form(
    app, module_routes, monkeypatch
):
    _patch_common(monkeypatch, module_routes)
    monkeypatch.setattr(
        module_routes, "current_user", SimpleNamespace(is_authenticated=False, id=None)
    )

    with app.test_request_context("/billing-relogin?next=%2Fprofile"):
        response = module_routes.billing_relogin()

    assert response.status_code == 302
    assert "/landing" not in (response.location or "")


def test_module_reenter_still_targets_minty_and_rejects_protocol_relative(
    app, module_routes, monkeypatch
):
    """``/enter`` is the other direction — the payer portal jumping INTO Minty."""
    _patch_common(monkeypatch, module_routes)

    with app.test_request_context(
        f"/entity/{ENTITY_ID}/enter?next=%2Fentity%2F{ENTITY_ID}%2Fsettings"
    ):
        ok = module_routes.module_reenter(ENTITY_ID)
    with app.test_request_context(f"/entity/{ENTITY_ID}/enter?next=%2F%2Fevil.example"):
        blocked = module_routes.module_reenter(ENTITY_ID)

    assert ok.location == f"/entity/{ENTITY_ID}/settings"
    assert blocked.location.startswith("/")
    assert "evil.example" not in blocked.location
