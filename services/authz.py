from __future__ import annotations

from collections.abc import Iterable
from functools import wraps
from typing import Any

from flask import flash, jsonify, redirect, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from services.permission_policy import Permission, has_entity_access, has_permission


def _wants_json_response() -> bool:
    if request.path.startswith("/api"):
        return True
    if request.is_json:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept_header = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept_header


def _auth_redirect() -> ResponseReturnValue:
    if _wants_json_response():
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    return redirect(url_for("auth.home"))


#: Why a request was refused. Carried to the no-permission page so it can say
#: something useful instead of the generic "you don't have permission" — a
#: disabled module is usually a lapsed subscription, which the user can fix
#: themselves, while a real permission denial is not.
DENIAL_MODULE_INACTIVE = "module_inactive"


def _forbidden(
    message: str, entity_id: str | None = None, *, reason: str | None = None
) -> ResponseReturnValue:
    if _wants_json_response():
        payload: dict[str, str] = {"status": "error", "message": message}
        if reason:
            payload["reason"] = reason
        return jsonify(payload), 403
    # No toast for an inactive module: the no-permission page renders its own
    # "Module not active" copy for that case, so flashing here would say the
    # same thing twice — once permanently, once for three seconds. Real
    # permission denials still need the toast; the page only has generic copy
    # for them. JSON callers get ``message`` either way.
    if reason != DENIAL_MODULE_INACTIVE:
        flash(message, "danger")
    target_kwargs = {"entity_id": entity_id} if entity_id else {}
    if reason:
        target_kwargs["reason"] = reason
    return redirect(url_for("auth.no_permission", **target_kwargs))


def permission_denied(
    message: str, *, entity_id: str | None = None, reason: str | None = None
) -> ResponseReturnValue:
    return _forbidden(message, entity_id=entity_id, reason=reason)


def _bad_request(message: str) -> ResponseReturnValue:
    if _wants_json_response():
        return jsonify({"status": "error", "message": message}), 400
    flash(message, "warning")
    return redirect(url_for("auth.index"))


def _extract_entity_id(
    kwargs: dict[str, Any],
    *,
    entity_arg: str | None,
    entity_keys: Iterable[str] | None,
) -> str | None:
    if entity_arg and kwargs.get(entity_arg):
        return str(kwargs[entity_arg])

    request_keys = tuple(entity_keys or ("entity_id", "org_id"))
    for key in request_keys:
        if kwargs.get(key):
            return str(kwargs[key])

    for key in request_keys:
        value = request.args.get(key) or request.form.get(key)
        if value:
            return str(value)

    json_payload = request.get_json(silent=True) or {}
    for key in request_keys:
        value = json_payload.get(key)
        if value:
            return str(value)

    return None


def extract_entity_id(
    *,
    kwargs: dict[str, Any] | None = None,
    entity_arg: str | None = None,
    entity_keys: Iterable[str] | None = None,
) -> str | None:
    return _extract_entity_id(
        kwargs or {},
        entity_arg=entity_arg,
        entity_keys=entity_keys,
    )


def require_entity_access(
    *,
    entity_arg: str | None = None,
    entity_keys: Iterable[str] | None = None,
    message: str = "Hmm, it looks like you don't have permission to look there.",
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                return _auth_redirect()

            entity_id = _extract_entity_id(
                kwargs, entity_arg=entity_arg, entity_keys=entity_keys
            )
            if not entity_id:
                return _bad_request(
                    "I need to know which entity we're working with first!"
                )

            if not has_entity_access(current_user, entity_id):
                return _forbidden(message, entity_id=entity_id)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_module(
    module_code: str,
    *,
    entity_arg: str | None = None,
    entity_keys: Iterable[str] | None = None,
    message: str | None = None,
):
    """Block access to a route unless the entity has ``module_code`` activated.

    Resolves the entity from the route/request the same way the other guards
    do, then checks the per-entity module state (entity_function_map, falling
    back to the catalog default). A disabled module is treated like a missing
    permission: JSON 403 for API/XHR callers, otherwise a flash + redirect to
    the no-permission page.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                return _auth_redirect()

            entity_id = _extract_entity_id(
                kwargs, entity_arg=entity_arg, entity_keys=entity_keys
            )
            if not entity_id:
                return _bad_request(
                    "I need to know which entity we're working with first!"
                )

            # Lazy import: the resolver lives in the entity blueprint, which
            # imports this module — importing at call time avoids the cycle.
            from blueprints.entity.routes.modules import _is_module_enabled

            if not _is_module_enabled(entity_id, module_code):
                msg = message or "This module is not activated for this entity."
                return _forbidden(
                    msg, entity_id=entity_id, reason=DENIAL_MODULE_INACTIVE
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(
    permission: Permission,
    *,
    entity_arg: str | None = None,
    entity_keys: Iterable[str] | None = None,
    message: str = "Not authorized",
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                return _auth_redirect()

            entity_id = _extract_entity_id(
                kwargs, entity_arg=entity_arg, entity_keys=entity_keys
            )
            if not has_permission(current_user, permission, entity_id=entity_id):
                return _forbidden(message, entity_id=entity_id)
            return func(*args, **kwargs)

        return wrapper

    return decorator

