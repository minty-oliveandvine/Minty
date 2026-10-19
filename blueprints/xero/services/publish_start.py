"""Starting a report's Xero publish - shared by the Jinja Submitted page
(``report/routes/submitted.py``) and the Petty Cash API (``petty_cash_api/routes/report.py``).

Extracted 2026-10-16 under ``tests/test_report_publish_state.py`` (characterisation, green before
and after). Flask's order, kept: the Xero token (``user_token``, then the legacy ``User`` columns
of the company's connector and of this person), the company's Xero settings, a status re-sync,
the report, the system-account check, then ``SELECT ... FOR UPDATE NOWAIT`` and
``publishing_status = publishing`` before the background worker starts - so a second click is
refused (409). The worker itself (``publish.process_xero_integration_background``) is unchanged.

Fixed on the way out: a draft is refused (with a report id the route took any report of the
company), and a failure after the lock always puts the report back to ``failed`` (the reset used
the report id from the address, so publishing the latest report left it stuck).
"""
from __future__ import annotations

import threading

from loguru import logger
from sqlalchemy.exc import OperationalError

from blueprints.shared.enums import PublishStatus
from blueprints.xero.services.publish import (process_xero_integration_background,
                                              validate_expenses_for_system_accounts)
from blueprints.xero.services.settings import (check_entity_xero_settings_complete,
                                               sync_entity_xero_status)
from models.db import Entity, Report, User, db
from services.auth.token_service import ensure_valid_token, resolve_xero_token

ALREADY = "Publishing already in progress. Please wait..."
ALREADY_ERROR = "This report is already being published. Please wait for the current process to complete."
DRAFT = "This report is still a draft. Submit the day before publishing it."


class PublishRefused(Exception):
    """A publish that cannot start: the sentence, the HTTP status, the Jinja page's ``error`` and
    whether Xero must be connected again."""

    def __init__(self, message: str, status: int, *, error: str | None = None, requires_connection: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error = error or message
        self.requires_connection = requires_connection


def _word(value):
    return None if value is None else str(getattr(value, "value", value))


def _token(entity, user):
    """``(token holder, access token)`` - the authoritative ``user_token`` row first (a stale copy
    would spend an already-rotated refresh token), then the legacy ``User`` columns, validated."""
    owner = resolve_xero_token(entity.id, user)
    token = owner.access_token if owner else None
    if owner:
        logger.info(f"Using {owner.username}'s token for publishing (current user: {user.username})")
    if not token:
        connector = User.query.filter(User.id == entity.connected_by_user_id).first() if entity.connected_by_user_id else None
        for candidate in (connector, user):
            if candidate is None or not getattr(candidate, "access_token", None):
                continue
            if ensure_valid_token(candidate):
                logger.warning(
                    f"LEGACY_USER_COLUMN_TOKEN entity={entity.id} user={candidate.username} - no usable "
                    f"user_token row; published from legacy User columns. Backfill required."
                )
                return candidate, candidate.access_token
    return owner, token


def start_publish(entity_id, report_id, user, app):
    """Start publishing ``report_id`` (or, with none, the company's latest submitted report) to
    Xero in the background. Returns the report; raises ``PublishRefused``."""
    entity = db.session.get(Entity, entity_id)
    if entity is None:
        raise PublishRefused("No report found to publish", 404)

    owner, token = _token(entity, user)
    if not token:
        raise PublishRefused("I've lost access to your Xero account. Mind reconnecting it in Settings?", 400,
                             error="No Xero access token found. Please reconnect to Xero.", requires_connection=True)
    if not check_entity_xero_settings_complete(entity_id):
        raise PublishRefused("Xero settings incomplete. Please configure entity settings first.", 400,
                             error="Entity Xero settings are incomplete. Please configure entity settings first.")

    # A status other than "connected" may simply be stale; only "disconnected" is worth a warning.
    if _word(entity.status) != "connected":
        if _word(entity.status) == "disconnected":
            logger.warning(f"Entity {entity_id} status is 'disconnected', but attempting to publish with stored tokens")
        try:
            sync_entity_xero_status(entity_id, token_validated=True)
        except Exception as sync_error:
            logger.warning(f"Status sync failed, proceeding anyway: {sync_error}")

    if report_id:
        report = Report.query.filter_by(id=report_id, company=entity_id).first()
    else:
        report = (
            Report.query.filter(Report.company == entity_id, db.or_(Report.status.is_(None), Report.status != "draft"))
            .order_by(Report.date.desc())
            .first()
        )
    if report is None:
        raise PublishRefused("No report found to publish", 404)
    if _word(report.status) == "draft":
        raise PublishRefused(DRAFT, 409)

    owner = owner or user
    errors = validate_expenses_for_system_accounts(entity_id, report.id, access_token=token)
    if errors:
        if len(errors) == 1:
            message = errors[0]["message"]
        else:
            listed = "\n".join(f"• {e['expense']} - {e['account_code']}" for e in errors)
            message = f"System accounts detected:\n{listed}\n\nPlease update."
        logger.warning(f"Validation failed for report {report.id}: {len(errors)} expense(s) with system account codes")
        raise PublishRefused(message, 400)

    try:
        # ``of=Report``: the creator and their token are eager-loaded through outer joins, and
        # Postgres refuses to lock the nullable side of one.
        locked = db.session.query(Report).filter(Report.id == report.id).with_for_update(nowait=True, of=Report).first()
        if locked is None:
            db.session.rollback()
            raise PublishRefused("Report not found", 404)
        if _word(locked.publishing_status) == "publishing":
            db.session.rollback()
            logger.warning(f"Report {report.id} is already being processed. Rejecting duplicate request.")
            raise PublishRefused(ALREADY, 409, error=ALREADY_ERROR)
        # Captured BEFORE the flip, so the worker knows a selective re-publish of a partial report.
        prior_status = locked.publishing_status
        locked.publishing_status = PublishStatus.PUBLISHING
        db.session.commit()
        logger.info(f"Lock acquired for report {report.id}")
    except OperationalError as lock_error:
        db.session.rollback()
        text = str(lock_error).lower()
        if "could not obtain lock" in text or "lock timeout" in text or "nowait" in text:
            logger.warning(f"Could not acquire lock for report {report.id}: {lock_error}")
            raise PublishRefused(ALREADY, 409, error=ALREADY_ERROR) from None
        raise

    try:
        logger.info(f"Starting Xero integration for report {report.id}, entity {entity_id} "
                    f"(using token from user: {owner.username})")
        threading.Thread(
            target=process_xero_integration_background,
            args=(entity_id, report.transaction_date, report.id, owner.username, token, app, prior_status),
            daemon=True,
        ).start()
    except Exception:
        _unstick(report.id)
        raise
    return report


def _unstick(report_id) -> None:
    """A start that failed after the lock: never leave the report "publishing" (nothing could then
    publish, edit or delete it)."""
    db.session.rollback()
    try:
        stuck = db.session.get(Report, report_id)
        if stuck is not None and _word(stuck.publishing_status) == "publishing":
            stuck.publishing_status = "failed"
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(f"Failed to recover publishing_status after a failed start, report {report_id}")
