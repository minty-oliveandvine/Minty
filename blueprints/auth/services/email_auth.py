import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from loguru import logger
from werkzeug.security import check_password_hash, generate_password_hash

from blueprints.auth.models.email_otp import EmailOtp
from blueprints.auth.services.identity import resolve_user_by_email
from blueprints.shared.email_rules import EMAIL_ASCII_MESSAGE, is_ascii_email
from models.db import User, db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """``email_otp`` timestamps are ``timestamptz``; Postgres hands them back aware, SQLite
    hands them back naive (and they were written as UTC). Compare in one time zone."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

# A code is valid for 60 seconds; after it expires the user may request a new
# one (the resend cooldown matches so a resend lands right as the code lapses).
OTP_EXPIRY_SECONDS = 60
MAX_OTP_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
# Brute-force lockout: once an email reaches MAX_OTP_ATTEMPTS failed codes it is
# locked for LOCKOUT_MINUTES. The failure count lives in email_otp.attempts and
# is CARRIED FORWARD across resends (see request_email_otp), so requesting a
# fresh code cannot reset it — without that carry-forward the lockout would be
# trivially bypassable, because each resend deletes the prior row. The lock is
# anchored to the locked row's created_at and auto-clears after the window.
LOCKOUT_MINUTES = 15
SIGNUP_TOKEN_MAX_AGE = 15 * 60  # window to choose a username after verifying
_SIGNUP_SALT = "email-signup-verified"

# Error codes returned alongside the message so the route can map them to HTTP
# status (e.g. lockout → 429). Plain strings keep the (result, error) callers
# working unchanged while a third return slot carries the code.
ERR_LOCKED = "locked"


def _lockout_remaining_seconds(otp: EmailOtp) -> int:
    """Seconds left on an active lockout for this OTP row, else 0.

    An email is locked once its (carried-forward) ``attempts`` reaches
    MAX_OTP_ATTEMPTS; the lock runs LOCKOUT_MINUTES from the row's ``created_at``
    and then auto-clears.
    """
    if otp is None or otp.attempts < MAX_OTP_ATTEMPTS or not otp.created_at:
        return 0
    unlock_at = _as_utc(otp.created_at) + timedelta(minutes=LOCKOUT_MINUTES)
    remaining = (unlock_at - _utcnow()).total_seconds()
    return int(remaining) if remaining > 0 else 0


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_otp() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def request_email_otp(email: str) -> tuple[bool, str | None]:
    """Issue and email a code for `email`. Works for both new and existing emails.

    Nothing is saved unless the email goes out: a failed send answers
    ``(False, message)`` and leaves the address's ``email_otp`` rows as they were.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "A valid email is required."
    if not is_ascii_email(email):
        return False, EMAIL_ASCII_MESSAGE

    latest = (
        EmailOtp.query.filter_by(email=email)
        .order_by(EmailOtp.created_at.desc())
        .first()
    )

    # While locked out, refuse to issue a new code — otherwise the lockout would
    # be bypassable by spamming resend. The lock auto-clears after the window.
    locked_seconds = _lockout_remaining_seconds(latest)
    if locked_seconds > 0:
        minutes = max(1, (locked_seconds + 59) // 60)
        return False, f"Too many attempts. Try again in about {minutes} minute(s)."

    if (
        latest
        and (_utcnow() - _as_utc(latest.created_at)).total_seconds()
        < RESEND_COOLDOWN_SECONDS
    ):
        return False, "Please wait a moment before requesting another code."

    # Carry the failure count forward across resends so a fresh code can't reset
    # the brute-force counter. Important: if we got here with attempts already at
    # MAX, the lock window has ELAPSED (an active lock returned above), so we
    # must NOT carry the maxed count — anchoring MAX onto the new row's
    # created_at would immediately re-lock it for another window. In that case
    # the window is over, so reset to 0 and let the user try again.
    prior = latest.attempts if latest else 0
    carried_attempts = 0 if prior >= MAX_OTP_ATTEMPTS else prior

    EmailOtp.query.filter_by(email=email).delete()  # supersede any prior codes

    code = generate_otp()
    db.session.add(
        EmailOtp(
            email=email,
            code_hash=generate_password_hash(code, method="pbkdf2:sha256"),
            expires_at=_utcnow() + timedelta(seconds=OTP_EXPIRY_SECONDS),
            attempts=carried_attempts,
        )
    )
    # Flush, send, and only then commit. Committing before the send meant a failed
    # send still left the new row behind: the user was told a code was on its way,
    # the row started the resend cooldown (so their retry was refused) and it made a
    # brand-new address look registered to the login page's check. Rolling back
    # undoes the delete above as well, so the previous row comes back with its
    # carried attempts and its old created_at - already past the cooldown, or we
    # would have returned above - and an immediate retry is allowed.
    db.session.flush()
    if not _send_code_email(email, code):
        db.session.rollback()
        return (
            False,
            "I couldn't send your sign-in code just now. Mind trying again in a moment?",
        )
    db.session.commit()
    return True, None


def verify_email_otp(
    email: str, code: str
) -> tuple[dict | None, str | None, str | None]:
    """Check a code. Returns ``(result, error, err_code)``.

    On success ``result`` is one of:
    {"action": "login", "user": User}                 # email already has an account
    {"action": "choose_username", "signup_token": str} # brand-new email

    On failure ``result`` is None, ``error`` is a user-facing message, and
    ``err_code`` is an optional machine code (``ERR_LOCKED`` when the email is
    in a brute-force lockout, so the route can answer 429).
    """
    email = (email or "").strip().lower()
    code = (code or "").strip()
    if not email or not code:
        return None, "Email and code are required.", None

    otp = (
        EmailOtp.query.filter_by(email=email)
        .order_by(EmailOtp.created_at.desc())
        .first()
    )
    if not otp:
        return None, "No code was requested for this email.", None

    # Brute-force gate FIRST — before the expiry/used checks — so a locked user
    # sees the lockout, not "expired" (the 60s code lapses long before the 15min
    # lock does). The count lives in otp.attempts and is carried across resends,
    # so the lock holds against fresh codes, direct API calls, and refreshes; it
    # clears only by waiting out the window or a successful verify.
    locked_seconds = _lockout_remaining_seconds(otp)
    if locked_seconds > 0:
        minutes = max(1, (locked_seconds + 59) // 60)
        return (
            None,
            f"Too many attempts. Try again in about {minutes} minute(s).",
            ERR_LOCKED,
        )
    # Lock window fully elapsed but the counter is still maxed → start fresh so
    # the next wrong code begins a new window rather than re-locking off a stale
    # created_at.
    if otp.attempts >= MAX_OTP_ATTEMPTS:
        otp.attempts = 0
        db.session.commit()

    if otp.expires_at and _as_utc(otp.expires_at) < _utcnow():
        return None, "This code has expired. Please request a new one.", None
    # Single-use: a code that's already been verified can't be replayed.
    if otp.verified_at is not None:
        return None, "This code has already been used. Please request a new one.", None
    if not check_password_hash(otp.code_hash, code):
        otp.attempts += 1
        db.session.commit()
        # That increment may have just tripped the lock.
        locked_seconds = _lockout_remaining_seconds(otp)
        if locked_seconds > 0:
            minutes = max(1, (locked_seconds + 59) // 60)
            return (
                None,
                f"Too many attempts. Try again in about {minutes} minute(s).",
                ERR_LOCKED,
            )
        return None, "Invalid code.", None

    otp.verified_at = _utcnow()
    otp.attempts = 0  # success → clear the brute-force counter for this email
    db.session.commit()

    # Resolve on either identity column: an address that equals someone's
    # xero_email logs into that same row (one user) instead of branching to a
    # new signup. To restrict to personal (non-Xero) accounts, add a
    # User.xero_user_id.is_(None) filter in resolve_user_by_email.
    existing_user = resolve_user_by_email(email)
    if existing_user:
        return {"action": "login", "user": existing_user}, None, None

    token = _serializer().dumps({"email": email}, salt=_SIGNUP_SALT)
    return {"action": "choose_username", "signup_token": token}, None, None


def complete_email_signup(
    signup_token: str,
    username: str,
    first_name: str,
    last_name: str,
) -> tuple[User | None, str | None]:
    """Create the passwordless personal account after the username step."""
    try:
        data = _serializer().loads(
            signup_token, salt=_SIGNUP_SALT, max_age=SIGNUP_TOKEN_MAX_AGE
        )
    except SignatureExpired:
        return None, "Your verification expired. Please start again."
    except BadSignature:
        return None, "Invalid verification. Please start again."

    email = (data.get("email") or "").strip().lower()
    username = (username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()

    if not email:
        return None, "Invalid verification. Please start again."
    if not username:
        return None, "A username is required."
    if not first_name or not last_name:
        # Flip to first_name = first_name or "" / last_name or "" for name-less signup.
        return None, "First and last name are required."

    if resolve_user_by_email(email):
        return None, "An account already exists for this email. Please log in."
    if User.query.filter_by(username=username).first():
        return None, "That username is taken."

    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        username=username,
        first_name=first_name,
        last_name=last_name,
        password=generate_password_hash(
            secrets.token_urlsafe(32), method="pbkdf2:sha256"
        ),
        system_role=User.SYSTEM_ROLE_DEFAULT,
        approved=True,
        # xero_user_id / xero_token / access_token ... all left NULL → personal account
    )
    db.session.add(new_user)
    EmailOtp.query.filter_by(email=email).delete()
    db.session.commit()
    return new_user, None


def _send_code_email(email: str, code: str) -> bool:
    mail = current_app.extensions.get("mail")
    if mail is None:
        logger.error("Mail extension not configured")
        return False
    try:
        msg = Message(
            subject="Your Minty sign-in code",
            sender=current_app.config.get("BREVO_EMAIL"),
            recipients=[email],
            html=_code_email_html(code),
        )
        mail.send(msg)
        logger.info(f"Email OTP sent to {email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send email OTP to {email}: {exc}")
        return False


def _code_email_html(code: str) -> str:
    return f"""\
<!DOCTYPE html><html><body style="margin:0;padding:40px 0;font-family:Arial,Helvetica,sans-serif;background:#f0f4f8;">
  <table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
    <table width="460" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;padding:36px 40px;box-shadow:0 4px 24px rgba(0,0,0,.08);">
      <tr><td style="text-align:center;">
        <h1 style="color:#2d3748;font-size:20px;margin:0 0 8px;">Your sign-in code</h1>
        <p style="color:#718096;font-size:14px;margin:0 0 24px;">Enter this code to continue to Minty.</p>
        <div style="font-size:34px;font-weight:700;letter-spacing:8px;color:#3BB8BF;">{code}</div>
        <p style="color:#a0aec0;font-size:12px;margin:24px 0 0;">This code expires in {OTP_EXPIRY_SECONDS} seconds. If you didn't request it, you can ignore this email.</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""
