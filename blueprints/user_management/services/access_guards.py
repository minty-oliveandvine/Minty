"""Shared access-control guards for user_management routes."""

from __future__ import annotations

from flask import Response, flash, redirect, url_for
from flask_login import current_user
from loguru import logger

from models.db import User


def require_superuser(
    redirect_endpoint: str,
    *,
    message: str = "Hmm, I can't let you in there.",
    category: str = "danger",
    log_unauthorized: bool = False,
    user=None,
    user_model=None,
) -> Response | None:
    """Ensure the current user is a superuser.

    Returns ``None`` when the user is a superuser and the caller should proceed.
    Otherwise flashes ``message`` and returns a redirect ``Response`` to
    ``redirect_endpoint`` for the caller to return directly.

    ``user`` and ``user_model`` let callers pass their own module-level
    ``current_user`` / ``User`` bindings so they stay the objects tests patch on
    the calling module.
    """
    actor = user if user is not None else current_user
    model = user_model if user_model is not None else User
    if getattr(actor, "system_role", None) == model.SYSTEM_ROLE_SUPERUSER:
        return None

    if log_unauthorized:
        logger.warning(
            "Unauthorized admin access attempt by user_id=%s",
            getattr(actor, "id", None),
        )

    flash(message, category)
    return redirect(url_for(redirect_endpoint))
