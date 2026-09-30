"""Persistence seam for the subscription tables.

Owns the local tables: ``user_stripe_customer`` (payer -> Stripe customer, plus the
payer's billing cycle), ``entity_module_subscription`` (per-module state: phase,
app-level trial, cancel-extension), ``subscription_audit_log`` (append-only history) and
``subscription_invoice`` / ``subscription_invoice_line`` (what was actually billed).

These rows ARE the source of truth now. They were once a mirror rebuilt from Stripe
subscriptions plus whatever app-owned state Stripe had nowhere to hold; with the Stripe
biller retired there is nothing to mirror, and Stripe is only the payment rail the
invoices are issued against. Higher-level services call these helpers; unit tests mock
THIS module rather than a database (the test app runs on SQLite, where the
``pettycashv3`` schema isn't materialised).

Each mutating helper commits its own unit of work, mirroring
``entity.services.modules.set_entity_module``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from blueprints.subscription.constants import (
    EXT_INVOICED,
    EXT_PENDING,
    PHASE_ACTIVE,
    PHASE_PAST_DUE,
    PHASE_SCHEDULED_CANCEL,
    PHASE_TRIAL,
)
from blueprints.subscription.services.billing import plan_code
from models.db import (
    BillingAccountPaymentMethod,
    BillingPlan,
    EntityBillingConsent,
    EntityBillingGroup,
    EntityModuleSubscription,
    PayerBillingGroup,
    SubscriptionAuditLog,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
    UserStripeCustomer,
    db,
)

# Columns a caller may set on an existing row WITHOUT disturbing the fields it doesn't
# pass. payer_user_id / entity_id / function_code are identity and handled separately.
_MODULE_MUTABLE_FIELDS = frozenset(
    {
        "phase",
        "app_access_until",
        "trial_end",
        "first_billed_at",
        "extension_state",
        "extension_amount",
    }
)


def _uuid() -> str:
    return str(uuid.uuid4())


# --- Payer (user) -> Stripe customer / subscription --------------------------


def customer_mapping_for_user(user_id) -> UserStripeCustomer | None:
    """The payer's ``user_stripe_customer`` row, or None if they have no customer yet."""
    if not user_id:
        return None
    return UserStripeCustomer.query.filter_by(user_id=str(user_id)).one_or_none()


def customer_id_for_user(user_id) -> str | None:
    """The payer's Stripe customer id (None before a customer exists)."""
    mapping = customer_mapping_for_user(user_id)
    return mapping.stripe_customer_id if mapping else None


def user_for_customer(customer_id) -> str | None:
    """Reverse lookup: the payer user id that owns a Stripe customer (None if the
    customer isn't mapped locally)."""
    if not customer_id:
        return None
    mapping = UserStripeCustomer.query.filter_by(
        stripe_customer_id=str(customer_id)
    ).one_or_none()
    return mapping.user_id if mapping else None


def upsert_customer_mapping(user_id, stripe_customer_id) -> UserStripeCustomer:
    """Create or update the 1:1 payer->customer link.

    Never creates a second row for a user (unique on ``user_id``).
    """
    mapping = customer_mapping_for_user(user_id)
    if mapping is None:
        mapping = UserStripeCustomer(
            id=_uuid(),
            user_id=str(user_id),
            stripe_customer_id=stripe_customer_id,
        )
        db.session.add(mapping)
    else:
        mapping.stripe_customer_id = stripe_customer_id
    db.session.commit()
    return mapping


# --- Per-(entity, module) mirror row -----------------------------------------


def module_row(entity_id, function_code) -> EntityModuleSubscription | None:
    """The current row for one entity+module (None if never created)."""
    if not entity_id or not function_code:
        return None
    return EntityModuleSubscription.query.filter_by(
        entity_id=str(entity_id), function_code=str(function_code).upper()
    ).one_or_none()


def module_rows_for_entity(entity_id) -> list[EntityModuleSubscription]:
    """Every module row for an entity (both modules of a bundle, etc.)."""
    if not entity_id:
        return []
    return EntityModuleSubscription.query.filter_by(entity_id=str(entity_id)).all()


def payer_for_entity(entity_id) -> str | None:
    """The payer user id for an entity, from any of its mirror rows (None if the entity
    has no subscription/trial yet). Under one-payer-per-entity these all agree, so the
    first row suffices — an invariant ``upsert_module_row`` now enforces rather than
    assumes. This is how ``customer_id_for_entity`` resolves entity -> payer."""
    if not entity_id:
        return None
    row = EntityModuleSubscription.query.filter_by(entity_id=str(entity_id)).first()
    return row.payer_user_id if row else None


def may_manage_subscription(entity_id, user_id) -> bool:
    """Whether ``user_id`` may change what this entity is billed for.

    Only the PAYER. An entity's subscription is one person's financial relationship —
    their card, their cycle, their invoice — and one-payer-per-entity is already enforced
    on the write (see ``upsert_module_row``). Without this, any other admin could cancel
    a module, start a trial that converts, or press Pay now, and the charge would land on
    a card belonging to someone who never saw the screen. The write invariant kept the
    BILLING coherent; it did nothing about who was allowed to trigger it.

    Until a payer exists nobody is being billed, so any admin may start the first trial
    or subscription — that act is precisely what establishes the payer. Entity-level
    permission (``Permission.MODULE_MANAGE``) still applies on top of this: being the
    payer is necessary, not sufficient.
    """
    if not entity_id or not user_id:
        return False
    payer = payer_for_entity(entity_id)
    return payer is None or str(payer) == str(user_id)


# --- Per-entity billing consent ----------------------------------------------


def has_billing_consent(entity_id, user_id=None) -> bool:
    """True if ``user_id`` has agreed to be billed for THIS entity.

    A payer's card lives on their one Stripe customer and is shared by every entity they
    pay for, so "has a card" says nothing about whether they agreed to pay for a
    particular entity. Both charging paths consult this: paid checkout
    (``checkout.start_modules_checkout``) and — more importantly — the trial-end job
    (``checkout.convert_or_expire_due_trials``), which otherwise converts a brand-new
    entity's trial to paid with no user action at all.

    ASK ABOUT A PAYER, always. The question this answers is "may I charge THIS card for
    this entity", and consent is given by a person, not held by a company. It used to
    ignore ``user_id`` entirely and answer "does any row exist", which was indistinguishable
    from the right answer only because an entity's payer never changed. Once a subscription
    can be handed over, the old payer's row would authorise charging the NEW payer's card —
    including the trial-end job converting with no user action at all.

    Omitting ``user_id`` keeps the old any-row behaviour and logs, so the remaining callers
    are visible rather than silently wrong. Treat that as a call site not yet converted.
    """
    if not entity_id:
        return False
    query = EntityBillingConsent.query.filter_by(entity_id=str(entity_id))
    if user_id is None:
        logger.warning(
            "consent: asked whether entity {} has consent without naming a payer; "
            "answering about ANY payer, which is wrong once a subscription is transferred",
            entity_id,
        )
    else:
        query = query.filter(EntityBillingConsent.user_id == str(user_id))
    return query.first() is not None


