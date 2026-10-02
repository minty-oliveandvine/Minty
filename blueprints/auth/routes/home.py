from flask import redirect, render_template, url_for
from flask_login import current_user

from blueprints.auth import auth_bp
from blueprints.shared import bearer_api


@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("entity.entity_list"))
    onboarding_base = bearer_api.onboarding_origin()
    return render_template("login/index.html", onboarding_base=onboarding_base)
