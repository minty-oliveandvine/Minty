from flask import render_template, request
from flask_login import login_required

from blueprints.auth import auth_bp
from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity


@auth_bp.route("/no-permission")
@login_required
def no_permission():
    entity_id = request.args.get("entity_id")
    entity_acronym = ""

    if entity_id:
        entity = Entity.query.filter_by(id=entity_id).first()
        if entity and entity.name:
            entity_acronym = build_entity_acronym(entity.name)

    return render_template(
        "entity/entity_no_permission.html",
        entity_id=entity_id,
        entity_acronym=entity_acronym,
        has_complete_xero_settings=False,
    )
