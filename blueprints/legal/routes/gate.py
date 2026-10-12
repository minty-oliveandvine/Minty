"""The request gate: block a logged-in person who has not agreed to the Terms.

This is the piece that makes the whole feature work. The sign-up tick boxes are
an optimisation that spares new users this screen; the gate is what covers
everyone else — every existing user at cutover, everyone who joined through a
screen we do not control (Xero, admin-created), and *everyone again* each time
the Terms are meaningfully rewritten.

-----------------------------------------------------------------------------
THE ALLOW-LIST IS THE DANGEROUS PART

This runs before every request. Get the allow-list wrong and every person is
locked out of Minty with no way back in — administrators included. Not slow,
not partly broken. Locked out.

Three entries are load-bearing and must never be removed:

  * entity.entity_list   — where this gate SENDS people. It hands the browser
                           to minty-web, which draws the acceptance panel. Gate
                           it and the redirect points at a page we block: a
                           loop with no exit, for everybody;
  * auth.logout          — someone who refuses must be able to leave;
  * the login endpoints  — or nobody can authenticate to reach the panel.

There is no Flask acceptance screen any more (`/legal/accept` and the
`templates/legal/` panel were deleted on 2026-10-12, when the documents moved
to minty-web), so the two bearer routes minty-web posts to and the invite
status route are the only `legal` endpoints left on the list.

-----------------------------------------------------------------------------
IT FAILS OPEN, DELIBERATELY

If this hook raises, the request is allowed through and the error is logged
loudly. That is a real trade-off, chosen in one direction on purpose: failing
closed on an unexpected error — a database blip, a missing document — takes the
entire application down for every user at once, while failing open means some
requests briefly skip a check that is itself a backstop. An outage is the worse
outcome, and the ERROR log is what makes the alternative visible.
"""

from flask import jsonify, redirect, request, url_for
from flask_login import current_user
from loguru import logger

from blueprints.legal import legal_bp
from blueprints.legal.services.consent import has_consent
from blueprints.legal.services.gate import (mark_session_agreed,
                                            session_agreed_to_current)
from legal import registry

# Endpoints reachable without having agreed. Keyed on endpoint name rather than
# URL path: a path prefix can be dodged with encoding tricks, an endpoint name
# cannot — it is whatever Flask actually matched.
ALLOWED_ENDPOINTS = frozenset(
    {
        # Server health. Gating this would make the app look down to the
        # platform's health checker and get it restarted in a loop.
        "health_check",
        # --- Getting in ---------------------------------------------------
        "auth.home",
        "auth.login",
        "auth.register",
        # the sign-in page's messages (minty-web's /login, phase 2)
        "auth.auth_notices",
        "auth.email_request_code",
        "auth.email_verify_code",
        "auth.email_handoff",
        "auth.reset_request",
        "auth.reset_token",
        # --- Getting out --------------------------------------------------
        # Non-negotiable. Someone who reads the Terms and refuses has to be
        # able to leave; without this the acceptance screen is a trap.
        "auth.logout",
        # --- Dead ends that must not redirect into the gate ---------------
        "auth.no_permission",
        # --- Arriving on an invite link -----------------------------------
        # This route renders nothing. It validates the token and bounces to
        # the onboarding sign-in page, which carries its own Terms tick box
        # (see _terms_consent_for_signup in blueprints/auth/routes/email_auth.py),
        # and acceptance is still enforced at auth.email_handoff and on every
        # entity route afterwards. So gating it protects nothing — it only
        # makes the invite link silently do nothing for anyone who has not
        # agreed yet, which is the largest group of people who ever receive
        # one. Deliberately NOT extended to invitation.xero_not_connected:
        # that one renders a template and stays gated.
        "invitation.accept_invitation_page",
        # --- Where the gate sends people ----------------------------------
        # THE critical entry. This route renders nothing: it hands the browser
        # to minty-web's company list, which draws the acceptance panel over
        # itself. Gate it and the gate redirects to a page it blocks — a loop
        # with no exit, for every person who owes an acceptance.
        #
        # The cost is that someone who has not agreed reaches minty-web's list
        # and, by removing the panel in devtools, could read their company
        # NAMES (the panel renders the page inert, not absent — see
        # minty-web's components/ui/TermsGate.tsx). They still cannot ENTER
        # any of them: every other entity route stays gated, here. A
        # deliberate, bounded trade, unchanged by the move.
        "entity.entity_list",
        # --- The acceptance flow itself -----------------------------------
        # Listed one by one rather than allowing the whole `legal` blueprint.
        # That blueprint also carries product functionality (the consent
        # history API), and a blanket rule would leave it reachable by someone
        # who has not agreed. Listing endpoints means a NEW legal route is
        # gated until someone deliberately opens it — the safe default.
        #
        # Which version is live. Read by the sign-up screen before anyone is
        # logged in (minty-web asks it, then fetches that version's text from
        # its own registry), so it must answer to a caller who owes an
        # acceptance and happens to send a session cookie too.
        "legal.current",
        # Asked by the sign-in screen before anyone is logged in, to decide
        # whether an invitee still needs the tick box at all.
        "legal.invite_terms_status",
        # minty-web's Terms panel (routes/hub.py) - the acceptance flow itself since
        # 2026-10-12, and the only one. Its calls are bearer-only and normally carry no
        # session, so the gate never sees them; but a client that sends the session cookie
        # too (a same-origin deployment, a fetch with credentials) would otherwise be
        # refused the very route that lets it agree.
        "legal.hub_terms_status",
        "legal.hub_terms_accept",
    }
)


