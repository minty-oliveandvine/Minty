"""Preview sets: hand a person back into the branch preview they came from.

A branch's previews live on ``https://pr-<slug>-<app>.dailyminty.com`` - one host per front end
(``my``, ``payment-request``, ``onboarding``, ``petty-cash``), kept complete by the ``.github`` repo's
``vercel-preview-set.yml``. Where ``PREVIEW_ORIGIN_REGEX`` is set (minty-infra writes it onto
ONE environment's services; ``services.app_runtime.env.preview_origin_regex``), a front end
names itself with ``?return_origin=`` on any navigation to Flask, and Flask keeps the SET - the
slug - in the session. Every hand-off built after that, to any of the four apps, goes to the
same set's host for that app, so crossing apps never leaves the change being previewed.

Unset, nothing here does anything. A stored set is re-checked against the regex on every read,
so removing the variable turns it off at once; a configured origin in ``return_origin`` (the
person went back to a normal host) and logging out both leave the set.

Only a SAME-SITE navigation may name a set: the browser's ``Sec-Fetch-Site`` says ``same-site``
when the trip comes from another dailyminty.com host - one of our front ends - and ``none`` or
``cross-site`` for a link in an email or on another site. And a set lapses ``SET_TTL_SECONDS``
after it was last named. Without both, a crafted link could park a signed-in person's session in
a set and route the tokens of every later Flask-started hand-off into a preview (security
review, 2026-10-13). A browser that sends no fetch metadata never names a set.

CORS never reads the session: it answers the request's own ``Origin`` (:func:`cors_origin`).
"""

from __future__ import annotations

import re
import time

from flask import has_request_context, request, session

from services.app_runtime.env import preview_origin_regex

SESSION_KEY = "preview_set"
#: How long a named set lasts; every same-site trip from a set host names it again.
SET_TTL_SECONDS = 30 * 60

#: The set-host shape. The app is read from the END of the label, so a slug may itself contain
#: an app's name. Same shape as ``@minty/shared/previewSibling``.
_SET_ORIGIN = re.compile(
    r"https://pr-([a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?)-(my|payment-request|onboarding|petty-cash)\.dailyminty\.com"
)


def set_origin(slug: str, app: str) -> str:
    return f"https://pr-{slug}-{app}.dailyminty.com"


def parse(origin: str) -> tuple[str, str] | None:
    """``(slug, app)`` for an origin the configured regex allows, else None."""
    pattern = preview_origin_regex()
    if pattern is None or not pattern.fullmatch(origin):
        return None
    m = _SET_ORIGIN.fullmatch(origin)
    return (m.group(1), m.group(2)) if m else None


def _configured_origins() -> set[str]:
    from blueprints.shared import bearer_api

    return {bearer_api.minty_web_origin(), bearer_api.frontend_origin(), bearer_api.onboarding_origin(),
            bearer_api.petty_cash_web_origin()}


def capture() -> None:
    """``before_request``: remember (or leave) the set named by ``?return_origin=``."""
    raw = request.args.get("return_origin")
    if raw is None or request.headers.get("Sec-Fetch-Site") not in ("same-site", "same-origin"):
        return
    origin = raw.strip().rstrip("/")
    parsed = parse(origin)
    if parsed:
        session[SESSION_KEY] = {"slug": parsed[0], "at": int(time.time())}
    elif origin in _configured_origins():
        session.pop(SESSION_KEY, None)


def handoff_origin(app: str, configured: str) -> str:
    """Where a hand-off to ``app`` goes: the stored set's host when the regex still allows it.
    Outside a request (a mail, a job) there is no person and so no set: ``configured``."""
    stored = session.get(SESSION_KEY) if has_request_context() else None
    fresh = isinstance(stored, dict) and time.time() - stored.get("at", 0) < SET_TTL_SECONDS
    slug = stored.get("slug") if fresh else None
    if slug:
        candidate = set_origin(slug, app)
        if parse(candidate) == (slug, app):
            return candidate
    return configured


def cors_origin(configured: tuple[str, ...], apps: tuple[str, ...]) -> str:
    """The ``Access-Control-Allow-Origin`` to answer: the request's ``Origin`` when it is one
    of ``configured`` or a set origin for one of ``apps``, otherwise ``configured[0]`` (which
    the browser refuses for any other caller)."""
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin in configured:
        return origin
    parsed = parse(origin)
    return origin if parsed and parsed[1] in apps else configured[0]


def is_set_origin(origin: str) -> bool:
    return parse(origin) is not None
