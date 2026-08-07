"""Public read-only views of the legal documents.

NONE of these require a login, and that is deliberate: someone reading the
Terms before signing up has no account yet, and someone held at the acceptance
gate must be able to read what they are being asked to agree to. Phase 4's
acceptance gate therefore has to allow-list every route in this module, or it
blocks the very pages it redirects people to.

Read-only by design — nothing here writes a consent record. Accepting happens
at `/legal/accept` (Phase 3), which does require a login.
"""

from flask import abort, jsonify, render_template, url_for

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
            # Null until the legal owner resolves `Last Updated: [DATE]` in the
            # source document. Reported honestly rather than defaulted.
            "effective_date": document.effective_date if document else None,
        }
    )
