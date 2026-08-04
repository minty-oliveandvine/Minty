"""Per-module checkout and trials for entity subscriptions.

The local rows are the source of truth: the plan catalog comes from ``billing_plan``
via ``catalog.py``, and the "already subscribed?" guards read the module rows via
``store``/``access``. Stripe is the payment RAIL only — it captures the card and the
invoices are issued against the payer's customer; there is no Stripe subscription
behind any of this.

Billing is ONE cycle per payer, priced per entity by the module SET it bills:

* **One module** → that module's own price.
* **Both modules** → the single bundle price (the bundle IS the discount — there
  is no coupon), so adding the second module bills the MARGINAL difference.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger

from blueprints.subscription.constants import (
    AUDIT_CANCEL,
    AUDIT_UNCANCEL,
    EXT_INVOICED,
    EXT_PENDING,
    OUTCOME_SUCCEEDED,
    PHASE_ACTIVE,
    PHASE_EXPIRED,
    PHASE_PAST_DUE,
    PHASE_SCHEDULED_CANCEL,
    PHASE_TRIAL,
)
from blueprints.subscription.services import access, catalog, clock, money, policy, store
from blueprints.subscription.services.catalog import PlanView

# Stripe is the payment RAIL, not the biller: what survives here is card capture,
# customer identity and the billing portal. Nothing that creates or edits a Stripe
# SUBSCRIPTION is imported any more — those functions still exist in stripe_client,
# but this module retired its last caller with the Stripe biller.
from blueprints.subscription.services.stripe_client import (
    attach_payment_method,
    create_billing_portal_session,
    create_setup_checkout_session,
    customer_default_payment_method,
    find_customer_by_user,
    get_or_create_billing_management_configuration,
    payment_method_display,
    retrieve_checkout_session,
    set_customer_default_payment_method,
    set_customer_identity,
)

# Post-cancellation access window for an active paid subscription, in days.
#
# DEFAULTS, both of them. The live values are ``billing_policy.paid_cancel_access_days``
# and ``billing_policy.trial_days`` — see ``services.policy``. They remain here as the
# fallback when the row cannot be read, and because a handful of tests assert against
# the shipped behaviour rather than a database.
#
# Both are safe to change at any time, for the same reason: neither is consulted after
# the fact. The trial's end is stamped into ``trial_end`` when it starts and no path
# moves it; the cancellation window is captured into ``app_access_until`` at
# cancellation. So an edit applies to new trials and new cancellations only, and can
# never shorten a window a customer is already inside.
PAID_CANCEL_ACCESS_DAYS = 30

# Length of the card-free onboarding trial, in days.
TRIAL_PERIOD_DAYS = 30


class CheckoutError(Exception):
    """Raised with a user-safe message when checkout can't proceed."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _session_currency(plans: list[PlanView]) -> str:
    """The billing currency for a setup-mode Checkout session. Raises if there is none.

    Was ``next((p.currency_code for p in plans if p.currency_code), "usd")``. That
    fallback could only ever fire on a catalog fault — every ``billing_plan`` row has a
    NOT NULL currency FK — and when it did, it opened a USD session for a business that
    prices in HKD. Silently guessing a currency is the one thing a payment path must not
    do: the customer is shown a card form denominated in money nobody sells in.

    Failing here costs nothing that is not already lost. A catalog with no priced plan
    has nothing to sell, so there is no card worth capturing.
    """
    currency = next((p.currency_code for p in plans if p.currency_code), None)
    if not currency:
        logger.error(
            "checkout: no plan carries a currency ({} plans considered); refusing to "
            "guess one for a Checkout session", len(plans),
        )
        raise CheckoutError(
            "Subscriptions are temporarily unavailable. Please try again shortly.",
            status=503,
        )
    return currency


def _has_active_subscription(entity_id, function_code: str) -> bool:
    """True if THIS ENTITY already bills the module — the double-buy guard.

    Scoped to the entity, not the payer: one customer can bill the same module for
    several entities, so a payer-wide check would wrongly block a second entity from
    subscribing to something the first already has.

    Read from the module row rather than live Stripe. That fixes a real gap: Stripe
    reports a failing card as ``past_due`` rather than ``active``, so the old check let
    a past-due module be purchased AGAIN — a second charge for something the customer
    already has and has not paid for.

    Only a live paid module blocks a purchase. A trial does not (buying converts it
    early, which is legitimate), and neither does a cancelled one — that is refused just
    below by ``_in_cancellation_window``, which can say "use Renew" instead. See
    ``access.is_subscribed``.

    "Already has it" is asked of the PHASE **and** of whether access is still granted.
    The phase alone answers a question about the past: nothing transitions a lapsed paid
    module to ``expired`` — the sweep revokes access without touching the phase, and
    ``end_dunning(status="closed")`` deliberately leaves a given-up account ``past_due``
    because the debt is real. So a customer whose subscription lapsed for non-payment was
    told forever after that they "already have an active subscription", and could never
    buy it back. ``is_subscribed``'s own reasoning is the fix: *cancelled / expired —
    nothing is held any more, so re-buying is right*. A lapsed module holds nothing.

    Every intended block survives, because each one still grants access: a live paid
    module, a running trial, and a past-due module inside its grace — that last being the
    case the docstring calls the worst version of a double buy.
    """
    row = store.module_row(entity_id, (function_code or "").strip().upper())
    if row is None or not access.is_subscribed(phase=row.phase):
        return False
    return access.grants_access(
        clock.now(),
        phase=row.phase,
        trial_end=getattr(row, "trial_end", None),
        app_access_until=getattr(row, "app_access_until", None),
        # From the ACCOUNT: one payer has one cycle, and the per-row copy drifts.
        period_end=store.paid_through_for_user(getattr(row, "payer_user_id", None)),
        past_due_grace_days=policy.current().past_due_window_days,
    )


def resolve_target_plan(entity_id, requested_code: str | None) -> PlanView:
    """Choose the plan to subscribe to.

    With an explicit module code, use that module's available plan. Without one,
    fall back to the single available module the entity isn't already subscribed
    to; raise if the choice is ambiguous or there's nothing left to buy.
    """
    if requested_code:
        plan = catalog.plan_for_module(requested_code)
        if plan is None:
            raise CheckoutError(
                f"No available subscription plan for module {requested_code!r}."
            )
        return plan

    candidates = [
        plan
        for plan in catalog.available_plans()
        if not _has_active_subscription(entity_id, plan.function_code)
    ]
    if not candidates:
        raise CheckoutError(
            "This entity is already subscribed to all available modules.", status=409
        )
    if len(candidates) > 1:
        raise CheckoutError("Please choose which module to subscribe to.")
    return candidates[0]


# NOTE: there is deliberately no "get or create the payer's customer" helper here, and
# nothing in this module creates a Stripe Customer. A customer must not exist until a
# card has actually been saved — creating one up front left an orphan behind every
# abandoned checkout. Both entry points (``start_modules_checkout``,
# ``start_payment_method_setup``) pass a possibly-None customer to
# ``create_setup_checkout_session``, and Stripe creates it at session CONFIRMATION;
# ``_adopt_session_customer`` then takes ownership of it.
#
# To READ the payer's customer use ``_resolve_customer_id`` (or
# ``_customer_id_for_entity``), which never creates.


def _resolve_customer_id(user_id) -> str | None:
    """The payer's Stripe customer: the local mapping first, then Stripe's own record.

    The mapping row is a CACHE, not the source of truth. ``_seed_user_customer_mapping``
    swallows its own write failures, so a payer can have a real, card-bearing customer in
    Stripe and no row here. Stripe knows which one: ``_adopt_session_customer`` stamps
    ``metadata.user_id`` on every customer it adopts, and deliberately does NOT swallow
    that failure — precisely so this lookup can recover from a lost mapping.

    Skipping that second step is not a smaller answer, it is a WRONG one, and every
    caller draws a different bad conclusion from it: checkout opens a setup session with
    no customer and Stripe mints a DUPLICATE, and the trial-end job expires a trial whose
    card was fine. The search is what makes the swallow above safe.

    Re-seeds the mapping on a hit. That is NOT just a cache warm-up — it is load-bearing.
    The anchor and ``paid_through`` live on the very same ``user_stripe_customer`` row, so
    without the row ``store.start_billing_cycle`` no-ops (it has nothing to write to) and
    ``_bill_module_change_in_house`` gives up with "could not anchor" — expiring the trial
    it just resolved a perfectly good customer for. Returning the id without writing the
    row would fix the lookup and leave the billing broken one step later.

    It also means a broken payer costs one search rather than one per request, and the
    log line below is how you find out the seed is failing at all.

    A Stripe failure PROPAGATES here rather than degrading to None — do not wrap this in
    a bare except. The search only runs when the mapping row is already missing, so the
    choice is between raising and answering "no customer" WRONGLY, and every caller
    handles the raise better than the wrong answer: the trial job catches per entity and
    retries tomorrow (instead of expiring a paid module today), the payment-method status
    endpoint already degrades to "no card", and checkout failing beats minting a
    duplicate. On the healthy path the mapping hits and Stripe is never called at all.

    NOT used on render paths (see ``modules._entity_customer_id``): a payer who genuinely
    has no customer would search on every page load and always find nothing.
    """
    mapped = store.customer_id_for_user(user_id)
    if mapped:
        return mapped
    if not user_id:
        return None
    found = find_customer_by_user(str(user_id))
    customer_id = (found or {}).get("id")
    if not customer_id:
        return None
    logger.warning(
        "subscription: payer {} had customer {} in Stripe but no mapping row; "
        "recovered it by search and re-seeded the mapping",
        user_id,
        customer_id,
    )
    _seed_user_customer_mapping(user_id, customer_id)
    return customer_id


