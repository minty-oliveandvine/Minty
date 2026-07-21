from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from blueprints.user_management import user_management_bp
from models.db import User, db


@user_management_bp.route("/approve_user/<string:user_id>", methods=["POST"])
@login_required
def approve_user(user_id):
    if current_user.system_role != User.SYSTEM_ROLE_SUPERUSER:
        flash("Only Super Admins can approve users.", "danger")
        return redirect(url_for("user_management.admin_dashboard"))
    user = User.query.get_or_404(user_id)
    user.approved = True
    db.session.commit()
    flash(f"User {user.username} approved successfully.", "success")
    return redirect(url_for("user_management.admin_dashboard"))


@user_management_bp.route("/reject_user/<string:user_id>", methods=["POST"])
@login_required
def reject_user(user_id):
    if current_user.system_role != User.SYSTEM_ROLE_SUPERUSER:
        flash("Not authorized", "danger")
        return redirect(url_for("user_management.admin_dashboard"))
    user = User.query.get_or_404(user_id)
    user.approved = False
    db.session.commit()
    flash(f"User {user.username} rejected and deactivated.", "warning")
    return redirect(url_for("user_management.admin_dashboard"))


