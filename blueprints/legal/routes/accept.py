"""The blocking screen: read the Terms, tick the box, continue.

This is the route the Phase 4 gate redirects to, and the only place a person
who has never agreed can reach. Two things follow from that, and both are
load-bearing:

  * it must never redirect back into the gate (a loop nobody can escape), and
  * logging out must always be possible from it — someone who refuses has to
    be able to leave.
"""

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.legal import legal_bp
from blueprints.legal.models.terms_consent import SOURCE_GATE
from blueprints.legal.services.consent import (ACCEPT_FAILED,
                                               ACCEPT_NOT_TICKED,
                                               ACCEPT_VERSION_CHANGED,
                                               accept_current_terms,
                                               consents_for_user, has_consent)
from blueprints.legal.services.gate import (mark_session_agreed,
                                            take_intended_destination)
from legal import registry
from models.db import db


def _default_destination() -> str:
    """Where to land someone with no remembered destination.

    Mirrors the post-login redirect the OTP flow uses
    (blueprints/auth/routes/email_auth.py::_post_login_redirect). Imported
    locally rather than at module scope to keep the legal blueprint free of a
    load-time dependency on the auth blueprint.
    """
    from models.db import User

    if getattr(current_user, "system_role", None) == User.SYSTEM_ROLE_SUPERUSER:
        return url_for("user_management.admin")
    return url_for("auth.index")


@legal_bp.route("/legal/accept", methods=["GET"])
@login_required
def accept_page():
    document = registry.get_current(registry.TERMS)
    if document is None:
        # No document means nobody can agree, and the gate would trap every
        # user with nothing to show them. verify_pinned_hashes() reports this
        # at startup; here we simply refuse to render a broken screen.
        logger.error(
            "Terms acceptance page requested but there is no current Terms "
            f"document for version {registry.current_version(registry.TERMS)!r}."
        )
        return redirect(_default_destination())

    # Already agreed → nothing to do. Re-syncs the session cache too, so a
    # person who arrives here with a stale cookie is not stuck in a loop
    # between the gate and this page.
    if has_consent(current_user.id):
        mark_session_agreed()
        return redirect(_default_destination())

    # "Out of date" and "never agreed" are both blocked, but they read very
    # differently to the person: one is being asked again, the other for the
    # first time. Only the former gets the "what changed" note.
    previous = consents_for_user(current_user.id)

    return render_template(
        "legal/accept.html",
        document=document,
        privacy_version=registry.current_version(registry.PRIVACY),
        is_update=bool(previous),
        previous_version=previous[0].terms_version if previous else None,
    )


@legal_bp.route("/legal/accept", methods=["POST"])
@login_required
def accept_submit():
    """Record the agreement. JSON in, JSON out; CSRF-protected by the app.

    The tick box on screen is a convenience. THIS is the check — a client can
    send whatever it likes, so acceptance is only real if it arrives here with
    `accepted` true and a version that is still live.
    """
    payload = request.get_json(silent=True) or {}
    # The checks are services/consent.accept_current_terms's - shared with minty-web's
    # Terms modal (routes/hub.py), so the two screens cannot disagree about what counts.
    outcome, live_version = accept_current_terms(
        current_user.id,
        accepted=payload.get("accepted") is True,
        submitted_version=payload.get("terms_version") or "",
        source=SOURCE_GATE,
    )

    if outcome == ACCEPT_NOT_TICKED:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Please tick the box to continue.",
                }
            ),
            400,
        )

    # The Terms changed while this page sat open: send the page back for a reload.
    if outcome == ACCEPT_VERSION_CHANGED:
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "version_changed",
                    "terms_version": live_version,
                }
            ),
            409,
        )

    if outcome == ACCEPT_FAILED:
        # Only reachable if the document vanished between the checks.
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not record your agreement. Please try again.",
                }
            ),
            500,
        )

    # Resolve the destination BEFORE committing. `_default_destination()` reads
    # `current_user.system_role`, and a commit expires every loaded instance —
    # so doing it afterwards costs an extra SELECT on every acceptance, and
    # fails outright if the session is not in a state to reload the row.
    destination = take_intended_destination() or _default_destination()

    # This route owns its transaction — record_consent deliberately does not
    # commit, so that sign-up can bundle the consent with the User row.
    db.session.commit()

    mark_session_agreed(live_version)

    return jsonify({"status": "success", "redirect_url": destination})
