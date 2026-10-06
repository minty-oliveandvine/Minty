"""Entity module entitlement writes.

The catalog (``entity_function``) defines which modules exist; per-entity
on/off lives in ``entity_function_map``. The resolver in
``blueprints.entity.routes.modules._is_module_enabled`` reads from these
tables. This module is the single place that *writes* to them, so the
onboarding endpoint and the CLI share one path and produce identically
shaped rows (id, audit columns, enabled/disabled timestamps).

Two callers, two helpers:
  * ``apply_module_selection`` — used by onboarding Step 2's single-select.
    Writes BOTH canonical modules in one shot (selected → enabled, the
    others → disabled). Use this whenever the caller has decided the full
    state — it's idempotent and leaves no ambiguity.
  * ``set_entity_module`` — used by the manual override (CLI). Flips ONE
    module without touching the others. Use this for ops-style toggles
    where you don't want to disturb the rest of the entitlement set.

Both helpers commit on success and write explicit rows — never relying on
``entity_function.is_active`` fallback — so the entity's state is always
an unambiguous DB record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from loguru import logger

# The entity-side module GATE -- who may use which module, and the writes that grant it.
# Subscription reasoning (cards, the panel, notices, the access sweep) is
# minty-subscription-api's; the few reads Flask still makes are ``subscription.services.store_ro``.
from blueprints.shared.enums import ModuleCode
from models.db import EntityFunction, EntityFunctionMap, db

# Canonical module codes: the ``module_code`` enum (blueprints/shared/enums.py, schema item
# 20). The Payment Request module's code is PAYMENT_REQUEST; ``MODULE_BILL`` keeps its
# historical name so the ~50 call sites read as before. ``billing_plan.code`` still says
# ``BILL`` by decision - minty-subscription-api maps it.
MODULE_PETTY_CASH = ModuleCode.PETTY_CASH.value
MODULE_BILL = ModuleCode.PAYMENT_REQUEST.value
MODULE_CODES: tuple[str, ...] = (MODULE_PETTY_CASH, MODULE_BILL)

# What the multi-module plan is called on screen. The catalog row carries its own
# display_name and that wins; this is the fallback for a catalog that has no bundle
# row yet, and the one place the name is written down.
BUNDLE_DISPLAY_NAME = "Super Minty"

# Why a module row is being written. Not stored (entity_function_map.created_by is the
# person, schema section 4); the paid-subscription guard in ``set_entity_module`` keys on
# ``actor == ACTOR_SUBSCRIPTION`` and the callers still say who they are.
ACTOR_ONBOARDING = "onboarding"
ACTOR_CLI = "cli"
ACTOR_ENTITY_CREATE = "entity_create"
ACTOR_SUBSCRIPTION = "subscription"

# Default entitlement for a freshly created entity (non-onboarding path): nothing.
# Access is a projection of the module's entity_module_subscription row, so a brand
# new entity holds no module until a trial or a subscription starts one — which is
# what writes the row and then flips the flag through ``_set_module_access``.
#
# This used to grant Petty Cash outright. Nothing revoked it (the sweep skips modules
# with no subscription row), so every entity ever created kept Petty Cash for free
# while its card still offered "Start free trial" — the two read different tables.
DEFAULT_MODULE_STATE: dict[str, bool] = {
    MODULE_PETTY_CASH: False,
    MODULE_BILL: False,
}

# Presentation metadata that isn't stored in the catalog table: marketing
# assets, pricing copy, and the "learn more" link. ``name`` and ``description``
# are NOT here — those come from entity_function (function_name / description).
# Keyed by canonical module code; keep in sync with MODULE_CODES when a new
# module is introduced.
# Per-module presentation metadata that has no source of truth elsewhere: the
# card illustration and the "Learn more" link. Prices and labels are NOT here —
# amounts come from billing_plan (services.catalog) and labels from entity_function
# (EntityFunction.function_name).
MODULE_DISPLAY: dict[str, dict] = {
    MODULE_PETTY_CASH: {
        "image": "img/cash_reg.webp",
        "learn_more": "https://youtu.be/kMs85hnvwFw?si=4Yt6WHeFIYVkNLPK",
    },
    MODULE_BILL: {
        "image": "img/payment-icon.png",
        "learn_more": "https://youtu.be/v7G6gaGO0V0?si=P7-aWHPa9p4jDlHS",
    },
}

def _enabled_state(entity_id: str) -> dict[str, bool]:
    """Resolve each canonical module's on/off state for an entity.

    Mirrors ``_is_module_enabled`` exactly, including its fail-closed default:
    map row → OFF. Anything else would let this helper and the request gate
    disagree about the same entity. Returns {code: bool} for every code in
    MODULE_CODES so callers get a complete, stable picture.
    """
    catalog_by_code = {
        fn.function_code: fn
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }
    fn_ids = [fn.id for fn in catalog_by_code.values()]
    maps_by_fn_id = {}
    if fn_ids:
        maps_by_fn_id = {
            row.entity_function_id: row
            for row in EntityFunctionMap.query.filter(
                EntityFunctionMap.entity_id == entity_id,
                EntityFunctionMap.entity_function_id.in_(fn_ids),
            ).all()
        }

    state: dict[str, bool] = {}
    for code in MODULE_CODES:
        fn = catalog_by_code.get(code)
        row = maps_by_fn_id.get(fn.id) if fn else None
        if row is not None:
            state[code] = bool(row.is_enabled)
        else:
            # No explicit grant — and the catalog's is_active says whether a module
            # is offered at all, never who may use it. Deny.
            state[code] = False
    return state


def get_enabled_modules_for_entities(entity_ids: list[str]) -> dict[str, set[str]]:
    """Map each entity id to the set of module codes that are enabled for it.

    Built on ``_enabled_state`` so it shares the same fail-closed default
    (map row → OFF). Used at onboarding finalize to decide which modules get a
    card-free trial — the wizard's Step 2 selection always writes explicit rows,
    so nothing here depends on a fallback.
    """
    result: dict[str, set[str]] = {}
    for entity_id in entity_ids:
        state = _enabled_state(entity_id)
        result[entity_id] = {code for code, on in state.items() if on}
    return result




def module_display_names(codes) -> dict[str, str]:
    """Human labels for module codes, from the catalog — ``{code: name}``.

    ``entity_function.function_name`` is the source of truth for what a module is
    called in the app (MODULE_DISPLAY deliberately holds no names), so the label is
    read rather than hardcoded. Codes with no catalog row fall back to the code, the
    same last resort ``get_module_cards`` uses.
    """
    codes = {(c or "").upper() for c in codes if c}
    if not codes:
        return {}
    try:
        rows = EntityFunction.query.filter(
            EntityFunction.function_code.in_(codes)
        ).all()
    except Exception:
        db.session.rollback()
        logger.exception("modules: could not read module display names")
        return {code: code for code in codes}
    by_code = {
        (r.function_code or "").upper(): (r.function_name or "").strip()
        for r in rows
    }
    return {code: (by_code.get(code) or code) for code in codes}


#: Session key holding the entity ids whose notice has already been shown this login.
NOTICE_SEEN_SESSION_KEY = "subscription_notice_seen"

#: Session key holding an id for the CURRENT sign-in, rewritten on every login.
#:
#: Exists so that "once per login" can mean the same thing in the Module 2 frontend,
#: which cannot see this session at all — it authenticates to Minty with a bearer
#: token and no cookie. The id rides along as a JWT claim, and the frontend keys its
#: own per-tab flag by it, so signing out and back in resets that flag too. Without
#: it the frontend's flag was per-TAB: re-logging in without closing the tab left the
#: notice suppressed, while the dashboard correctly showed it again.
#:
#: It is an opaque random value, not a session identifier anyone can authenticate
#: with — it only ever answers "is this the same sign-in as before".
LOGIN_SID_SESSION_KEY = "login_sid"


def claim_subscription_notice(session, entity_id: str) -> bool:
    """Whether the dashboard shows the subscription notice now - and if so, mark it shown.

    Once per entity per login: not once per page view, and not once forever - a user who
    comes back tomorrow should be told if it is still broken. Consuming rather than
    reading is what keeps the cost bearable: the notice is fetched from the subscription
    API only when this returns True.

    Takes the session as a parameter so it is testable with a plain dict.
    """
    if not entity_id:
        return False
    seen = session.get(NOTICE_SEEN_SESSION_KEY) or []
    if str(entity_id) in seen:
        return False
    # Reassign rather than mutate in place: Flask's session only marks itself dirty on
    # __setitem__, so appending to the existing list would not persist.
    session[NOTICE_SEEN_SESSION_KEY] = [*seen, str(entity_id)]
    return True






def apply_module_selection(
    entity_id: str, selected_code: str, *, actor: str, user_id: str | None = None
) -> tuple[dict, int]:
    """Set this entity's modules from a single-select choice.

    Selected → is_enabled=True, every other registered module → is_enabled=False.
    Returns ({"modules": {code: bool}}, status).
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400
    if selected_code not in MODULE_CODES:
        return (
            {"error": f"Unknown module code: {selected_code!r}. Expected one of {list(MODULE_CODES)}."},
            400,
        )

    pairs = {code: (code == selected_code) for code in MODULE_CODES}
    return _write_pairs(entity_id, pairs, actor=actor, user_id=user_id)


