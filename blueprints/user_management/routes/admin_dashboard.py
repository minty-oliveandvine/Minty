from flask import render_template
from flask_login import current_user, login_required

from blueprints.user_management import user_management_bp
from blueprints.user_management.services.access_guards import require_superuser
from models.db import User, UserEntity


def _build_membership_summary_by_user(user_ids: list[str]) -> dict[str, str]:
    memberships = UserEntity.query.filter(UserEntity.user_id.in_(user_ids)).all()
    summary_by_user: dict[str, list[str]] = {}
    for membership in memberships:
        summary_by_user.setdefault(membership.user_id, []).append(
            f"{membership.entity_id} ({membership.role})"
        )
    return {
        user_id: ", ".join(sorted(entries)) if entries else "No memberships"
        for user_id, entries in summary_by_user.items()
    }


@user_management_bp.route("/admin_dashboard", methods=["GET"])
@login_required
def admin_dashboard():
    denied = require_superuser("auth.index", user=current_user, user_model=User)
    if denied is not None:
        return denied
    pending_users = User.query.filter_by(approved=False).all()
    approved_users = User.query.filter_by(approved=True).all()
    membership_summary_by_user = _build_membership_summary_by_user(
        [user.id for user in [*pending_users, *approved_users]]
    )
    return render_template(
        "admin_dashboard.html",
        pending_users=pending_users,
        approved_users=approved_users,
        membership_summary_by_user=membership_summary_by_user,
        super_admin=(current_user.system_role == User.SYSTEM_ROLE_SUPERUSER),
    )
