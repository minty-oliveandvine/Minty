"""The Terms gate as minty-web draws it: ``GET /api/me/terms`` and ``POST /api/me/terms/accept``.

Since 2026-09-29 Flask's ``/entity`` hands the browser to minty-web's entity list whether or
not a Terms acceptance is owed (always, since phase 2), so minty-web draws the acceptance panel,
over every page of that app, the way Flask's request gate covers every page of this one. Since
2026-10-12 it also HOLDS THE DOCUMENT: the ``.md`` files, the renderer and the public pages are
``minty-web/lib/legal/``, and the Jinja panel this was once a port of is deleted. So these two
routes no longer serve any wording. The split is **this app names the version, minty-web supplies
the text**:

* WHAT IS OWED is ``services/gate.terms_owed`` - which version, whether this is a re-acceptance,
  and the fingerprint the record will carry. minty-web reads that version's text from its own
  registry and refuses to draw a panel if the two disagree.
* ACCEPTING is ``services/consent.accept_current_terms``: not ticked, the version changed under
  the reader, no manifest entry. The fingerprint recorded comes from the manifest, NEVER from the
  client - the ``document_hash`` the client sends is compared and then thrown away - and the row
  says where the agreement was given: ``source = "hub"``.

Bearer-only (``blueprints/shared/hub_api.py``): the calls normally carry no Flask session, so
the request gate never sees them - and both endpoints are on its allow-list anyway
(``routes/gate.py``), since a client that did send the session cookie would otherwise be
refused the very route that lets it agree. An acceptance recorded here is honoured by the gate
on the person's next Flask page - it falls back to the database whenever its session cache has
no answer.
"""

from __future__ import annotations

from flask import request
from services.app_runtime.log import logger

from blueprints.legal import legal_bp
from blueprints.legal.models.terms_consent import SOURCE_HUB
from blueprints.legal.services.consent import (ACCEPT_FAILED,
                                               ACCEPT_NOT_TICKED,
                                               ACCEPT_VERSION_CHANGED,
                                               accept_current_terms)
from blueprints.legal.services.gate import terms_owed
from blueprints.shared import hub_api
from legal import registry
from models.db import db


@legal_bp.route("/api/me/terms", methods=["GET", "OPTIONS"])
def hub_terms_status():
    """``{owed: false}``, or which version is owed: its number, effective date, draft flag and
    **fingerprint**, plus whether this is a re-acceptance and of what.

    No wording and no links - both are minty-web's own since 2026-10-12. The ``sha256`` is the
    hash this app will record if that version is agreed to, so the client can check that the
    document it holds is the one being asked for: a mismatch means the two are deployed out of
    step, and minty-web shows nobody a document this app would misrecord."""
    early, user = hub_api.guard()
    if early is not None:
        return early

    try:
        owed = terms_owed(user.id)
    except Exception:
        logger.exception(f"Terms status failed for user={user.id}")
        return hub_api.refuse("The Terms didn't load. Mind trying again?", 500)
    if owed is None:
        return hub_api.respond({"owed": False})

    entry = owed["document"]
    return hub_api.respond(
        {
            "owed": True,
            "document": {
                "version": entry.version,
                "effective_date": entry.effective_date,
                "sha256": entry.sha256,
                "show_draft_notice": entry.show_draft_notice,
            },
            "is_update": owed["is_update"],
            "previous_version": owed["previous_version"],
        }
    )


@legal_bp.route("/api/me/terms/accept", methods=["POST", "OPTIONS"])
def hub_terms_accept():
    """Record the agreement: ``{accepted: true, terms_version, document_hash}`` -> ``{ok: true}``.

    400 when not ticked, 409 ``version_changed`` (with the live ``terms_version``) when the
    Terms changed while the panel sat open - the client re-reads and asks again - and 500
    when there is no manifest entry to agree to.

    ``document_hash`` is the fingerprint of the document the client actually showed. It is
    COMPARED to the manifest and refused on a mismatch (409 ``document_mismatch``), never
    stored: the client picks the value it sends, so it proves nothing on its own. It is a canary
    against a stale minty-web bundle - or a curl - filing a consent row against wording nobody
    was shown, and minty-web checks the same thing before drawing the panel, so it should be
    unreachable. Omitted, it is not checked: a client too old to send it is not a client sending
    a wrong one.
    """
    early, user = hub_api.guard()
    if early is not None:
        return early

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    submitted = payload.get("terms_version")

    shown_hash = payload.get("document_hash")
    if isinstance(shown_hash, str) and shown_hash:
        entry = registry.get_version(registry.TERMS, submitted) if isinstance(submitted, str) else None
        expected = entry.sha256 if entry else None
        if expected and shown_hash != expected:
            logger.error(
                f"Terms {submitted!r} fingerprint mismatch for user={user.id}: "
                f"the client showed {shown_hash}, the manifest says {expected}. "
                "minty-web and this app are deployed out of step - nothing recorded."
            )
            return hub_api.respond({"error": "document_mismatch"}, 409)

    outcome, live_version = accept_current_terms(
        user.id,
        accepted=payload.get("accepted") is True,
        submitted_version=submitted if isinstance(submitted, str) else "",
        source=SOURCE_HUB,
    )

    if outcome == ACCEPT_NOT_TICKED:
        return hub_api.refuse("Please tick the box to continue.", 400)
    if outcome == ACCEPT_VERSION_CHANGED:
        return hub_api.respond({"error": "version_changed", "terms_version": live_version}, 409)
    if outcome == ACCEPT_FAILED:
        return hub_api.refuse("Could not record your agreement. Please try again.", 500)

    # This route owns its transaction - record_consent deliberately does not commit.
    db.session.commit()
    logger.info(f"Terms {live_version} accepted in minty-web by user={user.id}")
    return hub_api.respond({"ok": True, "terms_version": live_version})
