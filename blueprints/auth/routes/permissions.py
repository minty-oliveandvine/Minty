from flask import render_template, request
from flask_login import current_user, login_required

from blueprints.auth import auth_bp
from models.db import Entity


@auth_bp.route("/no-permission")
@login_required
def no_permission():
    entity_id = request.args.get("entity_id")
    entity_acronym = ""

    if entity_id:
        entity = Entity.query.filter_by(id=entity_id).first()
        if entity and entity.name:
            words = entity.name.split()
            entity_acronym = "".join(word[0].upper() for word in words if word)

    return render_template(
        "entity/entity_no_permission.html",
        entity_id=entity_id,
        entity_acronym=entity_acronym,
        has_complete_xero_settings=False,
    )
