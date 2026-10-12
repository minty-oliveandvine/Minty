"""Session state for Terms acceptance, and what is owed.

The request gate (`routes/gate.py`) and minty-web's panel (`routes/hub.py`)
read from here, so they cannot disagree about what "already agreed" means.

There is no return path any more. The Flask acceptance screen was deleted on
2026-10-12 when the documents moved to minty-web: the panel now lifts where
the person stands, in minty-web, and never comes back here to resume a Flask
destination, so the gate no longer remembers one.

WHY THE SESSION STORES A VERSION, NOT A FLAG
--------------------------------------------
Reading the database on every request would be wasteful, so the answer is
cached in the login session. What is cached matters:

    session["terms_ok"] = "beta-1"       # not True

The check compares that string against the live version. So when the Terms are
rewritten and CURRENT_TERMS_VERSION moves to "beta-2", every existing session
stops matching *by itself* — no cache to clear, no sessions to wipe, no extra
step in the release. A boolean would have needed all three, and forgetting any
of them would silently let everyone past the gate.
"""

from __future__ import annotations

from flask import session

from legal import registry

# Cached answer: the version this session has been confirmed against.
TERMS_OK_SESSION_KEY = "terms_ok"


def mark_session_agreed(version: str | None = None) -> None:
    session[TERMS_OK_SESSION_KEY] = version or registry.current_version(
        registry.TERMS
    )


def session_agreed_to_current() -> bool:
    """Whether this session has already been checked against the live version."""
    return session.get(TERMS_OK_SESSION_KEY) == registry.current_version(
        registry.TERMS
    )


def clear_session_agreement() -> None:
    """Drop the cached answer.

    Called when a user logs in, because the session COOKIE survives logout: a
    different person signing in on the same browser would otherwise inherit the
    previous user's cached agreement and walk straight past the gate. The same
    hazard the per-login reset in bootstrap.py already handles for other flags.
    """
    session.pop(TERMS_OK_SESSION_KEY, None)
    # "terms_next" was the remembered destination, dropped with the Flask
    # acceptance screen (2026-10-12). Still popped here so a session cookie
    # written by the previous release does not carry a stale key around.
    session.pop("terms_next", None)


def terms_owed(user_id) -> dict | None:
    """What `user_id` still has to agree to, or None when nothing is owed.

    No session involved - the one answer to "does this person owe an acceptance, and of
    what". Since 2026-10-12 there is one asker left: minty-web's Terms panel
    (`routes/hub.py`, bearer, no session), which draws the document it holds itself. The
    `document` here is a manifest ENTRY, not the wording (`legal/registry.py`).

    None also when the live version is not in the manifest: nobody can be asked to agree to
    something this app could not record (see the gate's fail-open reasoning).
    """
    from blueprints.legal.services.consent import consents_for_user, has_consent

    document = registry.get_current(registry.TERMS)
    if document is None or has_consent(user_id):
        return None

    # "Out of date" and "never agreed" are both blocked, but they read very
    # differently to the person: one is being asked again, the other for the
    # first time. Only the former gets the "what changed" note.
    previous = consents_for_user(user_id)
    return {
        "document": document,
        "privacy_version": registry.current_version(registry.PRIVACY),
        "is_update": bool(previous),
        "previous_version": previous[0].terms_version if previous else None,
    }