def _seed_user_customer_mapping(user_id, customer_id) -> None:
    """Record the payer->customer link locally (best-effort).

    Lets ``_resolve_customer_id`` answer without a Stripe search. A failure here must
    never block customer resolution — the customer already exists in Stripe, which is
    the source of truth, and the ``metadata.user_id`` stamp keeps it findable — so it's
    logged and swallowed.
    """
    if not user_id or not customer_id:
        return
    try:
        store.upsert_customer_mapping(user_id, customer_id)
    except Exception:
        logger.exception(
            "subscription: failed to seed user->customer mapping for user {}", user_id
        )


def _plan_for_codes(codes):
    """The catalog plan that bills exactly ``codes`` for ONE entity.

    A single module bills at its own price; two or more bill as the single bundle price
    — the bundle IS the discount, so there's no coupon and no per-module share of it.
    Raises ``CheckoutError`` when the live catalog can't express the combination.
    """
    wanted = sorted({str(c).strip().upper() for c in (codes or []) if str(c).strip()})
    if not wanted:
        raise CheckoutError("No modules to bill.")
    if len(wanted) == 1:
        plan = catalog.plan_for_module(wanted[0])
        if plan is None:
            raise CheckoutError(
                f"No available subscription plan for module {wanted[0]!r}."
            )
        return plan
    bundle = catalog.bundle_plan()
    if bundle is None or not bundle.covers(wanted):
        raise CheckoutError(
            "No bundle plan is configured for that combination of modules.", status=409
        )
    return bundle


def _create_paid_subscriptions(
    entity, user, customer_id: str, plans: list[PlanView], payment_method: str,
    idempotency_scope: str,
) -> list[str]:
    """Bill ``plans``' modules for this entity on the payer's ONE subscription.

    The entity has a single line whose price is decided by the modules it bills for, so
    this reconciles that line (add / swap 280 <-> 400) rather than creating a
    subscription per module. Modules already billed are skipped. Returns the codes newly
    billed.

    This is the BUY path, so it bills now: the customer just asked for the module and is
    expecting a charge for today-to-the-anchor, not a surprise on their next invoice.
    """
    current = _billed_codes_in_house(entity.id)
    new_codes = {plan.function_code.upper() for plan in plans} - current
    if not new_codes:
        return []

    # Unlike a trial conversion, this is interactive: the customer is waiting, so a
    # failure has to surface a message rather than quietly leave them unsubscribed.
    paid_through = _bill_module_change_in_house(
        entity.id, getattr(user, "id", None), customer_id, current, new_codes
    )
    if paid_through is None:
        raise CheckoutError(
            "We couldn't set up the subscription. Please check your payment "
            "method and try again.",
            status=402,
        )
    # Write the rows and open the access gate. Easy to miss, because under Stripe this
    # was done afterwards by the subscription webhook: without it the customer was
    # charged and the module never switched on.
    _grant_purchased_modules(entity.id, getattr(user, "id", None), new_codes)
    return sorted(new_codes)


def _in_cancellation_window(entity_id, function_code) -> bool:
    """True while a cancelled module still has the access it was charged an extension for.

    Stripe can't answer this: cancelling swaps the entity's line down to the survivor's
    price (or parks it on the £0 grace price), so the cancelled module has no view at all
    — yet its access runs to ``app_access_until`` and its extension is queued for the
    anchor invoice. That state is the app's, and it lives on the mirror row.
    """
    try:
        row = store.module_row(entity_id, function_code)
    except Exception:
        logger.exception(
            "checkout: could not read the cancellation window for {} {}",
            entity_id,
            function_code,
        )
        return False
    return bool(
        row is not None
        and row.phase == PHASE_SCHEDULED_CANCEL
        and row.app_access_until is not None
        and row.app_access_until > clock.now()
    )


def _customer_id_for_entity(entity_id) -> str | None:
    """The Stripe customer billing this entity, or None before one exists.

    entity -> payer -> customer. The customer belongs to the PAYER, not the entity: one
    card covers every entity they own. The first hop is a local read; the second goes
    through ``_resolve_customer_id``, which falls back to Stripe when the mapping row is
    missing.

    Stripe is still the payment RAIL — invoices are issued against this customer — so
    this survives the removal of the subscription biller.
    """
    payer_id = store.payer_for_entity(entity_id)
    return _resolve_customer_id(payer_id) if payer_id else None


def _resolve_checkout_plans(entity_id, requested_codes) -> list[PlanView]:
    """Validate the requested module codes into plans to subscribe to.

    Raises ``CheckoutError`` for an unknown plan, a module that already has an active
    subscription, or one still inside a paid cancellation window (which must be renewed,
    not re-bought). With no codes, falls back to the single unsubscribed module."""
    codes = [c.strip().upper() for c in (requested_codes or []) if c and c.strip()]
    if not codes:
        return [resolve_target_plan(entity_id, None)]
    plans: list[PlanView] = []
    for code in dict.fromkeys(codes):  # dedupe, preserve order
        plan = catalog.plan_for_module(code)
        if plan is None:
            raise CheckoutError(f"No available subscription plan for module {code!r}.")
        if _has_active_subscription(entity_id, plan.function_code):
            # A trial is refused for the same reason as a paid module — the entity
            # already has it — but saying "active subscription" to someone mid-trial is
            # simply untrue, and hides the fact that they need do nothing.
            row = store.module_row(entity_id, plan.function_code.upper())
            if row is not None and row.phase == PHASE_TRIAL:
                raise CheckoutError(
                    f"Module {code} is already on a free trial — it becomes a paid "
                    "subscription automatically when the trial ends.",
                    status=409,
                )
            raise CheckoutError(
                f"Module {code} already has an active subscription.", status=409
            )
        # A module cancelled out of a bundle has NO billing line, so the guard above is
        # blind to it — but its extension is queued and its access still runs. Buying it
        # again would charge for the module a second time on top of that extension.
        # Renewing is the only correct move, and it also reverses the extension.
        if _in_cancellation_window(entity_id, plan.function_code):
            raise CheckoutError(
                f"Module {code} is still active until its cancellation date — "
                "use Renew instead.",
                status=409,
            )
        plans.append(plan)
    return plans


def start_modules_checkout(
    entity,
    user,
    success_url: str,
    cancel_url: str,
    requested_codes: list[str] | None = None,
):
    """Subscribe an entity to one or more modules — ONE paid subscription per module.

    Three outcomes:

    * **Card on file AND this entity has billing consent** → create the paid
      subscriptions directly with the saved card. Returns ``{"created": [codes]}``.
    * **Card on file but NO consent for this entity** → returns
      ``{"needs_confirmation": {...}}`` and charges nothing. See below.
    * **No card yet** → a hosted setup-mode Checkout captures one; the module codes
      ride on its metadata and the subscriptions are created on return (see
      ``complete_setup_checkout``). Returns ``{"url": <setup checkout url>}``.

    The consent gate exists because the card is the PAYER's, shared by every entity
    they pay for. Without it, saving a card while setting up entity #1 silently
    authorises charges for every entity created afterwards — click Subscribe on a brand
    new entity and it just bills, with no prompt. Having a card is necessary to be
    charged; agreeing to be billed for THIS entity is also required. (The same gate
    guards the bigger surface, ``convert_or_expire_due_trials``, where a trial would
    otherwise convert to paid with no user action at all.)

    Either way the entity ends up with ONE line on the payer's subscription, priced
    by the modules it bills (standalone, or the bundle for both).

    Raises ``CheckoutError`` when a module is unavailable, already actively
    subscribed, or the choice is ambiguous.
    """
    customer_id = _customer_id_for_entity(entity.id)  # None on first checkout
    plans = _resolve_checkout_plans(entity.id, requested_codes)

    # No customer is resolved-or-created here, deliberately: a payer with no customer
    # also has no saved card, so they're headed for the setup checkout below — and
    # creating one now would leave an orphan behind every abandoned checkout. Stripe
    # creates it when the card is saved (see create_setup_checkout_session).
    payment_method = customer_default_payment_method(customer_id) if customer_id else None

    # A saved card implies a customer (it's read off one), but say so explicitly —
    # customer_id is Optional now that this no longer creates one up front.
    if customer_id and payment_method:
        if not store.has_billing_consent(entity.id):
            # Charge NOTHING. The caller shows "you'll be billed X on card ending Y"
            # and calls confirm_modules_checkout if the payer accepts.
            return {"needs_confirmation": _billing_confirmation(entity, plans, payment_method)}
        # Reuse the saved card — no redirect, no extra card. A fresh idempotency scope
        # per attempt guards Stripe SDK network retries without blocking a later
        # re-subscribe of the same module.
        created = _create_paid_subscriptions(
            entity, user, customer_id, plans, payment_method, uuid.uuid4().hex
        )
        return {"created": created}

    # No card yet: capture one via a hosted setup-mode Checkout (needs a currency —
    # use the modules' billing currency, which they share).
    currency = _session_currency(plans)
    session = create_setup_checkout_session(
        customer_id,
        success_url,
        cancel_url,
        currency,
        metadata={
            "entity_id": str(entity.id),
            "user_id": str(getattr(user, "id", "")),
            "modules_to_subscribe": ",".join(p.function_code.upper() for p in plans),
        },
    )
    return {"url": session.get("url")}


