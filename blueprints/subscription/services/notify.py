"""Billing email — the subscription engine's only outbound notification.

Before this module the engine was SILENT. Every lifecycle event was computed, stored and
acted on, and the customer learned about it either by happening to open the Module &
Subscription settings page or by being bounced to an "Access Denied" screen after their
module had already been switched off. The most consequential event of all — a free trial
that will not convert because no card is on file — was knowable days in advance and
announced nowhere.

THREE RULES, all of them load-bearing:

1. **Never raise.** Every entry point returns a bool and swallows its own exceptions.
   These are called from inside cron jobs that move money; a dead SMTP host must not be
   the thing that aborts a renewal run halfway through a batch of payers. This matches
   what ``invitation.services.invite`` and ``auth.services.email_auth`` already do.

2. **Never send twice.** The jobs that call this are documented as safe to re-run at any
   cadence, and that property is only true of state reconciliation — a send is not
   idempotent. So the send is CLAIMED in ``subscription_email_log`` first, and a claim
   that already succeeded short-circuits. See that model for why the constraint lives in
   the database rather than here.

3. **Send after the money, never during.** Callers collect events and flush them once
   their loop has finished and ``store`` has committed. Mailing mid-loop risks telling a
   customer about a charge that then rolls back, and puts network latency inside a
   billing transaction.

The copy for all nine events lives in ``_COPY`` below rather than in nine templates, so
the entire customer-facing vocabulary of the billing system is reviewable on one screen —
which matters more here than template purity, because these are the only words Minty ever
says to a customer about their money.

Recipient is the PAYER, with ONE exception. Every action these emails ask for (add a card,
settle an invoice, confirm billing) is one only the payer can take; co-admins on an entity
would receive amounts they cannot act on. The consequence is a known gap — a co-admin
still watches modules go dark with no explanation — and closing it needs a separate,
redacted template set rather than a wider recipient list on these.

The exception is ``subscriber_transfer_requested``, which is addressed to someone who is
NOT yet the payer and is being asked to become one. It belongs here rather than in a
separate system because it is a message about money with an amount in it, and the whole
point of keeping this vocabulary on one screen is that no such message escapes review.
"""
from __future__ import annotations

from datetime import datetime

from flask import current_app, render_template
from flask_mail import Message
from loguru import logger

from blueprints.subscription.services.money import format_minor

# --- Events -------------------------------------------------------------------
# Stable strings: they are persisted as dedupe rows, so renaming one silently
# re-sends every email of that kind to every customer who already had it.
TRIAL_ENDING = "trial_ending"
TRIAL_CONVERTED = "trial_converted"
TRIAL_EXPIRED = "trial_expired"
RENEWAL_PAID = "renewal_paid"
RENEWAL_FAILED = "renewal_failed"
DUNNING_RETRY_FAILED = "dunning_retry_failed"
PAYMENT_RECOVERED = "payment_recovered"
ACCOUNT_CLOSED = "account_closed"
ACCESS_REVOKED = "access_revoked"
# The handover family. ``requested`` is the one email in this module sent to a non-payer.
SUBSCRIBER_TRANSFER_REQUESTED = "subscriber_transfer_requested"
SUBSCRIBER_TRANSFER_ACCEPTED = "subscriber_transfer_accepted"
SUBSCRIBER_TRANSFER_FAILED = "subscriber_transfer_failed"

EVENTS = (
    TRIAL_ENDING,
    TRIAL_CONVERTED,
    TRIAL_EXPIRED,
    RENEWAL_PAID,
    RENEWAL_FAILED,
    DUNNING_RETRY_FAILED,
    PAYMENT_RECOVERED,
    ACCOUNT_CLOSED,
    ACCESS_REVOKED,
    SUBSCRIBER_TRANSFER_REQUESTED,
    SUBSCRIBER_TRANSFER_ACCEPTED,
    SUBSCRIBER_TRANSFER_FAILED,
)

TEMPLATE = "email/subscription_notice.html"


# --- Formatting helpers -------------------------------------------------------


