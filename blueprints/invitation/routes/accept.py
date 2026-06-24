import os
from urllib.parse import urlencode

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.invitation import invitation_bp
from blueprints.invitation.models.invitation import Invitation
from blueprints.invitation.services.invite import accept_invitation
from models.db import Entity


@invitation_bp.route("/invitation/accept/<string:token>", methods=["GET"])
def accept_invitation_page(token):
    """Bounce the invite link to the onboarding /auth page.

    The OTP flow on /auth → /auth/confirm proves the invitee's identity via
    the email code, then will eventually call back into accept_invitation()
    with the verified user. Token validity is checked here so an invalid or
    used link doesn't reach the onboarding app at all.
    """
    invitation = Invitation.query.filter_by(token=token, status="pending").first()
    if not invitation:
        logger.info("invitation.accept_link.invalid token=…{}", token[-6:] if token else "")
        flash("This invitation is invalid or has already been used.", "warning")
        return redirect(url_for("auth.home"))

    logger.info(
        "invitation.accept_link.opened invitation={} entity={} email={}",
        invitation.id, invitation.entity_id, invitation.email,
    )

    onboarding_base = os.environ.get("ONBOARDING_APP_URL", "http://localhost:3001").rstrip("/")
    params = {"invite": token, "email": invitation.email}
    fn = (request.args.get("fn") or "").strip()
    ln = (request.args.get("ln") or "").strip()
    if fn:
        params["fn"] = fn
    if ln:
        params["ln"] = ln
    return redirect(f"{onboarding_base}/auth?{urlencode(params)}")


@invitation_bp.route("/invitation/xero-not-connected/<string:entity_id>", methods=["GET"])
@login_required
def xero_not_connected(entity_id):
    """Page shown when user is added to Minty but not invited to Xero org."""
    entity = Entity.query.get(entity_id)
    if not entity:
        flash("Entity not found.", "danger")
        return redirect(url_for("entity.entity_list"))

    entity_name = entity.name or "Unknown"
    entity_acronym = "".join(w[0].upper() for w in entity_name.split() if w)

    return render_template(
        "invitation/xero_not_connected.html",
        entity_name=entity_name,
        entity_acronym=entity_acronym,
        entity_id=entity_id,
    )
