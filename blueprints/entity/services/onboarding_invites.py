"""User-invite service helpers for the onboarding app.

Token-authenticated wrappers around the invitation blueprint so the onboarding
app (separate origin, Bearer JWT, no session cookie) can send / list / cancel
invitations exactly like the Settings → Users page. Permission and role-rank
checks mirror ``blueprints/invitation/routes/api.py``.
"""

from __future__ import annotations

from blueprints.invitation.models.invitation import Invitation
from blueprints.invitation.services.invite import (cancel_invitation,
                                                   create_invitation,
                                                   get_pending_invitations,
                                                   send_invitation_email)
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
