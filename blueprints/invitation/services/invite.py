from __future__ import annotations

import hashlib
import html
import os
import secrets
from datetime import datetime, timezone, timedelta

from flask import current_app, request, url_for
from flask_mail import Message
from loguru import logger

from blueprints.invitation.models.invitation import Invitation
from models.db import Entity, User, UserEntity, db, tz
from blueprints.shared.enums import InvitationStatus

# Invitations are valid for this many days from creation (Hong Kong time).
INVITATION_TTL_DAYS = int(os.environ.get("INVITATION_TTL_DAYS", 7))

# Minimum seconds between resends of the same invitation. Enforced server-side
# and surfaced to the UI as a countdown so the resend button can disable itself.
RESEND_COOLDOWN_SECONDS = int(os.environ.get("INVITATION_RESEND_COOLDOWN_SECONDS", 60))

# In-memory record of when each invitation's email was last sent (HK time),
# keyed by invitation id. Backs the resend cooldown WITHOUT a DB column. Note:
# this lives in the worker process, so with multiple gunicorn workers the
# throttle is best-effort per-worker (a resend routed to another worker may not
# see the most recent send). Entries are pruned once they age past the cooldown.
_LAST_SENT: dict[str, datetime] = {}


def _record_sent(invitation_id: str) -> None:
    """Stamp ``invitation_id`` as just-sent and prune stale entries."""
    now = datetime.now(tz)
    cutoff = now - timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    stale = [k for k, v in _LAST_SENT.items() if v < cutoff]
    for k in stale:
        _LAST_SENT.pop(k, None)
    _LAST_SENT[invitation_id] = now


def resend_cooldown_remaining(invitation) -> int:
    """Seconds left before ``invitation`` may be resent again (0 if ready now).

    Reads the in-memory ``_LAST_SENT`` store; an invitation with no recorded
    send (e.g. after a worker restart) is treated as immediately resendable.
    """
    inv_id = getattr(invitation, "id", None) or invitation
    last_sent = _LAST_SENT.get(inv_id)
    if last_sent is None:
        return 0
    elapsed = (datetime.now(tz) - last_sent).total_seconds()
    remaining = RESEND_COOLDOWN_SECONDS - elapsed
    return int(remaining) + 1 if remaining > 0 else 0


# Accounts that must always be system superusers when invited. These are
# internal "view-all" logins; superuser grants read access across every entity.
# Comma-separated env override; defaults to the dailyminty view-all account.
# Matched case-insensitively.
AUTO_SUPERUSER_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("AUTO_SUPERUSER_EMAILS", "viewall@dailyminty.com").split(
        ","
    )
    if e.strip()
)


def _is_auto_superuser_email(email: str | None) -> bool:
    """True if ``email`` is one of the always-superuser view-all accounts."""
    return (email or "").strip().lower() in AUTO_SUPERUSER_EMAILS


def _promote_to_superuser(user: User | None) -> bool:
    """Ensure ``user`` is an approved system superuser.

    Returns True when a change was made (so the caller knows to commit). Does
    not commit itself.
    """
    if user is None:
        return False
    changed = False
    if user.system_role != User.SYSTEM_ROLE_SUPERUSER:
        user.system_role = User.SYSTEM_ROLE_SUPERUSER
        changed = True
    if not user.approved:
        user.approved = True
        changed = True
    return changed


def _is_invitation_expired(invitation) -> bool:
    """True when ``invitation`` has passed its ``expires_at`` (HK time).

    Legacy rows with no ``expires_at`` set never expire. The stored value may
    be naive (read back from a TIMESTAMP column) or tz-aware; we localize naive
    values to HK before comparing, mirroring the token-expiry handling.
    """
    expires_at = getattr(invitation, "expires_at", None)
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = tz.localize(expires_at)
    return datetime.now(tz) > expires_at


