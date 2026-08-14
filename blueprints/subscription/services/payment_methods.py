"""The payer's saved payment methods — the read model and the four writes behind them.

ONE ACCOUNT, ONE SHELF. ``user_stripe_customer`` is a single row per payer carrying one
currency, one anchor, one ``paid_through`` and one dunning clock, and every method here
hangs off that one Stripe customer. ``renewals`` builds a single invoice per payer with a
line per entity, and ``billing_gateway.issue_invoice(customer_id, ...)`` charges the
CUSTOMER — so there is exactly one card in play, however many companies are on the bill.
The methods listed are therefore the payer's, not any entity's, and promoting one changes
what renews EVERY company on the account.

A card saved PER ENTITY has no home and nothing that would charge it. It would also not
stop at storage: different cards mean different payment outcomes per entity, which means a
per-entity ``paid_through`` — the per-row copy that was deliberately removed because it
drifted between one payer's entities (see ``access.access_end``).

WHAT IS ACTUALLY STORED WHERE. Stripe holds the card; this application holds an id. The
number is typed into Stripe Elements in the browser and confirmed straight against a
SetupIntent — it never touches this process, this database or these logs, which is what
keeps the application out of PCI scope. Moving the management UI in-app does not move the
card in-app, and nothing here should ever be extended to accept a PAN.

WHY THE SHELF EXISTS AT ALL. The billing engine only ever consulted
``invoice_settings.default_payment_method``: one card, set at capture, replaced by
sending the payer to Stripe's hosted form. That is still the card that gets charged — the
default is the ONLY method with any billing meaning. The others are there so a payer can
add next year's card before this year's expires, and switch on their own date rather than
on a failed renewal.

THE TWO REFUSALS. Both exist because the account is live and unattended money depends on
it:

* the DEFAULT cannot be detached while another method exists — promote first, or the
  account is left holding cards with none nominated, and Stripe clears the default on
  detach;
* the LAST method cannot be detached at all while something is billing forward — the next
  renewal would decline into dunning by design rather than by accident.

Nothing here starts, stops or prices a subscription. Cancelling stays in the in-app
prorated flow; this module changes what gets charged, never what is owed.
"""

from __future__ import annotations

from loguru import logger

from blueprints.subscription.services import clock
from blueprints.subscription.services import store as sub_store
from blueprints.subscription.services.stripe_client import (
    attach_payment_method, create_customer_for_user, create_setup_intent,
    customer_default_payment_method, detach_payment_method,
    forget_default_payment_method, get_publishable_key, list_payment_methods,
    retrieve_payment_method, retrieve_setup_intent,
    set_customer_default_payment_method, update_payment_method)

# How near an expiry has to be before the page flags it. Two months, because the warning
# is only worth printing while it can still be acted on: a card expiring at the end of
# next month has at most one renewal left on it, and the payer needs the replacement
# saved before that renewal, not after it declines.
EXPIRING_SOON_MONTHS = 2


