"""Single configured entry point to the Stripe SDK.

Import ``get_stripe()`` wherever Stripe API calls are needed rather than
importing ``stripe`` directly, so the API key is always applied from config
(falling back to the environment when called outside an app context).

This module also holds the thin read helpers (``list_*`` / ``retrieve_*``) the
Stripe-first layer (``services.stripe_state``) builds on, so all Stripe access
goes through one place.
"""
from __future__ import annotations

import os

import stripe
from flask import current_app, g, has_app_context

# Per-request memo for ``customer_default_payment_method``. Same shape and lifetime as
# ``policy.current`` / ``money.decimal_places`` / ``clock.now`` — cached on the app-context
# global ``g``, so it is per-request and thread-safe (each context has its own ``g``).
#
# It is here because "does this customer have a card" is a NETWORK round trip, and it was
# being made on every module-settings render, on the payer portal, and once per entity per
# login on the dashboard — synchronously, in front of the response. The answer cannot
# change while a request is in flight except by our own write, and that write invalidates
# it (see ``set_customer_default_payment_method``).
_G_DEFAULT_PM_KEY = "_stripe_default_payment_methods"


def _default_pm_cache() -> dict | None:
    """The request's memo, or None outside an app context (CLI, worker, import time)."""
    if not has_app_context():
        return None
    cache = getattr(g, _G_DEFAULT_PM_KEY, None)
    if cache is None:
        cache = {}
        setattr(g, _G_DEFAULT_PM_KEY, cache)
    return cache


def forget_default_payment_method(customer_id: str | None) -> None:
    """Drop the memoized answer for one customer, after their card on file changed.

    Without this the memo is a correctness bug, not just a stale read: paid checkout
    captures a card and then asks whether one is on file to decide if it may subscribe
    directly (``checkout._has_payment_method``). Answering from a memo taken BEFORE the
    capture would send the payer back to capture a card they just saved.
    """
    cache = _default_pm_cache()
    if cache is not None and customer_id:
        cache.pop(str(customer_id), None)


def _config_value(key: str) -> str | None:
    """Read a Stripe setting from app config, falling back to the environment."""
    try:
        value = current_app.config.get(key)
        if value:
            return value
    except RuntimeError:
        # No application context (script/worker) — fall back to the environment.
        pass
    return os.environ.get(key)


def get_stripe():
    """Return the ``stripe`` module with ``api_key`` set, or raise if unconfigured."""
    api_key = _config_value("STRIPE_SECRET_KEY")
    if not api_key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not configured; cannot make Stripe API calls."
        )
    stripe.api_key = api_key
    return stripe


# --- Read helpers (catalog + subscription state) -----------------------------


def list_products():
    """All Stripe Products (paged)."""
    return list(get_stripe().Product.list(limit=100).auto_paging_iter())


def list_active_recurring_prices(product_id: str) -> list:
    """Active recurring Prices for a product (paged)."""
    prices = get_stripe().Price.list(
        product=product_id, active=True, limit=100
    ).auto_paging_iter()
    return [p for p in prices if p.get("recurring")]


def list_customer_subscriptions(customer_id: str) -> list:
    """Every subscription for a customer in any status, items + discounts expanded.

    ``status="all"`` so cancelled/past_due subscriptions are visible to the grace
    logic. Items are expanded so each line item's price (→ module) and the
    per-item current_period_* (newer API versions) are available.
    """
    if not customer_id:
        return []
    result = get_stripe().Subscription.list(
        customer=customer_id,
        status="all",
        limit=100,
        expand=["data.items.data.price", "data.discounts"],
    )
    # Capture Stripe's server time (response Date header) so subscription access /
    # grace decisions use a trusted clock rather than the host wall clock.
    _record_server_time(result)
    return list(result.auto_paging_iter())


def _record_server_time(stripe_result) -> None:
    """Best-effort: stash the ``Date`` header from a Stripe response as the trusted
    'now'. Silently ignored if headers aren't available."""
    try:
        last_response = getattr(stripe_result, "last_response", None)
        headers = getattr(last_response, "headers", None) or {}
        date_header = headers.get("Date") or headers.get("date")
        if date_header:
            from blueprints.subscription.services import clock

            clock.record_http_date(date_header)
    except Exception:  # never let clock capture break a real Stripe read
        pass


