"""Session state for Terms acceptance, and the return-path rules.

Shared between the accept screen (Phase 3) and the request gate (Phase 4), so
both agree on what "already agreed" means and where a person goes afterwards.

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

# Where to send the person once they accept. Kept in the SESSION rather than in
# the URL — see safe_internal_path below.
TERMS_NEXT_SESSION_KEY = "terms_next"


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
    session.pop(TERMS_NEXT_SESSION_KEY, None)


def safe_internal_path(candidate: str | None) -> str | None:
    """Return `candidate` if it is a path inside Minty, else None.

    The destination is remembered in the session rather than round-tripped
    through the URL, so this is defence in depth rather than the only defence —
    but the rule is worth stating explicitly, because a redirect that can be
    steered off-site turns the acceptance screen into a phishing hop.

    Rejects, matching the rule already used for the billing portal's `next`
    (blueprints/subscription/routes/portal.py):

      * anything not starting with "/"      — absolute URLs, scheme-relative
      * "//evil.example"                    — protocol-relative, leaves the site
      * ".."                                — no reason to hand anyone a traversal

    And additionally rejects backslashes: some browsers normalise "/\\evil.com"
    to "//evil.com", which is protocol-relative again by another spelling.
    """
    if not candidate:
        return None
    if not candidate.startswith("/"):
        return None
    if candidate.startswith("//"):
        return None
    if ".." in candidate or "\\" in candidate:
        return None
    return candidate


def remember_intended_destination(path: str | None) -> None:
    safe = safe_internal_path(path)
    if safe:
        session[TERMS_NEXT_SESSION_KEY] = safe


def take_intended_destination() -> str | None:
    """Pop the remembered destination, re-validating on the way out.

    Re-validated because the session is storage like any other: if anything
    ever writes to that key without going through `remember_intended_destination`,
    this is the last place to catch it.
    """
    return safe_internal_path(session.pop(TERMS_NEXT_SESSION_KEY, None))
