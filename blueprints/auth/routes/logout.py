from flask import current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_required, logout_user
from loguru import logger

from blueprints.auth import auth_bp
from services.auth.token_service import xero_logout_url


@auth_bp.route("/logout")
@login_required
def logout():
    from flask import get_flashed_messages

    get_flashed_messages()

    reason = request.args.get("reason")

    # Build the Xero end-session URL while we still have the user's id_token,
    # so logging out of Minty also ends their Xero SSO session. This only ends
    # the browser session at Xero — it does NOT revoke tokens or disconnect any
    # entity. Returns None for password-only users with no Xero session.
    xero_url = None
    try:
        xero_url = xero_logout_url(
            current_user,
            post_logout_redirect_uri=url_for("auth.home", _external=True),
        )
    except Exception:
        logger.exception("Logout: failed to build Xero logout URL")

    session["token"] = None
    session.pop("last_activity", None)
    logout_user()

    if reason == "idle":
        mins = int(current_app.config.get("IDLE_TIMEOUT_SECONDS", 1800) // 60)
        flash(
            f"You have been logged out after {mins} minutes of inactivity.",
            "warning",
        )

    # Hand off to Xero to end its session; Xero redirects back to auth.home.
    if xero_url:
        return redirect(xero_url)
    return redirect(url_for("auth.home"))
