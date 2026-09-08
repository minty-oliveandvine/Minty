"""Decides whether the bubble renders, on every page in the application.

TWO HARD REQUIREMENTS ON THE FUNCTION BELOW

  IT MUST NEVER RAISE. It runs for every template render in the app —
  including the login page and the error page. A context processor that throws
  turns every page into a 500, and the error page into a second one.

  IT MUST BE CHEAP. Same reason: it is on the render path of every request. Two
  indexed lookups at most, and the module check is cached on ``flask.g`` so a
  page that renders several templates only pays once.

It returns ``None`` — meaning render nothing — unless all five hold:

  1. the kill switch is on
  2. somebody is signed in
  3. an entity can be resolved for this request
  4. that entity has PETTY_CASH or BILL
  5. the user has permission on it

Resolution deliberately does NOT fall back to "any entity this user belongs
to". A bubble that uploads into a company the user is not currently looking at
is worse than no bubble: the file goes somewhere they did not intend and the
mistake is invisible until someone reviews the queue.

It DOES fall back to ``User.current_entity_id``, which is a different thing
entirely — see ``_current_entity_id``.
"""

from __future__ import annotations

from flask import g, render_template, request
from flask_login import current_user
from loguru import logger

from blueprints.capture import capture_bp

# Paths where the bubble has no business appearing even if everything else
# lines up: signing in, agreeing to terms, and the onboarding wizard, which is
# a linear flow that a floating panel would interrupt.
_SUPPRESSED_PREFIXES = (
    "/login",
    "/logout",
    "/register",
    "/auth/",
    "/legal/",
    "/onboarding",
    "/static/",
)


@capture_bp.app_context_processor
def inject_capture_bubble():
    try:
        return {"capture_bubble": _bubble()}
    except Exception as exc:
        # Never let this take a page down. A missing bubble is a small loss; a
        # 500 on every route is not.
        logger.debug("capture bubble: suppressed ({})", exc)
        return {"capture_bubble": None}


def _bubble():
    from blueprints.capture.services import capture_ai

    if not capture_ai.is_enabled():
        return None

    if not getattr(current_user, "is_authenticated", False):
        return None

    path = (request.path or "").lower()
    if any(path.startswith(prefix) for prefix in _SUPPRESSED_PREFIXES):
        return None

    entity_id = _current_entity_id()
    if not entity_id:
        return None

    petty_cash, bill = _entity_modules(entity_id)
    if not (petty_cash or bill):
        return None

    from services.permission_policy import Permission, has_permission

    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return None

    return {
        "entity_id": entity_id,
        "max_mb": capture_ai.max_file_bytes() // (1024 * 1024),
        "max_pages": capture_ai.max_pages(),
        # Which modules this company actually holds, so the panel can say where
        # a document will go instead of listing destinations they do not have.
        # Telling a Petty-Cash-only customer about Payment Submission is not
        # helpful, it is a question they now have to go and ask someone.
        "petty_cash": petty_cash,
        "bill": bill,
    }


def _current_entity_id():
    """The entity this request is about, or None.

    Only what the request itself carries — a URL argument, a query string, a
    form field. See the module docstring for why there is no "pick one for
    them" fallback.
    """
    view_args = request.view_args or {}
    for key in ("entity_id", "org_id", "id"):
        value = view_args.get(key)
        # ``id`` is the petty cash dashboard's entity argument, but it is also
        # a report id on other routes. Only trust it on a route whose endpoint
        # says it is an entity.
        if value and (key != "id" or _endpoint_takes_entity_id()):
            return str(value)

    for key in ("entity_id", "org_id"):
        value = request.args.get(key) or request.form.get(key)
        if value:
            return str(value)

    # Last resort: the company this person is currently inside.
    #
    # This is NOT "pick one of their companies", which is the guess the module
    # docstring rules out. ``User.current_entity_id`` is maintained by the
    # presence system (services/user_presence.py): it is written when someone
    # opens a company, follows them as they move — including arriving by deep
    # link — and is cleared on logout. It is the same fact the "who is signed
    # in" roster is built from.
    #
    # It is needed because most petty cash pages do not carry an entity in
    # their URL: only 6 of the 37 report routes do, and /report/expense is one
    # of the ones that does not. Without this the bubble would appear on the
    # dashboard and then vanish the moment the user started working.
    current = getattr(current_user, "current_entity_id", None)
    if current:
        return str(current)

    return None


def _endpoint_takes_entity_id() -> bool:
    endpoint = (request.endpoint or "")
    return endpoint in ("entity.report_dashboard",)


def _entity_modules(entity_id: str):
    """(petty_cash, bill) for this entity. Cached per request.

    Cached because this runs in the context processor AND again in the response
    injector, and a page can render several templates in between — without the
    cache a single page load would ask the entitlement tables four or five
    times for the same answer.
    """
    cache = getattr(g, "_capture_module_cache", None)
    if cache is None:
        cache = g._capture_module_cache = {}
    if entity_id in cache:
        return cache[entity_id]

    from blueprints.capture.services import routing

    cache[entity_id] = routing.entity_modules(entity_id)
    return cache[entity_id]


# ==========================================================================
# GETTING THE BUBBLE ONTO THE PAGE
#
# NOT by including it in a base template. That was the first attempt and it was
# wrong: only 7 of this application's 85 templates extend
# ``templates/base/layout.html``. Everything else — the entity dashboard, every
# petty cash page, the entity list — is a standalone <!DOCTYPE html> document
# with no inheritance at all, so the include reached almost nothing.
#
# Editing 85 templates is not an answer either: every page added afterwards
# would need remembering, and the one that got forgotten would be found by a
# user, not by us.
#
# So the rendered partial is spliced into the HTML response just before
# </body>. It is the same approach Flask-DebugToolbar takes, for the same
# reason, and it means a page added next year gets the bubble without anyone
# doing anything.
# ==========================================================================
@capture_bp.after_app_request
def inject_capture_bubble_html(response):
    try:
        # Only finished HTML pages. Each of these guards rules out a real case:
        #
        #   status          a 302 to the login page has a body, and pushing a
        #                   bubble into it would be both pointless and visible.
        #   passthrough     file streams (static assets, our own document
        #                   endpoint). Reading .get_data on one raises.
        #   content type    JSON, CSS, images and downloads all come through
        #                   here too.
        if response.status_code != 200:
            return response
        if response.direct_passthrough:
            return response
        if "text/html" not in (response.content_type or ""):
            return response

        bubble = _bubble()
        if not bubble:
            return response

        body = response.get_data(as_text=True)
        # rfind, not find: a page can mention "</body>" inside a script or a
        # code sample, and the real one is the last.
        index = body.rfind("</body>")
        if index == -1:
            return response

        snippet = render_template(
            "components/ai_capture_bubble.html", capture_bubble=bubble
        )
        # set_data fixes Content-Length for us; writing the body directly would
        # leave it stale and truncate the page in the browser.
        response.set_data(body[:index] + snippet + body[index:])
    except Exception as exc:
        # Never break a page over the bubble. Same rule as the context
        # processor: a missing bubble is a small loss, a broken response is not.
        logger.debug("capture bubble: not injected ({})", exc)
    return response
