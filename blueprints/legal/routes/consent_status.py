"""What this app still answers about the Terms, now that the documents are minty-web's.

The documents, the renderer and the public pages left on 2026-10-12 (`minty-web/lib/legal/`,
served at `/terms` and `/privacy`). What stays here is NOT a document: it is the two questions
only the side holding `terms_consent` and the version manifest can answer, both asked before
anyone is logged in, and both therefore on the gate's allow-list (`routes/gate.py`).

  * ``POST /legal/invite-terms-status`` — does the person this invite was sent to still owe an
    acceptance? Keyed on the invite token, never a raw email, and it fails SAFE.
  * ``GET /legal/current`` — which version is live. This app names the version; minty-web then
    reads that version's text from its own registry. One owner, so a deploy skew cannot leave
    the two disagreeing about what a consent row may name.

Neither requires a login, and neither writes anything. Recording an acceptance is
``POST /api/me/terms/accept`` (`routes/hub.py`).
"""

from flask import jsonify, request
from services.app_runtime.log import logger

from blueprints.legal import legal_bp
from legal import registry

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


@legal_bp.route("/legal/current")
def current():
    """Which version is live, for the sign-up screens.

    minty-web calls this before showing its tick box, then fetches that version's text from its
    own registry, so the version it sends back with the sign-up is the version this app will
    accept. It is the reason a client never hardcodes a version string - and the reason this
    route survived the documents' move: the wording is minty-web's, the VERSION is ours.

    No URLs any more: `terms_url`/`privacy_url` pointed at pages this app no longer serves.
    A client links to minty-web's own `/terms` and `/privacy` (its `lib/legal/paths.ts`).
    """
    entry = registry.get_current(registry.TERMS)
    return jsonify(
        {
            "terms_version": registry.current_version(registry.TERMS),
            "privacy_version": registry.current_version(registry.PRIVACY),
            # The header date as recorded in the manifest; null for a version with no
            # recorded date, reported honestly rather than defaulted.
            "effective_date": entry.effective_date if entry else None,
        }
    )
