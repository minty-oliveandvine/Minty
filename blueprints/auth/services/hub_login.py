"""Where a person signs in: minty-web's ``/login``, or ``/signup`` to make an account
(phase 2, 2026-10-05; sign-up got its own route 2026-10-09).

Sign-in - log in, sign up, an invitation - is the hub's page; Flask stays the identity
behind it (``/auth/email/*``, ``/xero_auth`` and the session they end in). Every place that
sends a person to sign in builds the address here, so it is spelled once.

Flashed messages cannot cross to another origin, so whatever was flashed on the way is
drained and signed into ``?flash=`` - the same hand-over the entity list uses
(``services.entity_list.sign_notices``); the page reads it back from ``GET /auth/notices``.
"""

from __future__ import annotations

from urllib.parse import urlencode

from flask import get_flashed_messages

from blueprints.entity.services.entity_list import sign_notices
from blueprints.shared import bearer_api
from blueprints.shared.safe_redirect import safe_internal_path

HUB_LOGIN_PATH = "/login"
HUB_SIGNUP_PATH = "/signup"


def hub_login_url(
    *,
    next_path: str | None = None,
    mode: str | None = None,
    invite: str | None = None,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    carry_flashes: bool = True,
) -> str:
    """``{MINTY_WEB_URL}/login?…``, or ``/signup?…`` when ``mode`` is ``"signup"`` - sign-up is
    its own page on the hub, like log in, so the mode is the PATH and never a query parameter.
    ``next_path`` is kept only when it is a path on this site
    (it comes back to Flask after sign-in); ``invite`` and
    ``email`` are an invitation's token and address, ``first_name``/``last_name`` the names
    the inviter gave (a new invitee's account is made from them) - the page reads them once
    and clears the address bar. ``carry_flashes`` drains the flashes into the hand-over."""
    params: dict[str, str] = {}
    safe_next = safe_internal_path(next_path)
    if safe_next:
        params["next"] = safe_next
    path = HUB_SIGNUP_PATH if mode == "signup" else HUB_LOGIN_PATH
    if invite:
        params["invite"] = invite
    if email:
        params["email"] = email
    if first_name:
        params["fn"] = first_name
    if last_name:
        params["ln"] = last_name
    if carry_flashes:
        notices = sign_notices(get_flashed_messages(with_categories=True))
        if notices:
            params["flash"] = notices
    query = f"?{urlencode(params)}" if params else ""
    return f"{bearer_api.minty_web_origin()}{path}{query}"
