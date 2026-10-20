from flask import redirect, url_for
from flask_login import login_required

from blueprints.auth import auth_bp


@auth_bp.route("/index")
@login_required
def index():
    """The company list (``entity.entity_list``, minty-web's). Flask's ``?entity_id=`` report list
    page went with its HTML on 2026-10-20; the address stays because Flask's own redirects and old
    links still name it."""
    return redirect(url_for("entity.entity_list"))