def record_billing_consent(entity_id, user_id, source: str) -> None:
    """Record that ``user_id`` agreed to be billed for ``entity_id``.

    ``source`` is how it was given — ``"card"`` (entered a card in a setup Checkout
    opened for this entity), ``"confirmed"`` (accepted the in-app charge confirmation
    against an already-saved card), or ``"transfer"`` (accepted a handover of the whole
    subscription, which is the same agreement made about a company someone else was
    paying for). Kept for support: "why was I billed for this entity?"

    Idempotent PER PAYER, which is the point: re-consenting is a harmless no-op so a
    refreshed return URL does nothing, but a DIFFERENT payer consenting to the same entity
    inserts a second row rather than being swallowed. The old rows are left alone — they
    are the answer to "why was I billed for this entity in June", and the person who asks
    that is usually the one who no longer pays.
    """
    if not entity_id or not user_id:
        return
    if has_billing_consent(entity_id, user_id):
        return
    db.session.add(
        EntityBillingConsent(
            id=_uuid(),
            entity_id=str(entity_id),
            user_id=str(user_id),
            source=source,
        )
    )
    db.session.commit()


def billing_plan_for_codes(codes) -> BillingPlan | None:
    """The in-house plan billing exactly ``codes`` — Minty's answer to ``_plan_for_codes``.

    Keyed by the module SET, so one module resolves to its own plan and two resolve to
    the bundle. Returns None when the catalog can't express the combination, which the
    caller must treat as "cannot bill" rather than falling back to a sum: the bundle IS
    the discount, and adding two single prices would overcharge.
    """
    try:
        code = plan_code(codes)
    except ValueError:
        return None
    return BillingPlan.query.filter_by(code=code, is_active=True).first()


def active_billing_plans() -> list[BillingPlan]:
    """Every sellable plan, cheapest first."""
    return (
        BillingPlan.query.filter_by(is_active=True)
        .order_by(BillingPlan.amount, BillingPlan.code)
        .all()
    )


def billing_cycle_for_user(user_id) -> tuple[datetime | None, str | None]:
    """The payer's ``(anchor_at, currency)``, or ``(None, None)`` if they have no cycle.

    A payer only has a cycle once something has actually been billed — an app-level
    trial creates no anchor, because nothing has been charged to anchor to.
    """
    row = customer_mapping_for_user(user_id)
    if row is None:
        return None, None
    return row.anchor_at, row.currency


def start_billing_cycle(user_id, anchor_at: datetime, currency: str) -> None:
    """Record the payer's FIRST anchor. Never moves an existing one.

    The anchor is immutable by design: every period is re-derived from it, so moving it
    would retroactively redraw every past period. Renewal advances nothing here — the
    current period comes from ``billing.period_containing(anchor, now)``.
    """
    row = customer_mapping_for_user(user_id)
    if row is None:
        logger.warning("billing: no billing account for user {}; cannot anchor", user_id)
        return
    if row.anchor_at is not None:
        return
    row.anchor_at = anchor_at
    row.currency = (currency or "").upper() or None
    db.session.commit()


def paid_through_for_user(user_id) -> datetime | None:
    """The EARLIEST date anything on this payer's account is paid through.

    An account-level question only — "when does something next bill for this person".
    Per-entity questions must use ``paid_through_for_entity``: since a payer may hold
    several cards, and each card buys its own period for its own companies, there is no
    single date that is true of all of them.

    Earliest rather than latest because the account-level uses are all "is anything due":
    taking the furthest-ahead group would hide a lapsed one behind a healthy one.

    Answers from the GROUPS only. There used to be a fallback to
    ``user_stripe_customer.paid_through`` for a payer with no group; that column was the
    superseded one-cycle-per-payer design and has been dropped, along with the fallback,
    once the backfill guaranteed every payer a group. A payer with none now answers None,
    which is the truthful answer rather than a stale one.
    """
    dates = [
        group.paid_through
        for group in billing_groups_for_payer(user_id)
        if group.paid_through is not None
    ]
    return min(dates) if dates else None


def paid_through_for_entity(entity_id) -> datetime | None:
    """What THIS company is paid through — the date its access is measured against.

    The card that pays for a company buys its periods, so the date lives on that card's
    group. Two companies of one payer on two cards genuinely have two answers, and one of
    them can be past due while the other is not; that containment is the whole point of
    the grain.

    This is NOT the per-row ``current_period_end`` that was removed for drifting. That one
    was a copy refreshed only when its own entity happened to be touched, so three rows of
    one payer held three different answers to ONE question. This is one answer per group,
    written by the charge that collected it.

    None for an entity with no nomination — a trial that has never been billed. This used
    to fall back to the payer's account row; that column is gone with the one-cycle-per-payer
    design it belonged to. A BILLABLE entity with no group is an error, and the charge paths
    say so rather than reading a date here.
    """
    group = billing_group_for_entity(entity_id)
    return group.paid_through if group is not None else None


def pending_extensions_for_payer(user_id) -> list[EntityModuleSubscription]:
    """Cancel-extensions this payer owes but has not been billed for yet.

    Recorded at cancellation and collected by the next renewal run, so that cancelling
    never depends on a card clearing — an expired card must not be able to stop somebody
    leaving.
    """
    return (
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.payer_user_id == str(user_id),
            EntityModuleSubscription.extension_state == EXT_PENDING,
            EntityModuleSubscription.extension_amount.isnot(None),
            EntityModuleSubscription.extension_amount > 0,
        )
        .order_by(EntityModuleSubscription.entity_id)
        .all()
    )


def mark_extensions_invoiced(row_ids) -> int:
    """Close out cancel-extensions that have now been billed. Returns rows updated.

    The other half of ``pending_extensions_for_payer``, and it is not optional. That
    query selects on ``extension_state == EXT_PENDING``, so an extension that is never
    moved off ``pending`` is picked up by EVERY subsequent renewal — the customer is
    charged the same cancellation fee once a month, indefinitely, for a module they have
    already left.

    Called only after the invoice carrying them is PAID, for the same reason
    ``paid_through`` only advances on success: marking first would drop the charge
    silently if collection then failed, and the days were still granted.

    It also arms a guard that could not fire before. ``_reactivate_module_in_house``
    refuses to undo a cancellation whose extension has been invoiced, because the money
    is real and returning it is a decision rather than a cleanup — but while every row
    stayed ``pending`` forever, that branch was unreachable and reactivating silently
    discarded a charge the customer had paid.
    """
    ids = [str(i) for i in row_ids if i]
    if not ids:
        return 0
    updated = (
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.id.in_(ids),
            # Only ever pending -> invoiced. A row already credited or refunded must not
            # be dragged back to invoiced by a re-run.
            EntityModuleSubscription.extension_state == EXT_PENDING,
        )
        .update({EntityModuleSubscription.extension_state: EXT_INVOICED},
                synchronize_session=False)
    )
    db.session.commit()
    return updated


def accounts_with_billing() -> list[UserStripeCustomer]:
    """Payers who have an anchor — i.e. something has been billed for them at least once.

    A payer with no anchor has only ever had app-level trials, so there is no cycle to
    renew and nothing to collect.
    """
    return (
        UserStripeCustomer.query.filter(UserStripeCustomer.anchor_at.isnot(None))
        .order_by(UserStripeCustomer.anchor_at)
        .all()
    )


def module_rows_for_payer(user_id) -> list[EntityModuleSubscription]:
    """Every module row this payer is responsible for, across all their entities.

    Renewal is a PAYER-level event — one subscription, one invoice, however many
    entities — so the work list has to start from the payer rather than from an entity.
    """
    return (
        EntityModuleSubscription.query.filter_by(payer_user_id=str(user_id))
        .order_by(
            EntityModuleSubscription.entity_id,
            EntityModuleSubscription.function_code,
        )
        .all()
    )


