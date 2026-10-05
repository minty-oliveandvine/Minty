"""Response hardening every Flask response gets, and the access log line.

Security headers (2026-10-05, the URL security round):

* ``Referrer-Policy: same-origin``: another site never learns a path or query from
  here (share-link secrets, tokens). Not ``no-referrer``: ``WTF_CSRF_SSL_STRICT``
  needs a same-origin Referer on every HTTPS form post.
* ``X-Content-Type-Options: nosniff`` and ``X-Frame-Options: SAMEORIGIN``.
* HSTS outside local development (plain http there).
* ``Cache-Control: no-store`` on any page whose PATH holds a secret
  (``SECRET_PATH_ARGS``): password reset, invitation accept, share links.

The access log replaces gunicorn's (``--access-logfile``), which printed every
request line in full - query-string tokens and path secrets included. This one
prints the path only, with the secret segments blanked.
"""

from __future__ import annotations

import time

from flask import Flask, g, request
from loguru import logger

from services.app_runtime.env import is_development

#: Route arguments whose value is a secret: ``/reset_password/<token>``,
#: ``/invitation/accept/<token>``, ``/Minty_Report/<path:entity_and_date>/`` (its
#: last segment is the share secret).
SECRET_PATH_ARGS = frozenset({"token", "entity_and_date"})


def _secret_values() -> list[str]:
    args = request.view_args or {}
    return [str(args[name]) for name in SECRET_PATH_ARGS if args.get(name)]


def loggable_path() -> str:
    """``request.path`` with every secret segment replaced; never the query string."""
    path = request.path
    for value in _secret_values():
        path = path.replace(value, "[redacted]")
    return path


def init_app(app: Flask) -> None:
    hsts = not is_development()

    @app.before_request
    def _stamp_request_start():
        g._request_started = time.perf_counter()

    @app.after_request
    def _harden_response(response):
        headers = response.headers
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if hsts:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if _secret_values():
            headers["Cache-Control"] = "no-store"

        if request.endpoint != "static":
            started = g.pop("_request_started", None)
            took = f" {(time.perf_counter() - started) * 1000:.0f}ms" if started else ""
            logger.info(f"{request.method} {loggable_path()} {response.status_code}{took}")
        return response
