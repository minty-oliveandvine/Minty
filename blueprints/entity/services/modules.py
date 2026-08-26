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
from decimal import Decimal
from typing import Mapping

from loguru import logger

from blueprints.entity.models.currency_info import CurrencyInfo
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

def _currency_symbol(currency_code: str | None) -> str:
    """Display symbol for a currency code, from ``currency_info``.

    Falls back to the upper-cased code itself (e.g. "HKD") when no symbol is
    recorded, and to "" when there's no currency code at all. The symbol is the
    one shown in the subscription summary — never hardcoded.
    """
    if not currency_code:
        return ""
    currency = CurrencyInfo.query.filter_by(currency_code=currency_code).first()
    if currency and currency.symbol:
        return currency.symbol
    return currency_code.upper()


def _normalize_price_amount(amount, currency_code=None) -> Decimal:
    """Convert a minor-unit amount to a display decimal.

    HKD: 28000 -> 280.00; JPY: 280 -> 280.

    Delegates to ``subscription.services.money`` so the card, the invoice memo and the
    first-charge dialog all scale money the same way. This function had the rule right
    while those two divided by a hardcoded 100 — the divergence money.py now closes. It
    also caches the lookup per request, which this did not.
    """
    from blueprints.subscription.services import money

    if amount is None:
        return Decimal("0")
    return money.to_major(amount, currency_code)


def _fmt_day_month(dt) -> str | None:
    """'19 Aug' — day with no leading zero, formatted cross-platform (no %-d/%#d)."""
    return f"{dt.day} {dt.strftime('%b')}" if dt else None


def _fmt_day_month_year(dt) -> str | None:
    """'19 Aug 2026'."""
    return f"{dt.day} {dt.strftime('%b %Y')}" if dt else None


def _fmt_money(symbol: str, amount, places: int = 2) -> str:
    """'HK$400' when whole, 'HK$400.50' when not — cents only shown when they matter.

    ``places`` is the currency's decimal places (``money.decimal_places``). It was fixed
    at 2, which rounds a 3-decimal currency wrong and invents a ".00" on a zero-decimal
    one. ``amount`` is already in MAJOR units — callers normalize first.

    A CODE is spaced off the number, a glyph is not: "HKD 400", but "HK$400". The
    leading token is whatever ``_currency_symbol`` resolved, which falls back to the
    bare code when ``currency_info`` records no symbol — and in practice it doesn't,
    so the panel read "HKD400". Same rule the onboarding app's ``money()`` applies.
    """
    space = " " if symbol[-1:].isalpha() else ""
    if places <= 0:
        return f"{symbol}{space}{int(Decimal(amount).to_integral_value()):,}"
    q = Decimal(amount).quantize(Decimal(1).scaleb(-places))
    if q == q.to_integral_value():
        return f"{symbol}{space}{int(q):,}"
    return f"{symbol}{space}{q:,.{places}f}"


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


def get_trial_modules_for_entities(entity_ids: list[str]) -> dict[str, set[str]]:
    """Map each entity id to the set of module codes currently on a FREE TRIAL.

    One query for the whole list. The per-entity path (``get_module_cards``) answers
    the same question far more thoroughly, but it reads Stripe, the billing policy
    and the payer's cycle for every entity it is asked about — repeating that once
    per row on the "select company" page would put a payment-provider round trip
    behind a page that only wants to draw a badge.

    "On a free trial" is the module card's claim, minus the states a badge cannot
    express:

      * the row was NEVER billed (``first_billed_at is None``) — that is what
        separates a trial from a paid module that is winding down, and both share
        the ``scheduled_cancel`` phase;
      * it is either running (``phase = trial``) or a CANCELLED trial, which stops
        the conversion to paid without ending the free days (see
        ``checkout.cancel_module``) and so is still a trial on screen;
      * the free days have not run out — with the same ``TRIAL_CLOSING_WINDOW``
        slack a running trial gets while it waits for the pass that closes it out,
        so the badge does not blink off in the hour before the job converts it.

    Fail-soft: any error yields no trials rather than an exception. A missing badge
    costs a hint; a raise here costs the user the whole entity list.
    """
    if not entity_ids:
        return {}

    # Imported here, not at module scope: the subscription package imports back into
    # the entity models, and this module is loaded early enough for that to bite.
    from blueprints.subscription.constants import (PHASE_SCHEDULED_CANCEL,
                                                   PHASE_TRIAL)
    from blueprints.subscription.models.entity_module_subscription import         EntityModuleSubscription
    from blueprints.subscription.services import clock

    try:
        now = clock.now()
        rows = EntityModuleSubscription.query.filter(
            EntityModuleSubscription.entity_id.in_(entity_ids),
            EntityModuleSubscription.first_billed_at.is_(None),
            EntityModuleSubscription.trial_end.isnot(None),
            EntityModuleSubscription.phase.in_((PHASE_TRIAL, PHASE_SCHEDULED_CANCEL)),
        ).all()
    except Exception:
        # The rollback is not optional. On Postgres a failed statement aborts the
        # whole transaction, so swallowing this without resetting the session would
        # turn a cosmetic lookup into a 500 several queries later in the same request.
        db.session.rollback()
        logger.exception("modules: could not read trial state for the entity list")
        return {}

    trials: dict[str, set[str]] = {}
    for row in rows:
        # Precedence rule 1 of ``access.access_end``: the app's own promise outranks
        # the term. A cancelled trial carries its remaining days there.
        ends_at = row.app_access_until or row.trial_end
        if ends_at <= now and not (
            row.phase == PHASE_TRIAL and (now - ends_at) <= TRIAL_CLOSING_WINDOW
        ):
            continue
        trials.setdefault(row.entity_id, set()).add(
            (row.function_code or "").upper()
        )
    return trials


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