def apply_module_selections(
    entity_id: str, selected_codes, *, actor: str, user_id: str | None = None
) -> tuple[dict, int]:
    """Set this entity's modules from a multi-select choice.

    Each code in ``selected_codes`` → is_enabled=True; every other registered
    module → is_enabled=False. Same shape as ``apply_module_selection`` but
    accepts an iterable so onboarding Step 2 can enable both modules at once.
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    selected = {str(c).strip().upper() for c in (selected_codes or []) if c}
    if not selected:
        return {"error": "Select at least one module."}, 400

    unknown = sorted(selected - set(MODULE_CODES))
    if unknown:
        return (
            {"error": f"Unknown module code(s): {unknown}. Expected one of {list(MODULE_CODES)}."},
            400,
        )

    pairs = {code: (code in selected) for code in MODULE_CODES}
    return _write_pairs(entity_id, pairs, actor=actor, user_id=user_id)


def apply_default_modules(
    entity_id: str, *, actor: str = ACTOR_ENTITY_CREATE, user_id: str | None = None
) -> tuple[dict, int]:
    """Seed a new entity's module entitlements with the default state.

    Used by the non-onboarding entity-create path so ``entity_function_map``
    is always populated at creation time — with every module OFF. Creation
    grants nothing: a module switches on when its trial or subscription starts.
    Writes explicit rows for every canonical module via ``_write_pairs``, so
    it's idempotent — onboarding Step 2 can later override the selection
    without producing duplicate or ambiguous rows.
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    return _write_pairs(entity_id, dict(DEFAULT_MODULE_STATE), actor=actor, user_id=user_id)


