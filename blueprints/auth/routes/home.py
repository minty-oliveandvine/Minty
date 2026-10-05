from flask import jsonify, redirect, request, url_for
from flask_login import current_user

from blueprints.auth import auth_bp
from blueprints.auth.services.hub_login import hub_login_url
from blueprints.entity.services.entity_list import read_notices


@auth_bp.route("/")
def home():
    """Flask-Login's ``login_view``. Signed in: the entity list. Otherwise the sign-in page,
    which is minty-web's since phase 2 (2026-10-05) - with ``next`` (where ``login_required``
    was sending the person) and anything flashed on the way."""
    if current_user.is_authenticated:
        return redirect(url_for("entity.entity_list"))
    return redirect(hub_login_url(next_path=request.args.get("next")))


@auth_bp.route("/auth/notices")
def auth_notices():
    """The messages a redirect to the sign-in page carried (``?flash=``, signed and short-lived
    - ``hub_login_url``). Public: the page asking has nobody signed in yet, and a forged or
    expired value reads as nothing."""
    return jsonify({"notices": read_notices(request.args.get("flash"))})