def get_module_cards(entity_id: str) -> list[dict]:
    """Build the module-settings cards for an entity, backend-driven.

    Merges three sources into one card per canonical module:
      * catalog copy — entity_function.function_name / description (the code
        itself is the last-resort fallback when the catalog row is missing);
      * presentation metadata — MODULE_DISPLAY (image, learn_more);
      * LIVE Stripe state — the available plan's price, and the entity's
        subscription status / period end / grace-aware access end, read from
        the module rows plus ``access.py`` — one source, so the card and checkout
        cannot disagree about what the entity holds.

    Cards come back in the canonical MODULE_CODES order. Subscription state is
    None when the entity isn't subscribed or Stripe isn't configured.
    """
    from blueprints.subscription.constants import (
        EXT_PENDING,
        PHASE_ACTIVE,
        PHASE_PAST_DUE,
        PHASE_SCHEDULED_CANCEL,
        PHASE_TRIAL,
    )
    from blueprints.subscription.services import access, catalog, clock, money, policy
    from blueprints.subscription.services import store as sub_store

    catalog_by_code = {
        fn.function_code: fn
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }

    from blueprints.subscription.services.stripe_client import (
        customer_default_payment_method,
    )

    customer_id = _entity_customer_id(entity_id)
    plans_by_code = {p.function_code.upper(): p for p in catalog.available_plans()}
    now = clock.now()

    # A trial without a card CANCELS at the end of its term (the card is optional at
    # signup), so those cards get an "add a card to keep this module" nudge. One lookup
    # for the whole page - it is a customer-level fact, not a per-module one.
    has_payment_method = bool(
        customer_id and customer_default_payment_method(customer_id)
    )

    # ...but a card is not sufficient. The payer's card is shared across every entity
    # they pay for, so THIS entity also needs its own billing consent before a trial
    # here may convert to a charge (see checkout._convert_due_trials). An entity with a
    # card but no consent gets the same nudge - otherwise its trial would quietly expire
    # and the user would never learn why.
    try:
        # Asked about the entity's PAYER — the person whose card the nudge is about.
        # After a handover the previous payer's consent is history and says nothing
        # about whether this one has agreed, so a card-but-no-consent entity would
        # otherwise stop showing the nudge and let its trial lapse unexplained.
        has_billing_consent = sub_store.has_billing_consent(
            entity_id, sub_store.payer_for_entity(entity_id)
        )
    except Exception:
        # Best-effort: never fail the page over the nudge. Assume consent so we do not
        # nag someone who has already given it.
        #
        # The rollback is NOT optional. On Postgres a failed statement aborts the whole
        # transaction, and every later query in the request then dies with "current
        # transaction is aborted" - so swallowing the Python exception without resetting
        # the session turns one bad query into a 500 several calls away (it surfaced as
        # an unrelated currency_info lookup failing).
        db.session.rollback()
        logger.exception(
            "modules: could not read billing consent for {}; assuming consent", entity_id
        )
        has_billing_consent = True

    will_convert = has_payment_method and has_billing_consent

    # THE module state, and now the only source of it.
    #
    # This used to merge live Stripe subscription views with these rows, which meant a
    # module's status could be read two ways and the two could disagree: an app-level
    # trial was invisible to Stripe, and a module cancelled out of a bundle had no
    # Stripe view at all because its line had been swapped down. The row plus
    # ``access.py`` answers every question this card asks, from one source.
    rows = {}
    paid_through = None
    payer_id = None
    try:
        rows = {
            row.function_code.upper(): row
            for row in sub_store.module_rows_for_entity(entity_id)
        }
        # What THIS company is paid through, read once. It lives on the card the company
        # is billed on: a payer may hold several, each buying its own periods for its own
        # companies. Not the per-row copy, which drifted apart between a payer's entities
        # because each was only refreshed when its own entity was touched.
        payer_id = next(
            (row.payer_user_id for row in rows.values() if row.payer_user_id), None
        )
        if payer_id:
            paid_through = sub_store.paid_through_for_entity(entity_id)
    except Exception:
        logger.exception("modules: could not read module rows for entity {}", entity_id)

    # What this period was ALREADY PAID FOR. A trial converting alongside these is a
    # mid-period change priced against them; converting with nothing here just starts the
    # cycle. Mirrors checkout._billed_codes_in_house exactly — the forecast and the
    # invoice must not be computed two ways — INCLUDING its treatment of a module that is
    # winding down: cancelled, but paid up to the period end, so for the days before that
    # end it is still on the line and still part of a bundle. Only until the renewal that
    # drops it, though, which is what the extension state and access end below are for:
    # the payer's paid_through moves on without the module, and reading the date alone
    # kept it on the line for a period it was never billed for.
    billed_now = {
        c
        for c, r in rows.items()
        if access.is_covered_this_period(
            phase=getattr(r, "phase", None) or "",
            first_billed_at=getattr(r, "first_billed_at", None),
            paid_through=paid_through,
            now=now,
            extension_state=getattr(r, "extension_state", None),
            app_access_until=getattr(r, "app_access_until", None),
        )
    }

    # Read once for the whole card set, not per module: every card on this page must
    # answer against the same window, and re-reading it per row is a lookup for nothing.
    grace_days = policy.current().past_due_window_days

    # What the request gate would actually answer for this entity right now. The card
    # has to agree with it: a module the user can already open must never render the
    # "Start free trial" button, whatever the subscription rows say.
    try:
        access_state = _enabled_state(entity_id)
    except Exception:
        # Same posture as the consent read above — the page must not 500 over one
        # lookup, and the rollback is what stops a failed statement poisoning the rest
        # of the request on Postgres. Assume NO access: that only ever suppresses a
        # trial button, where assuming access would offer a trial on a module the user
        # is already inside, which is the contradiction this field exists to prevent.
        db.session.rollback()
        logger.exception(
            "modules: could not read module access for {}; assuming none", entity_id
        )
        access_state = {code: False for code in MODULE_CODES}

    cards: list[dict] = []
    for code in MODULE_CODES:
        display = MODULE_DISPLAY.get(code, {})
        fn = catalog_by_code.get(code)
        row = rows.get(code.upper())
        phase = getattr(row, "phase", None) or ""

        granted = row is not None and access.grants_access(
            now,
            phase=phase,
            trial_end=getattr(row, "trial_end", None),
            app_access_until=getattr(row, "app_access_until", None),
            period_end=paid_through,
            past_due_grace_days=grace_days,
        )
        # A CANCELLED trial is still a trial: cancelling one does not end it, it only
        # stops it converting to paid, so the free days keep running (see
        # checkout.cancel_module). It must still present as trialing - otherwise the
        # card reads "Not subscribed" while the user demonstrably still has access.
        # ``first_billed_at`` is what separates it from a cancelled PAID module, which
        # is winding down for an entirely different reason.
        never_billed = getattr(row, "first_billed_at", None) is None
        app_trial_running = bool(row is not None and phase == PHASE_TRIAL and granted)
        app_trial_cancelled = bool(
            row is not None
            and phase == PHASE_SCHEDULED_CANCEL
            and never_billed
            and getattr(row, "trial_end", None) is not None
            and granted
        )
        app_trial = app_trial_running or app_trial_cancelled

        # Whether the request gate would let this entity into the module right now.
        # Normally implied by ``granted`` — access only projects the row — but the two
        # can part company between a write and the sweep that repairs it, and the card
        # must side with the gate.
        has_access = bool(access_state.get(code))

        # THE WINDOW BETWEEN THE TERM ENDING AND THE JOB CLOSING IT OUT.
        #
        # ``trial_end`` passes unattended. Until the subscription pass runs, the row is
        # still ``phase = trial`` while ``granted`` has already gone false — so the card
        # dropped out of "trialing", failed the paid branch too, and landed on
        # ``trial_expired``: it told a customer their free trial was used up while the
        # gate was still letting them work, and while a trial with a card and consent was
        # in fact about to CONVERT. Premature, and for the converting case the opposite of
        # what was coming.
        #
        # Bounded by construction, which is what makes it safe to show. It needs the gate
        # to still say yes, and the next pass ends it either way — close-trials converts
        # or expires the row, and failing that the sweep revokes access because
        # ``grants_access`` is already false. A scheduler that stopped cannot leave a card
        # stuck here; it resolves to the honest ``trial_expired`` as soon as anything runs.
        _trial_end = getattr(row, "trial_end", None)
        app_trial_closing = bool(
            row is not None
            and phase == PHASE_TRIAL
            and not granted
            and has_access
            # BOUNDED BY TIME, and this is the whole safety of the state.
            #
            # It was first written as "phase is trial, access is still on" and justified
            # as self-limiting: the next pass converts or expires the row within the hour,
            # so it could not persist. That is only true where the pass RUNS. On an
            # environment with no scheduler — which production was, and which any
            # environment becomes the moment the scheduler is off — a trial past its term
            # keeps its phase and its access indefinitely, and the unbounded version
            # matched every one of them, forever: a trial that ended three weeks ago
            # rendered as a running trial with a past date, and ``needs_card`` turned on
            # with it, which displaced the billing-portal banner with a nudge quoting a
            # deadline in the past.
            #
            # So the window is explicit. Past it, the trial is not "being closed out", it
            # is simply over and nothing came for it — which is what ``trial_expired`` has
            # always said.
            and _trial_end is not None
            and (now - _trial_end) <= TRIAL_CLOSING_WINDOW
        )
        # Folded into ``app_trial`` rather than given a status of its own. Everything
        # downstream — the panel's enabled set, the notices, the badge, the row styling —
        # asks "is this trialing", and answering differently for the hour before the pass
        # runs would rearrange the whole page around a state the customer cannot act on and
        # which resolves by itself. It IS still a trial: nothing has closed it out. The
        # closing flag is carried separately and used for exactly one thing, a label.
        app_trial = app_trial or app_trial_closing

        # Trial eligibility: a module this entity has NEVER held. The trial is
        # once-per-module, so ANY history disqualifies it - including a lapsed one - and
        # those go through paid checkout instead. The row existing at all IS that
        # history, which is exactly what ``checkout.start_module_trial`` checks.
        #
        # Access with no row disqualifies it too. Offering a trial there produced the
        # contradiction this whole model exists to remove: a clickable "Start free trial"
        # on a module the user was already working inside.
        trial_eligible = fn is not None and row is None and not has_access

        # ...and the other side of that coin: a trial this entity USED UP. It held one,
        # it is over, and nothing was ever charged — so the module is off and cannot be
        # trialled again. "not active" on its own reads as "never had this", which leaves
        # the customer wondering why the card offers Subscribe instead of a free trial.
        # A module whose PAID subscription ended is a different sentence and is excluded
        # by never_billed.
        trial_expired = bool(
            row is not None
            and never_billed
            and getattr(row, "trial_end", None) is not None
            and not granted
            # Not yet: the term is up but the pass has not closed it out, and the customer
            # is still working inside the module. Calling that "expired" is a guess about
            # an outcome that has not been decided — see ``app_trial_closing``.
            and not app_trial_closing
        )

        plan = plans_by_code.get(code.upper())
        amount = (
            _normalize_price_amount(plan.amount, plan.currency_code)
            if plan
            else Decimal(0)
        )

        # Winding down: a scheduled cancellation still inside its paid days, or a
        # renewal that failed and is inside its grace. Both show "access until ... /
        # Renew" rather than Subscribe - offering Subscribe would double-charge, since
        # the queued extension bills on the anchor AND the module is billed afresh.
        winding_down = phase in (PHASE_SCHEDULED_CANCEL, PHASE_PAST_DUE) and granted
        access_end = (
            access.access_end(
                phase=phase,
                trial_end=getattr(row, "trial_end", None),
                app_access_until=getattr(row, "app_access_until", None),
                # From the ACCOUNT, not the row: one payer has one cycle, and the
                # per-row copy drifts apart between their entities.
                period_end=paid_through,
                past_due_grace_days=grace_days,
            )
            if row is not None
            else None
        )
        access_end_date = (
            access_end.strftime("%B %d, %Y")
            if (winding_down and access_end and access_end > now)
            else None
        )
        pending_cancel = bool(access_end_date)

        # What the customer is told about the next date. A trial runs to its term; a
        # paid module runs to what the payer is paid through.
        #
        # ``granted`` gates the paid branch as well as the trial one. The phase alone is
        # not "is this live": a phase stays ``active`` until something writes it, while
        # access ends on a DATE that passes unattended (the sweep is what reconciles the
        # gate afterwards — see sweep_expired_module_access). Reading the phase by itself
        # left a module whose period had lapsed, and whose access had just been swept
        # off, still badged "active" with "valid until <a date in the past>" and a Cancel
        # button — the card claiming a subscription the request gate would refuse.
        if app_trial:
            subscription_status = "trialing"
            period_end = getattr(row, "trial_end", None)
        elif granted and phase in (PHASE_ACTIVE, PHASE_PAST_DUE, PHASE_SCHEDULED_CANCEL):
            subscription_status = "past_due" if phase == PHASE_PAST_DUE else "active"
            period_end = paid_through
        else:
            # Never held it, or held it and lost it. Either way there is nothing live to
            # cancel and the card offers the way back in.
            subscription_status = None
            period_end = None
        formatted_period_end = period_end.strftime("%B %d, %Y") if period_end else None

        cards.append(
            {
                "code": code,
                "name": (fn.function_name if fn and fn.function_name else code),
                "description": (fn.description if fn and fn.description else ""),
                "image": display.get("image", ""),
                "learn_more": display.get("learn_more", "#"),
                # The double-buy guard: a live paid module OR a running trial.
                # ``access.is_subscribed`` owns that rule, so the card and checkout
                # cannot disagree about whether the entity already has this module.
                "is_subscribed": bool(
                    row is not None and access.is_subscribed(phase=phase)
                ),
                "trial_eligible": trial_eligible,
                # The term is up and the pass has not closed it out yet. Presentation
                # ONLY: the card is otherwise a running trial in every respect, and this
                # adds a line saying the outcome is being settled. Never gate behaviour on
                # it — see where it is set.
                "trial_closing": app_trial_closing,
                # Held a trial, used it up, never paid: the card says "free trial
                # expired" under its status so "not active" is not the whole story.
                "trial_expired": trial_expired,
                # The other half of that story: PAID for, and now out of access — with
                # the DATE it ran out, and deliberately without a verdict on why.
                #
                # "Subscription ended" was wrong here. A module whose paid period lapses
                # keeps ``phase = active`` until something writes it (see
                # sweep_expired_module_access), so nothing has ended: nobody cancelled,
                # and the renewal simply never replaced the period. Stating the date is
                # true whether it lapsed, was cancelled to completion, or is waiting on a
                # renewal that has not run.
                "lapsed_long": (
                    _fmt_day_month_year(
                        getattr(row, "app_access_until", None) or paid_through
                    )
                    if (
                        row is not None
                        and not never_billed
                        and not granted
                        and (getattr(row, "app_access_until", None) or paid_through)
                    )
                    else None
                ),
                # What the request gate answers for this module. The card's "is it on"
                # branch reads THIS, not subscription_status, so what the page shows and
                # what the user can actually open are the same question.
                "has_access": has_access,
                # No Stripe subscription exists any more. Kept as a key because the
                # template still reads it; Renew and Cancel act on the module CODE.
                "subscription_id": None,
                "subscription_status": subscription_status,
                # Whether the user can cancel this module right now. An already-cancelled
                # trial is still trialing (access runs on) but must not offer Cancel
                # again - its card shows "access until ... / Renew" instead.
                #
                # ``granted`` for the same reason it gates subscription_status above: a
                # module whose period has lapsed keeps its ``active`` phase until
                # something writes it, and there is nothing live to cancel.
                "can_cancel": bool(
                    app_trial_running
                    or (
                        granted
                        and phase in (PHASE_ACTIVE, PHASE_PAST_DUE)
                        and not pending_cancel
                    )
                ),
                "amount": amount,
                "formatted_amount": (
                    money.format_minor(plan.amount, plan.currency_code)
                    if plan
                    else "0.00"
                ),
                "currency_code": (plan.currency_code if plan else None),
                "billing_interval": (plan.billing_interval if plan else "month"),
                "cancel_at_period_end": phase == PHASE_SCHEDULED_CANCEL,
                "pending_cancel": pending_cancel,
                # A cancelled free trial, still running. Distinct from a cancelled PAID
                # module: no money changed hands, so the copy is "will not convert"
                # rather than "you paid for these days", and resuming it costs nothing.
                "trial_cancelled": app_trial_cancelled,
                "formatted_period_end": formatted_period_end,
                # Compact / long variants for the redesigned card + panel: "19 Aug"
                # for the trial pill, "19 Aug 2026" for the "valid until" line.
                "period_end_short": _fmt_day_month(period_end),
                "period_end_long": _fmt_day_month_year(period_end),
                # Raw datetime as well as the formatted strings: the panel needs to
                # compare dates to pick the EARLIEST next-invoice date across modules,
                # and re-parsing "19 Aug 2026" to do it would be absurd.
                "period_end": period_end,
                # What converting THIS trial will charge on the spot, on top of the
                # monthly rate. Filled by _forecast_conversion_charges AFTER this loop:
                # the answer depends on the OTHER trials, because whichever converts
                # first starts the cycle every later one is then prorated against.
                "conversion_charge": Decimal(0),
                # A cancel-extension already recorded on this module and not yet billed.
                # It is a real line on the payer's next invoice (renewals.
                # _pending_extension_lines), so a panel quoting only the recurring price
                # would understate what is about to be charged.
                "extension_amount": (
                    _normalize_price_amount(
                        getattr(row, "extension_amount", None),
                        plan.currency_code if plan else None,
                    )
                    if row is not None
                    and getattr(row, "extension_state", None) == EXT_PENDING
                    and getattr(row, "extension_amount", None)
                    else Decimal(0)
                ),
                # Ready to print. The card states what the cancellation costs, and money
                # on a card is formatted by the same rule as money in the panel.
                "extension_formatted": (
                    _fmt_money(
                        _currency_symbol(plan.currency_code if plan else None),
                        _normalize_price_amount(
                            row.extension_amount, plan.currency_code if plan else None
                        ),
                        money.decimal_places(plan.currency_code if plan else None),
                    )
                    if row is not None
                    and getattr(row, "extension_state", None) == EXT_PENDING
                    and getattr(row, "extension_amount", None)
                    else None
                ),
                "access_end_date": access_end_date,
                "access_end_long": (
                    _fmt_day_month_year(access_end)
                    if (winding_down and access_end and access_end > now)
                    else None
                ),
                # A trial that will not convert CANCELS when the term ends - warn while
                # there is still time to fix it. Two reasons it will not: no card at
                # all, or a card the payer never authorised for THIS entity.
                "needs_card": bool(
                    app_trial and not will_convert and not pending_cancel
                ),
                # Which of the two it is, so the banner can say "add a card" vs
                # "confirm billing for this company" - the fix differs.
                "needs_consent_only": bool(
                    has_payment_method and not has_billing_consent
                ),
            }
        )

    # Second pass, once every card exists: the conversion charges are SEQUENTIAL and a
    # per-card computation cannot see the trials it depends on.
    for code, charge in _forecast_conversion_charges(
        entity_id, payer_id, billed_now, cards
    ).items():
        for card in cards:
            if (card["code"] or "").upper() == code:
                card["conversion_charge"] = _normalize_price_amount(
                    charge, card.get("currency_code")
                )
    return cards