def entity_ids_with_billed_modules(user_id=None) -> set[str]:
    """Entities holding a module in a phase that is BILLED, whatever their access says.

    The access sweep's other population is "modules currently switched on", which can
    only ever shrink. This one is read from the subscription rows instead, so a module
    that was switched off while its account was past due is still visible to the sweep
    once the account pays and its entitlement returns.

    Phase alone, deliberately: ``access.is_paid_module`` also weighs ``first_billed_at``
    to tell a cancelled paid module from a cancelled trial, but that is a per-row call
    the sweep makes anyway. This only has to be a superset cheap enough to run daily.

    ``user_id`` narrows it to one payer, for a caller reconciling a single account.
    """
    query = EntityModuleSubscription.query.filter(
        EntityModuleSubscription.phase.in_(
            (PHASE_ACTIVE, PHASE_PAST_DUE, PHASE_SCHEDULED_CANCEL)
        )
    )
    if user_id is not None:
        query = query.filter_by(payer_user_id=str(user_id))
    return {
        str(row.entity_id)
        for row in query.with_entities(EntityModuleSubscription.entity_id).all()
    }


# --- Billing groups: one card, and everything it pays for ---------------------
#
# A payer used to have exactly one card, one ``paid_through`` and one dunning clock, all
# on ``user_stripe_customer``. They now live per GROUP — one payment method plus the
# companies nominated onto it — so that a card failing takes down only what that card
# pays for. ``anchor_at`` and ``currency`` stay on the account: every group of a payer
# renews on the same period boundaries, so it is one cycle billed as several invoices.
#
# The card is an ATTRIBUTE of the group, never its key. Replacing an expiring card is an
# UPDATE of ``stripe_payment_method_id``; keying on the ``pm_...`` would make every
# replacement a new group with a NULL ``paid_through``, which ``due_renewals`` skips —
# the company would stop renewing with nothing raising.


def billing_group(group_id) -> PayerBillingGroup | None:
    """One group by id, or None."""
    if not group_id:
        return None
    return PayerBillingGroup.query.filter_by(id=str(group_id)).one_or_none()


def billing_groups_for_payer(user_id) -> list[PayerBillingGroup]:
    """Every card this payer bills on, oldest first.

    Oldest first is load-bearing in one place: an invoice raised before per-entity cards
    carries no group, and ``dunning`` attributes those to the payer's FIRST group — which
    after the backfill is the single group holding everything they had.
    """
    if not user_id:
        return []
    return (
        PayerBillingGroup.query.filter_by(payer_user_id=str(user_id))
        .order_by(PayerBillingGroup.created_at, PayerBillingGroup.id)
        .all()
    )


# --- the cards on an account ---------------------------------------------------------
#
# ``payer_billing_group.stripe_payment_method_id`` is the card an account CHARGES.
# ``billing_account_payment_method`` is every card the payer has put on that account. The
# default is recorded in both places on purpose — the charge path reads the account row
# and must not join to find out what to charge — so everything in this section writes the
# pair together. Nothing else should write either one.


def cards_in_group(group_id) -> list[BillingAccountPaymentMethod]:
    """Every card on this account, default first then oldest first."""
    if not group_id:
        return []
    return (
        BillingAccountPaymentMethod.query.filter_by(billing_group_id=str(group_id))
        .order_by(
            BillingAccountPaymentMethod.is_default.desc(),
            BillingAccountPaymentMethod.created_at,
            BillingAccountPaymentMethod.id,
        )
        .all()
    )


def _shelf_row(group_id, payment_method_id) -> BillingAccountPaymentMethod | None:
    return BillingAccountPaymentMethod.query.filter_by(
        billing_group_id=str(group_id),
        stripe_payment_method_id=str(payment_method_id),
    ).one_or_none()


def add_card_to_group(
    group_id, payment_method_id, make_default: bool = False
) -> BillingAccountPaymentMethod:
    """Put a card on an account. Find-or-create; does not commit.

    Uncommitted on purpose: every caller is already inside a unit of work that is
    creating or repointing something else, and a card added by a transaction that then
    rolls back must not survive it.

    ``make_default`` moves the account's charged card too — the pair is never written
    apart. Without it the card is simply on the shelf, which is what "add a second card"
    means when the payer has not asked to switch.
    """
    if not group_id or not payment_method_id:
        raise ValueError("group and payment method are both required")

    row = _shelf_row(group_id, payment_method_id)
    if row is None:
        row = BillingAccountPaymentMethod(
            id=_uuid(),
            billing_group_id=str(group_id),
            stripe_payment_method_id=str(payment_method_id),
            is_default=False,
        )
        db.session.add(row)
        # Flushed for the same reason ``nominate_card_for_entity`` flushes: the caller
        # may promote this row in the same transaction, and the UPDATE below has to see
        # it.
        db.session.flush()

    if make_default:
        _promote(group_id, row)
    return row


def _promote(group_id, row: BillingAccountPaymentMethod) -> None:
    """Make one shelf row the account's default, in the database's own terms.

    Demote-then-promote, in that order and in one flush. The partial unique index
    ``uq_billing_account_payment_method_default`` allows exactly one default per account,
    so promoting before demoting collides with the card being replaced.
    """
    group = billing_group(group_id)
    if group is None:
        raise ValueError(f"no billing account {group_id}")

    BillingAccountPaymentMethod.query.filter(
        BillingAccountPaymentMethod.billing_group_id == str(group_id),
        BillingAccountPaymentMethod.id != row.id,
        BillingAccountPaymentMethod.is_default.is_(True),
    ).update({"is_default": False}, synchronize_session="fetch")
    db.session.flush()

    row.is_default = True
    # THE OTHER HALF OF THE PAIR. Renewals and dunning read this column, not the shelf;
    # setting one without the other bills a card the payer is not being shown, and
    # nothing raises when it happens.
    group.stripe_payment_method_id = row.stripe_payment_method_id


def set_group_default_card(group_id, payment_method_id) -> PayerBillingGroup:
    """Switch the card an account charges. Commits.

    Adds the card to the shelf first if it is not already there, so "charge this card
    instead" cannot leave the account charging something its own list does not contain.
    """
    group = billing_group(group_id)
    if group is None:
        raise ValueError(f"no billing account {group_id}")

    row = add_card_to_group(group_id, payment_method_id)
    _promote(group_id, row)
    db.session.commit()
    logger.info(
        "billing: account {} now charges {} (payer {})",
        group.id, payment_method_id, group.payer_user_id,
    )
    return group


def create_billing_account(
    payer_user_id, payment_method_id, billing_email=None, billing_company=None
) -> PayerBillingGroup:
    """Open a billing account on a card, with the identity the payer gave. Commits.

    ALWAYS CREATES. Unlike ``nominate_card_for_entity`` this does not find-or-create on
    the card: since ``v1a01_billing_account`` a payer may hold the same card on two
    accounts — one company each, separate invoices — so a second account on a familiar
    card is a legitimate request rather than a duplicate to be folded away.

    Identity is optional and stays optional. An account nobody names renders as the
    payer's own details, which is what every account did before this existed.
    """
    if not payer_user_id or not payment_method_id:
        raise ValueError("payer and payment method are both required")

    group = PayerBillingGroup(
        id=_uuid(),
        payer_user_id=str(payer_user_id),
        stripe_payment_method_id=str(payment_method_id),
        billing_email=(str(billing_email).strip() or None) if billing_email else None,
        billing_company=(
            (str(billing_company).strip() or None) if billing_company else None
        ),
    )
    db.session.add(group)
    # Before the shelf row: it carries ``billing_group_id`` as a plain value, so the unit
    # of work sees no dependency and would batch the child INSERT first.
    db.session.flush()

    add_card_to_group(group.id, payment_method_id, make_default=True)
    db.session.commit()
    logger.info(
        "billing: payer {} opened account {} on {}",
        payer_user_id, group.id, payment_method_id,
    )
    return group


