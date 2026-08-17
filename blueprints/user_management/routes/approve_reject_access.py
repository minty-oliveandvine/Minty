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

    # Same refusal as ``check_not_subscription_payer_anywhere_or_error``, spelled out
    # here because this route answers in flashes rather than JSON. Deactivating a payer
    # leaves ``payer_user_id`` pointing at someone who can no longer sign in, while the
    # renewals keep charging their card and no remaining admin may stop them.
    #
    # Refused even for a superuser: the resulting state cannot be repaired from inside
    # the app by anyone, so "staff may override" would only mean staff may create it.
    # The way through is to move the subscription first, which is now a supported act.
    from blueprints.subscription.services import store as sub_store

    paying_for = sub_store.entities_paid_for_by(user.id)
    if paying_for:
        names = ", ".join(name for _entity_id, name in paying_for)
        flash(
            f"I can't deactivate {user.username} while they're paying for {names}. "
            "Move the subscription to another admin first.",
            "warning",
        )
        return redirect(url_for("user_management.admin_dashboard"))

    user.approved = False
    db.session.commit()
    flash(f"I've rejected {user.username} and deactivated the account.", "warning")
    return redirect(url_for("user_management.admin_dashboard"))
