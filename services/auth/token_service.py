"""Token-related helper services for Xero OAuth lifecycle."""

from __future__ import annotations

import base64
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, MutableMapping, cast

import pytz
import requests
from flask import current_app, g
from sqlalchemy import text

from models.db import Entity, User, UserToken


def _resolve_app(application=None):
    if application is not None:
        return application
    try:
        return cast(Any, current_app)._get_current_object()
    except Exception:
        return None


def _log(application, level: str, message: str, exc_info: bool = False):
    app = _resolve_app(application)
    if not app:
        return
    logger = getattr(app, "logger", None)
    if not logger:
        return
    if exc_info:
        logger.error(message, exc_info=True)
    else:
        getattr(logger, level, logger.info)(message)


def _get_timezone(tz):
    if tz:
        return tz
    return pytz.timezone("Asia/Hong_Kong")


def refresh_access_token_for_user(user, application=None):
    app = _resolve_app(application)
    if not app:
        return None
    if not user or not getattr(user, "refresh_token", None):
        return None

    try:
        client_id_secret = f"{app.config['CLIENT_ID']}:{app.config['CLIENT_SECRET']}"
        base64_id_secret = base64.b64encode(client_id_secret.encode("utf-8")).decode(
            "utf-8"
        )
        authorization_header = f"Basic {base64_id_secret}"

        url = "https://identity.xero.com/connect/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": user.refresh_token,
        }
        headers = {
            "Authorization": authorization_header,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # A timeout is mandatory here. requests waits forever by default, and
        # this runs from an after_request hook (pettycash/core/hooks.py:383) —
        # so a slow or unreachable identity.xero.com hangs the worker until
        # gunicorn kills it, losing a request whose response was ALREADY
        # rendered. (connect, read) in seconds; the except below turns a
        # timeout into a normal "refresh failed" and the caller carries on.
        response = requests.post(
            url, data=payload, headers=headers, timeout=(5, 10)
        )
        if response.status_code == 200:
            token_data = response.json()
            return token_data
        _log(
            app,
            "error",
            f"Token refresh failed with status {response.status_code}: {response.text}",
        )
        return None
    except Exception as exc:
        _log(app, "error", f"Error refreshing access token: {str(exc)}")
        return None


def token_expired(current_user, application=None, tz=None):
    app = _resolve_app(application)
    try:
        if not current_user:
            return {"Token Expired": "Missing user"}, 500
        _log(app, "info", f"Checking token expiration for user: {current_user.username}")
        if current_user.expires_in is None or current_user.token_created_at is None:
            # No bundle (never connected, disconnected, or the row was cleared): there is
            # nothing to be current, so "expired" - and not an error worth a log line.
            return True
        expires_in_seconds = int(current_user.expires_in) - 300
        obtained = current_user.token_created_at
        if getattr(obtained, "tzinfo", None) is None:
            # naive: written as local time (SQLite, and rows older than the timestamptz change)
            obtained = _get_timezone(tz).localize(obtained)
        created_at = obtained.timestamp()
        timenow = datetime.now(_get_timezone(tz)).timestamp()
        elapsed_seconds = timenow - created_at
        _log(
            app,
            "info",
            f"Time now: {timenow}, Created at: {created_at}, Elapsed seconds: {elapsed_seconds}",
        )
        if elapsed_seconds > expires_in_seconds:
            date_elapsed = datetime.fromtimestamp(elapsed_seconds, _get_timezone(tz))
            _log(
                app,
                "info",
                f"Compared time: {elapsed_seconds} > {expires_in_seconds}, Time now: {timenow}, Created at: {created_at}, Elapsed seconds: {elapsed_seconds}, Date elapsed: {date_elapsed}",
            )
            return True
        return False
    except Exception as exc:
        _log(app, "error", f"Error checking token expiration: {str(exc)}")
        # Callers key on the tuple shape (see hooks.py / refresh flow), so keep
        # it — but the exception text is already logged just above.
        return {"Token Expired": "Could not check token expiry"}, 500


def auto_refresh_token(current_user, application=None):
    app = _resolve_app(application)
    try:
        new_tokens = refresh_access_token_for_user(current_user, application=application)
        if not new_tokens:
            _log(app, "warning", "Token refresh returned no tokens - refresh token may be expired")
            return False
        if apply_refreshed_tokens(current_user, new_tokens, application=application):
            _log(app, "info", "Access token refreshed successfully")
            return True
        return False
    except Exception as exc:
        _log(app, "error", f"Error auto refreshing token: {str(exc)}", exc_info=True)
        return False


def ensure_valid_token(
    user,
    application=None,
    cache: MutableMapping[str, bool] | None = None,
):
    app = _resolve_app(application)
    try:
        if user is None:
            _log(app, "error", "ensure_valid_token called with no user")
            return False

        scope = cache if cache is not None else getattr(g, "_token_validated", None)
        if scope is None:
            setattr(g, "_token_validated", {})
            scope = g._token_validated

        user_key = str(getattr(user, "id", id(user)))
        if scope.get(user_key):
            return True

        if not user.access_token or not user.refresh_token:
            if not user.access_token and not user.refresh_token:
                _log(app, "error", "User missing both access token and refresh token")
            elif not user.access_token:
                _log(app, "error", "User missing access token")
            else:
                _log(app, "error", "User missing refresh token")
            return False

        expired = token_expired(user, application=application)
        if expired:
            if isinstance(expired, tuple):
                return False
            _log(app, "info", "Access token expired, attempting to refresh...")
            result = auto_refresh_token(user, application=application)
            if result:
                scope[user_key] = True
                _log(app, "info", "Token refreshed successfully")
            else:
                _log(app, "warning", "Token refresh failed - refresh token may be expired or invalid")
            return result
        scope[user_key] = True
        return True
    except Exception as exc:
        _log(app, "error", f"Error ensuring valid token: {str(exc)}")
        return False


def upsert_user_token(user, token_data, application=None, is_refresh=False):
    """Write/refresh the user_token row for ``user`` from a Xero token payload.

    ``token_data`` is the dict returned by Xero's /connect/token endpoint
    (``access_token``, ``refresh_token``, ``id_token``, ``expires_in``).
    Existing rows are updated in place; missing rows are created.

    When ``is_refresh`` is True, ``refresh_token_last_used_at`` is stamped
    with the current HK time so we can track refresh churn.
    """
    from models.db import db

    app = _resolve_app(application)
    if not user or not getattr(user, "id", None) or not token_data:
        return None

    try:
        row = UserToken.query.filter_by(user_id=user.id).first()
        if row is None:
            row = UserToken(user_id=user.id)
            db.session.add(row)

        now_hk = datetime.now(_get_timezone(None))

        if token_data.get("access_token") is not None:
            row.access_token = token_data.get("access_token")
            row.access_token_obtained_at = now_hk
        if token_data.get("expires_in") is not None:
            row.access_token_expires_in = int(token_data["expires_in"])
        if token_data.get("refresh_token") is not None:
            row.refresh_token = token_data.get("refresh_token")
        if token_data.get("id_token") is not None:
            row.id_token = token_data.get("id_token")

        if is_refresh:
            row.refresh_token_last_used_at = now_hk

        db.session.commit()
        return row
    except Exception as exc:
        _log(app, "error", f"Error upserting user_token for user {user.id}: {str(exc)}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def apply_refreshed_tokens(user, new_tokens, application=None):
    """Commit a refreshed token bundle to ``user_token`` and stamp
    ``refresh_token_last_used_at``.

    Returns ``True`` if anything was applied, ``False`` otherwise. Use this everywhere
    a token response comes back from Xero. There is one store: ``User.access_token`` and
    friends are properties over the same row (blueprints/auth/models/user.py), so every
    reader sees the new bundle immediately.
    """
    if not user or not new_tokens:
        return False
    return upsert_user_token(user, new_tokens, application=application, is_refresh=True) is not None


def _hydrate_user_from_user_token(user, application=None):
    """True when ``user`` holds a usable Xero bundle.

    Historically copied the ``user_token`` row onto the six shadow columns of ``user``;
    those columns are gone and ``User.access_token`` reads the row directly, so the only
    question left is whether there is anything to read.
    """
    if not user or not getattr(user, "id", None):
        return False
    return bool(user.access_token)


def get_xero_token_user_for_entity(entity_id, application=None, token_cache=None):
    """Resolve the Xero token-bearer for ``entity_id``.

    Strategy (single deterministic path; no legacy fallback):

    1. Read ``entity.connected_by_user_id``.
    2. Load that User and hydrate access/refresh tokens from ``user_token``.
    3. Run ``ensure_valid_token`` (refreshes if expired).
    4. If anything in the chain fails, return ``None`` so the UI can prompt
       the user to reconnect, instead of silently masking the failure with
       ``current_user``.
    """
    app = _resolve_app(application)
    if not entity_id:
        return None

    entity = Entity.query.get(entity_id)
    if not entity or not entity.xero_org_id:
        return None

    if not getattr(entity, "connected_by_user_id", None):
        _log(
            app,
            "info",
            f"Entity {entity_id} has no connected_by_user_id; reconnect required",
        )
        return None

    try:
        owner_user = User.query.filter(
            User.id == entity.connected_by_user_id,
        ).first()
    except Exception as exc:
        _log(
            app,
            "warning",
            f"Error loading connector user for entity {entity_id}: {str(exc)}",
        )
        return None

    if owner_user is None:
        _log(
            app,
            "warning",
            f"connected_by_user_id {entity.connected_by_user_id} on entity "
            f"{entity_id} points to a missing user",
        )
        return None

    # Hydrate from user_token (authoritative). If that's empty, the connector
    # has no usable token bundle and we give up.
    if not _hydrate_user_from_user_token(owner_user, application=application):
        _log(
            app,
            "info",
            f"No user_token row for connector {owner_user.id} of entity "
            f"{entity_id}; reconnect required",
        )
        return None

    if not ensure_valid_token(owner_user, application=application, cache=token_cache):
        _log(
            app,
            "info",
            f"Connector token for entity {entity_id} could not be validated/"
            f"refreshed; reconnect required",
        )
        return None

    return owner_user


def resolve_xero_token(entity_id, current_user, application=None, token_cache=None):
    """Resolve the Xero token-bearer using the 3-tier strategy per spec:

    1. Entity connector — read ``entity.connected_by_user_id``, look up that
       user's ``user_token``, return them if valid.
    2. Current user fallback — hydrate ``current_user`` from ``user_token``
       and return them if their own token is valid.
    3. Disconnected — return ``None`` so the UI can prompt Reconnect.

    A WARNING is logged when the tier-2 fallback fires so we don't silently
    mask connector-resolution failures the way the old tenant-name lookup
    did.
    """
    app = _resolve_app(application)

    if entity_id:
        owner = get_xero_token_user_for_entity(
            entity_id, application=application, token_cache=token_cache,
        )
        if owner is not None:
            return owner

    if current_user is not None and getattr(current_user, "is_authenticated", False):
        if _hydrate_user_from_user_token(current_user, application=application):
            if ensure_valid_token(
                current_user, application=application, cache=token_cache
            ):
                _log(
                    app,
                    "warning",
                    f"resolve_xero_token: tier-2 fallback to current_user "
                    f"(id={getattr(current_user, 'id', None)}) for "
                    f"entity={entity_id} — entity connector did not resolve",
                )
                return current_user

    return None


# ---------------------------------------------------------------------------
# Service-to-service token resolution (used by the billing backend)
#
# Billing holds no Xero client credentials by design. Xero rotates refresh
# tokens on every use and invalidates the one it was sent, so a second refresher
# racing this one would leave a dead token in one of the two stores and break
# the connection until a human reconnects. Minty is the sole refresher; billing
# asks for a token through `resolve_entity_access_token_for_service`.
# ---------------------------------------------------------------------------

# int4; distinct namespace so these locks can't collide with any other
# advisory lock taken elsewhere in the app.
_XERO_LOCK_NAMESPACE = 1481594447  # 0x5845524F, "XERO"


@contextmanager
def _xero_refresh_lock(user_id, application=None, wait_seconds: float = 5.0):
    """Serialize Xero token refreshes for one token bearer across all processes.

    The lock must be held across the HTTP call to Xero, not merely across the
    database write: /connect/token is what spends the single-use refresh token,
    so by the time a row is being written the damage is already done.

    Held on a dedicated AUTOCOMMIT connection rather than the request session.
    `apply_refreshed_tokens` commits twice, and a pooled session may hand back
    its connection at commit, which would strand a session-scoped lock on a
    connection we no longer own. Closing this connection releases the lock even
    if the unlock statement never runs.

    Yields True if the lock was acquired, False if `wait_seconds` elapsed first.
    """
    from models.db import db

    app = _resolve_app(application)
    key = f"xero_refresh:{user_id}"
    params = {"ns": _XERO_LOCK_NAMESPACE, "k": key}
    acquired = False
    conn = db.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            acquired = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(:ns, hashtext(:k))"), params
                ).scalar()
            )
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        yield acquired
    finally:
        if acquired:
            try:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:ns, hashtext(:k))"), params
                )
            except Exception as exc:  # pragma: no cover - closing conn frees it anyway
                _log(app, "warning", f"Failed to release Xero refresh lock: {exc}")
        conn.close()


