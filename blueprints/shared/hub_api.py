"""minty-web's door into Flask: the bearer surface its hub pages read - the entity list
(``entity.routes.me_api``), My Profile (``user_management.routes.me_api``) and the Terms
modal (``legal.routes.hub``).

The same transport as the other bearer surfaces (``bearer_api``: an explicit origin,
``Vary: Origin``, a JWT in the ``Authorization`` header and no session cookie), and three
differences worth knowing:

* Not a subscription surface: the entity list and the profile are the person's, whatever
  they pay for.
* The token's ``entity_id`` claim is ignored: a person reads their OWN list and their OWN
  profile, and a company the profile should describe travels as an explicit ``?entity=``
  that is checked against membership.
* A token for a person who no longer exists, or whose account is switched off
  (``approved`` false), is refused like a bad one - deactivating an account must shut this
  door too, not only the login form's.

Every refusal goes back through ``cors``: a bare 401 without the headers reads to the
browser as a CORS failure rather than a lapsed token, and minty-web's client only
re-authenticates on a 401 it can see.

WHO may call it cross-origin: minty-web, and - since the sidebar (menu + My Profile) was
copied into it on 2026-09-30 - billing-frontend, whose My Profile reads and saves the same
``/api/me/profile``. A browser allows one origin per response, so the request's own
``Origin`` is echoed when it is one of the two, and minty-web's named otherwise (the
browser then refuses the stranger, which is the point). Flask's own pages call these routes
same-origin with the token ``GET /me/sidebar-token`` hands them - no CORS involved.
"""

from __future__ import annotations

from flask import jsonify, make_response, request

from blueprints.shared import bearer_api

#: Everything the hub's routes answer between them. A preflight for a method not named here
#: is refused by the browser before a route is reached, so this is a real constraint.
METHODS = "GET, POST, PATCH, OPTIONS"


def allowed_origins() -> tuple[str, ...]:
    """The front ends that may call the hub routes from another origin; minty-web first."""
    return (bearer_api.minty_web_origin(), bearer_api.frontend_origin())


def cors(resp):
    allowed = allowed_origins()
    origin = (request.headers.get("Origin") or "").rstrip("/")
    return bearer_api.cors(resp, origin if origin in allowed else allowed[0], methods=METHODS)


def respond(payload, status: int = 200):
    return cors(make_response(jsonify(payload), status))


def refuse(error: str, status: int):
    """A refusal minty-web shows as it stands - ``error`` is a sentence for a person, except
    ``unauthorized``, which the client answers by fetching a fresh token instead."""
    return respond({"error": error}, status)


def guard():
    """``(early_response, user)``: the preflight, then a valid token naming an approved user.

    Return ``early_response`` when it is not None; otherwise ``user`` is the ``User`` row.
    """
    if request.method == "OPTIONS":
        return cors(make_response("", 204)), None
    user_id = bearer_api.user_id_from_bearer()
    if not user_id:
        return refuse("unauthorized", 401), None

    from models.db import User, db

    user = db.session.get(User, user_id)
    if user is None or not user.approved:
        return refuse("unauthorized", 401), None
    return None, user
