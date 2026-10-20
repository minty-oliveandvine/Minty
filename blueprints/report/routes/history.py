"""Report history routes."""

from flask import redirect, request
from flask_login import login_required

from blueprints.entity.routes.modules import petty_cash_web_handoff_url
from blueprints.report import report_bp
from services.authz import require_entity_access


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports", methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
def entity_report_history(entity_id):
    # As the dashboard (entity.report_dashboard): minty-petty-cash-web's history, its filters kept.
    return redirect(petty_cash_web_handoff_url(entity_id, "/reports", request.query_string.decode()))
