"""Flask endpoints called by Module 2 (billing_backend) to trigger Xero
chart-of-accounts sync when the Bill Settings page is opened.

Module 2's bill list endpoint POSTs here with a Bearer JWT from the same
Module 1 handoff token; we resolve the entity's Xero token locally rather
than trusting anything from the incoming payload (only entity_id from URL).
"""

from __future__ import annotations

from flask import jsonify, request
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.entity.services.settings import (
    sync_chart_of_accounts_if_changed_background,
    sync_contacts_if_changed_background, sync_xero_coa_bill)
from models.db import Entity
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)


def _require_bearer():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Bearer token required"}), 401
    return None


@entity_bp.route(
    "/api/entities/<string:entity_id>/billing/sync-chart-accounts",
    methods=["POST"],
)
def billing_sync_chart_accounts(entity_id):
    """Backfill entity_bill_account_xero from account_info for this entity.

    Insert-only mirror of the petty cash CoA sync (no Xero fetch, no
    soft-delete). account_info is kept fresh by the entity's own Xero syncs
    (connect / settings GET / sync-chart-if-changed).
    """
    err = _require_bearer()
    if err:
        return err

    entity = Entity.query.get(entity_id)
    if not entity:
        return jsonify({"skipped": True, "reason": "entity_not_found"}), 404
    if not entity.xero_org_id:
        return jsonify({"skipped": True, "reason": "no_xero_org_id"}), 200

    try:
        token_user = get_xero_token_user_for_entity(entity_id)
        if not token_user or not ensure_valid_token(token_user):
            return jsonify({"skipped": True, "reason": "no_valid_xero_token"}), 200

        inserted, _refreshed = sync_xero_coa_bill(
            entity_id, user_id=str(token_user.id)
        )
        return jsonify({"status": "ok", "new_rows": int(inserted or 0)}), 200
    except Exception as exc:
        logger.exception(
            "billing_sync_chart_accounts failed entity=%s: %s", entity_id, exc
        )
        # Detail stays in the log; the response carries only a stable reason
        # code for Module 2 to branch on. A caught exception is a failure, not
        # a skip: returning 200 had the caller log it at WARNING next to benign
        # reasons like no_xero_org_id. 500 puts it in the caller's error branch
        # (bills/services/flask_billing_sync.py), which logs the body and still
        # returns True, so nothing downstream changes shape.
        return jsonify({"status": "failed", "reason": "exception"}), 500


@entity_bp.route(
    "/api/entities/<string:entity_id>/billing/sync-chart-if-changed",
    methods=["POST"],
)
def billing_sync_chart_if_changed(entity_id):
    """Compare Xero vs DB; if anything changed, sync both Module 1 and Module 2."""
    err = _require_bearer()
    if err:
        return err

    entity = Entity.query.get(entity_id)
    if not entity:
        return jsonify({"skipped": True, "reason": "entity_not_found"}), 404
    if not entity.xero_org_id:
        return jsonify({"skipped": True, "reason": "no_xero_org_id"}), 200

    try:
        token_user = get_xero_token_user_for_entity(entity_id)
        if not token_user or not ensure_valid_token(token_user):
            return jsonify({"skipped": True, "reason": "no_valid_xero_token"}), 200

        # Fire-and-forget: run the Xero diff/sync in a daemon thread and return
        # immediately. The bill CoA list is served from the DB, so the caller
        # (and the settings render) is never blocked on the Xero diff; this only
        # refreshes entity_bill_account_xero for the next load.
        sync_chart_of_accounts_if_changed_background(
            entity_id,
            token_user.access_token,
            entity.xero_org_id,
            user_id=str(token_user.id),
        )
        return jsonify({"status": "triggered"}), 202
    except Exception as exc:
        logger.exception(
            "billing_sync_chart_if_changed failed entity=%s: %s", entity_id, exc
        )
        # Detail stays in the log; the response carries only a stable reason
        # code for Module 2 to branch on. A caught exception is a failure, not
        # a skip: returning 200 had the caller log it at WARNING next to benign
        # reasons like no_xero_org_id. 500 puts it in the caller's error branch
        # (bills/services/flask_billing_sync.py), which logs the body and still
        # returns True, so nothing downstream changes shape.
        return jsonify({"status": "failed", "reason": "exception"}), 500


@entity_bp.route(
    "/api/entities/<string:entity_id>/billing/sync-contacts-if-changed",
    methods=["POST"],
)
def billing_sync_contacts_if_changed(entity_id):
    """Compare Xero vs DB contacts; if anything changed, refresh locally.

    Mirror of ``billing_sync_chart_if_changed`` for contacts. Module 2 POSTs
    here when the Bill Settings / contact picker is opened; we resolve the
    entity's Xero token locally and never trust the incoming payload (only
    entity_id from the URL).
    """
    err = _require_bearer()
    if err:
        return err

    entity = Entity.query.get(entity_id)
    if not entity:
        return jsonify({"skipped": True, "reason": "entity_not_found"}), 404
    if not entity.xero_org_id:
        return jsonify({"skipped": True, "reason": "no_xero_org_id"}), 200

    try:
        token_user = get_xero_token_user_for_entity(entity_id)
        if not token_user or not ensure_valid_token(token_user):
            return jsonify({"skipped": True, "reason": "no_valid_xero_token"}), 200

        # Fire-and-forget: run the Xero diff/sync in a daemon thread and return
        # immediately. The contact list is served from the DB, so the caller is
        # never blocked on the Xero diff; this only refreshes the cached
        # contacts for the next load.
        sync_contacts_if_changed_background(
            entity_id,
            token_user.access_token,
            entity.xero_org_id,
        )
        return jsonify({"status": "triggered"}), 202
    except Exception as exc:
        logger.exception(
            "billing_sync_contacts_if_changed failed entity=%s: %s", entity_id, exc
        )
        # Detail stays in the log; the response carries only a stable reason
        # code for Module 2 to branch on. A caught exception is a failure, not
        # a skip: returning 200 had the caller log it at WARNING next to benign
        # reasons like no_xero_org_id. 500 puts it in the caller's error branch
        # (bills/services/flask_billing_sync.py), which logs the body and still
        # returns True, so nothing downstream changes shape.
        return jsonify({"status": "failed", "reason": "exception"}), 500
