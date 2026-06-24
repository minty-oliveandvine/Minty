from flask import jsonify, request
from flask_login import current_user, login_required
from loguru import logger

from blueprints.invitation import invitation_bp
from blueprints.invitation.services.invite import (
    cancel_invitation,
    create_invitation,
    get_pending_invitations,
    resend_cooldown_remaining,
    resend_invitation,
    send_invitation_email,
)
from services.authz import require_entity_access, require_permission
from services.permission_policy import (
    Permission,
    can_manage_role_assignment_for_entity,
)


@invitation_bp.route("/minty/api/invitation/send", methods=["POST"])
@login_required
@require_permission(
    Permission.USER_INVITE,
    entity_keys=("entity_id",),
    message="You do not have permission to invite users to this entity.",
)
def send_invitation():
    data = request.get_json(silent=True) or {}

    entity_id = data.get("entity_id")
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    if not entity_id or not email or not role:
        logger.info(
            "invitation.send.invalid actor={} entity={} email={} role={}",
            current_user.id, entity_id, email, role,
        )
        return jsonify({"status": "error", "message": "entity_id, email, and role are required."}), 400

    if not can_manage_role_assignment_for_entity(current_user, role, entity_id):
        logger.warning(
            "invitation.send.denied actor={} entity={} email={} role={} reason=role_above_actor",
            current_user.id, entity_id, email, role,
        )
        return jsonify({"status": "error", "message": "You cannot assign a role higher than your own."}), 403

    invitation, error = create_invitation(
        entity_id=entity_id,
        email=email,
        role=role,
        invited_by=current_user.id,
        first_name=first_name,
        last_name=last_name,
    )
    if error:
        logger.info(
            "invitation.send.rejected actor={} entity={} email={} role={} reason={!r}",
            current_user.id, entity_id, email, role, error,
        )
        return jsonify({"status": "error", "message": error}), 409

    email_sent = send_invitation_email(
        invitation,
        first_name=first_name,
        last_name=last_name,
    )

    logger.info(
        "invitation.send.ok actor={} entity={} invitation={} email={} role={} email_sent={}",
        current_user.id, entity_id, invitation.id, email, role, email_sent,
    )

    return jsonify({
        "status": "success",
        "message": "Invitation sent successfully." if email_sent else "Invitation created but email delivery failed.",
        "invitation": {
            "id": invitation.id,
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "email_sent": email_sent,
        },
    }), 201


@invitation_bp.route("/minty/api/invitation/<string:entity_id>/pending", methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.USER_VIEW_ALL,
    entity_arg="entity_id",
    message="You do not have permission to view invitations.",
)
def list_pending(entity_id):
    invitations = get_pending_invitations(entity_id)
    return jsonify({
        "status": "success",
        "invitations": [
            {
                "id": inv.id,
                "email": inv.email,
                "role": inv.role,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "resend_cooldown": resend_cooldown_remaining(inv),
            }
            for inv in invitations
        ],
    })


@invitation_bp.route("/minty/api/invitation/<string:invitation_id>/cancel", methods=["POST"])
@login_required
def cancel_invite(invitation_id):
    from blueprints.invitation.models.invitation import Invitation

    invitation = Invitation.query.get(invitation_id)
    if not invitation:
        logger.info(
            "invitation.cancel.not_found actor={} invitation={}",
            current_user.id, invitation_id,
        )
        return jsonify({"status": "error", "message": "Invitation not found."}), 404

    from services.permission_policy import can_manage_role_assignment_for_entity, has_permission

    if not has_permission(current_user, Permission.USER_INVITE, invitation.entity_id):
        logger.warning(
            "invitation.cancel.denied actor={} entity={} invitation={} reason=no_permission",
            current_user.id, invitation.entity_id, invitation_id,
        )
        return jsonify({"status": "error", "message": "Not authorized."}), 403

    if not can_manage_role_assignment_for_entity(current_user, invitation.role, invitation.entity_id):
        logger.warning(
            "invitation.cancel.denied actor={} entity={} invitation={} role={} reason=role_above_actor",
            current_user.id, invitation.entity_id, invitation_id, invitation.role,
        )
        return jsonify({"status": "error", "message": "You cannot cancel an invitation for a role equal to or higher than your own."}), 403

    success, error = cancel_invitation(invitation_id)
    if not success:
        logger.info(
            "invitation.cancel.rejected actor={} entity={} invitation={} reason={!r}",
            current_user.id, invitation.entity_id, invitation_id, error,
        )
        return jsonify({"status": "error", "message": error}), 400

    logger.info(
        "invitation.cancel.ok actor={} entity={} invitation={} email={}",
        current_user.id, invitation.entity_id, invitation_id, invitation.email,
    )
    return jsonify({"status": "success", "message": "Invitation cancelled."})


@invitation_bp.route("/minty/api/invitation/<string:invitation_id>/resend", methods=["POST"])
@login_required
def resend_invite(invitation_id):
    from blueprints.invitation.models.invitation import Invitation

    invitation = Invitation.query.get(invitation_id)
    if not invitation:
        logger.info(
            "invitation.resend.not_found actor={} invitation={}",
            current_user.id, invitation_id,
        )
        return jsonify({"status": "error", "message": "Invitation not found."}), 404

    from services.permission_policy import can_manage_role_assignment_for_entity, has_permission

    if not has_permission(current_user, Permission.USER_INVITE, invitation.entity_id):
        logger.warning(
            "invitation.resend.denied actor={} entity={} invitation={} reason=no_permission",
            current_user.id, invitation.entity_id, invitation_id,
        )
        return jsonify({"status": "error", "message": "Not authorized."}), 403

    if not can_manage_role_assignment_for_entity(current_user, invitation.role, invitation.entity_id):
        logger.warning(
            "invitation.resend.denied actor={} entity={} invitation={} role={} reason=role_above_actor",
            current_user.id, invitation.entity_id, invitation_id, invitation.role,
        )
        return jsonify({"status": "error", "message": "You cannot resend an invitation for a role equal to or higher than your own."}), 403

    entity_id = invitation.entity_id
    invitation, error, retry_after = resend_invitation(invitation_id, actor_id=current_user.id)
    if error:
        # A live cooldown (retry_after > 0) is a rate-limit, not a bad request.
        status_code = 429 if retry_after > 0 else 400
        logger.info(
            "invitation.resend.rejected actor={} entity={} invitation={} retry_after={} reason={!r}",
            current_user.id, entity_id, invitation_id, retry_after, error,
        )
        return jsonify({
            "status": "error",
            "message": error,
            "retry_after": retry_after,
        }), status_code

    email_sent = send_invitation_email(invitation)

    logger.info(
        "invitation.resend.ok actor={} entity={} invitation={} email={} role={} email_sent={}",
        current_user.id, entity_id, invitation.id, invitation.email, invitation.role, email_sent,
    )

    return jsonify({
        "status": "success" if email_sent else "error",
        "message": "Invitation resent successfully." if email_sent else "Failed to resend invitation email.",
        "email_sent": email_sent,
        "resend_cooldown": resend_cooldown_remaining(invitation),
    }), 200 if email_sent else 502