def set_account_identity(group_id, billing_email=None, billing_company=None) -> PayerBillingGroup:
    """Rename an account. Commits. Passing None for a field leaves it alone.

    Clearing a field takes an explicit empty string, so a caller that only knows one of
    the two cannot blank the other by omission.
    """
    group = billing_group(group_id)
    if group is None:
        raise ValueError(f"no billing account {group_id}")

    if billing_email is not None:
        group.billing_email = str(billing_email).strip() or None
    if billing_company is not None:
        group.billing_company = str(billing_company).strip() or None
    db.session.commit()
    return group


def nomination_for_entity(entity_id, payer_user_id=None) -> EntityBillingGroup | None:
    """The ``entity_billing_group`` row naming this company's card, or None.

    Grain is (entity, payer), so the payer has to be part of the question. Omitting it
    resolves the CURRENT payer from the module rows — the previous payer's nomination is
    history and must never answer for the new one, which is the same trap
    ``has_billing_consent`` was widened to avoid.
    """
    if not entity_id:
        return None
    payer = payer_user_id or payer_for_entity(entity_id)
    if not payer:
        return None
    return EntityBillingGroup.query.filter_by(
        entity_id=str(entity_id), payer_user_id=str(payer)
    ).one_or_none()


def billing_group_for_entity(entity_id, payer_user_id=None) -> PayerBillingGroup | None:
    """The group — and therefore the card and the cycle — paying for this company."""
    nomination = nomination_for_entity(entity_id, payer_user_id)
    return billing_group(nomination.billing_group_id) if nomination else None


def card_for_entity(entity_id, payer_user_id=None) -> str | None:
    """The ``pm_...`` this company is billed on, or None if none is nominated.

    None is NOT "use the account default". There is deliberately no fallback: a card
    inherited silently is how one card came to pay for every company in the first place.
    A billable entity answering None is an error for the caller to report and skip.
    """
    group = billing_group_for_entity(entity_id, payer_user_id)
    return group.stripe_payment_method_id if group else None


def nominate_card_for_entity(
    entity_id, payer_user_id, payment_method_id, source: str = "chosen"
) -> PayerBillingGroup:
    """Put this company on this card. Creates the group if the payer has none on it.

    Find-or-create rather than always-create: the group IS the card, so nominating a
    second company onto a card the payer already bills on must join the existing cycle,
    not open a second one against the same ``pm_...`` (which the unique index refuses
    anyway).

    A company already nominated is REPOINTED — the row is updated, never duplicated. The
    group it leaves is kept even when it empties: it holds the ``paid_through`` for
    periods that card actually collected, and an invoice that names it is history.
    """
    if not entity_id or not payer_user_id or not payment_method_id:
        raise ValueError("entity, payer and payment method are all required")

    payer = str(payer_user_id)
    group = PayerBillingGroup.query.filter_by(
        payer_user_id=payer, stripe_payment_method_id=str(payment_method_id)
    ).one_or_none()
    if group is None:
        group = PayerBillingGroup(
            id=_uuid(), payer_user_id=payer,
            stripe_payment_method_id=str(payment_method_id),
        )
        db.session.add(group)
        # FLUSHED BEFORE THE NOMINATION, and this is not optional: the nomination carries
        # ``billing_group_id`` as a plain value rather than through a relationship, so the
        # unit of work sees no dependency and batches the child INSERT first — straight
        # into a foreign key violation.
        db.session.flush()
        # The shelf has to be opened with the account. An account whose card list is
        # empty while it charges a card is exactly the divergence
        # ``billing_account_payment_method`` exists to prevent, and this is the one path
        # that creates an account without going through ``create_billing_account``.
        add_card_to_group(group.id, payment_method_id, make_default=True)

    nomination = nomination_for_entity(entity_id, payer)
    if nomination is None:
        nomination = EntityBillingGroup(
            id=_uuid(), entity_id=str(entity_id), payer_user_id=payer,
            billing_group_id=group.id, source=str(source)[:20],
        )
        db.session.add(nomination)
    else:
        leaving = billing_group(nomination.billing_group_id)
        nomination.billing_group_id = group.id
        nomination.source = str(source)[:20]
        _carry_paid_days(entity_id, leaving, group)
    db.session.commit()
    logger.info(
        "billing: entity {} is now billed on {} (payer {})",
        entity_id, payment_method_id, payer,
    )
    return group


def _carry_paid_days(entity_id, leaving, joining) -> None:
    """The days a company has already been paid for travel with it to its new card.

    A company moved between two of a payer's cards mid-cycle is the one case where the
    two dates disagree, and both directions cost real money if it is left alone:

    * THE NEW CARD HAS NO CYCLE AT ALL. ``due_renewals`` skips a NULL ``paid_through``
      outright, so the company would simply never be billed again — it keeps running,
      silently, for nothing. Seeded from the card it left, so the new one picks the cycle
      up exactly where the old one stopped.
    * THE NEW CARD IS BEHIND the days already bought. Its next renewal would charge for a
      period the old card has already collected. ``billed_through`` is the claim that
      suppresses exactly that — the same mechanism a handover uses, and honoured by the
      same ``renewals.entities_covered_into``.

    The remaining case, a new card paid FURTHER ahead than the company was, is left as
    is: the company is covered to a date its own money did not reach, which is a handful
    of free days on the payer's own account and the only alternative is billing them
    twice for the overlap.

    Never raises and never blocks the move. A card change that failed because of this
    would leave a company pointing at a card the payer did not choose, which is worse
    than a date that has to be corrected.
    """
    if leaving is None or joining is None or leaving.id == joining.id:
        return
    bought = leaving.paid_through
    if bought is None:
        return
    if bought.tzinfo is None:
        bought = bought.replace(tzinfo=timezone.utc)
    try:
        if joining.paid_through is None:
            joining.paid_through = bought
            logger.info(
                "billing: group {} takes over the cycle at {} for entity {}",
                joining.id, bought, entity_id,
            )
            return
        joined = joining.paid_through
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        if joined >= bought:
            return
        # FORWARD-ONLY, enforced in the WHERE and not trusted from here, and on
        # billing-forward rows only — a claim on a trial row is inert until it converts
        # and then silently suppresses renewals nobody chose to skip.
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.entity_id == str(entity_id),
            EntityModuleSubscription.phase.in_((PHASE_ACTIVE, PHASE_PAST_DUE)),
            db.or_(
                EntityModuleSubscription.billed_through.is_(None),
                EntityModuleSubscription.billed_through < bought,
            ),
        ).update(
            {EntityModuleSubscription.billed_through: bought},
            synchronize_session=False,
        )
        logger.info(
            "billing: entity {} carries days paid to {} onto group {}",
            entity_id, bought, joining.id,
        )
    except Exception:
        logger.exception(
            "billing: could not carry the paid days for entity {} onto group {}",
            entity_id, joining.id,
        )


def clear_nomination_for_entity(entity_id, payer_user_id) -> bool:
    """Drop one payer's nomination for a company. Returns whether a row went.

    Used by a handover: the outgoing payer's card must stop paying for a company that is
    no longer theirs, exactly as their consent stops authorising it. The GROUP is left
    alone — other companies may still be on that card, and its cycle is history either
    way.
    """
    nomination = nomination_for_entity(entity_id, payer_user_id)
    if nomination is None:
        return False
    db.session.delete(nomination)
    db.session.commit()
    return True


def entity_ids_in_group(group_id) -> set[str]:
    """Every company nominated onto this group's card."""
    if not group_id:
        return set()
    rows = (
        EntityBillingGroup.query.filter_by(billing_group_id=str(group_id))
        .with_entities(EntityBillingGroup.entity_id)
        .all()
    )
    return {str(row.entity_id) for row in rows}