def get_subscription_summary(entity_id: str) -> dict:
    """Build the subscription cost summary shown beside the module cards.

    One line per module with a *continuing* subscription — i.e. one that will
    actually be billed: active/trialing and NOT winding down (cancel-at-period-end
    or cancelled). A cancelled module is dropped from the summary entirely. Lines
    are priced from ``billing_plan`` via ``services.catalog``; when the continuing
    modules are exactly the bundle's set the total is the single bundle price instead
    (the bundle IS the discount — there is no coupon). Nothing is hardcoded, and it is
    the same table the billing engine quotes from, so this and the invoice cannot
    disagree.
    The page renders this summary as-is and does NOT recompute it from the toggles.

    Returns a dict shaped for the template:
        {currency, lines: [{code, label, amount, currency_code}], subtotal,
         bulk_discount, total, has_discount}
    """
    from blueprints.subscription.services import access, catalog, store

    catalog_by_code = {
        fn.function_code: fn
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }
    plans_by_code = {
        plan.function_code.upper(): plan for plan in catalog.available_plans()
    }

    # The modules actually going to be charged again, read from the module rows rather
    # than live Stripe. A trial contributes nothing (it is free right now) and a module
    # winding down is excluded, so the summary reflects only the ongoing cost.
    #
    # The old version also required a stored period end still in the future. That check
    # did not survive the move, and does not need to: it guarded against a period end
    # that had lapsed without renewing, whereas the phase says directly whether the
    # module is still being billed. Its one real effect was to drop a PAST-DUE payer
    # from their own summary — showing them nothing owed at the moment they owe most.
    continuing_codes = {
        row.function_code.upper()
        for row in store.module_rows_for_entity(entity_id)
        if access.is_billing_forward(phase=row.phase)
    }

    lines: list[dict] = []
    for code in MODULE_CODES:
        if code.upper() not in continuing_codes:
            continue
        fn = catalog_by_code.get(code)
        plan = plans_by_code.get(code.upper())
        if plan is not None:
            amount = _normalize_price_amount(plan.amount, plan.currency_code)
            line_currency = plan.currency_code
        else:
            # No live plan for this module (not configured in Stripe yet) — show
            # zero so the summary still renders rather than inventing a price.
            amount = Decimal(0)
            line_currency = None
        label = fn.function_name if fn and fn.function_name else code
        lines.append(
            {"code": code, "label": label, "amount": amount, "currency_code": line_currency}
        )

    subtotal = sum((line["amount"] for line in lines), Decimal("0"))

    # The bundle IS the discount: when the continuing modules are exactly the bundle's
    # set, the entity bills the single bundle price instead of the standalone lines, and
    # the saving is the difference. There is no coupon.
    bundle = catalog.bundle_plan()
    bundle_amount = (
        _normalize_price_amount(bundle.amount, bundle.currency_code)
        if bundle
        else Decimal("0")
    )
    bundle_currency = (bundle.currency_code or "").upper() if bundle else None
    line_codes = [ln["code"].upper() for ln in lines]
    bundled = bool(bundle and len(lines) > 1 and bundle.covers(line_codes))

    total = bundle_amount if bundled else subtotal
    bulk_discount = (subtotal - total) if bundled else Decimal("0")

    # Currency symbol for the summary, resolved live from the listed modules' Stripe
    # plan currency (first one wins; falls back to the bundle's) — never hardcoded.
    summary_currency_code = next(
        (ln["currency_code"] for ln in lines if ln["currency_code"]),
        bundle_currency,
    )

    return {
        "currency": _currency_symbol(summary_currency_code),
        # The CODE as well as the symbol: the symbol cannot tell a caller how many
        # decimal places to render, and the billing panel needs to know.
        "currency_code": summary_currency_code,
        "lines": lines,
        "subtotal": subtotal,
        # Kept for the template: the saving vs paying for each module separately.
        "bulk_discount": bulk_discount,
        "total": total,
        "has_discount": bulk_discount > 0,
        # The bundle price + the modules it covers, exposed so the client-side "modules
        # to subscribe" cart can preview exactly what checkout will bill: pick the
        # bundle price when the selection is the bundle's set, else the sum of the
        # standalone lines. Populated regardless of what's currently subscribed, so the
        # preview works with no live subs.
        "bundle_amount": bundle_amount,
        "bundle_amount_formatted": f"{bundle_amount:,.2f}",
        "bundle_codes": sorted(bundle.function_codes) if bundle else [],
        "bundle_currency": bundle_currency,
        # What to CALL the bundle. The trial-decision modal names the plan the customer
        # is choosing, and it recomputes that name as modules are ticked, so it needs the
        # name as data rather than as a string baked into a template.
        "bundle_name": (bundle.display_name if bundle else None) or BUNDLE_DISPLAY_NAME,
    }


def get_billing_anchor(entity_id: str) -> str | None:
    """The payer's billing anchor date, formatted for display, or None if unset.

    The anchor lives on the billing ACCOUNT and is set once, at the first charge —
    so it stays None while the entity is only on an app-level trial (a trial has no
    cycle). The settings page shows None as "To Be Decided" and the real date once
    the first paid module pins the cycle.
    """
    from blueprints.subscription.services import store as sub_store

    payer_id = sub_store.payer_for_entity(entity_id)
    if not payer_id:
        return None
    row = sub_store.customer_mapping_for_user(payer_id)
    anchor = getattr(row, "anchor_at", None) if row else None
    return _fmt_day_month_year(anchor) if anchor else None


def next_payment_from_panel(panel: dict | None) -> str | None:
    """The date of the panel's next actual charge, or None if it has none scheduled.

    THE FIRST ROW of ``upcoming_charges``, which is already sorted on the raw datetime.
    The card at the top of the settings page and the list in the panel below it were two
    separate answers to "when am I next charged", computed from different sources, and
    they disagreed whenever anything but the renewal came first: a trial converting on the
    20th is charged eight days before the renewal on the 28th, and the card named the 28th
    — the SECOND charge — as the next one. Reading the card off the list makes that
    impossible rather than merely unlikely.

    OVERDUE ROWS ARE SKIPPED. ``past_due`` carries a ``paid_through`` that is already
    behind us, so the earliest row can be a date in the PAST — which under the words "Next
    payment date" is exactly the bug this card was rewritten to fix, and with none of the
    red that makes the panel's own "Renewal — overdue" line legible as arrears. The debt
    is stated there, properly, rather than silently here.

    None when nothing is scheduled — a trial that will not convert, or every module
    cancelled. The caller falls back to :func:`get_next_payment_date`.
    """
    for row in (panel or {}).get("upcoming_charges") or []:
        if row.get("date") and not row.get("overdue"):
            return row["date"]
    return None


def get_next_payment_date(entity_id: str) -> str | None:
    """The payer's NEXT billing date, formatted for display, or None if there is no cycle.

    The FALLBACK behind :func:`next_payment_from_panel` — what the settings card shows for
    an entity with no charge of its own scheduled. The anchor itself is the wrong thing to
    put in front of a customer: it is the ORIGINAL first-charge date and never moves, so a
    payer anchored in July still reads "28 Jul 2026" in August — a date in the past,
    labelled as when they will be billed. This projects the same cycle forward instead.

    Derived from the anchor rather than from ``paid_through`` so the month-end clamp is
    the same one the renewal runner bills on (``period_containing``: 31 Jan → 28 Feb →
    back to 31 Mar), and so it can never quote a date that has already gone —
    ``period_containing`` returns the period ``now`` is inside, whose END is by
    construction still ahead.

    None while the entity is only on an app-level trial: no charge has happened, so there
    is no cycle to project and nothing honest to name. The page shows that as
    "To Be Decided", same as before.
    """
    from blueprints.subscription.services import clock
    from blueprints.subscription.services import store as sub_store
    from blueprints.subscription.services.billing import period_containing

    payer_id = sub_store.payer_for_entity(entity_id)
    if not payer_id:
        return None
    anchor, _currency = sub_store.billing_cycle_for_user(payer_id)
    if not anchor:
        return None
    try:
        return _fmt_day_month_year(period_containing(anchor, clock.now()).end)
    except Exception:
        # A date on a card must never cost anyone the page — the panel below it carries
        # the same information per module.
        logger.exception("modules: could not project the next payment date for {}", entity_id)
        return None


