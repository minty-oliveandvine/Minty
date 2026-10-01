import html
import os
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user
from flask_mail import Message
from loguru import logger
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash

from blueprints.auth import auth_bp
from blueprints.auth.forms import RequestResetForm, ResetPasswordForm
from blueprints.auth.services.email_auth import _as_utc
from blueprints.auth.services.identity import normalize_email
from models.db import User, db

# How long an emailed reset link works. The email states it, so it comes from here.
RESET_LINK_TTL_HOURS = 1

# The one answer to a reset request, whether or not the address has an account.
# "I've sent a link to X" for a real account and "that doesn't look familiar" for
# an unknown one let anyone check who is signed up. The category matters as much
# as the words: it sets the toast's colour.
_RESET_REQUESTED_FLASH = (
    "If that email has a Minty account, a reset link is on its way — it can take "
    "a few minutes to arrive."
)


@auth_bp.route("/reset_password", methods=["GET", "POST"])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for("auth.home"))
    form = RequestResetForm()
    if form.validate_on_submit():
        user = _find_user_for_reset(form.email.data)
        # Prefer email; username holds the address for OTP, invite and Xero sign-ups.
        recipient = (user.email or user.username) if user else None
        if not recipient or "@" not in recipient:
            # No account, or none with an address to write to: answer exactly as
            # if a link went out, and send nothing.
            flash(_RESET_REQUESTED_FLASH, "info")
            return redirect(url_for("auth.login"))
        mail = current_app.extensions.get("mail")
        if mail is None:
            logger.error("Mail extension not configured - no password reset link sent")
            flash(
                "We couldn't send a reset email — our mail service isn't reachable right now. Please let your administrator know.",
                "danger",
            )
            return redirect(url_for("auth.login"))
        # Read now: a rollback expires `user`, and reloading it could fail as well.
        user_id = user.id
        token = str(uuid.uuid4())
        user.reset_token = token
        # Aware UTC: the column is timestamptz, and reset_token() compares with an
        # aware "now".
        user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(
            hours=RESET_LINK_TTL_HOURS
        )
        try:
            # Commit first: a link that arrives before its token is saved would
            # not work, while a saved token whose email never went out is
            # harmless (it lapses, and the next request replaces it).
            db.session.commit()
            mail.send(_reset_message(recipient, token))
        except Exception:
            db.session.rollback()
            logger.exception(f"Could not send a password reset link to user {user_id}")
            flash(
                "I couldn't get your reset link sent just now. Please try "
                "again in a few minutes, or tell your administrator if it "
                "keeps happening.",
                "danger",
            )
            return redirect(url_for("auth.login"))
        logger.info(f"Password reset link sent to {recipient}")
        flash(_RESET_REQUESTED_FLASH, "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for("auth.home"))
    user = User.query.filter_by(reset_token=token).first()
    if user is None:
        flash(
            "This reset link doesn't work anymore. Want me to send a fresh one?",
            "warning",
        )
        return redirect(url_for("auth.reset_request"))
    # Postgres hands the timestamptz back aware, and comparing it with a naive
    # datetime.now() raised TypeError - every reset link answered 500. A naive value
    # can only be a pre-timestamptz row; _as_utc reads it as UTC.
    if user.reset_token_expiry and _as_utc(user.reset_token_expiry) < datetime.now(
        timezone.utc
    ):
        flash("This reset link has expired. Want me to send a fresh one?", "warning")
        return redirect(url_for("auth.reset_request"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Read now: a rollback expires `user`, and reloading it could fail as well.
        user_id = user.id
        try:
            if form.password.data is None:
                flash("I can't let you in without a password.", "danger")
                return render_template("reset_token.html", form=form, token=token)
            hashed_password = generate_password_hash(
                form.password.data, method="pbkdf2:sha256"
            )
            user.password = hashed_password
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash("Your password is all set — you can log in now.", "success")
            return redirect(url_for("auth.login"))
        except Exception:
            db.session.rollback()
            logger.exception(f"Could not save a new password for user {user_id}")
            flash(
                "I couldn't save your new password. Mind trying again?",
                "danger",
            )
    return render_template("reset_token.html", form=form, token=token)


def _find_user_for_reset(address: str | None) -> User | None:
    """The account a reset request names: ``address`` matched case-insensitively
    on ``email`` or ``username`` (the username IS the address for OTP, invite and
    Xero sign-ups, and an exact match missed any address typed in another case)."""
    normalized = normalize_email(address)
    if normalized is None:
        return None
    return User.query.filter(
        or_(
            func.lower(User.email) == normalized,
            func.lower(User.username) == normalized,
        )
    ).first()


def _reset_message(recipient: str, token: str) -> Message:
    """The reset email. Its links are built on PUBLIC_URL, as the invitation
    email's are: the request host is whichever proxy or internal name the request
    arrived on, which is not necessarily one the recipient can reach."""
    # The invitation service's helpers, imported rather than copied so emailed assets keep
    # ONE content-fingerprint cache and one rule for their host. Imported here, as
    # auth.email_handoff does, to keep the invitation package out of import time.
    from blueprints.invitation.services.invite import _asset_url, email_base_url

    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    reset_url = (
        f"{public_url}{url_for('auth.reset_token', token=token)}"
        if public_url
        else url_for("auth.reset_token", token=token, _external=True)
    )
    return Message(
        subject="Reset your Minty password",
        sender=current_app.config.get("BREVO_EMAIL"),
        recipients=[recipient],
        html=_build_reset_html(
            reset_url, _asset_url(email_base_url(), "img/minty-mark.png")
        ),
    )


def _build_reset_html(reset_url: str, logo_url: str) -> str:
    """The invitation email's frame (``_build_invitation_html`` in
    blueprints/invitation/services/invite.py): a white 520px card on #f0f4f8, the
    Minty mark, one #54D3DA button. Every interpolated value is escaped."""
    url = html.escape(reset_url)
    logo = html.escape(logo_url)
    ttl = f"{RESET_LINK_TTL_HOURS} hour{'' if RESET_LINK_TTL_HOURS == 1 else 's'}"
    year = datetime.now(timezone.utc).year
    return f"""\
<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="x-apple-disable-message-reformatting">
<title>Reset your Minty password</title>
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
    Choose a new Minty password. The link works for {ttl}.
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
          <img src="{logo}" alt="Minty" width="72"
               style="display:block;border:0;width:72px;max-width:72px;height:auto;margin:0 auto;" />
        </td></tr>

        <!-- Body -->
        <tr><td class="m-pad m-body" style="padding:36px 40px 0 40px;">
          <h1 class="m-h1" style="color:#2d3748;font-size:22px;margin:0 0 8px 0;text-align:center;">
            Reset your password
          </h1>
          <p style="color:#718096;font-size:14px;line-height:1.6;text-align:center;margin:0;">
            We got a request to reset the password on your Minty account.
            Choose a new one with the button below.
          </p>
        </td></tr>

        <!-- CTA Button -->
        <tr><td class="m-cta" style="text-align:center;padding:32px 40px;">
          <a href="{url}" class="m-btn"
             style="display:inline-block;background:#54D3DA;color:#ffffff;text-decoration:none;
                    padding:14px 48px;border-radius:8px;font-weight:600;font-size:16px;
                    line-height:1.2;text-align:center;
                    box-shadow:0 2px 8px rgba(84,211,218,0.35);">
            Choose a new password
          </a>
        </td></tr>

        <tr><td class="m-pad" style="padding:0 40px 28px 40px;">
          <p style="color:#718096;font-size:13px;line-height:1.6;text-align:center;margin:0;
                    word-break:break-word;">
            This link expires in {ttl}. If the button doesn&#39;t work, paste this
            address into your browser:<br />
            <a href="{url}" style="color:#3BB8BF;word-break:break-all;">{url}</a>
          </p>
        </td></tr>

        <!-- Footer -->
        <tr><td class="m-pad"
                style="padding:16px 40px 24px 40px;text-align:center;border-top:1px solid #e2e8f0;">
          <p style="color:#a0aec0;font-size:12px;line-height:1.5;margin:0;">
            If you didn&#39;t ask to reset your password, you can safely ignore this
            email &mdash; your password stays as it is.<br />
            &copy; {year} Minty &mdash; Petty Cash Management
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
