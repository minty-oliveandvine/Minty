from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from loguru import logger
from sqlalchemy import func

from blueprints.auth import auth_bp
from blueprints.auth.models.email_otp import EmailOtp
from blueprints.legal.models.terms_consent import (SOURCE_SIGNUP_INVITE,
                                                   SOURCE_SIGNUP_OTP)
from blueprints.auth.services.email_auth import (
    ERR_LOCKED,
    complete_email_signup,
    request_email_otp,
    verify_email_otp,
)
from blueprints.shared.email_rules import EMAIL_ASCII_MESSAGE, is_ascii_email
from models.db import User

_HANDOFF_SALT = "auth-email-handoff"


def _email_is_registered(email: str) -> bool:
    """Whether `email` belongs to a known account, for the login-page gate.

    Checks in order:
      1. User table, ``username`` column (the primary signal — email signups
         store the email as the username).
      2. ``email_otp`` table, ``email`` column (fallback: an address that has
         been issued a code before).
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    if User.query.filter(func.lower(User.username) == email).first():
        return True
    if EmailOtp.query.filter(func.lower(EmailOtp.email) == email).first():
        return True
    return False


# Window for the browser to GET the handoff URL after a verify. 60s was too
# tight — any hiccup between minting and navigation expired the token and
# silently dropped the user back at the login page. 5 min is still one-shot.
_HANDOFF_MAX_AGE = 5 * 60  # seconds


def _post_login_redirect(user: User) -> str:
    if user.system_role == User.SYSTEM_ROLE_SUPERUSER:
        return url_for("user_management.admin")
    return url_for("auth.index")


def _handoff_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _mint_handoff_url(user_id: str, invite_token: str = "") -> str:
    """Sign a one-shot token and return the full handoff URL.

    The handoff is a same-origin GET so Flask's Set-Cookie sticks in the
    browser — cross-origin POST responses can't reliably set the session
    cookie on localhost without HTTPS + SameSite=None.
    """
    token = _handoff_serializer().dumps(
        {"user_id": str(user_id), "invite": invite_token},
        salt=_HANDOFF_SALT,
    )
    return url_for("auth.email_handoff", h=token, _external=True)


def _validate_invite_for_email(invite_token: str, verified_email: str) -> str | None:
    """Return an error message if `invite_token` can't be accepted by the person
    who just verified `verified_email`; None if it's good to proceed.

    The OTP code was delivered to `verified_email`, so requiring the invite to
    target that same address is what proves ownership of the invited inbox. We
    accept both 'pending' and 'accepted' (re-accept is idempotent downstream).
    """
    from blueprints.invitation.models.invitation import Invitation

    token = (invite_token or "").strip()
    email = (verified_email or "").strip().lower()
    if not token:
        return None
    invitation = (
        Invitation.query.filter_by(token=token)
        .filter(Invitation.status.in_(("pending", "accepted")))
        .first()
    )
    if not invitation:
        return "This invitation is invalid or has already been used."
    if invitation.email.strip().lower() != email:
        return "This invite went to a different account — mind signing in as that one?"
    return None


def _terms_consent_for_signup(data: dict) -> tuple[str | None, str | None]:
    """Resolve the Terms agreement carried by a sign-up request.

    Returns `(version_to_record, error_message)`. `version_to_record` is None
    when nothing should be recorded; `error_message` is set only when the
    request must be refused outright.

    Three cases, and the distinction matters:

    * agreed to the live version  -> record it
    * nothing sent                -> during rollout, allow (the acceptance gate
                                     catches them at the next request); once
                                     REQUIRE_TERMS_AT_SIGNUP is on, refuse
    * agreed to a DIFFERENT version -> never recorded. Filing a record against
                                     wording they did not see is worse than no
                                     record, because it looks genuine. Treated
                                     as "nothing sent".
    """
    from legal import registry

    accepted = data.get("terms_accepted") is True
    submitted_version = (data.get("terms_version") or "").strip()
    live_version = registry.current_version(registry.TERMS)

    if accepted and submitted_version == live_version:
        return live_version, None

    if accepted and submitted_version and submitted_version != live_version:
        # The Terms moved between the page loading and the code being entered.
        logger.warning(
            f"Sign-up agreed to Terms {submitted_version!r} but {live_version!r} "
            "is live; not recording."
        )
        if registry.REQUIRE_TERMS_AT_SIGNUP:
            # Its own message: telling someone who just ticked the box that
            # they must accept the Terms reads as a bug. They need to reload.
            return None, (
                "Our Terms of Use were updated while you were signing up. "
                "Please refresh the page and read the new version."
            )
        return None, None

    if registry.REQUIRE_TERMS_AT_SIGNUP:
        return None, "You must accept the Terms of Use to create an account."

    return None, None


@auth_bp.route("/auth/email/check", methods=["POST"])
def email_check():
    """Tell the login page whether an email belongs to an existing account.

    The page calls this before sending an OTP so an unregistered email is
    stopped on the login page ("Please sign up first") and never advances to
    the OTP step or creates a user.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    exists = _email_is_registered(email)
    return jsonify({"status": "success", "exists": exists})


