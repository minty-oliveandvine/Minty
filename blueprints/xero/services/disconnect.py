"""Disconnecting a company from Xero - the one place it is done (phase 2, 2026-10-05: moved here
from the session route ``POST /entity/settings/xero/disconnect`` when the Entity & Integration
tab became minty-web's; its bearer route is ``POST /api/me/company/xero/disconnect``).

What it does, in order: revoke the company's grant at Xero (best effort - the connector's token
may have lapsed, Xero may be down: logged, and the local side goes on), clear the connector's
stored tokens when this was the LAST company they connected (tokens are per person and shared
across their companies), drop the cached Xero data (whatever connects next may be another
organisation), and mark the company ``disconnected`` with no org and no connector.

Raises when the local side cannot be saved, after rolling back; the caller says so - the revoke
at Xero may already have gone through, so the two sides can disagree.
"""

from __future__ import annotations

import requests
from loguru import logger

from blueprints.entity.services.settings import invalidate_entity_xero_cache
from models.db import Entity, User, db
from services.auth.token_service import ensure_valid_token

_CONNECTIONS_URL = "https://api.xero.com/connections"


def _revoke_at_xero(connector, entity_id: str, xero_org_id) -> None:
    try:
        if not ensure_valid_token(connector):
            return
        listed = requests.get(
            _CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {connector.access_token}"},
            timeout=10,
        )
        if listed.status_code != 200:
            logger.warning(f"Xero GET /connections returned {listed.status_code} for user {connector.username}")
            return
        for conn in listed.json():
            if conn.get("tenantId") == str(xero_org_id):
                deleted = requests.delete(
                    f"{_CONNECTIONS_URL}/{conn.get('id')}",
                    headers={"Authorization": f"Bearer {connector.access_token}"},
                    timeout=10,
                )
                if deleted.status_code in (200, 204):
                    logger.info(f"Disconnected user {connector.username} from entity {entity_id}")
                else:
                    logger.warning(f"Xero DELETE /connections/{conn.get('id')} returned {deleted.status_code}")
                return
    except Exception as exc:  # noqa: BLE001 - the local disconnect goes on; Xero is told when it can be
        logger.warning(f"Failed to revoke the Xero grant of user {connector.username}: {exc}")


def disconnect_entity_from_xero(entity_id: str) -> None:
    try:
        org = Entity.query.get(entity_id)
        if org is None:
            raise LookupError(f"no entity {entity_id}")
        logger.info(f"Disconnecting entity: {org.name} (ID: {entity_id})")

        connector = User.query.get(org.connected_by_user_id) if org.connected_by_user_id else None
        if org.connected_by_user_id and connector is None:
            logger.warning(
                f"connected_by_user_id {org.connected_by_user_id} on entity {entity_id} "
                "points to a missing user; skipping remote disconnect"
            )
        if connector is not None and org.xero_org_id:
            _revoke_at_xero(connector, entity_id, org.xero_org_id)

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
                logger.info(f"Keeping Xero tokens for user {connector.username} — still connected to other entities")
            else:
                connector.clear_tokens()
                logger.info(f"Cleared Xero tokens for user {connector.username}")

        invalidate_entity_xero_cache(org.id, org.xero_org_id)
        org.status = "disconnected"
        org.xero_org_id = None
        org.connected_by_user_id = None
        db.session.commit()
        logger.info(f"Successfully disconnected entity: {entity_id}")
    except Exception:
        db.session.rollback()
        raise
