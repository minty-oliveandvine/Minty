"""Render every billing email, to files for review or to a real inbox.

    python scripts/subscription/preview_billing_emails.py                     # HTML files
    python scripts/subscription/preview_billing_emails.py --send you@work.com # real messages

WHY THIS DOES NOT CALL ``notify.notify``
---------------------------------------
``notify`` claims a row in ``subscription_email_log`` before it sends, and a row at
``sent`` is never sent again — that is the whole point of the table. A review send routed
through it against a real payer id would therefore burn the claim for a genuine
notification, and the customer would never receive the real thing. So this builds the
message itself from the same copy builders and the same templates, and never writes to
the database at all.

The contexts below are FIXTURES, not reads. Nothing here touches a real subscription, so
it is safe to run against any environment whose SMTP settings you are willing to use.

Preview mode inlines the images as ``data:`` URIs so a browser shows them. Send mode
attaches them as CID parts, because that is what has to survive in a real mail client and
is therefore the only version worth reviewing before launch.
"""
from __future__ import annotations

import argparse
import base64
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import app  # noqa: E402  (the path insert above has to come first)

UTC = timezone.utc
NOW = datetime.now(UTC)

ENTITY = "Aetheria Capital Limited"
PORTAL = "https://app.dailyminty.com/profile/subscriptions"


def contexts() -> dict[str, dict]:
    """One representative context per event, in the order a customer might meet them."""
    from blueprints.subscription.services import notify

    return {
        notify.TRIAL_ENDING: {
            "entity_id": "demo-entity", "entity_name": ENTITY,
            "codes": ["PETTY_CASH", "PAYMENT_REQUEST"],
            "trial_end": NOW + timedelta(days=7),
            "amount": 28000, "currency": "HKD",
            "needs_card": True, "needs_consent": False,
        },
        notify.RENEWAL_FAILED: {
            "total": 68000, "currency": "HKD",
            "deadline": NOW + timedelta(days=14),
        },
        notify.DUNNING_RETRY_FAILED: {
            "attempts": 2, "deadline": NOW + timedelta(days=9),
        },
        notify.PAYMENT_RECOVERED: {},
        notify.SUBSCRIBER_TRANSFER_REQUESTED: {
            "entity_id": "demo-entity", "entity_name": ENTITY,
            "from_name": "Rebecca Park", "to_name": "John Doe",
            "amount": 68000, "currency": "HKD",
            "billed_through": NOW + timedelta(days=21),
            "expires_at": NOW + timedelta(days=7),
            "portal_url": PORTAL,
        },
        notify.SUBSCRIBER_TRANSFER_ACCEPTED: {
            "entity_id": "demo-entity", "entity_name": ENTITY,
            "from_name": "Rebecca Park", "to_name": "John Doe",
            "portal_url": PORTAL,
        },
        notify.SUBSCRIBER_TRANSFER_DECLINED: {
            "entity_id": "demo-entity", "entity_name": ENTITY,
            "from_name": "Rebecca Park", "to_name": "John Doe",
            "portal_url": PORTAL,
        },
        notify.SUBSCRIBER_TRANSFER_EXPIRED: {
            "entity_id": "demo-entity", "entity_name": ENTITY,
            "from_name": "Rebecca Park", "to_name": "John Doe",
            "portal_url": PORTAL,
        },
    }


def render(event: str, ctx: dict, *, inline: bool):
    """``(subject, html, logo_bytes, art_bytes)`` for one event.

    ``inline`` swaps the CID references for ``data:`` URIs so the result stands alone in a
    browser. The template takes the image as a plain ``src`` rather than a bare CID
    precisely so this substitution is possible.
    """
    from flask import render_template

    from blueprints.subscription.services import notify

    content = notify._COPY[event](ctx)
    logo = notify.logo_bytes()
    art = notify.image_bytes(*notify.illustration_path(event))

    def ref(data: bytes | None, cid: str) -> str | None:
        if not data:
            return None
        if inline:
            return "data:image/png;base64," + base64.b64encode(data).decode()
        return f"cid:{cid}"

    html = render_template(
        notify.NOTICE_TEMPLATE,
        first_name="Angelika",
        base_url=notify.base_url(),
        logo_src=ref(logo, notify.LOGO_CID),
        illustration_src=ref(art, notify.ILLUSTRATION_CID),
        **content,
    )
    return content["subject"], html, logo, art


