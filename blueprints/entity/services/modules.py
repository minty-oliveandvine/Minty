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

import uuid
from datetime import datetime, timezone
from typing import Mapping

from models.db import EntityFunction, EntityFunctionMap, db

# Canonical module codes. Keep in sync with the catalog seed in
# migration b8f3a2c1d4e5_seed_modules_and_backfill.
MODULE_PETTY_CASH = "PETTY_CASH"
MODULE_BILL = "BILL"
MODULE_CODES: tuple[str, ...] = (MODULE_PETTY_CASH, MODULE_BILL)

# Audit-trail values for entity_function_map.created_by (column is 36 chars).
ACTOR_ONBOARDING = "onboarding"
ACTOR_CLI = "cli"
ACTOR_ENTITY_CREATE = "entity_create"

# Default entitlement for a freshly created entity (non-onboarding path):
# Petty Cash on, Bill off. Mirrors the catalog defaults and the backfill.
DEFAULT_MODULE_STATE: dict[str, bool] = {
    MODULE_PETTY_CASH: True,
    MODULE_BILL: False,
}

# Presentation metadata that isn't stored in the catalog table: marketing
# assets, pricing copy, and the "learn more" link. ``name`` and ``description``
# are NOT here — those come from entity_function (function_name / description).
# Keyed by canonical module code; keep in sync with MODULE_CODES when a new
# module is introduced.
MODULE_DISPLAY: dict[str, dict] = {
    MODULE_PETTY_CASH: {
        "image": "img/cash_reg.webp",
        "price": "280 HKD per Month",
        "price_amount": 280,
        "summary_label": "Petty cash module",
        "learn_more": "https://youtu.be/kMs85hnvwFw?si=4Yt6WHeFIYVkNLPK",
    },
    MODULE_BILL: {
        "image": "img/payment-icon.png",
        "price": "280 HKD per Month",
        "price_amount": 280,
        "summary_label": "Bill module",
        "learn_more": "https://youtu.be/v7G6gaGO0V0?si=P7-aWHPa9p4jDlHS",
    },
}

# Subscription pricing presentation. The currency symbol shown in the
# subscription summary, and the bulk discount applied when the entity
# subscribes to more than one module (mirrors the Discount_coupon catalog).
SUBSCRIPTION_CURRENCY = "HK$"
BULK_DISCOUNT_AMOUNT = 160


def _enabled_state(entity_id: str) -> dict[str, bool]:
    """Resolve each canonical module's on/off state for an entity.

    Mirrors ``_is_module_enabled``'s backward-compatible fallback:
    map row → catalog is_active → True. Returns {code: bool} for every
    code in MODULE_CODES so callers get a complete, stable picture.
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
        elif fn is not None:
            state[code] = bool(fn.is_active)
        else:
            state[code] = True
    return state


def get_module_cards(entity_id: str) -> list[dict]:
    """Build the module-settings cards for an entity, backend-driven.

    Merges three sources into one card per canonical module:
      * per-entity state — entity_function_map.is_enabled / disabled_at;
      * catalog copy — entity_function.function_name / description (the code
        itself is the last-resort fallback when the catalog row is missing);
      * presentation metadata — MODULE_DISPLAY (image, price, learn_more).

    Cards come back in the canonical MODULE_CODES order so the UI is stable
    regardless of DB row order. Enabled state mirrors ``_is_module_enabled``'s
    backward-compatible fallback (map row → catalog is_active → True).
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

    cards: list[dict] = []
    for code in MODULE_CODES:
        display = MODULE_DISPLAY.get(code, {})
        fn = catalog_by_code.get(code)
        row = maps_by_fn_id.get(fn.id) if fn else None

        if row is not None:
            enabled = bool(row.is_enabled)
        elif fn is not None:
            enabled = bool(fn.is_active)
        else:
            enabled = True

        # Only meaningful while the module is disabled (the UI hides the
        # cancellation block otherwise). Formatted without strftime's %-d so it
        # renders the same on Windows and Linux.
        cancellation_date = ""
        if row is not None and row.disabled_at:
            cancellation_date = (
                f"{row.disabled_at.day} {row.disabled_at.strftime('%b %Y')}"
            )

        cards.append(
            {
                "code": code,
                "name": (fn.function_name if fn and fn.function_name else code),
                "description": (fn.description if fn and fn.description else ""),
                "image": display.get("image", ""),
                "price": display.get("price", ""),
                "learn_more": display.get("learn_more", "#"),
                "is_enabled": enabled,
                "cancellation_date": cancellation_date,
            }
        )
    return cards