def groups_with_billing() -> list[PayerBillingGroup]:
    """Groups whose payer has an anchor — i.e. a cycle exists to renew against.

    The group twin of ``accounts_with_billing``, and it still asks the ACCOUNT about the
    anchor: the cycle is per payer, so a group can only renew once its payer has one.
    """
    return (
        PayerBillingGroup.query.join(
            UserStripeCustomer,
            UserStripeCustomer.user_id == PayerBillingGroup.payer_user_id,
        )
        .filter(UserStripeCustomer.anchor_at.isnot(None))
        .order_by(PayerBillingGroup.created_at, PayerBillingGroup.id)
        .all()
    )


def groups_in_dunning() -> list[PayerBillingGroup]:
    """Cards with collection in progress, oldest failure first.

    Oldest-first so a limited run always works on the groups closest to being given up
    on — the ones where a missed attempt costs the most.
    """
    return (
        PayerBillingGroup.query.filter(
            PayerBillingGroup.dunning_started_at.isnot(None)
        )
        .order_by(PayerBillingGroup.dunning_started_at)
        .all()
    )


def set_group_paid_through(group_id, until: datetime) -> None:
    """Record what this CARD has paid for. Only ever moves FORWARD.

    Same rule and same reason as the account-level write it replaces: a late or replayed
    event carrying an older period must not claw back access already granted.
    """
    group = billing_group(group_id)
    if group is None:
        logger.warning("billing: no billing group {}", group_id)
        return
    if group.paid_through is not None and until <= group.paid_through:
        return
    group.paid_through = until
    db.session.commit()


def set_group_module_phase(
    group_id, *, from_phase: str, to_phase: str,
    skip_covered_at: datetime | None = None
) -> int:
    """Move the module rows of THIS GROUP'S companies from one phase to another.

    The containment primitive. A payer-wide phase move (every module on every card at once)
    which is the behaviour a second card exists to end: one declining card must not put a
    company paid for by a different, healthy card into the past-due grace window and then
    terminate it.

    Everything else matches its payer-wide twin — only rows already IN ``from_phase``
    move, and ``skip_covered_at`` spares rows whose ``billed_through`` reaches past that
    instant (days a handover already collected).
    """
    entity_ids = entity_ids_in_group(group_id)
    if not entity_ids:
        return 0
    group = billing_group(group_id)
    query = EntityModuleSubscription.query.filter(
        EntityModuleSubscription.entity_id.in_(sorted(entity_ids)),
        EntityModuleSubscription.phase == from_phase,
    )
    if group is not None:
        # A nomination outlives a handover as history; the rows now belong to someone
        # else and are not this card's to move.
        query = query.filter(
            EntityModuleSubscription.payer_user_id == str(group.payer_user_id)
        )
    if skip_covered_at is not None:
        query = query.filter(
            db.or_(
                EntityModuleSubscription.billed_through.is_(None),
                EntityModuleSubscription.billed_through <= skip_covered_at,
            )
        )
    moved = query.update(
        {EntityModuleSubscription.phase: to_phase}, synchronize_session=False
    )
    db.session.commit()
    if moved:
        logger.info(
            "dunning: moved {} module row(s) in group {} from {} to {}",
            moved, group_id, from_phase, to_phase,
        )
    return moved


def begin_group_dunning(group_id, failed_at: datetime) -> None:
    """Record that THIS CARD has started failing. Does NOT restart an existing run.

    The start time anchors the whole retry schedule, so a second failure arriving mid-run
    must not move it — that would extend collection indefinitely, one failure at a time,
    past the access grace window.
    """
    group = billing_group(group_id)
    if group is None:
        logger.warning("dunning: no billing group {}", group_id)
        return
    if group.dunning_started_at is None:
        group.dunning_started_at = failed_at
        group.dunning_attempts = 0
    db.session.commit()
    # The rows have to move too, or the past-due grace never applies: access is read from
    # the module phase, not from the group.
    set_group_module_phase(
        group_id,
        from_phase=PHASE_ACTIVE,
        to_phase=PHASE_PAST_DUE,
        skip_covered_at=failed_at,
    )


def record_group_dunning_attempt(group_id) -> int:
    """Count a retry that has been MADE (whatever its outcome). Returns the new total."""
    group = billing_group(group_id)
    if group is None:
        return 0
    group.dunning_attempts = int(group.dunning_attempts or 0) + 1
    db.session.commit()
    return group.dunning_attempts


def end_group_dunning(group_id, *, status: str = "active") -> None:
    """Collection resolved for this card — paid (``active``) or given up on (``closed``).

    Clears the schedule either way, so a later failure starts a fresh run rather than
    inheriting a spent attempt count. On give-up the rows are LEFT past due: the debt is
    real and unpaid, and access lapses when the grace runs out.
    """
    group = billing_group(group_id)
    if group is None:
        return
    group.dunning_started_at = None
    group.dunning_attempts = 0
    db.session.commit()
    if status == "active":
        set_group_module_phase(
            group_id, from_phase=PHASE_PAST_DUE, to_phase=PHASE_ACTIVE
        )
    logger.info("dunning: collection ended for group {} ({})", group_id, status)


def upsert_module_row(
    entity_id, function_code, payer_user_id, **fields
) -> EntityModuleSubscription:
    """Create or update the row for one entity+module, keyed on (entity, function_code).

    Only the fields in ``fields`` (restricted to ``_MODULE_MUTABLE_FIELDS``) are written,
    so a Stripe-driven sync that passes only Stripe columns leaves the app-owned trial
    fields untouched. Unknown keys raise — a typo shouldn't silently no-op.

    ONE PAYER PER ENTITY, enforced here. ``payer_user_id`` is a REQUEST — the first
    module to be paid for fixes who pays for the entity, and every later module joins
    that payer rather than opening a second billing relationship. A caller asking for a
    different payer is ignored and logged, never obeyed.

    Enforced at this choke point rather than per caller because the payer arrives as
    "the acting user" from two directions — ``checkout.start_module_trial`` and
    ``checkout._grant_purchased_modules`` — so a second admin starting a trial, or buying
    a module, on an entity someone else already pays for would silently create a second
    payer. That state is not modelled anywhere downstream: ``payer_for_entity`` takes the
    FIRST row it finds, and ``entity.services.modules.get_module_cards`` reads one payer's
    cycle and applies it to every module on the page. It was observed live — one entity
    with a paid module on one payer's cycle and a trial on another payer with no cycle at
    all, which rendered a next-invoice date and a prorated figure belonging to neither.

    The update branch is equally load-bearing: it used to reassign ``payer_user_id`` on
    EVERY write, so a second admin merely cancelling a module moved the billing
    relationship to themselves.
    """
    unknown = set(fields) - _MODULE_MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"upsert_module_row: unknown field(s) {sorted(unknown)}")

    code = str(function_code).upper()
    row = module_row(entity_id, code)

    # The entity's established payer, if it has one. Read from a SIBLING module where
    # possible: on an update this row's own payer is the answer anyway, and on a create
    # it is the sibling that carries the entity's existing relationship.
    established = payer_for_entity(entity_id)
    if established and payer_user_id and str(payer_user_id) != str(established):
        logger.warning(
            "store: entity {} already bills to payer {}; ignoring the request to set "
            "{} as the payer for {} (one payer per entity)",
            entity_id,
            established,
            payer_user_id,
            code,
        )
    effective_payer = established or payer_user_id

    if row is None:
        row = EntityModuleSubscription(
            id=_uuid(),
            entity_id=str(entity_id),
            function_code=code,
            payer_user_id=str(effective_payer),
            phase=fields.pop("phase"),  # required on create
        )
        for key, value in fields.items():
            setattr(row, key, value)
        db.session.add(row)
    else:
        row.payer_user_id = str(effective_payer)
        for key, value in fields.items():
            setattr(row, key, value)
    db.session.commit()
    return row