def money(amount_minor, currency: str | None) -> str:
    """``28000, 'hkd'`` -> ``'HKD 280.00'``.

    Currency is stated alongside the number rather than as a symbol: these emails reach
    customers in several currencies and a bare ``$`` is ambiguous across most of them.
    """
    code = (currency or "").strip().upper()
    return f"{code} {format_minor(amount_minor, currency)}".strip()


def day(value) -> str:
    """A date a human reads without parsing: ``12 Mar 2026``. Empty when unknown.

    Formatted the way ``modules._fmt_day_month_year`` already did it: take the day as an
    INT and let strftime handle only the parts it agrees about across platforms. This
    used to probe for glibc's ``%-d`` at every call and fall back to
    ``"%d %b %Y".lstrip("0")`` on Windows -- two code paths, a try/except and a bare
    ``datetime`` literal, to reach the string an f-string gives directly.
    """
    if not isinstance(value, datetime):
        return ""
    return f"{value.day} {value:%b %Y}"


def modules_phrase(codes) -> str:
    """``['PETTY_CASH', 'BILL']`` -> ``'Petty Cash and Payment Request'``."""
    names = [_module_name(code) for code in codes if code]
    if not names:
        return "your modules"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _module_name(code: str) -> str:
    pretty = {"PETTY_CASH": "Petty Cash", "BILL": "Payment Request"}
    key = str(code or "").strip().upper()
    return pretty.get(key, key.title().replace("_", " "))


def base_url() -> str:
    """Public origin for links, WITHOUT a request to derive it from.

    ``PUBLIC_URL`` — the same setting the invitation email already uses, deliberately not
    a second one of its own. Both are outbound mail that has to name a host it cannot
    look up, and two config keys meaning the same thing is how one of them ends up stale
    after a domain change while the other keeps working.

    Set explicitly rather than derived: these are sent from CLI jobs, where
    ``url_for(_external=True)`` needs ``SERVER_NAME`` and silently produces
    ``http://localhost`` when it is unset — a link that is worse than no link, because it
    looks real. An unset value drops the button rather than shipping a dead one.
    """
    value = (current_app.config.get("PUBLIC_URL") or "").rstrip("/")
    _warn_once_if_unreachable(value)
    return value


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", ".local", ".test")
_warned_unreachable = False


def _warn_once_if_unreachable(value: str) -> None:
    """Say something when the buttons in these emails cannot possibly work.

    A developer's ``PUBLIC_URL`` reaching production mail is a silent failure otherwise:
    every message goes out looking perfect and every button lands on a host only the
    sender can resolve. Cheap to detect, and worth one loud line per process — the alert
    emails are the ones whose whole purpose is getting somebody to click through.

    Once per process, not per send: a nightly run mailing forty payers should not print
    forty copies of the same configuration problem.
    """
    global _warned_unreachable
    if _warned_unreachable:
        return
    lowered = value.lower()
    if not value:
        _warned_unreachable = True
        logger.warning(
            "notify: PUBLIC_URL is unset — billing emails will go out with no "
            "action buttons at all."
        )
    elif any(host in lowered for host in _LOCAL_HOSTS):
        _warned_unreachable = True
        logger.warning(
            "notify: PUBLIC_URL is {!r}, which no recipient can reach. Billing emails "
            "will ship buttons that go nowhere.", value,
        )


def settings_url(entity_id) -> str:
    """The Module & Subscription page for an entity — where every action actually is."""
    root = base_url()
    if not root or not entity_id:
        return root
    return f"{root}/entity/settings/module/{entity_id}"


# --- Logo ---------------------------------------------------------------------
# Embedded in the message rather than linked. A remote <img> in an email fails in two
# ordinary situations, and both produce a broken-image box, which reads worse than no
# logo at all:
#
#   1. most clients — Gmail and Outlook included — block remote images by default until
#      the reader clicks "show images", so the masthead is a grey box on first open;
#   2. the host has to be publicly reachable. ``PUBLIC_URL`` is a developer's
#      ``https://localhost:5001`` far more often than anyone intends, and mail sent that
#      way carries a logo nobody outside that machine can load. That is exactly what the
#      first live send did.
#
# A CID attachment is part of the message, so it renders offline, behind image blocking,
# and whatever ``PUBLIC_URL`` says. The cost is ~14KB per email, which is nothing next to
# a masthead that is broken by default.

