"""User-invite service helpers for the onboarding app.

Token-authenticated wrappers around the invitation blueprint so the onboarding
app (separate origin, Bearer JWT, no session cookie) can send / list / cancel
invitations exactly like the Settings → Users page. Permission and role-rank
checks mirror ``blueprints/invitation/routes/api.py``.
"""

from __future__ import annotations

from blueprints.invitation.models.invitation import Invitation
from loguru import logger

from blueprints.invitation.services.invite import (_is_invitation_expired,
                                                   cancel_invitation,
                                                   create_invitation,
                                                   get_pending_invitations,
                                                   resend_cooldown_remaining,
                                                   resend_invitation,
                                                   send_invitation_email)
from blueprints.shared.email_rules import invite_address_error
from models.db import User
from services.permission_policy import (Permission,
                                        can_manage_role_assignment_for_entity,
                                        has_permission_by_user_id)

# Roles selectable in the onboarding invite step, mirroring the Settings
# dropdown which excludes entity_base and super_admin.
_ASSIGNABLE_ROLES = {"cashier", "shop_manager", "accountant", "admin"}


def _normalize_role(name: str) -> str:
    if not name:
        return ""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _invite_payload(inv: Invitation) -> dict:
    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "status": inv.status,
        "first_name": inv.first_name or "",
        "last_name": inv.last_name or "",
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        # Step 3 shows when each invite lapses, and that a lapsed one needs Resend. A row
        # with no expires_at (older invitations) never expires.
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "expired": _is_invitation_expired(inv),
    }


def send_invite(user_id, entity_id, email, role, first_name="", last_name=""):
    """Create and email an invitation for the onboarding entity."""
    if not has_permission_by_user_id(user_id, Permission.USER_INVITE, entity_id):
        return {"error": "You do not have permission to invite users to this entity."}, 403

    email = (email or "").strip().lower()
    role = _normalize_role(role)
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if not email or not role:
        return {"error": "email and role are required."}, 400
    address_error = invite_address_error(email)
    if address_error:
        return {"error": address_error}, 400
    if role not in _ASSIGNABLE_ROLES:
        return {"error": "Invalid role."}, 400

    user = User.query.get(user_id)
    if not can_manage_role_assignment_for_entity(user, role, entity_id):
        return {"error": "You cannot assign a role higher than your own."}, 403

    invitation, error = create_invitation(
        entity_id=entity_id,
        email=email,
        role=role,
        invited_by=user_id,
        first_name=first_name,
        last_name=last_name,
    )
    if error:
        return {"error": error}, 409

    email_sent = send_invitation_email(
        invitation, first_name=first_name, last_name=last_name
    )
    return {
        "status": "success",
        "email_sent": email_sent,
        "invitation": _invite_payload(invitation),
    }, 201


def list_invites(user_id, entity_id):
    """Return the entity's pending invitations."""
    if not has_permission_by_user_id(user_id, Permission.USER_VIEW_ALL, entity_id):
        return {"error": "Access denied"}, 403
    invitations = get_pending_invitations(entity_id)
    return {"invitations": [_invite_payload(inv) for inv in invitations]}, 200


def resend_invite(user_id, invitation_id):
    """Send a pending invitation again, with a fresh link and a fresh expiry (step 3).

    The same two gates as cancel - USER_INVITE on the invitation's company, and a role the
    user may assign - then ``resend_invitation``'s cooldown, answered as 429 with
    ``retry_after`` (seconds) so the wizard can count it down.
    """
    invitation = Invitation.query.get(invitation_id)
    if not invitation:
        return {"error": "Invitation not found."}, 404
    if not has_permission_by_user_id(user_id, Permission.USER_INVITE, invitation.entity_id):
        return {"error": "Not authorized."}, 403
    user = User.query.get(user_id)
    if not can_manage_role_assignment_for_entity(user, invitation.role, invitation.entity_id):
        return {"error": "You cannot resend an invitation for a role equal to or higher than your own."}, 403

    inv, error, retry_after = resend_invitation(invitation.id, actor_id=user_id)
    if error:
        return {"error": error, "retry_after": retry_after}, 429 if retry_after > 0 else 400
    if not send_invitation_email(inv):
        # The token rotated already: the old link is dead and the new one did not go out.
        logger.error(f"onboarding invitation resend: email failed invitation={inv.id}")
        return {"error": "I couldn't send that email just now. Mind trying again in a moment?",
                "retry_after": resend_cooldown_remaining(inv)}, 502
    return {"status": "success", "invitation": _invite_payload(inv),
            "resend_cooldown": resend_cooldown_remaining(inv)}, 200


def cancel_invite(user_id, invitation_id):
    """Cancel a pending invitation the user is allowed to manage."""
    invitation = Invitation.query.get(invitation_id)
    if not invitation:
        return {"error": "Invitation not found."}, 404

    if not has_permission_by_user_id(user_id, Permission.USER_INVITE, invitation.entity_id):
        return {"error": "Not authorized."}, 403

    user = User.query.get(user_id)
    if not can_manage_role_assignment_for_entity(user, invitation.role, invitation.entity_id):
        return {"error": "You cannot cancel an invitation for a role equal to or higher than your own."}, 403

    success, error = cancel_invitation(invitation_id)
    if not success:
        return {"error": error}, 400
    return {"status": "success"}, 200