def retrieve_subscription(subscription_id: str):
    """Fetch one Stripe Subscription (with its discounts expanded)."""
    return get_stripe().Subscription.retrieve(subscription_id, expand=["discounts"])


# --- Write helpers (checkout / trials / billing) -----------------------------

# What the payer's ONE subscription is called, in the Stripe dashboard and on customer-
# facing Stripe surfaces. Not a product name: a payer has a single subscription spanning
# every entity and module combination they pay for, so naming it after any one product
# would be wrong the moment they own two. The line items carry the product names.
SUBSCRIPTION_DESCRIPTION = "Minty"


# NOTE: no customer is created on any path that MIGHT save a card, deliberately. A
# customer must not exist until a card has actually been saved, so
# ``create_setup_checkout_session`` hands Stripe ``customer_creation="always"`` and lets
# it create one at session confirmation. ``checkout._adopt_session_customer`` then stamps
# and maps it. Creating one up front reintroduces an orphan customer for every abandoned
# checkout.
#
# ``create_customer_for_user`` below is the one direct create, and it does not weaken
# that: it is called from the in-app card form's CONFIRM step, i.e. after Stripe has
# already told us a payment method exists. Card first, customer second — the invariant is
# about ordering, not about which API call makes the customer.


def find_customer_by_user(user_id: str):
    """Find a payer's Stripe Customer via ``metadata.user_id`` and return the Customer
    dict (or None). The customer is owned by the paying USER, not the entity.

    NOTE: Stripe's Customer Search is eventually consistent (results can lag a write by
    up to ~a minute), so code running right after creating a customer must dedupe via the
    create idempotency key rather than relying on search.
    """
    if not user_id:
        return None
    stripe_client = get_stripe()
    result = stripe_client.Customer.search(
        query=f"metadata['user_id']:'{user_id}'",
        limit=1,
    )
    data = result.get("data") or []
    return data[0] if data else None


def retrieve_customer(customer_id: str):
    """Retrieve a Stripe Customer by id (None if missing/blank)."""
    if not customer_id:
        return None
    stripe_client = get_stripe()
    return stripe_client.Customer.retrieve(customer_id)


def add_subscription_item(
    subscription_id: str,
    *,
    price_data: dict,
    metadata: dict[str, str] | None = None,
    proration_behavior: str = "create_prorations",
    payment_behavior: str | None = None,
    idempotency_key: str | None = None,
):
    """Add a line item to an existing subscription, at an INLINE per-entity price.

    ``price_data``, never a shared ``price`` id: Stripe rejects two items on one
    subscription that use the same Price, and one payer's subscription carries a line per
    entity — so two entities on the same module would collide. See
    ``checkout._price_data_for_codes`` for why this is safe (the product is shared, so the
    module mapping still works, and inline prices are invisible to the catalog).

    ``proration_behavior`` decides WHEN the partial period is billed, and the two modes
    are not interchangeable:

    * ``create_prorations`` (default) holds the charge as a pending proration that rides
      the next scheduled invoice. Correct for anything the customer didn't just ask for —
      notably a cancel/downgrade, whose access extension is meant to bill ON the anchor.
    * ``always_invoice`` cuts an invoice immediately, so the customer pays now for the
      partial period up to the anchor. Correct on a BUY, where they're expecting a charge.

    Pass ``payment_behavior="error_if_incomplete"`` with ``always_invoice``: otherwise a
    declined card still leaves the item added and an invoice open, i.e. the customer keeps
    what they didn't pay for until dunning catches up.
    """
    payload: dict[str, object] = {
        "subscription": subscription_id,
        "price_data": price_data,
        "proration_behavior": proration_behavior,
        "metadata": metadata or {},
    }
    if payment_behavior:
        payload["payment_behavior"] = payment_behavior
    request_options: dict[str, object] = {}
    if idempotency_key:
        request_options["idempotency_key"] = idempotency_key
    return get_stripe().SubscriptionItem.create(**payload, **request_options)


