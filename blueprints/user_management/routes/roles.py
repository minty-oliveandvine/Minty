from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required, logout_user

from blueprints.user_management import user_management_bp
from models.db import User, UserEntity, db
from services.authz import require_permission
from services.permission_policy import (
    Permission,
    can_manage_role_assignment_for_entity,
)


def _resolve_entity_id(payload: dict | None) -> str | None:
    payload = payload or {}
    entity_id = payload.get("entity_id") or payload.get("company_uuid")
    if entity_id:
        return str(entity_id)
    return request.args.get("entity_id") or request.args.get("company_uuid")


@user_management_bp.route("/minty/api/users/<string:user_id>", methods=["PATCH"])
@login_required
@require_permission(
    Permission.USER_ROLE_ASSIGN,
    entity_keys=("entity_id", "company_uuid"),
    message="You do not have permission to edit users for this entity.",
)
def update_user_details(user_id):
    """Update a user's profile details and optionally their role within an entity."""
    payload = request.get_json(silent=True) or {}
    entity_id = _resolve_entity_id(payload)
    if not entity_id:
        return jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}), 400

    membership = UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()
    if not membership:
        return jsonify({"status": "error", "message": "I couldn't find that person on this entity."}), 404

    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({"status": "error", "message": "Hmm, that name doesn't seem to be in my list."}), 404

    first_name = payload.get("first_name", "").strip()
    last_name = payload.get("last_name", "").strip()
    new_role = payload.get("role", "").strip().lower()

    if first_name:
        target_user.first_name = first_name
    if last_name:
        target_user.last_name = last_name

    if new_role:
        if not can_manage_role_assignment_for_entity(current_user, new_role, entity_id):
            return jsonify({"status": "error", "message": "I can't let you give someone a role above your own."}), 403
        if not can_manage_role_assignment_for_entity(current_user, membership.role, entity_id):
            return jsonify({"status": "error", "message": "I can't let you manage someone whose role matches or outranks your own."}), 403
        membership.role = new_role

    db.session.commit()
    return jsonify({
        "status": "success",
        "message": "User updated successfully.",
        "user": {
            "id": target_user.id,
            "first_name": target_user.first_name,
            "last_name": target_user.last_name,
            "role": membership.role,
        },
    }), 200


@user_management_bp.route("/minty/api/users/<string:user_id>/role", methods=["PATCH"])
@login_required
@require_permission(
    Permission.USER_ROLE_ASSIGN,
    entity_keys=("entity_id", "company_uuid"),
    message="You do not have permission to change user roles for this entity.",
)
def update_user_role(user_id):
    payload = request.get_json(silent=True) or {}
    entity_id = _resolve_entity_id(payload)
    new_role = str(payload.get("role") or "").strip().lower()
    if not entity_id:
        return jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}), 400
    if not new_role:
        return jsonify({"status": "error", "message": "I need a role before I can save that."}), 400

    membership = UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()
    if not membership:
        return jsonify({"status": "error", "message": "I couldn't find that person on this entity."}), 404

    if not can_manage_role_assignment_for_entity(current_user, new_role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I can't let you give someone a role above your own.",
                }
            ),
            403,
        )

    if not can_manage_role_assignment_for_entity(current_user, membership.role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I can't let you manage someone whose role matches or outranks your own.",
                }
            ),
            403,
        )

    membership.role = new_role

    db.session.commit()
    return (
        jsonify(
            {
                "status": "success",
                "message": "User role updated successfully.",
                "user_id": user_id,
                "entity_id": entity_id,
                "role": new_role,
            }
        ),
        200,
    )


@user_management_bp.route("/minty/api/users/<string:user_id>/role", methods=["DELETE"])
@login_required
@require_permission(
    Permission.USER_ROLE_DELETE,
    entity_keys=("entity_id", "company_uuid"),
    message="You do not have permission to delete user roles for this entity.",
)
def delete_user_role(user_id):
    payload = request.get_json(silent=True) or {}
    entity_id = _resolve_entity_id(payload)
    if not entity_id:
        return jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}), 400

    membership = UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()
    if not membership:
        return jsonify({"status": "error", "message": "I couldn't find that person on this entity."}), 404

    db.session.delete(membership)
    db.session.commit()
    return (
        jsonify(
            {
                "status": "success",
                "message": "User role deleted successfully.",
                "user_id": user_id,
                "entity_id": entity_id,
            }
        ),
        200,
    )


@user_management_bp.route("/minty/api/users/me", methods=["DELETE"])
@login_required
def deactivate_my_account():
    # Data retention policy: keep historical records, deactivate account only.
    current_user.approved = False
    current_user.access_token = None
    current_user.refresh_token = None
    current_user.id_token = None
    current_user.expires_in = None
    db.session.commit()
    logout_user()
    return (
        jsonify(
            {
                "status": "success",
                "message": "Your account has been deactivated.",
            }
        ),
        200,
    )


@user_management_bp.route("/minty/api/users/me", methods=["PATCH"])
@login_required
def update_my_profile():
    payload = request.get_json(silent=True) or {}
    allowed_fields = ("first_name", "last_name", "user_phone")
    updated = False

    for field in allowed_fields:
        if field in payload:
            setattr(current_user, field, payload.get(field))
            updated = True

    if not updated:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "No updatable fields provided.",
                }
            ),
            400,
        )

    db.session.commit()
    return (
        jsonify(
            {
                "status": "success",
                "message": "Profile updated successfully.",
                "user": {
                    "id": current_user.id,
                    "first_name": current_user.first_name,
                    "last_name": current_user.last_name,
                    "user_phone": current_user.user_phone,
                },
            }
        ),
        200,
    )


@user_management_bp.route("/minty/api/users/me", methods=["GET"])
@login_required
def get_my_profile():
    memberships = UserEntity.query.filter_by(user_id=current_user.id).all()
    return (
        jsonify(
            {
                "status": "success",
                "user": {
                    "id": current_user.id,
                    "email": current_user.email,
                    "username": current_user.username,
                    "first_name": current_user.first_name,
                    "last_name": current_user.last_name,
                    "user_phone": current_user.user_phone,
                    "system_role": current_user.system_role,
                    "approved": current_user.approved,
                },
                "memberships": [
                    {
                        "entity_id": membership.entity_id,
                        "role": membership.role,
                        "approved": membership.approved,
                    }
                    for membership in memberships
                ],
            }
        ),
        200,
    )
