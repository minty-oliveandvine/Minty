"""Public read-only views of the legal documents.

NONE of these require a login, and that is deliberate: someone reading the
Terms before signing up has no account yet, and someone held at the acceptance
gate must be able to read what they are being asked to agree to. Phase 4's
acceptance gate therefore has to allow-list every route in this module, or it
blocks the very pages it redirects people to.

Read-only by design — nothing here writes a consent record. Accepting happens
at `/legal/accept` (Phase 3), which does require a login.
"""

from flask import abort, jsonify, render_template, request, url_for
from loguru import logger

from blueprints.legal import legal_bp
from legal import registry

_TITLES = {
    registry.TERMS: "Terms of Use",
    registry.PRIVACY: "Privacy Policy",
}


def _render(kind: str, version: str | None):
    """Shared view for both document kinds, current version or a named one."""
    document = (
        registry.get_current(kind)
        if version is None
        else registry.get_document(kind, version)
    )
    if document is None:
        # A missing *current* document is a misconfiguration rather than a bad
        # URL, but 404 either way — the caller cannot tell them apart and there
        # is nothing useful to show. verify_pinned_hashes() reports the
        # misconfiguration at startup, which is where it belongs.
        abort(404)
    return render_template(
        "legal/document.html",
        document=document,
        title=_TITLES.get(kind, kind.title()),
        is_current=document.version == registry.current_version(kind),
    )


@legal_bp.route("/legal/terms")
def terms():
    return _render(registry.TERMS, None)


@legal_bp.route("/legal/terms/<version>")
def terms_version(version):
    return _render(registry.TERMS, version)


@legal_bp.route("/legal/privacy")
def privacy():
    return _render(registry.PRIVACY, None)


@legal_bp.route("/legal/privacy/<version>")
def privacy_version(version):
    return _render(registry.PRIVACY, version)


@legal_bp.route("/legal/invite-terms-status", methods=["POST"])
def invite_terms_status():
    """Whether the person an invite was sent to still owes a Terms acceptance.

    The sign-in screen cannot tell on its own. It knows an email, but not
    whether that email already has an account, and the server is the only side
    that knows whether that account has already agreed. Without this, every
    invitee was shown the tick box — including people who accepted the Terms
    months ago, who then had to read and agree a second time for no reason.

    KEYED ON THE INVITE TOKEN, NEVER A RAW EMAIL.

    An email-keyed version of this endpoint would be an account-enumeration
    oracle: anyone could ask "does this address have a Minty account?" for any
    address they liked. The token is a secret already bound to one address —
    whoever holds it received the invitation — so answering for that address
    reveals nothing they did not already have.

    POST, WITH THE TOKEN IN THE BODY (2026-10-05). As a GET query it landed in every
    access log and proxy log on the way. Read-only, keyed on a secret, no session: so it
    is CSRF-exempt (bootstrap.py) like the other onboarding-origin calls.

    FAILS SAFE. Anything unclear — no token, unknown token, no such user —
    answers "yes, still required". Asking someone to accept twice is a small
    annoyance; skipping someone who never agreed is a missing consent record,
    which is the thing this whole feature exists to prevent.
    """
    from blueprints.auth.services.identity import resolve_user_by_email
    from blueprints.invitation.models.invitation import Invitation
    from blueprints.legal.services.consent import has_consent

    required = True
    token = str((request.get_json(silent=True) or {}).get("invite") or "").strip()

    if token:
        try:
            invitation = Invitation.query.filter_by(
                token=token, status="pending"
            ).first()
            if invitation is not None:
                user = resolve_user_by_email(invitation.email)
                if user is not None:
                    required = not has_consent(user.id)
        except Exception:
            # Same fail-safe direction as everything else here: a database blip
            # must leave the tick box in place, not 500 the sign-in screen and
            # not wave someone through unasked. `required` is still True.
            logger.exception(
                "invite-terms-status lookup failed; treating Terms as required"
            )

    return jsonify(
        {
            "terms_required": required,
            "terms_version": registry.current_version(registry.TERMS),
        }
    )


@legal_bp.route("/legal/content/<kind>")
def content(kind):
    """The rendered document as JSON, for a client that must show it inline.

    WHY THIS EXISTS RATHER THAN AN IFRAME

    The onboarding app runs on its own origin, so it cannot read the scroll
    position of an <iframe> pointing at /legal/terms — the browser forbids it.
    Its tick box is gated on the person actually reaching the end of the
    document, and to do that it needs the markup itself.

    The HTML is produced by legal.render, which escapes the source text BEFORE
    applying markup, so what comes back is safe for the client to inject.
    """
    if kind not in (registry.TERMS, registry.PRIVACY):
        abort(404)

    document = registry.get_current(kind)
    if document is None:
        abort(404)

    return jsonify(
        {
            "kind": kind,
            "version": document.version,
            "html": document.html,
            "sha256": document.sha256,
            "effective_date": document.effective_date,
            "is_pinned": document.is_pinned,
        }
    )


@legal_bp.route("/legal/current")
def current():
    """Which version is live, for the sign-up screens.

    The onboarding app calls this before rendering its tick box so the version
    it sends back with the sign-up matches what the person actually saw. It is
    the reason a client never hardcodes a version string.
    """
    document = registry.get_current(registry.TERMS)
    return jsonify(
        {
            "terms_version": registry.current_version(registry.TERMS),
            "privacy_version": registry.current_version(registry.PRIVACY),
            "terms_url": url_for("legal.terms"),
            "privacy_url": url_for("legal.privacy"),
            # The header date as recorded in registry._EFFECTIVE_DATES; null for
            # a version with no recorded date, reported honestly rather than
            # defaulted.
            "effective_date": document.effective_date if document else None,
        }
    )