def _module_has_paid_subscription(entity_id: str, code: str) -> bool:
    """True if the module is BILLED, so it must be cancelled through billing rather
    than switched off here — otherwise access and payment fall out of step.

    Trialing modules are intentionally NOT counted: a card-free trial can be toggled
    off freely, because nothing is being charged for it.

    Answered from Minty's own mirror rather than live Stripe. Two behavioural notes:

    * a PAST-DUE module now counts as paid. Stripe reports it as ``past_due`` rather
      than ``active``, so the old check let it be toggled off — bypassing billing on
      exactly the accounts where money is already in question;
    * a cancelled module still inside its paid extension also counts, matching Stripe's
      ``active`` + ``cancel_at_period_end``. A cancelled TRIAL shares that phase but has
      never been charged, so it stays freely toggleable (see ``store_ro.module_is_paid``).
    """
    from blueprints.subscription.services import store_ro

    return store_ro.module_is_paid(entity_id, code)


def set_entity_module(
    entity_id: str, code: str, enabled: bool, *, actor: str, user_id: str | None = None
) -> tuple[dict, int]:
    """Flip one module on/off for an entity without touching the others.

    The subscription sync (``actor="subscription"``) is authoritative on access
    and bypasses the paid-subscription guard so a cancellation/lapse read from
    Stripe can still turn a module off.
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400
    if code not in MODULE_CODES:
        return (
            {"error": f"Unknown module code: {code!r}. Expected one of {list(MODULE_CODES)}."},
            400,
        )

    # A module with a paid subscription can't be disabled from the UI — access
    # follows billing, so it's cancelled via the billing portal (which then
    # revokes access through the subscription webhook).
    if (
        not enabled
        and actor != ACTOR_SUBSCRIPTION
        and _module_has_paid_subscription(entity_id, code)
    ):
        return (
            {
                "error": "This module has an active subscription. Cancel it from "
                "billing before disabling the module."
            },
            409,
        )

    return _write_pairs(entity_id, {code: bool(enabled)}, actor=actor, user_id=user_id)


def _write_pairs(
    entity_id: str, pairs: Mapping[str, bool], *, actor: str, user_id: str | None = None
) -> tuple[dict, int]:
    """Upsert one row per (entity_id, function_code) in ``pairs``.

    Existing rows are mutated in place so audit history (created_at /
    created_by) is preserved; only enabled_at or disabled_at is bumped on
    actual state changes, and updated_at is bumped every write.

    ``user_id`` is the person doing it and lands in ``created_by`` on a NEW row; None
    (the CLI, the subscription sync, a seed) leaves it NULL. ``actor`` is the reason and
    is not stored - see ACTOR_*.
    """
    del actor  # behaviour is keyed on it by the callers; the row does not record it
    now = datetime.now(timezone.utc)
    codes = list(pairs.keys())

    catalog = (
        EntityFunction.query.filter(EntityFunction.function_code.in_(codes)).all()
    )
    catalog_by_code = {fn.function_code: fn for fn in catalog}
    missing = [c for c in codes if c not in catalog_by_code]
    if missing:
        # Catalog hasn't been seeded yet — the migration that seeds it is the
        # prerequisite, not silent self-healing here.
        return (
            {"error": f"Module catalog missing rows for: {missing}. Run the seed migration."},
            500,
        )

    fn_ids = [fn.id for fn in catalog]
    existing = EntityFunctionMap.query.filter(
        EntityFunctionMap.entity_id == entity_id,
        EntityFunctionMap.entity_function_id.in_(fn_ids),
    ).all()
    by_fn_id = {row.entity_function_id: row for row in existing}

    for code, enabled in pairs.items():
        fn = catalog_by_code[code]
        row = by_fn_id.get(fn.id)
        if row is None:
            row = EntityFunctionMap(
                entity_id=entity_id,
                entity_function_id=fn.id,
                is_enabled=enabled,
                enabled_at=now if enabled else None,
                disabled_at=None if enabled else now,
                created_by=str(user_id) if user_id else None,
                created_at=now,
                updated_at=now,
            )
            db.session.add(row)
        else:
            if row.is_enabled != enabled:
                if enabled:
                    row.enabled_at = now
                else:
                    row.disabled_at = now
                row.is_enabled = enabled
            row.updated_at = now

    db.session.commit()

    # Return the full canonical-module state so callers (and clients) get a
    # single consistent shape regardless of which helper they called.
    final_rows = EntityFunctionMap.query.filter(
        EntityFunctionMap.entity_id == entity_id,
        EntityFunctionMap.entity_function_id.in_([fn.id for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()]),
    ).all()
    code_by_fn_id = {
        fn.id: fn.function_code
        for fn in EntityFunction.query.filter(EntityFunction.function_code.in_(MODULE_CODES)).all()
    }
    state = {code: False for code in MODULE_CODES}
    for row in final_rows:
        code = code_by_fn_id.get(row.entity_function_id)
        if code:
            state[code] = bool(row.is_enabled)

    return {"modules": state}, 200