"""Consent history lookup — "what did this person actually agree to, and when?"

The one question the consent table exists to answer, exposed so it can be
answered without database access.

Unlike the rest of this blueprint, these routes ARE behind the acceptance gate.
They are product functionality, not part of the acceptance flow — an
administrator who has not agreed to the Terms meets the gate here like anywhere
else.
"""

from flask import jsonify
from flask_login import current_user, login_required

from blueprints.legal import legal_bp
from blueprints.legal.services.consent import consents_for_user
from models.db import UserEntity
from services.permission_policy import Permission, has_permission


def _may_view_consents(target_user_id: str) -> bool:
    """Whether the caller may see `target_user_id`'s agreements.

    Two ways to qualify:

      * it is your own history — you can always see what you agreed to;
      * you hold USER_VIEW_ALL in an entity the target belongs to, which is the
        same permission that governs looking at users elsewhere in the app.

    Deliberately NOT superuser-only: the people who need this are the admins of
    the business the person belongs to.
    """
    if target_user_id == current_user.id:
        return True

    memberships = UserEntity.query.filter_by(
        user_id=target_user_id, approved=True
    ).all()
    return any(
        has_permission(current_user, Permission.USER_VIEW_ALL, membership.entity_id)
        for membership in memberships
    )


@legal_bp.route("/minty/api/users/<user_id>/consents", methods=["GET"])
@login_required
def user_consents(user_id):
    if not _may_view_consents(user_id):
        # 403 rather than 404: the caller knows the id they asked for, so
        # pretending it does not exist buys nothing and misleads the honest.
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "You do not have permission to view this.",
                }
            ),
            403,
        )

    return jsonify(
        {
            "user_id": user_id,
            "consents": [
                {
                    "terms_version": row.terms_version,
                    # ISO 8601 with offset — the timestamp is stored timezone
                    # aware precisely so this is unambiguous.
                    "accepted_at": (
                        row.accepted_at.isoformat() if row.accepted_at else None
                    ),
                    "source": row.source,
                    # Included so the record can be checked against the document
                    # itself: the fingerprint shown at the foot of
                    # /legal/terms/<version> must match.
                    "document_hash": row.document_hash,
                }
                for row in consents_for_user(user_id)
            ],
        }
    )
