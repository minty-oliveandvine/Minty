# Report and draft history logging. Used by report detail (edit), ending,
# opening, etc.
from __future__ import annotations

import traceback

from loguru import logger

from models.db import ReportHistory, ReportHistoryDraft, User, db


def log_history(
    report_id,
    company,
    user_id,
    action,
    field_changed=None,
    old_value=None,
    new_value=None,
):
    try:
        old_value_str = str(old_value) if old_value is not None else None
        new_value_str = str(new_value) if new_value is not None else None
        history = ReportHistory(
            report_id=report_id,
            company=company,
            user_id=user_id,
            action=action,
            field_changed=field_changed,
            old_value=old_value_str,
            new_value=new_value_str,
        )
        db.session.add(history)
        db.session.commit()
        return history
    except Exception as e:
        logger.error(f"Error logging history: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None


def log_history_draft(
    report_draft_id,
    company,
    user_id,
    action,
    field_changed=None,
    old_value=None,
    new_value=None,
):
    try:
        user = (
            User.query.filter_by(username=user_id).first()
            or User.query.filter_by(id=user_id).first()
        )
        if not user:
            logger.warning(
                f"User {user_id} not found in database, skipping history log"
            )
            return None
        actual_user_id = user.id
        old_value_str = str(old_value) if old_value is not None else None
        new_value_str = str(new_value) if new_value is not None else None
        history = ReportHistoryDraft(
            report_draft_id=report_draft_id,
            company=company,
            user_id=actual_user_id,
            action=action,
            field_changed=field_changed,
            old_value=old_value_str,
            new_value=new_value_str,
        )
        db.session.add(history)
        db.session.commit()
        return history
    except Exception as e:
        logger.error(f"Error logging draft history: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None
