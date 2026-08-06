from flask import render_template, request, url_for
from flask_login import current_user, login_required

from blueprints.auth import auth_bp
from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity
from services.authz import DENIAL_MODULE_INACTIVE
from services.permission_policy import (Permission, has_entity_access,
                                        has_permission)


@auth_bp.route("/no-permission")
@login_required
def no_permission():
    entity_id = request.args.get("entity_id")
    entity_acronym = ""

    # Anyone can type ?reason= into the URL, so only values the guards actually
    # emit are allowed to change what the page claims happened.
    reason = request.args.get("reason")
    module_inactive = reason == DENIAL_MODULE_INACTIVE

    if entity_id:
        entity = Entity.query.filter_by(id=entity_id).first()
        if entity and entity.name:
            entity_acronym = build_entity_acronym(entity.name)

    # Offer the module/subscription page only when the user could actually open
    # it. Gating on MODULE_VIEW matters: entity_settings_module is guarded by
    # it, so an unqualified link would bounce the user straight back here.
    subscription_settings_url = None
    if entity_id and has_entity_access(current_user, entity_id) and has_permission(
        current_user, Permission.MODULE_VIEW, entity_id
    ):
        subscription_settings_url = url_for(
            "entity.entity_settings_module", org_id=entity_id
        )

    return render_template(
        "entity/entity_no_permission.html",
        entity_id=entity_id,
        entity_acronym=entity_acronym,
        module_inactive=module_inactive,
        subscription_settings_url=subscription_settings_url,
        has_complete_xero_settings=False,
    )
