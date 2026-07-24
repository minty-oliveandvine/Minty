from __future__ import annotations

from flask import Response, jsonify
from flask_login import current_user

from models.db import UserEntity
from models.user_management import Roles
from services.permission_policy import can_manage_role_assignment_for_entity


def get_all_roles():
    return Roles.query.all()


def find_membership_or_error(
    user_id: str, entity_id: str, *, model: type[UserEntity] | None = None
) -> tuple[UserEntity | None, tuple[Response, int] | None]:
    """Look up a user's membership on an entity.

    Returns ``(membership, None)`` on success, or ``(None, error_response)``
    with a 404 JSON body when no membership exists.

    ``model`` lets callers pass their own module-level ``UserEntity`` binding so
    it stays the object tests patch on the calling module.
    """
    membership_model = model if model is not None else UserEntity
    membership = membership_model.query.filter_by(
        user_id=user_id, entity_id=entity_id
    ).first()
    if not membership:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't find that person on this entity.",
                }
            ),
            404,
        )
    return membership, None


def check_role_assignment_or_error(
    role: str, entity_id: str, *, user=None, policy=None
) -> tuple[Response, int] | None:
    """Ensure the current user may assign ``role`` on ``entity_id``.

    Returns ``None`` when allowed, otherwise a 403 JSON error response.
    """
    actor = user if user is not None else current_user
    check = policy if policy is not None else can_manage_role_assignment_for_entity
    if not check(actor, role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I can't let you give someone a role above your own.",
                }
            ),
            403,
        )
    return None


def check_can_manage_membership_or_error(
    membership_role: str, entity_id: str, *, user=None, policy=None
) -> tuple[Response, int] | None:
    """Ensure the current user outranks ``membership_role`` on ``entity_id``.

    Returns ``None`` when allowed, otherwise a 403 JSON error response.
    """
    actor = user if user is not None else current_user
    check = policy if policy is not None else can_manage_role_assignment_for_entity
    if not check(actor, membership_role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "I can't let you manage someone whose role matches "
                        "or outranks your own."
                    ),
                }
            ),
            403,
        )
    return None
