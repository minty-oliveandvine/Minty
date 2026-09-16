# Report submitted routes; delegates to app implementation.


import threading

from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy.exc import OperationalError

from blueprints.report import report_bp
from blueprints.xero.services.publish import (
    process_xero_integration_background, validate_expenses_for_system_accounts)
from blueprints.xero.services.settings import (
    check_entity_xero_settings_complete, sync_entity_xero_status)
from models.db import Entity, Report, User, db
from services.auth.token_service import ensure_valid_token, resolve_xero_token
from services.authz import require_entity_access, require_permission
from services.permission_policy import (Permission, can_view_report,
                                        has_permission)


@report_bp.route("/report/submitted", methods=["GET"])
@report_bp.route("/report/<string:id>/submitted", methods=["GET"])
@login_required
def report_submitted(id=None):
    DD_CLIENT_TOKEN = "pub8127bb0367f2b74cbba93dad6f012b90"
    entity_id = request.args.get("entity_id")

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
        was_previously_published = report.publishing_status is not None
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

    return render_template(
        "report/submitted.html",
        current_user=current_user,
        id=id,
        entity_id=entity_id,
        is_published_to_xero=is_published_to_xero,
        was_previously_published=was_previously_published,
        transaction_date=transaction_date,
        DD_CLIENT_TOKEN=DD_CLIENT_TOKEN,
        can_publish=can_publish,
    )


