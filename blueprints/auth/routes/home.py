import os

from flask import redirect, render_template, url_for
from flask_login import current_user

from blueprints.auth import auth_bp


@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("entity.entity_list"))
    onboarding_base = os.environ.get(
        "ONBOARDING_APP_URL", "http://localhost:3001"
    ).rstrip("/")
    return render_template("login/index.html", onboarding_base=onboarding_base)
