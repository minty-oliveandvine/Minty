"""Server-side onboarding resume state.

The onboarding wizard (separate Next.js repo) has no database access and, on a
cold resume (new browser / incognito / cleared storage / different device), has
no localStorage to rehydrate from. The ``entities`` row — not the browser — is
the source of truth for an in-progress onboarding, so this module reconstructs
the whole wizard picture from the DB and the wizard treats localStorage as a
cache only.

``get_onboarding_state`` returns everything the wizard needs to land on the
correct step bound to ``entity_id`` without any browser storage: the entity's
basic info, selected modules, Xero connection, pending invites, and a derived
``current_step`` / ``max_reached``.

Same token/membership contract as the other ``/api/onboarding/*`` services: the
caller is the JWT's user_id; access is denied (403) unless that user is a member
of the entity.
"""

from __future__ import annotations

from blueprints.entity.services.modules import (MODULE_BILL, MODULE_CODES,
                                                MODULE_PETTY_CASH)
from blueprints.entity.services.onboarding_invites import list_invites
from models.db import (Entity, EntityFunction, EntityFunctionMap,
                       EntityPettycashSettings, UserEntity)

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


def _xero_state(entity: Entity) -> dict:
    """Xero connection picture for the wizard, from the entities row."""
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

    # Pending invites are best-effort: a permission gap there shouldn't break
    # resume, so fall back to an empty list rather than failing the request.
    invites_data, invites_status = list_invites(user_id, entity_id)
    invites = invites_data.get("invitations", []) if invites_status == 200 else []

    payload = {
        "entity_id": entity.id,
        "status": entity.status,
        "current_step": current_step,
        "max_reached": current_step,
        "entity": {
            "name": entity.name or "",
            "country": entity.country_code or "",
            "currency": entity.currency_code or "",
        },
        "modules": modules,
        "xero": xero,
        "invites": invites,
    }
    return payload, 200
