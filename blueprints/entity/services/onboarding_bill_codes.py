"""Token-authenticated Bill Account Code settings for onboarding (Step 7).

The bill chart of accounts lives in ``pettycashv3.entity_bill_account_xero``
(the Module 2 / Bills snapshot) with an ``is_active`` flag deciding which codes
appear when adding a bill. This mirrors that tick state for the onboarding Bill
Settings step: ensure the snapshot is backfilled from ``account_info`` (no live
Xero call — that happens on connect), expose the codes + active state, and
persist the user's selection back onto ``is_active``.
"""

from __future__ import annotations

from services.app_runtime.log import logger
from sqlalchemy import bindparam, text

from blueprints.entity.services.settings import sync_xero_coa_bill
from models.db import Entity, db
from services.permission_policy import Permission, has_permission_by_user_id
from blueprints.shared.schema import SCHEMA

_TBL = f"{SCHEMA}.entity_bill_account_xero"


def _code_sort_key(code):
    """Sort by account code: numeric codes first (in numeric order), then others."""
    s = str(code or "").strip()
    try:
        return (0, int(s), "")
    except ValueError:
        return (1, 0, s.lower())


def get_bill_code_options(user_id, entity_id):
    """Return the bill account codes + current active selection for Step 7.

    Returns ``(data, status)``. 409 when the entity isn't connected to Xero yet
    (the bill chart only exists after a real Xero connection in Step 3).
    """
    if not has_permission_by_user_id(user_id, Permission.COA_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    entity = Entity.query.get(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if not entity.xero_org_id:
        return {
            "error": "Connect to Xero first to load payment account codes.",
            "connected": False,
        }, 409

    # Backfill entity_bill_account_xero from the already-synced account_info
    # (DB-only — Xero is hit on connect, not here). Idempotent and preserves
    # any is_active toggles the user has already made.
    try:
        sync_xero_coa_bill(entity_id, user_id)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.warning("get_bill_code_options backfill failed entity=%s: %s", entity_id, exc)

    rows = db.session.execute(
        text(
            f"SELECT account_code, account_name, is_active, is_default FROM {_TBL} "
            "WHERE entity_id = :eid AND is_deleted = false"
        ),
        {"eid": entity_id},
    ).fetchall()

    bill_codes = []
    selected_codes = []
    inactive_count = 0
    default_code = ""
    for code, name, is_active, is_default in rows:
        c = (code or "").strip()
        if not c:
            continue
        if is_default:
            default_code = c
        bill_codes.append({"code": c, "name": name or ""})
        if is_active:
            selected_codes.append(c)
        else:
            inactive_count += 1
    bill_codes.sort(key=lambda e: _code_sort_key(e["code"]))
    default_all = not selected_codes and inactive_count == 0

    return {
        "connected": True,
        "bill_codes": bill_codes,
        "selected_codes": selected_codes,
        "default_all": default_all,
        # The code a new payment request preselects ("" when none is set).
        "default_code": default_code,
    }, 200


def save_bill_codes(user_id, entity_id, selected_codes, default_code=None):
    """Persist the Step 8 selection onto ``entity_bill_account_xero.is_active``.

    ``selected_codes`` is the list of account codes that should appear when
    adding a bill; everything else is deactivated. ``default_code``, when sent, is
    the one ticked code a new payment request preselects (``is_default``); it must
    be one of ``selected_codes``, and every other code loses the flag. Not sent
    leaves the default as it is. Returns ``(data, status)``.
    """
    if not has_permission_by_user_id(user_id, Permission.COA_UPDATE, entity_id):
        return {"error": "Access denied"}, 403
    if not isinstance(selected_codes, list):
        return {"error": "selected_codes must be an array"}, 400

    entity = Entity.query.get(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if not entity.xero_org_id:
        return {
            "error": "Connect to Xero first to save payment account codes.",
            "connected": False,
        }, 409

    selected = sorted({str(c).strip() for c in selected_codes if str(c).strip()})

    # At least one code stays ticked (Payment Settings' rule, billing-backend's 409): a payment
    # can only use the ticked codes. A company with no codes listed has nothing to tick.
    listed = {
        (row[0] or "").strip()
        for row in db.session.execute(
            text(f"SELECT account_code FROM {_TBL} WHERE entity_id = :eid AND is_deleted = false"),
            {"eid": entity_id},
        )
    } - {""}
    if listed and not listed.intersection(selected):
        return {"error": "Pick at least one account code."}, 400
    default = str(default_code).strip() if default_code is not None else None
    if default and default not in selected:
        return {"error": "The default account code must be one of the ticked codes."}, 400

    try:
        db.session.execute(
            text(
                f"UPDATE {_TBL} SET is_active = false, updated_at = NOW() "
                "WHERE entity_id = :eid AND is_deleted = false"
            ),
            {"eid": entity_id},
        )
        if selected:
            stmt = text(
                f"UPDATE {_TBL} SET is_active = true, updated_at = NOW() "
                "WHERE entity_id = :eid AND is_deleted = false "
                "AND TRIM(account_code) IN :codes"
            ).bindparams(bindparam("codes", expanding=True))
            db.session.execute(stmt, {"eid": entity_id, "codes": selected})
        if default is not None:
            db.session.execute(
                text(
                    f"UPDATE {_TBL} SET is_default = (TRIM(account_code) = :code), "
                    "updated_at = NOW() WHERE entity_id = :eid AND is_deleted = false"
                ),
                {"eid": entity_id, "code": default},
            )
        db.session.commit()

        logger.info(
            "save_bill_codes: entity=%s selected=%s", entity_id, len(selected)
        )
        return {"ok": True, "selected_codes": selected, "default_code": default}, 200
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error("save_bill_codes failed entity=%s: %s", entity_id, exc)
        return {"error": "Failed to save payment account codes. Please try again."}, 500
