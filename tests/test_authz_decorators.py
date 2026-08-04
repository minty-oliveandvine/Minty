from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from flask import Blueprint, Flask, flash, get_flashed_messages, jsonify

from services import authz
from services.permission_policy import Permission


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.route("/login")
    def login():
        return "login"

    @auth_bp.route("/no-permission")
    def no_permission():
        return "no permission"

    app.register_blueprint(auth_bp)
    return app


def _stub_module_gate(monkeypatch, *, enabled: bool) -> None:
    """Stand in for ``blueprints.entity.routes.modules``.

    ``require_module`` imports that module lazily (it imports authz back, so the
    import has to happen at call time). Importing the real one here would re-run
    its ``@entity_bp.route`` decorators against a blueprint the app fixture has
    already registered, which Flask rejects — so swap in a stub that only has
    the one function the guard calls.
    """
    stub = ModuleType("blueprints.entity.routes.modules")
    stub._is_module_enabled = lambda *_args, **_kwargs: enabled  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "blueprints.entity.routes.modules", stub)


def test_require_entity_access_returns_401_for_unauthenticated(monkeypatch):
    app = _build_app()

    @authz.require_entity_access(entity_keys=("entity_id",))
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(authz, "current_user", SimpleNamespace(is_authenticated=False))

    with app.test_request_context("/api/protected?entity_id=e-1"):
        response, status = protected()

    assert status == 401
    assert response.get_json()["message"] == "Authentication required"


def test_require_entity_access_returns_400_when_entity_missing(monkeypatch):
    app = _build_app()

    @authz.require_entity_access(entity_keys=("entity_id",))
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )

    with app.test_request_context("/api/protected"):
        response, status = protected()

    assert status == 400
    assert response.get_json()["message"] == "I need to know which entity we're working with first!"


def test_require_entity_access_returns_403_when_membership_missing(monkeypatch):
    app = _build_app()

    @authz.require_entity_access(entity_keys=("entity_id",))
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )
    monkeypatch.setattr(authz, "has_entity_access", lambda *_args, **_kwargs: False)

    with app.test_request_context("/api/protected?entity_id=e-1"):
        response, status = protected()

    assert status == 403
    assert response.get_json()["message"] == "Hmm, it looks like you don't have permission to look there."


def test_require_permission_uses_entity_from_json_body(monkeypatch):
    app = _build_app()
    captured: dict[str, str | Permission | None] = {}

    @authz.require_permission(
        Permission.SALES_METHOD_CREATE,
        entity_keys=("entity_id",),
        message="denied",
    )
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )

    def _fake_has_permission(user, permission, entity_id=None):
        captured["user_id"] = user.id
        captured["permission"] = permission
        captured["entity_id"] = entity_id
        return True

    monkeypatch.setattr(authz, "has_permission", _fake_has_permission)

    with app.test_request_context(
        "/api/protected", method="POST", json={"entity_id": "entity-99"}
    ):
        response, status = protected()

    assert status == 200
    assert response.get_json()["status"] == "ok"
    assert captured == {
        "user_id": "user-1",
        "permission": Permission.SALES_METHOD_CREATE,
        "entity_id": "entity-99",
    }


def test_require_permission_returns_403_when_denied(monkeypatch):
    app = _build_app()

    @authz.require_permission(
        Permission.REPORT_VIEW_ENTITY,
        entity_keys=("entity_id",),
        message="denied",
    )
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )
    monkeypatch.setattr(authz, "has_permission", lambda *_args, **_kwargs: False)

    with app.test_request_context("/api/protected?entity_id=e-1"):
        response, status = protected()

    assert status == 403
    assert response.get_json()["message"] == "denied"


def test_require_permission_redirects_html_requests_to_no_permission(monkeypatch):
    app = _build_app()

    @authz.require_permission(
        Permission.REPORT_VIEW_ENTITY,
        entity_keys=("entity_id",),
        message="denied",
    )
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )
    monkeypatch.setattr(authz, "has_permission", lambda *_args, **_kwargs: False)

    with app.test_request_context("/protected?entity_id=e-1"):
        response = protected()

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/no-permission?entity_id=e-1")


