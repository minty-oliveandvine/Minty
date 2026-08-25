from flask import get_flashed_messages, jsonify, render_template, request

from blueprints.auth import auth_bp
from blueprints.auth.forms import _REQUIRED, RegistrationForm
from models.db import User


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # Registration is now OTP-verified end to end: the register page (register.html)
    # collects name + email, the user clicks "Verify" to receive a 6-digit code
    # (POST /auth/email/request-code), and the account is created ONLY after the
    # code is confirmed on the Register click (POST /auth/email/verify-code, which
    # creates the passwordless user via _create_passwordless_user and logs them
    # in). This route therefore no longer creates users on a plain form POST —
    # doing so would be an unverified-email bypass. A direct POST just re-renders
    # the page so the JS flow can run.
    from legal import registry

    form = RegistrationForm()
    get_flashed_messages()
    return render_template(
        "register.html",
        form=form,
        first_name=form.first_name.data,
        last_name=form.last_name.data,
        email=form.email.data,
        # Stamped into the page so the consent record names the wording this
        # person was actually shown, rather than whatever is live by the time
        # they finish entering the code.
        terms_version=registry.current_version(registry.TERMS),
        # The body itself, so the tick box can be gated on reading it rather
        # than on clicking past a link. Same document object the acceptance
        # gate renders, so the two screens cannot show different wording.
        terms_document=registry.get_current(registry.TERMS),
    )


@auth_bp.route("/validate_register", methods=["POST", "GET"])
def validate_register():
    form = RegistrationForm()
    errors = {}
    form.validate()
    for key, error in form.errors.items():
        # Skip the "required" error while typing — an empty field the user hasn't
        # filled yet shouldn't flash an error inline (it's still enforced on submit).
        if isinstance(error, list) and len(error) > 0 and error[0] != _REQUIRED:
            errors[key] = error
    # Duplicate-email check, reported inline like any other field error so the
    # client can flag just the email field (no full-page submit/redirect that
    # wipes the form). The register page sends this as a JSON body (so the OTP
    # "Verify" button can gate on it before emailing a code), so read the email
    # from JSON first and fall back to the form field.
    json_body = request.get_json(silent=True) or {}
    email = (json_body.get("email") or form.email.data or "").strip()
    if email and not form.email.errors:
        existing = (
            User.query.with_entities(User.username).filter_by(username=email).first()
        )
        if existing:
            errors["email"] = ["An account with this email already exists"]

    error_count = len(errors)
    return jsonify({"errors": errors, "errorCount": error_count})
