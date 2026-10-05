# Token endpoints: mytoken, event_id, check_token, refresh_token.
from flask import current_app, flash, jsonify
from flask_login import current_user, login_required
from loguru import logger

from blueprints.auth import auth_bp
from services.auth.token_service import ensure_valid_token


@auth_bp.route("/check/token", methods=["GET"])
@login_required
def check_token():
    response = ensure_valid_token(current_user)
    if response:
        return "Valid Token"
    return "expired_token"


@auth_bp.route("/refresh_token", methods=["POST"])
@login_required
def refresh_user_token():
    try:
        if ensure_valid_token(current_user):
            flash("Your Xero connection is refreshed.", "success")
            return jsonify(
                {"status": "success", "message": "Token refreshed successfully"}
            )
        # ensure_valid_token returning falsy means Xero refused to renew the
        # session — an expired or already-used refresh token. It is not a
        # timeout, and retrying will not help: only reconnecting will.
        flash(
            "Xero wouldn't renew your session, so I've lost access to your "
            "Xero data. Mind reconnecting to Xero to get it back?",
            "danger",
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Xero wouldn't renew your session. Mind reconnecting to Xero?",
                }
            ),
            401,
        )
    except Exception as e:
        logger.error("Error refreshing user token: %s", str(e))
        flash(
            "That didn't quite work! One more try to get things back in order?",
            "danger",
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end. Mind trying again?",
                }
            ),
            500,
        )
