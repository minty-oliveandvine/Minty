from flask import redirect

from blueprints.auth import auth_bp
from blueprints.auth.services.hub_login import hub_login_url


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Sign-up is minty-web's ``/signup`` (its own route since 2026-10-09; it was
    ``/login?mode=signup`` from phase 2, 2026-10-05): the account
    is still made here, by ``POST /auth/email/verify-code`` once the emailed code is
    confirmed. Nothing is created on this route - it only forwards old links and bookmarks."""
    return redirect(hub_login_url(mode="signup"))