def _billing_confirmation(entity, plans: list[PlanView], payment_method: str) -> dict:
    """What the payer needs to see before a first charge on this entity is authorised.

    The amount is the price of the whole combination, not a per-module sum — two modules
    bill as the single bundle price (the bundle IS the discount), so summing the plans
    would overstate it.
    """
    plan = _plan_for_codes([p.function_code for p in plans])
    return {
        "entity_id": str(entity.id),
        "entity_name": entity.name,
        "codes": [p.function_code.upper() for p in plans],
        "amount": plan.amount,
        # Formatted HERE, not in the dialog. The browser has no way to know how many
        # minor units a currency has, so the script divided by a hardcoded 100 — which
        # would quote a customer 2.80 while authorising a charge of 280 in a zero-decimal
        # currency. The one number a payer is asked to approve is not a place to guess.
        "formatted_amount": money.format_minor(plan.amount, plan.currency_code),
        "currency": plan.currency_code,
        "interval": plan.billing_interval,
        "card": payment_method_display(payment_method),
    }


def authorize_entity_billing(entity, user) -> dict:
    """Record consent to bill this entity WITHOUT subscribing or charging anything.

    For a module still inside its app-level trial. The trial has paid time left, so the
    right outcome is "let it run and convert at term end", not "charge now" — which is
    what going through ``confirm_modules_checkout`` would do, since an app-level trial
    has no Stripe object and therefore doesn't look like an active subscription to
    ``_resolve_checkout_plans``.

    Idempotent (consent is once per entity), so a double-click is harmless.
    """
    store.record_billing_consent(entity.id, getattr(user, "id", None), "confirmed")
    return {"ok": True}


def confirm_modules_checkout(
    entity,
    user,
    success_url: str,
    cancel_url: str,
    requested_codes: list[str] | None = None,
):
    """Record the payer's consent to be billed for THIS entity, then subscribe.

    The second half of the ``needs_confirmation`` handshake: the payer has been shown
    the amount and the card, and accepted. Consent is per entity and permanent, so
    subsequent module purchases on this entity go straight through.

    Delegates to ``start_modules_checkout``, which re-validates the modules — the codes
    come back from the client, so they can't be trusted to still be buyable — and, now
    that consent exists, takes the charge path. It still routes to a setup Checkout if
    the card vanished between the two calls.
    """
    store.record_billing_consent(entity.id, getattr(user, "id", None), "confirmed")
    return start_modules_checkout(
        entity, user, success_url, cancel_url, requested_codes
    )


def _save_setup_checkout_card(entity, session_id: str) -> tuple[str, str, dict]:
    """Verify a setup-mode Checkout session belongs to this entity and save its card
    as the customer's default.

    Returns ``(customer_id, payment_method_id, session)``. Raises ``CheckoutError``
    if the entity has no billing account, the session isn't theirs, or no card was
    captured. Idempotent — re-running on the same session just re-sets the same
    default, so a page refresh is harmless.

    Shared by the two things a setup checkout can be for: capturing a card on its own
    (``complete_payment_method_setup``) and capturing one in order to subscribe
    (``complete_setup_checkout``).

    The customer is read off the SESSION, not resolved from the entity: on a payer's
    first card the customer didn't exist when the session was opened — Stripe created it
    at confirmation — so there is nothing local to resolve yet. Session ownership is
    checked against ``metadata.entity_id`` (which we stamp when opening the session)
    instead of against a pre-existing customer id.
    """
    session = retrieve_checkout_session(session_id)
    meta = session.get("metadata") or {}
    if str(meta.get("entity_id") or "") != str(entity.id):
        raise CheckoutError("Checkout session not found for this entity.", status=404)

    session_customer = session.get("customer")
    if isinstance(session_customer, dict):
        session_customer = session_customer.get("id")
    if not session_customer:
        # Setup mode with customer_creation="always" populates this on confirmation;
        # absent means the session was never completed.
        raise CheckoutError("No card was saved; please try again.", status=409)

    setup_intent = session.get("setup_intent") or {}
    payment_method = (
        setup_intent.get("payment_method") if isinstance(setup_intent, dict) else None
    )
    if isinstance(payment_method, dict):
        payment_method = payment_method.get("id")
    if not payment_method:
        raise CheckoutError("No card was saved; please try again.", status=409)

    customer_id = _adopt_session_customer(session_customer, meta.get("user_id"))
    if customer_id != session_customer:
        # The payer already had a customer; move the card onto it before defaulting.
        attach_payment_method(payment_method, customer_id)

    # Entering a card in a Checkout opened FOR THIS ENTITY is consent to bill it —
    # this is the other way consent is granted, alongside the in-app confirmation.
    # Without it, a payer who added a card during entity #2's own setup would still be
    # asked to confirm, which would be nonsense.
    store.record_billing_consent(entity.id, meta.get("user_id"), "card")

    # Make the captured card the default so subscriptions (and future invoices)
    # bill it — including a trial that converts to paid at the end of its term.
    set_customer_default_payment_method(customer_id, payment_method)
    return customer_id, payment_method, session


def _adopt_session_customer(session_customer: str, user_id) -> str:
    """Take ownership of the Customer a setup Checkout produced, and return the id to use.

    Sessions for a payer with no customer are opened without one so that abandoning them
    creates nothing (see ``create_setup_checkout_session``). The customer Stripe then
    makes at confirmation has none of our bookkeeping, so this stamps ``metadata.user_id``
    on it and writes the local mapping.

    That stamp is load-bearing: it is what ``find_customer_by_user`` recovers from when
    the local mapping is missing, so unlike ``_seed_user_customer_mapping`` its failure is
    NOT swallowed. A customer with neither the stamp nor a mapping row is invisible to
    every lookup we have, so it's better to fail the request and let the caller retry.

    Ordering matters: the existing-customer check comes FIRST so we never stamp
    ``user_id`` onto a duplicate — two stamped customers would make the search fallback
    ambiguous, which is worse than the duplicate itself.

    If the payer already had a customer (a second setup session confirming after the
    first — two tabs, a back-button replay), that one wins and is returned. The duplicate
    Stripe just made is logged for manual cleanup rather than deleted here: deleting a
    Stripe customer is irreversible and this is not the place to do it unprompted.
    """
    if not user_id:
        # No payer on the session metadata — nothing to key the mapping on. The customer
        # still exists and holds the card, so use it rather than failing the save.
        logger.error(
            "subscription: setup session customer {} has no user_id in metadata; "
            "cannot map it to a payer",
            session_customer,
        )
        return session_customer

    # Resolved rather than read straight off the mapping: this IS the duplicate guard,
    # and a payer whose mapping row went missing is exactly the one Stripe has just
    # built a second customer for. Reading locally here would miss the duplicate and
    # then stamp ``user_id`` onto it — two stamped customers, which makes the search
    # ambiguous and is worse than the duplicate itself.
    existing = _resolve_customer_id(user_id)
    if existing and existing != session_customer:
        logger.error(
            "subscription: payer {} already had customer {}; setup checkout created "
            "duplicate {} — using the existing one, {} needs manual cleanup in Stripe",
            user_id,
            existing,
            session_customer,
            session_customer,
        )
        return existing

    set_customer_identity(
        session_customer, metadata={"user_id": str(user_id)}, **_payer_identity(user_id)
    )
    _seed_user_customer_mapping(user_id, session_customer)
    return session_customer


def _payer_identity(user_id) -> dict[str, str]:
    """The payer's display fields for their Stripe customer: ``name``/``email``/``description``.

    The customer is the PAYER, not the entity — one customer can bill several entities,
    so an entity name here would be wrong the moment a second entity is added. (Which
    entity a charge is for lives on the subscription ITEM metadata and on the invoice
    line labels, not on the customer.)

    ``name`` is the human name so invoices read properly; ``description`` carries the
    username because ``first_name``/``last_name`` are not unique and two payers sharing a
    name are otherwise indistinguishable in the Stripe dashboard list.

    These OVERWRITE whatever the payer typed into Checkout — our record is the source of
    truth for who they are. ``email`` is the exception: it's nullable locally, so when we
    don't have one we leave Stripe's Checkout-collected address rather than blanking it.

    Returns {} if the user can't be loaded; the ``user_id`` stamp still goes on, since
    resolvability matters more than a display name.
    """
    from models.db import User

    user = User.query.get(str(user_id)) if user_id else None
    if user is None:
        logger.warning(
            "subscription: no user {} to name their Stripe customer after", user_id
        )
        return {}

    fields: dict[str, str] = {}
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    if name:
        fields["name"] = name
    if user.username:
        fields["description"] = f"@{user.username}"
    if user.email:
        fields["email"] = user.email
    return fields


def entity_has_payment_method(entity) -> bool:
    """True if the entity has a card on file, read live from Stripe.

    Onboarding Step 2 gates "Save & Next" on this. Trials do NOT need it — they're
    app-level and card-free (see ``trial_payment_method``); the card is only consulted
    when a trial ends, to decide convert-to-paid vs expire.
    """
    customer_id = _customer_id_for_entity(entity.id)
    if not customer_id:
        return False
    return customer_default_payment_method(customer_id) is not None


def trial_payment_method(customer_id: str | None) -> str | None:
    """The card a converting trial should bill, or None when the payer hasn't added one.

    The card is OPTIONAL during an app-level trial — it's only consulted when the trial
    ENDS, where its presence decides convert-to-paid vs expire (see
    ``convert_or_expire_due_trials``). So this reports its absence rather than raising.
    """
    return customer_default_payment_method(customer_id)


