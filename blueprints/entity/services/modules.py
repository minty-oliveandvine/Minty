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
from datetime import datetime, timedelta, timezone
from typing import Mapping

from loguru import logger

# Nothing here formats money or dates any more, and nothing imports ``Decimal``: the code
# that did went to ``subscription.services`` (``money``, ``display``, ``cards``, ``panel``,
# ``notices``, ``access_sweep``). What is left is the entity-side module GATE -- who may
# use which module, and the writes that grant it.
from models.db import EntityFunction, EntityFunctionMap, db

# Canonical module codes. Keep in sync with the catalog seed in
# migration b8f3a2c1d4e5_seed_modules_and_backfill.
MODULE_PETTY_CASH = "PETTY_CASH"
MODULE_BILL = "BILL"
MODULE_CODES: tuple[str, ...] = (MODULE_PETTY_CASH, MODULE_BILL)

# How long after ``trial_end`` a trial the subscription pass has not closed out yet still
# presents as a trial being finalised rather than as one that expired.
#
# Six hours against an hourly pass: wide enough to cover a missed run, a deploy, or a host
# that was busy, and far too narrow to cover an environment where nothing runs at all.
# That second half is the point. Without a bound, every stale trial on a system with no
# scheduler matches forever — which is precisely what production is until the scheduler is
# enabled there.
TRIAL_CLOSING_WINDOW = timedelta(hours=6)

# What the multi-module plan is called on screen. The catalog row carries its own
# display_name and that wins; this is the fallback for a catalog that has no bundle
# row yet, and the one place the name is written down.
BUNDLE_DISPLAY_NAME = "Super Minty"

# Audit-trail values for entity_function_map.created_by (column is 36 chars).
ACTOR_ONBOARDING = "onboarding"
ACTOR_CLI = "cli"
ACTOR_ENTITY_CREATE = "entity_create"

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

# How money and dates are PRINTED is not this module's business, and the five helpers that
# used to sit here have gone to the two modules that own those questions:
#
#   _currency_symbol        -> money.symbol
#   _normalize_price_amount -> money.to_major
#   _fmt_money              -> money.format_trimmed
#   _fmt_day_month_year     -> display.day          (unpadded: prose)
#   _fmt_day_month          -> display.day_month
#
# The first two were already one-line delegations by the time they moved; the other three
# carried real logic. Nothing outside this file called any of them, and nothing that
# remains here needs them -- they served only the card/panel/catalogue code, which is
# itself on its way out (see ``subscription.services.notices`` and ``access_sweep`` for
# the pieces already gone).


def _entity_customer_id(entity_id) -> str | None:
    """The entity's Stripe customer id from local tables (None if it has no customer).

    LOCAL READS ONLY, deliberately — do NOT swap this for
    ``checkout._resolve_customer_id``. That helper falls back to a Stripe Customer
    Search when the mapping row is missing, which is right on the billing paths (being
    wrong there mints a duplicate customer or revokes a paid module) but wrong here:
    this feeds the settings-page card render, so a payer who genuinely has no customer
    would fire a search on EVERY page load and always find nothing. The old
    ``stripe_state`` route got away with it by memoizing per request; nothing memoizes
    now.

    The cost of being wrong here is only that the card reads "no payment method", which
    is also what it says for a payer with no customer at all. If that ever needs to be
    exact, resolve it once at the billing seam and pass it in.
    """
    if not entity_id:
        return None
    # entity -> payer -> customer. The customer belongs to the PAYER (a user), not to
    # the entity, because one payer's card covers every entity they own.
    from blueprints.subscription.services import store as sub_store

    payer_id = sub_store.payer_for_entity(entity_id)
    return sub_store.customer_id_for_user(payer_id) if payer_id else None


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


# The module cards moved to ``subscription.services.cards``. Re-exported: ``routes/settings.py``
# imports this name from here inside the request, and ``notices`` reaches it through this
# module too.
def get_module_cards(entity_id: str) -> list[dict]:
    from blueprints.subscription.services.cards import get_module_cards as _cards

    return _cards(entity_id)


# Re-exported despite being private, because ``test_conversion_forecast.py`` calls it on
# THIS module by name -- fourteen tests over what a converting trial is actually charged,
# which is worth more than the tidiness of dropping an underscore-prefixed re-export.
def _forecast_conversion_charges(entity_id, payer_id, billed_now, cards):
    from blueprints.subscription.services.cards import _forecast_conversion_charges as _f

    return _f(entity_id, payer_id, billed_now, cards)


# Moved to ``subscription.services.panel`` / ``.cards``. Re-exported because every one of
# these is called on THIS module by name -- ``routes/settings.py`` and ``routes/create.py``
# import them here inside the request, and the suite reaches them the same way.
def get_subscription_summary(entity_id: str) -> dict:
    from blueprints.subscription.services.panel import get_subscription_summary as _f

    return _f(entity_id)


def get_billing_anchor(entity_id: str) -> str | None:
    from blueprints.subscription.services.panel import get_billing_anchor as _f

    return _f(entity_id)


