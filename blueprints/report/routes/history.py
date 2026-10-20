"""Report history routes."""

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from blueprints.entity.routes.modules import petty_cash_web_handoff_url
from blueprints.entity.services.shared import check_user_has_entities
from blueprints.report import report_bp
from blueprints.report.services.history_query import STATUS_FILTERS, get_entity_report_history
from blueprints.shared import bearer_api
from models.db import Entity
from services.authz import require_entity_access
from services.permission_policy import Permission, has_permission


PER_PAGE = (10, 25, 50, 100)


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports", methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
def entity_report_history(entity_id):
    # As the dashboard (entity.report_dashboard): with minty-petty-cash-web set, its history.
    if bearer_api.petty_cash_web_is_set():
        return redirect(petty_cash_web_handoff_url(entity_id, "/reports", request.query_string.decode()))

    can_view_entity_history = True

    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you your report history.",
            "info",
        )
        return redirect(url_for("entity.entity_list"))

    can_edit_entity_reports = has_permission(
        current_user, Permission.REPORT_EDIT_ENTITY, entity_id
    )
    can_delete_entity_reports = has_permission(
        current_user, Permission.REPORT_DELETE_ENTITY, entity_id
    )
    can_publish = has_permission(
        current_user, Permission.REPORT_PUBLISH, entity_id
    )

    start_date = request.args.get("start_date") or ""
    end_date = request.args.get("end_date") or ""
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    report_id = request.args.get("report_id")
    # Rows per page (Part 14 Pagination: 10/25/50/100) and the status chip, both in the URL.
    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in PER_PAGE:
        per_page = 10
    status = request.args.get("status") or None
    if status not in STATUS_FILTERS:
        status = None

    try:
        report_data = get_entity_report_history(
            entity_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            report_id=report_id,
            per_page=per_page,
            uploaded_by=None if can_view_entity_history else current_user.username,
            status=status,
        )
    except ValueError:
        # The detail belongs in the log, not in the body the client renders.
        current_app.logger.exception(
            "Report history query failed for entity %s", entity_id
        )
        return {
            "status": "error",
            "message": "I couldn't load your report history. Mind trying again?",
        }, 400

    return render_template(
        "report_history/report_history.html",
        report_history=report_data["report_history"],
        entity_id=entity_id,
        entity_name=Entity.query.with_entities(Entity.name).filter(Entity.id == entity_id).scalar() or "",
        latest_transaction_date=report_data["latest_transaction_date"],
        latest_report_id=report_data["latest_report_id"],
        today_date=report_data["today_date"],
        entity_acronym=report_data["entity_acronym"],
        display_date=report_data["display_date"],
        page=report_data["page"],
        total_pages=report_data["total_pages"],
        total_count=report_data["total_count"],
        start_date=start_date,
        end_date=end_date,
        can_edit_entity_reports=can_edit_entity_reports,
        can_delete_entity_reports=can_delete_entity_reports,
        can_publish=can_publish,
        per_page=per_page,
        per_page_choices=PER_PAGE,
        status=status,
    )