LOGO_CID = "minty-logo"
LOGO_PATH = ("img", "logo_v2.png")

_logo_cache: tuple[bytes | None] | None = None


def logo_bytes() -> bytes | None:
    """The logo file, read once per process. None if it cannot be read.

    Resolved from ``static_folder``, NOT ``root_path``. This app is constructed inside
    ``services/app_runtime/legacy``, so ``root_path`` is that package directory while the
    static assets live at the repository root — joining onto ``root_path`` looks right
    and silently finds nothing.

    Cached either way — including the failure — so a missing asset costs one warning
    rather than a disk hit on every message of every nightly run.
    """
    global _logo_cache
    if _logo_cache is not None:
        return _logo_cache[0]

    import os

    path = os.path.join(current_app.static_folder or "", *LOGO_PATH)
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except Exception as exc:
        # Not an error: the email is entirely readable without it, and every word of it
        # still renders. Worth saying once so a lost asset does not go unnoticed forever.
        logger.warning("notify: could not read email logo at {}: {}", path, exc)
        data = None

    _logo_cache = (data,)
    return data


# --- Copy ---------------------------------------------------------------------
# Each builder takes the event context and returns the rendered content. Keeping them
# as functions rather than format strings is what lets one event vary its wording on a
# fact — TRIAL_ENDING says something materially different depending on whether a card is
# on file, and that difference is the entire value of the email.


def _trial_ending(ctx: dict) -> dict:
    entity = ctx.get("entity_name") or "your company"
    mods = modules_phrase(ctx.get("codes") or [])
    ends = day(ctx.get("trial_end"))
    amount = ctx.get("amount")
    currency = ctx.get("currency")
    if ctx.get("needs_card"):
        return {
            "tone": "warn",
            "subject": f"Action needed: {entity}'s free trial ends {ends}",
            "heading": "Your free trial is ending",
            "lede": (
                f"The free trial for {mods} on {entity} ends on {ends}. There's no "
                f"payment method saved for this company yet, so access will stop on "
                f"that date rather than continuing."
            ),
            "facts": _trial_facts(entity, mods, ends, amount, currency),
            "body": [
                "Adding a card before then keeps everything running with no "
                "interruption — you won't be charged until the trial actually ends."
            ],
            "cta_label": "Add a payment method",
            "cta_url": settings_url(ctx.get("entity_id")),
        }
    if ctx.get("needs_consent"):
        # A CARD IS SAVED and this trial will still lapse. Until this branch existed
        # these payers got the no-card copy above — told to add a payment method they
        # could see on their own billing page, while the actual reason went unnamed.
        # The cause is not obvious and has to be spelled out: one card serves every
        # company on the account, so each company is authorised separately.
        return {
            "tone": "warn",
            "subject": f"Action needed: confirm billing for {entity} by {ends}",
            "heading": "Confirm billing to keep your subscription",
            "lede": (
                f"The free trial for {mods} on {entity} ends on {ends}. Your saved card "
                f"is shared with your other companies, so it won't be charged for this "
                f"one until you confirm — and access will stop on that date instead."
            ),
            "facts": _trial_facts(entity, mods, ends, amount, currency),
            "body": [
                "Confirming takes a moment and charges nothing today — the first "
                "payment is taken when the trial actually ends."
            ],
            "cta_label": "Confirm billing",
            "cta_url": settings_url(ctx.get("entity_id")),
        }
    return {
        "tone": "neutral",
        "subject": f"{entity}'s free trial ends {ends}",
        "heading": "Your free trial ends soon",
        "lede": (
            f"The free trial for {mods} on {entity} ends on {ends}. Your saved card "
            f"will be charged then and access continues without interruption — "
            f"there's nothing you need to do."
        ),
        "facts": _trial_facts(entity, mods, ends, amount, currency),
        "body": ["If you'd rather not continue, you can cancel any time before that date."],
        "cta_label": "Review subscription",
        "cta_url": settings_url(ctx.get("entity_id")),
    }