def update_subscription_item_price(
    item_id: str,
    price_id: str | None = None,
    *,
    price_data: dict | None = None,
    metadata: dict[str, str] | None = None,
    proration_behavior: str = "create_prorations",
    payment_behavior: str | None = None,
):
    """Swap a line item's price in place (single 280 <-> bundle 400).

    This is how a module is added to / removed from an entity: the entity has exactly
    ONE line, so its price changes rather than lines being added.

    Pass exactly one of:

    * ``price_data`` — for a module line. An inline per-entity price, because two entities
      on one subscription can't share a Price (see ``add_subscription_item``).
    * ``price_id`` — only for the shared £0 GRACE price. Safe from that collision because
      grace applies solely to the payer's LAST remaining line, so there is never a second
      item to conflict with.

    See ``add_subscription_item`` for when to pass ``always_invoice`` +
    ``error_if_incomplete``. The default stays ``create_prorations`` because this same
    helper carries the cancel path — swapping a line DOWN, or parking it on the £0 grace
    price, must not cut an invoice crediting back access the customer still has.
    """
    if bool(price_id) == bool(price_data):
        raise ValueError("pass exactly one of price_id or price_data")
    payload: dict[str, object] = {"proration_behavior": proration_behavior}
    payload["price_data" if price_data else "price"] = price_data or price_id
    if metadata is not None:
        payload["metadata"] = metadata
    if payment_behavior:
        payload["payment_behavior"] = payment_behavior
    return get_stripe().SubscriptionItem.modify(item_id, **payload)


def remove_subscription_item(item_id: str, *, proration_behavior: str = "create_prorations"):
    """Delete a line item; the subscription keeps running for its other items."""
    return get_stripe().SubscriptionItem.delete(
        item_id, proration_behavior=proration_behavior
    )


def create_paid_subscription(
    customer_id: str,
    *,
    price_data: dict,
    default_payment_method: str | None = None,
    metadata: dict[str, str] | None = None,
    idempotency_key: str | None = None,
):
    """Create the payer's PAID subscription with its first line item — billed
    immediately (no trial).

    There is ONE subscription per payer; further entities' lines are added to it with
    ``add_subscription_item``. ``metadata`` is written to the subscription AND to this
    first item, because the entity a line bills for lives on the ITEM (one subscription
    can span several entities, so the subscription itself can't name one).

    The first line takes an INLINE ``price_data`` like every other, so a later entity
    buying the same module doesn't collide with it (see ``add_subscription_item``).

    ``default_payment_method`` bills a specific saved card; when omitted Stripe uses the
    customer's invoice default. ``off_session=True`` charges that saved card without the
    customer present (the checkout POST / setup-return is server-side, not an
    interactive payment page). ``payment_behavior='error_if_incomplete'`` makes a card
    that can't be charged fail loudly (the caller reports it) rather than leaving an
    ``incomplete`` subscription lingering.

    ``description`` names the SUBSCRIPTION, not its lines. Without it Stripe titles the
    subscription after whichever product it happens to hold, so a payer's one
    subscription would be labelled "Super Minty" even though it
    spans several entities and module combinations. The line items keep their own
    product names — the product is what was bought, the description is what the
    relationship is.
    """
    stripe_client = get_stripe()
    payload: dict[str, object] = {
        "customer": customer_id,
        "items": [{"price_data": price_data, "metadata": metadata or {}}],
        "metadata": metadata or {},
        "description": SUBSCRIPTION_DESCRIPTION,
        "payment_behavior": "error_if_incomplete",
        "off_session": True,
    }
    if default_payment_method:
        payload["default_payment_method"] = default_payment_method
    request_options: dict[str, object] = {}
    if idempotency_key:
        request_options["idempotency_key"] = idempotency_key
    return stripe_client.Subscription.create(**payload, **request_options)