def _resolve_service_token_bearer(entity, application=None):
    """The user whose Xero bundle serves ``entity``: ``entity.connected_by_user_id``.

    That column is the only record of who connected a company (the old
    ``user.xero_entity_id`` fallback went with the column, schema item 19). No connector
    means the company needs a human to reconnect; say so rather than guess.
    """
    app = _resolve_app(application)
    connector_id = getattr(entity, "connected_by_user_id", None)
    if not connector_id:
        _log(app, "info", f"Entity {entity.id} has no connected_by_user_id; reconnect required")
        return None
    bearer = User.query.filter(User.id == str(connector_id)).first()
    if bearer is None:
        _log(app, "warning",
             f"connected_by_user_id {connector_id} on entity {entity.id} points to a missing user")
    return bearer


def resolve_entity_access_token_for_service(entity_id, application=None):
    """Return ``(access_token, xero_org_id)`` for ``entity_id``, refreshing if needed.

    Called by the billing backend, which cannot refresh. Returns ``None`` when no
    usable token can be produced, so the caller surfaces a reconnect prompt rather
    than sending Xero a dead token.
    """
    from models.db import db

    app = _resolve_app(application)
    if not entity_id:
        return None

    entity = Entity.query.get(entity_id)
    if not entity or not entity.xero_org_id:
        _log(app, "info", f"Entity {entity_id} has no Xero org linked")
        return None

    bearer = _resolve_service_token_bearer(entity, application=application)
    if bearer is None:
        _log(app, "info", f"No Xero token bearer for entity {entity_id}; reconnect required")
        return None

    with _xero_refresh_lock(bearer.id, application=application) as acquired:
        # Re-read under the lock: whoever held it before us has very likely just
        # written a fresh bundle, in which case there is nothing left to do.
        db.session.refresh(bearer)
        _hydrate_user_from_user_token(bearer, application=application)

        if bearer.access_token and token_expired(bearer, application=application) is False:
            return bearer.access_token, str(entity.xero_org_id)

        if not acquired:
            # Another refresh is in flight and did not finish in time. Refreshing
            # now would spend a refresh token that request is about to spend.
            _log(
                app,
                "warning",
                f"Timed out waiting for Xero refresh lock on bearer {bearer.id} "
                f"(entity {entity_id}); not refreshing",
            )
            return None

        # `ensure_valid_token` memoises per-request in `g`; pass a private cache so
        # this genuinely re-evaluates rather than reusing an earlier verdict.
        if not ensure_valid_token(bearer, application=application, cache={}):
            _log(
                app,
                "info",
                f"Refresh failed for bearer {bearer.id} (entity {entity_id}); "
                f"reconnect required",
            )
            return None

        return bearer.access_token, str(entity.xero_org_id)
