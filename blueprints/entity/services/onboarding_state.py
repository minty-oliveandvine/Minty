"""Server-side onboarding resume state.

The onboarding wizard (separate Next.js repo) has no database access and, on a
cold resume (new browser / incognito / cleared storage / different device), has
no localStorage to rehydrate from. The ``entities`` row — not the browser — is
the source of truth for an in-progress onboarding, so this module reconstructs
the whole wizard picture from the DB and the wizard treats localStorage as a
cache only.

``get_onboarding_state`` returns everything the wizard needs to land on the
correct step bound to ``entity_id`` without any browser storage: the entity's
basic info, selected modules, Xero connection, petty-cash Sales Setting (sales
methods + opening balance), pending invites, and a derived ``current_step`` /
``max_reached``.

Same token/membership contract as the other ``/api/onboarding/*`` services: the
caller is the JWT's user_id; access is denied (403) unless that user is a member
of the entity.
"""

from __future__ import annotations

import requests
from loguru import logger

from blueprints.entity.services.modules import (MODULE_BILL, MODULE_CODES,
                                                MODULE_PETTY_CASH)
from blueprints.entity.services.onboarding_invites import list_invites
from models.db import (Entity, EntityFunction, EntityFunctionMap,
                       EntityPettycashSettings, Report, ReportDraft,
                       EntitySaleSetting, UserEntity, db)
from services.auth.token_service import get_xero_token_user_for_entity

_XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

# Wizard step ids, mirroring the STEPS table in the onboarding app's
# OnboardingApp.jsx. Kept here so ``current_step`` derivation lives next to the
# data it reads rather than in the frontend.
STEP_BASIC = 1
STEP_MODULE = 2
STEP_INVITE = 3
STEP_ACCOUNTING = 4
STEP_SALES = 5
STEP_ACCOUNT_CODE = 6
STEP_OTHERS = 7
STEP_BILLS = 8
STEP_ALL_SET = 9


def _enabled_modules(entity_id: str) -> list[str]:
    """Module codes currently enabled for the entity, via entity_function_map.

    Mirrors ``routes.modules._is_module_enabled`` but resolves all canonical
    modules in one pass so the wizard gets the full selection.
    """
    functions = {
        f.function_code: f
        for f in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }
    enabled: list[str] = []
    for code in MODULE_CODES:
        fn = functions.get(code)
        if not fn:
            # No catalog row — default to enabled only for Petty Cash, matching
            # the create-time default state.
            if code == MODULE_PETTY_CASH:
                enabled.append(code)
            continue
        mapping = EntityFunctionMap.query.filter(
            EntityFunctionMap.entity_id == entity_id,
            EntityFunctionMap.entity_function_id == fn.id,
        ).first()
        is_on = mapping.is_enabled if mapping else fn.is_active
        if is_on:
            enabled.append(code)
    return enabled


def _reconcile_xero_disconnect(entity: Entity) -> None:
    """Detect a Xero-side disconnect and clear local connection state.

    The wizard reads ``connected`` from ``entity.xero_org_id`` (see
    ``_xero_state``), which lags reality if the user revokes the app from inside
    Xero rather than through our disconnect flow. This verifies against Xero's
    /connections endpoint using the entity's connector token: if that token is
    valid yet the tenant is gone, the connection was revoked remotely, so we
    flip the entity back to the not-connected onboarding state (mirroring
    ``disconnect_entity_xero``, minus the remote DELETE that already happened).

    Best-effort: any failure (no connector, invalid/expired token, Xero
    unreachable) leaves existing state untouched so a transient error never
    falsely drops a live connection.
    """
    if not entity.xero_org_id:
        return

    token_user = get_xero_token_user_for_entity(entity.id)
    if token_user is None:
        # Can't verify (no connector / token couldn't be validated). Don't
        # touch state — a reconnect prompt elsewhere handles the token case.
        return

    try:
        resp = requests.get(
            _XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {token_user.access_token}"},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "onboarding state: Xero /connections check failed for entity %s: %s",
            entity.id, exc,
        )
        return

    if resp.status_code != 200:
        logger.warning(
            "onboarding state: Xero /connections returned %s for entity %s; "
            "preserving existing connection state",
            resp.status_code, entity.id,
        )
        return

    still_connected = any(
        conn.get("tenantId") == str(entity.xero_org_id) for conn in resp.json()
    )
    if still_connected:
        return

    # Confirmed Xero-side revoke: connector token is valid but the tenant is
    # gone. Clear local connection so the wizard shows Xero as not connected.
    entity.status = "onboarding"
    entity.xero_org_id = None
    entity.connected_by_user_id = None
    db.session.commit()
    logger.info(
        "onboarding state: entity %s connection revoked on Xero side; "
        "cleared local connection state",
        entity.id,
    )