def create_invitation(
    entity_id: str,
    email: str,
    role: str,
    invited_by: str,
    first_name: str = "",
    last_name: str = "",
) -> tuple[Invitation | None, str | None]:
    """Create an invitation record and return (invitation, error_message).

    `first_name` and `last_name` are persisted on the invitation row so the
    pending-invite cards keep their name/email/role format when re-read on
    resume. They're also rolled into the accept URL (see send_invitation_email)
    so the OTP-verify path can create a User row at sign-in time for invitees
    who don't have a Xero account.
    """

    entity = Entity.query.get(entity_id)
    if not entity:
        return None, "Entity not found."

    existing_user = User.query.filter_by(email=email).first()
    if not existing_user:
        existing_user = User.query.filter_by(username=email).first()

    # The dailyminty view-all account is always a system superuser. If a row
    # already exists for this address, promote it now so the role is set even
    # before the invite is accepted. (If no row exists yet it is promoted on
    # accept, once the User is created.)
    if existing_user and _is_auto_superuser_email(email):
        if _promote_to_superuser(existing_user):
            db.session.commit()

    if existing_user:
        already_member = UserEntity.query.filter_by(
            user_id=existing_user.id, entity_id=entity_id
        ).first()
        if already_member and already_member.approved:
            return None, "This user is already a member of this entity."

    pending = Invitation.query.filter_by(
        entity_id=entity_id, email=email, status="pending"
    ).first()
    if pending:
        # An expired pending invite shouldn't block a fresh one — lazily mark
        # it expired and continue so the resend succeeds.
        if _is_invitation_expired(pending):
            pending.status = "expired"
            db.session.commit()
        else:
            return None, "An invitation is already pending for this email."

    token = secrets.token_urlsafe(48)

    invitation = Invitation(
        entity_id=entity_id,
        email=email,
        role=role,
        token=token,
        status="pending",
        invited_by=invited_by,
        first_name=(first_name or "").strip() or None,
        last_name=(last_name or "").strip() or None,
        expires_at=datetime.now(tz) + timedelta(days=INVITATION_TTL_DAYS),
    )
    db.session.add(invitation)
    db.session.commit()

    return invitation, None


def send_invitation_email(
    invitation: Invitation,
    first_name: str = "",
    last_name: str = "",
) -> bool:
    """Send the invitation email. Returns True on success.

    `first_name` and `last_name` are appended to the accept URL as ?fn / ?ln
    so the OTP-verify path can create a User row for non-Xero invitees. When
    omitted they fall back to the names persisted on the invitation record,
    so resends produce the same link as the original send. If the user trims
    the URL they're lost and the User would have to be created later via
    /auth signup.
    """
    try:
        entity = Entity.query.get(invitation.entity_id)
        entity_name = entity.name if entity else "Unknown Entity"
        inviter = (
            User.query.get(invitation.invited_by) if invitation.invited_by else None
        )
        # Only the parts that are there: a blank or missing last name printed a stray
        # space (or the word "None") in the inviter's place.
        inviter_name = (
            " ".join(
                part.strip()
                for part in (inviter.first_name, inviter.last_name)
                if part and part.strip()
            )
            if inviter
            else ""
        ) or "A team member"

        from urllib.parse import urlencode

        public_url = (current_app.config.get("PETTY_CASH_URL") or "").rstrip("/")
        accept_path = url_for(
            "invitation.accept_invitation_page",
            token=invitation.token,
        )
        accept_url = (
            f"{public_url}{accept_path}"
            if public_url
            else url_for(
                "invitation.accept_invitation_page",
                token=invitation.token,
                _external=True,
            )
        )
        # Callers that don't have the names to hand (resend) get them off the record.
        first_name = first_name or invitation.first_name or ""
        last_name = last_name or invitation.last_name or ""

        name_qs = {}
        if first_name:
            name_qs["fn"] = first_name
        if last_name:
            name_qs["ln"] = last_name
        if name_qs:
            sep = "&" if "?" in accept_url else "?"
            accept_url = f"{accept_url}{sep}{urlencode(name_qs)}"

        mail = current_app.extensions.get("mail")
        if mail is None:
            logger.error("Mail extension not configured")
            return False

        logo_url = _asset_url(email_base_url(), "img/minty-mark.png")

        msg = Message(
            # One line: a company name carrying a line break is a header Flask-Mail
            # refuses (BadHeaderError), and the except below would swallow the send.
            subject=f"You've been invited to {' '.join(entity_name.split())} on Minty",
            sender=current_app.config.get("MAIL_FROM"),
            recipients=[invitation.email],
            html=_build_invitation_html(
                entity_name=entity_name,
                role=invitation.role,
                inviter_name=inviter_name,
                accept_url=accept_url,
                logo_url=logo_url,
            ),
        )
        mail.send(msg)
        _record_sent(invitation.id)
        logger.info(
            f"Invitation email sent to {invitation.email} for entity {entity_name}"
        )
        return True
    except Exception as exc:
        logger.error(f"Failed to send invitation email to {invitation.email}: {exc}")
        return False