@auth_bp.route("/auth/email/request-code", methods=["POST"])
def email_request_code():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    # English only, before anything else (shared/email_rules.py): a non-ASCII address is
    # refused for sign-up and sign-in alike - a 400 in the hint's words, not login mode's
    # 404 "Please sign up first", which would send the person to a sign-up that refuses it.
    if not is_ascii_email(email):
        return jsonify({"status": "error", "message": EMAIL_ASCII_MESSAGE}), 400

    # In login mode an OTP may only go to an existing account. This is the
    # server-side enforcement behind the login page's check — it can't be
    # bypassed by calling this endpoint directly. Registration/signup omits
    # mode (or sends mode != "login") and is unaffected, so request_email_otp
    # stays open for brand-new emails.
    if data.get("mode") == "login" and not _email_is_registered(email):
        return jsonify({"status": "error", "message": "Please sign up first"}), 404

    # Invited users only: if this OTP request carries an invite token, the email
    # they're logging in with must be the invited address. Catch the mismatch
    # here — before an OTP is sent — instead of only at verify-code. Requests
    # without an invite token are ordinary logins and skip this entirely.
    invite_token = (data.get("invite") or "").strip()
    if invite_token:
        invite_error = _validate_invite_for_email(invite_token, email)
        if invite_error:
            return jsonify({"status": "error", "message": invite_error}), 400

    ok, error = request_email_otp(email)
    if not ok:
        return (
            jsonify({"status": "error", "message": error or "Could not send a code."}),
            400,
        )
    return jsonify(
        {"status": "success", "message": "A code has been sent to your email."}
    )