def _forecast_conversion_charges(entity_id, payer_id, billed_now, cards) -> dict[str, int]:
    """{code: minor units} actually charged ON each converting trial's date.

    The whole charge for that day, not a top-up on a monthly rate: the row it feeds reads
    "Petty Cash converts · 28 Aug · HKD 280", and that figure is what leaves the card.

    SEQUENTIAL, and that is the whole point. Trials that end on different days convert on
    different days, and the FIRST one to land pins the payer's billing anchor and bills a
    full period. Every later conversion is then a mid-period CHANGE against the cycle that
    first one started — credit the old price, charge the new, prorated over the days left
    (the 373.33 / 28.00 oracles in tests/test_change_billing.py).

    Forecasting each trial independently against today's state answers 0 for all of them,
    because today there is no anchor and nothing billed — which is exactly the bug this
    replaces: two trials a fortnight apart both quoted a plain "/mo" and the second
    module's prorated charge arrived with no warning anywhere on the page.

    Calls the same ``changes.build_change`` the conversion itself does
    (``checkout._bill_module_change_in_house``), so the forecast and the invoice cannot be
    computed two ways. What it does NOT mirror is the anchoring side effect: this reads.

    Two shapes, matching ``_bill_module_change_in_house`` exactly:
      * the conversion that STARTS the payer's cycle is charged a FULL period for the
        modules it turns on — the plan price, not a proration, because the payer was
        never part of an earlier period to prorate against;
      * every later one is a mid-period change: credit the old price for the unused days,
        charge the new for them, and the NET is what the card is hit for.

    A code maps to 0 only when there is genuinely nothing to take — a downgrade, or a
    combination the catalog cannot price, both of which make ``build_change`` return None
    rather than guess.
    """
    if not payer_id:
        return {}

    # Only trials that will actually convert. One that expires charges nothing, so
    # forecasting it would invent a number for an event that never happens — and it must
    # not advance the simulated anchor either.
    converting = sorted(
        (
            c
            for c in cards
            if c.get("subscription_status") == "trialing"
            and not c.get("needs_card")
            and not c.get("pending_cancel")
            and c.get("period_end")
        ),
        key=lambda c: c["period_end"],
    )
    if not converting:
        return {}

    try:
        from blueprints.subscription.services import changes
        from blueprints.subscription.services import store as sub_store
        from blueprints.subscription.services.billing import period_containing

        anchor, _currency = sub_store.billing_cycle_for_user(payer_id)
    except Exception:
        logger.exception("modules: could not read the billing cycle for {}", entity_id)
        return {}

    billed: set[str] = {str(c).upper() for c in (billed_now or ())}
    out: dict[str, int] = {}
    for card in converting:
        code = (card["code"] or "").upper()
        at = card["period_end"]
        if anchor is None:
            # Nothing has ever been billed for this payer, so THIS conversion starts the
            # cycle and anchors it on its own date — exactly the branch
            # _bill_module_change_in_house takes when it finds no anchor. Anchoring HERE
            # rather than short-cutting to the plan price keeps the line below the only
            # arithmetic in this function: with the period starting at the conversion,
            # build_change has a whole period left to bill and returns the full charge by
            # the same route it prorates a later one. Later trials in this loop then
            # prorate against the cycle it just created, which is what a per-card
            # forecast cannot see.
            anchor = at
        try:
            # The period containing the CONVERSION, not today's — a trial ending next
            # month prorates against the period it lands in.
            period = period_containing(anchor, at)
            invoice = changes.build_change(
                entity_id, str(entity_id), billed, billed | {code}, period, at
            )
            out[code] = int(getattr(invoice, "total", 0) or 0) if invoice else 0
        except Exception:
            # A forecast must never cost anyone the page. Silence here only drops the
            # "charged on the day" line; the conversion itself bills from its own path.
            logger.exception(
                "modules: could not forecast the conversion charge for {} {}",
                entity_id,
                code,
            )
            out[code] = 0
        billed.add(code)
    return out


def _empty_panel_next_invoice(cards: list[dict], fmt) -> dict | None:
    """The next-invoice line for a panel with nothing enabled.

    Nothing renews and no trial converts, so the only thing that can still be charged is
    a cancel-extension already recorded and not yet collected. Cancelling the LAST module
    is precisely how an entity reaches this panel, and it is the case that most often
    owes one — reporting "nothing will be billed" over the top of a pending charge would
    be the panel's worst possible lie.

    The date is the payer's cycle end, which a winding-down module still carries (it
    reports ``subscription_status`` "active" until its access runs out).
    """
    extensions = sum((c.get("extension_amount") or Decimal(0) for c in cards), Decimal(0))
    if extensions <= 0:
        return None
    on = next((c.get("period_end_long") for c in cards if c.get("period_end_long")), None)
    return {
        "date": on,
        "amount": fmt(extensions),
        "overdue": False,
        "includes_extension": True,
    }


def _winding_notices(cards: list[dict], bundle_codes, bundle_name: str) -> list[dict]:
    """The "X cancelled — active until DATE" lines, one per cancellation the customer made.

    Grouped by what was CANCELLED, not by module: cancelling a two-module bundle is one
    decision and reads as one sentence naming the plan, rather than the same date printed
    twice under two module names.

    ``past_due`` is excluded for the reason it is excluded everywhere else here: it
    carries the same winding-down flag but is in arrears, not cancelled, and telling a
    customer their module is "cancelled" while dunning still retries the charge would be
    wrong in the direction that loses the account.
    """
    winding = [
        c
        for c in cards
        if c.get("pending_cancel")
        and c.get("access_end_long")
        and c.get("subscription_status") != "past_due"
    ]
    if not winding:
        return []

    # A cancelled TRIAL is a different sentence from a cancelled subscription: nothing was
    # bought, nothing is being ended early, and the free days run out on the date they
    # were always going to. Calling that "cancelled" describes a purchase the customer
    # never made. Mixed groups read as the paid case, which is the one with money in it.
    def kind(cards_):
        return "trial" if all(c.get("trial_cancelled") for c in cards_) else "paid"

    codes = sorted((c["code"] or "").upper() for c in winding)
    wanted = sorted((code or "").upper() for code in (bundle_codes or []))
    if wanted and len(winding) > 1 and codes == wanted:
        return [
            {
                "label": bundle_name,
                "date": winding[0]["access_end_long"],
                "kind": kind(winding),
            }
        ]
    return [
        {"label": c["name"], "date": c["access_end_long"], "kind": kind([c])}
        for c in winding
    ]


def _extension_charges(cards: list[dict], fmt, bundle_codes=None, bundle_name="") -> list[dict]:
    """One upcoming-charge row per CANCELLATION — not per module.

    A cancellation extends access to the later of the paid period and 30 days, and bills
    the days BEYOND what was paid for on the payer's next invoice
    (renewals._pending_extension_lines). That is a different charge from a renewal and a
    different charge from a trial conversion: it is one-off, it belongs to a module that
    is going away, and it is the only line here the customer did not choose to keep
    paying for.

    Folding it into the renewal's figure made both unreadable — a "Renewal HKD 400" that
    is really 280 of subscription and 120 of cancellation, with a footnote to explain the
    arithmetic. Worse, when the cancelled module was the entity's LAST paid one there was
    no renewal row to fold it into, and the charge disappeared from a list titled
    "upcoming charges" while remaining perfectly real.

    Cancelling a bundle is ONE decision and the two modules share the bundle price for
    those days, split unevenly between their rows (checkout._leaving_marginal), so it is
    one line naming the plan and carrying the whole figure — two uneven rows the customer
    cannot reconcile against the dialog they confirmed, or against the invoice, is the
    same mistake the renewal line used to make by folding the extension in.

    The date is the module's own period end — the extension rides the invoice raised for
    the cycle it is already inside.
    """
    charged = [c for c in cards if (c.get("extension_amount") or Decimal(0)) > 0]
    if not charged:
        return []

    total = sum((c["extension_amount"] for c in charged), Decimal(0))
    note = "Extra days after your paid period — charged once, not monthly."
    codes = sorted((c["code"] or "").upper() for c in charged)
    wanted = sorted((code or "").upper() for code in (bundle_codes or []))
    if wanted and len(charged) > 1 and codes == wanted and bundle_name:
        return [
            {
                "at": charged[0].get("period_end"),
                "date": charged[0].get("period_end_long"),
                "label": f"{bundle_name} cancellation",
                "amount": fmt(total),
                "overdue": False,
                "note": note,
            }
        ]
    return [
        {
            "at": c.get("period_end"),
            "date": c.get("period_end_long"),
            "label": f"{c['name']} cancellation",
            "amount": fmt(c["extension_amount"]),
            "overdue": False,
            "note": note,
        }
        for c in charged
    ]


def build_consent_takeover(
    entity_id, user_id, *, can_manage: bool, access_state=None
) -> dict | None:
    """The restart screen for an entity whose trial lapsed, or None.

    Two shapes come out of one builder because they are one screen in two frames:
    ``mode="takeover"`` replaces the page when nothing live is left, ``mode="panel"``
    sits above the module cards when another module is still trialing. The condition
    itself lives in ``subscription.services.consent`` — this only dresses it.

    ``access_state`` is the ``{code: bool}`` gate map, resolved from ``_enabled_state``
    when not supplied. It is a parameter so a test can state the gate directly instead of
    building an ``entity_function_map``, and so a future caller that already holds the map
    can hand it over rather than reading it a second time.

    ``can_act`` is carried SEPARATELY from ``mode``. A co-admin must never be shown this
    screen — ``require_subscription_payer`` would refuse the write, so it would be a form
    that cannot submit — but the page still needs to know a restart is outstanding so it
    can name the payer who has to do it.

    Returns None when there is nothing lapsed, so the caller can pass it straight to the
    template and let a single falsy check pick the ordinary page.
    """
    from blueprints.subscription.services import consent

    state = consent.lapsed_trial_for_entity(
        entity_id, user_id if can_manage else None, access_state=access_state
    )
    if not state.get("mode"):
        return None

    view = {
        "mode": state["mode"],
        "can_act": bool(can_manage),
        "lapsed": state["lapsed"],
        "payer_user_id": state.get("payer_user_id"),
        "has_card": state.get("has_card", False),
        "single": len(state["lapsed"]) == 1,
        "names": [item["name"] for item in state["lapsed"]],
        "quote": None,
        "methods": None,
    }
    for item in view["lapsed"]:
        item["lapsed_on_long"] = _fmt_day_month_year(item["lapsed_on"])

    # Everything below costs a Stripe round trip, and NONE of it is any use to someone
    # who cannot act on it. A co-admin gets the naming fields above and nothing more.
    if not can_manage:
        return view

    view["quote"] = _restart_quote(entity_id, user_id, view["lapsed"])
    view["methods"] = _restart_methods(user_id, entity_id)
    return view


