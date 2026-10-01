# Public share links for a submitted report: /Minty_Report/{initials}/{date}/{secret}/.
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app, url_for
from loguru import logger

from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity, ShareLink, UserEntity, db
from utils import generate_share_token

SHARE_LINK_HOURS = 720
# 24 random bytes -> 32 url-safe characters. The secret, not the readable
# "{initials}/{date}" prefix, is what grants access to a shared report.
_SECRET_BYTES = 24
SHARE_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")


def is_share_path(path_segment):
    """True for the current "{initials}/{date}/{secret}" form. The old two-part form
    had no secret, so it was guessable, and it is refused everywhere."""
    parts = (path_segment or "").strip("/").split("/")
    return len(parts) == 3 and all(parts) and bool(SHARE_SECRET_RE.match(parts[2]))


def create_share_link_for_report(user_id, payload):
    payload = payload or {}
    entity_id = payload.get("entity_id")
    transaction_date = payload.get("transaction_date")

    if not entity_id or not transaction_date:
        return {"error": "Missing entity_id or transaction_date"}, 400

    user_entity = UserEntity.query.filter(
        UserEntity.user_id == user_id, UserEntity.entity_id == entity_id
    ).first()

    if not user_entity:
        return {"error": "You don't have access to this entity"}, 403

    entity = Entity.query.get(entity_id)
    if not entity:
        return {"error": "Entity not found"}, 404

    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:
        return {"error": "Server configuration error"}, 500

    try:
        date_obj = datetime.strptime(transaction_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid transaction_date format. Expected YYYY-MM-DD"}, 400

    token = generate_share_token(
        entity_id, transaction_date, secret_key, expiration_hours=SHARE_LINK_HOURS
    )
    expires_at = datetime.now() + timedelta(hours=SHARE_LINK_HOURS)

    # One link per company-day, keyed on the company itself: two companies whose
    # initials match never share (or take over) a row.
    share_link = ShareLink.query.filter_by(
        entity_id=entity_id, transaction_date=date_obj.date()
    ).first()
    if share_link is None:
        share_link = ShareLink(entity_id=entity_id, transaction_date=date_obj.date())
        db.session.add(share_link)
    if not is_share_path(share_link.path_segment):
        # A name with no Latin letters (e.g. Chinese) has no initials; the prefix
        # is cosmetic, so fall back rather than emit an empty URL segment.
        entity_acronym = (
            build_entity_acronym(entity.name, letters_only=True) or "Report"
        )
        date_url = date_obj.strftime("%d_%b_%Y")
        share_link.path_segment = (
            f"{entity_acronym}/{date_url}/{secrets.token_urlsafe(_SECRET_BYTES)}"
        )
    share_link.token = token
    share_link.expires_at = expires_at
    db.session.commit()

    logger.info(
        f"share link issued: link={share_link.id} entity={entity_id} "
        f"date={transaction_date} user={user_id}"
    )

    shareable_url = url_for(
        "report.minty_report_share",
        entity_and_date=share_link.path_segment,
        _external=True,
    )

    return {"url": shareable_url}, 200