def create_setup_checkout_session(
    customer_id: str | None,
    success_url: str,
    cancel_url: str,
    currency: str,
    metadata: dict[str, str] | None = None,
):
    """Create a Checkout Session in ``setup`` mode to save a card (no charge).

    Used to capture a payment method before creating per-module paid subscriptions
    server-side. Setup mode requires a ``currency`` (the modules' billing currency).
    ``metadata`` (carrying the entity, payer and any module codes) rides on the session
    so the completion handler knows what to create; the saved card is set as the
    customer's default on completion.

    ``customer_id`` is None for a payer who has no Stripe customer yet. The session is
    then opened WITHOUT a customer and with ``customer_creation="always"``, so Stripe
    creates the Customer during session CONFIRMATION — i.e. only once the card is
    actually saved. Abandoning the session leaves no Customer behind. That is a
    deliberate invariant: NO CUSTOMER IS EVER CREATED WITHOUT A CARD. Do not "fix" this
    by resolving a customer up front — that reintroduces orphan customers for every
    abandoned checkout.

    It must be ``always``, not ``if_required``: with ``if_required`` the session can end
    up saving neither the customer nor the payment method, which defeats setup mode.

    The customer Stripe creates carries none of our bookkeeping (no ``metadata.user_id``,
    and it bypasses the ``user-customer-{user_id}`` idempotency key). The completion
    handler adopts it — see ``checkout._adopt_session_customer``.
    """
    payload: dict[str, object] = {
        "mode": "setup",
        "currency": (currency or "").lower(),
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata or {},
    }
    if customer_id:
        payload["customer"] = customer_id
    else:
        payload["customer_creation"] = "always"
    return get_stripe().checkout.Session.create(**payload)


def retrieve_checkout_session(session_id: str):
    """Retrieve a Checkout Session with its ``setup_intent`` expanded (so the saved
    payment method is readable)."""
    return get_stripe().checkout.Session.retrieve(
        session_id, expand=["setup_intent"]
    )


def set_customer_default_payment_method(customer_id: str, payment_method_id: str):
    """Make ``payment_method_id`` the customer's default for invoices."""
    result = get_stripe().Customer.modify(
        customer_id,
        invoice_settings={"default_payment_method": payment_method_id},
    )
    # The memo below now holds a stale "no card" for this customer, and the very next
    # thing checkout does is ask whether one is on file.
    forget_default_payment_method(customer_id)
    return result


def set_customer_identity(
    customer_id: str,
    *,
    metadata: dict[str, str] | None = None,
    name: str | None = None,
    email: str | None = None,
    description: str | None = None,
):
    """Write who a customer IS: the ``user_id`` stamp plus the payer's display fields.

    One ``Customer.modify`` rather than several, so the identity of a customer Stripe
    just created during a setup Checkout lands atomically. ``metadata`` is the important
    half — it's what ``find_customer_by_user`` recovers from, and without it the customer
    is invisible to every lookup we have. (Stripe MERGES metadata keys; it doesn't
    replace the object.)

    Only non-None fields are sent, so a caller can leave Stripe's Checkout-collected
    value in place for anything it can't improve on (e.g. a payer whose local ``email``
    is null).
    """
    payload: dict[str, object] = {}
    if metadata:
        payload["metadata"] = metadata
    if name:
        payload["name"] = name
    if email:
        payload["email"] = email
    if description:
        payload["description"] = description
    if not payload:
        return None
    return get_stripe().Customer.modify(customer_id, **payload)


def attach_payment_method(payment_method_id: str, customer_id: str):
    """Attach a PaymentMethod to a customer.

    Only needed on the duplicate-customer reconciliation path: a card captured against
    a Stripe-created customer has to be moved onto the payer's pre-existing customer
    before it can be made the default there (see ``checkout._adopt_session_customer``).
    """
    return get_stripe().PaymentMethod.attach(payment_method_id, customer=customer_id)


def customer_default_payment_method(customer_id: str | None) -> str | None:
    """The customer's default invoice payment method id, or None.

    Used to decide whether paid checkout can create subscriptions directly (a card
    is on file) or must first capture one via a setup-mode Checkout.

    MEMOIZED FOR THE REQUEST. The Stripe round trip behind this was on the render path of
    every module-settings page — and ``get_module_cards`` is not the only caller in a
    request. ``None`` is cached like any other answer: "this payer has no card" is the
    common case on a trial and the one worth not asking twice.
    """
    if not customer_id:
        return None

    cache = _default_pm_cache()
    key = str(customer_id)
    if cache is not None and key in cache:
        return cache[key]

    customer = retrieve_customer(customer_id)
    pm = None
    if customer:
        pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
        if isinstance(pm, dict):
            pm = pm.get("id")
    if cache is not None:
        cache[key] = pm
    return pm


