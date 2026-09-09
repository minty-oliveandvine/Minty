"""GET /capture — the Draft Queue page.

The bubble is a launcher: a drop zone, a badge, and the last three uploads.
The reviewing happens here, on a real page, because a queue with editable
amount, supplier, account code and date fields is painful in a 340px panel in
the corner of the screen.

BUILD ORDER NOTE
This is the step-2 shell: it renders, it proves the gate and the permission
check work end to end, and it shows an honest empty state. The cards, the
filters and the confirm actions arrive at step 11, once there are drafts for
them to show.
"""

from __future__ import annotations

from flask import render_template
from flask_login import current_user, login_required

from blueprints.capture import capture_bp
from blueprints.capture.routes.module_guard import current_entity_id
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@capture_bp.route("/capture", methods=["GET"])
@login_required
def capture_queue():
    entity_id = current_entity_id()

    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You don't have permission to use the AI Hub here.",
            entity_id=entity_id,
        )

    from blueprints.entity.models.entity import Entity

    entity = Entity.query.filter(Entity.id == entity_id).first()

    return render_template(
        "capture/queue.html",
        entity=entity,
        entity_id=entity_id,
        drafts=[],
    )