def transfer_entity_payer(entity_id, new_payer_user_id, *, billed_through=None) -> int:
    """Move EVERY module row of one entity to a new payer, in ONE statement.

    The deliberate exception to one-payer-per-entity, and the reason it is a separate
    function rather than a flag on ``upsert_module_row``: that function IGNORES a payer
    change and only logs it, and the comment above explains what re-opening that path
    would cost — a second admin cancelling a module used to take the billing relationship
    with them. A transfer is a different act, authorised on both sides, and it says so by
    having its own name.

    ONE UPDATE, not a loop. A row-by-row rewrite is order-dependent: ``payer_for_entity``
    answers from an unordered ``.first()``, so a partial flip makes the entity's payer
    nondeterministic — and every later ``upsert_module_row`` on that entity would then
    re-spread whichever payer happened to be read back.

    ``billed_through`` records the days the OLD payer already paid for, or that were
    bought at accept. Forward-only: it is written only where it would move the value
    later, so a second transfer of an entity can never shorten a claim the first one
    established. Never set back to NULL.

    The two columns move on DIFFERENT ROW SETS, which is the subtle part. The payer moves
    on every row — a dead row is still a row about this entity and must follow it. The
    claim moves only on rows that were actually being billed, because that is the only
    place the statement it makes is true. See the comment on the second UPDATE.

    Returns the number of rows moved. Does NOT commit — the caller owns the transaction,
    because the flip, the consent row and the audit entries have to land together or not
    at all.
    """
    if not entity_id or not new_payer_user_id:
        raise ValueError("transfer_entity_payer needs an entity and a new payer")

    if billed_through is not None and billed_through.tzinfo is None:
        raise ValueError("billed_through must be timezone-aware")

    # TWO statements, each doing one thing, because the two columns have different rules:
    # the payer moves on every row unconditionally, the claim only ever moves FORWARD.
    # Folding them into one UPDATE and then patching up the rows the forward-only filter
    # skipped double-counts — after the first pass those rows satisfy the second pass's
    # ``>=`` test too, and ``moved`` is what tells the caller the flip actually happened.
    moved = EntityModuleSubscription.query.filter(
        EntityModuleSubscription.entity_id == str(entity_id)
    ).update(
        {EntityModuleSubscription.payer_user_id: str(new_payer_user_id)},
        synchronize_session=False,
    )

    if billed_through is not None:
        # BILLING-FORWARD ROWS ONLY, and this is a money rule rather than an optimisation.
        #
        # The claim means "someone else's money already covers these days". That is only
        # ever true of a row that was being billed. A trial was free, and an expired or
        # cancelled row is not being billed at all — stamping them says something false.
        #
        # On a trial row it is worse than untidy. It looks inert, because
        # ``renewals._covered_entities`` skips anything not billing forward — but the
        # trial converts, ``_finish_conversion`` writes ``phase=active``, and the claim
        # silently becomes live. The new payer's renewals for that entity are then
        # suppressed for every period the claim covers: free months, from a date nobody
        # chose, with no invoice to notice the absence of. And it cannot be undone —
        # ``billed_through`` is deliberately outside ``_MODULE_MUTABLE_FIELDS``, so no
        # ordinary writer can clear it.
        #
        # Forward-only is enforced in the WHERE rather than trusted from the caller, so a
        # row already covered further out keeps its own, longer claim.
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.entity_id == str(entity_id),
            EntityModuleSubscription.phase.in_((PHASE_ACTIVE, PHASE_PAST_DUE)),
            db.or_(
                EntityModuleSubscription.billed_through.is_(None),
                EntityModuleSubscription.billed_through < billed_through,
            ),
        ).update(
            {EntityModuleSubscription.billed_through: billed_through},
            synchronize_session=False,
        )

    logger.info(
        "store: transferred {} module row(s) of entity {} to payer {} (billed_through={})",
        moved, entity_id, new_payer_user_id, billed_through,
    )
    return moved


def payer_is_dunning(user_id) -> bool:
    """Whether collection is currently failing for this payer.

    The single-user form of ``groups_in_dunning``, and it reads the same place: ANY of the
    payer's cards being in collection makes the payer so. It previously read
    ``user_stripe_customer.dunning_started_at``, which nothing has written since the
    per-card cutover -- so it answered False for a payer genuinely mid-collection and let
    a handover through with the debt still outstanding.

    A transfer is refused while either side is in it: the outgoing payer because the debt
    is theirs and splitting it in half leaves it uncollectable, the incoming payer because
    they are in no state to take on another bill.
    """
    if not user_id:
        return False
    return any(
        group.dunning_started_at is not None
        for group in billing_groups_for_payer(user_id)
    )


def rows_for_entity(entity_id) -> list[EntityModuleSubscription]:
    """Every module row of one entity, whatever its phase or payer."""
    if not entity_id:
        return []
    return EntityModuleSubscription.query.filter_by(entity_id=str(entity_id)).all()


def entities_paid_for_by(user_id) -> list[tuple[str, str]]:
    """``(entity_id, name)`` for every entity whose bill this user currently carries.

    Answers "may this person leave / deactivate?" — the question the membership-level
    payer guard asks about one entity, asked across all of them. Named rather than
    counted because a refusal that lists the companies is actionable and a bare "you
    still pay for something" is not.

    Phase-blind on purpose: a cancelled or past-due row still names a payer, and a payer
    with an unsettled row is exactly the one who must not vanish.
    """
    if not user_id:
        return []
    rows = EntityModuleSubscription.query.filter_by(
        payer_user_id=str(user_id)
    ).with_entities(EntityModuleSubscription.entity_id).all()
    ids = {str(entity_id) for (entity_id,) in rows}
    if not ids:
        return []

    # Lazy, like ``renewals._entity_names`` — the subscription store must not pull the
    # entity model graph in at import time.
    from models.db import Entity

    named = {
        str(e.id): (e.name or "").strip() or str(e.id)
        for e in Entity.query.filter(Entity.id.in_(list(ids))).all()
    }
    # An entity row that has gone missing still counts — it is the SUBSCRIPTION that
    # strands, and dropping it here would let the payer slip out through a broken FK.
    return sorted((eid, named.get(eid, eid)) for eid in ids)


