"""Collect a ``billing.Invoice`` through a payment processor.

The ONLY Stripe-aware part of in-house billing, and deliberately thin: it takes lines
that are already priced and described, and does nothing but present and charge them.
Swapping processor should mean rewriting this file and nothing in ``billing``.

Why invoice ITEMS rather than subscription items — the whole reason billing moved here:

    a subscription line's description is composed by Stripe from the PRODUCT name and
    cannot be changed, through any endpoint:
        POST /v1/invoices/{inv}/lines/{line} -> 400 You may only update `tax_rates`,
                                               `tax_amounts`, or `discounts` for a
                                               subscription typed line item.

    an invoice ITEM carries whatever description it is given.

So a payer with two entities on the same bundle sees two lines naming their entities,
instead of two identical "1 x Super Minty 400.00" lines that no one can tell apart.

The subscription is NOT the biller here. If one still exists it is only a payment
instrument and a cycle marker; every amount and every period on the invoice came from
``billing``.

It does one thing besides talk to Stripe: every invoice it sends is RECORDED locally
first, in ``subscription_invoice``. That is not bookkeeping tacked onto the wrong layer —
this is the only place that knows what was actually sent (zero-amount lines are dropped
here) and the only place with a before-and-after around the charge, which is what a
double-billing guard has to have. The write goes through ``store``, so the processor and
the persistence stay separable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from blueprints.subscription.services.billing import Invoice
from blueprints.subscription.services.stripe_client import get_stripe


class BillingError(Exception):
    """Collection failed. Carries a customer-safe message where Stripe gave one."""

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message


def find_invoice_by_metadata(customer_id: str, key: str, value: str) -> dict | None:
    """An existing invoice for this customer carrying ``metadata[key] == value``.

    NO LONGER the routine double-billing guard. That is now the UNIQUE index on
    ``subscription_invoice.idempotency_key``, claimed before the charge (see
    ``issue_invoice``) and read by ``renewals.run_renewals`` in one indexed lookup — this
    used to LIST a customer's invoices and scan them, once per payer per renewal.

    It survives for the one case a local row cannot answer: a reservation whose
    ``external_id`` is still NULL, meaning we claimed the key and then never heard back.
    Only the processor knows whether that invoice exists, and metadata is how to ask —
    Stripe expires idempotency keys after 24 hours, metadata never.

    Still the guard for ``changes.issue_change``, which has not been moved over.
    """
    # ``auto_paging_iter``, not the first page: ``limit`` is a PAGE SIZE, so a bare
    # list() stops at 100 and quietly reports "no such invoice" for a long-lived payer —
    # which here means re-issuing an invoice that already exists.
    listing = get_stripe().Invoice.list(customer=customer_id, limit=100)
    for candidate in listing.auto_paging_iter():
        if (candidate.get("metadata") or {}).get(key) == value:
            return candidate
    return None


def _reserve(customer_id, invoice: Invoice, lines, memo, idempotency_key,
             payer_user_id):
    """Claim the key and record what is about to be sent. See ``issue_invoice``.

    Returns the local row, or None if there is none to update — either because it could
    not be written (no key, so record-keeping only) or because there was no payer to
    attribute it to. Raises when a KEYED invoice cannot be reserved: that is the guard
    refusing to let the same period be charged twice, and it has to fail closed.
    """
    from blueprints.subscription.services import store

    try:
        payer = payer_user_id or store.user_for_customer(customer_id)
        if not payer:
            # Nothing to attribute the row to. An unmapped customer is a real problem,
            # but it is not one to discover by refusing a charge the payer is waiting on.
            raise ValueError(f"no payer mapped to customer {customer_id}")
        record = store.reserve_invoice(
            payer_user_id=payer,
            stripe_customer_id=customer_id,
            period=invoice.period,
            currency=invoice.currency,
            lines=lines,
            memo=memo,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        if idempotency_key:
            logger.exception(
                "billing: could not reserve {} for customer {}; refusing to charge "
                "without the guard", idempotency_key, customer_id,
            )
            raise BillingError(
                f"could not reserve invoice {idempotency_key} for {customer_id}"
            ) from exc
        logger.exception(
            "billing: could not record the invoice for customer {}; charging anyway "
            "because nothing about this guards the customer", customer_id,
        )
        return None

    if record is None and idempotency_key:
        # The unique index refused it: this period is already being, or has been,
        # invoiced. Charging now is the exact double-bill the table exists to prevent.
        raise BillingError(
            f"invoice {idempotency_key} is already claimed for {customer_id}"
        )
    return record


def _settle(record, **fields) -> None:
    """Update the local row, never at the expense of the charge.

    Called after money may already have moved, so a failure here is logged and swallowed:
    losing the record of a payment is bad, but raising would turn a collected payment
    into an exception the caller reads as "it failed" — and that is how a customer gets
    charged a second time.
    """
    if record is None:
        return
    from blueprints.subscription.services import store

    try:
        store.settle_invoice(record.id, **fields)
    except Exception:
        logger.exception(
            "billing: charged, but could not update local invoice record {}", record.id
        )


def _local(external_id):
    """The local row for a processor invoice, or None — never a reason to fail.

    An invoice raised before these tables existed, or straight from the Stripe dashboard,
    has no local row. Collecting it must still work.
    """
    from blueprints.subscription.services import store

    try:
        return store.invoice_for_external_id(external_id)
    except Exception:
        logger.exception("billing: could not look up local record for {}", external_id)
        return None


def _moment(timestamp) -> datetime | None:
    """A Stripe unix timestamp as an aware UTC datetime, or None.

    Stripe's own times are used rather than the local clock so the recorded moments line
    up with the invoice they describe — which is also what keeps test-clock runs
    readable, where "now" and the billed period are years apart.
    """
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _record_of(result: dict) -> dict:
    """The settle fields describing ``result`` — status, total and when it moved."""
    transitions = result.get("status_transitions") or {}
    return {
        "status": result.get("status") or "draft",
        "total": result.get("total"),
        "issued_at": _moment(transitions.get("finalized_at") or result.get("created")),
        "paid_at": _moment(transitions.get("paid_at")),
    }


def issue_invoice(customer_id: str, invoice: Invoice, *, memo: str | None = None,
                  collect: bool = True, metadata: dict[str, str] | None = None,
                  idempotency_key: str | None = None,
                  payer_user_id: str | None = None) -> dict:
    """Create, finalize and (by default) charge ``invoice`` for ``customer_id``.

    The order matters. The invoice is created FIRST and each item attached to it by id,
    rather than letting items sit pending and be swept up later: a pending item lands on
    whatever invoice Stripe next generates, which is fine for a cancel extension riding
    an anchor but wrong here, where these lines are the invoice.

    ``pending_invoice_items_behavior="exclude"`` keeps unrelated pending items — a queued
    extension, say — off this one for the same reason.

    Zero-amount lines are skipped: Stripe rejects them, and a 0.00 line says nothing a
    customer needs. A wholly empty invoice is not created at all.

    Pass ``collect=False`` to leave it as a DRAFT for inspection — useful while the
    subscription path is still the one actually billing.

    EVERY invoice sent from here is also recorded locally, and the local row is written
    BEFORE the processor is called. Two different things depend on that ordering:

    * with an ``idempotency_key``, the write is the double-billing GUARD — a unique
      index, so a second attempt at the same period cannot even reach Stripe. If the key
      is already claimed this refuses to charge, which is the whole point;
    * without one (a mid-period purchase, guarded by the user waiting for the response),
      it is only a record, and a failure to write it must never cost the customer their
      purchase. So that case is logged and the charge proceeds.

    Recording only what came BACK would leave the window this table exists to close:
    charge succeeds, runner dies, nothing on disk, next run bills the period again.
    """
    lines = [line for line in invoice.lines if line.amount]
    if not lines:
        logger.info("billing: nothing to invoice for customer {}", customer_id)
        return {}

    record = _reserve(customer_id, invoice, lines, memo, idempotency_key, payer_user_id)

    stripe = get_stripe()
    try:
        options = {"idempotency_key": idempotency_key} if idempotency_key else {}
        draft = stripe.Invoice.create(
            customer=customer_id,
            currency=invoice.currency,
            auto_advance=False,
            collection_method="charge_automatically",
            pending_invoice_items_behavior="exclude",
            description=memo,
            metadata=metadata or {},
            **options,
        )
        # Stamped the moment Stripe acknowledges the invoice exists, so the "we claimed
        # the key but never heard back" window is exactly the create call and nothing
        # more. Everything after this point is recoverable by id.
        _settle(record, external_id=draft.get("id"), status=draft.get("status"))
        # Created in REVERSE, because Stripe renders invoice items newest-first: items
        # made in order come out backwards, which puts a swap's charge above the credit
        # that explains it. Cosmetic only -- order never changes what is owed -- and the
        # newest-first behaviour is observed rather than documented, so the worst case if
        # it ever changes is that lines read in the other order again.
        for line in reversed(lines):
            stripe.InvoiceItem.create(
                customer=customer_id,
                invoice=draft["id"],
                currency=invoice.currency,
                amount=line.amount,
                description=line.description,
                # The entity travels ON the line. Stripe stamps a subscription's metadata
                # onto every line it owns, which names one entity for all of them; this
                # is written per item and stays correct.
                metadata={"entity_id": line.entity_id},
                period={
                    "start": int(invoice.period.start.timestamp()),
                    "end": int(invoice.period.end.timestamp()),
                },
            )
        if not collect:
            held = stripe.Invoice.retrieve(draft["id"])
            _settle(record, **_record_of(held))
            return held

        finalized = stripe.Invoice.finalize_invoice(draft["id"])
        # Recorded BEFORE the payment attempt, because a decline raises: without this the
        # local row would still say "draft" for an invoice that is really open and owed,
        # and dunning chases what is open.
        _settle(record, **_record_of(finalized))
        # A finalized invoice with charge_automatically is normally collected by Stripe,
        # but not synchronously — pay() makes the outcome available now, so a decline
        # surfaces to the caller instead of arriving by webhook later.
        if finalized.get("status") == "open":
            finalized = stripe.Invoice.pay(draft["id"])
            _settle(record, **_record_of(finalized))
        return finalized
    except Exception as exc:
        logger.exception(
            "billing: could not issue invoice for customer {} ({} line(s), total {})",
            customer_id, len(lines), invoice.total,
        )
        raise BillingError(
            f"could not issue invoice for {customer_id}",
            user_message=getattr(exc, "user_message", None),
        ) from exc


def retry_invoice(invoice_id: str) -> tuple[bool, str | None]:
    """Attempt payment on an already-finalized invoice. Returns ``(paid, reason)``.

    Used by the dunning run. Returns rather than raises because a decline is the EXPECTED
    outcome here, not an error — a failed retry is data the schedule acts on, and raising
    would make the caller treat "the card was declined" the same as "the processor is
    down", which need opposite responses.

    An invoice that is already paid returns ``(True, None)``: someone may have paid it
    out of band between the attempt being scheduled and it running.

    Whatever the outcome, the local record is brought up to date. A recovered invoice
    that still reads "open" months later would make the table lie about the one thing it
    is for — a declined renewal is precisely the case someone asks "was I charged?" of.
    """
    stripe = get_stripe()
    try:
        invoice = stripe.Invoice.retrieve(invoice_id)
        if invoice.get("status") == "paid":
            _settle(_local(invoice_id), **_record_of(invoice))
            return True, None
        paid = stripe.Invoice.pay(invoice_id)
        _settle(_local(invoice_id), **_record_of(paid))
        return paid.get("status") == "paid", None
    except Exception as exc:
        reason = getattr(exc, "user_message", None) or str(exc)
        logger.info("dunning: retry of invoice {} failed: {}", invoice_id, reason)
        return False, reason


def open_invoices(customer_id: str) -> list[dict]:
    """The customer's finalized-but-unpaid invoices, oldest first — what dunning chases.

    Pages in full. ``limit`` is Stripe's PAGE SIZE, not a cap, and reading only the first
    page truncated silently in the worst possible direction: dunning chases
    ``invoices[0]``, the OLDEST open invoice, so a payer with more than a page of history
    could have their genuine oldest debt fall outside the window entirely. Worse, an
    empty first page reads as "settled elsewhere" and ends dunning as recovered — see
    the no-invoices branch in ``dunning.collect_due``.
    """
    listing = get_stripe().Invoice.list(customer=customer_id, status="open", limit=100)
    return sorted(listing.auto_paging_iter(), key=lambda i: i.get("created") or 0)


def void_invoice(invoice_id: str) -> None:
    """Void a finalized invoice, or delete it if still a draft.

    Finalized invoices cannot be deleted — only voided — and neither their lines nor
    their memo can be edited afterwards. So anything needing correction has to be caught
    while it is still a draft.
    """
    stripe = get_stripe()
    invoice = stripe.Invoice.retrieve(invoice_id)
    if invoice.get("status") == "draft":
        stripe.Invoice.delete(invoice_id)
    else:
        stripe.Invoice.void_invoice(invoice_id)