def _wants_json() -> bool:
    """Whether this caller expects JSON rather than a page.

    Same rule as the error handler in pettycash/core/hooks.py — deliberately,
    so the two never disagree about what a background request looks like. The
    "/api/" clause matters because several JSON routes sit under /minty/api/
    rather than /api/.
    """
    return (
        "/api/" in request.path
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "").lower()
    )


@legal_bp.before_app_request
def require_terms_acceptance():
    try:
        # Anonymous callers have nothing to agree to yet, and this must not
        # interfere with the login flow itself. It also means the Bearer-token
        # integrations (billing sync, onboarding) are untouched — they never
        # populate current_user.
        if not current_user.is_authenticated:
            return None

        endpoint = request.endpoint
        if endpoint is None:
            # Unmatched URL — let Flask 404 it rather than redirecting, which
            # would turn every typo into a trip through the acceptance screen.
            return None
        if endpoint == "static" or endpoint in ALLOWED_ENDPOINTS:
            return None

        # Nothing to ask for → do not block. The live version has no entry in
        # the manifest (legal/registry.py), so this app could not record an
        # agreement to it even if someone gave one, and minty-web's panel
        # cannot be answered. A mistyped CURRENT_TERMS_VERSION would otherwise
        # lock out every user in the system.
        if registry.get_current(registry.TERMS) is None:
            logger.error(
                "Terms gate is NOT enforcing: current version "
                f"{registry.current_version(registry.TERMS)!r} is not in the "
                "manifest. Nobody can be asked to agree until this is fixed."
            )
            return None

        # Fast path: the session already confirmed this user against the live
        # version, so no database read. Stores the version, not a flag, so a
        # Terms revamp invalidates every session by itself.
        if session_agreed_to_current():
            return None

        if has_consent(current_user.id):
            mark_session_agreed()
            return None

        # A redirect sent to a background request fails silently — the user
        # sees nothing happen at all, with no clue why. JSON callers get an
        # explicit code they can act on.
        if _wants_json():
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "terms_acceptance_required",
                        "message": "Please accept the Terms of Use to continue.",
                    }
                ),
                403,
            )

        # The company list, which hands over to minty-web, which draws the
        # acceptance panel over itself. There is no Flask fallback screen any
        # more, and the page they were trying to reach is NOT remembered: the
        # panel lifts where the person stands, in minty-web, and never comes
        # back here to resume a Flask destination.
        return redirect(url_for("entity.entity_list"))

    except Exception:
        # See the module docstring: an outage is worse than a briefly skipped
        # backstop. Loud, so this is never the silent state of the system.
        logger.exception(
            "Terms acceptance gate failed; allowing the request through. "
            "This means the gate is NOT enforcing — investigate immediately."
        )
        return None