def _restart_quote(entity_id, user_id, lapsed) -> dict | None:
    """What restarting every lapsed module would cost, for the first render.

    Priced through ``preview_subscribe_modules`` — the same figure the charge itself
    uses — so the number on the screen and the number billed come from one calculation.
    The page re-asks the ``restart-quote`` route whenever a box is ticked; this exists
    only so the first paint needs no round trip.

    None on any failure. The page then shows its boxes with the amount pending and
    fetches it, which is a slower screen rather than a broken one — and far better than
    a takeover that renders no price at all.
    """
    from models.db import Entity, User

    try:
        from blueprints.subscription.services.checkout import preview_subscribe_modules

        entity = Entity.query.get(str(entity_id))
        user = User.query.get(str(user_id))
        if entity is None or user is None:
            return None
        return preview_subscribe_modules(
            entity, user, [item["code"] for item in lapsed]
        )
    except Exception:
        db.session.rollback()
        logger.exception(
            "modules: could not price the restart for {}; the page will fetch it",
            entity_id,
        )
        return None


def _restart_methods(user_id, entity_id) -> dict:
    """The payer's saved cards for the in-page picker, with THIS company's marked.

    ``nominated_id`` is what the picker preselects, falling back to ``default_id``. A
    company billed to one card and preselected on another would have the payer confirm a
    charge against a card they never chose for it.

    An empty wallet is NOT an error and must not read as one: ``has_account`` false is
    the ordinary state of a payer whose trial never captured a card, and the screen shows
    the add-card form alone. A genuine failure answers the same shape, because the page
    can still fetch the list itself — the one thing it must never do is imply the cards
    are gone.
    """
    empty = {"has_account": False, "default_id": None, "nominated_id": None,
             "methods": [], "total": 0}
    try:
        from blueprints.subscription.services import payment_methods

        return payment_methods.for_entity(user_id, entity_id)
    except Exception:
        logger.exception(
            "modules: could not read saved cards for payer {}; the page will fetch them",
            user_id,
        )
        return empty


