"""Who is making this request — a Minty session, or Module 2's bearer token.

TWO DOORS INTO THE SAME ROUTES

  Minty's own pages       a Flask-Login session cookie, same as everything else.
  Module 2's widget       an ``Authorization: Bearer <jwt>`` header, no cookie.

The second door exists because the bubble also runs on Module 2's module-
selection page, which is served from a different origin (port 3000 against
Minty's 5001). A browser will not send Minty's session cookie to a request made
from that page — third-party cookie rules — so a cookie-only API could never be
called from there at all.

The token is the one Module 2 ALREADY holds. Minty mints it during the module
handoff (``blueprints/entity/routes/modules.py::_generate_module_token``), signs
it with the shared SECRET_KEY, and Module 2 carries it for every call it makes.
Nothing new is issued and no second secret exists.

This is not a new pattern in this application. ``blueprints/shared/bearer_api.py``
already carries three surfaces that work exactly this way — the payer portal,
the subscription-notice API and the onboarding app. This module reuses that
decoder rather than writing a fourth one; the comment at the top of bearer_api
explains what happened the last time there were two.

WHAT THE TOKEN DOES NOT DO

It identifies a person. It does not grant them anything. Every route still calls
``has_permission`` for the resolved entity, which for an entity-scoped
permission requires an approved membership on that exact company. A valid token
for user A cannot reach company B's drafts.
"""

from __future__ import annotations

from flask import request
from flask_login import current_user
from loguru import logger

from blueprints.shared import bearer_api


def is_cross_origin() -> bool:
    """True when this request came from Module 2's front end.

    Judged on the Origin header rather than on the presence of a token: a
    same-origin page could carry a token too, and what this answers is "does
    this response need CORS headers", not "how was it authenticated".
    """
    origin = request.headers.get("Origin", "")
    return bool(origin) and origin.rstrip("/") == bearer_api.frontend_origin()


def has_bearer() -> bool:
    return request.headers.get("Authorization", "").startswith("Bearer ")


def acting_user():
    """The signed-in user, from either door. None when neither identifies one.

    The session is checked FIRST. On Minty's own pages both may be present —
    someone could paste a token onto a same-origin request — and the session is
    the stronger claim: it cannot be copied out of a URL.
    """
    if getattr(current_user, "is_authenticated", False):
        return current_user

    user_id = bearer_api.user_id_from_bearer()
    if not user_id:
        return None

    # Imported lazily: this module is imported by the route package while
    # models.db may still be initialising.
    from models.db import User

    user = User.query.get(user_id)
    if user is None:
        # A token that decodes but names nobody. Either the account went away or
        # the token was minted against a different database.
        logger.warning("capture: bearer token names unknown user {}", user_id)
    return user


def expired_or_unauthenticated():
    """The reply when nobody could be identified.

    A bearer caller gets 401 with a plain sentence, because the widget shows it
    verbatim and the honest cause is almost always the 30-minute token having
    run out. Silently doing nothing on a page that had a working button is worse
    than one sentence telling the user what to do about it.

    A session caller gets the app's ordinary 401 shape.
    """
    from flask import jsonify

    if has_bearer() or is_cross_origin():
        return (
            jsonify(
                {
                    "status": "error",
                    "reason": "session_expired",
                    "message": "Your session's expired, refresh the page.",
                }
            ),
            401,
        )
    return (
        jsonify({"status": "error", "message": "Please sign in again."}),
        401,
    )


def actor_id():
    """The acting user's id as a string, or None.

    A string because every id it is compared against is a ``String(36)`` column,
    and a comparison against anything else silently never matches.
    """
    user = acting_user()
    return str(user.id) if user is not None and getattr(user, "id", None) else None
