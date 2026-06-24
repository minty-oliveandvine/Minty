"""Xero settings and connection debug routes."""

import time

import requests
from flask import jsonify, request
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from loguru import logger

from blueprints.xero import xero_bp
from blueprints.xero.services.settings import \
    check_entity_xero_settings_complete
from models.db import (AccountInfo, Entity, EntityAccountXero, XeroContactSync,
                       db)
from services.authz import require_entity_access, require_permission
from services.auth.token_service import ensure_valid_token
from services.permission_policy import Permission, has_permission


@xero_bp.route("/remove/connections/all", methods=["GET"])
@login_required
def remove_connections_all() -> ResponseReturnValue:
    try:
        entity_id = request.args.get("entity_id")
        if not entity_id:
            return jsonify({"status": "error", "message": "Entity ID is required."}), 400
        if not has_permission(current_user, Permission.XERO_SETTINGS_UPDATE, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to remove Xero connections for this entity.",
                    }
                ),
                403,
            )
        org = Entity.query.get_or_404(entity_id)
        if ensure_valid_token(current_user):
            response = requests.get(
                "https://api.xero.com/connections",
                headers={
                    "Authorization": f"Bearer {current_user.access_token}"},
            )
            for conn in response.json():
                id = conn.get("id")
                for req in range(3):
                    logger.info(f"Deleting connection {req+1}/3: {id}")
                    delete_response = requests.delete(
                        f"https://api.xero.com/connections/{id}",
                        headers={
                            "Authorization": f"Bearer {current_user.access_token}"},
                    )
                    time.sleep(1)
                    logger.info(
                        f"Deleting connection {req+1}/3: {delete_response}")
                    logger.info("Deleted all Xero connections")
            org.status = "disconnected"
            db.session.commit()
        else:
            logger.error("Remove connections all: Token validation failed")
        return (
            "Your xero connections have been removed. Contact Admin to remove the "
            "entity created in Minty App. To start again, please create a new "
            "entity to connect to the entity you just disconnected. "
            '<a href="/">Login</a>',
            200,
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing Xero connections: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@xero_bp.route("/debug/xero-settings/<string:entity_id>")
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero settings debug for this entity.",
)
def debug_xero_settings(entity_id: str) -> ResponseReturnValue:
    """Debug route to check Xero settings status"""
    try:
        entity = Entity.query.get_or_404(entity_id)
        settings_count = (
            db.session.query(EntityAccountXero)
            .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .count()
        )
        contact_count = (
            db.session.query(XeroContactSync).filter_by(
                entity_id=entity_id).count())
        is_complete = check_entity_xero_settings_complete(entity_id)

        # Get detailed account types
        account_types = (
            db.session.query(EntityAccountXero.type)
            .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .all()
        )
        contact_categories = (
            db.session.query(XeroContactSync.category)
            .filter_by(entity_id=entity_id)
            .all()
        )

        return jsonify(
            {
                "entity_id": entity_id,
                "entity_name": entity.name,
                "xero_org_id": entity.xero_org_id,
                "settings_count": settings_count,
                "contact_count": contact_count,
                "is_complete": is_complete,
                "required_accounts": 6,
                "required_contacts": 3,
                "account_types": [t[0] for t in account_types],
                "contact_categories": [c[0] for c in contact_categories],
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


"""Xero domain helper functions moved out of legacy app."""