def payment_method_display(payment_method_id: str | None) -> dict | None:
    """The card's brand + last4 for showing the payer what they're about to be charged
    on, or None if it can't be read.

    Display only — never a billing decision. Returns e.g. ``{"type": "card", "brand":
    "visa", "last4": "4242", "exp_month": 8, "exp_year": 2028, "expiry": "08/28",
    "label": "Visa •••• 4242"}``.

    The expiry is included because a card about to expire is the commonest reason a
    renewal fails, and the billing page is where someone would go to fix it. ``expiry`` is
    the pre-formatted MM/YY the UI prints; the raw parts are kept so a caller can compare
    against a date without parsing it back.

    NOT every payment method is a card. A payer who checked out through Stripe Link has a
    ``link`` method with no ``card`` object at all, and this used to answer None for
    them — so the one screen that says what will be charged said nothing. Those now come
    back with the type and a ``label`` and empty card fields, because "Link" is a true
    answer and blank is not.

    ``brand`` and ``last4`` keep their exact previous meaning — a card's, or None — so
    callers reading them are unaffected. ``label`` is the complete string to print.
    """
    if not payment_method_id:
        return None
    try:
        pm = get_stripe().PaymentMethod.retrieve(payment_method_id)
    except Exception:
        from loguru import logger

        logger.exception(
            "subscription: could not read payment method {}", payment_method_id
        )
        return None
    card = (pm or {}).get("card") or {}
    kind = (pm or {}).get("type") or ""
    # Whoever the card is registered to. Stripe's own field, so the billing screen can
    # show a cardholder rather than guessing it is the payer — they are often different
    # people (a finance lead's card on a director's account).
    cardholder = ((pm or {}).get("billing_details") or {}).get("name")

    if card:
        month, year = card.get("exp_month"), card.get("exp_year")
        brand, last4 = card.get("brand"), card.get("last4")
        return {
            "type": "card",
            "brand": brand,
            "last4": last4,
            "cardholder": cardholder,
            "exp_month": month,
            "exp_year": year,
            "expiry": (
                f"{int(month):02d}/{int(year) % 100:02d}" if month and year else None
            ),
            "label": " ".join(
                p for p in [(brand or "card").title(), f"•••• {last4}" if last4 else ""]
                if p
            ),
        }

    if kind:
        # A wallet — Link today. Stripe exposes no card object for it (the funding source
        # is Link's business), so the honest answer is what it IS.
        return {
            "type": kind,
            "brand": None,
            "last4": None,
            "cardholder": cardholder,
            "exp_month": None,
            "exp_year": None,
            "expiry": None,
            "label": kind.replace("_", " ").title(),
        }

    return None


# --- Saved payment methods (the in-app wallet) -------------------------------
#
# Everything above reads or writes the ONE default card, which is all the billing engine
# ever needed: ``issue_invoice`` charges the customer and Stripe bills whatever
# ``invoice_settings.default_payment_method`` names. The billing account PAGE needs the
# rest of the shelf — every method saved against the customer, so one can be added,
# corrected, promoted or removed without leaving the app.
#
# Stripe remains the only place a card number exists. These helpers move ids and display
# fields; the PAN is entered into Stripe Elements in the browser and never reaches this
# process, which is what keeps the application out of PCI scope.


def create_customer_for_user(
    user_id,
    *,
    name: str | None = None,
    email: str | None = None,
    description: str | None = None,
):
    """Create the payer's Stripe Customer, stamped so every lookup can find it.

    THE ONLY DIRECT CUSTOMER CREATE IN THE APPLICATION, and it has exactly one caller:
    the in-app card form's confirm step, once Stripe has confirmed a SetupIntent and a
    payment method genuinely exists (see ``payment_methods.confirm_setup``). Do not call
    it earlier in a flow — "no customer without a card" is what stops an abandoned form
    leaving an orphan behind, and this is the first moment the card is a fact.

    ``metadata.user_id`` is not optional. It is what ``find_customer_by_user`` recovers
    from when the local mapping row is missing, and a customer without it is invisible to
    every lookup we have.

    The idempotency key is the payer, permanently: two tabs confirming two SetupIntents
    seconds apart must not produce two customers for one payer, and Customer Search is
    eventually consistent so it cannot be used to dedupe a write that just happened.
    Stripe replays the original response for 24h; beyond that the mapping row (written by
    the caller) is what prevents a second create.
    """
    payload: dict[str, object] = {"metadata": {"user_id": str(user_id)}}
    if name:
        payload["name"] = name
    if email:
        payload["email"] = email
    if description:
        payload["description"] = description
    return get_stripe().Customer.create(
        **payload, idempotency_key=f"user-customer-{user_id}"
    )