def start_payment_method_setup(entity, user, success_url: str, cancel_url: str) -> dict:
    """Open a hosted setup-mode Checkout that saves a card WITHOUT subscribing.

    Used by onboarding Step 2, where the card must be on file before the wizard can
    continue but the trials themselves aren't created until finalize. Returns
    ``{"url": …}``.

    Does NOT create the Stripe customer. A payer who has none yet gets a session with
    ``customer_creation="always"``, so Stripe creates the customer only when the card is
    actually saved — abandoning onboarding here leaves nothing behind. An existing
    customer is passed through so the card lands on it rather than on a duplicate.

    Setup mode needs a currency; use the modules' billing currency (they share one).
    Raises if the catalog cannot supply one — see ``_session_currency``.
    """
    # Resolved, not read locally: passing None for a payer who DOES have a customer
    # sends Stripe ``customer_creation="always"`` and mints a duplicate, stranding the
    # card they already saved on the original.
    customer_id = _resolve_customer_id(getattr(user, "id", None))
    plans = catalog.available_plans()
    currency = _session_currency(plans)
    session = create_setup_checkout_session(
        customer_id,
        success_url,
        cancel_url,
        currency,
        metadata={
            "entity_id": str(entity.id),
            "user_id": str(getattr(user, "id", "")),
            # No modules_to_subscribe: this session saves a card, nothing more. The
            # completion handler must not create subscriptions off it.
            "purpose": "payment_method",
        },
    )
    return {"url": session.get("url")}


def complete_payment_method_setup(entity, session_id: str) -> bool:
    """Finish a card-only setup checkout: save the captured card as the default.

    Deliberately creates NO subscriptions — onboarding starts the trials at finalize,
    once the whole wizard is done. Safe to re-run (a refresh of the return URL just
    re-sets the same default). Returns True once the card is on file.
    """
    _save_setup_checkout_card(entity, session_id)
    return True


def complete_setup_checkout(entity, user, session_id: str) -> list[str]:
    """Finish a setup-mode checkout: save the captured card as the customer default,
    then create one paid subscription per module recorded on the session metadata.

    Returns the codes subscribed (possibly empty). Raises ``CheckoutError`` if the
    session isn't this entity's. Safe to re-run (idempotent subscription creation +
    the already-subscribed guard), so a page refresh won't double-charge."""
    customer_id, payment_method, session = _save_setup_checkout_card(entity, session_id)

    codes = (session.get("metadata") or {}).get("modules_to_subscribe", "")
    plans: list[PlanView] = []
    for code in [c for c in codes.split(",") if c]:
        plan = catalog.plan_for_module(code)
        if plan is None or _has_active_subscription(entity.id, plan.function_code):
            continue
        plans.append(plan)
    if not plans:
        return []
    # Scope idempotency to this checkout session so a fresh attempt (possibly a new
    # card) can't collide with a burned key from an earlier one.
    return _create_paid_subscriptions(
        entity, user, customer_id, plans, payment_method, session_id
    )


def _set_module_access(entity_id, function_code: str, enabled: bool) -> None:
    """Flip a module's access gate. Best-effort: logged, never raised — the trial row
    is the record of truth and a later resync/sweep self-heals the flag."""
    from blueprints.entity.services.modules import set_entity_module

    try:
        _data, status = set_entity_module(
            entity_id, function_code, enabled, actor="subscription"
        )
        if status != 200:
            logger.warning(
                "trial: access write for {} {} returned {}: {}",
                entity_id,
                function_code,
                status,
                _data,
            )
    except Exception:
        logger.exception(
            "trial: failed to set access for {} {}", entity_id, function_code
        )


def start_module_trial(entity, user, plan: PlanView):
    """Start the APP-LEVEL trial for one module. No Stripe object is created.

    The trial clock lives entirely in the app (``entity_module_subscription``): access
    runs until ``trial_end = now + TRIAL_PERIOD_DAYS``. Stripe only gets involved when
    the trial ENDS (see ``convert_or_expire_due_trials``), so a trial needs neither a
    customer nor a card — whether one exists by then decides convert vs expire.

    The acting ``user`` becomes the module's payer. Returns the trial row, or None if
    the module already has a trial or a subscription (the trial is once per module).
    """
    code = plan.function_code.upper()
    if store.module_row(entity.id, code) is not None:
        return None

    now = clock.now()
    trial_end = now + timedelta(days=policy.current().trial_days)
    row = store.upsert_module_row(
        entity.id,
        code,
        getattr(user, "id", None),
        phase=PHASE_TRIAL,
        trial_end=trial_end,
        app_access_until=trial_end,
    )
    _set_module_access(entity.id, code, True)
    return row


def start_module_trials(entity, user, requested_codes) -> list[str]:
    """Start app-level trials for never-used modules; return their codes.

    Every requested module must be trial-eligible — the trial is once per module, so a
    module with any existing trial or subscription row is rejected and the caller routes
    it to paid checkout instead. Raises ``CheckoutError`` for an unknown plan too.

    No Stripe customer and no card are needed: the trial is tracked entirely in the app
    and only reaches Stripe when it ends.
    """
    codes = [c.strip().upper() for c in (requested_codes or []) if c and c.strip()]
    if not codes:
        raise CheckoutError("No modules specified for a trial.")

    plans: list[PlanView] = []
    for code in dict.fromkeys(codes):  # dedupe, preserve order
        plan = catalog.plan_for_module(code)
        if plan is None:
            raise CheckoutError(
                f"No available subscription plan for module {code!r}."
            )
        if store.module_row(entity.id, plan.function_code) is not None:
            raise CheckoutError(
                f"Module {code} has already used its free trial.", status=409
            )
        plans.append(plan)

    started: list[str] = []
    for plan in plans:
        if start_module_trial(entity, user, plan) is not None:
            started.append(plan.function_code.upper())
    return started


def convert_or_expire_due_trials(limit: int | None = None) -> dict:
    """Close out app-level trials whose term has ended (run on a schedule).

    For each due trial: if the payer has a card on file the module CONVERTS to a paid
    subscription; otherwise the trial EXPIRES and access is revoked. This is the only
    thing that ends an app-level trial — the access sweep deliberately leaves modules
    with no Stripe subscription alone.

    Returns ``{"converted": [...], "expired": [...]}``.
    """
    now = clock.now()
    converted: list[dict] = []
    expired: list[dict] = []
    # Grouped by ENTITY, because an entity bills on ONE line: two modules whose trials
    # end together are a single swap to the bundle price, not two. Converting them
    # row-by-row cut two invoices seconds apart — the first billing a standalone price
    # the customer never chose, the second immediately crediting it back.
    by_entity: dict[str, list] = {}
    for row in store.due_trials(now, limit=limit):
        by_entity.setdefault(row.entity_id, []).append(row)

    for entity_id, rows in by_entity.items():
        try:
            billed, unbilled = _convert_due_trials(entity_id, rows)
        except Exception:
            logger.exception(
                "trial: failed to close out trials for entity {}", entity_id
            )
            continue
        converted.extend(
            {"entity_id": entity_id, "code": row.function_code} for row in billed
        )
        for row in unbilled:
            try:
                _expire_due_trial(row)
            except Exception:
                logger.exception(
                    "trial: failed to expire trial for {} {}",
                    entity_id,
                    row.function_code,
                )
                continue
            expired.append({"entity_id": entity_id, "code": row.function_code})

    # One email per ENTITY, not per module — for the same reason the conversion itself
    # is grouped by entity: two modules whose trials end together are a single event the
    # customer experienced once, and two emails seconds apart describing it would read
    # as a bug. Sent after every entity has been closed out, so the mail can never
    # describe a conversion a later exception undid.
    _notify_trial_outcomes(converted, expired, by_entity)
    return {"converted": converted, "expired": expired}


def _notify_trial_outcomes(converted: list[dict], expired: list[dict],
                           by_entity: dict) -> None:
    """Tell each payer how their trial ended. Never raises — see ``notify``.

    Deduped on entity + module set, which a trial can only reach once: after this runs
    the rows are off ``trial`` phase, so the same trial cannot be closed out twice.
    """
    from blueprints.subscription.services import notify

    payers = {
        entity_id: rows[0].payer_user_id
        for entity_id, rows in by_entity.items()
        if rows
    }
    names = _entity_names_for_notice(set(payers))

    events = []
    for event, outcome in ((notify.TRIAL_CONVERTED, converted),
                           (notify.TRIAL_EXPIRED, expired)):
        by_id: dict[str, list[str]] = {}
        for item in outcome:
            by_id.setdefault(item["entity_id"], []).append(item["code"])
        for entity_id, codes in by_id.items():
            payer = payers.get(entity_id)
            if not payer:
                continue
            events.append((
                payer,
                event,
                f"{entity_id}:{','.join(sorted(codes))}",
                {
                    "entity_id": entity_id,
                    "entity_name": names.get(str(entity_id)),
                    "codes": sorted(codes),
                },
            ))
    notify.notify_many(events)


def _entity_names_for_notice(entity_ids) -> dict[str, str]:
    """{entity_id: name} in one query. Empty on any failure — an email that says
    "your company" is a smaller loss than a trial-close job that dies looking up a name.
    """
    if not entity_ids:
        return {}
    try:
        from models.db import Entity

        rows = Entity.query.filter(Entity.id.in_([str(i) for i in entity_ids])).all()
        return {str(e.id): (e.name or "").strip() for e in rows if (e.name or "").strip()}
    except Exception:
        logger.exception("trial: could not resolve entity names for notification")
        return {}


