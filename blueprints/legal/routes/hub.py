"""The Terms gate as minty-web draws it: ``GET /api/me/terms`` and ``POST /api/me/terms/accept``.

Since 2026-09-29 Flask's ``/entity`` hands the browser to minty-web's entity list whether or
not a Terms acceptance is owed (``MINTY_WEB_HUB``), so minty-web draws the acceptance panel
itself - a port of ``templates/legal/_terms_panel.html``, over every page of that app, the way
Flask's request gate covers every page of this one. These two routes are what it reads and
posts. Everything they decide is the Jinja panel's own:

* WHAT IS OWED is ``services/gate.terms_owed`` - the function the panel over the Select
  Company list reads (through ``outstanding_terms_context``);
* ACCEPTING is ``services/consent.accept_current_terms`` - the checks ``POST /legal/accept``
  makes, word for word: not ticked, the version changed under the reader, no document. The
  document's fingerprint comes from the registry, never from the client, and the row says
  where it was given: ``source = "hub"``.

Bearer-only (``blueprints/shared/hub_api.py``): the calls normally carry no Flask session, so
the request gate never sees them - and both endpoints are on its allow-list anyway
(``routes/gate.py``), since a client that did send the session cookie would otherwise be
refused the very route that lets it agree. An acceptance recorded here is honoured by the gate
on the person's next Flask page - it falls back to the database whenever its session cache has
no answer.
"""

from __future__ import annotations

from flask import request, url_for
from loguru import logger

from blueprints.legal import legal_bp
from blueprints.legal.models.terms_consent import SOURCE_HUB
from blueprints.legal.services.consent import (ACCEPT_FAILED,
                                               ACCEPT_NOT_TICKED,
                                               ACCEPT_VERSION_CHANGED,
                                               accept_current_terms)
from blueprints.legal.services.gate import terms_owed
from blueprints.shared import hub_api
from models.db import db


@legal_bp.route("/api/me/terms", methods=["GET", "OPTIONS"])
def hub_terms_status():
    """``{owed: false}``, or everything the panel draws: the live document (its HTML is
    ``legal.render``'s, which escapes the source before applying markup, so it is safe to
    inject - the same markup ``GET /legal/content/<kind>`` serves the onboarding app), whether
    this is a re-acceptance and of what, and the links the panel carries."""
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

    document = owed["document"]
    previous = owed["previous_version"]
    return hub_api.respond(
        {
            "owed": True,
            "document": {
                "version": document.version,
                "effective_date": document.effective_date,
                "html": document.html,
                "show_draft_notice": document.show_draft_notice,
            },
            "is_update": owed["is_update"],
            "previous_version": previous,
            # Paths on this app; minty-web prefixes its MINTY_URL. Public pages - a person
            # held at the gate must be able to read what they are asked to agree to.
            "links": {
                "terms": url_for("legal.terms"),
                "privacy": url_for("legal.privacy"),
                "previous": url_for("legal.terms_version", version=previous) if previous else None,
            },
        }
    )


@legal_bp.route("/api/me/terms/accept", methods=["POST", "OPTIONS"])
def hub_terms_accept():
    """Record the agreement: ``{accepted: true, terms_version}`` -> ``{ok: true}``.

    400 when not ticked, 409 ``version_changed`` (with the live ``terms_version``) when the
    Terms changed while the modal sat open - the client re-reads and asks again - and 500
    when there is no document to agree to.
    """
    early, user = hub_api.guard()
    if early is not None:
        return early

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    submitted = payload.get("terms_version")
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
