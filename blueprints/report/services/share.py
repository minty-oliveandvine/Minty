# Report-related API routes: expense create_contact, submit_all, delete;
# get_draft_totals; publish_to_xero; publishing_status.
from datetime import datetime, timedelta

from flask import current_app, url_for

from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity, ShareLink, UserEntity, db
from utils import generate_share_token


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

    token = generate_share_token(
        entity_id, transaction_date, secret_key, expiration_hours=720
    )

    entity_acronym = build_entity_acronym(entity.name, letters_only=True)
    try:
        date_obj = datetime.strptime(transaction_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid transaction_date format. Expected YYYY-MM-DD"}, 400
    date_str = date_obj.strftime("%d %b %Y")
    date_url = date_str.replace(" ", "_")
    path_segment = f"{entity_acronym}/{date_url}"
    expires_at = datetime.now() + timedelta(hours=720)

    existing_link = ShareLink.query.filter_by(path_segment=path_segment).first()
    if existing_link:
        existing_link.token = token
        existing_link.entity_id = entity_id
        existing_link.transaction_date = transaction_date
        existing_link.expires_at = expires_at
        share_link = existing_link
    else:
        share_link = ShareLink(
            path_segment=path_segment,
            token=token,
            entity_id=entity_id,
            transaction_date=transaction_date,
            expires_at=expires_at,
        )
        db.session.add(share_link)
    db.session.commit()

    shareable_url = url_for(
        "report.minty_report_share", entity_and_date=path_segment, _external=True
    )

    return {"url": shareable_url}, 200
