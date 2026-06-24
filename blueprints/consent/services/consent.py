"""Business logic for first-time Terms & Conditions consent.

Consent is versioned: a user is "first time" when they have no ``given``
event for the currently active ``terms_version``. The event log
(``consent_event``) records ``notice`` when the modal is shown and ``given``
when the user accepts. Multi-row inserts are wrapped in a savepoint so the
outer request transaction stays usable, following the pattern in
``blueprints/entity/services/xero_account_mapping_post.py``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from flask import current_app
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.consent.models.consent_event import ConsentEvent
from blueprints.consent.models.consent_record import ConsentRecord
from blueprints.consent.models.terms_user_principal import TermsUserPrincipal
from blueprints.consent.models.terms_version import TermsVersion
from models.db import db

EVENT_TYPE_EXPLICIT = "explicit"
CAPTURE_METHOD_WEB_CHECKBOX = "web-checkbox"

STATE_NOTICE = "notice"
STATE_GIVEN = "given"
STATE_WITHDRAWN = "withdrawn"


def get_active_terms_version() -> TermsVersion | None:
    """The current active terms version (``superseded_at IS NULL``), newest
    first, or ``None`` when none has been seeded yet."""
    return (
        TermsVersion.query.filter(TermsVersion.superseded_at.is_(None))
        .order_by(TermsVersion.published_at.desc())
        .first()
    )


def get_or_create_principal(user_id: str) -> TermsUserPrincipal:
    """Return the user's consent principal, creating it on first use.

    ``account_ref`` is UNIQUE, so a concurrent create raises IntegrityError;
    a savepoint keeps the outer transaction usable and we fall back to the
    row the winner inserted.
    """
    principal = TermsUserPrincipal.query.filter_by(account_ref=user_id).first()
    if principal:
        return principal
    try:
        with db.session.begin_nested():
            principal = TermsUserPrincipal(account_ref=user_id)
            db.session.add(principal)
        return principal
    except IntegrityError:
        existing = TermsUserPrincipal.query.filter_by(account_ref=user_id).first()
        if existing:
            return existing
        raise


def has_given_consent(principal_id: str, terms_ver_id: str) -> bool:
    """True if a ``given`` event exists for this principal + terms version."""
    return (
        db.session.query(ConsentEvent.event_id)
        .join(ConsentRecord, ConsentEvent.record_id == ConsentRecord.record_id)
        .filter(
            ConsentRecord.principal_id == principal_id,
            ConsentRecord.terms_ver_id == terms_ver_id,
            ConsentEvent.event_state == STATE_GIVEN,
        )
        .first()
        is not None
    )


def _record_for(principal_id: str, terms_ver_id: str) -> ConsentRecord | None:
    return ConsentRecord.query.filter_by(
        principal_id=principal_id, terms_ver_id=terms_ver_id
    ).first()


def _record_hash(
    principal_id: str,
    terms_ver_id: str,
    content_text: str,
    captured_ip: str,
    captured_ua: str,
    capture_method: str,
    moment: datetime,
) -> bytes:
    """Keyed tamper-evidence digest over the canonical consent fields.

    HMAC-SHA256 keyed with the app ``SECRET_KEY`` (32-byte digest), so the
    hash can't be forged by anyone who only has the column values.
    """
    content_digest = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    canonical = "|".join(
        [
            principal_id,
            terms_ver_id,
            content_digest,
            moment.isoformat(),
            captured_ip,
            captured_ua,
            capture_method,
        ]
    )
    secret = current_app.config["SECRET_KEY"]
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest()


def ensure_notice_record(
    principal: TermsUserPrincipal,
    terms_version: TermsVersion,
    captured_ip: str,
    captured_ua: str,
) -> ConsentRecord:
    """Return the consent record for (principal, version), creating it plus a
    ``notice`` event in one transaction on first presentation. Idempotent:
    reuses the existing record so the notice is written exactly once."""
    existing = _record_for(principal.principal_id, terms_version.terms_ver_id)
    if existing:
        return existing

    ip = captured_ip or "0.0.0.0"
    ua = captured_ua or ""
    moment = datetime.now(timezone.utc)
    try:
        with db.session.begin_nested():
            record = ConsentRecord(
                principal_id=principal.principal_id,
                terms_ver_id=terms_version.terms_ver_id,
                captured_ip=ip,
                captured_ua=ua,
                capture_method=CAPTURE_METHOD_WEB_CHECKBOX,
                record_hash=_record_hash(
                    principal.principal_id,
                    terms_version.terms_ver_id,
                    terms_version.content_text,
                    ip,
                    ua,
                    CAPTURE_METHOD_WEB_CHECKBOX,
                    moment,
                ),
            )
            db.session.add(record)
            db.session.flush()  # populate record.record_id for the event FK
            db.session.add(
                ConsentEvent(
                    record_id=record.record_id,
                    event_time=moment,
                    event_state=STATE_NOTICE,
                    event_type=EVENT_TYPE_EXPLICIT,
                )
            )
        db.session.commit()
        logger.info(
            "consent: notice recorded principal=%s terms=%s",
            principal.principal_id, terms_version.terms_ver_id,
        )
        return record
    except IntegrityError:
        db.session.rollback()
        existing = _record_for(principal.principal_id, terms_version.terms_ver_id)
        if existing:
            return existing
        raise


def record_acceptance(
    principal: TermsUserPrincipal,
    terms_version: TermsVersion,
    captured_ip: str,
    captured_ua: str,
) -> ConsentRecord:
    """Record a ``given`` event for (principal, version) in one transaction.

    Creates the underlying record (with its ``notice``) if it is somehow
    missing. Idempotent: a no-op if consent was already given.
    """
    record = ensure_notice_record(principal, terms_version, captured_ip, captured_ua)
    if has_given_consent(principal.principal_id, terms_version.terms_ver_id):
        return record

    moment = datetime.now(timezone.utc)
    try:
        with db.session.begin_nested():
            db.session.add(
                ConsentEvent(
                    record_id=record.record_id,
                    event_time=moment,
                    event_state=STATE_GIVEN,
                    event_type=EVENT_TYPE_EXPLICIT,
                )
            )
        db.session.commit()
        logger.info(
            "consent: given recorded principal=%s terms=%s",
            principal.principal_id, terms_version.terms_ver_id,
        )
    except Exception:
        db.session.rollback()
        raise
    return record
