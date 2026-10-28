"""Preview sets: hand a person back into the branch preview they came from.

A branch's previews live on ``https://pr-<slug>-<app>.dailyminty.com`` - one host per front end
(``my``, ``payment-request``, ``onboarding``, ``pettycash``), kept complete by the ``.github`` repo's
``vercel-preview-set.yml``. Where ``PREVIEW_ORIGIN_REGEX`` is set (minty-infra writes it onto
ONE environment's services; ``services.app_runtime.env.preview_origin_regex``), a set's front
ends name themselves with ``?return_origin=`` on every navigation to Flask, and the hand-off
that trip starts goes to the same set's host for the target app, so crossing apps never leaves
the change being previewed.

Previews call PRODUCTION's Flask until the November launch, so a preview tab and a production
tab share one Flask session - and each TRIP decides where its own hand-off goes (:func:`_named`),
so both can be used side by side:

- ``return_origin`` names a set (same-site only, below) - that set; a configured origin - the
  configured front end, from any trip (leaving a set is never risky).
- A navigation from another of our hosts (``same-site``: production's front ends send no
  ``return_origin``), from the address bar or a bookmark (``none``), or with no fetch metadata -
  the configured front end.
- Only a hop that CAN'T name a set reads the one stored in the session (``SESSION_KEY``, written
  by the last trip that named one, cleared by a trip that named the configured hosts): a link on
  a Flask page (``same-origin``) and Xero's OAuth return (``cross-site``). So a Flask Petty Cash
  page hands back to the side the person last came from - with two tabs interleaved, that can
  be the other tab's side. Fetches (the hubs' API calls) name nothing and change nothing.

Unset, nothing here does anything. A stored set is re-checked against the regex on every read,
so removing the variable turns it off at once; logging out also leaves the set.

Only a SAME-SITE navigation may name a set: the browser's ``Sec-Fetch-Site`` says ``same-site``
when the trip comes from another dailyminty.com host - one of our front ends - and ``none`` or
``cross-site`` for a link in an email or on another site. And a stored set lapses
``SET_TTL_SECONDS`` after it was last named. Without both, a crafted link could park a signed-in
person's session in a set and route the tokens of later Flask-started hand-offs into a preview
(security review, 2026-10-13). A browser that sends no fetch metadata never names a set.

CORS never reads the session: it answers the request's own ``Origin`` (:func:`cors_origin`).

The ALTERNATE SET (``EXTRA_FRONTEND_ORIGINS``, ``services.app_runtime.env.extra_frontend_origins``)
is one more set, listed origin by origin instead of by pattern: a second copy of the front ends
on other hosts (the Cloudflare trial's ``*.workers.dev`` Workers, built from ``main``). It rides
the same session key under the slug ``ALT_SLUG`` and the same TTL. Unlike a branch preview it
may be named from ANY trip, cross-site included (a workers.dev page is never same-site with
dailyminty.com): its hosts are exact, ours, and run the same code as production - the same
trust as a configured origin, which any trip may name. An app it does not list keeps its
configured origin; unset, a stored alternate set is ignored at once.
"""

from __future__ import annotations

import re
import time

from flask import has_request_context, request, session

from services.app_runtime.env import extra_frontend_origins, preview_origin_regex

SESSION_KEY = "preview_set"
#: The stored slug of the alternate set. ``~`` is never in a branch slug.
ALT_SLUG = "~alt"
#: How long a named set lasts; every same-site trip from a set host names it again.
SET_TTL_SECONDS = 30 * 60

#: The set-host shape. The app is read from the END of the label, so a slug may itself contain
#: an app's name. Same shape as ``@minty/shared/previewSibling``.
_SET_ORIGIN = re.compile(
    r"https://pr-([a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?)-(my|payment-request|onboarding|pettycash)\.dailyminty\.com"
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


def _named() -> str | None:
    """What THIS request names: a set's slug, ``""`` for the configured front ends, or None for
    a hop that can't name one - a link on a Flask page, Xero's OAuth return, or a fetch."""
    fetch_site = request.headers.get("Sec-Fetch-Site")
    raw = request.args.get("return_origin")
    if raw is not None:
        origin = raw.strip().rstrip("/")
        if origin in _configured_origins():
            return ""
        if origin in extra_frontend_origins().values():
            return ALT_SLUG
        parsed = parse(origin)
        if parsed and fetch_site in ("same-site", "same-origin"):
            return parsed[0]
    if request.headers.get("Sec-Fetch-Mode", "navigate") != "navigate":
        return None
    return None if fetch_site in ("same-origin", "cross-site") else ""


def capture() -> None:
    """``before_request``: remember the set this trip names, or leave it for a configured host."""
    named = _named()
    if named:
        session[SESSION_KEY] = {"slug": named, "at": int(time.time())}
    elif named == "":
        session.pop(SESSION_KEY, None)


def handoff_origin(app: str, configured: str) -> str:
    """Where a hand-off to ``app`` goes: the set this trip names, else - for a hop that can't
    name one - the stored set, in each case only while the regex still allows it. Outside a
    request (a mail, a job) there is no person and so no set: ``configured``."""
    if not has_request_context():
        return configured
    slug = _named()
    if slug is None:
        stored = session.get(SESSION_KEY)
        fresh = isinstance(stored, dict) and time.time() - stored.get("at", 0) < SET_TTL_SECONDS
        slug = stored.get("slug") if fresh else None
    if slug == ALT_SLUG:
        return extra_frontend_origins().get(app, configured)
    if slug:
        candidate = set_origin(slug, app)
        if parse(candidate) == (slug, app):
            return candidate
    return configured


def cors_origin(configured: tuple[str, ...], apps: tuple[str, ...]) -> str:
    """The ``Access-Control-Allow-Origin`` to answer: the request's ``Origin`` when it is one
    of ``configured``, an extra origin of one of ``apps`` or a set origin for one of them,
    otherwise ``configured[0]`` (which the browser refuses for any other caller)."""
    origin = (request.headers.get("Origin") or "").rstrip("/")
    extra = extra_frontend_origins()
    if origin in configured or origin in {extra[a] for a in apps if a in extra}:
        return origin
    parsed = parse(origin)
    return origin if parsed and parsed[1] in apps else configured[0]


def is_set_origin(origin: str) -> bool:
    return parse(origin) is not None or origin in extra_frontend_origins().values()
