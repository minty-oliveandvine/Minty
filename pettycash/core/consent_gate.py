"""First-time Terms & Conditions gate.

Two hooks, registered from ``pettycash.core.hooks.init_app``:

* ``before_request`` — for authenticated users with no ``given`` consent for
  the active terms version, flag the request (``g.terms_consent_required``) and
  refuse mutating requests so the block has real teeth.
* ``after_request`` — when flagged and the response is an HTML page, record the
  ``notice`` event (the definitive "modal was shown" moment) and inject the
  consent modal before ``</body>`` so it appears on whatever page the user is on.

There is no shared base template in this app (pages are standalone HTML docs),
so centralised response injection is how the modal reaches every page.
"""

from __future__ import annotations

from flask import (flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user
from loguru import logger

from blueprints.consent.services.consent import (ensure_notice_record,
                                                  get_active_terms_version,
                                                  get_or_create_principal,
                                                  has_given_consent)

TERMS_OK_SESSION_KEY = "terms_ok"

# Never gate/block these: auth entry & exit, the accept endpoint itself, and
# framework/static/health endpoints.
_EXEMPT_ENDPOINTS = {
    "static",
    "health_check",
    "consent.accept_terms",
    "auth.logout",
    "auth.home",
    "auth.login",
    "auth.email_check",
    "auth.email_request_code",
    "auth.email_verify_code",
    "auth.email_handoff",
}

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _wants_json() -> bool:
    return (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def register(app, db):
    @app.before_request
    def consent_gate():
        try:
            if not current_user.is_authenticated:
                return None
            if request.endpoint is None or request.endpoint in _EXEMPT_ENDPOINTS:
                return None

            terms_version = get_active_terms_version()
            if terms_version is None:
                # No terms seeded — never lock users out.
                logger.warning(
                    "consent: no active terms_version; gate disabled")
                return None

            if session.get(TERMS_OK_SESSION_KEY) == terms_version.terms_ver_id:
                return None

            principal = get_or_create_principal(current_user.id)
            if has_given_consent(
                    principal.principal_id, terms_version.terms_ver_id):
                session[TERMS_OK_SESSION_KEY] = terms_version.terms_ver_id
                return None

            # Un-consented: flag for the injector, and block writes.
            g.terms_consent_required = True
            g.terms_version = terms_version

            if request.method in _MUTATING_METHODS:
                logger.info(
                    "consent: blocked %s %s for un-consented user=%s",
                    request.method, request.path, current_user.id,
                )
                if _wants_json():
                    return (
                        jsonify({
                            "status": "error",
                            "code": "terms_not_accepted",
                            "message": "Please accept the Terms & Conditions to continue.",
                        }),
                        403,
                    )
                flash(
                    "Please accept the Terms & Conditions to continue.",
                    "warning",
                )
                return redirect(request.referrer or url_for("auth.home"))
        except Exception:
            logger.exception("consent_gate before_request failed")
        return None

    @app.after_request
    def inject_terms_modal(response):
        try:
            if not getattr(g, "terms_consent_required", False):
                return response
            if response.direct_passthrough or response.status_code != 200:
                return response
            if "text/html" not in response.headers.get("Content-Type", ""):
                return response

            terms_version = getattr(g, "terms_version", None) \
                or get_active_terms_version()
            if terms_version is None:
                return response

            # Definitive "modal shown" moment — record the notice (idempotent).
            principal = get_or_create_principal(current_user.id)
            ensure_notice_record(
                principal,
                terms_version,
                captured_ip=request.remote_addr or "",
                captured_ua=request.headers.get("User-Agent", ""),
            )

            modal_html = render_template(
                "consent/terms_modal.html",
                terms_content=terms_version.content_text,
                terms_label=terms_version.ver_label,
            )
            body = response.get_data(as_text=True)
            if "</body>" in body:
                body = body.replace("</body>", modal_html + "</body>", 1)
            else:
                body = body + modal_html
            response.set_data(body)
        except Exception:
            logger.exception("consent_gate after_request injection failed")
        return response