@report_bp.route("/report/submitted/publish_to_xero", methods=["GET", "POST"])
@login_required
@require_entity_access(entity_keys=("entity_id",))
@require_permission(
    Permission.REPORT_PUBLISH,
    entity_keys=("entity_id",),
    message="You do not have permission to publish reports for this entity.",
)
def report_submitted_publish_to_xero():
    entity_id = request.args.get("entity_id")
    report_id = request.args.get("report_id")
    try:
        entity = None
        if entity_id:
            entity = Entity.query.get_or_404(entity_id)

        # Resolve the Xero token bearer. This MUST go through
        # resolve_xero_token: the authoritative tokens live in the
        # ``user_token`` table, and reading ``User.access_token`` directly
        # yields whatever was written the last time this route refreshed --
        # typically hours stale once any other code path has refreshed. A
        # stale bundle is worse than none: Xero rotates refresh tokens on
        # every use and invalidates the one it was sent, so refreshing with
        # the stale copy spends a token that was already spent, fails, and
        # leaves us publishing with a dead access token that Xero 401s.
        owner_user = resolve_xero_token(entity_id, current_user)
        access_token = owner_user.access_token if owner_user else None
        if owner_user:
            logger.info(
                f"Using {owner_user.username}'s token for publishing "
                f"(current user: {current_user.username})"
            )

        # Legacy tier: resolve_xero_token gives up when a user has no
        # ``user_token`` row (it hydrates from there and bails if absent), but
        # accounts that connected before that table was populated still hold
        # usable tokens in the legacy ``User`` columns and were publishing fine
        # through the old hand-rolled lookup. Preserve that path so this fix
        # doesn't lock them out; ensure_valid_token still refreshes/validates,
        # so no unvalidated token gets through.
        if not access_token:
            for candidate in (
                (
                    User.query.filter(
                        User.id == entity.connected_by_user_id
                    ).first()
                    if entity and entity.connected_by_user_id
                    else None
                ),
                current_user,
            ):
                if candidate is None or not getattr(candidate, "access_token", None):
                    continue
                if ensure_valid_token(candidate):
                    owner_user = candidate
                    access_token = candidate.access_token
                    logger.warning(
                        f"LEGACY_USER_COLUMN_TOKEN entity={entity_id} "
                        f"user={candidate.username} — no usable user_token row; "
                        f"published from legacy User columns. Backfill required."
                    )
                    break

        # No usable token. Do NOT fall back to publishing with an unvalidated
        # one: it cannot succeed, and it turns a clear "reconnect" prompt into
        # an opaque mid-publish rejection.
        if not access_token:
            return (
                jsonify(
                    {
                        "status": "error",
                        "error": "No Xero access token found. Please reconnect to Xero.",
                        "message": "I've lost access to your Xero account. Mind reconnecting it in Settings?",
                        "requires_connection": True,
                    }),
                400,
            )

        if not check_entity_xero_settings_complete(entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "error": "Entity Xero settings are incomplete. Please configure entity settings first.",
                        "message": "Xero settings incomplete. Please configure entity settings first.",
                    }
                ),
                400,
            )

        # Re-sync a status that isn't "connected" before publishing; it may
        # simply be stale. entity_status is onboarding / connected / disconnected
        # (C2); only "disconnected" is worth a warning, "onboarding" is benign.
        if entity.status != "connected":
            if entity.status == "disconnected":
                logger.warning(
                    f"Entity {entity_id} status is '{entity.status}', but attempting to publish with stored tokens"
                )
            try:
                sync_entity_xero_status(entity_id, token_validated=True)
                # Re-check after sync
                entity = Entity.query.get(entity_id)
            except Exception as sync_error:
                logger.warning(
                    f"Status sync failed, proceeding anyway: {str(sync_error)}"
                )

        # Get the specific report by ID if provided, otherwise get the latest
        if report_id:
            posted_report = Report.query.filter_by(
                id=report_id, company=entity_id
            ).first()
        else:
            # This is the SUBMITTED-report view; a draft must never load here.
            posted_report = (
                Report.query.filter(
                    Report.company == entity_id,
                    db.or_(Report.status.is_(None), Report.status != "draft"),
                )
                .order_by(Report.date.desc())
                .first()
            )
        if not posted_report:
            return jsonify({"error": "No report found to publish"}), 404

        logger.info(
            f"Starting Xero integration for report {posted_report.id}, entity {entity_id} (using token from user: {owner_user.username if owner_user else 'unknown'})"
        )
        # Get user info before starting background thread
        # Use owner_user's email for background processing
        if owner_user is None:
            owner_user = current_user
        user_email = owner_user.username
        access_token_to_use = access_token

        # Validate expenses for system account codes before starting background
        # processing
        validation_errors = validate_expenses_for_system_accounts(
            entity_id, posted_report.id, access_token=access_token_to_use
        )

        if validation_errors:
            # Format error message for user display
            if len(validation_errors) == 1:
                error_message = validation_errors[0]["message"]
            else:
                error_list = [
                    f"• {err['expense']} - {err['account_code']}"
                    for err in validation_errors
                ]
                error_message = (
                    "System accounts detected:\n"
                    + "\n".join(error_list)
                    + "\n\nPlease update."
                )

            logger.warning(
                f"Validation failed for report {posted_report.id}: {len(validation_errors)} expense(s) with system account codes"
            )

            return (
                jsonify(
                    {
                        "status": "error",
                        "message": error_message,
                        "error": error_message,
                    }
                ),
                400,  # Bad Request - validation failed
            )

        # Atomic check and lock using SELECT FOR UPDATE to prevent concurrent
        # publishing
        try:
            # Use SELECT FOR UPDATE with nowait to lock the row and fail fast
            # if already locked
            locked_report = (
                db.session.query(Report)
                .filter(Report.id == posted_report.id)
                .with_for_update(nowait=True)
                .first()
            )

            if not locked_report:
                db.session.rollback()
                return jsonify({"error": "Report not found"}), 404

            # Check if already processing
            if locked_report.publishing_status == "processing":
                db.session.rollback()
                logger.warning(
                    f"Report {posted_report.id} is already being processed. Rejecting duplicate request."
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "This report is already being published. Please wait for the current process to complete.",
                            "message": "Publishing already in progress. Please wait...",
                        }
                    ),
                    409,  # 409 Conflict
                )

            # Capture the status BEFORE flipping to "processing" so the worker
            # knows whether this is a selective re-publish of a partial report.
            prior_status = locked_report.publishing_status

            # Set status to processing atomically
            locked_report.publishing_status = "processing"
            db.session.commit()
            logger.info(f"Lock acquired for report {posted_report.id}")

        except OperationalError as lock_error:
            db.session.rollback()
            # Handle database lock timeout (another process has the lock)
            error_msg = str(lock_error).lower()
            if (
                "could not obtain lock" in error_msg
                or "lock timeout" in error_msg
                or "nowait" in error_msg
            ):
                logger.warning(
                    f"Could not acquire lock for report {posted_report.id}: {str(lock_error)}"
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "This report is already being published. Please wait for the current process to complete.",
                            "message": "Publishing already in progress. Please wait...",
                        }
                    ),
                    409,  # 409 Conflict
                )
            # Re-raise if it's a different database error
            raise
        except Exception as lock_error:
            db.session.rollback()
            # Catch any other unexpected errors during locking
            logger.error(
                f"Unexpected error during lock acquisition for report {posted_report.id}: {str(lock_error)}"
            )
            raise

        # Start processing in background thread to avoid timeout
        # Return immediately with 202 Accepted status
        threading.Thread(
            target=process_xero_integration_background,
            args=(
                entity_id,
                posted_report.transaction_date,
                posted_report.id,
                user_email,
                access_token_to_use,
                current_app._get_current_object(),
                prior_status,
            ),
            daemon=True,
        ).start()

        return (
            jsonify(
                {
                    "category": "info",
                    "status": "processing",
                    "message": "Xero integration started. Processing in background. This may take a few minutes.",
                }
            ),
            202,  # 202 Accepted - request accepted for processing
        )

    except Exception as e:
        db.session.rollback()
        # Safety fallback: prevent report from being stuck in 'processing' if any error
        # occurs after status was set.
        try:
            stuck_report = Report.query.get(report_id)
            if stuck_report and stuck_report.publishing_status == "processing":
                stuck_report.publishing_status = "failed"
                db.session.commit()
        except Exception as recover_error:
            logger.error(
                f"Failed to recover publishing_status after exception for report {report_id}: {str(recover_error)}"
            )
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


# Submitted step: report_submitted transferred from app.py (single
# function, no new functions).
