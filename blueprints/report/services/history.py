# Report and draft history logging. Used by report detail (edit), ending,
# opening, etc.
from __future__ import annotations

import traceback

from loguru import logger

from models.db import ReportHistory, User, db


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
        # Resolve user_id whether the caller passed a username or an id. This
        # was previously only in log_history_draft, which is why callers are
        # inconsistent: deposit.py:286 passes current_draft.uploaded_by (a
        # username) while the rest pass current_user.id. Folding it in here
        # lets the log_history_draft callers redirect to this function without
        # silently dropping their history rows.
        resolved_user_id = user_id
        if user_id is not None:
            user = (
                User.query.filter_by(username=user_id).first()
                or User.query.filter_by(id=user_id).first()
            )
            if user:
                resolved_user_id = user.id
            else:
                logger.warning(
                    f"User {user_id} not found; logging history without a user"
                )
                resolved_user_id = None

        old_value_str = str(old_value) if old_value is not None else None
        new_value_str = str(new_value) if new_value is not None else None
        # ``company`` is accepted for the callers' sake and not stored: the report knows its
        # company (report_history lost the column in the redesign).
        history = ReportHistory(
            report_id=report_id,
            user_id=resolved_user_id,
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


# log_history_draft was deleted in Step 4a-2/4a-4. It was the only writer to
# report_history_draft and had no callers — log_history (above) resolves a
# username or an id, which is why the callers could redirect to it. Draft
# history lands in report_history; see history_query.py:127.
