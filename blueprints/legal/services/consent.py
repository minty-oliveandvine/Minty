"""Recording and checking agreement to the Terms of Use.

Two functions carry the whole feature: `record_consent` writes the evidence,
`has_consent` answers the gate. Everything else in the Terms work is a screen
or a route on top of these.

THIS MODULE NEVER COMMITS
-------------------------
`record_consent` adds and flushes; the caller commits. That is not fussiness —
at sign-up the `User` row and its consent row must land in ONE transaction, so
there is never an account without an agreement, nor an agreement without an
account. A commit in here would break that guarantee by splitting the two.

The gate (`POST /legal/accept`) owns its own transaction and commits itself.

THE HASH IS NEVER TAKEN FROM THE CLIENT
---------------------------------------
The caller says which *version* was shown; the wording's fingerprint is looked
up server-side from legal/registry.py. A client that could supply the hash
could choose what it claims to have agreed to, which would make the record
worthless in exactly the situation it exists for.
"""

from __future__ import annotations

from flask import has_request_context, request
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.legal.models.terms_consent import CONSENT_SOURCES, TermsConsent
from legal import registry
from models.db import db


def _client_details() -> tuple[str | None, str | None]:
    """(ip_address, user_agent) for the current request, if there is one.

    X-Forwarded-For is preferred because Minty sits behind a load balancer in
    production, where `remote_addr` is the balancer and therefore identical for
    everyone — useless as a record.

    CAVEAT, stated plainly: that header is client-supplied and can be forged,
    and this app does not currently run ProxyFix to establish a trusted chain.
    So treat both of these as supporting detail, never as proof. What proves the
    agreement is the user id, the version, the document fingerprint and the
    timestamp — none of which the client controls.
    """
    if not has_request_context():
        return None, None
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    ip = forwarded or request.remote_addr
    user_agent = request.headers.get("User-Agent")
    return (
        ip[:45] if ip else None,
        user_agent[:512] if user_agent else None,
    )


def record_consent(
    user_id: str,
    *,
    source: str,
    version: str | None = None,
) -> TermsConsent | None:
    """Record that `user_id` agreed to `version` (default: the live version).

    Returns the row — the existing one if this person had already agreed to
    this version. Returns None only if the version has no document behind it,
    which is a misconfiguration rather than a user error.

    Idempotent. Does NOT commit; see the module docstring.
    """
    if source not in CONSENT_SOURCES:
        # A typo'd source silently poisons the audit trail — every row would
        # claim the wrong origin and nothing would ever notice. Fail loudly.
        raise ValueError(
            f"Unknown consent source {source!r}; expected one of {CONSENT_SOURCES}"
        )

    version = version or registry.current_version(registry.TERMS)
    document = registry.get_document(registry.TERMS, version)
    if document is None:
        logger.error(
            f"Refusing to record consent for {user_id}: no Terms document for "
            f"version {version!r}. A consent row naming a version we cannot "
            "produce is unverifiable."
        )
        return None

    existing = TermsConsent.query.filter_by(
        user_id=user_id, terms_version=version
    ).first()
    if existing is not None:
        return existing

    ip_address, user_agent = _client_details()
    consent = TermsConsent(
        user_id=user_id,
        terms_version=version,
        document_hash=document.sha256,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # SAVEPOINT, not a plain add. Two tabs (or a double-click) can both pass the
    # existence check above and race to insert, and the loser hits the unique
    # index. In PostgreSQL an IntegrityError aborts the ENTIRE transaction — at
    # sign-up that would take the User row down with it, turning a harmless
    # double-click into a failed registration. The nested block confines the
    # rollback to this insert so the caller's transaction survives intact.
    #
    # NOTE for anyone debugging this under tests: pysqlite does not honour
    # SAVEPOINT rollback, so on SQLite a row written here survives a
    # session.rollback(). That is a driver limitation, not a defect in this
    # code — PostgreSQL, which is what production runs, behaves correctly.
    # See tests/test_terms_consent.py for the xfail that records it.
    try:
        with db.session.begin_nested():
            db.session.add(consent)
        return consent
    except IntegrityError:
        # The other tab won. Its row is the record; that is a success, not an
        # error — the person did agree, exactly once.
        logger.info(
            f"Consent for user {user_id} version {version} already existed "
            "(concurrent insert); reusing it."
        )
        return TermsConsent.query.filter_by(
            user_id=user_id, terms_version=version
        ).first()


#: What `accept_current_terms` concluded. `recorded` is the only one that wrote anything.
ACCEPT_RECORDED = "recorded"
ACCEPT_NOT_TICKED = "not_ticked"
ACCEPT_VERSION_CHANGED = "version_changed"
ACCEPT_FAILED = "failed"


def accept_current_terms(
    user_id: str, *, accepted: bool, submitted_version: str, source: str
) -> tuple[str, str]:
    """The person's "Accept & Continue", wherever the panel was drawn: ``(outcome, live_version)``.

    ONE place for the checks both acceptance screens make - Minty's own (``POST
    /legal/accept``, the panel over its Select Company list) and minty-web's modal
    (``POST /api/me/terms/accept``). The tick box on screen is a convenience; THIS is the
    check, since a client can send whatever it likes:

      * not ticked -> ``not_ticked``;
      * the Terms changed while the panel sat open -> ``version_changed``: recording now
        would file the agreement against wording that is no longer live, an accurate record
        of the wrong thing - the client re-reads and asks again;
      * the version has no document behind it -> ``failed`` (a misconfiguration);
      * otherwise the consent is recorded (idempotently) -> ``recorded``.

    Does NOT commit, like ``record_consent``: each route owns its transaction.
    """
    live_version = registry.current_version(registry.TERMS)
    if not accepted:
        return ACCEPT_NOT_TICKED, live_version
    if (submitted_version or "").strip() != live_version:
        logger.info(
            f"Terms version changed under user {user_id}: submitted "
            f"{submitted_version!r}, live {live_version!r}. Asking them to reload."
        )
        return ACCEPT_VERSION_CHANGED, live_version
    if record_consent(user_id, source=source) is None:
        # Only reachable if the document vanished between the two checks above.
        return ACCEPT_FAILED, live_version
    return ACCEPT_RECORDED, live_version


def has_consent(user_id: str, version: str | None = None) -> bool:
    """Whether `user_id` has agreed to `version` (default: the live version).

    This is the question the gate asks on every request. It is answered from
    the session cache in normal operation — see the gate — so this hits the
    database about once per login.
    """
    if not user_id:
        return False
    version = version or registry.current_version(registry.TERMS)
    return (
        db.session.query(TermsConsent.id)
        .filter_by(user_id=user_id, terms_version=version)
        .first()
        is not None
    )


def consents_for_user(user_id: str) -> list[TermsConsent]:
    """Every agreement this person has given, newest first.

    Backs the admin view, and is the shape you want when someone asks what a
    given user actually agreed to and when.
    """
    return (
        TermsConsent.query.filter_by(user_id=user_id)
        .order_by(TermsConsent.accepted_at.desc())
        .all()
    )