def list_payment_methods(customer_id: str | None) -> list:
    """Every payment method attached to a customer, newest first.

    No ``type`` filter — the customer's whole shelf. Filtering to ``card`` would silently
    hide a Stripe Link wallet that a payer checked out with, i.e. the very method their
    renewals are charged against (see ``payment_method_display``, which learned the same
    lesson).

    Returns ``[]`` for a payer with no customer rather than raising: "no billing account
    yet" is a real state the page has to render (an app-level trial never captured a
    card), not an error.
    """
    if not customer_id:
        return []
    return list(
        get_stripe().PaymentMethod.list(
            customer=customer_id, limit=100
        ).auto_paging_iter()
    )


def retrieve_payment_method(payment_method_id: str):
    """Fetch one PaymentMethod (None if blank).

    The OWNERSHIP CHECK behind every mutation on this shelf: the id arrives from the
    browser, so ``pm.customer`` is compared against the caller's own customer before
    anything is promoted, edited or detached. Without it, a payer who guessed another
    payer's ``pm_…`` id could detach their card.
    """
    if not payment_method_id:
        return None
    return get_stripe().PaymentMethod.retrieve(payment_method_id)


def create_setup_intent(customer_id: str | None, *, user_id, metadata: dict | None = None):
    """A SetupIntent for the in-app card form to confirm against.

    ``usage="off_session"`` because of what the saved card is FOR: renewals and dunning
    retries charge it with nobody at the keyboard (``billing_gateway.issue_invoice``). Set
    up on-session, the card can be saved in a state the issuer later refuses for
    unattended charges — a failure that surfaces a month later on a renewal rather than
    now, in front of the person who could fix it.

    ``customer`` is optional and often absent: a payer adding their FIRST card has no
    customer, and creating one to open a form they may abandon is the orphan this app
    refuses to make. Stripe attaches the method to the customer on success when one is
    given; ``payment_methods.confirm_setup`` creates the customer and attaches the method
    by hand when one is not.

    ``metadata.user_id`` is what makes the confirm step safe. The SetupIntent id comes
    back from the browser, and for a customerless intent there is nothing else to check it
    against — an intent that does not carry the caller's own stamp is refused rather than
    attached.

    Card only. The Payment Element can offer redirect-based methods (iDEAL, Bancontact),
    and every one of them is a bank mandate this billing engine has no path for: it
    charges a saved method off-session on the anchor, which those cannot do.
    """
    payload: dict[str, object] = {
        "usage": "off_session",
        "payment_method_types": ["card"],
        "metadata": {"user_id": str(user_id), **(metadata or {})},
    }
    if customer_id:
        payload["customer"] = customer_id
    return get_stripe().SetupIntent.create(**payload)


def retrieve_setup_intent(setup_intent_id: str):
    """Fetch one SetupIntent (None if blank). Read to learn what the browser saved."""
    if not setup_intent_id:
        return None
    return get_stripe().SetupIntent.retrieve(setup_intent_id)


def update_payment_method(
    payment_method_id: str,
    *,
    exp_month: int | None = None,
    exp_year: int | None = None,
    billing_details: dict | None = None,
):
    """Edit what CAN be edited on a saved method: the expiry, and the billing details.

    Stripe does not let a card's number, CVC or brand be changed — those are the card, and
    a different card is a new PaymentMethod. So "Edit" here means the two things that
    legitimately change on the same plastic: a reissued expiry date, and the name/address
    the issuer checks against (a cardholder who moved is a real cause of declines).

    ``exp_month``/``exp_year`` are rejected outright by Stripe on a non-card method, so
    the caller filters them out for a wallet rather than sending them and reading back a
    Stripe error the customer cannot act on.
    """
    payload: dict[str, object] = {}
    if exp_month is not None or exp_year is not None:
        card: dict[str, object] = {}
        if exp_month is not None:
            card["exp_month"] = int(exp_month)
        if exp_year is not None:
            card["exp_year"] = int(exp_year)
        payload["card"] = card
    if billing_details:
        payload["billing_details"] = billing_details
    if not payload:
        return None
    return get_stripe().PaymentMethod.modify(payment_method_id, **payload)


