"""Route to record explicit acceptance of the active Terms & Conditions."""

from flask import jsonify, request, session, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.consent import consent_bp
from blueprints.consent.services.consent import (
    get_active_terms_version,
    get_or_create_principal,
    record_acceptance,
)
from pettycash.core.consent_gate import TERMS_OK_SESSION_KEY


@consent_bp.route("/consent/accept", methods=["POST"])
@login_required
def accept_terms():
    data = request.get_json(silent=True) or {}
    if data.get("accepted") is not True:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "You must tick the checkbox to accept the terms.",
                }
            ),
            400,
        )

    terms_version = get_active_terms_version()
    if terms_version is None:
        # Nothing to accept — don't fabricate consent against a missing version.
        return (
            jsonify(
                {"status": "error", "message": "No active terms to accept."}
            ),
            409,
        )

    try:
        principal = get_or_create_principal(current_user.id)
        record_acceptance(
            principal,
            terms_version,
            captured_ip=request.remote_addr or "",
            captured_ua=request.headers.get("User-Agent", ""),
        )
    except Exception:
        logger.exception("consent: failed to record acceptance user=%s", current_user.id)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not record your acceptance. Please try again.",
                }
            ),
            500,
        )

    # Short-circuit the gate for the rest of this session.
    session[TERMS_OK_SESSION_KEY] = terms_version.terms_ver_id

    return jsonify({"status": "success", "redirect_url": url_for("auth.home")})