def _xero_state(entity: Entity) -> dict:
    """Xero connection picture for the wizard, from the entities row."""
    _reconcile_xero_disconnect(entity)
    connected = bool(entity.xero_org_id)
    return {
        "connected": connected,
        "org": entity.xero_tenant_name or "",
    }


def _account_codes_done(entity_id: str) -> bool:
    """True once the petty-cash account-code mapping has been saved (Step 6).

    The pettycash settings row carries the core mappings; a non-empty
    ``pettycash_account_id`` marks the step as completed.
    """
    row = EntityPettycashSettings.query.filter_by(entity_id=entity_id).first()
    return bool(row and getattr(row, "pettycash_account_id", None))


def _sales_methods_state(entity_id: str) -> dict:
    """Saved petty-cash Sales Setting (Step 5) for resume rehydration.

    Reads the same ``sale_info`` rows the save path writes via
    ``replace_sales_methods``: enabled Electronic/Delivery method names, in the
    display order the wizard rendered them. Shape mirrors the POST
    ``/api/onboarding/sales-methods`` body so the frontend round-trips with no
    translation. Empty lists when nothing has been saved yet.
    """
    methods = (
        EntitySaleSetting.query.filter(
            EntitySaleSetting.entity_id == entity_id,
            EntitySaleSetting.enabled.is_(True),
            EntitySaleSetting.type.in_(["Electronic", "Delivery"]),
        )
        .order_by(EntitySaleSetting.display_order.asc(), EntitySaleSetting.create_date.asc())
        .all()
    )
    return {
        "electronic": [m.sale_name for m in methods if m.type == "Electronic"],
        "delivery": [m.sale_name for m in methods if m.type == "Delivery"],
    }


def _opening_balance_state(entity_id: str) -> dict | None:
    """Saved petty-cash opening balance (Step 5) for resume rehydration.

    Reads the opening ``report_draft`` seeded by ``seed_opening_draft`` (keyed by
    ``company`` = entity_id). Onboarding stores the starting cash in
    ``opening_balance`` (with ``cash_addition`` 0); both are returned so the
    frontend can bind to either. ``None`` when no opening draft exists yet.
    """
    # Read-only: only the balance fields are consumed. Migrated to `report`.
    draft = (
        Report.query.filter(
            Report.company == entity_id,
            Report.status == "draft",
        )
        .order_by(Report.transaction_date.asc())
        .first()
    )
    if draft is None:
        return None
    tx = draft.transaction_date
    return {
        "opening_date": tx.isoformat() if tx else None,
        "opening_balance": draft.opening_balance,
        "cash_addition": draft.cash_addition,
        "adjusted_opening_balance": draft.adjusted_opening_balance,
    }


