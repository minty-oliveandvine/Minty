"""Flask's one read from minty-subscription-api: the dashboard's subscription notice.

The subscription engine decides whether a company is past due or winding down a paid
module; Flask's Petty Cash dashboard only shows the answer. It asks server-side, as the
person viewing the dashboard, with a five-minute token it mints itself - signed with the
``SECRET_KEY`` every backend shares, naming the person and the company - so the API
answers exactly what it would answer that person (``can_manage`` depends on who asks).

A notice must never break the dashboard: any failure is logged and answers ``None``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import requests
from flask import current_app
from loguru import logger

from blueprints.shared.sidebar import subscription_api_origin

#: Seconds before the dashboard gives up on the notice; a page load must not wait long.
NOTICE_TIMEOUT_SECONDS = 4

#: How long the self-minted assertion lives. One request, so minutes is plenty.
ASSERTION_MINUTES = 5


def _assertion(user, entity_id: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "user_id": str(user.id),
        "entity_id": str(entity_id),
        "system_role": (getattr(user, "system_role", None) or ""),
        "iat": now,
        "exp": now + timedelta(minutes=ASSERTION_MINUTES),
    }
    return jwt.encode(claims, current_app.config["SECRET_KEY"], algorithm="HS256")


def fetch_notice(entity_id: str, user) -> dict | None:
    """The company's notice for this person, or None when there is nothing to show or
    the API could not be asked (logged)."""
    url = f"{subscription_api_origin()}/api/entities/{entity_id}/subscription-notice"
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {_assertion(user, entity_id)}",
                "Accept": "application/json",
            },
            timeout=NOTICE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error(f"Subscription notice: could not reach the subscription API for {entity_id}: {exc}")
        return None
    if resp.status_code != 200:
        logger.error(
            f"Subscription notice: the subscription API answered {resp.status_code} for {entity_id}"
        )
        return None
    try:
        notice = resp.json()
    except ValueError:
        logger.error(f"Subscription notice: a non-JSON answer for {entity_id}")
        return None
    if not isinstance(notice, dict) or not notice.get("items"):
        return None
    return notice
