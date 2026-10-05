"""The one rule for a redirect target taken from a request: a path on THIS site.

Every place that redirects to a value the request supplied (``?next=``, the Referer, a
value parked in the session) goes through ``safe_internal_path``. One copy, because the
hand-rolled ``startswith("/") and not startswith("//")`` checks it replaced each let an
attacker steer the redirect off-site:

  * ``/%09/evil.com``: browsers and Werkzeug drop tab/CR/LF from a URL, so this
    arrives as ``//evil.com`` (proven: Werkzeug's ``redirect()`` emitted
    ``Location: //evil.com``).
  * ``/\\evil.com``: browsers read a backslash as a slash.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import request


def safe_internal_path(candidate: str | None) -> str | None:
    """``candidate`` when it is a path on this site, else None.

    Refuses: anything not starting with ``/``; ``//host`` (protocol-relative); a
    backslash or any control character (both get rewritten into ``//host``); ``..``
    (no reason to hand anyone a traversal); and anything ``urlsplit`` reads as having
    a scheme or a host.
    """
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return None
    if "\\" in candidate or ".." in candidate:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
        return None
    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return None
    return candidate


def safe_next(candidate: str | None, default: str) -> str:
    """``safe_internal_path(candidate)``, or ``default`` when it is refused."""
    return safe_internal_path((candidate or "").strip()) or default


def safe_referrer(default: str) -> str:
    """Back where the person came from: the Referer's path when it is this site, else
    ``default``. The header is the browser's to fill in, so another site's address -
    or a missing one, which ``Referrer-Policy`` can cause - falls back."""
    parts = urlsplit(request.referrer or "")
    if parts.netloc != request.host:
        return default
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return safe_next(path, default)