@auth_bp.route("/auth/email/verify-code", methods=["POST"])
def email_verify_code():
    data = request.get_json(silent=True) or {}
    invite_token = (data.get("invite") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    result, error, err_code = verify_email_otp(
        data.get("email") or "", data.get("code") or ""
    )
    if error or result is None:
        # Lockout → 429 so the client (and any direct API caller) sees an
        # unambiguous "too many attempts" that's enforced server-side.
        status = 429 if err_code == ERR_LOCKED else 400
        return (
            jsonify({"status": "error", "message": error or "Verification failed."}),
            status,
        )

    if result["action"] == "login":
        user = result["user"]
        # Validate the invite NOW, while we still have a request/response to
        # surface an error on. The OTP was delivered to the address the user
        # just verified, so an invite whose email doesn't match that verified
        # address is rejected here instead of silently no-op'ing in the handoff
        # (which would log the user in with no entity shared — the original bug).
        if invite_token:
            verified_email = (data.get("email") or "").strip().lower()
            invite_error = _validate_invite_for_email(invite_token, verified_email)
            if invite_error:
                return jsonify({"status": "error", "message": invite_error}), 400
        # Unapproved accounts are gated here — UNLESS they're accepting an
        # invite. The invite IS the approval: the handoff runs accept_invitation
        # (which validates the token + email and clears User.approved) before
        # logging them in. A bogus invite still fails there and gets bounced,
        # so this doesn't let unapproved users in through a fake token.
        if not user.approved and not invite_token:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Your account isn't approved just yet — hang tight!",
                    }
                ),
                403,
            )
        # This person already has an account, so nothing is being created —
        # but they may still have ticked the Terms box on the way in. An
        # invitee who was invited before, or who signed up and never finished,
        # lands here rather than in the sign-up branch below.
        #
        # Honour the tick. Dropping it meant they agreed on the sign-in screen
        # and were then immediately shown the acceptance gate anyway, which
        # reads as the tick box being broken.
        #
        # Safe to call unconditionally: record_consent is idempotent (unique
        # index on user_id + terms_version), so someone who had already agreed
        # to this version gets their existing row back and nothing changes.
        # _terms_consent_for_signup returns None unless the box was ticked AND
        # the submitted version matches the live one, so a plain login records
        # nothing.
        login_terms_version, _ = _terms_consent_for_signup(data)
        if login_terms_version:
            from blueprints.legal.services.consent import record_consent
            from models.db import db

            try:
                record_consent(
                    user.id,
                    source=SOURCE_SIGNUP_INVITE if invite_token else SOURCE_SIGNUP_OTP,
                    version=login_terms_version,
                )
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 - never block a valid login
                db.session.rollback()
                logger.warning(
                    f"Could not record login-time Terms consent for {user.id}: {exc}"
                )

        # Don't login_user here — the cookie wouldn't stick on a cross-origin
        # POST response. Mint a same-origin handoff URL; the browser GETs it,
        # Flask logs the user in there and the cookie is set on a same-origin
        # response that the browser keeps.
        handoff_url = _mint_handoff_url(user.id, invite_token=invite_token)
        return jsonify(
            {"status": "success", "action": "login", "redirect_url": handoff_url}
        )
    if invite_token:
        if not (first_name and last_name):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Please contact your inviter.",
                    }
                ),
                400,
            )
        terms_version, terms_error = _terms_consent_for_signup(data)
        if terms_error:
            return jsonify({"status": "error", "message": terms_error}), 400
        new_user = _create_passwordless_user(
            email=(data.get("email") or "").strip().lower(),
            first_name=first_name,
            last_name=last_name,
            consent_source=SOURCE_SIGNUP_INVITE if terms_version else None,
            terms_version=terms_version,
        )
        if new_user is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Could not create your account. Please contact your inviter.",
                    }
                ),
                400,
            )
        handoff_url = _mint_handoff_url(new_user.id, invite_token=invite_token)
        return jsonify(
            {"status": "success", "action": "login", "redirect_url": handoff_url}
        )

    # Brand-new email, no invite. Self-serve signup: if the signup page sent a
    # name, create the account directly (same passwordless/approved row as an
    # invitee) and hand off to login. Without a name this was a plain "Log in
    # with OTP" for an address that has no account — guide them to sign up.
    if not (first_name and last_name):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "No account found for this email — please sign up.",
                }
            ),
            404,
        )
    terms_version, terms_error = _terms_consent_for_signup(data)
    if terms_error:
        return jsonify({"status": "error", "message": terms_error}), 400
    new_user = _create_passwordless_user(
        email=(data.get("email") or "").strip().lower(),
        first_name=first_name,
        last_name=last_name,
        consent_source=SOURCE_SIGNUP_OTP if terms_version else None,
        terms_version=terms_version,
    )
    if new_user is None:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not create your account. Please try again.",
                }
            ),
            400,
        )
    handoff_url = _mint_handoff_url(new_user.id)
    return jsonify(
        {"status": "success", "action": "login", "redirect_url": handoff_url}
    )


def _create_passwordless_user(
    email: str,
    first_name: str,
    last_name: str,
    consent_source: str | None = None,
    terms_version: str | None = None,
):
    """Create a passwordless, Xero-less User row for someone who just verified
    their email via OTP — shared by the invite-accept and self-serve signup
    paths. The username is set to the email since the User model requires a
    unique non-null username. password is a hashed random string (never used —
    login is OTP-only).

    When `consent_source` is given, the Terms consent row is written in the
    SAME transaction as the User row. That is the point of doing it here rather
    than in the caller: if either fails, neither is saved, so there is never an
    account without an agreement nor an agreement without an account.
    """
    import secrets
    import uuid

    from werkzeug.security import generate_password_hash

    from blueprints.auth.services.identity import resolve_user_by_email
    from blueprints.legal.services.consent import record_consent
    from models.db import db

    try:
        # Reuse any row that already owns this address on either identity column
        # (personal email or Xero email) so we never duplicate a person or trip
        # the unique-username constraint.
        existing = (
            resolve_user_by_email(email) or User.query.filter_by(username=email).first()
        )
        if existing:
            return existing  # race — someone else created it; reuse it.
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            username=email,
            first_name=first_name,
            last_name=last_name,
            password=generate_password_hash(
                secrets.token_urlsafe(32), method="pbkdf2:sha256"
            ),
            system_role=User.SYSTEM_ROLE_DEFAULT,
            approved=True,
        )
        db.session.add(user)

        # Same transaction as the User row — see the docstring. `user.id` is
        # assigned above rather than by the database, so no flush is needed to
        # know it.
        if consent_source:
            record_consent(
                user.id, source=consent_source, version=terms_version
            )

        db.session.commit()
        logger.info(
            f"Created passwordless User {user.id} for {email}"
            + (f" with Terms consent ({consent_source})" if consent_source else "")
        )
        return user
    except Exception as exc:
        # The rollback matters now that two rows ride on this transaction: a
        # half-written signup left pending would otherwise leak into whatever
        # the next request does with this session.
        db.session.rollback()
        logger.error(f"Failed to create passwordless User for {email}: {exc}")
        return None


