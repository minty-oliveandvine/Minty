# Public share links for a submitted report: /Minty_Report/{initials}/{date}/{secret}/ (Flask's
# page) and GET /api/petty-cash/v1/public/share/{initials}/{date}/{secret} (the petty-cash web
# apps' /share page). Both open a link through resolve_share.
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, request, url_for
from loguru import logger

from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity, Report, ShareLink, UserEntity, db
from utils import generate_share_token, verify_share_token

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

    return {"url": shareable_url, "path": share_link.path_segment,
            "expires_at": share_link.expires_at.astimezone(timezone.utc).isoformat()}, 200


class ShareRefused(Exception):
    """A share link that opens nothing. ``reason`` is which check failed (for the caller's status
    and the log, never for an anonymous visitor); ``message``/``category`` are Flask's flash."""

    def __init__(self, reason, message, category="danger"):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.category = category


_DEAD = "This link doesn't work anymore. Could you ask for a fresh one?"
_WRONG = "This link doesn't look right to me."


def resolve_share(path_segment):
    """``(link, entity, report)`` for a live "{initials}/{date}/{secret}" path, else ShareRefused.

    Only the full path, secret included, finds a link: the old two-part form had no secret and
    could be guessed, so it is refused even while its row still exists. An expired link and one
    whose token fails its signature are deleted. The secret is never logged - only the row id.
    """
    if not is_share_path(path_segment):
        logger.warning(f"share link refused: malformed or old-form path, from {request.remote_addr}")
        raise ShareRefused("malformed", _DEAD)

    share_link = ShareLink.query.filter_by(path_segment=path_segment.strip("/")).first()
    if not share_link:
        logger.warning(f"share link refused: unknown secret, from {request.remote_addr}")
        raise ShareRefused("unknown", "Hmm, I couldn't find that share link.")

    # expires_at is TIMESTAMPTZ; a naive value (a hand-made row) is local time.
    expires_at = share_link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.astimezone()
    if datetime.now(timezone.utc) > expires_at:
        logger.info(f"share link refused: expired, link {share_link.id} removed")
        db.session.delete(share_link)
        db.session.commit()
        raise ShareRefused("expired", "This link has expired. Could you ask for a fresh one?", "warning")

    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:
        logger.error("share link refused: SECRET_KEY is not set")
        raise ShareRefused("misconfigured", "Something's not set up right on my end. Could you let us know?")

    is_valid, params = verify_share_token(share_link.token, secret_key)
    if not is_valid or not params:
        logger.warning(f"share link refused: token fails its signature, link {share_link.id} removed")
        db.session.delete(share_link)
        db.session.commit()
        raise ShareRefused("bad_token", _DEAD)

    token_entity_id = params.get("entity_id")
    token_transaction_date = params.get("transaction_date")
    if not token_entity_id or not token_transaction_date:
        logger.warning(f"share link refused: token names no company or day, link {share_link.id}")
        raise ShareRefused("bad_token", _WRONG)

    # The signed token must name the same company and day as the row.
    if (str(token_entity_id) != str(share_link.entity_id)
            or str(token_transaction_date) != str(share_link.transaction_date)):
        logger.warning(f"share link refused: token does not match link {share_link.id}")
        raise ShareRefused("mismatch", _WRONG)

    entity = Entity.query.get(token_entity_id)
    if not entity:
        logger.warning(f"share link refused: no company, link {share_link.id}")
        raise ShareRefused("no_company", "Hmm, I looked everywhere but couldn't find that one.")

    report_date = datetime.strptime(token_transaction_date, "%Y-%m-%d").date()
    report = Report.query.filter(
        # Share-link target: SUBMITTED reports only, never a draft.
        db.or_(Report.status.is_(None), Report.status != "draft"),
        Report.company == str(token_entity_id),
        Report.transaction_date == report_date,
    ).first()
    if report is None:
        logger.warning(f"share link refused: no submitted report, link {share_link.id}")
        raise ShareRefused("no_report", f"I couldn't find a report for {token_transaction_date}.", "warning")

    logger.info(
        f"share link opened: link={share_link.id} entity={token_entity_id} "
        f"date={token_transaction_date} from {request.remote_addr}")
    return share_link, entity, report