def due_trials(now, limit: int | None = None) -> list[EntityModuleSubscription]:
    """App-level trials whose ``trial_end`` has passed and that still need closing out.

    The work list for the trial-end job: each of these either converts to a paid
    subscription (payer has a card AND authorised this entity) or expires. Ordered
    oldest-first so a limited run always drains the most overdue.

    Includes CANCELLED trials (``scheduled_cancel``), not just running ones. Cancelling
    a trial doesn't end it — it keeps its free days and simply won't convert — so the
    row still has to be closed out at ``trial_end``, just always down the expire branch
    (``checkout._convert_due_trials`` refuses to convert it). Leaving them out would
    strand the row in ``scheduled_cancel`` with access lapsing only whenever the daily
    sweep next ran.

    The ``first_billed_at IS NULL`` guard applies ONLY to the cancelled branch, and must
    not be applied to ``trial``: a running trial has never been billed either, so it
    would match, and the guard is about telling a cancelled TRIAL from a cancelled PAID
    module — a distinction that only matters once something is cancelled.

    On the cancelled branch it is load-bearing. ``scheduled_cancel`` is also the phase of
    a cancelled PAID module, and one that had once been a trial still carries a past
    ``trial_end``, so nothing about the dates separates them. Expiring a paid one here
    revokes access they paid an extension for.

    This guard used to read the Stripe subscription item id, which only the Stripe
    biller ever set. Billing in-house it was NULL on every row, so cancelled PAID
    modules were swept in and expired — precisely the harm the guard exists to prevent.

    It also closes a gap the old guard had: a cancelled TRIAL on an entity with a paid
    sibling carried that sibling's item id (an entity had ONE line, shared by both
    module rows) and was wrongly skipped. A trial has no ``first_billed_at`` whatever
    its siblings are doing.
    """
    query = (
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.trial_end.isnot(None),
            EntityModuleSubscription.trial_end <= now,
            or_(
                EntityModuleSubscription.phase == PHASE_TRIAL,
                and_(
                    EntityModuleSubscription.phase == PHASE_SCHEDULED_CANCEL,
                    EntityModuleSubscription.first_billed_at.is_(None),
                ),
            ),
        )
        .order_by(EntityModuleSubscription.trial_end)
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def trials_ending_between(start, end, limit: int | None = None
                          ) -> list[EntityModuleSubscription]:
    """Running trials whose ``trial_end`` falls in ``[start, end)``.

    The work list for the trial-ending WARNING, which is the one notification that can
    prevent a lapse rather than report one. ``due_trials`` is the mirror of this and runs
    at the other end: this looks forward at trials still running, that one looks back at
    trials already over.

    ``PHASE_TRIAL`` only — unlike ``due_trials``, which deliberately also sweeps up
    cancelled trials so their rows get closed out. A cancelled trial is not going to
    convert, and the customer is the one who cancelled it; warning them that the thing
    they asked to end is about to end is noise, not a service.

    Half-open on purpose, matching ``Period``: consecutive daily windows tile without
    overlap, so a trial sitting exactly on a boundary is warned about once rather than on
    two consecutive days.
    """
    query = (
        EntityModuleSubscription.query.filter(
            EntityModuleSubscription.trial_end.isnot(None),
            EntityModuleSubscription.trial_end >= start,
            EntityModuleSubscription.trial_end < end,
            EntityModuleSubscription.phase == PHASE_TRIAL,
        )
        .order_by(EntityModuleSubscription.trial_end)
    )
    if limit:
        query = query.limit(limit)
    return query.all()


# --- Audit log (append-only) -------------------------------------------------