def _trial_facts(entity, mods, ends, amount, currency) -> list[tuple[str, str]]:
    facts = [("Company", entity), ("Modules", mods), ("Trial ends", ends)]
    if amount:
        # The entity's monthly price after conversion — NOT "first charge". When a trial
        # converts alongside a module the entity already pays for, the immediate charge
        # is the marginal step up to the bundle, not the full line. Labelling the line
        # price as the first charge would state a number the customer never sees on
        # their card. The recurring figure is true in both cases.
        facts.append(("Monthly after trial", money(amount, currency)))
    return facts


def _trial_converted(ctx: dict) -> dict:
    entity = ctx.get("entity_name") or "your company"
    mods = modules_phrase(ctx.get("codes") or [])
    return {
        "tone": "neutral",
        "subject": f"{entity} is now on a paid Minty subscription",
        "heading": "Your free trial has converted",
        "lede": (
            f"The free trial for {mods} on {entity} has ended and the subscription is "
            f"now active. Your saved card has been charged."
        ),
        "facts": [("Company", entity), ("Modules", mods)],
        "body": ["Nothing has changed about your access — this is just to confirm the switch."],
        "cta_label": "View subscription",
        "cta_url": settings_url(ctx.get("entity_id")),
    }


def _trial_expired(ctx: dict) -> dict:
    entity = ctx.get("entity_name") or "your company"
    mods = modules_phrase(ctx.get("codes") or [])
    return {
        "tone": "alert",
        "subject": f"{entity}'s free trial has ended",
        "heading": "Your free trial has ended",
        "lede": (
            f"The free trial for {mods} on {entity} has ended, and access has been "
            f"switched off. This happens when there's no payment method saved for the "
            f"company, or billing for it was never confirmed."
        ),
        "facts": [("Company", entity), ("Modules", mods)],
        "body": [
            "Your data is untouched and waiting — subscribing restores access to "
            "everything exactly as you left it."
        ],
        "cta_label": "Subscribe",
        "cta_url": settings_url(ctx.get("entity_id")),
    }


def _renewal_paid(ctx: dict) -> dict:
    total = money(ctx.get("total"), ctx.get("currency"))
    start, end = day(ctx.get("period_start")), day(ctx.get("period_end"))
    return {
        "tone": "neutral",
        "subject": f"Your Minty receipt — {total}",
        "heading": "Payment received",
        "lede": f"Thanks — we've charged {total} for your Minty subscription.",
        "facts": [("Amount", total), ("Period", f"{start} – {end}" if start else "")],
        "lines": ctx.get("lines") or [],
        "body": [],
        "cta_label": "View billing",
        "cta_url": base_url(),
    }


def _renewal_failed(ctx: dict) -> dict:
    total = money(ctx.get("total"), ctx.get("currency"))
    return {
        "tone": "alert",
        "subject": f"We couldn't take payment for Minty ({total})",
        "heading": "Your payment didn't go through",
        "lede": (
            f"We tried to charge {total} for your Minty subscription and the payment "
            f"was declined."
        ),
        "facts": [("Amount due", total)],
        "body": [
            "We'll try again automatically over the next few days. Updating your card "
            "now — or paying immediately from your billing page — settles it straight "
            "away and avoids any interruption to your access.",
        ],
        "cta_label": "Update payment method",
        "cta_url": base_url(),
    }


def _dunning_retry_failed(ctx: dict) -> dict:
    attempts = int(ctx.get("attempts") or 0) + 1
    reason = (ctx.get("reason") or "").strip()
    return {
        "tone": "alert",
        "subject": "Your Minty payment failed again",
        "heading": "We still can't take payment",
        "lede": (
            f"That's attempt {attempts} on the outstanding balance for your Minty "
            f"subscription, and the card was declined again."
        ),
        "facts": [("Attempts", str(attempts))] + ([("Reason", reason)] if reason else []),
        "body": [
            "Retries don't continue indefinitely. If the balance isn't settled before "
            "the deadline, access to your modules will be switched off.",
        ],
        "cta_label": "Update payment method",
        "cta_url": base_url(),
    }


