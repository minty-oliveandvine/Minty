"""Token-authenticated Xero connection actions for the onboarding app.

Onboarding runs cross-origin with a short-lived Bearer JWT (no Flask session
cookie), so it can't hit the session-authenticated ``/entity/settings/xero/*``
routes. This module mirrors ``disconnect_from_xero`` (blueprints/xero/routes/
routes.py) as a service returning ``(data, status)`` for the onboarding API.

It performs the same two-sided disconnect:
  1. Remote: revoke the connection on Xero (GET /connections to find the
     connection id for the entity's tenant, then DELETE /connections/{id}).
  2. Local: flip the entity to status "disconnected", clear xero_org_id /
     connected_by_user_id, and clear the connector's stored token bundle.

Permission/membership contract matches the other onboarding endpoints; the
caller is the JWT's user_id and must hold XERO_SETTINGS_UPDATE on the entity.
"""

from __future__ import annotations

import requests
from loguru import logger

from models.db import Entity, User, UserToken, db
from services.auth.token_service import ensure_valid_token
from services.permission_policy import Permission, has_permission_by_user_id

_XERO_CONNECTIONS_URL = "https://api.xero.com/connections"


def disconnect_entity_xero(user_id, entity_id):
    """Disconnect ``entity_id`` from Xero during onboarding.

    Mirrors ``disconnect_from_xero``: revokes the connection on Xero's side and
    clears the local connection + token state. Returns ``(data, status)``.
    """
    entity_id = (entity_id or "").strip()
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    if not has_permission_by_user_id(
        user_id, Permission.XERO_SETTINGS_UPDATE, entity_id
    ):
        return {"error": "Access denied"}, 403

    org = Entity.query.get(entity_id)
    if not org:
        return {"error": "Entity not found"}, 404

    try:
        connector = None
        if org.connected_by_user_id:
            connector = User.query.get(org.connected_by_user_id)
            if connector is None:
                logger.warning(
                    "onboarding disconnect: connected_by_user_id %s on entity %s "
                    "points to a missing user; skipping remote disconnect",
                    org.connected_by_user_id, entity_id,
                )

        # 1. Revoke on Xero's side (best-effort — local state is cleared even if
        #    the remote call fails, matching disconnect_from_xero).
        if connector is not None and org.xero_org_id:
            try:
                if ensure_valid_token(connector):
                    get_conn_response = requests.get(
                        _XERO_CONNECTIONS_URL,
                        headers={
                            "Authorization": f"Bearer {connector.access_token}"
                        },
                        timeout=10,
                    )
                    if get_conn_response.status_code == 200:
                        for conn in get_conn_response.json():
                            if conn.get("tenantId") == str(org.xero_org_id):
                                conn_id = conn.get("id")
                                delete_response = requests.delete(
                                    f"{_XERO_CONNECTIONS_URL}/{conn_id}",
                                    headers={
                                        "Authorization": f"Bearer {connector.access_token}"
                                    },
                                    timeout=10,
                                )
                                if delete_response.status_code in (200, 204):
                                    logger.info(
                                        "onboarding disconnect: revoked user %s from entity %s",
                                        connector.username, entity_id,
                                    )
                                else:
                                    logger.warning(
                                        "onboarding disconnect: Xero DELETE /connections/%s "
                                        "returned %s",
                                        conn_id, delete_response.status_code,
                                    )
                                break
                    else:
                        logger.warning(
                            "onboarding disconnect: Xero GET /connections returned %s "
                            "for user %s",
                            get_conn_response.status_code, connector.username,
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "onboarding disconnect: failed to revoke for user %s: %s",
                    getattr(connector, "username", "?"), exc,
                )

        # 2. Clear the connector's stored tokens (user columns + user_token row)
        #    — but ONLY if this user has no OTHER entity still connected with the
        #    same shared token bundle. Tokens are per-user (user_token.user_id is
        #    UNIQUE) and one user can be connected_by_user_id for several
        #    entities, so a blanket clear here would break those other entities'
        #    Xero access. We scope the clear to "this was their last connection".
        if connector is not None:
            other_connected = (
                Entity.query.filter(
                    Entity.connected_by_user_id == connector.id,
                    Entity.xero_org_id.isnot(None),
                    Entity.id != entity_id,
                ).first()
                is not None
            )
            if other_connected:
                logger.info(
                    "onboarding disconnect: keeping Xero tokens for user %s — "
                    "still connected to other entities",
                    connector.username,
                )
            else:
                connector.access_token = None
                connector.refresh_token = None
                connector.xero_entity_id = None
                connector.id_token = None
                connector.expires_in = None
                connector.token_created_at = None

                token_row = UserToken.query.filter_by(
                    user_id=connector.id
                ).first()
                if token_row is not None:
                    token_row.access_token = None
                    token_row.refresh_token = None
                    token_row.id_token = None
                    token_row.access_token_expires_in = None
                    token_row.access_token_obtained_at = None
                logger.info(
                    "onboarding disconnect: cleared Xero tokens for user %s",
                    connector.username,
                )

        # 3. Flip local connection state. Mid-onboarding we keep the entity in
        #    the onboarding flow (status stays a non-connected value); we use
        #    "onboarding" so the resume flow continues to treat it as in-progress
        #    and the wizard simply shows Xero as not connected again.
        org.status = "onboarding"
        org.xero_org_id = None
        org.connected_by_user_id = None
        db.session.commit()
        logger.info("onboarding disconnect: entity %s disconnected", entity_id)
        return {"ok": True, "connected": False}, 200
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error(
            "onboarding disconnect failed entity=%s: %s", entity_id, exc
        )
        return {"error": "Failed to disconnect from Xero. Please try again."}, 500
