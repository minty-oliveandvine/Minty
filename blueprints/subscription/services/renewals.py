"""Build a payer's next invoice from Minty's own records.

PHASE 5, first slice. This is what replaces the Stripe subscription: instead of Stripe
deciding what a payer owes each period, the amount is assembled here from the module
rows and the in-house plan catalog, and handed to ``billing_gateway`` to collect.

Nothing here charges anyone. ``build_renewal`` is a pure-ish read: rows and catalog in,
a ``billing.Invoice`` out. Issuing it is a separate, deliberate call — which keeps this
safe to run in shadow against live data and diff against what Stripe actually billed.

TWO RULES THAT DECIDE THE AMOUNT, both already proven elsewhere:

* one line per ENTITY, priced by the SET of modules it bills. Two modules on one entity
  are the bundle price, not the sum — the bundle IS the discount, so summing standalone
  prices would overcharge. ``billing_plan`` is keyed by the code set for exactly this.
* only modules that will actually be charged again count
  (``access.is_billing_forward``). A trial is free, and a cancelling module is winding
  down; billing either would charge for something the customer was told was not coming.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger

from blueprints.subscription.services import access, store
from blueprints.subscription.services.billing import (
    Invoice,
    Line,
    Period,
    period_containing,
    renewal_invoice,
    renewal_memo,
)


def _entity_names(entity_ids) -> dict[str, str]:
    """{entity_id: name} in one query — the invoice needs a name per line."""
    if not entity_ids:
        return {}
    from models.db import Entity

    rows = Entity.query.filter(Entity.id.in_(list(entity_ids))).all()
    return {str(e.id): (e.name or "").strip() or str(e.id) for e in rows}


def billable_codes_by_entity(user_id) -> dict[str, set[str]]:
    """{entity_id: {module codes}} this payer will be charged for next period."""
    by_entity: dict[str, set[str]] = {}
    for row in store.module_rows_for_payer(user_id):
        if not access.is_billing_forward(phase=row.phase):
            continue
        by_entity.setdefault(str(row.entity_id), set()).add(
            row.function_code.upper()
        )
    return by_entity


def build_renewal(user_id, period: Period) -> Invoice | None:
    """What this payer owes for ``period``, or None if they owe nothing.

    Returns None rather than an empty invoice: a payer whose modules have all lapsed or
    gone to trial has nothing to collect, and issuing a zero invoice would put a
    meaningless document in front of them every month.

    A combination the catalog cannot price is SKIPPED and logged, never guessed at. The
    alternative — falling back to a sum of standalone prices — silently overcharges by
    the bundle discount, which is the kind of error nobody notices until a customer does.
    """
    # NOT an early return on "nothing renewing": a payer whose last entity was
    # cancelled has no billable modules but may still owe a cancel-extension, and
    # bailing here would give those days away.
    by_entity = billable_codes_by_entity(user_id)
    names = _entity_names(by_entity.keys())
    entries: list[tuple[str, str, str, int]] = []
    currency = None
    for entity_id, codes in sorted(by_entity.items(), key=lambda kv: names.get(kv[0], "")):
        plan = store.billing_plan_for_codes(codes)
        if plan is None:
            logger.error(
                "renewal: no plan prices {} for entity {}; skipping the line rather "
                "than guessing a price",
                ",".join(sorted(codes)),
                entity_id,
            )
            continue
        currency = currency or plan.currency
        entries.append((entity_id, names.get(entity_id, entity_id), plan.display_name,
                        plan.amount))

    extensions = _pending_extension_lines(user_id, names)
    if not entries and not extensions:
        return None

    if currency is None:
        # Nothing renewing — this invoice is extensions only, so the price catalog was
        # never consulted. Fall back to the currency the payer has been billed in.
        _anchor, currency = store.billing_cycle_for_user(user_id)
    # Cancel-extensions ride this invoice rather than being charged at cancellation
    # time, so that cancelling never depends on a card clearing. Under Stripe they were
    # a pending invoice item swept onto the anchor invoice; the runner plays that role
    # now — and unlike Stripe it fires even when this was the payer's LAST entity.
    invoice = renewal_invoice(entries, period, (currency or "").lower())
    if not extensions:
        return invoice
    return Invoice(
        currency=invoice.currency,
        period=invoice.period,
        lines=invoice.lines + tuple(extensions),
    )


def _pending_extension_lines(user_id, names: dict[str, str]) -> list[Line]:
    """Lines for cancel-extensions this payer owes but has not been billed for."""
    lines: list[Line] = []
    for row in store.pending_extensions_for_payer(user_id):
        entity_id = str(row.entity_id)
        name = names.get(entity_id) or _entity_names({entity_id}).get(entity_id, entity_id)
        lines.append(
            Line(
                entity_id=entity_id,
                entity_name=name,
                product_name=f"{row.function_code.title().replace('_', ' ')} "
                             "(access after cancellation)",
                amount=int(row.extension_amount or 0),
            )
        )
    return lines


def due_renewals(now: datetime) -> list:
    """Payers whose current period has ended and who need their next invoice.

    Driven off the ACCOUNT's ``paid_through``, not a date derived from the anchor and not
    the per-row copy. A derived period always contains "now" so it can never come due;
    a per-row copy drifts between a payer's entities, and taking the oldest of several
    disagreeing rows would re-bill a period already collected.
    """
    due = []
    for account in store.accounts_with_billing():
        if account.anchor_at is None or account.paid_through is None:
            continue  # nothing has ever been billed for this payer
        if account.paid_through > now:
            continue
        if not billable_codes_by_entity(account.user_id) and not (
            store.pending_extensions_for_payer(account.user_id)
        ):
            # Nothing renewing AND nothing owed. A payer whose LAST entity was cancelled
            # has no billable modules but still owes the extension they were promised
            # access for — dropping them here would give those days away.
            continue
        due.append((account, account.paid_through))
    return due


def period_key(user_id, period: Period) -> str:
    """Stable id for "this payer's invoice for this period".

    Claimed under the UNIQUE index on ``subscription_invoice.idempotency_key`` before the
    charge, so a runner that crashes between charging and recording cannot bill the same
    period twice. Also Stripe's idempotency key and the invoice's ``renewal_key``
    metadata — the latter is what ``_already_invoiced`` falls back to when a reservation
    was never confirmed sent.

    Stable by construction: derived from the payer and the period START, so it survives
    a process restart. Anything built off "now" would not.
    """
    return f"renewal-{user_id}-{period.start:%Y%m%d}"


def _already_invoiced(customer_id, key: str) -> str | None:
    """The status of the invoice already raised under ``key``, or None if there is none.

    ONE INDEXED LOOKUP, where this used to LIST the payer's Stripe invoices and scan
    their metadata — once per payer, every renewal run. The local row is written before
    the charge (``billing_gateway.issue_invoice``) under a UNIQUE index, so its presence
    is a stronger answer than a search that came back empty: a search can miss, a unique
    constraint cannot.

    THE ONE CASE THE ROW CANNOT ANSWER is a reservation with no ``external_id``: the key
    was claimed and then nothing came back, so we do not know whether Stripe created the
    invoice. Guessing either way is a real error — assume it exists and the payer is
    never billed for the period; assume it does not and they may be billed twice. So this
    is the one path that still asks the processor, and it costs a scan only after a run
    died mid-charge rather than on every renewal.

    If the processor has never heard of it, the reservation is DISCARDED so the retry can
    proceed. Leaving it would block that period's invoice permanently — the guard turned
    into a hold on a charge nobody ever made.
    """
    record = store.invoice_for_key(key)
    if record is None:
        return None
    if record.external_id:
        return record.status

    from blueprints.subscription.services import billing_gateway

    logger.warning(
        "renewal: {} was reserved but never confirmed sent; asking the processor", key
    )
    existing = billing_gateway.find_invoice_by_metadata(
        customer_id, "renewal_key", key
    )
    if existing is None:
        store.discard_invoice(record.id)
        return None
    # It does exist — record what was found so the next run needs no scan at all.
    store.settle_invoice(
        record.id, external_id=existing.get("id"), status=existing.get("status")
    )
    return existing.get("status")


class _AllPayers:
    """Sentinel for "every payer" — see ``ALL_PAYERS``."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ALL_PAYERS"