#: The events with a mockup of their own. ``dunning_retry_failed`` is deliberately not
#: here even though it has art: it reuses the payment-failure design, so reviewing it
#: alongside ``renewal_failed`` shows the same page twice.
MOCKED = (
    "trial_ending",
    "renewal_failed",
    "payment_recovered",
    "subscriber_transfer_requested",
    "subscriber_transfer_accepted",
    "subscriber_transfer_declined",
    "subscriber_transfer_expired",
)


def selected(only: str | None) -> dict[str, dict]:
    """The events to render: everything, the mocked seven, or a named subset."""
    everything = contexts()
    if not only:
        return everything
    if only == "mocked":
        return {k: v for k, v in everything.items() if k in MOCKED}
    wanted = [name.strip() for name in only.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in everything]
    if unknown:
        raise SystemExit(f"Unknown event(s): {', '.join(unknown)}")
    return {k: everything[k] for k in wanted}


def write_files(out: Path, chosen: dict[str, dict]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for index, (event, ctx) in enumerate(chosen.items(), start=1):
        subject, html, _, art = render(event, ctx, inline=True)
        path = out / f"{index:02d}_{event}.html"
        path.write_text(html, encoding="utf-8")
        flag = "" if art else "   (no illustration yet)"
        print(f"  {path.name:44s} {subject}{flag}")
    print(f"\nWrote {len(chosen)} files to {out}")
    return 0


def send_all(address: str, chosen: dict[str, dict]) -> int:
    from flask import current_app

    from blueprints.subscription.services import notify

    mail = current_app.extensions.get("mail")
    if mail is None or not current_app.config.get("MAIL_SERVER"):
        print("No SMTP_URL configured — nothing was sent.", file=sys.stderr)
        return 1
    if current_app.config.get("TESTING"):
        # MAIL_SUPPRESS_SEND follows TESTING, so this would silently swallow the batch
        # and report success.
        print("TESTING is on; mail would be suppressed. Aborting.", file=sys.stderr)
        return 1

    # The same resolver the real sends use, so a review copy cannot arrive from a
    # different address than the thing it is reviewing.
    sender = notify.billing_sender()
    failures = 0
    for event, ctx in chosen.items():
        subject, html, logo, art = render(event, ctx, inline=False)
        message = notify.InlineImageMessage(
            subject=subject, sender=sender, recipients=[address], html=html
        )
        for data, cid, name in ((logo, notify.LOGO_CID, "logo.png"),
                                (art, notify.ILLUSTRATION_CID, "illustration.png")):
            if data:
                message.attach(
                    name, "image/png", data, "inline",
                    # Angle brackets in the header, none in the src.
                    headers={"Content-ID": f"<{cid}>", "X-Attachment-Id": cid},
                )
        try:
            mail.send(message)
            print(f"  sent  {event:34s} {subject}")
        except Exception as exc:  # noqa: BLE001 - report every one, stop for none
            failures += 1
            print(f"  FAIL  {event:34s} {exc}", file=sys.stderr)

    print(f"\n{len(chosen) - failures}/{len(chosen)} sent to {address}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send", metavar="ADDRESS",
        help="send real mail to this address instead of writing files",
    )
    parser.add_argument(
        "--out", default="_email_preview", type=Path,
        help="directory for the HTML files (default: _email_preview)",
    )
    parser.add_argument(
        "--only", metavar="EVENTS",
        help='comma-separated event keys, or "mocked" for the seven with a mockup '
             "of their own",
    )
    args = parser.parse_args()

    with app.app_context():
        chosen = selected(args.only)
        return (send_all(args.send, chosen) if args.send
                else write_files(args.out, chosen))


if __name__ == "__main__":
    raise SystemExit(main())
