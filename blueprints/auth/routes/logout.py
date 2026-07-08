from flask import redirect, session, url_for
from flask_login import login_required, logout_user

from blueprints.auth import auth_bp


@auth_bp.route("/logout")
@login_required
def logout():
    from flask import get_flashed_messages

    get_flashed_messages()
    session["token"] = None
    session.pop("last_activity", None)
    logout_user()
    return redirect(url_for("auth.home"))