def _payment_recovered(ctx: dict) -> dict:
    return {
        "tone": "neutral",
        "subject": "Payment received — your Minty subscription is active",
        "heading": "You're all settled",
        "lede": (
            "Your outstanding balance has been paid and your Minty subscription is "
            "active again. Full access has been restored."
        ),
        "facts": [],
        "body": ["Thanks for sorting it out — no further action needed."],
        "cta_label": "View subscription",
        "cta_url": base_url(),
    }


def _account_closed(ctx: dict) -> dict:
    return {
        "tone": "alert",
        "subject": "Your Minty subscription has been closed",
        "heading": "Your subscription has been closed",
        "lede": (
            "We weren't able to collect payment for your Minty subscription after "
            "several attempts, so it has now been closed and module access has stopped."
        ),
        "facts": [("Attempts made", str(ctx.get("attempts") or 0))],
        "body": [
            "None of your data has been deleted. Subscribing again with a working "
            "payment method restores access to everything.",
        ],
        "cta_label": "Reactivate",
        "cta_url": base_url(),
    }


def _access_revoked(ctx: dict) -> dict:
    entity = ctx.get("entity_name") or "your company"
    mods = modules_phrase(ctx.get("codes") or [])
    return {
        "tone": "alert",
        "subject": f"{mods} access for {entity} has been switched off",
        "heading": "Module access has stopped",
        "lede": (
            f"Access to {mods} for {entity} has been switched off because the "
            f"subscription is no longer active."
        ),
        "facts": [("Company", entity), ("Modules", mods)],
        "body": [
            "Your data is safe and unchanged. Restarting the subscription switches "
            "everything back on immediately.",
        ],
        "cta_label": "Restart subscription",
        "cta_url": settings_url(ctx.get("entity_id")),
    }


def _subscriber_transfer_requested(ctx: dict) -> dict:
    """Sent to the person being ASKED to take the bill on — not to the payer.

    It names the amount and the date because accepting is a purchase, and a request to
    take on a recurring cost with the figure withheld is not a request anyone can answer.
    """
    entity = ctx.get("entity_name") or "a company"
    who = ctx.get("from_name") or "The current subscriber"
    amount = money(ctx.get("amount"), ctx.get("currency"))
    return {
        "tone": "info",
        "subject": f"{who} would like you to take over billing for {entity}",
        "heading": f"Take over the subscription for {entity}?",
        "lede": (
            f"{who} has asked you to become the subscriber for {entity}. If you accept, "
            "its subscription moves to your billing account and future invoices come to you."
        ),
        "facts": [
            ("Company", entity),
            ("Requested by", who),
            ("Charged when you accept", amount),
            ("Covers from", day(ctx.get("billed_through"))),
            ("Request expires", day(ctx.get("expires_at"))),
        ],
        "body": [
            "The amount above covers the period the current subscriber has already paid "
            "for up to — you are not charged for days they have covered.",
            "Nothing changes until you accept.",
        ],
        "cta_label": "Review the request",
        "cta_url": ctx.get("portal_url") or base_url(),
    }


def _subscriber_transfer_accepted(ctx: dict) -> dict:
    """Sent to the OUTGOING payer: their bill just got smaller and they should know why."""
    entity = ctx.get("entity_name") or "a company"
    who = ctx.get("to_name") or "another admin"
    return {
        "tone": "info",
        "subject": f"{who} is now the subscriber for {entity}",
        "heading": "The subscription has been handed over",
        "lede": (
            f"{who} has taken over the subscription for {entity}. You will not be billed "
            "for it again."
        ),
        "facts": [("Company", entity), ("New subscriber", who)],
        "body": [
            "Invoices you were already sent stay on your account — they are the record "
            "of what you paid, so they do not move.",
        ],
        "cta_label": "View your subscriptions",
        "cta_url": ctx.get("portal_url") or base_url(),
    }