def build_subscription_panel(cards: list[dict], summary: dict | None, anchor_display: str | None) -> dict | None:
    """The "Your subscription" panel model, from the already-built cards + summary.

    Pure — it re-uses ``get_module_cards`` / ``get_subscription_summary`` output rather
    than re-querying, so the panel and the cards can never disagree about what's enabled.

    Unlike ``get_subscription_summary`` (which only counts modules being billed forward,
    and so is empty during a trial), this reflects what the enabled modules cost whether
    they're trialing or paid — the trial panel has to preview the price the trial will
    convert to. The billing anchor decides the mode: no anchor yet ⇒ still on trial
    ("Subscribe to Minty", "first charge … on <trial end>"); anchor set ⇒ paid
    ("Manage subscription", "Billed …/mo · next payment <date>"). ``anchor_display`` is
    only ever read as that switch — the anchor is a past date and is never shown; the
    footer names ``next_invoice_on``, the date the cycle actually bills next.

    ALWAYS returns a panel. With nothing enabled it returns an ``is_empty`` one that
    still names every module and prices the total at zero, rather than None — the panel
    used to disappear entirely, so the page silently lost a column exactly when the
    answer mattered most (right after cancelling the last module, the customer was left
    with no statement of what they are and aren't being billed for). "Nothing" is a
    state worth rendering, not an absence.
    """
    from blueprints.subscription.services import money

    summary = summary or {}
    symbol = summary.get("currency") or ""
    currency_code = summary.get("currency_code")
    if not symbol or not currency_code:
        for card in cards:
            if card.get("currency_code"):
                symbol = symbol or _currency_symbol(card["currency_code"])
                currency_code = currency_code or card["currency_code"]
                break

    # Resolved once for the whole panel: every figure below is in the same currency, so
    # re-deriving it per line is a lookup for nothing and a chance for two to disagree.
    places = money.decimal_places(currency_code)

    def fmt(amount) -> str:
        return _fmt_money(symbol, amount, places)

    # One name for the bundle everywhere it is spoken about: the priced line, its note,
    # the cancellation notices below, and the decision modal.
    bundle_name = summary.get("bundle_name") or BUNDLE_DISPLAY_NAME

    # "Enabled" = will be on the NEXT invoice: a running trial or a live paid line, but
    # NOT one that's winding down. A cancelled module keeps access until its period ends
    # yet is billed no further, so it must drop out of the future-invoice total the moment
    # it's cancelled — exactly as get_subscription_summary excludes it via is_billing_forward.
    #
    # PAST_DUE is the exception, and it has to be spelled out. The card sets
    # ``pending_cancel`` for it too, because a failed renewal and a scheduled cancellation
    # share one "winding down" flag that drives the Renew button. Billing is a different
    # question: a past-due subscription has NOT ended and the money IS still owed, which
    # is precisely what ``access.is_billing_forward`` says. Reading pending_cancel alone
    # dropped it, and the panel then said "No modules enabled — nothing will be billed"
    # to a customer in arrears, at the moment they owe most.
    def billed_forward(card) -> bool:
        status = card.get("subscription_status")
        if status == "past_due":
            return True
        return status in ("trialing", "active") and not card.get("pending_cancel")

    enabled = [c for c in cards if billed_forward(c)]
    if not enabled:
        # Nothing billed forward — no live module, or every one of them winding down.
        # Same shape as a live panel so the template needs no second layout: every
        # module named and marked unbilled, and a real formatted zero rather than a
        # blank, which would read as "we couldn't work it out" instead of "nothing".
        owed = _empty_panel_next_invoice(cards, fmt)
        return {
            "state": "empty",
            "is_empty": True,
            "currency": symbol,
            "lines": [
                {
                    "kind": "module",
                    "label": card["name"],
                    "amount": None,
                    "billed": False,
                }
                for card in cards
            ],
            "is_bundle": False,
            "note": None,
            "total": fmt(Decimal(0)),
            # Nothing enabled means nothing renews and no trial converts. A pending
            # cancel-extension can still be owed here, so it is surfaced rather than
            # silently dropped — that is a real charge on a panel that otherwise reads
            # "nothing will be billed".
            "next_invoice": owed,
            "trial_conversions": [],
            # Nothing renews and no trial converts, so the list is the owed extensions or
            # nothing at all — named per module, exactly as on a live panel. Calling it
            # "Renewal" here was wrong twice: nothing is renewing, and the one thing that
            # IS charged is the cancellation that emptied the panel.
            "upcoming_charges": _extension_charges(
                cards, fmt, summary.get("bundle_codes"), bundle_name
            ),
            # A module winding down is excluded from the total — it bills no further —
            # but the customer still HAS it until its access runs out. Saying only
            # "nothing will be billed" over the top of that reads as "you have nothing",
            # which is wrong on the exact screen they opened to check.
            "winding_down": [
                {"label": c["name"], "date": c.get("access_end_long")}
                for c in cards
                if c.get("pending_cancel")
                and c.get("access_end_long")
                # past_due carries pending_cancel too (one "winding down" flag serves
                # both), but it is NOT billing no further — it is in arrears and will be
                # retried. Listing it here printed "Not billed again" directly above the
                # overdue charge for the same module.
                and c.get("subscription_status") != "past_due"
            ],
            # What the panel actually renders for those: one sentence per cancellation
            # rather than one row per module — see _winding_notices.
            "winding_notices": _winding_notices(
                cards, summary.get("bundle_codes"), bundle_name
            ),
            "footer": "No modules enabled — nothing will be billed.",
            # The panel button is the ONLY way into the decision modal, so an empty panel
            # still needs one whenever there is something to decide:
            #   * a module winding down — re-ticking it is the undo, and withholding the
            #     button would leave a cancellation with no way back;
            #   * a module that could be taken up — an entity whose trials are spent has
            #     nothing enabled and nothing cancelled, and this is its way back in. The
            #     modal lists untried modules too; ticking one starts its free trial
            #     rather than buying it, so this button is right either way.
            # Only a company with no modules at all in the catalog gets no action.
            "primary_action": (
                "manage"
                if any(c.get("pending_cancel") for c in cards)
                else ("subscribe_stripe" if cards else None)
            ),
            "subscribe_codes": [],
        }

    # The anchor is pinned at the first charge, so its presence is exactly "has this
    # entity started paying" — the one bit that separates the trial panel from the paid.
    state = "active" if anchor_display else "trialing"

    # ...which is the wrong question for the BUTTON, twice over. The anchor lives on the
    # payer's ACCOUNT, so a payer already charged for another company gives this one an
    # anchor on day one; and a trial that already has a card and this company's consent
    # needs nothing from the customer — it converts on its own.
    #
    # So "Subscribe to Minty" is offered for exactly one condition: a running trial that
    # will NOT convert as things stand, because there is no card or this company was
    # never authorised for the saved one. That is what needs_card means (see
    # get_module_cards); needs_consent_only says which of the two it is. Everything else
    # — trials that will convert, and paying entities — is "Manage subscription".
    needs_billing_setup = any(c.get("needs_card") for c in cards)

    enabled_codes = sorted((c["code"] or "").upper() for c in enabled)
    bundle_codes = sorted((code or "").upper() for code in (summary.get("bundle_codes") or []))
    bundle_amount = summary.get("bundle_amount") or Decimal(0)
    # The bundle IS the discount: when the enabled set is exactly the bundle's, it bills
    # at the single bundle price. Mirrors get_subscription_summary / checkout.
    is_bundle = bool(bundle_codes and len(enabled) > 1 and enabled_codes == bundle_codes)

    subtotal = sum((c["amount"] for c in enabled), Decimal(0))
    total = bundle_amount if is_bundle else subtotal
    saving = (subtotal - total) if is_bundle else Decimal(0)

    lines: list[dict] = []
    if is_bundle:
        lines.append(
            {
                "kind": "bundle",
                "label": bundle_name,
                "sublabel": " & ".join(c["name"] for c in enabled),
                "original": fmt(subtotal),
                "amount": fmt(total),
            }
        )
    else:
        # One line per canonical module — an unenabled one reads "Not billed" rather
        # than vanishing, so the panel always shows the full picture.
        for card in cards:
            on = billed_forward(card)
            lines.append(
                {
                    "kind": "module",
                    "label": card["name"],
                    "amount": (fmt(card["amount"]) + "/mo") if on else None,
                    "billed": on,
                }
            )

    # The highlighted context line — what the price actually is, in plain words.
    #
    # The bundle line reads the same whether trialing or paid. It used to append "vs
    # HK$280 each" once billing had started, which quoted a per-module price for a plan
    # nobody is billed per module on — and the saving beside it already carries the
    # comparison.
    if is_bundle:
        note = f"{bundle_name} price — save {fmt(saving)}"
    else:
        module = enabled[0]
        price = fmt(module["amount"])
        if state == "trialing":
            after = module.get("period_end_short")
            note = (
                f"{module['name']} free trial — {price}/mo after {after}"
                if after
                else f"{module['name']} free trial — {price}/mo"
            )
        else:
            note = f"{module['name']} subscription — {price}/mo."

    total_fmt = fmt(total)

    # --- What actually lands on the next invoice -------------------------------
    #
    # NOT the same set as ``total``. ``total`` is what the enabled modules COST per
    # month, trials included, because the trial panel has to preview the price it will
    # convert to. The invoice bills what ``access.is_billing_forward`` allows on the DAY
    # IT IS RAISED — so a trial still running then is in the total and not on the bill.
    # Quoting one figure for both would misstate whichever the customer was asking about.
    paid = [
        c for c in enabled if c.get("subscription_status") in ("active", "past_due")
    ]
    # The date the payer's cycle next bills: paid_through, carried on any active or
    # past_due card. Absent while the entity has only trials — there is no cycle yet.
    next_invoice_at = next(
        (c.get("period_end") for c in paid if c.get("period_end")), None
    )
    next_invoice_on = next(
        (c.get("period_end_long") for c in paid if c.get("period_end_long")), None
    )

    # A trial that CONVERTS BEFORE the invoice date is active by the time it is raised,
    # so the renewal bills it too — ``billable_codes_by_entity`` reads phases when the
    # run fires, not when this page was rendered. Leaving them out quoted one module's
    # price for an invoice that will charge the bundle: a trial ending 20 Aug is paid
    # for by the 28 Aug invoice, and the panel said 280 against a real 400.
    converts_before_invoice = [
        c
        for c in enabled
        if c.get("subscription_status") == "trialing"
        and not c.get("needs_card")
        and c.get("period_end")
        and next_invoice_at is not None
        and c["period_end"] <= next_invoice_at
    ]
    on_invoice = paid + converts_before_invoice
    invoiced_codes = sorted((c["code"] or "").upper() for c in on_invoice)
    invoiced_is_bundle = bool(
        bundle_codes and len(on_invoice) > 1 and invoiced_codes == bundle_codes
    )
    recurring = (
        bundle_amount
        if invoiced_is_bundle
        else sum((c["amount"] for c in on_invoice), Decimal(0))
    )
    # Cancel-extensions ride the same invoice (renewals._pending_extension_lines), and
    # they sit on modules that are winding down — which is exactly the set ``enabled``
    # excludes. Read them off every card, or the figure understates what is charged.
    extensions = sum((c.get("extension_amount") or Decimal(0) for c in cards), Decimal(0))
    invoice_amount = recurring + extensions

    next_invoice = None
    if next_invoice_on and invoice_amount > 0:
        next_invoice = {
            "date": next_invoice_on,
            "amount": fmt(invoice_amount),
            # past_due means the date has already passed and the money is owed now.
            "overdue": any(
                c.get("subscription_status") == "past_due" for c in paid
            ),
            "includes_extension": extensions > 0,
        }

    # Trial conversions are listed SEPARATELY, one per trialing module, rather than
    # folded into the next-invoice line. Two modules trialled on different days convert
    # on different days, and an entity can hold a trial beside a paid module — so there
    # are genuinely several dates, and collapsing them to one drops real information.
    #
    # The amount is quoted either way — it is what the module costs when the trial ends,
    # and that is the number the customer is deciding against. ``will_convert`` carries
    # whether it is actually going to be taken (no card, or no consent for this entity,
    # means it expires instead), so the row can say "converts" versus "trial ends" and
    # qualify the figure rather than withhold it. Hiding the price left the row reading
    # "Not charged" with nothing to weigh the decision against.
    trial_conversions = [
        {
            "label": c["name"],
            "date": c.get("period_end_long"),
            # WHAT IS CHARGED THAT DAY — not the monthly rate. For the conversion that
            # starts the cycle those are the same number; for one landing mid-period they
            # are not, and the monthly rate is the wrong one. A trial converting into a
            # running cycle pays only the days left in it (the 65.83 shape), so quoting
            # "280/mo" against that date named money that is not taken.
            #
            # A trial that will NOT convert keeps the monthly price: nothing is charged,
            # so there is no day's figure, and the price is still what the decision to
            # add a card is being weighed against.
            "amount": fmt(
                c["conversion_charge"]
                if not c.get("needs_card")
                else c["amount"]
            ),
            "will_convert": not c.get("needs_card"),
        }
        for c in enabled
        if c.get("subscription_status") == "trialing" and c.get("period_end_long")
    ]

    # --- One date-ordered list of what will be charged, and when ----------------
    #
    # A trial converting mid-cycle and the renewal that follows are TWO charges on two
    # dates, and both are real: the conversion collects the days between it and the cycle
    # end, then the renewal bills the full month. Presenting them as separate blocks left
    # the reader working out the order and whether one included the other; a single
    # chronological list answers "what leaves my card, and when" in one pass.
    #
    # Non-converting trials are absent by construction — nothing is charged for a trial
    # that expires, so it is not an upcoming charge. It still appears in the footer,
    # which is where "add a card or lose this" belongs.
    #
    # GROUPED BY DAY, and a day whose conversions are exactly the bundle is ONE row naming
    # the plan. Two modules converting together are billed as the bundle, not as two
    # modules: the forecasts are computed sequentially, so the first carries a full period
    # (280) and the second the net of the change into the bundle (120), and only their SUM
    # (400) is a number the customer will recognise. Printed as two rows they had to add
    # up a 280 and a 120 that appear nowhere on the invoice to check the 400 that does.
    # Same rule the cancellation rows already follow (_extension_charges).
    converting_by_day: dict = {}
    for card in enabled:
        if (
            card.get("subscription_status") == "trialing"
            and not card.get("needs_card")
            and card.get("period_end")
        ):
            converting_by_day.setdefault(card["period_end"], []).append(card)

    upcoming_charges = []
    for at, same_day_cards in converting_by_day.items():
        day_codes = sorted((c["code"] or "").upper() for c in same_day_cards)
        day_amount = sum(
            (c.get("conversion_charge") or Decimal(0) for c in same_day_cards), Decimal(0)
        )
        if bundle_codes and len(same_day_cards) > 1 and day_codes == bundle_codes:
            rows = [(bundle_name, day_amount)]
        else:
            rows = [
                (c["name"], c.get("conversion_charge") or Decimal(0))
                for c in same_day_cards
            ]
        upcoming_charges.extend(
            {
                "at": at,
                "date": same_day_cards[0].get("period_end_long"),
                "label": f"{label} converts",
                "amount": fmt(amount),
                "overdue": False,
                "note": None,
            }
            for label, amount in rows
        )
    # The renewal quotes the RECURRING figure only. Any cancel-extension riding the same
    # invoice is listed beside it as its own row, so each line is one thing the customer
    # can recognise; ``next_invoice`` still carries the combined total, because that is
    # what the invoice will say.
    if next_invoice_on and next_invoice_at and recurring > 0:
        upcoming_charges.append(
            {
                "at": next_invoice_at,
                "date": next_invoice_on,
                "label": "Renewal",
                "amount": fmt(recurring),
                "overdue": bool(next_invoice and next_invoice["overdue"]),
                "note": None,
            }
        )
    # Cancellations are charged whether or not anything renews — including when the
    # cancelled module was the last paid one, which is precisely when the panel used to
    # drop the charge entirely.
    upcoming_charges.extend(
        _extension_charges(cards, fmt, summary.get("bundle_codes"), bundle_name)
    )
    # Sorted on the raw datetime — the formatted date sorts alphabetically, which would
    # put 11 Sep before 28 Aug. A row with no date at all (an extension on a module whose
    # period end never made it onto the card) goes last rather than blowing up the sort.
    _dated = [e for e in upcoming_charges if e["at"] is not None]
    _dated.sort(key=lambda e: e["at"])
    upcoming_charges = _dated + [e for e in upcoming_charges if e["at"] is None]

    if state == "trialing":
        # Every trial here is pre-anchor, so "will any of them actually charge" decides
        # whether the footer may name a figure at all.
        converting = [
            c
            for c in enabled
            if c.get("subscription_status") == "trialing"
            and c.get("period_end_long")
            and not c.get("needs_card")
        ]
        if not trial_conversions:
            footer = f"You're on a free trial — first charge {total_fmt} when the trial ends."
        elif not converting:
            # Still names the price: "nothing will be charged" alone told them the
            # outcome but not the stake, on the one screen where adding a card is the
            # decision in front of them.
            footer = (
                f"Your free trial ends {trial_conversions[0]['date']} — "
                f"{total_fmt}/mo after that, once a card is added."
            )
        else:
            # The FIRST charge is the earliest conversion, and it bills only the modules
            # converting on that DAY — not the combined total. Two trials started a
            # fortnight apart convert a fortnight apart, so quoting the bundle price
            # against the earlier date names money that is not taken until the later one.
            # Sorted on the raw datetime; the formatted string sorts alphabetically.
            #
            # Summed from the per-module forecasts rather than re-priced here, so the
            # footer and the rows above it cannot disagree about the same day's charge.
            first_at = min(
                c["period_end"] for c in converting if c.get("period_end")
            ) if any(c.get("period_end") for c in converting) else None
            same_day = [
                c
                for c in converting
                if first_at is None or c.get("period_end") == first_at
            ] or converting
            first_charge_on = same_day[0]["period_end_long"]
            first_amount = sum(
                (c.get("conversion_charge") or Decimal(0) for c in same_day), Decimal(0)
            )
            footer = (
                f"You're on a free trial — first charge {fmt(first_amount)} "
                f"on {first_charge_on}."
            )
    else:
        # NO FOOTER once billing has started — both halves of the old sentence are now
        # said better elsewhere on the page. "Billed HK$400/mo" repeated the Total row
        # directly above it, and "· next payment 28 Aug 2026" repeated the date card at
        # the top of the page, which is where a customer looks for it. The template skips
        # the paragraph entirely rather than printing an empty one.
        #
        # The trial and empty states keep theirs: those say something no other element
        # on the panel does (when the first charge lands, or that nothing is billed).
        footer = ""

    return {
        "state": state,
        "is_empty": False,
        "currency": symbol,
        "lines": lines,
        "is_bundle": is_bundle,
        "note": note,
        "total": total_fmt,
        # {date, amount, overdue, includes_extension} or None when the cycle has
        # nothing to bill — see the block above for why this is not ``total``.
        "next_invoice": next_invoice,
        # One entry per trialing module: {label, date, amount, will_convert}. Kept as the
        # underlying fact — the footer composes from it, including the trials that will
        # NOT convert and so never reach upcoming_charges.
        "trial_conversions": trial_conversions,
        # What the panel actually renders: every charge, in the order it happens.
        "upcoming_charges": upcoming_charges,
        # Modules that still grant access but bill no further — see the empty panel.
        "winding_down": [
            {"label": c["name"], "date": c.get("access_end_long")}
            for c in cards
            if c.get("pending_cancel")
            and c.get("access_end_long")
            # past_due carries pending_cancel too (one "winding down" flag serves both),
            # but it is NOT billing no further — it is in arrears and will be retried.
            # Listing it here printed "Not billed again" directly above the overdue
            # charge for the very same module.
            and c.get("subscription_status") != "past_due"
        ],
        "winding_notices": _winding_notices(
            cards, summary.get("bundle_codes"), bundle_name
        ),
        "footer": footer,
        # Both captions open the same decision modal — this only says which question the
        # entity is being asked. "Subscribe" when billing still has to be set up for a
        # trial to convert; "Manage" once there is nothing missing.
        "primary_action": "subscribe_stripe" if needs_billing_setup else "manage",
        "subscribe_codes": [c["code"] for c in enabled],
    }


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