def record_action(
    *,
    entity_id,
    function_code,
    payer_user_id,
    action,
    outcome,
    actor_user_id=None,
    phase_before=None,
    phase_after=None,
    app_access_until=None,
    extension_amount=None,
    extension_state=None,
    cancel_reason=None,
    note=None,
    payer_before=None,
    payer_after=None,
) -> SubscriptionAuditLog:
    """Append an immutable cancel/uncancel/transfer record. ``extension_amount`` is frozen
    here (the mirror deliberately doesn't store it).

    ``cancel_reason`` is the customer's own text from the cancellation dialog. It is
    kept here rather than on the module row because it is history: every cancellation
    keeps its own, where a column on the row would hold only the most recent one.

    ``payer_before`` / ``payer_after`` are set only by the transfer family of actions,
    which are the first ones here with two parties. ``payer_user_id`` keeps its existing
    meaning throughout — the payer at the time of the action, so on a transfer it is the
    OUTGOING one, matching every other row's "whose bill was this".

    A transfer writes ONE ROW PER MODULE CODE of the entity, because ``function_code`` is
    NOT NULL and the payer lives on every row. That is deliberate rather than a
    workaround: it makes "what happened to this module" answerable the same way for a
    handover as for a cancellation."""
    entry = SubscriptionAuditLog(
        id=_uuid(),
        entity_id=str(entity_id),
        function_code=str(function_code).upper(),
        payer_user_id=str(payer_user_id),
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        payer_before=str(payer_before) if payer_before else None,
        payer_after=str(payer_after) if payer_after else None,
        action=action,
        outcome=outcome,
        phase_before=phase_before,
        phase_after=phase_after,
        app_access_until=app_access_until,
        extension_amount=extension_amount,
        extension_state=extension_state,
        cancel_reason=cancel_reason,
        note=note,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


# --- Local invoice record ----------------------------------------------------
#
# Minty's own copy of what it billed. Written by ``billing_gateway.issue_invoice``,
# read by ``renewals.run_renewals`` as the double-billing guard — which is the point of
# the whole table: a UNIQUE index turns "we searched Stripe and didn't find one" into
# "the database will not let us".


def _fits(value, limit: int) -> str | None:
    """``value`` trimmed to what the column will hold.

    A snapshot that is 3 characters too long must not be the thing that stops a charge:
    on a keyed invoice the reservation fails closed, so an over-long entity name would
    turn a naming quirk into an unbillable renewal. Truncating loses the tail of a label;
    raising loses the payment.
    """
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def invoice_for_key(idempotency_key) -> SubscriptionInvoice | None:
    """The invoice raised under ``idempotency_key``, or None if the key is unclaimed.

    Replaces a LIST of the customer's Stripe invoices plus a metadata scan, run once per
    payer per renewal, with one indexed lookup.
    """
    if not idempotency_key:
        return None
    return SubscriptionInvoice.query.filter_by(
        idempotency_key=str(idempotency_key)
    ).one_or_none()


def invoice_for_external_id(external_id) -> SubscriptionInvoice | None:
    """The local record of a processor invoice, or None if it was raised elsewhere.

    None is an ordinary answer, not an error: invoices predating these tables have no
    local row, and neither does one raised straight from the Stripe dashboard.
    """
    if not external_id:
        return None
    return (
        SubscriptionInvoice.query.filter_by(external_id=str(external_id))
        .order_by(SubscriptionInvoice.created_at.desc())
        .first()
    )


def open_invoices_for_group(group_id) -> list[SubscriptionInvoice]:
    """This card's invoices whose LOCAL row still reads "open" - the rows to re-read when
    the processor says nothing is open, because each was then settled somewhere this code
    cannot see (there is no webhook) and would go on showing as failed."""
    if not group_id:
        return []
    return (
        SubscriptionInvoice.query.filter(
            SubscriptionInvoice.billing_group_id == str(group_id),
            SubscriptionInvoice.status == "open",
            SubscriptionInvoice.external_id.isnot(None),
            SubscriptionInvoice.external_id != "",
        )
        .order_by(SubscriptionInvoice.created_at)
        .all()
    )


def reserve_invoice(
    *,
    payer_user_id,
    stripe_customer_id,
    period,
    currency,
    lines,
    memo=None,
    idempotency_key=None,
    billing_group_id=None,
) -> SubscriptionInvoice | None:
    """Claim ``idempotency_key`` and record what is ABOUT to be sent. None if taken.

    Written BEFORE the processor is called, not after, and that ordering is the entire
    guard. Recording afterwards leaves a window — charge succeeds, runner dies, nothing
    on disk — in which the next run sees no record and bills the period again. That is
    the exact failure the Stripe metadata scan existed to cover, so a record-after write
    would have been a regression dressed as a feature.

    The cost of reserving first is the opposite window: a row whose ``external_id`` is
    still NULL because we never heard back. That case is RECOVERABLE and ambiguous only
    to us, not to the customer — see ``renewals.run_renewals``, which resolves it against
    the processor rather than guessing.

    Returns None when the key is already claimed: someone else is issuing, or has issued,
    this exact invoice. The caller must not charge.
    """
    record = SubscriptionInvoice(
        id=_uuid(),
        payer_user_id=str(payer_user_id),
        stripe_customer_id=str(stripe_customer_id) if stripe_customer_id else None,
        external_id=None,
        period_start=period.start,
        period_end=period.end,
        # Stored UPPER to match currency_info.currency_code, the ISO registry these
        # rows are meant to reference. Only the stored copy is normalised: the same
        # value goes to stripe.Invoice.create in billing_gateway, and Stripe's own
        # currency is lowercase, so the outbound path is left exactly as it was.
        currency=(currency or "").upper(),
        total=sum(int(line.amount) for line in lines),
        status="draft",
        memo=_fits(memo, 500),
        idempotency_key=str(idempotency_key) if idempotency_key else None,
        # WHICH CARD this document belongs to. A payer now has one invoice per group per
        # period, so "the payer's invoice for this period" is no longer a question with
        # one answer — dunning has to chase the right one.
        billing_group_id=str(billing_group_id) if billing_group_id else None,
    )
    for line in lines:
        record.lines.append(
            SubscriptionInvoiceLine(
                id=_uuid(),
                entity_id=str(line.entity_id),
                entity_name=_fits(line.entity_name, 255),
                product_name=_fits(line.product_name, 255),
                amount=int(line.amount),
                kind=line.kind,
                at=line.at,
                # What the line paid for, as whatever priced it said (``billing.Line``).
                period_start=line.period_start,
                period_end=line.period_end,
                unit_amount=line.unit_amount,
            )
        )
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        # The unique index did its job. Roll back so the session is usable — a poisoned
        # session would take down whatever else this request still has to do.
        db.session.rollback()
        logger.warning(
            "invoice: {} is already claimed; not issuing a second invoice for it",
            idempotency_key,
        )
        return None
    return record


def settle_invoice(
    invoice_id,
    *,
    external_id=None,
    status=None,
    total=None,
    issued_at=None,
    paid_at=None,
    payment_method=None,
    hosted_invoice_url=None,
) -> SubscriptionInvoice | None:
    """Fill in what the processor said, once it has said it.

    Only the fields passed are touched: a settle that knows the status but not the paid
    time must not blank a paid time already recorded. That matters more for the three
    display fields than for the rest — ``issue_invoice`` settles up to four times as an
    invoice moves draft -> open -> paid, and the early calls know none of them.
    """
    record = db.session.get(SubscriptionInvoice, str(invoice_id))
    if record is None:
        logger.error("invoice: no local record {} to settle", invoice_id)
        return None
    if external_id is not None:
        record.external_id = str(external_id)
    if status is not None:
        record.status = str(status)
    if total is not None:
        record.total = int(total)
    if issued_at is not None:
        record.issued_at = issued_at
    if paid_at is not None:
        record.paid_at = paid_at
    if payment_method is not None:
        record.payment_method = _fits(payment_method, 100)
    if hosted_invoice_url is not None:
        record.hosted_invoice_url = _fits(hosted_invoice_url, 500)
    db.session.commit()
    return record


def discard_invoice(invoice_id) -> None:
    """Drop a reservation whose invoice was never created.

    Only safe when the processor is KNOWN not to have been reached — otherwise the key
    has to stay claimed, because the alternative is billing the period twice.
    """
    record = db.session.get(SubscriptionInvoice, str(invoice_id))
    if record is None:
        return
    db.session.delete(record)
    db.session.commit()


# --- re-issuing an invoice the processor will no longer collect -----------------------------
#
# Stripe cancels an invoice's PaymentIntent once it has been confirmed too many times ("a
# variable upper limit" - ten declines in our account), and a cancelled one can never be paid
# again: every later attempt, scheduled or pressed, is refused. ``billing_gateway.
# refresh_invoice`` re-issues it as an identical replacement; these are the rows' half of that.


def refresh_key(external_id) -> str:
    """The claim - locally, and at the processor as its idempotency key - of the replacement
    for ``external_id``.

    Derived from the DEAD invoice, so every attempt at the same refresh (a crash resumed, the
    scheduled run racing a button) claims the same key and at most one replacement can exist.
    """
    return f"refresh-{external_id}"


def retired_key(key, external_id) -> str:
    """The key a replaced invoice keeps once its own has moved to the replacement.

    ``~``, not ``-``: ``dunning._names_period`` reads ``<key>-...`` as the SAME period (a replay
    scopes its keys that way), so a retired key joined with a dash would go on claiming the
    period it has handed over. Still unique, and still says which period it was.
    """
    return f"{key}~{external_id}"


def invoice_lines(invoice_id) -> list[SubscriptionInvoiceLine]:
    """The lines recorded for one invoice - what it was actually sent with."""
    return (
        SubscriptionInvoiceLine.query.filter_by(invoice_id=str(invoice_id))
        .order_by(SubscriptionInvoiceLine.created_at, SubscriptionInvoiceLine.id)
        .all()
    )


def replacement_of(record) -> SubscriptionInvoice | None:
    """The invoice that replaced ``record``, or None if it has not been re-issued.

    Two ways to find it, depending on how far the refresh got. Before the key moves, the
    replacement still holds its own claim (``refresh_key``). After, ``record`` holds a
    ``retired_key`` and the key it gave up names whatever is live NOW - which, after a second
    refresh, is the replacement's own replacement, the one that can still be paid.
    """
    external_id = getattr(record, "external_id", None)
    if not external_id:
        return None
    key = record.idempotency_key or ""
    suffix = f"~{external_id}"
    if key.endswith(suffix):
        return invoice_for_key(key[: -len(suffix)])
    return invoice_for_key(refresh_key(external_id))


def supersede_invoice(dead_id, replacement_id) -> None:
    """Hand a dead invoice's key to its replacement, and mark the dead one void. One transaction.

    The key is what every reader asks by - the renewal run's "is this period invoiced?", the
    invoice list's Retry button - so it has to name the document that can still be paid. It
    is RELEASED before it is re-claimed, in two ordered writes, because ``idempotency_key`` is
    unique: the other order collides with itself. Written as two explicit UPDATEs rather than
    attribute changes, because the unit of work flushes dirty rows in an order of its own.

    A dead invoice with no key (a charge raised without one) is only marked void; its
    replacement keeps its ``refresh_key``, which is how ``replacement_of`` finds it. Safe to run
    twice: a key already retired is left where it is.
    """
    try:
        rows = {
            str(row.id): row
            for row in SubscriptionInvoice.query.filter(
                SubscriptionInvoice.id.in_([str(dead_id), str(replacement_id)])
            ).with_for_update().all()
        }
        dead = rows.get(str(dead_id))
        replacement = rows.get(str(replacement_id))
        if dead is None or replacement is None:
            raise ValueError(f"no invoice rows {dead_id} / {replacement_id} to supersede")
        if not replacement.external_id:
            raise ValueError(f"replacement {replacement_id} has no processor invoice yet")
        key = dead.idempotency_key
        moving = bool(key) and not key.endswith(f"~{dead.external_id}")
        if moving:
            SubscriptionInvoice.query.filter_by(id=str(dead.id)).update(
                {"idempotency_key": retired_key(key, dead.external_id), "status": "void"},
                synchronize_session=False,
            )
            SubscriptionInvoice.query.filter_by(id=str(replacement.id)).update(
                {"idempotency_key": key}, synchronize_session=False
            )
        else:
            SubscriptionInvoice.query.filter_by(id=str(dead.id)).update(
                {"status": "void"}, synchronize_session=False
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    # The UPDATEs bypassed the objects loaded above; make them re-read.
    db.session.expire_all()