def detach_payment_method(payment_method_id: str):
    """Remove a saved method from its customer.

    Detaching the customer's DEFAULT also clears ``invoice_settings.default_payment_method``
    at Stripe's end, which is why the caller refuses to detach a default while another
    method exists — the promotion has to happen first, or the account is briefly left with
    a shelf full of cards and nothing nominated to charge.
    """
    return get_stripe().PaymentMethod.detach(payment_method_id)


def create_billing_portal_session(
    customer_id: str,
    return_url: str,
    configuration: str,
    flow_data: dict | None = None,
):
    """Create a Stripe Customer Portal session.

    ``configuration`` is REQUIRED, and deliberately not optional: a session without one
    silently uses the account default, where Stripe's own cancel button is enabled — and
    cancelling there bypasses everything the in-app flow guarantees (no extension queued,
    no ``app_access_until``, no audit row), then the webhook revokes access on the spot,
    stripping the 30 days the customer paid for. Cancelling is IN-APP ONLY.

    Callers should resolve it via ``checkout._billing_portal_configuration``, which fails
    closed rather than falling back to the default. A route that opened the default portal
    existed and was deleted for exactly this reason.

    Pass ``flow_data`` to deep-link into a specific flow with an ``after_completion``
    redirect — but note the flow only decides where the session OPENS; ``configuration``
    is what bounds where the customer can go from there.
    """
    if not configuration:
        raise ValueError(
            "create_billing_portal_session requires a configuration — without one "
            "Stripe opens the default portal, which lets the customer cancel."
        )
    payload: dict[str, object] = {
        "customer": customer_id,
        "return_url": return_url,
        "configuration": configuration,
    }
    if flow_data:
        payload["flow_data"] = flow_data
    return get_stripe().billing_portal.Session.create(**payload)


# Tag for the portal configuration used to VIEW billing (invoices + payment method)
# without exposing Stripe's own cancellation flow (cancellation must go through the
# in-app prorated flow). Reused across sessions so we don't recreate it each time.
BILLING_MANAGEMENT_CONFIG_ROLE = "minty_billing_management"
_billing_management_config_id: str | None = None


def get_or_create_billing_management_configuration() -> str | None:
    """Return the id of the portal configuration that shows invoice history and lets
    the customer update their payment method, but does NOT allow cancelling or
    changing subscriptions. Finds the tagged config (by metadata) or creates it.
    Returns None if it can't be created (caller then falls back to the default
    portal). Memoized per process.
    """
    global _billing_management_config_id
    if _billing_management_config_id:
        return _billing_management_config_id

    s = get_stripe()
    try:
        for cfg in s.billing_portal.Configuration.list(limit=100).auto_paging_iter():
            meta = cfg.get("metadata") or {}
            if meta.get("minty_role") == BILLING_MANAGEMENT_CONFIG_ROLE and cfg.get("active", True):
                _billing_management_config_id = cfg["id"]
                return _billing_management_config_id

        cfg = s.billing_portal.Configuration.create(
            features={
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "customer_update": {"enabled": False},
                "subscription_cancel": {"enabled": False},
                "subscription_update": {"enabled": False},
            },
            metadata={"minty_role": BILLING_MANAGEMENT_CONFIG_ROLE},
        )
        _billing_management_config_id = cfg["id"]
        return _billing_management_config_id
    except Exception:
        from loguru import logger

        logger.exception(
            "stripe: could not get/create billing-management portal configuration; "
            "falling back to the default portal"
        )
        return None