# Passed as ``scope`` to bill everybody. It exists so that billing the whole customer
# base has to be TYPED rather than obtained by leaving an argument out.
#
# This is not hypothetical caution. A global renewal run driven by an injected test
# clock charged a real payer twice for catch-up periods: the runner was correct, the
# clock belonged to a different customer, and nothing in the signature made the blast
# radius visible at the call site. A harness now cannot reach every payer by accident —
# it has to ask for them by name.
ALL_PAYERS = _AllPayers()


def run_renewals(now: datetime, *, scope, issue: bool = False,
                 limit: int | None = None) -> dict:
    """Bill payers whose period has ended. SHADOW by default.

    ``scope`` is required and has no default: either an iterable of user ids, or
    ``ALL_PAYERS``. Omitting it is a TypeError rather than a full sweep.

    With ``issue=False`` this computes what each payer would be charged and changes
    nothing — the safe way to run it against live data for a cycle and compare with what
    Stripe actually billed, before it is ever allowed to take money.

    Returns ``{"planned": [...], "issued": [...], "failed": [...], "skipped": [...]}``.

    Ordering is deliberate and matters more than it looks:

    1. a local invoice already carrying this period's key means the money was collected
       on an earlier run that died before recording it — so ADOPT it, advance
       ``paid_through``, and charge nothing. This is the case a naive runner
       double-bills. See ``_already_invoiced``;
    2. issue and collect;
    3. only on success advance ``paid_through``. Advancing first would skip the period
       forever if the charge then failed — the customer gets a free month and nothing
       ever notices;
    4. on failure start dunning, which is what turns a declined renewal into the retry
       schedule rather than a silent lapse.
    """
    from blueprints.subscription.services import billing_gateway

    planned: list[dict] = []
    issued: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []

    wanted = None if scope is ALL_PAYERS else {str(u) for u in scope}
    candidates = [
        (account, paid_through)
        for account, paid_through in due_renewals(now)
        if wanted is None or str(account.user_id) in wanted
    ]

    for account, paid_through in candidates[: limit or None]:
        user_id = account.user_id
        period = next_period(account.anchor_at, paid_through)
        invoice = build_renewal(user_id, period)
        entry = {
            "user_id": user_id,
            "period_start": period.start,
            "period_end": period.end,
            "total": invoice.total if invoice else 0,
            "lines": [line.description for line in invoice.lines] if invoice else [],
            # Carried so the receipt / decline email can state the amount in the right
            # currency without re-deriving the payer's invoice from scratch.
            "currency": invoice.currency if invoice else None,
        }
        if invoice is None:
            skipped.append({**entry, "reason": "nothing billable"})
            continue
        if not issue:
            planned.append(entry)
            continue

        key = period_key(user_id, period)
        # Captured BEFORE issuing, so the rows closed out afterwards are exactly the ones
        # whose lines rode this invoice. Re-querying after would also catch anything
        # cancelled while the charge was in flight and mark it paid for free.
        extension_ids = [
            row.id for row in store.pending_extensions_for_payer(user_id)
        ]
        try:
            status = _already_invoiced(account.stripe_customer_id, key)
            if status is not None:
                # Charged on a previous run that failed to record it. Catching up costs
                # nothing; re-issuing would bill the customer twice for one month.
                if status == "paid":
                    store.set_paid_through(user_id, period.end)
                    # The extensions rode THAT invoice; leaving them pending would put
                    # them on the next one too.
                    store.mark_extensions_invoiced(extension_ids)
                    skipped.append({**entry, "reason": "already invoiced; adopted"})
                else:
                    skipped.append({**entry, "reason": "already invoiced; unpaid"})
                continue

            result = billing_gateway.issue_invoice(
                account.stripe_customer_id,
                invoice,
                # Counted off the invoice itself rather than off the rows, so the memo
                # describes what is actually being charged. An extension is called out
                # because it is the one line on a renewal nobody is expecting.
                memo=renewal_memo(
                    period,
                    len(invoice.entity_ids),
                    sum(1 for line in invoice.lines
                        if "access after cancellation" in line.product_name),
                ),
                metadata={"renewal_key": key},
                idempotency_key=key,
                # Known here, so the gateway doesn't have to look up the payer the
                # customer id came from in the first place.
                payer_user_id=user_id,
            )
            if result.get("status") == "paid":
                store.set_paid_through(user_id, period.end)
                # Only now: the cancellation fee has actually been collected. Marking
                # before would drop the charge if collection then failed, and the
                # extension days were granted either way.
                store.mark_extensions_invoiced(extension_ids)
                issued.append({**entry, "invoice": result.get("id")})
            else:
                store.begin_dunning(user_id, now)
                failed.append({**entry, "invoice": result.get("id"),
                               "status": result.get("status")})
        except Exception:
            logger.exception("renewal: failed to bill payer {}", user_id)
            try:
                store.begin_dunning(user_id, now)
            except Exception:
                logger.exception("renewal: could not start dunning for {}", user_id)
            failed.append({**entry, "status": "error"})

    # Emails go out only after the whole batch has been billed and committed. Sending
    # inside the loop would put SMTP latency between two payers' charges, and would tell
    # a customer about a charge that a later exception could still roll back.
    _notify_renewals(issued, failed)

    return {"planned": planned, "issued": issued, "failed": failed, "skipped": skipped}


def _notify_renewals(issued: list[dict], failed: list[dict]) -> None:
    """Mail the receipts and the declines. Never raises — see ``notify``.

    Deduped on the period key, which is what makes a re-run harmless: the same payer and
    period produce the same key, so a job that is run twice in a day charges once (by
    ``_already_invoiced``) and mails once (by the email log).
    """
    from blueprints.subscription.services import notify

    events = []
    for entry in issued:
        period = Period(start=entry["period_start"], end=entry["period_end"])
        events.append(
            (entry["user_id"], notify.RENEWAL_PAID,
             period_key(entry["user_id"], period), entry)
        )
    for entry in failed:
        period = Period(start=entry["period_start"], end=entry["period_end"])
        events.append(
            (entry["user_id"], notify.RENEWAL_FAILED,
             period_key(entry["user_id"], period), entry)
        )
    notify.notify_many(events)


def next_period(anchor: datetime, paid_through: datetime) -> Period:
    """The period that follows what has been paid for.

    Derived from the anchor so month-end billing stays correct — 31 Jan clamps to 28 Feb
    and springs back to 31 Mar — rather than by adding a month to the previous end,
    which would peg a month-end payer to the 28th permanently.
    """
    return period_containing(anchor, paid_through)