def _subscriber_transfer_failed(ctx: dict) -> dict:
    """Sent to the person who tried to accept, when the card did not go through.

    Says plainly that nothing moved. A failed handover that reads as ambiguous leaves two
    people each assuming the other is being billed.
    """
    entity = ctx.get("entity_name") or "a company"
    return {
        "tone": "alert",
        "subject": f"We couldn't complete the handover for {entity}",
        "heading": "That payment didn't go through",
        "lede": (
            f"The payment to take over {entity} was declined, so the handover has not "
            "happened and the current subscriber is still being billed."
        ),
        "facts": [
            ("Company", entity),
            ("Amount", money(ctx.get("amount"), ctx.get("currency"))),
        ],
        "body": [
            "Nothing has changed. Update your payment method and accept the request "
            "again — it is still open.",
        ],
        "cta_label": "Update payment method",
        "cta_url": ctx.get("portal_url") or base_url(),
    }


_COPY = {
    TRIAL_ENDING: _trial_ending,
    TRIAL_CONVERTED: _trial_converted,
    TRIAL_EXPIRED: _trial_expired,
    RENEWAL_PAID: _renewal_paid,
    RENEWAL_FAILED: _renewal_failed,
    DUNNING_RETRY_FAILED: _dunning_retry_failed,
    PAYMENT_RECOVERED: _payment_recovered,
    ACCOUNT_CLOSED: _account_closed,
    ACCESS_REVOKED: _access_revoked,
    SUBSCRIBER_TRANSFER_REQUESTED: _subscriber_transfer_requested,
    SUBSCRIBER_TRANSFER_ACCEPTED: _subscriber_transfer_accepted,
    SUBSCRIBER_TRANSFER_FAILED: _subscriber_transfer_failed,
}


# --- Delivery -----------------------------------------------------------------


class InlineImageMessage(Message):
    """A ``Message`` whose inline parts are RELATED to the body, not merely attached.

    Flask-Mail builds every message with attachments as ``multipart/mixed``, which says
    "here is a body, and separately here are some files". That is the wrong statement for
    an image the body references by ``cid:`` — the correct container is
    ``multipart/related`` (RFC 2387), which says the parts belong to one document.

    It matters in practice, not just on paper: under ``mixed`` several Outlook builds
    render the logo inline AND list it as a paperclip attachment, so a billing notice
    arrives looking like it has a file enclosed. Under ``related`` it is unambiguously
    part of the message.

    Only flipped when EVERY attachment carries a ``Content-ID``. A message that ever
    gains a genuine enclosure — a PDF invoice, say — is left as ``mixed``, which is then
    the correct answer again.
    """

    def _message(self):
        msg = super()._message()
        if msg.get_content_type() != "multipart/mixed":
            return msg
        parts = msg.get_payload()
        # parts[0] is the alternative body; anything after it is an attachment. Fewer
        # than a body plus one attachment means there is nothing to relate.
        BODY_PLUS_ONE_ATTACHMENT = 2
        if (len(parts) < BODY_PLUS_ONE_ATTACHMENT
                or not all(part.get("Content-ID") for part in parts[1:])):
            return msg
        msg.set_type("multipart/related")
        # Names which part is the root document. Without it a strict client has to guess
        # which of the related parts to actually display.
        msg.set_param("type", "multipart/alternative")
        return msg


def recipient_for(user_id) -> tuple[str | None, str]:
    """``(email, first_name)`` for a payer.

    Falls back to ``xero_email``: a user who signed up through Xero may have no personal
    ``email`` at all, and they are just as capable of owing money as anyone else.
    """
    from models.db import User

    user = User.query.filter_by(id=str(user_id)).first()
    if user is None:
        return None, ""
    address = (user.email or user.xero_email or "").strip()
    return (address or None), (user.first_name or "").strip()


