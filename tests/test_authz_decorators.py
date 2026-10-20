from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from flask import Blueprint, Flask, get_flashed_messages, jsonify

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

    app.register_blueprint(auth_bp)
    entity_bp = Blueprint("entity", __name__)

    @entity_bp.route("/entity")
    def entity_list():
        return "companies"

    app.register_blueprint(entity_bp)
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


def test_require_permission_sends_a_browser_to_the_company_list(monkeypatch):
    """Flask draws no page (2026-10-20): a browser is refused onto ``/entity``, which carries the
    flashed message to minty-web's company list."""
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
        assert get_flashed_messages() == ["denied"]

    assert response.status_code == 302
    assert response.location == "/entity"


def test_permission_denied_sends_a_browser_to_the_company_list():
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied("denied", entity_id="e-1")
        assert get_flashed_messages() == ["denied"]

    assert response.status_code == 302
    assert response.location == "/entity"


def test_a_module_denial_says_why_on_the_company_list():
    """No page shows "Module not active" any more, so the message itself is the notice."""
    app = _build_app()

    with app.test_request_context("/protected?entity_id=e-1"):
        response = authz.permission_denied(
            "Petty Cash is not activated for this entity.",
            entity_id="e-1",
            reason=authz.DENIAL_MODULE_INACTIVE,
        )
        assert get_flashed_messages() == ["Petty Cash is not activated for this entity."]

    assert response.status_code == 302
    assert response.location == "/entity"


def test_module_denial_json_body_carries_the_reason():
    """API callers get the message and the reason, as before."""
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


def test_require_module_sends_a_browser_to_the_company_list(monkeypatch):
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
    assert response.location == "/entity"


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
