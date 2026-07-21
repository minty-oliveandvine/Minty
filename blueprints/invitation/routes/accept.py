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
    resume_url = f"{onboarding_base}/auth?{urlencode(params)}"

    # Email-bound acceptance: if a DIFFERENT user is already logged in (their
    # identity doesn't own the invited email), never silently accept under the
    # wrong identity. Log them out of our app session and bounce to /auth to
    # re-authenticate as the invited email.
    #
    # IMPORTANT: imports inside this block are LAZY (inside the function), never
    # at module top, to keep this route module always importable (a failed
    # module-level import would drop the whole invitation blueprint).
    if current_user.is_authenticated:
        from blueprints.auth.services.identity import normalize_email

        invited_email = normalize_email(invitation.email)
        owned = {
            normalize_email(getattr(current_user, "email", None)),
            normalize_email(getattr(current_user, "xero_email", None)),
            normalize_email(getattr(current_user, "username", None)),
        }
        owned.discard(None)
        if invited_email and invited_email not in owned:
            from flask import session
            from flask_login import logout_user

            logger.warning(
                "invitation.accept_link.session_mismatch invitation={} "
                "invited={} user={}",
                invitation.id, invited_email,
                getattr(current_user, "id", "?"),
            )
            # Clear our app session so the wrong user isn't carried into the
            # accept flow, then bounce to /auth to re-authenticate. The Xero
            # login uses ``prompt=login`` (see xero_auth), so the user can sign
            # in as the correct account even if another Xero session is active —
            # and accept_invitation re-blocks any wrong account regardless.
            session["token"] = None
            session.pop("last_activity", None)
            logout_user()
            flash(
                f"This invitation was sent to {invitation.email}. Please sign "
                f"in as that account to accept it.",
                "warning",
            )
            return redirect(resume_url)

    return redirect(resume_url)


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
