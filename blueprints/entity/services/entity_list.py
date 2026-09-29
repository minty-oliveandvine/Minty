"""The select-company list: every company a person may pick, in the list's order.

ONE BUILDER, TWO READERS. The Jinja page (``routes/list.py::entity_list``) draws it while
``MINTY_WEB_HUB`` is off, and while the person still owes a Terms acceptance; minty-web's list
reads it through ``GET /api/me/entities`` (``routes/me_api.py``). Values leave here raw - the
last access as an aware UTC datetime, modules as codes - and each reader formats its own, so
the two pages cannot disagree about which companies there are or which badges they carry.

THE FLASH HAND-OVER. Seventy-odd routes ``flash()`` a message and redirect to ``/entity``
("I looked everywhere but couldn't find that one", "you don't have permission to look
there"). With the hub on, ``/entity`` sends the browser on to minty-web, which cannot read
Flask's session - so the message would be dropped without anyone seeing it. The redirect
drains the flashes and signs them into the URL (``sign_notices``); the list's API reads them
back (``read_notices``). Signed, so a crafted ``?flash=`` cannot put words in Minty's mouth;
timed, so an old link or a reload later says nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from loguru import logger
from sqlalchemy.orm import aliased

from blueprints.entity.services.modules import (get_enabled_modules_for_entities,
                                                get_trial_modules_for_entities,
                                                module_display_names)
from models.db import Entity, User, UserEntity, db
from services.permission_policy import is_superuser

NOTICE_SALT = "hub-flash"
#: How long a signed hand-over stays readable: long enough for the landing's round trip,
#: short enough that a bookmarked or shared URL shows nothing.
NOTICE_MAX_AGE_SECONDS = 300
#: A redirect chain flashes one or two messages; anything past this is noise, not news.
MAX_NOTICES = 5
MAX_NOTICE_LENGTH = 500


def _utc(dt: datetime | None) -> datetime | None:
    """``last_accessed_at`` is a ``TIMESTAMPTZ``, so the driver hands back an aware value in
    the session's zone; this states it in UTC. A naive value (SQLite, or a row read some other
    way) is taken to be UTC already."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def build_entity_list(user) -> list[dict]:
    """Every company ``user`` may pick, "Setup in progress" first, then most recently opened.

    Superusers see every company, including those they hold no ``user_entity`` row on (they
    enter those read-only). Each entry: ``id``, ``name``, ``status``, ``modules`` (the codes
    switched on - the resolver is fail-closed, so a code here is a module the request gate
    will let through), ``trial_modules`` (those running on a free trial, intersected with
    ``modules`` so a badge never claims a trial on a module whose icon is not there),
    ``trial_module_names``, ``last_accessed_at`` (aware UTC, or None when never opened) and
    ``last_accessed_by`` (the name of whoever opened it last, or None).
    """
    # Who last opened each entity - outer-joined so entities never opened
    # (last_accessed_by_user_id IS NULL) still come back.
    accessor = aliased(User)
    query = (
        db.session.query(
            Entity.id,
            Entity.name,
            Entity.status,
            Entity.last_accessed_at,
            accessor.first_name,
            accessor.last_name,
        )
        .outerjoin(accessor, Entity.last_accessed_by_user_id == accessor.id)
        # "Setup in progress" floats to the top so a half-finished entity is the first
        # thing seen, then most-recently-opened first. Never-opened entities sort last
        # rather than first, which is what NULLS LAST buys.
        .order_by(
            (Entity.status == "onboarding").desc(),
            Entity.last_accessed_at.desc().nulls_last(),
        )
    )
    if not is_superuser(user):
        query = query.join(UserEntity, UserEntity.entity_id == Entity.id).filter(
            UserEntity.user_id == user.id
        )
    rows = query.all()
    if not rows:
        return []

    entity_ids = [r.id for r in rows]
    modules_by_entity = get_enabled_modules_for_entities(entity_ids)
    trials_by_entity = get_trial_modules_for_entities(entity_ids)
    trial_labels = module_display_names(
        {code for codes in trials_by_entity.values() for code in codes}
    )

    entries = []
    for r in rows:
        modules = modules_by_entity.get(r.id, set())
        trial_modules = trials_by_entity.get(r.id, set()) & modules
        entries.append(
            {
                "id": str(r.id),
                "name": r.name,
                "status": str(r.status) if r.status is not None else None,
                "modules": sorted(modules),
                "trial_modules": sorted(trial_modules),
                # Named in the badge's tooltip so a card showing two module icons and one
                # badge says WHICH module the free trial belongs to.
                "trial_module_names": sorted(
                    trial_labels.get(code, code) for code in trial_modules
                ),
                "last_accessed_at": _utc(r.last_accessed_at),
                "last_accessed_by": (
                    f"{r.first_name or ''} {r.last_name or ''}".strip() or None
                ),
            }
        )
    return entries


# --- the flash hand-over ---------------------------------------------------------------


def _category(raw: str) -> str:
    """Flask's category, read the way ``templates/components/flash_messages.html`` reads it
    for its own toasts: error/danger are errors, warning and info are themselves, and
    everything else (``success``, the bare ``message`` default) is a success."""
    if raw in ("error", "danger"):
        return "error"
    if raw in ("warning", "info"):
        return raw
    return "success"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=NOTICE_SALT)


def sign_notices(messages: Iterable[tuple[str, str]]) -> str | None:
    """The ``(category, message)`` pairs a redirect drained, signed for the trip to
    minty-web - or None when there is nothing to tell."""
    notices = [
        {"category": _category(category), "message": str(message)[:MAX_NOTICE_LENGTH]}
        for category, message in messages
        if str(message).strip()
    ][:MAX_NOTICES]
    return _serializer().dumps(notices) if notices else None


def read_notices(token: str | None) -> list[dict]:
    """What ``sign_notices`` sent, or ``[]`` for no token, an expired one or a forged one.

    Never raises: the list must load whatever the URL carries. An expired hand-over is the
    ordinary case of a reload minutes later, so it is logged quietly; a bad signature is
    somebody editing the URL, and says so.
    """
    if not token:
        return []
    try:
        data = _serializer().loads(token, max_age=NOTICE_MAX_AGE_SECONDS)
    except SignatureExpired:
        logger.info("Entity list notices: the hand-over had expired, nothing shown")
        return []
    except BadSignature:
        logger.warning("Entity list notices: the hand-over's signature did not verify, nothing shown")
        return []
    if not isinstance(data, list):
        logger.warning("Entity list notices: a signed hand-over that is not a list, nothing shown")
        return []
    return [
        {"category": _category(str(item.get("category", ""))), "message": str(item["message"])}
        for item in data[:MAX_NOTICES]
        if isinstance(item, dict) and isinstance(item.get("message"), str) and item["message"].strip()
    ]