def notify_trials_ending(days_before: int = 3, limit: int | None = None) -> dict:
    """Warn payers about trials that end in ``days_before`` days.

    THE ONLY NOTIFICATION IN THE SYSTEM THAT CAN PREVENT A LAPSE. Everything else in this
    module reports something that has already happened — a trial that converted, a trial
    that expired, access that was revoked. This one arrives while the customer can still
    act, and the case it exists for is the trial that will NOT convert because no card is
    saved or billing for the entity was never confirmed: without it, that customer's first
    news is their module going dark.

    Reads the SAME three conditions ``_convert_due_trials`` will apply on the day
    (customer, card, consent) rather than a simplified version, so the warning cannot
    promise a conversion the conversion job then refuses. Where they must disagree it is
    in the safe direction: this runs days earlier, so a card saved in between turns a
    warned trial into a quiet one, never the reverse.

    Returns ``{"warned": [...], "skipped": [...]}``. Idempotent by the email log — the
    dedupe key is the entity, module set and trial-end date, so re-running warns nobody
    twice even if the daily window is widened or the job is run by hand.
    """
    now = clock.now()
    # A one-day window, not "everything within N days": run daily this tiles the calendar
    # exactly once per trial. A cumulative "<= N days" filter would re-match the same
    # trial on each of the N days before it ends and rely entirely on the email log to
    # stay quiet — correct, but it makes the dedupe row load-bearing for basic sanity
    # rather than a backstop.
    #
    # Anchored to CALENDAR MIDNIGHT, not to ``now``. A window of
    # ``[now + 3d, now + 4d)`` only tiles if the job runs at precisely 24-hour intervals,
    # and cron does not: a run at 08:10 followed by one at 08:15 leaves a five-minute
    # hole, and any trial ending inside it is never warned about at all. Found against
    # real data — a trial ending 13:00 HKT (05:00 UTC) fell before a window that opened
    # at 08:10 UTC and was silently skipped. Day-aligned, the windows tile whatever time
    # the job runs, and a second run the same day re-derives the SAME window (which the
    # email log then dedupes) instead of a shifted one.
    target = (now + timedelta(days=days_before)).astimezone(timezone.utc).date()
    start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    warned: list[dict] = []
    skipped: list[dict] = []
    by_entity: dict[str, list] = {}
    for row in store.trials_ending_between(start, end, limit=limit):
        by_entity.setdefault(row.entity_id, []).append(row)

    events = []
    names = _entity_names_for_notice(set(by_entity))
    for entity_id, rows in by_entity.items():
        try:
            payer = rows[0].payer_user_id
            codes = sorted(row.function_code.upper() for row in rows)
            amount, currency = _trial_line_price(entity_id, codes)
            context = {
                "entity_id": entity_id,
                "entity_name": names.get(str(entity_id)),
                "codes": codes,
                "trial_end": min(row.trial_end for row in rows),
                "amount": amount,
                "currency": currency,
                "needs_card": not _trial_will_convert(entity_id, payer),
            }
            events.append((
                payer,
                _notify_module().TRIAL_ENDING,
                f"{entity_id}:{','.join(codes)}:{context['trial_end']:%Y-%m-%d}",
                context,
            ))
            warned.append({"entity_id": entity_id, "codes": codes,
                           "needs_card": context["needs_card"]})
        except Exception:
            logger.exception(
                "trial: could not prepare ending-soon notice for entity {}", entity_id
            )
            skipped.append({"entity_id": entity_id, "reason": "error"})

    _notify_module().notify_many(events)
    return {"warned": warned, "skipped": skipped}


def _notify_module():
    """Imported lazily: ``notify`` reaches into the model layer, and importing it at
    module scope would drag the entity model graph in behind the Stripe client (same
    reason as ``money.decimal_places``)."""
    from blueprints.subscription.services import notify

    return notify


def _trial_will_convert(entity_id, payer_user_id) -> bool:
    """Whether this entity's trial has everything it needs to become a paid subscription.

    The exact conjunction ``_convert_due_trials`` enforces. A card alone is NOT enough —
    the payer's card is shared across every entity they pay for, so consent is what
    authorises charging it for THIS one. Any failure to determine it returns False, which
    sends the warning variant: nagging a customer who was fine is a far smaller harm than
    silently letting a trial they wanted lapse.
    """
    try:
        customer_id = _resolve_customer_id(payer_user_id)
        if not customer_id:
            return False
        if not trial_payment_method(customer_id):
            return False
        return bool(store.has_billing_consent(entity_id))
    except Exception:
        logger.exception(
            "trial: could not determine conversion readiness for entity {}", entity_id
        )
        return False


def _trial_line_price(entity_id, converting_codes) -> tuple[int | None, str | None]:
    """What this entity will bill per month once these trials convert.

    Priced on the FULL resulting module set, because an entity bills one line priced by
    the set it carries — quoting the converting module's standalone price would overstate
    the bill for an entity that ends up on the bundle. Returns ``(None, None)`` when the
    catalog can't price the combination, and the email simply omits the figure rather
    than guessing at it.
    """
    try:
        codes = {str(code).upper() for code in converting_codes}
        for row in store.module_rows_for_entity(entity_id):
            if access.is_billing_forward(phase=row.phase):
                codes.add(row.function_code.upper())
        plan = _plan_for_codes(codes)
        return plan.amount, plan.currency_code
    except Exception:
        logger.info(
            "trial: no catalog price for entity {}; omitting amount from notice",
            entity_id,
        )
        return None, None


def _convert_due_trials(entity_id, rows) -> tuple[list, list]:
    """Bill ONE entity's due trials as a single line change.

    Returns ``(converted, to_expire)``. Everything the entity can't be billed for comes
    back in ``to_expire`` for the caller to close out — a cancelled trial, no customer,
    no card, no consent for this entity, no live plan, or a card that wouldn't take the
    charge.

    All the module codes ending together go into ONE billing call, so the entity is
    priced straight at its final module set and the customer gets one invoice for one
    event — billing them row-by-row cut two invoices seconds apart, the first at a
    standalone price the customer never chose.

    The charge lands IMMEDIATELY, on the conversion day: converting is the moment the
    customer starts paying, so that is when the bill should arrive. The phase is moved
    off ``trial`` here so a re-run can't convert the same module twice.
    """
    # A cancelled trial ran its free days out but must never become a charge — that IS
    # what cancelling a trial means. Checked before anything else, so a payer with a
    # card and consent still doesn't get billed for one they cancelled.
    doomed = [row for row in rows if row.phase == PHASE_SCHEDULED_CANCEL]
    candidates = [row for row in rows if row.phase != PHASE_SCHEDULED_CANCEL]
    if not candidates:
        return [], doomed

    payer_user_id = candidates[0].payer_user_id
    # Resolved, not read locally. "No customer" ends this trial and revokes access, and
    # this job runs unattended — a payer whose mapping row went missing would lose a
    # module their card would have paid for, with nobody in the loop to notice.
    customer_id = _resolve_customer_id(payer_user_id)
    if not customer_id:
        return [], rows
    payment_method = trial_payment_method(customer_id)
    if not payment_method:
        return [], rows
    # The payer's card is shared across every entity they pay for, so a card alone is
    # NOT authorisation to bill this one. Without this check a brand-new entity's trial
    # converts to a real charge with no user action whatsoever, purely because a card
    # was saved for a different entity. Expire instead; the settings page nudges for
    # consent while the trial is still running (see modules.get_module_cards).
    if not store.has_billing_consent(entity_id):
        logger.info(
            "trial: entity {} has a card but no billing consent; expiring {} rather "
            "than charging",
            entity_id,
            ",".join(sorted(row.function_code for row in candidates)),
        )
        return [], rows

    billable = [
        row
        for row in candidates
        if catalog.plan_for_module(row.function_code) is not None
    ]
    for row in candidates:
        if row not in billable:
            logger.warning(
                "trial: no live plan for {}; expiring instead of converting",
                row.function_code,
            )
            doomed.append(row)
    if not billable:
        return [], doomed

    # Priced as a CHANGE from what the entity already bills to what it will bill: if
    # it is already paying for the other module, converting costs the marginal step up
    # to the bundle (400 - 280 = 120), not the converting module's standalone price.
    #
    # The charge is raised and collected here, on the conversion day, rather than left
    # to ride the next renewal — a charge that surfaces weeks later bundled with the
    # next period is impossible for the customer to recognise.
    #
    # A failure to collect returns None rather than raising, and the caller expires the
    # trial: a decline must not leave the rows stuck in ``trial`` with a past
    # ``trial_end``, or every future run of this job retries the same dead card forever.
    codes = {row.function_code.upper() for row in billable}

    paid_through = _bill_module_change_in_house(
        entity_id, payer_user_id, customer_id,
        _billed_codes_in_house(entity_id), codes,
    )
    if paid_through is None:
        # Could not collect. Treat it exactly like "no card": the caller expires the
        # trial rather than handing over modules nobody paid for.
        return [], rows
    _finish_conversion(entity_id, billable)
    return billable, doomed