def get_subscription_summary(entity_id: str) -> dict:
    """Build the subscription cost summary shown beside the module cards.

    One line per *enabled* canonical module priced from MODULE_DISPLAY, a bulk
    discount when more than one module is enabled, and the resulting total. The
    summary tracks the per-module on/off toggle state — disabling a module via
    its toggle removes it from the summary and its cost from the total.

    Returns a dict shaped for the template:
        {currency, lines: [{label, amount}], subtotal,
         bulk_discount, total, has_discount}
    """
    catalog_by_code = {
        fn.function_code: fn
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }
    enabled = _enabled_state(entity_id)

    lines: list[dict] = []
    for code in MODULE_CODES:
        if not enabled.get(code):
            continue
        display = MODULE_DISPLAY.get(code, {})
        fn = catalog_by_code.get(code)
        amount = display.get("price_amount", 0)
        label = display.get("summary_label") or (
            fn.function_name if fn and fn.function_name else code
        )
        lines.append({"label": label, "amount": amount})

    subtotal = sum(line["amount"] for line in lines)
    bulk_discount = BULK_DISCOUNT_AMOUNT if len(lines) > 1 else 0
    total = subtotal - bulk_discount

    return {
        "currency": SUBSCRIPTION_CURRENCY,
        "lines": lines,
        "subtotal": subtotal,
        "bulk_discount": bulk_discount,
        "total": total,
        "has_discount": bulk_discount > 0,
    }


def apply_module_selection(
    entity_id: str, selected_code: str, *, actor: str
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
    return _write_pairs(entity_id, pairs, actor=actor)


def apply_module_selections(
    entity_id: str, selected_codes, *, actor: str
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
    return _write_pairs(entity_id, pairs, actor=actor)


def apply_default_modules(
    entity_id: str, *, actor: str = ACTOR_ENTITY_CREATE
) -> tuple[dict, int]:
    """Seed a new entity's module entitlements with the default state.

    Used by the non-onboarding entity-create path so ``entity_function_map``
    is always populated at creation time (Petty Cash enabled, Bill disabled).
    Writes explicit rows for every canonical module via ``_write_pairs``, so
    it's idempotent — onboarding Step 2 can later override the selection
    without producing duplicate or ambiguous rows.
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    return _write_pairs(entity_id, dict(DEFAULT_MODULE_STATE), actor=actor)


def set_entity_module(
    entity_id: str, code: str, enabled: bool, *, actor: str
) -> tuple[dict, int]:
    """Flip one module on/off for an entity without touching the others."""
    if not entity_id:
        return {"error": "entity_id is required"}, 400
    if code not in MODULE_CODES:
        return (
            {"error": f"Unknown module code: {code!r}. Expected one of {list(MODULE_CODES)}."},
            400,
        )

    return _write_pairs(entity_id, {code: bool(enabled)}, actor=actor)


def _write_pairs(
    entity_id: str, pairs: Mapping[str, bool], *, actor: str
) -> tuple[dict, int]:
    """Upsert one row per (entity_id, function_code) in ``pairs``.

    Existing rows are mutated in place so audit history (created_at /
    created_by) is preserved; only enabled_at or disabled_at is bumped on
    actual state changes, and updated_at is bumped every write.
    """
    now = datetime.now(timezone.utc)
    actor_trim = (actor or "")[:36]
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
                id=str(uuid.uuid4()),
                entity_id=entity_id,
                entity_function_id=fn.id,
                is_enabled=enabled,
                enabled_at=now if enabled else None,
                disabled_at=None if enabled else now,
                created_by=actor_trim,
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