def test_permission_denied_redirects_html_requests_to_no_permission():
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied("denied", entity_id="e-1")

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/no-permission?entity_id=e-1")


# --- denial reason ----------------------------------------------------------
#
# A disabled module and a missing permission used to be indistinguishable by the
# time they reached /no-permission, so the page could only say "access denied"
# to someone whose subscription had simply lapsed. The reason rides along now.


def test_permission_denial_carries_no_reason():
    """A real permission denial stays reasonless — the page keeps its old copy."""
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied("denied", entity_id="e-1")

    assert "reason=" not in (response.location or "")


def test_permission_denied_forwards_reason_to_no_permission():
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )

    assert response.status_code == 302
    assert "entity_id=e-1" in response.location
    assert f"reason={authz.DENIAL_MODULE_INACTIVE}" in response.location


def test_module_denial_does_not_flash():
    """The page renders its own "Module not active" copy — no duplicate toast."""
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )
        assert get_flashed_messages() == []


def test_permission_denial_still_flashes():
    """Only the module case is silent — the page has no specific copy for this."""
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        authz.permission_denied("denied", entity_id="e-1")
        assert get_flashed_messages() == ["denied"]


def test_module_denial_suppresses_only_its_own_toast():
    """The flash channel stays open — an unrelated pending message still drains.

    Suppressing the toast must not disable flashing for the no-permission page
    generally, or anything queued earlier in the session would vanish with it.
    """
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        flash("Your session ran out. Mind logging back in?", "warning")
        authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )
        assert get_flashed_messages() == ["Your session ran out. Mind logging back in?"]


def test_module_denial_keeps_everything_but_the_toast():
    """Redirect, entity_id and reason all survive the suppressed flash."""
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )
        assert get_flashed_messages() == []

    assert response.status_code == 302
    assert "/no-permission" in response.location
    assert "entity_id=e-1" in response.location
    assert f"reason={authz.DENIAL_MODULE_INACTIVE}" in response.location


def test_module_denial_json_body_is_unaffected_by_flash_suppression():
    """API callers never saw the toast, so they must still get the message."""
    app = _build_app()

    with app.test_request_context("/api/protected?entity_id=e-1"):
        response, status = authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )

    assert status == 403
    payload = response.get_json()
    assert payload["message"] == "Petty Cash is not activated for this entity."
    assert payload["reason"] == authz.DENIAL_MODULE_INACTIVE
    assert payload["status"] == "error"


def test_require_module_redirect_carries_module_inactive_reason(monkeypatch):
    app = _build_app()

    @authz.require_module("PETTY_CASH", entity_keys=("entity_id",))
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )
    _stub_module_gate(monkeypatch, enabled=False)

    with app.test_request_context("/protected?entity_id=e-1"):
        response = protected()

    assert response.status_code == 302
    assert f"reason={authz.DENIAL_MODULE_INACTIVE}" in response.location


def test_require_module_json_denial_includes_reason(monkeypatch):
    app = _build_app()

    @authz.require_module("PETTY_CASH", entity_keys=("entity_id",))
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )
    _stub_module_gate(monkeypatch, enabled=False)

    with app.test_request_context("/api/protected?entity_id=e-1"):
        response, status = protected()

    assert status == 403
    payload = response.get_json()
    assert payload["reason"] == authz.DENIAL_MODULE_INACTIVE
    assert payload["message"] == "This module is not activated for this entity."


def test_require_permission_without_entity_context(monkeypatch):
    app = _build_app()
    captured = {}

    @authz.require_permission(Permission.ENTITY_CREATE, message="denied")
    def protected():
        return jsonify({"status": "ok"}), 200

    monkeypatch.setattr(
        authz,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", system_role="normal"),
    )

    def _fake_has_permission(user, permission, entity_id=None):
        captured["user_id"] = user.id
        captured["permission"] = permission
        captured["entity_id"] = entity_id
        return True

    monkeypatch.setattr(authz, "has_permission", _fake_has_permission)

    with app.test_request_context("/entity/create"):
        response, status = protected()

    assert status == 200
    assert response.get_json()["status"] == "ok"
    assert captured == {
        "user_id": "user-1",
        "permission": Permission.ENTITY_CREATE,
        "entity_id": None,
    }