def add_pending_invoice_item(
    customer_id: str,
    subscription_id: str | None,
    amount: int,
    currency: str,
    description: str,
    *,
    metadata: dict[str, str] | None = None,
    idempotency_key: str | None = None,
):
    """Create a PENDING invoice item — no invoice is created here.

    Because it isn't attached to an invoice, Stripe sweeps it onto the subscription's
    NEXT scheduled invoice (the billing anchor). That's how a cancel-extension — which
    covers the days AFTER the anchor — gets billed on the anchor invoice rather than
    cutting a second one.

    A NEGATIVE ``amount`` is a credit line: it nets against the next invoice's charges
    (and any excess rolls into the customer balance, since invoices can't go negative).
    """
    payload: dict[str, object] = {
        "customer": customer_id,
        "amount": int(amount),
        "currency": currency.lower(),
        "description": description,
        "metadata": metadata or {},
    }
    if subscription_id:
        payload["subscription"] = subscription_id
    request_options: dict[str, object] = {}
    if idempotency_key:
        request_options["idempotency_key"] = idempotency_key
    return get_stripe().InvoiceItem.create(**payload, **request_options)


def set_subscription_cancel_at(subscription_id: str, cancel_at):
    """Schedule a subscription to fully cancel at an exact time (``cancel_at``), or clear
    it by passing None.

    Used when cancelling the payer's LAST line: the line is parked on the £0 grace price
    so the subscription can stay alive to this date — the true end of the paid access
    extension — and Stripe holds it rather than the app tracking it alone.
    """
    return get_stripe().Subscription.modify(
        subscription_id,
        cancel_at=int(cancel_at.timestamp()) if cancel_at else None,
    )


def retrieve_invoice_item(item_id: str):
    """Fetch one invoice item (None if missing/blank).

    ``item["invoice"]`` is null while the item is still pending and set once the anchor
    invoice has swept it — that's how the undo decides delete-vs-credit.
    """
    if not item_id:
        return None
    return get_stripe().InvoiceItem.retrieve(item_id)


def delete_invoice_item(item_id: str):
    """Delete a PENDING invoice item — only possible while it hasn't been swept onto an
    invoice. The cheap undo for an extension that never billed (no money moved)."""
    return get_stripe().InvoiceItem.delete(item_id)


def retrieve_invoice(invoice_id: str):
    """Fetch one Invoice (None if missing/blank).

    Used to read back what a cancel-extension actually collected, so undoing it credits
    exactly that amount.
    """
    if not invoice_id:
        return None
    return get_stripe().Invoice.retrieve(invoice_id)


# NOTE: there are deliberately no invoice-annotation helpers here.
#
# A payer has ONE subscription spanning every entity they own, so an invoice mixes
# entities: two entities on the bundle produce two identical "Super Minty 400.00" lines. The
# obvious fixes were both tried against live Stripe and both are dead ends.
#
# 1. Rewriting the LINE description. Refused on any subscription-typed line, by every
#    endpoint — the bulk one, the singular one, and the invoiceitems one:
#
#      POST /v1/invoices/{inv}/lines/{line}  ->  400 You may only update `tax_rates`,
#                                                `tax_amounts`, or `discounts` for a
#                                                subscription typed line item.
#      POST /v1/invoiceitems/{line}          ->  400 When passing an invoice's line item
#                                                id, you may only update `tax_rates` or
#                                                `discounts`.
#
#    A line's text is composed by Stripe from the PRODUCT name ("1 x {product}",
#    "Remaining time on {product} after {date}") and frozen at creation.
#
# 2. Writing the entity breakdown into the invoice MEMO (``Invoice.description``). This
#    works, but only on a DRAFT, and the draft window is not what it looks like:
#
#      renewal invoice                     created 13:00:00, finalized 14:00:00  (~1h)
#      proration from ``always_invoice``   created 13:00:00, finalized 13:00:00  (0s)
#
#    Every charge this app initiates — trial conversion, buy, plan change — uses
#    ``always_invoice`` and so finalizes in the same second, leaving no window at all.
#    Memos were therefore reachable only on multi-entity RENEWAL invoices, and a missed
#    webhook lost even those permanently ("Finalized invoices can't be updated in this
#    way"). Removed as more moving parts than coverage.
#
# The only route left is giving each entity its own Stripe Product, so the entity name
# is part of the line text Stripe generates.


def get_webhook_secret() -> str:
    """Return the signing secret used to verify incoming Stripe webhooks."""
    secret = _config_value("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured.")
    return secret


def get_publishable_key() -> str | None:
    """Return the publishable key for use by the frontend (safe to expose)."""
    return _config_value("STRIPE_PUBLISHABLE_KEY")