def accept_invitation(
    token: str, user_id: str
) -> tuple[str | None, str | None, str | None]:
    """Accept an invitation. Returns (entity_id, error_message, status_hint).

    status_hint is one of: 'dashboard', 'xero_not_connected', or None on error.

    Idempotent: re-accepting an invitation that this same user already accepted
    is a no-op success (returns the entity_id), not an error — so a retried
    handoff or double-click can't strand the user with "already used".
    """
    invitation = (
        Invitation.query.filter_by(token=token)
        .filter(Invitation.status.in_(("pending", "accepted")))
        .first()
    )
    if not invitation:
        logger.info("invitation.accept.invalid user={}", user_id)
        return None, "Invitation is invalid or has already been used.", None

    # Reject expired pending invites (an already-accepted invite stays valid so
    # the idempotent re-accept below still works). Mark it expired lazily.
    if invitation.status == "pending" and _is_invitation_expired(invitation):
        invitation.status = "expired"
        db.session.commit()
        logger.info(
            "invitation.accept.expired invitation={} entity={} email={} user={}",
            invitation.id,
            invitation.entity_id,
            invitation.email,
            user_id,
        )
        return None, "This invitation has expired. Please request a new one.", None

    user = User.query.get(user_id)
    if not user:
        logger.info(
            "invitation.accept.no_user invitation={} user={}", invitation.id, user_id
        )
        return None, "User not found.", None

    # Ownership check. The invite was sent to invitation.email; the user proves
    # they own that inbox either by carrying it on any identity column (email /
    # xero_email / username) — the OTP flow has already verified the code was
    # delivered to that address before calling here.
    invited = invitation.email.lower()
    owned = {
        (user.email or "").lower(),
        (user.xero_email or "").lower(),
        (user.username or "").lower(),
    }
    if invited not in owned:
        logger.warning(
            "invitation.accept.email_mismatch invitation={} entity={} invited={} user={}",
            invitation.id,
            invitation.entity_id,
            invited,
            user_id,
        )
        return (
            None,
            "This invite went to a different account — mind signing in as that one?",
            None,
        )

    # The dailyminty view-all account is always a system superuser. Apply this
    # before the re-accept short-circuit below so it holds on every accept path.
    if _is_auto_superuser_email(invitation.email) and _promote_to_superuser(user):
        db.session.commit()

    # An already-accepted invite for THIS user (re-accept) short-circuits to
    # success; for a DIFFERENT user it's a genuine conflict.
    if invitation.status == "accepted":
        existing_member = UserEntity.query.filter_by(
            user_id=user.id, entity_id=invitation.entity_id
        ).first()
        if existing_member:
            logger.info(
                "invitation.accept.reaccept invitation={} entity={} user={}",
                invitation.id,
                invitation.entity_id,
                user_id,
            )
            return invitation.entity_id, None, "dashboard"
        logger.warning(
            "invitation.accept.conflict invitation={} entity={} user={} reason=accepted_by_other",
            invitation.id,
            invitation.entity_id,
            user_id,
        )
        return None, "Invitation is invalid or has already been used.", None

    entity = Entity.query.get(invitation.entity_id)
    if not entity:
        logger.warning(
            "invitation.accept.no_entity invitation={} entity={} user={}",
            invitation.id,
            invitation.entity_id,
            user_id,
        )
        return None, "The entity no longer exists.", None

    existing = UserEntity.query.filter_by(
        user_id=user.id, entity_id=invitation.entity_id
    ).first()
    if existing:
        existing.role = invitation.role
        existing.approved = True
        existing.joined_at = datetime.utcnow()
    else:
        user_entity = UserEntity(
            user_id=user.id,
            entity_id=invitation.entity_id,
            role=invitation.role,
            approved=True,
            joined_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(user_entity)

    # Accepting a valid invitation IS the approval: clear the account-level
    # gate so the invitee can log in. The OTP login path checks User.approved,
    # which is separate from the per-entity UserEntity.approved set above.
    user.approved = True

    invitation.status = "accepted"
    invitation.accepted_at = datetime.utcnow()
    db.session.commit()

    logger.info(
        "invitation.accept.ok invitation={} entity={} email={} role={} user={}",
        invitation.id,
        invitation.entity_id,
        invitation.email,
        invitation.role,
        user_id,
    )

    # Invited users don't need their own Xero connection — the entity
    # owner's token is used for Xero API calls.  Always send them to the
    # dashboard so they can start working immediately.
    return invitation.entity_id, None, "dashboard"


def get_pending_invitations(entity_id: str) -> list[Invitation]:
    return (
        Invitation.query.filter_by(entity_id=entity_id, status="pending")
        .order_by(Invitation.created_at.desc())
        .all()
    )


def cancel_invitation(invitation_id: str) -> tuple[bool, str | None]:
    invitation = Invitation.query.filter_by(id=invitation_id, status="pending").first()
    if not invitation:
        return False, "Invitation not found or already processed."
    invitation.status = InvitationStatus.REVOKED  # the enum word for "cancelled"
    db.session.commit()
    return True, None


def resend_invitation(
    invitation_id: str, actor_id: str | None = None
) -> tuple[Invitation | None, str | None, int]:
    """Rotate a pending invitation's token and refresh its expiry for resend.

    Returns (invitation, error_message, retry_after_seconds).

    - Rate-limited: if the invite was sent within ``RESEND_COOLDOWN_SECONDS``,
      returns an error and the remaining cooldown in ``retry_after_seconds``.
    - The accept token is regenerated so any previously delivered link is
      invalidated; only the freshly emailed link works after a resend.
    - The TTL is reset from now so a near-expired invite becomes valid again.

    The caller is responsible for sending the email (which records the send
    time in ``_LAST_SENT``); this function only prepares the row and logs.
    """
    invitation = Invitation.query.filter_by(id=invitation_id, status="pending").first()
    if not invitation:
        return None, "Invitation not found or already processed.", 0

    remaining = resend_cooldown_remaining(invitation)
    if remaining > 0:
        logger.info(
            f"Resend of invitation {invitation.id} ({invitation.email}) blocked by "
            f"cooldown; {remaining}s remaining (actor={actor_id})"
        )
        return (
            None,
            f"Please wait {remaining}s before resending this invitation.",
            remaining,
        )

    # Invalidate any previously delivered link by rotating the accept token.
    invitation.token = secrets.token_urlsafe(48)
    invitation.expires_at = datetime.now(tz) + timedelta(days=INVITATION_TTL_DAYS)
    db.session.commit()

    logger.info(
        f"Invitation {invitation.id} resent to {invitation.email} for entity "
        f"{invitation.entity_id} (role={invitation.role}, actor={actor_id}); "
        f"previous link invalidated"
    )

    return invitation, None, 0


def _is_user_in_xero_org(user: User, entity: Entity) -> bool:
    """Check if the user's Xero account is connected to the entity's Xero org."""
    if not entity.xero_org_id:
        return False

    if not user.access_token:
        return False

    try:
        import requests as http_requests

        headers = {
            "Authorization": f"Bearer {user.access_token}",
            "Content-Type": "application/json",
        }
        resp = http_requests.get(
            "https://api.xero.com/connections", headers=headers, timeout=10
        )
        if resp.status_code != 200:
            return False

        connections = resp.json()
        for conn in connections:
            if conn.get("tenantId") == str(entity.xero_org_id):
                return True
    except Exception as exc:
        logger.warning(f"Xero connection check failed for user {user.id}: {exc}")

    return False


# Content fingerprints for static assets embedded in outbound email, keyed by
# path relative to the static folder. Mail clients (Gmail in particular) proxy
# and cache remote images by URL and hold them indefinitely, so replacing an
# image in place is invisible to anyone who was sent the old one. Appending a
# content hash gives each revision its own URL, forcing a refetch.
_ASSET_FINGERPRINTS: dict[str, str] = {}


def email_base_url() -> str:
    """The site root an emailed asset is served from: ``PETTY_CASH_URL``, else this request's.

    Not ``url_for("static", filename="", _external=True)``: that already ends in
    ``/static``, ``_asset_url`` adds another, and the logo 404'd wherever ``PETTY_CASH_URL``
    was unset. Shared with the password-reset email. Needs a request when ``PETTY_CASH_URL`` is
    unset; every sender of these emails runs inside one.
    """
    return (current_app.config.get("PETTY_CASH_URL") or "").rstrip("/") or request.url_root.rstrip("/")


def _asset_url(base_url: str, rel_path: str) -> str:
    """Return the absolute URL for a static asset, fingerprinted by content.

    Falls back to the plain URL if the file cannot be read, so a missing or
    unreadable asset degrades to the previous behaviour rather than failing
    the send.
    """
    digest = _ASSET_FINGERPRINTS.get(rel_path)
    if digest is None:
        try:
            static_folder = current_app.static_folder or "static"
            full_path = os.path.join(static_folder, *rel_path.split("/"))
            with open(full_path, "rb") as handle:
                digest = hashlib.md5(handle.read()).hexdigest()[:10]
        except OSError as exc:
            logger.warning(f"Could not fingerprint static asset {rel_path}: {exc}")
            digest = ""
        _ASSET_FINGERPRINTS[rel_path] = digest

    url = f"{base_url}/static/{rel_path}"
    return f"{url}?v={digest}" if digest else url


def _build_invitation_html(
    entity_name: str,
    role: str,
    inviter_name: str,
    accept_url: str,
    logo_url: str = "",
) -> str:
    # Every value is escaped, once, here. A company or a person can be named anything -
    # "<b>Acme</b>", or a script - and the email is HTML; the URLs carry "&".
    role_display = html.escape(role.replace("_", " ").title())
    entity_name = html.escape(entity_name)
    inviter_name = html.escape(inviter_name)
    accept_url = html.escape(accept_url)
    logo_url = html.escape(logo_url)
    return f"""\
<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="x-apple-disable-message-reformatting">
<title>You&#39;ve been invited to Minty</title>
<!--[if mso]>
<xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>
<![endif]-->
<style>
  body,table,td,a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  table,td {{ mso-table-lspace:0pt; mso-table-rspace:0pt; }}
  img {{ -ms-interpolation-mode:bicubic; border:0; line-height:100%; outline:none; text-decoration:none; }}
  body {{ width:100% !important; min-width:100%; }}
  @media only screen and (max-width:600px) {{
    .m-wrap   {{ padding:20px 12px !important; }}
    .m-card   {{ width:100% !important; max-width:100% !important; border-radius:12px !important; }}
    .m-header {{ padding:20px 16px !important; }}
    .m-pad    {{ padding-left:24px !important; padding-right:24px !important; }}
    .m-body   {{ padding-top:28px !important; }}
    .m-cta    {{ padding:24px !important; }}
    .m-h1     {{ font-size:20px !important; }}
    .m-btn    {{ display:block !important;
                padding-left:16px !important; padding-right:16px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;font-family:'Inter',Arial,Helvetica,sans-serif;background:#f0f4f8;">
  <div style="display:none;font-size:1px;color:#f0f4f8;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
    {inviter_name} invited you to join {entity_name} on Minty.
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f0f4f8;">
    <tr><td align="center" class="m-wrap" style="padding:40px 12px;">

      <!--[if mso]>
      <table role="presentation" width="520" cellpadding="0" cellspacing="0" border="0"><tr><td>
      <![endif]-->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="m-card"
             style="width:100%;max-width:520px;background:#ffffff;border-radius:16px;
                    overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header: the Minty mark -->
        <tr><td class="m-header"
                style="background:#ffffff;
                       padding:24px 40px;text-align:center;">
          <img src="{logo_url}" alt="Minty" width="72"
               style="display:block;border:0;width:72px;max-width:72px;height:auto;margin:0 auto;" />
        </td></tr>

        <!-- Body -->
        <tr><td class="m-pad m-body" style="padding:36px 40px 0 40px;">
          <h1 class="m-h1" style="color:#2d3748;font-size:22px;margin:0 0 8px 0;text-align:center;">
            You&#39;ve Been Invited!
          </h1>
          <p style="color:#718096;font-size:14px;text-align:center;margin:0 0 28px 0;">
            Join your team on Minty and start collaborating.
          </p>
        </td></tr>

        <tr><td class="m-pad" style="padding:0 40px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="background:#f7fafc;border-radius:10px;">
            <tr><td style="padding:20px 24px;color:#4a5568;font-size:14px;line-height:1.7;
                           word-break:break-word;">
              <p style="margin:0 0 6px 0;">
                <strong>{inviter_name}</strong> has invited you to join
              </p>
              <p style="margin:0 0 6px 0;font-size:18px;">
                <strong style="color:#54D3DA;">{entity_name}</strong>
              </p>
              <p style="margin:0;color:#718096;">
                Role: <strong>{role_display}</strong>
              </p>
            </td></tr>
          </table>
        </td></tr>

        <!-- CTA Button -->
        <tr><td class="m-cta" style="text-align:center;padding:32px 40px;">
          <a href="{accept_url}" class="m-btn"
             style="display:inline-block;background:#54D3DA;color:#ffffff;text-decoration:none;
                    padding:14px 48px;border-radius:8px;font-weight:600;font-size:16px;
                    line-height:1.2;text-align:center;
                    box-shadow:0 2px 8px rgba(84,211,218,0.35);">
            Accept Invitation
          </a>
        </td></tr>

        <!-- Footer -->
        <tr><td class="m-pad"
                style="padding:16px 40px 24px 40px;text-align:center;border-top:1px solid #e2e8f0;">
          <p style="color:#a0aec0;font-size:12px;line-height:1.5;margin:0;">
            If you did not expect this invitation you can safely ignore this email.<br />
            &copy; {_current_year()} Minty &mdash; Petty Cash Management
          </p>
        </td></tr>

      </table>
      <!--[if mso]>
      </td></tr></table>
      <![endif]-->

    </td></tr>
  </table>
</body>
</html>"""


def _current_year() -> int:
    return datetime.utcnow().year