def _derive_current_step(entity: Entity, modules: list[str], xero: dict,
                         account_codes_done: bool) -> int:
    """Furthest sensible landing step from what's saved in the DB.

    Conservative: we only advance past a step once its data is present, so a
    user who stopped after basic information lands back on the module step
    (the next thing to do), not deep in a half-configured flow. A finalized
    entity (status != onboarding) reports the terminal step.
    """
    if entity.status != "onboarding":
        return STEP_ALL_SET
    if not modules:
        return STEP_MODULE
    if not xero.get("connected"):
        return STEP_ACCOUNTING
    # Xero is connected. Petty-cash configuration (sales / account codes) is the
    # next gate when that module is enabled.
    if MODULE_PETTY_CASH in modules and not account_codes_done:
        return STEP_SALES
    if MODULE_BILL in modules:
        return STEP_BILLS
    return STEP_INVITE


def get_onboarding_state(user_id, entity_id: str) -> tuple[dict, int]:
    """Full resume picture for ``entity_id``, sourced from the DB.

    Returns ``(payload, status)``. 403 if the token's user isn't a member of
    the entity; 404 if it doesn't exist. The payload includes enough to fully
    reconstruct the wizard with no browser storage.
    """
    entity_id = (entity_id or "").strip()
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        return {"error": "You don't have access to this entity"}, 403

    entity = Entity.query.get(entity_id)
    if not entity:
        return {"error": "Entity not found"}, 404

    modules = _enabled_modules(entity_id)
    xero = _xero_state(entity)
    account_codes_done = _account_codes_done(entity_id)
    current_step = _derive_current_step(entity, modules, xero, account_codes_done)
    sales_methods = _sales_methods_state(entity_id)
    opening_balance = _opening_balance_state(entity_id)

    # Pending invites are best-effort: a permission gap there shouldn't break
    # resume, so fall back to an empty list rather than failing the request.
    invites_data, invites_status = list_invites(user_id, entity_id)
    invites = invites_data.get("invitations", []) if invites_status == 200 else []

    payload = {
        "entity_id": entity.id,
        "status": entity.status,
        "current_step": current_step,
        "max_reached": current_step,
        # The wizard step the user last "Saved and Exited" on, returned verbatim
        # (the frontend step id), or null if never set. The wizard resumes here,
        # but only advances past Step 4 when xero.connected is truly true above.
        "saved_step": entity.onboarding_saved_step,
        "entity": {
            "name": entity.name or "",
            # country: ISO alpha-2 code (country_info PK); currency: uuid into
            # currency_info — the wizard's Step 1 dropdowns carry these values
            # (labels come from the registries).
            "country": entity.country_code or "",
            "currency": entity.currency_id or "",
        },
        "modules": modules,
        "xero": xero,
        # Saved petty-cash Sales Setting (Step 5). Shape mirrors the
        # POST /api/onboarding/sales-methods body: {electronic, delivery} of
        # enabled method names (empty lists when nothing saved yet).
        "sales_methods": sales_methods,
        # Saved petty-cash opening balance (Step 5), or null if no opening draft
        # exists yet. Includes both opening_balance and cash_addition so the
        # frontend can bind to either field.
        "opening_balance": opening_balance,
        "invites": invites,
    }
    return payload, 200


def save_onboarding_step(user_id, entity_id: str, saved_step) -> tuple[dict, int]:
    """Persist the wizard's "Save and Exit" step on the entity.

    ``saved_step`` is the frontend step id (1-9) and is stored verbatim — no
    remap to the backend's derived current_step ordering. Same token/membership
    contract as ``get_onboarding_state``: 403 unless the token's user is a member
    of the entity. Returns ``(payload, status)``.
    """
    entity_id = (entity_id or "").strip()
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    try:
        step = int(saved_step)
    except (TypeError, ValueError):
        return {"error": "saved_step must be an integer 1-9"}, 400
    if step < STEP_BASIC or step > STEP_ALL_SET:
        return {"error": "saved_step must be an integer 1-9"}, 400

    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        return {"error": "You don't have access to this entity"}, 403

    entity = Entity.query.get(entity_id)
    if not entity:
        return {"error": "Entity not found"}, 404

    entity.onboarding_saved_step = step
    db.session.commit()
    return {"ok": True, "saved_step": step}, 200
