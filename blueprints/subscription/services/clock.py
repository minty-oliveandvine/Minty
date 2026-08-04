"""Trusted clock for subscription access / grace decisions.

Module access windows (past-due grace, the in-app paid-cancel ``app_access_until``) are
enforced by comparing a stored, absolute end date against "now". If "now" were the app
host's wall clock, a wrong or shifted system clock could wrongly grant or revoke access.

So those decisions call :func:`now` rather than ``datetime.now()``. It answers from the
first available of three sources:

1. **Stripe's** server time, captured from the ``Date`` header of a fetch made during
   this request. The same clock Stripe's own timestamps come from, so comparisons
   against them are exact.
2. **The database's** clock — one ``SELECT now()`` against Postgres, cached per request.
3. The process clock, as a last resort.

Source 2 exists because source 1 is a SIDE EFFECT of a call made for another reason. As
billing moves in-house, ``list_customer_subscriptions`` stops being called — and with it
the only writer of Stripe's time. Without a second source the fallback would be the host
wall clock, silently, exactly when the trusted clock is most needed. Worse, during a
partial migration it would vary per request depending on which code path ran first.

The database is the right second source: it is a round trip already being made, on
infrastructure under the same control, and it is shared by every app instance — so two
servers with differently-drifted clocks still agree, which per-host time cannot promise.

All values are cached on the Flask application-context global ``g``, so they are
per-request/per-CLI-invocation and thread-safe (each context has its own ``g``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from flask import g, has_app_context

_G_KEY = "_subscription_server_now"
_G_DB_KEY = "_subscription_database_now"


def _parse_http_date(value: str | None) -> datetime | None:
    """Parse an HTTP ``Date`` header (RFC 7231) to an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def record_http_date(date_header: str | None) -> None:
    """Record Stripe's server time (a response ``Date`` header) for this context so
    later :func:`now` calls use it. No-op outside an app context or on a bad header."""
    dt = _parse_http_date(date_header)
    if dt is not None and has_app_context():
        setattr(g, _G_KEY, dt)


def database_now() -> datetime | None:
    """The DATABASE's current time, cached for this request. None if unavailable.

    Deliberately quiet on failure: a clock lookup must never be the thing that breaks a
    request. The caller falls through to the process clock, which is worse but working.
    """
    if not has_app_context():
        return None
    cached = getattr(g, _G_DB_KEY, None)
    if cached is not None:
        return cached
    try:
        # Imported here, not at module scope: this module is imported by the Stripe
        # client, and pulling the model layer in at import time drags the whole entity
        # model graph along with it.
        from sqlalchemy import text

        from models.db import db

        value = db.session.execute(text("SELECT now()")).scalar()
    except Exception:
        return None
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    setattr(g, _G_DB_KEY, value)
    return value


def now() -> datetime:
    """Trusted current UTC time for access/grace decisions.

    Stripe's captured server time, else the database's, else the process clock — see
    the module docstring for why there are three.

    The order matters: while Stripe's time is present it stays authoritative, because
    every date it is compared against came from Stripe too. The database is what keeps
    the answer trustworthy once those calls go away, instead of silently degrading to
    the host's own clock.
    """
    if has_app_context():
        recorded = getattr(g, _G_KEY, None)
        if recorded is not None:
            return recorded
        from_db = database_now()
        if from_db is not None:
            return from_db
    return datetime.now(timezone.utc)
