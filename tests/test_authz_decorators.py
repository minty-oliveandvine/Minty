from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, Flask, jsonify

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
