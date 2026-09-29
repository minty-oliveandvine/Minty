from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required, logout_user

from blueprints.user_management import user_management_bp
from blueprints.user_management.services.roles import (
    check_can_manage_membership_or_error,
    check_not_last_admin_or_error,
    check_not_pending_subscriber_or_error,
    check_not_subscription_payer_anywhere_or_error,
    check_not_subscription_payer_or_error,
    check_role_assignment_or_error,
    check_role_change_or_error,
    find_membership_or_error,
)
from models.db import User, UserEntity, db
from services.authz import require_permission
from services.permission_policy import Permission, can_manage_role_assignment_for_entity


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
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I need to know which entity we're working with first!",
                }
            ),
            400,
        )

    membership, error = find_membership_or_error(user_id, entity_id, model=UserEntity)
    if error is not None:
        return error

    target_user = User.query.get(user_id)
    if not target_user:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Hmm, that name doesn't seem to be in my list.",
                }
            ),
            404,
        )

    first_name = payload.get("first_name", "").strip()
    last_name = payload.get("last_name", "").strip()
    new_role = payload.get("role", "").strip().lower()

    if first_name:
        target_user.first_name = first_name
    if last_name:
        target_user.last_name = last_name

    if new_role:
        error = check_role_assignment_or_error(
            new_role,
            entity_id,
            user=current_user,
            policy=can_manage_role_assignment_for_entity,
        )
        if error is not None:
            return error
        error = check_can_manage_membership_or_error(
            membership.role,
            entity_id,
            user=current_user,
            policy=can_manage_role_assignment_for_entity,
        )
        if error is not None:
            return error
        # Losing admin reaches the same broken states removal does, so this route is
        # guarded too — otherwise "demote then delete" walks straight around the DELETE.
        error = check_role_change_or_error(
            membership.role, new_role, user_id, entity_id, model=UserEntity
        )
        if error is not None:
            return error
        membership.role = new_role

    db.session.commit()
    return (
        jsonify(
            {
                "status": "success",
                "message": "User updated successfully.",
                "user": {
                    "id": target_user.id,
                    "first_name": target_user.first_name,
                    "last_name": target_user.last_name,
                    "role": membership.role,
                },
            }
        ),
        200,
    )


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
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I need to know which entity we're working with first!",
                }
            ),
            400,
        )
    if not new_role:
        return (
            jsonify(
                {"status": "error", "message": "I need a role before I can save that."}
            ),
            400,
        )

    membership, error = find_membership_or_error(user_id, entity_id, model=UserEntity)
    if error is not None:
        return error

    error = check_role_assignment_or_error(
        new_role,
        entity_id,
        user=current_user,
        policy=can_manage_role_assignment_for_entity,
    )
    if error is not None:
        return error

    error = check_can_manage_membership_or_error(
        membership.role,
        entity_id,
        user=current_user,
        policy=can_manage_role_assignment_for_entity,
    )
    if error is not None:
        return error

    # The payer must stay an admin, and the last admin must stay an admin — both for the
    # same reason the DELETE refuses them. Self-demotion is the case this was asked for
    # and it needs no special handling: the rule is about the ROLE being given up, so it
    # reads the same whoever is pressing the button.
    error = check_role_change_or_error(
        membership.role, new_role, user_id, entity_id, model=UserEntity
    )
    if error is not None:
        return error

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
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I need to know which entity we're working with first!",
                }
            ),
            400,
        )

    membership, error = find_membership_or_error(user_id, entity_id, model=UserEntity)
    if error is not None:
        return error

    # THREE guards, and none of them was here. Removing a membership was the only
    # destructive action on this table that ran no check beyond the route permission —
    # while ``update_user_role``, which merely CHANGES a role, ran two.
    #
    # Ordered by what each answers: may you act on this person at all, then the two
    # invariants that deleting would break. The payer comes before the last-admin count
    # because it is the more actionable of the two — moving the subscription is a
    # prerequisite either way, and it is the one that costs money while it is wrong.

    # 1. Rank. USER_ROLE_DELETE's floor is ACCOUNTANT, so without this an accountant
    #    could delete an admin outright — an action they cannot perform through the
    #    weaker route of demoting that admin first. Same policy the PATCH uses, so the
    #    two agree about who may touch whom.
    error = check_can_manage_membership_or_error(
        membership.role,
        entity_id,
        user=current_user,
        policy=can_manage_role_assignment_for_entity,
    )
    if error is not None:
        return error

    # 2. The payer's card outlives their membership — see the check for what that
    #    strands. Applies to everyone, self-removal included.
    error = check_not_subscription_payer_or_error(user_id, entity_id)
    if error is not None:
        return error

    # 3. An entity with no admin cannot be administered, and cannot appoint one.
    error = check_not_last_admin_or_error(
        membership.role, user_id, entity_id, model=UserEntity
    )
    if error is not None:
        return error

    # 4. A handover offered TO them is relying on them still being here. Removing them
    #    now would make the accept refuse and cancel the offer, which the outgoing payer
    #    would only notice as an exit that never completes.
    error = check_not_pending_subscriber_or_error(user_id, entity_id)
    if error is not None:
        return error

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
    # Refused while this account still pays for a company. Deactivating leaves every
    # membership row and every ``payer_user_id`` untouched, so without this the account
    # goes dark while the renewals carry on charging its card — and nobody left inside
    # the entity can stop them, because only the payer may manage the subscription.
    # ``check_not_subscription_payer_or_error`` already refuses the same outcome one
    # membership at a time; this closes the account-level door beside it.
    error = check_not_subscription_payer_anywhere_or_error(current_user.id)
    if error:
        return error

    # Data retention policy: keep historical records, deactivate account only.
    current_user.approved = False
    current_user.clear_tokens()
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
    # Saved through the same service as minty-web's My Profile (services/profile.py), so the
    # names are trimmed the same way whichever door they come in by. No email here - that
    # is the profile's, with the rules that keep sign-in and reset pointing at one address.
    from blueprints.user_management.services.profile import ProfileError, update_profile

    payload = request.get_json(silent=True) or {}
    fields = {
        field: payload.get(field)
        for field in ("first_name", "last_name", "user_phone")
        if field in payload
    }

    if not fields:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "No updatable fields provided.",
                }
            ),
            400,
        )

    try:
        update_profile(current_user, **fields)
    except ProfileError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
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