@auth_bp.route("/auth/email/complete", methods=["POST"])
def email_complete_signup():
    data = request.get_json(silent=True) or {}
    user, error = complete_email_signup(
        signup_token=data.get("signup_token") or "",
        username=data.get("username") or "",
        first_name=data.get("first_name") or "",
        last_name=data.get("last_name") or "",
    )
    if error or user is None:
        return (
            jsonify(
                {"status": "error", "message": error or "Could not complete sign-up."}
            ),
            400,
        )
    login_user(user)
    return jsonify(
        {
            "status": "success",
            "action": "login",
            "redirect_url": _post_login_redirect(user),
        }
    )


@auth_bp.route("/auth/email/handoff", methods=["GET"])
def email_handoff():
    """Same-origin landing after a cross-origin OTP verify.

    The browser arrives here via a top-level navigation, so login_user's
    Set-Cookie sticks. We resolve the invite (if any) before redirecting
    to the destination page so the user lands as a confirmed member.
    """
    token = (request.args.get("h") or "").strip()
    if not token:
        logger.warning("Handoff: no token in request — redirecting to login.")
        return redirect(url_for("auth.home"))

    try:
        payload = _handoff_serializer().loads(
            token, salt=_HANDOFF_SALT, max_age=_HANDOFF_MAX_AGE
        )
    except SignatureExpired:
        logger.warning(
            f"Handoff: token expired (older than {_HANDOFF_MAX_AGE}s) — redirecting to login."
        )
        return redirect(url_for("auth.home"))
    except BadSignature:
        logger.warning("Handoff: bad token signature — redirecting to login.")
        return redirect(url_for("auth.home"))

    user_id = payload.get("user_id") or ""
    user = User.query.get(user_id)
    if not user:
        logger.warning(
            f"Handoff: no user found for id {user_id!r} — redirecting to login."
        )
        return redirect(url_for("auth.home"))
    invite_token = (payload.get("invite") or "").strip()
    if invite_token:
        # Accept BEFORE the approval gate: a valid invitation clears
        # User.approved, which is what lets a not-yet-approved invitee in. A
        # bogus/expired invite returns an error and falls through to the normal
        # approval check below — so it can't be used to bypass approval.
        from blueprints.invitation.services.invite import accept_invitation

        entity_id, accept_error, _hint = accept_invitation(invite_token, user.id)
        if not accept_error:
            login_user(user)
            logger.info(
                f"Handoff: user {user.id} accepted invite to entity {entity_id}."
            )
            return redirect(url_for("entity.report_dashboard", id=entity_id))
        # The invite was already validated at verify-code time, so a failure
        # here is a real problem (race / DB error), NOT an expected mismatch.
        # Do NOT fall through to a plain login — that's the original bug, where
        # the user lands logged-in with no entity shared and no signal. Surface
        # it and send them back so they (or the inviter) can retry.
        logger.error(
            f"Handoff: invite acceptance failed for user {user.id}: {accept_error}"
        )
        flash(accept_error, "danger")
        return redirect(url_for("auth.home"))

    if not user.approved:
        logger.warning(
            f"Handoff: user {user.id} is not approved — redirecting to login."
        )
        return redirect(url_for("auth.home"))

    login_user(user)
    logger.info(f"Handoff: logged in user {user.id}.")
    return redirect(_post_login_redirect(user))