def next_payment_from_panel(panel: dict | None) -> str | None:
    from blueprints.subscription.services.panel import next_payment_from_panel as _f

    return _f(panel)


def get_next_payment_date(entity_id: str) -> str | None:
    from blueprints.subscription.services.panel import get_next_payment_date as _f

    return _f(entity_id)


def build_consent_takeover(entity_id, user_id, *, can_manage: bool, access_state=None):
    from blueprints.subscription.services.panel import build_consent_takeover as _f

    return _f(entity_id, user_id, can_manage=can_manage, access_state=access_state)


def get_module_plan_catalog() -> dict:
    from blueprints.subscription.services.cards import get_module_plan_catalog as _f

    return _f()


def get_trial_modules_for_entities(entity_ids: list[str]) -> dict[str, set[str]]:
    from blueprints.subscription.services.cards import get_trial_modules_for_entities as _f

    return _f(entity_ids)


# The subscription panel moved to ``subscription.services.panel``. Re-exported because
# ``routes/settings.py`` imports it from here inside the request, and three tests call
# ``modules.build_subscription_panel`` directly.
def build_subscription_panel(cards, summary, anchor_display):
    from blueprints.subscription.services.panel import build_subscription_panel as _panel

    return _panel(cards, summary, anchor_display)


# How close a converting trial has to be before it is worth mentioning, or None to
# mention it for the whole trial. None is deliberate: a running trial has a first
# charge coming, and a customer who is told the date on day one cannot say they were
# never told. Nothing else in the notice is time-windowed either — past due, a trial
# that will not convert, and a wind-down are all shown whenever they are true.
#
# Set to an int (7 was the previous value) to go back to only warning near the end.
TRIAL_ENDING_SOON_DAYS: int | None = None

# Ordering for the notice list, most severe first. The modal shows every item that
# applies rather than picking one — a company can be past due on one module and
# winding down another, and hiding the second would be a lie of omission.
_NOTICE_ORDER = ("past_due", "needs_card", "needs_consent", "pending_cancel", "trial_ending")


# The dashboard notice moved to ``subscription.services.notices`` -- deciding a company
# is past due or winding down is subscription reasoning. Re-exported rather than
# repointed: importers name THIS module (some binding at import, some per request), and
# the moved code reads its inputs back off here at call time so the suite's patches on
# ``modules.TRIAL_ENDING_SOON_DAYS`` and ``modules.get_module_cards`` still bite.
def claim_subscription_notice(session, entity_id: str) -> bool:
    from blueprints.subscription.services.notices import claim_subscription_notice as _claim

    return _claim(session, entity_id)


def build_subscription_notices(entity_id: str, user_id) -> dict:
    from blueprints.subscription.services.notices import build_subscription_notices as _build

    return _build(entity_id, user_id)


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
    is always populated at creation time — with every module OFF. Creation
    grants nothing: a module switches on when its trial or subscription starts.
    Writes explicit rows for every canonical module via ``_write_pairs``, so
    it's idempotent — onboarding Step 2 can later override the selection
    without producing duplicate or ambiguous rows.
    """
    if not entity_id:
        return {"error": "entity_id is required"}, 400

    return _write_pairs(entity_id, dict(DEFAULT_MODULE_STATE), actor=actor)


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
      never been charged, so it stays freely toggleable (see ``access.is_paid_module``).
    """
    from blueprints.subscription.services import access, store

    row = store.module_row(entity_id, (code or "").strip().upper())
    if row is None:
        return False
    return access.is_paid_module(
        phase=row.phase,
        has_been_billed=row.first_billed_at is not None,
    )


def set_entity_module(
    entity_id: str, code: str, enabled: bool, *, actor: str
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
        and actor != "subscription"
        and _module_has_paid_subscription(entity_id, code)
    ):
        return (
            {
                "error": "This module has an active subscription. Cancel it from "
                "billing before disabling the module."
            },
            409,
        )

    return _write_pairs(entity_id, {code: bool(enabled)}, actor=actor)


# The daily access reconciler moved to ``subscription.services.access_sweep`` -- it is
# subscription work and every one of its callers lives there. Re-exported rather than
# repointed: importers and the suite's monkeypatches both name THIS module, and the moved
# code reads these two back off it at call time, so the patches still bite.
from blueprints.subscription.services.access_sweep import (  # noqa: E402, F401
    _notify_access_revoked, sweep_expired_module_access)


def _entity_names_for_sweep(entity_ids) -> dict[str, str]:
    """{entity_id: name} in one query. Empty on failure — a missing name costs the email
    a company name; a raised exception would cost the sweep its run.
    """
    if not entity_ids:
        return {}
    try:
        from models.db import Entity

        rows = Entity.query.filter(Entity.id.in_([str(i) for i in entity_ids])).all()
        return {str(e.id): (e.name or "").strip() for e in rows if (e.name or "").strip()}
    except Exception:
        logger.exception("modules: could not resolve entity names for notification")
        return {}


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