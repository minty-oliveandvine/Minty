"""The entity list minty-web draws: ``GET /api/me/entities`` (Part 3 step 4, done early).

The same list the Jinja page draws (``services/entity_list.build_entity_list``), with the
last access as an ISO instant rather than a string formatted in Hong Kong time - minty-web
renders it in the viewer's own zone, as the Jinja page's script already did.

``?flash=`` is the signed hand-over ``routes/list.py`` puts on the URL when it sends the
browser on to minty-web; it comes back as ``notices`` (``[]`` when missing, expired or
forged), so what a redirect flashed on its way to /entity is still said.
"""

from __future__ import annotations

from flask import request
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.entity.services.entity_list import build_entity_list, read_notices
from blueprints.shared import hub_api


@entity_bp.route("/api/me/entities", methods=["GET", "OPTIONS"])
def my_entities_api():
    early, user = hub_api.guard()
    if early is not None:
        return early

    try:
        entries = build_entity_list(user)
    except Exception:
        logger.exception(f"Entity list API failed for user={user.id}")
        return hub_api.refuse("Your companies didn't load. Mind trying again?", 500)

    return hub_api.respond(
        {
            "entities": [
                {
                    **entry,
                    "last_accessed_at": (
                        entry["last_accessed_at"].isoformat() if entry["last_accessed_at"] else None
                    ),
                }
                for entry in entries
            ],
            "notices": read_notices(request.args.get("flash")),
        }
    )
