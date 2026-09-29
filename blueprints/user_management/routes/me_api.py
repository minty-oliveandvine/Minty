"""My Profile as minty-web reads and saves it: ``GET`` / ``PATCH /api/me/profile``
(Part 3 step 4, done early - minty-accounts-api takes this contract in Part 3).

``?entity=<id>`` names the company the profile was opened from; the answer then carries
that company, the person's role there and its modules (403 for one they may not see).
Without it the profile describes the person alone - opened from the entity list, there is
no company to describe. The same read gives minty-web's header and side menu the person's
name and initials.

``PATCH {first_name?, last_name?, email?}`` saves the person's OWN row: nothing in the
request can name anyone else. A refusal (``services.profile.ProfileError``) comes back as
422 with the sentence to show; the success answers with the fresh profile.
"""

from __future__ import annotations

from flask import request
from loguru import logger

from blueprints.shared import hub_api
from blueprints.user_management import user_management_bp
from blueprints.user_management.services import profile

#: What minty-web's profile may change. ``user_phone`` is the session route's alone.
_PATCHABLE = ("first_name", "last_name", "email")
_SAVE_FAILED = "That didn't quite save. Mind trying again?"


@user_management_bp.route("/api/me/profile", methods=["GET", "PATCH", "OPTIONS"])
def my_profile_api():
    early, user = hub_api.guard()
    if early is not None:
        return early

    if request.method == "PATCH":
        body = request.get_json(silent=True)
        fields = (
            {key: body[key] for key in _PATCHABLE if key in body} if isinstance(body, dict) else {}
        )
        if not fields or not all(isinstance(value, str) for value in fields.values()):
            return hub_api.refuse(_SAVE_FAILED, 400)
        try:
            profile.update_profile(user, **fields)
        except profile.ProfileError as exc:
            return hub_api.refuse(str(exc), 422)
        except Exception:
            logger.exception(f"Profile save failed for user={user.id}")
            return hub_api.refuse(_SAVE_FAILED, 500)

    entity = None
    entity_id = (request.args.get("entity") or "").strip()
    if entity_id:
        entity = profile.entity_context(user, entity_id)
        if entity is None:
            return hub_api.refuse("You don't have access to that company.", 403)
    return hub_api.respond(profile.profile_payload(user, entity))