class PaymentMethodError(Exception):
    """Raised with a message the page can show verbatim, and the status to answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --- Reading -----------------------------------------------------------------


def _fmt(moment) -> str | None:
    """'15 Aug 2026' — the same zero-padded form the rest of the portal prints."""
    return moment.strftime("%d %b %Y") if moment else None


def _months_until(exp_year, exp_month, now) -> int | None:
    """Whole months from ``now`` to the END of the card's expiry month.

    A card is good through the last day of its expiry month, so 04/29 during April 2029 is
    still live and answers 0 — not expired, not yet next month's problem. Negative means
    the month has passed.
    """
    if not exp_year or not exp_month:
        return None
    return (int(exp_year) - now.year) * 12 + (int(exp_month) - now.month)


def _brand_label(brand: str | None) -> str:
    """'visa' -> 'Visa', 'amex' -> 'Amex', 'mastercard' -> 'Mastercard'."""
    return (brand or "card").replace("_", " ").title()


# How a tokenised card was presented. ``card.wallet.type`` is set when the number Stripe
# holds came through a wallet rather than off the plastic — the underlying card is still
# the one that gets charged, but the payer thinks of it as "my Apple Pay", and a row that
# does not say so is a card they will not recognise.
#
# Title-casing the raw value gets most of these right and mangles the ones that matter
# ("Apple Pay" survives, "Amex Express Checkout" does not), so the names Stripe documents
# are spelled out and anything new falls back to the generic rule.
_WALLET_LABELS = {
    "apple_pay": "Apple Pay",
    "google_pay": "Google Pay",
    "samsung_pay": "Samsung Pay",
    "link": "Link",
    "visa_checkout": "Visa Checkout",
    "amex_express_checkout": "Amex Express Checkout",
    "masterpass": "Masterpass",
}


def _wallet_label(wallet_type: str | None) -> str | None:
    if not wallet_type:
        return None
    return _WALLET_LABELS.get(wallet_type, wallet_type.replace("_", " ").title())


def _view(pm, default_id: str | None, now, country_names: dict | None = None) -> dict:
    """One saved method, in the shape the page renders.

    Built from the PaymentMethod object already in hand rather than by calling
    ``payment_method_display`` per row — that helper retrieves by id, which would be one
    network round trip per card on a page whose whole content is the list.

    A method with no ``card`` object is not a failure to describe: a Stripe Link wallet
    exposes none, and "Link" is the true answer. Its card fields stay null and the UI has
    to cope, exactly as ``payment_method_display`` decided.
    """
    pm_id = pm.get("id")
    card = pm.get("card") or {}
    kind = pm.get("type") or ""
    details = pm.get("billing_details") or {}
    address = details.get("address") or {}

    brand, last4 = card.get("brand"), card.get("last4")
    exp_month, exp_year = card.get("exp_month"), card.get("exp_year")
    months_left = _months_until(exp_year, exp_month, now)
    wallet_type = ((card.get("wallet") or {}) or {}).get("type")

    # THE ISSUING COUNTRY, falling back to the billing address.
    #
    # A DELIBERATE CHOICE between two facts that disagree constantly, and it looks like a
    # bug from the inside: pick the Philippines in the card form and the row still reads
    # "United States", because `card.country` is where the card was ISSUED and Stripe's
    # 4242 test card is issued in the US. That is the column working.
    #
    # The issuer is the fact worth printing. It is a property of the card, which is what
    # these rows are; it is what drives cross-border fees and the declines that come with
    # them; and it is the half the payer cannot see anywhere else. The billing address is
    # already in the row's own Edit dialog, and it is whatever the payer last typed.
    #
    # The address is the FALLBACK rather than nothing, because a wallet has no card object
    # and therefore no issuer to name, and an address country beats a blank cell.
    country_code = card.get("country") or address.get("country")

    created = pm.get("created")
    added = None
    if created:
        try:
            from datetime import datetime, timezone

            added = datetime.fromtimestamp(int(created), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            added = None

    return {
        "id": pm_id,
        "type": kind or ("card" if card else ""),
        "brand": brand,
        "brand_label": _brand_label(brand) if card else kind.replace("_", " ").title(),
        "last4": last4,
        # The complete string to print when a row has to be described in one line.
        "label": (
            f"{_brand_label(brand)} •••• {last4}"
            if last4
            else (kind.replace("_", " ").title() or "Saved method")
        ),
        # Stripe's own field. Often NOT the payer — a finance lead's card on a director's
        # account is normal — so it is shown rather than assumed.
        "cardholder": details.get("name"),
        "email": details.get("email"),
        "address": {
            "line1": address.get("line1"),
            "line2": address.get("line2"),
            "city": address.get("city"),
            "state": address.get("state"),
            "postal_code": address.get("postal_code"),
            "country": address.get("country"),
        },
        "exp_month": exp_month,
        "exp_year": exp_year,
        "expiry": (
            f"{int(exp_month):02d}/{int(exp_year) % 100:02d}"
            if exp_month and exp_year
            else None
        ),
        # "credit" / "debit" / "prepaid". Stripe's own classification, not a guess from
        # the brand — a debit Visa and a credit Visa are the same brand and behave
        # differently at the issuer.
        "funding": card.get("funding"),
        # How it was presented: "apple_pay", "google_pay", "link"… None for a card
        # entered as a number.
        "wallet": wallet_type,
        "wallet_label": _wallet_label(wallet_type),
        "country": country_code,
        # Resolved against the country registry, so this column reads the way the rest of
        # the portal's country columns do. Falls back to the code — a two-letter cell is a
        # worse answer than a name and a better one than a blank.
        "country_name": (country_names or {}).get(country_code or "", country_code),
        "is_default": bool(default_id) and pm_id == default_id,
        "expired": months_left is not None and months_left < 0,
        "expires_soon": (
            months_left is not None and 0 <= months_left <= EXPIRING_SOON_MONTHS
        ),
        "added": _fmt(added),
        "added_iso": added.isoformat() if added else None,
    }


def _sorted(views: list[dict]) -> list[dict]:
    """Default first, then newest saved first.

    The default is the only row with billing meaning, so it leads regardless of when it
    was added — a payer scanning for "what will actually be charged" should not have to
    find it.
    """
    return sorted(
        views,
        key=lambda v: (0 if v["is_default"] else 1, -(_epoch(v))),
    )


def _epoch(view: dict) -> int:
    from datetime import datetime

    iso = view.get("added_iso")
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return 0


def _bills_forward(user_id) -> bool:
    """Is anything on this account due to be charged again.

    Asked before the last saved method may be removed. ``is_billing_forward`` is the same
    question the renewal runner asks when it decides what to put on the next invoice — see
    ``access.is_billing_forward``, which distinguishes it from "do they have it" and "is
    money involved" — so the refusal cannot disagree with what would actually be charged.

    Fails CLOSED. If the rows cannot be read we answer True and refuse the removal: a
    refusal the payer can retry is a smaller harm than a silently emptied wallet on an
    account that renews next week.
    """
    from blueprints.subscription.services import access

    try:
        return any(
            access.is_billing_forward(phase=getattr(row, "phase", None) or "")
            for row in sub_store.module_rows_for_payer(user_id)
        )
    except Exception:
        logger.exception(
            "payment methods: could not read the module rows for payer {}", user_id
        )
        return True


def list_for_user(user_id) -> dict:
    """Every method saved on the payer's account, with the default marked.

    ``has_account`` is the distinction the page has to be able to draw: a payer whose
    trial never captured a card has no Stripe customer at all, which is not an empty
    wallet and not an error — it is the state where "Add payment method" is the only thing
    on the screen.

    Stripe failures PROPAGATE. An empty list rendered after a failed read tells a payer
    their cards are gone; the page can retry an error.
    """
    customer_id = sub_store.customer_id_for_user(user_id)
    if not customer_id:
        return {"has_account": False, "default_id": None, "methods": [], "total": 0}

    default_id = customer_default_payment_method(customer_id)
    now = clock.now()
    raw = list_payment_methods(customer_id)

    # ONE registry query for the whole list, not one per row. Reuses the portal's own
    # resolver so this column and the entity ones name a country the same way.
    #
    # NEVER FAILS THE PAGE OVER A LABEL — the same posture the resolver itself takes, and
    # the wrapper is here because its own handler cannot always run: it rolls back on
    # error, and the rollback needs the app context the failure may have been about. Every
    # cell falls back to the two-letter code, which is a worse answer than a name and a far
    # better one than an error where the payer's cards should be.
    from blueprints.subscription.services.portal import _country_names

    codes = {
        (pm.get("card") or {}).get("country")
        or ((pm.get("billing_details") or {}).get("address") or {}).get("country")
        for pm in raw
    }
    try:
        names = _country_names(codes)
    except Exception:
        logger.exception("payment methods: could not resolve country names")
        names = {}

    methods = _sorted([_view(pm, default_id, now, names) for pm in raw])
    return {
        "has_account": True,
        "default_id": default_id,
        "methods": methods,
        "total": len(methods),
    }


# --- Adding ------------------------------------------------------------------


def start_setup(user_id) -> dict:
    """Open a SetupIntent for the in-app card form, and hand back what Elements needs.

    ``client_secret`` authorises the browser to confirm THIS intent and nothing else, and
    the publishable key is safe to publish by definition. Neither is a credential for this
    application.

    Works for a payer with NO customer, which is the point: the hosted-portal route this
    replaces answered 409 there and told them to go and subscribe an entity first, because
    a billing portal session needs a customer to exist. A SetupIntent does not, so the
    first card can be saved from the billing page — and the customer is created in
    ``confirm_setup`` once Stripe says the card is real.

    Adding a card AUTHORISES NOTHING. Billing an entity needs that entity's own consent
    (``store.has_billing_consent``), which is granted on its settings page and is exactly
    what stops a card saved here from silently converting some other company's trial.
    """
    customer_id = sub_store.customer_id_for_user(user_id)
    intent = create_setup_intent(customer_id, user_id=user_id)
    key = get_publishable_key()
    if not key:
        # Elements cannot be mounted without it, and failing here names the cause. The
        # alternative is a card form that renders and then silently refuses to confirm.
        logger.error("payment methods: STRIPE_PUBLISHABLE_KEY is not configured")
        raise PaymentMethodError(
            "Card payments aren't configured on this environment.", status=503
        )
    return {
        "client_secret": intent.get("client_secret"),
        "publishable_key": key,
        "setup_intent": intent.get("id"),
    }


def _payer_customer_for_confirm(user_id, intent_customer: str | None) -> tuple[str, bool]:
    """The customer the confirmed card belongs on. Returns ``(customer_id, created)``.

    Three cases, and the ordering matters:

    * the payer already has a customer — it WINS, even if the intent named another. Two
      customers for one payer make ``find_customer_by_user`` ambiguous, which is worse
      than the duplicate itself (the same reasoning as
      ``checkout._adopt_session_customer``).
    * the intent carried one and the payer has none — adopt it.
    * neither — create one now. This is the first moment the card is a fact, which is the
      only moment a customer may be made.
    """
    # Resolved rather than read off the mapping: a payer whose row went missing has a real
    # card-bearing customer in Stripe, and creating a second one here would strand it.
    from blueprints.subscription.services.checkout import (_payer_identity,
                                                           _resolve_customer_id,
                                                           _seed_user_customer_mapping)

    existing = _resolve_customer_id(user_id)
    if existing:
        if intent_customer and intent_customer != existing:
            logger.warning(
                "payment methods: setup intent for payer {} named customer {} but the "
                "payer already has {} — attaching to the existing one",
                user_id, intent_customer, existing,
            )
        return existing, False

    if intent_customer:
        _seed_user_customer_mapping(user_id, intent_customer)
        return intent_customer, False

    customer = create_customer_for_user(user_id, **_payer_identity(user_id))
    customer_id = customer.get("id")
    if not customer_id:
        raise PaymentMethodError(
            "We couldn't open a billing account for that card. Let's try again?",
            status=502,
        )
    # NOT swallowed the way ``_seed_user_customer_mapping`` swallows its own failures: the
    # anchor and paid-through live on this row, so without it the next charge cannot be
    # billed at all. The ``metadata.user_id`` stamp above keeps the customer findable, so
    # a raise here loses nothing but the request.
    sub_store.upsert_customer_mapping(user_id, customer_id)
    return customer_id, True


def confirm_setup(user_id, setup_intent_id: str, *, make_default: bool = False) -> dict:
    """Take ownership of a card the browser just confirmed. Returns the fresh list.

    The browser confirms the SetupIntent directly with Stripe, so this is the app finding
    out what happened — the id comes back from the client and every fact is re-read from
    Stripe rather than trusted.

    ``metadata.user_id`` is the gate. A SetupIntent with no customer has nothing else
    tying it to anybody, so one that does not carry the caller's own stamp is refused: it
    is either another payer's or not ours at all.

    Idempotent. Re-running on the same intent re-attaches an already-attached method
    (Stripe accepts it), re-sets the same default, and returns the same list — a
    double-click or a retried request cannot produce two cards or two customers.
    """
    intent = retrieve_setup_intent(setup_intent_id)
    if not intent:
        raise PaymentMethodError("That card setup couldn't be found.", status=404)

    stamped = str((intent.get("metadata") or {}).get("user_id") or "")
    if stamped != str(user_id):
        # Same answer as "not found": telling the two apart confirms an id to someone who
        # should not be asking.
        raise PaymentMethodError("That card setup couldn't be found.", status=404)

    status = intent.get("status")
    payment_method = intent.get("payment_method")
    if isinstance(payment_method, dict):
        payment_method = payment_method.get("id")
    if status != "succeeded" or not payment_method:
        # The card was declined, abandoned, or still needs the customer to authenticate.
        # Nothing is saved and nothing is created — notably no customer.
        raise PaymentMethodError(
            "That card wasn't saved. Please check the details and try again.", status=409
        )

    intent_customer = intent.get("customer")
    if isinstance(intent_customer, dict):
        intent_customer = intent_customer.get("id")

    customer_id, created_customer = _payer_customer_for_confirm(user_id, intent_customer)

    # Stripe attaches automatically when the intent named a customer. It cannot have when
    # the payer had none, and the customer we just made is not the one the intent knew
    # about — so attach explicitly. Attaching an already-attached method to the same
    # customer is a no-op at Stripe, which is what keeps the retry above harmless.
    try:
        attach_payment_method(payment_method, customer_id)
    except Exception:
        # Only a genuine failure matters here; the common "already attached" case does not
        # raise. Re-read below decides whether anything actually landed.
        logger.exception(
            "payment methods: could not attach {} to {}", payment_method, customer_id
        )

    forget_default_payment_method(customer_id)
    current_default = customer_default_payment_method(customer_id)
    # The FIRST card is always the default — an account whose only saved method is not
    # nominated has nothing to charge, which is the state dunning exists to shout about.
    if make_default or created_customer or not current_default:
        set_customer_default_payment_method(customer_id, payment_method)

    return list_for_user(user_id)


# --- Editing, promoting, removing --------------------------------------------


def _owned(user_id, payment_method_id: str) -> tuple[str, dict]:
    """``(customer_id, payment_method)`` once the method is proven to be the caller's.

    THE SECURITY CHECK for every mutation below. The id arrives from the browser, so
    ``pm.customer`` is compared against the customer resolved from the TOKEN's user — a
    ``pm_…`` id belonging to somebody else answers "not found" rather than being acted on.
    """
    if not payment_method_id:
        raise PaymentMethodError("No payment method was given.", status=400)

    customer_id = sub_store.customer_id_for_user(user_id)
    if not customer_id:
        raise PaymentMethodError("You don't have a billing account yet.", status=409)

    try:
        pm = retrieve_payment_method(payment_method_id)
    except Exception:
        logger.exception(
            "payment methods: could not read {} for payer {}", payment_method_id, user_id
        )
        raise PaymentMethodError("That payment method couldn't be found.", status=404)

    pm_customer = (pm or {}).get("customer")
    if isinstance(pm_customer, dict):
        pm_customer = pm_customer.get("id")
    if not pm or str(pm_customer or "") != str(customer_id):
        raise PaymentMethodError("That payment method couldn't be found.", status=404)
    return customer_id, pm


def set_default(user_id, payment_method_id: str) -> dict:
    """Nominate the method every future invoice is charged against. Returns the list.

    This is the ONE write on this screen with billing consequences, and they are
    account-wide: renewals bill the payer, so promoting a card here changes what charges
    every company on the account, not one of them.
    """
    customer_id, _pm = _owned(user_id, payment_method_id)
    set_customer_default_payment_method(customer_id, payment_method_id)
    return list_for_user(user_id)


def _valid_expiry(exp_month, exp_year) -> tuple[int, int]:
    """Parse and sanity-check an edited expiry, in the app's own words.

    Checked here rather than left to Stripe because Stripe's refusal ("Your card's
    expiration year is invalid.") arrives as an API error the form cannot attach to a
    field, and a past date is the mistake worth catching before it becomes a saved card
    that cannot be charged.
    """
    try:
        month, year = int(exp_month), int(exp_year)
    except (TypeError, ValueError):
        raise PaymentMethodError("Enter the expiry as a month and a year.", status=422)

    if not 1 <= month <= 12:
        raise PaymentMethodError("That expiry month doesn't exist.", status=422)
    if year < 100:
        # "29" for 2029 — what a customer types into a two-box expiry field.
        year += 2000
    now = clock.now()
    if (year, month) < (now.year, now.month):
        raise PaymentMethodError("That expiry date has already passed.", status=422)
    return month, year


def update(
    user_id,
    payment_method_id: str,
    *,
    exp_month=None,
    exp_year=None,
    name: str | None = None,
    address: dict | None = None,
) -> dict:
    """Correct a saved method's expiry or billing details. Returns the list.

    Deliberately NOT a way to change the card. Stripe does not allow a number, brand or
    CVC to be edited — a different card is a different PaymentMethod — so this covers the
    two things that legitimately change on the same plastic: a reissued expiry, and the
    name and address the issuer checks. Everything else is "Add payment method".
    """
    _customer_id, pm = _owned(user_id, payment_method_id)

    payload: dict = {}
    if exp_month is not None or exp_year is not None:
        if not (pm.get("card") or {}):
            raise PaymentMethodError(
                "That payment method has no expiry date to change.", status=422
            )
        month, year = _valid_expiry(
            exp_month if exp_month is not None else (pm.get("card") or {}).get("exp_month"),
            exp_year if exp_year is not None else (pm.get("card") or {}).get("exp_year"),
        )
        payload["exp_month"], payload["exp_year"] = month, year

    details: dict = {}
    if name is not None:
        details["name"] = name.strip() or None
    if address is not None:
        # Only the keys Stripe knows, and only the ones supplied — sending the whole shape
        # with blanks would erase an address the payer did not touch.
        allowed = ("line1", "line2", "city", "state", "postal_code", "country")
        cleaned = {
            key: (str(address.get(key)).strip() or None)
            for key in allowed
            if address.get(key) is not None
        }
        if cleaned:
            details["address"] = cleaned
    if details:
        payload["billing_details"] = details

    if not payload:
        raise PaymentMethodError("There was nothing to change.", status=422)

    update_payment_method(payment_method_id, **payload)
    return list_for_user(user_id)


def remove(user_id, payment_method_id: str) -> dict:
    """Detach a saved method. Returns the list.

    Two refusals, both about leaving the account unable to pay itself — see the module
    docstring. Neither is a permission check: they are guards on a live billing
    relationship, and each one names the fix.
    """
    customer_id, pm = _owned(user_id, payment_method_id)

    default_id = customer_default_payment_method(customer_id)
    others = [
        m for m in list_payment_methods(customer_id) if m.get("id") != payment_method_id
    ]

    if payment_method_id == default_id and others:
        raise PaymentMethodError(
            "That's the payment method your invoices are charged to. Make another one "
            "the default first, then remove it.",
            status=409,
        )
    if not others and _bills_forward(user_id):
        raise PaymentMethodError(
            "This is the only payment method on the account, and there are "
            "subscriptions still being billed to it. Add another one first.",
            status=409,
        )

    detach_payment_method(payment_method_id)
    # Detaching the default clears it at Stripe's end. Nothing here promotes a survivor in
    # its place: which card an account pays with is the payer's decision, and choosing one
    # for them silently is how a company gets charged on a card it did not nominate. The
    # page shows "no default" and asks — the only case this can arise in is a non-default
    # detach, since the branch above refuses the other one.
    forget_default_payment_method(customer_id)
    logger.info(
        "payment methods: payer {} removed {} ({})",
        user_id, payment_method_id, (pm.get("card") or {}).get("last4") or pm.get("type"),
    )
    return list_for_user(user_id)