def _claim(user_id, event: str, dedupe_key: str):
    """Reserve this send, or return None if it has already gone out.

    Insert-then-send rather than send-then-record: a process that dies between the two
    leaves a claim with no email, which costs one missed notice. The other order leaves
    an email with no claim, which mails the customer again on every subsequent run.
    """
    from models.db import db
    from blueprints.subscription.models.subscription_email_log import (
        STATUS_FAILED,
        SubscriptionEmailLog,
    )

    existing = SubscriptionEmailLog.query.filter_by(
        event=event, dedupe_key=str(dedupe_key)
    ).first()
    if existing is not None:
        # A previous attempt that failed to deliver is retried; one that succeeded is
        # never touched again.
        return None if existing.status != STATUS_FAILED else existing

    row = SubscriptionEmailLog(
        user_id=str(user_id),
        event=event,
        dedupe_key=str(dedupe_key),
        status=STATUS_FAILED,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001 - a lost dedupe race is somebody else's send
        # Almost certainly the unique constraint: a concurrent run claimed it first.
        # Either way somebody else owns this send.
        db.session.rollback()
        return None
    return row


def notify(user_id, event: str, *, dedupe_key: str, context: dict | None = None) -> bool:
    """Send one billing email to a payer. Returns whether it went out. Never raises.

    ``False`` covers every non-delivery equally — already sent, no address, mail not
    configured, SMTP refused — because no caller can act differently on the difference.
    The distinctions are in the log and in ``subscription_email_log.error``.
    """
    from models.db import db
    from blueprints.subscription.models.subscription_email_log import STATUS_SENT

    try:
        builder = _COPY.get(event)
        if builder is None:
            logger.error("notify: unknown billing email event {}", event)
            return False

        address, first_name = recipient_for(user_id)
        if not address:
            logger.warning(
                "notify: payer {} has no email address; skipping {}", user_id, event
            )
            return False

        mail = current_app.extensions.get("mail")
        if mail is None:
            logger.error("notify: mail extension not configured; skipping {}", event)
            return False

        row = _claim(user_id, event, dedupe_key)
        if row is None:
            logger.debug("notify: {} / {} already sent", event, dedupe_key)
            return False

        content = builder(context or {})
        logo = logo_bytes()
        html = render_template(
            TEMPLATE,
            first_name=first_name,
            base_url=base_url(),
            # Only offered to the template when the bytes are actually going to be
            # attached, so the markup can never reference a part that isn't there.
            logo_src=f"cid:{LOGO_CID}" if logo else None,
            **content,
        )
        message = InlineImageMessage(
            subject=content["subject"],
            sender=current_app.config.get("BREVO_EMAIL"),
            recipients=[address],
            html=html,
        )
        if logo:
            message.attach(
                "logo.png",
                "image/png",
                logo,
                "inline",
                # Angle brackets are required by RFC 2392 for the header; the ``src``
                # references it WITHOUT them (``cid:minty-logo``). Getting that pair
                # wrong is the usual reason an inline image silently fails to resolve.
                headers={"Content-ID": f"<{LOGO_CID}>",
                         "X-Attachment-Id": LOGO_CID},
            )
        row.recipient = address
        try:
            mail.send(message)
        except Exception as exc:
            # The claim row stays at ``failed`` on purpose, so the next run of the job
            # retries this send rather than treating it as delivered.
            row.error = str(exc)[:500]
            db.session.commit()
            logger.error("notify: failed to send {} to {}: {}", event, address, exc)
            return False

        row.status = STATUS_SENT
        db.session.commit()
        logger.info("notify: sent {} to {} ({})", event, address, dedupe_key)
        return True
    except Exception:
        # The outermost guard. Nothing about a notification may propagate into a caller
        # that is in the middle of billing somebody.
        logger.exception("notify: unexpected failure sending {}", event)
        try:
            from models.db import db as _db

            _db.session.rollback()
        except Exception:  # noqa: BLE001 - already failing; the rollback is the salvage
            logger.exception("notify: rollback after a failed {} send also failed", event)
        return False


def notify_many(events) -> int:
    """Flush a batch of prepared notifications; returns how many were delivered.

    ``events`` are ``(user_id, event, dedupe_key, context)`` tuples. Callers accumulate
    these during their run and flush ONCE at the end — see rule 3 in the module
    docstring. Nothing here raises, so a batch always drains completely.
    """
    sent = 0
    for user_id, event, dedupe_key, context in events:
        if notify(user_id, event, dedupe_key=dedupe_key, context=context):
            sent += 1
    return sent