def _billed_codes_in_house(entity_id) -> set[str]:
    """The modules this entity is ALREADY billed for, from Minty's own rows.

    The in-house counterpart of ``_entity_billing_line``, and it exists because that
    function cannot answer this question once the cutover is on: it reads the payer's
    Stripe SUBSCRIPTION items, and in-house there is no subscription, so it returns an
    empty set for every entity no matter what they are paying.

    That is not a cosmetic difference. An empty "before" makes ``changes.build_change``
    treat every upgrade as a fresh JOIN and charge the new module's STANDALONE price on
    top of what the entity already paid this period — the bundle discount is lost for the
    remainder of the period. Adding Payment Request to an entity already on Petty Cash was
    billed 65.33 (280 prorated) instead of 28.00 (the 120 bundle margin prorated).

    ``is_billing_forward`` matches what ``_cancel_module_in_house`` already uses to price
    a cancellation, so the two directions of a change agree on what the line holds.
    A ``scheduled_cancel`` module is therefore NOT counted: it is winding down and its
    marginal value has already been charged as an extension. Whether an entity that is
    part-way out should be re-priced onto a bundle is a pricing decision, not a coding
    one; it is left alone deliberately rather than settled here by accident.
    """
    return {
        row.function_code.upper()
        for row in store.module_rows_for_entity(entity_id)
        if access.is_billing_forward(phase=row.phase)
    }


def _bill_module_change_in_house(entity_id, payer_user_id, customer_id: str,
                                 current, codes):
    """Bill a module change from Minty's own arithmetic. Returns the new paid-through.

    Shared by the trial conversion and the BUY path — the money is the same either way,
    only the caller's response to failure differs (expire the trial vs tell the user).

    Returns None if nothing could be collected, which the caller treats exactly like a
    declined card: expire the trial rather than hand over modules that were not paid for.

    The FIRST conversion for a payer establishes their anchor at "now", so the period
    starts here and the charge is a full one — matching what Stripe billed at conversion
    (280.00). A later entity joining an existing payer is prorated against the anchor
    already recorded (373.33). Both figures were verified against Stripe before cutover.
    """
    from blueprints.subscription.services import changes
    from blueprints.subscription.services.billing import period_containing
    from models.db import Entity

    now = clock.now()
    anchor, _currency = store.billing_cycle_for_user(payer_user_id)
    if anchor is None:
        # Nothing has ever been billed for this payer: the cycle starts now, so this
        # period is charged in full rather than prorated against a period they were
        # never part of.
        plan = store.billing_plan_for_codes(current | codes)
        store.start_billing_cycle(payer_user_id, now, (plan.currency if plan else ""))
        anchor, _currency = store.billing_cycle_for_user(payer_user_id)
        if anchor is None:
            logger.error("trial: could not anchor payer {}", payer_user_id)
            return None

    period = period_containing(anchor, now)

    # The entity name is what makes the invoice line readable, but it must not be able
    # to STOP the conversion: failing here would cost the customer their modules over a
    # cosmetic lookup. Falls back to the id and logs loudly — a line reading as a uuid
    # is bad, and silently not billing is worse.
    name = str(entity_id)
    try:
        entity = Entity.query.filter_by(id=entity_id).first()
        if entity is not None and (entity.name or "").strip():
            name = entity.name.strip()
        else:
            logger.error("billing: entity {} has no name for its invoice line", entity_id)
    except Exception:
        logger.exception(
            "billing: could not read the name for entity {}; billing it as its id",
            entity_id,
        )

    try:
        invoice = changes.issue_change(
            customer_id, entity_id, name, current, current | codes, period, now
        )
    except Exception:
        logger.exception(
            "trial: could not bill the conversion for {} {} in-house", entity_id, codes
        )
        return None

    # A None invoice means nothing was owed (already at this price), which is a success:
    # the modules are granted and the period stands.
    if invoice is not None and invoice.get("status") != "paid":
        logger.warning(
            "trial: conversion invoice {} for entity {} is {}; not granting modules",
            invoice.get("id"),
            entity_id,
            invoice.get("status"),
        )
        return None

    store.set_paid_through(payer_user_id, period.end)
    return period.end


def _finish_conversion(entity_id, billable) -> None:
    """Write the converted rows and align the entity's other active modules.

    Shared by both billers so the local state after a conversion is identical whichever
    one collected the money — the mirror should not be able to tell them apart.
    """
    now = clock.now()
    for row in billable:
        fields = {"phase": PHASE_ACTIVE, "app_access_until": None}
        # Stamped once, on the FIRST charge, and never moved: it is what marks this row
        # as a paid module rather than a trial for the rest of its life. Re-stamping on a
        # later change would still read as non-null, but the date would stop meaning
        # "when they started paying".
        if getattr(row, "first_billed_at", None) is None:
            fields["first_billed_at"] = now
        store.upsert_module_row(
            entity_id, row.function_code, row.payer_user_id, **fields
        )


def _bill_reinstatement_in_house(entity, user, code: str, row) -> None:
    """Collect the part of the period a reinstated module is not covered for.

    The extension paid up to ``app_access_until``; the renewal skipped this module for
    the rest of the period. So the customer owes from one to the other, at the MARGINAL
    price — putting Petty Cash back onto an entity already paying for Payment Request costs
    the 120 difference, not Petty Cash's 280.

    ``build_change`` does that arithmetic already: prorating from ``app_access_until``
    rather than from now bills exactly the uncovered window.

    Raises rather than returning on failure. Reinstating is a purchase, and a purchase
    that is not paid for must not be granted.
    """
    from blueprints.subscription.services import changes
    from blueprints.subscription.services.billing import period_containing

    payer_user_id = row.payer_user_id or getattr(user, "id", None)
    # Resolved, not read locally: "no customer" here reinstates the module WITHOUT
    # charging, so a missing mapping row is money quietly not collected.
    customer_id = _resolve_customer_id(payer_user_id)
    anchor, _currency = store.billing_cycle_for_user(payer_user_id)
    covered_to = row.app_access_until
    if not customer_id or anchor is None or covered_to is None:
        # Nothing to prorate against. Better to reinstate than to strand the customer
        # over a missing date, but say so — this is money that was not collected.
        logger.error(
            "reinstate: cannot price the uncovered period for {} {} (customer={} "
            "anchor={} covered_to={}); reinstating WITHOUT charging",
            entity.id, code, customer_id, anchor, covered_to,
        )
        return

    # The period we are IN, not the one containing covered_to -- those differ exactly
    # when the extension runs past the anchor, which is the case this guard is for.
    period = period_containing(anchor, clock.now())
    if covered_to >= period.end:
        # The 30 free days already cover the rest of this period. Charging anyway would
        # bill for days the extension paid for.
        return

    before = _billed_codes_in_house(entity.id) - {code}
    name = getattr(entity, "name", None) or str(entity.id)
    try:
        invoice = changes.issue_change(
            customer_id, entity.id, name, before, before | {code}, period, covered_to
        )
    except Exception as exc:
        raise CheckoutError(
            "We couldn't take the payment to restore this module. Please check your "
            "payment method and try again.",
            status=402,
        ) from exc

    if invoice is not None and invoice.get("status") != "paid":
        raise CheckoutError(
            "We couldn't take the payment to restore this module. Please check your "
            "payment method and try again.",
            status=402,
        )


def _grant_purchased_modules(entity_id, payer_user_id, codes) -> None:
    """Activate modules bought outright, once their charge has been collected.

    The buy-path counterpart of ``_finish_conversion``. That one starts from existing
    trial ROWS; a purchase may have no row at all for the module, so this works from
    codes and creates them.

    Ordered so a failure cannot hand over an unpaid module: the caller has already
    collected the money before this runs.
    """
    now = clock.now()
    for code in sorted({str(c).upper() for c in codes}):
        existing = store.module_row(entity_id, code)
        fields = {
            "phase": PHASE_ACTIVE,
            "app_access_until": None,
        }
        if getattr(existing, "first_billed_at", None) is None:
            fields["first_billed_at"] = now
        store.upsert_module_row(entity_id, code, payer_user_id, **fields)
        _set_module_access(entity_id, code, True)


def _expire_due_trial(row) -> None:
    """End a trial that had nothing to bill: mark it expired and revoke access."""
    store.upsert_module_row(
        row.entity_id,
        row.function_code,
        row.payer_user_id,
        phase=PHASE_EXPIRED,
        app_access_until=None,
    )
    _set_module_access(row.entity_id, row.function_code, False)


def _extension_amount(line_amount: int, remaining_codes) -> int:
    """What cancelling a module actually saves — its MARGINAL price on the line.

    A bundled module isn't worth its standalone price: dropping Petty Cash from a 400
    bundle leaves Bill at 280, so Petty Cash's marginal value is 120 — not 280. With no
    survivor, the whole line price is the marginal amount.
    """
    if not remaining_codes:
        return max(0, int(line_amount))
    return max(0, int(line_amount) - int(_plan_for_codes(remaining_codes).amount))


def _prorate(amount: int, period_start, period_end, access_end) -> int:
    """The slice of ``amount`` covering the days between period_end and access_end."""
    if amount <= 0 or period_start is None or period_end is None or access_end is None:
        return 0
    extra = (access_end - period_end).total_seconds()
    span = (period_end - period_start).total_seconds()
    if extra <= 0 or span <= 0:
        return 0
    return max(0, round(amount * extra / span))


