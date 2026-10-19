# Report submitted routes; delegates to app implementation.



from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.shared.enums import PublishStatus
from blueprints.xero.services.publish_start import PublishRefused, start_publish
from models.db import Entity, Report, db
from services.authz import require_entity_access, require_permission
from services.permission_policy import (Permission, can_view_report,
                                        has_permission)


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/new/submitted", methods=["GET"])
@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/<string:id>/submitted", methods=["GET"])
@report_bp.route("/report/submitted", methods=["GET"])
@report_bp.route("/report/<string:id>/submitted", methods=["GET"])
@login_required
def report_submitted(id=None, entity_id=None):
    DD_CLIENT_TOKEN = "pub8127bb0367f2b74cbba93dad6f012b90"
    entity_id = entity_id or request.args.get("entity_id")

    # Get the report to check Xero integration status
    report = None
    is_published_to_xero = False
    was_previously_published = False
    transaction_date = None
    if id:
        report = Report.query.filter(Report.id == id).first()
        if not report:
            return jsonify({"status": "error", "message": "Hmm, I couldn't find that report."}), 404
        if not can_view_report(current_user, report):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view this report.",
                    }
                ),
                403,
            )
        entity_id = entity_id or report.company
        is_published_to_xero = report.xero_integrated_yes or False
        # A report edited after a publish has xero_integrated_yes cleared but
        # keeps publishing_status, so it renders as a first-time publish. Xero
        # object IDs are never stored, so that second publish duplicates every
        # transaction rather than updating it -- warn on it like a republish.
        # The column is NOT NULL since the schema redesign ('unpublished' is the
        # never-published state), so "is not None" would warn on every report.
        was_previously_published = report.publishing_status not in (None, PublishStatus.UNPUBLISHED)
        transaction_date = report.transaction_date
    if not entity_id:
        can_publish = False
    else:
        can_publish = has_permission(
            current_user, Permission.REPORT_PUBLISH, entity_id
        )
    if entity_id and not (
        has_permission(current_user, Permission.REPORT_VIEW_ENTITY, entity_id)
        or has_permission(current_user, Permission.REPORT_VIEW_OWN, entity_id)
    ):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "You do not have permission to view submitted reports for this entity.",
                }
            ),
            403,
        )

    # The outcome page (Part 15.12e) draws its facts from the report row; the company for the shell.
    return render_template(
        "report/submitted.html",
        current_user=current_user,
        org=Entity.query.filter(Entity.id == str(entity_id)).first() if entity_id else None,
        report=report,
        id=id,
        entity_id=entity_id,
        is_published_to_xero=is_published_to_xero,
        was_previously_published=was_previously_published,
        transaction_date=transaction_date,
        DD_CLIENT_TOKEN=DD_CLIENT_TOKEN,
        can_publish=can_publish,
    )


@report_bp.route("/report/submitted/publish_to_xero", methods=["POST"])
@login_required
@require_entity_access(entity_keys=("entity_id",))
@require_permission(
    Permission.REPORT_PUBLISH,
    entity_keys=("entity_id",),
    message="You do not have permission to publish reports for this entity.",
)
def report_submitted_publish_to_xero():
    """Start the Xero publish (``xero/services/publish_start.py``, shared with the Petty Cash API):
    202 while the background worker runs, or the refusal with its status."""
    entity_id = request.args.get("entity_id")
    report_id = request.args.get("report_id")
    try:
        start_publish(entity_id, report_id, current_user, current_app._get_current_object())
    except PublishRefused as refused:
        body = {"status": "error", "error": refused.error, "message": refused.message}
        if refused.requires_connection:
            body["requires_connection"] = True
        return jsonify(body), refused.status
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to publish to Xero: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "publish_failed",
                    "message": "I couldn't publish this to Xero. Could you check the connection and try again?",
                }),
            500,
        )
    return (
        jsonify(
            {
                "category": "info",
                "status": "publishing",
                "message": "Xero integration started. Processing in background. This may take a few minutes.",
            }
        ),
        202,  # 202 Accepted - request accepted for processing
    )


# Submitted step: report_submitted transferred from app.py (single
# function, no new functions).
