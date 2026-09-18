"""The cross-origin, bearer-token transport the separate front ends call Minty through.

Three surfaces speak it and each had written it out itself:

* ``subscription.routes.portal`` -- the payer portal, called by the Module 2 frontend.
* ``entity.routes.modules`` -- the subscription-notice API, same frontend.
* ``entity.routes.create`` -- the onboarding app, a different origin again.

They share a shape, not a configuration: every one names its origin explicitly rather
than leaning on the global flask-cors install, pins ``Vary: Origin`` so a response cached
for one origin is never replayed to another, and authenticates on a JWT in the
``Authorization`` header with no session cookie. What differs is only the ORIGIN and
which methods it advertises, so those are arguments and the rest is shared.

Why it is worth sharing: the two JWT decoders had already drifted. Both used the same
secret, algorithm and exception set -- the security posture was never in question -- but
one returned ``str(user_id)`` and the other the raw claim, so the same token produced a
different TYPE depending on which door it came through, and every downstream comparison
against a ``String(36)`` id is a string comparison. :func:`user_id_from_bearer` settles
that on the coercing form.

The route modules keep their own thin ``_cors`` / ``_user_id_from_bearer`` names in front
of these, so anything patching a route module still intercepts (see docs/code_cleanse/CODE_CLEANSE_NOTES.md
on dependency injection).
"""
from __future__ import annotations

import os

import jwt
from flask import current_app, request

#: Where the Module 2 frontend is served from.
FRONTEND_APP_URL_DEFAULT = "http://localhost:3000"
#: Where the onboarding wizard is served from -- a different app on a different port.
ONBOARDING_APP_URL_DEFAULT = "http://localhost:3001"

#: What every one of these responses allows a caller to send. Not parametrised: a bearer
#: token and a JSON body is the whole contract, and a surface needing more is a decision
#: to take deliberately rather than by widening this for everyone.
ALLOWED_HEADERS = "Authorization, Content-Type"


def _origin(env_var: str, default: str) -> str:
    """The configured origin for a front end, without a trailing slash.

    Trailing slashes are stripped because this value is compared literally by the browser
    against the page's origin, and ``https://app.example/`` does not match
    ``https://app.example``.
    """
    return os.environ.get(env_var, default).rstrip("/")


def frontend_origin() -> str:
    """Origin of the Module 2 frontend (payer portal, subscription notices)."""
    return _origin("FRONTEND_APP_URL", FRONTEND_APP_URL_DEFAULT)


def onboarding_origin() -> str:
    """Origin of the onboarding app."""
    return _origin("ONBOARDING_APP_URL", ONBOARDING_APP_URL_DEFAULT)


def cors(resp, origin: str, *, methods: str = "GET, POST, OPTIONS"):
    """Stamp the cross-origin headers onto ``resp`` and return it.

    ``methods`` is per-surface and deliberately narrow: a preflight for a method the
    header does not name is refused by the browser before the route is ever reached, so
    advertising only what a surface actually serves is a real constraint rather than
    documentation.
    """
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = methods
    resp.headers["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
    return resp


def user_id_from_bearer() -> str | None:
    """The ``user_id`` claim of a valid JWT in the ``Authorization`` header, or None.

    Returns a STRING. The ids it is compared against are ``String(36)`` columns, and a
    decoder that sometimes answered with an int was one of the two copies this replaces.

    Every failure is None rather than an exception: a missing header, a malformed token,
    a bad signature and an expired one are all simply "not authenticated" to the caller,
    which answers 401 the same way for each. Distinguishing them in the response would
    tell an attacker which part of a forged token to fix.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        decoded = jwt.decode(
            header[len("Bearer "):].strip(),
            current_app.config.get("SECRET_KEY"),
            algorithms=["HS256"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.DecodeError):
        return None
    user_id = decoded.get("user_id")
    return str(user_id) if user_id else None