def build_subscription_notices(entity_id: str, user_id) -> dict:
    """Everything worth interrupting someone with when they enter an entity.

    ENTITY-WIDE, not per-module: billing is per payer and the anchor is shared, so a
    declined card affects every module the entity holds. Both landing pages (Petty
    Cash here, Payment in the billing frontend) show the same list, each item naming
    the module it is about.

    Deliberately reuses ``get_module_cards`` rather than re-deriving state. Every
    condition below is already a field on those cards, computed against the
    subscription rows that the billing engine itself reads — so the modal, the
    settings page and the invoice cannot disagree about what is wrong.

    Returns ``items: []`` when there is nothing to say; callers treat that as
    "render nothing" rather than rendering an empty modal.
    """
    from blueprints.subscription.services import clock
    from blueprints.subscription.services import store as sub_store
    from models.db import User
    from services.permission_policy import Permission, has_permission_by_user_id

    cards = get_module_cards(entity_id)
    now = clock.now()
    items: list[dict] = []

    for card in cards:
        name = card.get("name") or card.get("code")
        code = card.get("code")

        # 1. Money already failed. The most urgent thing that can be true: access
        #    ends on a date the payer can still act before.
        if card.get("subscription_status") == "past_due":
            items.append(
                {
                    "kind": "past_due",
                    "severity": "critical",
                    "module": name,
                    "module_code": code,
                    "title": f"{name} payment failed",
                    "detail": (
                        f"Pay by {card['access_end_long']} to keep access."
                        if card.get("access_end_long")
                        else "Update your payment method to keep access."
                    ),
                    "deadline": card.get("access_end_long"),
                }
            )
            continue

        # 2. The trial ALREADY lapsed and the gate is off. This state was silent: a
        #    payer could lose a module and never be told, because branch 3 below only
        #    fires while a trial is still running and there was nothing after it. The
        #    restart screen on the settings page can fix it, so the notice is the thing
        #    that gets them there.
        #
        #    Reuses ``needs_card`` rather than inventing a kind: the billing frontend
        #    types NoticeKind as a closed union and renders every kind generically, so a
        #    new one would arrive there unhandled.
        #
        #    NAMES THE MODULE, and has to. An entity can be part-lapsed with another
        #    trial still running, and a notice implying the whole company is down would
        #    be wrong for the half that is fine.
        if card.get("trial_expired") and not card.get("has_access"):
            ended = card.get("access_end_long") or card.get("trial_end_long")
            items.append(
                {
                    "kind": "needs_card",
                    "severity": "critical",
                    "module": name,
                    "module_code": code,
                    "title": f"{name} has expired",
                    "detail": (
                        (f"Its free trial ended {ended}. " if ended else "")
                        + "Restart billing to get it back."
                    ),
                    "deadline": ended,
                }
            )
            continue

        # 3. A trial that will NOT convert. Two different fixes, so two kinds — a
        #    payer with a card saved still has to authorise THIS company before it
        #    can be charged (see checkout._convert_due_trial).
        if card.get("needs_card"):
            consent_only = card.get("needs_consent_only")
            deadline = card.get("period_end_long") or card.get("period_end_short")
            items.append(
                {
                    "kind": "needs_consent" if consent_only else "needs_card",
                    "severity": "warning",
                    "module": name,
                    "module_code": code,
                    "title": (
                        f"Confirm billing to keep {name}"
                        if consent_only
                        else f"Add a payment method to keep {name}"
                    ),
                    "detail": (
                        (
                            "Your saved card is used by your other companies and won't be "
                            "charged for this one until you confirm."
                        )
                        if consent_only
                        else "Your free trial will end without converting."
                    )
                    + (f" Free trial ends {deadline}." if deadline else ""),
                    "deadline": deadline,
                }
            )
            continue

        # 4. Winding down — cancelled but still inside the paid period.
        if card.get("pending_cancel") and card.get("access_end_long"):
            items.append(
                {
                    "kind": "pending_cancel",
                    "severity": "warning",
                    "module": name,
                    "module_code": code,
                    "title": f"{name} is ending",
                    "detail": (
                        f"Access until {card['access_end_long']}. It won't be billed again."
                    ),
                    "deadline": card.get("access_end_long"),
                }
            )
            continue

        # 5. A healthy trial that will convert. Not a problem — but the first charge
        #    is a surprise if nobody said it was coming, so it carries its date for
        #    the whole trial rather than only near the end.
        period_end = card.get("period_end")
        if (
            card.get("subscription_status") == "trialing"
            and period_end
            and not card.get("pending_cancel")
        ):
            # Still >= 0 even with no window: a trial past its end date is not
            # "ending", it has ended, and the sweep is what speaks next.
            #
            # ``trial_closing`` is the one exception, and it is not a contradiction of
            # that rule: it means the term has passed but nothing has closed the trial
            # out YET and the customer still has access. Dropping the notice there would
            # take the "first charge is coming, on this date" message away in the final
            # hour before the charge — the moment it is most worth having on screen — and
            # would make the panel visibly rearrange itself for a state nobody can act on.
            days_left = (period_end - now).days
            if (days_left >= 0 or card.get("trial_closing")) and (
                TRIAL_ENDING_SOON_DAYS is None
                or days_left <= TRIAL_ENDING_SOON_DAYS
            ):
                items.append(
                    {
                        "kind": "trial_ending",
                        "severity": "info",
                        "module": name,
                        "module_code": code,
                        # "is ending" was true when this only fired in the last week.
                        # It now runs the whole trial, and reading "ending" on day one
                        # of thirty would look like a bug — so the title states the
                        # state and the detail carries the date.
                        "title": f"{name} is on a free trial",
                        "detail": (
                            f"Your trial ends {card.get('period_end_long')} and billing starts then."
                            if card.get("period_end_long")
                            else "Billing starts when your trial ends."
                        ),
                        "deadline": card.get("period_end_long"),
                    }
                )

    items.sort(key=lambda i: _NOTICE_ORDER.index(i["kind"]))

    # Who may actually act. Permission says who administers the entity; the payer is
    # whose card the buttons spend — @require_subscription_payer refuses anyone else
    # server-side, so offering them an action would produce a button that fails.
    can_manage = bool(
        user_id
        and has_permission_by_user_id(
            str(user_id), Permission.MODULE_MANAGE, entity_id
        )
        and sub_store.may_manage_subscription(entity_id, user_id)
    )

    payer = None
    payer_id = sub_store.payer_for_entity(entity_id)
    if payer_id and str(payer_id) != str(user_id):
        payer_user = User.query.get(str(payer_id))
        if payer_user:
            payer = {
                "name": " ".join(
                    p for p in (payer_user.first_name, payer_user.last_name) if p
                ).strip(),
                "email": payer_user.email or "",
            }

    return {
        "items": items,
        "can_manage": can_manage,
        "payer": payer,
        "severity": items[0]["severity"] if items else None,
    }


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
    """Whether to show the notice now — and if so, mark it shown for this session.

    "Always appear when first logged in to the entity": once per entity per login,
    not once per page view and not once forever. A user who fixes the problem and
    comes back tomorrow should be told if it is still broken.

    Consumes rather than merely reads, because that is what makes the cost bearable:
    ``build_subscription_notices`` is only ever called when this returns True, so the
    subscription queries run once per entity per session instead of on every dashboard
    load. A previous per-page-view billing read was removed for exactly that reason
    (see the comment in ``routes.modules.module_selection``).

    Takes the session as a parameter rather than importing ``flask.session`` so it is
    testable with a plain dict, and so the JSON endpoint — which is stateless and
    always returns the notice — can simply not call it.
    """
    if not entity_id:
        return False
    seen = session.get(NOTICE_SEEN_SESSION_KEY) or []
    if str(entity_id) in seen:
        return False
    # Reassign rather than mutate in place: Flask's session only marks itself dirty
    # on __setitem__, so appending to the existing list would not persist.
    session[NOTICE_SEEN_SESSION_KEY] = [*seen, str(entity_id)]
    return True


