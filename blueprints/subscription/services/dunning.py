"""What to do when a renewal payment fails — retry schedule and give-up rules.

Stripe's Smart Retries are ML-timed and deliberately opaque; there is no point trying to
reproduce them. What matters in-house is a schedule that is PREDICTABLE — a customer can
be told exactly when the next attempt is, and support can explain why access ended on a
particular day — and that stays coherent with the access window.

Pure by construction: plain values in, decisions out. No Stripe, no ORM, no clock. The
caller supplies "now" and persists whatever comes back, which keeps the policy testable
without a database and portable off Stripe.

THE INVARIANT THAT MATTERS. Dunning must finish inside the access grace window
(``access.PAST_DUE_GRACE_DAYS``). Get that wrong in either direction and the system
contradicts itself:

* retries running PAST the grace end keep charging a customer whose access was already
  revoked — billing someone for something they can no longer use;
* giving up WELL BEFORE it ends leaves a customer with days of free access after the
  last attempt, and no way to recover the subscription even if they fix their card.

``test_dunning_finishes_inside_the_access_grace_window`` pins this, so changing either
constant without the other fails loudly rather than drifting.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Days after the FIRST failure at which each retry runs. EVERY day from the first to the
# thirteenth: most failures are transient — an expired card that has already been
# replaced, or a temporary hold — and a daily attempt collects on the day the customer
# fixes it rather than up to three days later, which is three more days of an account
# reading as past due to everyone who looks at it.
#
# It stops at 13, not 15, because the schedule has to finish before the window does:
# ``policy._dunning_pair`` rejects any list whose last retry leaves under two days to
# settle, and falls back to the shipped default if it does. Those two quiet days at the
# end are deliberate — automatic attempts have stopped, the customer has been told, and
# they can still pay in the portal before access ends.
RETRY_OFFSETS_DAYS: tuple[int, ...] = tuple(range(1, 14))

MAX_ATTEMPTS = len(RETRY_OFFSETS_DAYS)

# When dunning stops and the subscription is given up on, measured from the first
# failure. Sits at the end of the access grace window: the last retry has had two days
# to settle, and access ends the moment collection does.
GIVE_UP_AFTER_DAYS = 15

# --- Where these values actually come from now ---------------------------------------
#
# Both constants above are DEFAULTS. The live values are
# ``billing_policy.past_due_window_days`` and ``billing_policy.retry_offsets_days``,
# resolved by ``services.policy`` and passed in by ``collect_due``.
#
# The two-constants-must-agree problem is gone at the source: access grace and the
# give-up deadline are ONE column, so ``give_up_at`` and ``access.access_end`` are handed
# the same number and cannot drift. What ``policy`` still has to check is the schedule
# fitting inside it — see ``policy._dunning_pair``.
#
# They stay here so every function below remains pure: plain values in, decisions out,
# no database needed to test the schedule and a sane fallback if the row cannot be read.


def next_attempt_at(
    first_failed_at: datetime,
    attempts: int,
    offsets: tuple[int, ...] = RETRY_OFFSETS_DAYS,
) -> datetime | None:
    """When the next retry is due, or None once the schedule is exhausted.

    ``attempts`` counts retries ALREADY made, so 0 means the first failure has been
    recorded and nothing has been retried yet.

    Timed from the FIRST failure rather than the previous attempt. A retry that is
    delayed — a worker outage, a queue backlog — must not push everything after it back
    and quietly extend dunning past the grace window.
    """
    if attempts < 0:
        raise ValueError("attempts cannot be negative")
    if attempts >= len(offsets):
        return None
    return first_failed_at + timedelta(days=offsets[attempts])


def is_exhausted(attempts: int, offsets: tuple[int, ...] = RETRY_OFFSETS_DAYS) -> bool:
    """Whether every scheduled retry has been made."""
    return attempts >= len(offsets)


def give_up_at(
    first_failed_at: datetime,
    window_days: int = GIVE_UP_AFTER_DAYS,
    access_ends_at: datetime | None = None,
) -> datetime:
    """When to stop trying and cancel, whatever the attempt count says.

    A wall-clock deadline as well as an attempt count, because the two can disagree: a
    worker that was down for a week comes back to a subscription whose retries are all
    still "pending" but which is long past the point of being worth chasing.

    ``access_ends_at`` CLAMPS the deadline, and it is the whole reason this takes a
    second date. The window is one number, but the two halves of going past due count it
    from different instants:

        access ends at      paid_through        + window
        collection ends at  dunning_started_at  + window

    Those coincide only if the renewal ran the moment the period ended. It does not have
    to: ``renewals.due_renewals`` picks up anyone whose ``paid_through`` has passed, so a
    worker outage, a paused cron or a batch ``limit`` pushes the first failure — and with
    it the whole retry schedule — days later. The drift is one-directional, because a
    renewal cannot fail before its period ends, so collection always outlives access.

    Worked through: period ends 1 Mar, window 15, worker down a week. Dunning starts
    8 Mar and would run to 23 Mar, retrying on the 9th, 12th, 15th, 18th and 21st — but
    access ended on the 16th. The last two retries charge a card for a customer who has
    been locked out for days, which is exactly the failure the module docstring opens
    with.

    Clamping fixes the harm without touching the schedule: retries keep their normal
    spacing and simply stop when entitlement does. Passing None keeps the unclamped
    deadline, which is what the pure tests use.
    """
    deadline = first_failed_at + timedelta(days=window_days)
    if access_ends_at is not None and access_ends_at < deadline:
        return access_ends_at
    return deadline


def should_attempt_now(
    now: datetime,
    first_failed_at: datetime,
    attempts: int,
    offsets: tuple[int, ...] = RETRY_OFFSETS_DAYS,
    window_days: int = GIVE_UP_AFTER_DAYS,
    access_ends_at: datetime | None = None,
) -> bool:
    """Whether a retry is due at ``now``.

    False once the schedule is exhausted OR the deadline has passed, so a caller that
    polls cannot keep charging a card past the point of giving up. Because the deadline
    is ``give_up_at``, passing ``access_ends_at`` also stops retries the moment access
    does — no separate check needed here.
    """
    if now >= give_up_at(first_failed_at, window_days, access_ends_at):
        return False
    due = next_attempt_at(first_failed_at, attempts, offsets)
    return due is not None and now >= due


def should_give_up(
    now: datetime,
    first_failed_at: datetime,
    window_days: int = GIVE_UP_AFTER_DAYS,
    access_ends_at: datetime | None = None,
) -> bool:
    """Whether to stop and cancel. The DEADLINE only — never the attempt count.

    Running out of retries means "stop charging the card", not "cancel the
    subscription". Those are different decisions and conflating them costs the customer
    real days: with retries at 1/4/7/10/13 and a 15-day window, cancelling on exhaustion
    would end access on day 13 while the past-due grace still promised 15.

    The gap is the most valuable part of the window. Automatic retries have stopped, so
    the customer has been told to act, and they can still pay in the portal — which
    settles the invoice and recovers the subscription. Cancelling early removes exactly
    that chance.

    Access and collection end together on the same day — by construction when the
    renewal ran on time, and by ``access_ends_at`` clamping the deadline when it did not.
    """
    return now >= give_up_at(first_failed_at, window_days, access_ends_at)


def attempts_remaining(
    attempts: int, offsets: tuple[int, ...] = RETRY_OFFSETS_DAYS
) -> int:
    """How many retries are left — for telling the customer what happens next."""
    return max(0, len(offsets) - attempts)


# --- Running a collection cycle -------------------------------------------------
#
# Everything above is pure policy. Below is the one function that acts on it, kept
# separate so the schedule stays testable without a database or a processor.


def _settle_period(account, invoice) -> None:
    """Record the period a recovered payment covers.

    Only for RENEWAL invoices, and only on evidence. Dunning chases the payer's oldest
    open invoice, which may be a mid-period change or a reinstatement — those are paid
    for in full and cover no period, so advancing the cycle off one hands the customer a
    free month. ``renewal_key`` is the marker (see ``renewals.period_key``).

    ``invoice is None`` means the debt was settled somewhere this code cannot see (a
    portal payment, a manual charge) and there is nothing left to read. It is NOT
    advanced: guessing risks the free month, whereas doing nothing self-heals — the next
    renewal run finds the paid invoice by its key and adopts it. The cost is that the
    payer stays unentitled until then, which is why the paid-retry path above does this
    properly rather than relying on it.
    """
    from loguru import logger

    from blueprints.subscription.services import renewals, store

    if invoice is None:
        logger.info(
            "dunning: payer {} settled outside the app; leaving paid_through for the "
            "next renewal run to adopt",
            account.user_id,
        )
        return
    if not (invoice.get("metadata") or {}).get("renewal_key"):
        return

    anchor = account.anchor_at
    paid_through = account.paid_through
    if anchor is None or paid_through is None:
        return
    period = renewals.next_period(anchor, paid_through)
    store.set_paid_through(account.user_id, period.end)


def _restore_access(user_id) -> None:
    """Switch this payer's modules back on now that the balance is settled.

    ``_settle_period`` moves ``paid_through`` and ``end_dunning`` moves the phases, but
    neither touches ``entity_function_map`` — and access is a separate write. Without
    this the money is collected, the subscription reads active, and the customer is
    still bounced off every page in it. The daily sweep would eventually notice, so this
    is about WHEN: the customer who just paid to get back in should be back in.

    Never raises. A recovery that collected the money is not undone because a follow-up
    write failed; the sweep is the backstop, and a swallowed error here is visible in the
    log rather than as a lost payment.
    """
    from blueprints.entity.services.modules import sweep_expired_module_access

    try:
        sweep_expired_module_access(payer_user_id=user_id)
    except Exception:
        logger.exception("dunning: could not restore access for payer {}", user_id)


def collect_due(now, limit: int | None = None) -> dict:
    """Run one dunning cycle: retry what is due, give up on what is spent.

    Returns ``{"retried": [...], "recovered": [...], "given_up": [...]}``.

    Safe to run repeatedly and at any cadence. ``should_attempt_now`` gates on the
    schedule rather than on when this last ran, so an hourly job and a daily one produce
    the same attempts — and a job that was down for a week does not fire the whole
    backlog at once, because the missed slots are simply past.
    """
    from loguru import logger

    from blueprints.subscription.services import billing_gateway, policy, store

    # Resolved ONCE for the cycle, not per account: every payer is on the same policy,
    # and re-reading it mid-run would let an edit land halfway through — some payers
    # given up on under the old window, some under the new.
    settings = policy.current()
    offsets = settings.retry_offsets_days
    window = settings.past_due_window_days

    retried: list[dict] = []
    recovered: list[dict] = []
    given_up: list[dict] = []

    accounts = store.accounts_in_dunning()
    if limit:
        accounts = accounts[:limit]

    for account in accounts:
        user_id = account.user_id
        started = account.dunning_started_at
        attempts = int(account.dunning_attempts or 0)
        entry = {"user_id": user_id, "attempts": attempts}
        # The episode this entry belongs to, stamped now because ``end_dunning`` clears
        # ``dunning_started_at`` before the notification is composed. Without it a payer
        # who lapses, recovers, and lapses again months later would dedupe against the
        # first episode's email and hear nothing the second time.
        entry["_episode"] = f"{user_id}:{started:%Y%m%dT%H%M%S}" if started else str(user_id)
        # When this payer's past-due access actually runs out. The SAME expression
        # ``access.access_end`` uses for a past-due module — ``paid_through`` plus the
        # window — so collection can never outlive entitlement however late the renewal
        # that started this ran. See ``give_up_at`` for the drift it closes.
        #
        # A payer with no paid_through has never been billed and cannot be past due on a
        # renewal; there is nothing to clamp against, so the unclamped deadline stands.
        access_ends_at = (
            account.paid_through + timedelta(days=window)
            if account.paid_through is not None
            else None
        )
        try:
            if should_give_up(now, started, window, access_ends_at):
                store.end_dunning(user_id, status="closed")
                given_up.append(entry)
                continue
            if not should_attempt_now(
                now, started, attempts, offsets, window, access_ends_at
            ):
                # Either not due yet, or the retries are spent and the account is
                # riding out the rest of the window — still recoverable if the customer
                # pays in the portal, so it stays in dunning until the deadline.
                continue

            invoices = billing_gateway.open_invoices(account.stripe_customer_id)
            if not invoices:
                # Nothing outstanding — it was settled elsewhere (a portal payment, a
                # manual charge). Dunning has no reason to continue, but the period it
                # paid for still has to be recorded, or the customer has paid and is
                # locked out until the next renewal run notices.
                _settle_period(account, None)
                store.end_dunning(user_id, status="active")
                _restore_access(user_id)
                recovered.append(entry)
                continue

            # The attempt is counted BEFORE it runs. If this process dies mid-retry the
            # slot is spent rather than replayed, which is the safe direction: a
            # double-charge is far worse than a skipped retry.
            store.record_dunning_attempt(user_id)
            paid, reason = billing_gateway.retry_invoice(invoices[0]["id"])
            entry["invoice"] = invoices[0]["id"]
            entry["reason"] = reason
            retried.append(entry)

            if paid:
                # Advance BEFORE clearing dunning: this is what the customer just paid
                # for. Without it the money is collected and they stay unentitled until
                # the next monthly run adopts the invoice by its idempotency key — a
                # month of paying for nothing.
                _settle_period(account, invoices[0])
                store.end_dunning(user_id, status="active")
                _restore_access(user_id)
                recovered.append(entry)
        except Exception:
            logger.exception("dunning: cycle failed for payer {}", user_id)

    # After the cycle, never during it. A payer whose retry succeeds appears in both
    # ``retried`` and ``recovered``; mailing from inside the loop would send them a
    # "failed again" notice moments before the "you're all settled" one.
    _notify_dunning(retried, recovered, given_up)

    return {"retried": retried, "recovered": recovered, "given_up": given_up}


def _notify_dunning(retried: list[dict], recovered: list[dict],
                    given_up: list[dict]) -> None:
    """Mail the dunning outcomes. Never raises — see ``notify``.

    The retry notice is deliberately suppressed for an attempt that then SUCCEEDED: the
    same entry lands in both lists, and the customer cares about the outcome, not the
    mechanics. Only a retry that left the balance outstanding is worth an email.

    Dedupe keys are per-episode, and the retry key includes the attempt number — so each
    of the three or four scheduled attempts notifies once, and a job run twice in a day
    still only sends what actually happened once.
    """
    from blueprints.subscription.services import notify

    settled = {entry["user_id"] for entry in recovered}
    events = []
    for entry in retried:
        if entry["user_id"] in settled:
            continue
        events.append(
            (entry["user_id"], notify.DUNNING_RETRY_FAILED,
             f"{entry['_episode']}:{entry['attempts']}", entry)
        )
    for entry in recovered:
        events.append(
            (entry["user_id"], notify.PAYMENT_RECOVERED, entry["_episode"], entry)
        )
    for entry in given_up:
        events.append(
            (entry["user_id"], notify.ACCOUNT_CLOSED, entry["_episode"], entry)
        )
    notify.notify_many(events)

    # ``_episode`` is scaffolding for the dedupe key, not part of what ``collect_due``
    # reports. Dropped here so the documented return shape stays what it was.
    for entry in (*retried, *recovered, *given_up):
        entry.pop("_episode", None)


def retry_now(user_id) -> dict:
    """Collect this payer's outstanding invoice IMMEDIATELY, at their own request.

    The same collection ``collect_due`` performs, minus one thing: the schedule gate.
    ``should_attempt_now`` paces AUTOMATIC retries so a cron job does not hammer a card
    every hour. It has no business standing between a customer who has just fixed their
    card and the debt they are trying to settle — without this they save a card and then
    wait up to two days for a slot, still locked out, with no way to say "try it now".

    Everything else is deliberately identical, and calls the same helpers, so a manual
    collection and a scheduled one cannot end in different states:

      * the GIVE-UP deadline still applies. Past it, retries stop for the same reason the
        cron stops — collection must never outlive access (see ``give_up_at``).
      * the attempt is counted against the same budget. A customer-initiated retry is a
        charge attempt like any other, and sharing the budget is what bounds the total
        number of times a card can be hit however the retry was triggered. The cost is
        that clicking twice spends two automatic slots; the account still rides out the
        window and is still recoverable, which ``should_give_up`` is explicit about.
      * success settles the period BEFORE clearing dunning, so the customer is entitled
        to what they just paid for rather than waiting for the next renewal run.

    Keyed on the DEBT, not on the dunning stamp. The open invoice is what the customer
    owes; ``dunning_started_at`` is bookkeeping for the retry schedule. Asking the stamp
    first meant a payer with a real unpaid invoice — but no stamp, because the renewal
    that should have set one never ran, or the row was written by hand — was told "no
    outstanding payment" while the page beside the button read "payment due". The stamp
    still governs the deadline and the attempt budget, which is all it is for.

    Returns ``{"status": ..., "attempts": int, "invoice": id|None, "reason": str|None}``
    where status is one of:

        paid            collected, subscription recovered
        failed          the card was declined again — ``reason`` says why
        no_card         nothing on file to charge; no attempt is spent on it
        gave_up         past the deadline; dunning closed rather than charged
        nothing_owed    no open invoice at all, so there is nothing to collect
    """
    from loguru import logger

    from blueprints.subscription.services import billing_gateway, clock, policy, store
    from blueprints.subscription.services.stripe_client import (
        customer_default_payment_method,
    )

    account = store.customer_mapping_for_user(user_id)
    if account is None:
        return {"status": "nothing_owed", "attempts": 0,
                "invoice": None, "reason": None}

    now = clock.now()
    window = policy.current().past_due_window_days
    started = account.dunning_started_at
    attempts = int(account.dunning_attempts or 0)
    access_ends_at = (
        account.paid_through + timedelta(days=window)
        if account.paid_through is not None
        else None
    )

    # Only meaningful while collection is running: with no stamp there is no schedule to
    # have outrun, so there is no deadline to be past.
    if started is not None and should_give_up(now, started, window, access_ends_at):
        store.end_dunning(user_id, status="closed")
        return {"status": "gave_up", "attempts": attempts,
                "invoice": None, "reason": None}

    invoices = billing_gateway.open_invoices(account.stripe_customer_id)
    if not invoices:
        # Nothing owed. If collection was running it was settled somewhere this code
        # cannot see (a portal payment, a manual charge), so close it out and record what
        # it paid for — otherwise the customer has paid and stays locked out until the
        # next renewal run notices.
        if started is not None:
            _settle_period(account, None)
            store.end_dunning(user_id, status="active")
        return {"status": "nothing_owed", "attempts": attempts,
                "invoice": None, "reason": None}

    # No card => the charge CANNOT succeed, so it must not be attempted. Counting a slot
    # for it would spend the retry budget on a guaranteed decline, and every press would
    # spend another — the customer's actual next step is to add a card, which is the
    # button beside this one.
    if not customer_default_payment_method(account.stripe_customer_id):
        return {"status": "no_card", "attempts": attempts,
                "invoice": invoices[0]["id"], "reason": None}

    # Counted BEFORE it runs, exactly as the scheduled path does: if this request dies
    # mid-retry the slot is spent rather than replayed. A double-charge is far worse
    # than a skipped retry.
    attempts = store.record_dunning_attempt(user_id)
    invoice_id = invoices[0]["id"]
    paid, reason = billing_gateway.retry_invoice(invoice_id)
    logger.info(
        "dunning: manual retry for payer {} invoice {} -> {} ({})",
        user_id, invoice_id, "paid" if paid else "failed", reason,
    )

    if paid:
        _settle_period(account, invoices[0])
        # Only ends collection if it was running; a payer who paid an open invoice
        # without ever being dunned has nothing to clear.
        if started is not None:
            store.end_dunning(user_id, status="active")
        return {"status": "paid", "attempts": attempts,
                "invoice": invoice_id, "reason": reason}

    return {"status": "failed", "attempts": attempts,
            "invoice": invoice_id, "reason": reason}
