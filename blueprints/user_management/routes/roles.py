from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required, logout_user

from blueprints.user_management import user_management_bp
from blueprints.user_management.services.roles import (
    check_not_subscription_payer_anywhere_or_error,
)
from models.db import UserEntity, db


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
