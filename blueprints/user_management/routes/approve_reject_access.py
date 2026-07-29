from flask import flash, redirect, url_for
from flask_login import current_user, login_required

from blueprints.user_management import user_management_bp
from blueprints.user_management.services.access_guards import require_superuser
from models.db import User, db


@user_management_bp.route("/approve_user/<string:user_id>", methods=["POST"])
@login_required
def approve_user(user_id):
    denied = require_superuser(
        "user_management.admin_dashboard",
        message="That task is reserved for our Super Admins.",
        user=current_user,
        user_model=User,
    )
    if denied is not None:
        return denied
    user = User.query.get_or_404(user_id)
    user.approved = True
    db.session.commit()
    flash(f"I've approved {user.username}.", "success")
    return redirect(url_for("user_management.admin_dashboard"))


@user_management_bp.route("/reject_user/<string:user_id>", methods=["POST"])
@login_required
def reject_user(user_id):
    denied = require_superuser(
        "user_management.admin_dashboard", user=current_user, user_model=User
    )
    if denied is not None:
        return denied
    user = User.query.get_or_404(user_id)
    user.approved = False
    db.session.commit()
    flash(f"I've rejected {user.username} and deactivated the account.", "warning")
    return redirect(url_for("user_management.admin_dashboard"))