def get_module_plan_catalog() -> dict:
    """The module price list for the onboarding wizard, live from Stripe.

    Entity-independent — no customer, no subscriptions, just what each canonical
    module costs plus the bundle price. Onboarding Step 2 uses it to preview the same
    subtotal / discount / total the settings page shows, and that checkout will
    actually bill once the app-level trial converts to paid.

    A module with no live Stripe plan is omitted rather than priced at zero, so a
    half-seeded catalog can't invent a price. Amounts come back as JSON numbers,
    already converted out of Stripe's smallest currency unit.
    """
    from blueprints.subscription.services import catalog, money, policy

    catalog_by_code = {
        fn.function_code: fn
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    }
    plans_by_code = {
        plan.function_code.upper(): plan for plan in catalog.available_plans()
    }

    plans: list[dict] = []
    for code in MODULE_CODES:
        plan = plans_by_code.get(code.upper())
        if plan is None:
            continue
        fn = catalog_by_code.get(code)
        amount = _normalize_price_amount(plan.amount, plan.currency_code)
        plans.append(
            {
                "code": code,
                "name": fn.function_name if fn and fn.function_name else code,
                "amount": float(amount),
                "formatted_amount": money.format_minor(plan.amount, plan.currency_code),
                "currency_code": plan.currency_code,
                "currency_symbol": _currency_symbol(plan.currency_code),
                "billing_interval": plan.billing_interval or "month",
            }
        )

    bundle = catalog.bundle_plan()
    bundle_amount = (
        _normalize_price_amount(bundle.amount, bundle.currency_code)
        if bundle
        else Decimal("0")
    )

    return {
        "plans": plans,
        # The bundle price + its modules: the wizard bills the bundle price when the
        # picked set is exactly these, else the sum of the standalone plans — exactly
        # as get_subscription_summary and checkout do. The bundle IS the discount.
        "bundle_amount": float(bundle_amount),
        "bundle_codes": sorted(bundle.function_codes) if bundle else [],
        "bundle_currency": (bundle.currency_code or None) if bundle else None,
        "trial_period_days": policy.current().trial_days,
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


def sweep_expired_module_access(payer_user_id=None) -> dict:
    """Disable modules whose access has lapsed past its grace, and END the ones that are
    over.

    ``payer_user_id`` narrows the whole pass to one billing account. The daily job runs
    unscoped; a caller that has just changed one account's entitlement — dunning, on the
    payment that clears an episode — passes its payer so the customer's access comes back
    with the payment rather than at the next nightly run.

    Nothing fires at a grace boundary — not the past-due window measured from
    ``paid_through``, and not ``app_access_until`` (a cancelled module's paid
    extension). So the access map goes stale the moment a window simply elapses, and
    this reconciles it.

    Two things go stale at that boundary, not one. Access is the obvious one. The other
    is the PHASE: ``scheduled_cancel`` and ``past_due`` describe a subscription on its
    way out, and once the date they hang on has passed it is out — so they are moved to
    ``cancelled``, which is terminal and, unlike either of them, lets the customer buy
    the module again. Without that the row reads as mid-cancellation or in-arrears
    forever and the panel keeps offering Renew or Pay now for something already ended.
    See ``checkout.terminate_lapsed_module``; trials are excluded there, because the
    trial-end job owns that transition.

    Runs the SAME sync the webhooks do, per entity, rather than reimplementing "who should
    have access" — the copy that used to live here had drifted into three bugs: it read
    the payer's views without filtering to this entity (granting siblings' modules), it
    iterated only codes that HAD a Stripe view (so a module cancelled out of a bundle —
    whose line is gone, which is the exact case this exists for — was never evaluated),
    and it ignored app-granted access (revoking live trials).

    A module with NO subscription row is revoked, not skipped. The subscription row is
    the record of truth and ``is_enabled`` only projects it, so "switched on with no row
    behind it" is precisely the state this job exists to erase — it is how an entity ends
    up inside a module whose card still offers "Start free trial". This used to `continue`
    on the grounds that a hand-enabled module was nobody's business, which meant the one
    inconsistency nothing else could repair was the one thing deliberately left alone.

    Entities still mid-onboarding are exempt: the wizard records its Step 2 selection in
    the map and only starts the trials at finalize, so between those two calls an enabled
    module with no row is expected rather than broken.

    Reconciles in BOTH directions. A module whose entitlement has come BACK — a past-due
    account that paid, a dunning episode that recovered — is switched on again, because
    nothing else does it either. Revocation used to be one-way: the sweep only looked at
    modules that were currently on, so one it turned off left its candidate set for good
    and the customer stayed locked out of a subscription still being charged for. See the
    restore branch for why that direction is deliberately narrower than this one.

    Intended to run daily (``flask subscriptions sweep-access``). Returns
    ``{"disabled": [{"entity_id", "code"}, ...], "restored": [...]}``.
    """
    from blueprints.subscription.services import access, checkout, clock, policy
    from blueprints.subscription.services import store as sub_store
    from models.db import Entity

    code_set = set(MODULE_CODES)
    disabled: list[dict] = []
    restored: list[dict] = []
    now = clock.now()
    # One window for the whole sweep. Reading it per entity would let a mid-run edit
    # revoke access for the tail of the batch under a rule the head never saw.
    grace_days = policy.current().past_due_window_days

    # Two populations, because this reconciles in BOTH directions.
    #
    # Entities with a module switched on are the only ones that could need switching
    # off. On its own that set made the sweep a one-way ratchet: a module revoked here
    # left the candidate set permanently, so nothing could ever switch it back on — and
    # nothing else does. An account that went past due, then paid, stayed locked out of
    # a subscription it was being charged for, which is precisely the recovery dunning
    # exists to deliver. So entities holding a BILLED module are candidates too, however
    # their access flag currently reads.
    module_fn_ids = [
        fn.id
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(MODULE_CODES)
        ).all()
    ]
    entity_ids = (
        {
            row.entity_id
            for row in EntityFunctionMap.query.filter(
                EntityFunctionMap.entity_function_id.in_(module_fn_ids),
                EntityFunctionMap.is_enabled.is_(True),
            ).all()
        }
        if module_fn_ids
        else set()
    )
    if payer_user_id is None:
        entity_ids |= sub_store.entity_ids_with_billed_modules()
    else:
        mine = {
            str(row.entity_id)
            for row in sub_store.module_rows_for_payer(payer_user_id)
        }
        entity_ids = (entity_ids & mine) | sub_store.entity_ids_with_billed_modules(
            payer_user_id
        )

    # Mid-onboarding entities are exempt (see docstring). Resolved in ONE query up
    # front rather than per entity, so a long sweep can't straddle a finalize and
    # judge the head of the batch by a different rule than the tail. Unfiltered by
    # entity_ids on purpose: the set of in-flight onboardings is small, and an IN
    # clause over every enabled entity is the part that would not scale.
    onboarding_ids = {
        row.id
        for row in Entity.query.filter(Entity.status == "onboarding")
        .with_entities(Entity.id)
        .all()
    }

    for entity_id in entity_ids:
        if entity_id in onboarding_ids:
            continue
        try:
            rows = {
                row.function_code.upper(): row
                for row in sub_store.module_rows_for_entity(entity_id)
            }
            # The date access is measured against lives on the CARD this company is
            # billed on — not on the rows, which drift apart between entities, and no
            # longer on the account, which cannot answer for two cards at once.
            payer_id = next(
                (r.payer_user_id for r in rows.values() if r.payer_user_id), None
            )
            paid_through = (
                sub_store.paid_through_for_entity(entity_id) if payer_id else None
            )
            enabled = _enabled_state(entity_id)
            for code in code_set:
                row = rows.get(code)
                if not enabled.get(code):
                    # Switched off while the subscription still entitles it. Restoring
                    # is deliberately narrower than revoking: only a BILLED module, and
                    # only on the same ``grants_access`` predicate that took it away.
                    #
                    # Requiring a row keeps the guarantee that access is a projection of
                    # a subscription — a flag with nothing behind it is still revoked
                    # above and is never invented here. Requiring the module to be BILLED
                    # is what keeps this from fighting the customer: a paid module cannot
                    # be switched off by hand at all (``set_entity_module`` refuses it),
                    # so an off flag on one can only have come from this sweep. A trial
                    # IS freely toggleable, so re-enabling one would silently overturn a
                    # deliberate choice — and a live trial never loses access this way in
                    # the first place, since its date does not depend on the billing
                    # cycle. Terminal phases grant nothing and so are never restored.
                    if row is not None and access.is_paid_module(
                        phase=row.phase,
                        has_been_billed=row.first_billed_at is not None,
                    ) and access.grants_access(
                        now,
                        phase=row.phase,
                        trial_end=row.trial_end,
                        app_access_until=row.app_access_until,
                        period_end=paid_through,
                        past_due_grace_days=grace_days,
                    ):
                        set_entity_module(entity_id, code, True, actor="subscription")
                        restored.append({"entity_id": entity_id, "code": code})
                    continue
                # Switched on with nothing behind it — never subscribed, or a row
                # deleted out from under the flag. Access is a projection; with no
                # row to project, it comes off.
                if row is None:
                    set_entity_module(entity_id, code, False, actor="subscription")
                    disabled.append(
                        {"entity_id": entity_id, "code": code, "payer_user_id": payer_id}
                    )
                    continue
                if access.grants_access(
                    now,
                    phase=row.phase,
                    trial_end=row.trial_end,
                    app_access_until=row.app_access_until,
                    period_end=paid_through,
                    past_due_grace_days=grace_days,
                ):
                    continue
                # Access has lapsed — a trial that ended, a cancellation past its
                # extension, or a past-due account past its grace. Nothing else closes
                # the gate: the boundary is a DATE, and no event fires when a date passes.
                set_entity_module(entity_id, code, False, actor="subscription")
                # The same date ENDS the subscription, so the phase has to say so too.
                # Revoking access while leaving the row on scheduled_cancel / past_due
                # left a module nobody could use still offering Renew or Pay now for
                # something already over. A trial is left alone — the trial-end job owns
                # that transition (see checkout.terminate_lapsed_module).
                checkout.terminate_lapsed_module(row)
                disabled.append(
                    {"entity_id": entity_id, "code": code, "payer_user_id": payer_id}
                )
        except Exception:
            logger.exception("modules: access sweep failed for entity {}", entity_id)
            continue

    # After the whole sweep. A revocation the customer is not told about is how someone
    # discovers their subscription lapsed by being bounced to an Access Denied page.
    _notify_access_revoked(disabled)
    # ``payer_user_id`` is scaffolding for addressing the email, not part of what this
    # reports. Dropped so the documented return shape is unchanged by notification
    # having been bolted on.
    for item in disabled:
        item.pop("payer_user_id", None)
    # Restorations are deliberately NOT mailed. The customer is told by the thing that
    # caused them — the dunning "you're all settled" notice, the receipt for the payment
    # that cleared the balance — and a second "your access is back" for the same event
    # reads as a system talking to itself. A revocation has no such owner, which is why
    # that one does send.
    return {"disabled": disabled, "restored": restored}


def _notify_access_revoked(disabled: list[dict]) -> None:
    """Tell each payer which modules were switched off. Never raises — see ``notify``.

    One email per entity, listing every module it lost, rather than one per module: the
    customer lost access to a company, not to two rows.

    A trial that ended has ALREADY been mailed by ``convert_or_expire_due_trials``, which
    revokes access itself — so by the time this sweep runs those modules are no longer
    enabled and never reach this list. That ordering is what keeps the two jobs from
    double-notifying, and is why ``close-trials`` is documented to run first.
    """
    if not disabled:
        return
    from blueprints.subscription.services import notify

    now = datetime.now(timezone.utc)
    by_entity: dict[str, dict] = {}
    for item in disabled:
        payer = item.get("payer_user_id")
        if not payer:
            # Nothing was ever subscribed for this entity, so there is no payer to tell.
            continue
        bucket = by_entity.setdefault(
            str(item["entity_id"]), {"payer": payer, "codes": []}
        )
        bucket["codes"].append(item["code"])

    names = _entity_names_for_sweep(set(by_entity))
    events = [
        (
            bucket["payer"],
            notify.ACCESS_REVOKED,
            # Date-stamped so an entity that resubscribes and lapses again months later
            # is notified again rather than deduping against the first lapse.
            f"{entity_id}:{','.join(sorted(bucket['codes']))}:{now:%Y-%m-%d}",
            {
                "entity_id": entity_id,
                "entity_name": names.get(entity_id),
                "codes": sorted(bucket["codes"]),
            },
        )
        for entity_id, bucket in by_entity.items()
    ]
    notify.notify_many(events)


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