def _paid_cancel_terms(entity, user, code: str, row) -> dict:
    """What cancelling this PAID module would cost and when access would end.

    PURE — reads only. ``_cancel_module_in_house`` calls this and then writes exactly
    what it returns, and ``preview_cancel_module`` calls it to fill the confirmation
    dialog. That shared call is the point: the figure the user is shown before
    confirming and the figure recorded on the row cannot be computed two ways.

    Returns the payer id, the access end, the marginal amount, the prorated extension
    charge, and the modules that would survive.
    """
    from blueprints.subscription.services.billing import (
        Period,
        cancel_access_end,
        extension_charge,
        marginal_amount,
        period_containing,
    )

    payer_user_id = (getattr(row, "payer_user_id", None)) or getattr(user, "id", None)
    now = clock.now()

    current = {
        r.function_code.upper()
        for r in store.module_rows_for_entity(entity.id)
        if access.is_billing_forward(phase=r.phase)
    }
    if code not in current:
        raise CheckoutError(f"Module {code} isn't currently subscribed.", status=409)

    anchor, currency = store.billing_cycle_for_user(payer_user_id)
    paid_through = store.paid_through_for_user(payer_user_id)
    if anchor is None or paid_through is None:
        raise CheckoutError("This entity has no billing account yet.", status=409)

    access_end = cancel_access_end(
        paid_through, now, extension_days=policy.current().paid_cancel_access_days
    )

    # What the module was WORTH on the line — its marginal price, not its list price.
    # Dropping Petty Cash from a 400 bundle leaves Bill at 280, so it was worth 120;
    # charging 280 for the extension would bill more than it ever cost.
    remaining = current - {code}
    plan_now = store.billing_plan_for_codes(current)
    plan_after = store.billing_plan_for_codes(remaining) if remaining else None
    marginal = (
        marginal_amount(plan_now.amount, plan_after.amount if plan_after else None)
        if plan_now
        else 0
    )
    period = period_containing(anchor, paid_through - timedelta(seconds=1))
    amount = extension_charge(marginal, Period(period.start, paid_through), access_end)

    return {
        "payer_user_id": payer_user_id,
        "access_end": access_end,
        "paid_through": paid_through,
        "amount": amount,
        "marginal": marginal,
        "currency": currency,
        "remaining": sorted(remaining),
        "plan_after": plan_after,
    }


def _cancel_module_in_house(entity, user, code: str, row) -> dict:
    """Cancel a PAID module when Minty does the billing.

    Same promise as the Stripe path — access until ``max(paid_through, now + 30 days)``,
    and the days beyond what was paid for are charged — but nothing is collected here.
    The amount is RECORDED on the row and picked up by the next renewal run
    (``renewals._pending_extension_lines``).

    That deferral is the point, not an optimisation. Charging at cancellation would make
    leaving depend on a card clearing, so an expired card could trap somebody in a
    subscription. Recording it cannot fail.

    No Stripe object is touched: there is no line to swap down and no £0 grace price to
    park on, because the subscription those existed to keep alive is not what bills this
    payer any more.
    """
    # Read NOW, not at the audit call below: ``upsert_module_row`` writes through the
    # same identity-mapped object, so by then ``row.phase`` is already the new phase and
    # the log would record scheduled_cancel -> scheduled_cancel.
    phase_before = getattr(row, "phase", None)

    terms = _paid_cancel_terms(entity, user, code, row)
    payer_user_id = terms["payer_user_id"]
    access_end = terms["access_end"]
    amount = terms["amount"]

    fields = {
        "phase": PHASE_SCHEDULED_CANCEL,
        "app_access_until": access_end,
    }
    if amount > 0:
        fields["extension_amount"] = amount
        fields["extension_state"] = EXT_PENDING
    store.upsert_module_row(entity.id, code, payer_user_id, **fields)

    store.record_action(
        entity_id=entity.id,
        function_code=code,
        payer_user_id=payer_user_id,
        actor_user_id=getattr(user, "id", None),
        action=AUDIT_CANCEL,
        outcome=OUTCOME_SUCCEEDED,
        # Captured before the upsert above. Omitting it logged
        # "NULL -> scheduled_cancel" for every PAID cancellation while the trial path
        # logged "trial -> scheduled_cancel" — so the state was missing on exactly the
        # cancellations where money moved, in the table meant to answer "why was I
        # charged?".
        phase_before=phase_before,
        phase_after=PHASE_SCHEDULED_CANCEL,
        app_access_until=access_end,
        extension_amount=amount or None,
        extension_state=EXT_PENDING if amount > 0 else None,
        note="cancelled in-house; extension recorded for the next invoice",
    )
    return {
        "access_end": access_end,
        "extension_state": EXT_PENDING if amount > 0 else None,
    }


def cancel_module(entity, user, function_code: str) -> dict:
    """Cancel ONE module under the prorated access-extension rule.

    Cancelling one of two modules drops the entity to the survivor's price (400 -> 280);
    cancelling the last one ends the entity's billing altogether.

    * Access runs until ``max(paid_through, now + PAID_CANCEL_ACCESS_DAYS)`` — the
      window only ever EXTENDS access, never shortens what was already paid for. It is
      recorded on the row as ``app_access_until``, the single access-end authority.
    * The extra days fall AFTER the billing anchor, so they are owed: the module's
      MARGINAL price (see ``_extension_amount``), prorated, recorded on the row as
      ``extension_amount`` and collected by the next renewal run. Nothing is charged
      up-front, so cancelling never depends on a card clearing and never aborts.

    An app-level trial has nothing to prorate, but it follows the same shape:
    cancelling SCHEDULES the cancellation rather than ending it. See below.

    Returns ``{access_end, extension_state}``.
    """
    code = (function_code or "").strip().upper()
    if not code:
        raise CheckoutError("A module is required to cancel.")
    user_id = getattr(user, "id", None)

    row = store.module_row(entity.id, code)
    # App-level trial: no Stripe object at all, and no charge either way.
    #
    # Cancelling must NOT end the trial. It only means "don't convert me to paid" —
    # the user keeps the free days they were given, exactly as a cancelled PAID module
    # keeps the days it was charged for. So this schedules the cancellation: access runs
    # to trial_end (``app_access_until``), the trial-end job then expires instead of
    # converting it (see ``_convert_due_trials``), and the user can change their mind any
    # time before that date (``renew_module``).
    if row is not None and row.phase == PHASE_TRIAL:
        now = clock.now()
        access_end = row.trial_end
        if access_end is None or access_end <= now:
            # Nothing left to keep — an overdue trial the end-job hasn't swept yet.
            # Expiring it now is the same outcome, just sooner.
            _expire_due_trial(row)
            store.record_action(
                entity_id=entity.id,
                function_code=code,
                payer_user_id=row.payer_user_id,
                actor_user_id=user_id,
                action=AUDIT_CANCEL,
                outcome=OUTCOME_SUCCEEDED,
                phase_before=PHASE_TRIAL,
                phase_after=PHASE_EXPIRED,
                note="app-level trial cancelled after its end date; expired immediately",
            )
            return {"access_end": None, "extension_state": None}

        # Access deliberately left ENABLED — the trial keeps running.
        store.upsert_module_row(
            entity.id,
            code,
            row.payer_user_id,
            phase=PHASE_SCHEDULED_CANCEL,
            app_access_until=access_end,
        )
        store.record_action(
            entity_id=entity.id,
            function_code=code,
            payer_user_id=row.payer_user_id,
            actor_user_id=user_id,
            action=AUDIT_CANCEL,
            outcome=OUTCOME_SUCCEEDED,
            phase_before=PHASE_TRIAL,
            phase_after=PHASE_SCHEDULED_CANCEL,
            app_access_until=access_end,
            note="app-level trial cancelled; access runs to trial end, will not convert",
        )
        return {"access_end": access_end, "extension_state": None}

    # A PAID module. Access continues to app_access_until and the extension is
    # recorded for the next renewal to collect, so cancelling never depends on a
    # card clearing.
    return _cancel_module_in_house(entity, user, code, row)


def preview_cancel_module(entity, user, function_code: str) -> dict:
    """What cancelling would do, WITHOUT doing it — for the confirmation dialog.

    Answers the two questions the dialog exists to answer: when does access end, and is
    there anything left to pay. Reads only; safe to call on render or on hover.

    Deliberately mirrors ``cancel_module`` branch for branch, and shares
    ``_paid_cancel_terms`` with the paid path, so the dialog cannot quote a date or an
    amount that the cancellation then contradicts. Anything that changes the rule has to
    change it for both.

    Returns::

        {kind, access_end, amount, amount_formatted, currency, charged_now,
         remaining, remaining_amount, error}

    ``kind`` is one of ``trial`` (free days kept, nothing owed), ``trial_expired``
    (nothing left to keep — cancelling ends it now), ``paid``, or ``none`` when the
    module isn't cancellable at all. ``charged_now`` is always False: nothing is
    collected at cancellation, by design.
    """
    from blueprints.subscription.services import money

    code = (function_code or "").strip().upper()
    if not code:
        raise CheckoutError("A module is required to cancel.")

    row = store.module_row(entity.id, code)
    if row is None:
        return {"kind": "none", "error": "This module isn't subscribed."}

    base = {
        "code": code,
        "amount": 0,
        "amount_formatted": None,
        "currency": None,
        # Nothing is charged at cancellation on any path — the extension is recorded
        # and collected by the next renewal run. The dialog says so rather than
        # implying a card is about to be hit.
        "charged_now": False,
        "remaining": [],
        "remaining_amount": None,
        "error": None,
    }

    if row.phase == PHASE_TRIAL:
        now = clock.now()
        access_end = row.trial_end
        if access_end is None or access_end <= now:
            return {**base, "kind": "trial_expired", "access_end": None}
        # The free days are kept: cancelling a trial only means "don't convert me".
        return {**base, "kind": "trial", "access_end": access_end}

    terms = _paid_cancel_terms(entity, user, code, row)
    currency = terms["currency"]
    amount = terms["amount"]
    plan_after = terms["plan_after"]

    return {
        **base,
        "kind": "paid",
        "access_end": terms["access_end"],
        "paid_through": terms["paid_through"],
        "amount": amount,
        "amount_formatted": money.format_minor(amount, currency) if amount else None,
        "currency": currency,
        "remaining": terms["remaining"],
        # What the entity drops to once this module goes — the survivor's price, not
        # the bundle's. Shown so "you'll keep paying" is a number, not an implication.
        "remaining_amount": (
            money.format_minor(plan_after.amount, currency) if plan_after else None
        ),
    }


def _reactivate_trial(entity, user, code: str, row) -> None:
    """Un-cancel an app-level trial: put it back in the trial phase so it converts again.

    Only valid while the trial still has time left. Once ``trial_end`` has passed the
    free days are gone and there is nothing to resume — the user has to subscribe, which
    is a purchase and must not be reachable by clicking Renew. (Cancelling and
    un-cancelling never moved money, so unlike the paid path there's no extension to
    reverse and no charge to credit.)
    """
    now = clock.now()
    if row.trial_end is None or row.trial_end <= now:
        raise CheckoutError(
            f"The free trial for {code} has already ended — subscribe to keep it.",
            status=409,
        )

    store.upsert_module_row(
        entity.id,
        code,
        row.payer_user_id,
        phase=PHASE_TRIAL,
        app_access_until=row.trial_end,
    )
    # Access was never revoked by the cancel, but re-assert it: if the trial lapsed and
    # was re-cancelled, or a sweep ran against a stale row, this is what puts it back.
    _set_module_access(entity.id, code, True)
    store.record_action(
        entity_id=entity.id,
        function_code=code,
        payer_user_id=row.payer_user_id,
        actor_user_id=getattr(user, "id", None),
        action=AUDIT_UNCANCEL,
        outcome=OUTCOME_SUCCEEDED,
        phase_before=PHASE_SCHEDULED_CANCEL,
        phase_after=PHASE_TRIAL,
        app_access_until=row.trial_end,
        note="app-level trial un-cancelled; will convert at trial end again",
    )


def _reactivate_module_in_house(entity, user, code: str, row) -> None:
    """Undo a scheduled cancellation when Minty does the billing.

    Much simpler than the Stripe path, because the extension was never charged. It was
    RECORDED on the row for the next renewal run to collect, so undoing it is deleting a
    number nobody has been billed for — no invoice item to remove, no credit note, no
    ``cancel_at`` to clear, and no money moved in either direction.

    Once a run has COLLECTED the extension, undoing is not free. The extension paid for
    access up to ``app_access_until`` and the renewal SKIPPED this module for the rest of
    the period (a cancelling module is not billing-forward), so the window from there to
    the period end is covered by nobody. Reinstating without charging it hands the
    customer the rest of the month.

    That gap is charged NOW rather than queued onto the next invoice. Cancelling defers
    deliberately — leaving must never depend on a card clearing — but reinstating is a
    PURCHASE, and a purchase that waits until month end is one the customer can walk away
    from having already had the module. So it is collected up front, and a decline leaves
    the module cancelled rather than granting it unpaid.

    The extension itself is NOT reversed: those days were used, at the marginal rate they
    would have cost anyway. Crediting them and re-charging the same window would move
    money twice to reach the same place, and put two lines on the invoice that only make
    sense read together.
    """
    if row.extension_state == EXT_INVOICED:
        _bill_reinstatement_in_house(entity, user, code, row)

    fields = {
        "phase": PHASE_ACTIVE,
        "app_access_until": None,
    }
    if row.extension_state != EXT_INVOICED:
        # Still pending: nobody was billed, so this is deleting a number.
        fields["extension_amount"] = None
        fields["extension_state"] = None

    store.upsert_module_row(entity.id, code, row.payer_user_id, **fields)
    _set_module_access(entity.id, code, True)
    store.record_action(
        entity_id=entity.id,
        function_code=code,
        payer_user_id=row.payer_user_id,
        actor_user_id=getattr(user, "id", None),
        action=AUDIT_UNCANCEL,
        outcome=OUTCOME_SUCCEEDED,
        phase_before=PHASE_SCHEDULED_CANCEL,
        phase_after=PHASE_ACTIVE,
        note=(
            "reactivated in-house; the uncovered remainder of the period was charged"
            if row.extension_state == EXT_INVOICED
            else "reactivated in-house; pending extension discarded before it was billed"
        ),
    )


def reactivate_module(entity, user, function_code: str) -> None:
    """Undo a scheduled cancellation for ONE module.

    Puts the module back on the entity's line (swapping 280 -> 400 as it rejoins the
    other module), clears any pending whole-subscription cancellation, and reverses the
    extension charge — deleted if it never billed, credited if it already did (see
    ``_reverse_extension``).

    A cancelled app-level TRIAL is handled separately below: it has no Stripe object, no
    extension and no charge to reverse, so un-cancelling is just putting the row back in
    the trial phase.
    """
    code = (function_code or "").strip().upper()
    row = store.module_row(entity.id, code)
    # A past-due module has nothing to un-cancel: it is live and in arrears, and what it
    # needs is a card the retry can use. The card no longer offers Renew for it, but a
    # page left open before that fix — or a stale tab — still can, so answer with the
    # action that actually helps rather than "isn't scheduled to cancel", which is true
    # and tells the customer nothing.
    if row is not None and row.phase == PHASE_PAST_DUE:
        raise CheckoutError(
            f"Module {code} is past due, not cancelled. Update your payment method to "
            "settle it.",
            status=409,
        )
    if row is None or row.phase != PHASE_SCHEDULED_CANCEL:
        raise CheckoutError(f"Module {code} isn't scheduled to cancel.", status=409)

    # A cancelled app-level trial: nothing in Stripe exists for it (no line, no
    # extension, no cancel_at), so none of the Stripe reversal below applies — running
    # it would fail on the missing billing account for an entity that has never paid.
    #
    # Asked of ``first_billed_at``, NOT of ``stripe_subscription_item_id``: only the
    # Stripe biller sets an item id, so in-house every paid module took this branch and
    # un-cancelling one was refused with "your free trial has already ended". The old
    # ``trial_end is not None`` half is gone because it is true of every row — a paid
    # module that began as a trial keeps its trial_end forever.
    if row.first_billed_at is None:
        _reactivate_trial(entity, user, code, row)
        return

    _reactivate_module_in_house(entity, user, code, row)


def _billing_portal_configuration() -> str:
    """The ONLY configuration a portal session may ever use.

    Cancellation is in-app EXCLUSIVELY. Stripe's own cancel button skips everything the
    policy guarantees — it queues no access extension, stamps no ``app_access_until``,
    writes no audit row — and the resulting webhook revokes access immediately, taking
    the 30 days the customer paid for. The restricted config turns it off.

    A session with no ``configuration`` silently uses the ACCOUNT DEFAULT, where cancel is
    enabled. So this refuses rather than falling back: being briefly unable to show
    invoices is recoverable, a customer cancelling through Stripe is not.
    """
    configuration = get_or_create_billing_management_configuration()
    if not configuration:
        logger.error(
            "billing portal: the restricted configuration could not be resolved; "
            "refusing rather than opening Stripe's default portal (cancel enabled)"
        )
        raise CheckoutError(
            "Billing management is temporarily unavailable. Please try again shortly.",
            status=503,
        )
    return configuration


def open_payment_method_update(entity, return_url: str):
    """Open the Stripe portal's add/update payment-method flow.

    Deep-links straight into the payment-method flow (not the portal home) with an
    ``after_completion`` redirect, so the customer lands back on ``return_url`` as
    soon as the card is saved. Raises ``CheckoutError`` if the entity has no Stripe
    customer yet.
    """
    customer_id = _customer_id_for_entity(entity.id)
    if not customer_id:
        raise CheckoutError("This entity has no billing account yet.", status=409)
    return create_billing_portal_session(
        customer_id,
        return_url,
        # The flow deep-link decides where the session OPENS; the configuration decides
        # what the customer can reach from there. Without it they can navigate to the
        # default portal's home and cancel.
        configuration=_billing_portal_configuration(),
        flow_data={
            "type": "payment_method_update",
            "after_completion": {
                "type": "redirect",
                "redirect": {"return_url": return_url},
            },
        },
    )


def open_billing_management_portal(entity, return_url: str):
    """Open the Stripe portal showing invoice history + payment-method management, but
    WITHOUT Stripe's own cancellation/update — cancelling is in-app only.

    Raises ``CheckoutError`` if the entity has no Stripe customer yet, or if the
    restricted configuration can't be resolved (see ``_billing_portal_configuration``:
    this used to fall back to the default portal, which enables cancel).
    """
    customer_id = _customer_id_for_entity(entity.id)
    if not customer_id:
        raise CheckoutError("This entity has no billing account yet.", status=409)
    return create_billing_portal_session(
        customer_id, return_url, configuration=_billing_portal_configuration()
    )


def start_trials_for_enabled_modules(entity, user) -> list:
    """Start app-level trials for every enabled module the entity hasn't used one on
    (called at the end of onboarding).

    Needs no customer and no card — the wizard lets a user skip the card, and that only
    matters when the trial ends (convert vs expire). Modules that already have a trial
    or a subscription are skipped rather than raising, since this runs over whatever the
    wizard enabled.
    """
    # Lazy import: the entity module service pulls in the full model graph.
    from blueprints.entity.services.modules import get_enabled_modules_for_entities

    enabled = get_enabled_modules_for_entities([entity.id]).get(entity.id, set())
    if not enabled:
        return []

    created = []
    for code in sorted(enabled):
        plan = catalog.plan_for_module(code)
        if plan is None:
            continue
        row = start_module_trial(entity, user, plan)
        if row is not None:
            created.append(row)
    return created
