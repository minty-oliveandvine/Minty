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
prints the path only, with the secret segments blanked. Render switches gunicorn's
back on through ``GUNICORN_CMD_ARGS``, so ``gunicorn.conf.py`` gives gunicorn a
logger that writes no access line (``services/app_runtime/gunicorn_logging.py``).

Every request also opens a trace (``minty_shared.logctx``): an incoming ``X-Request-ID`` is
kept when well formed (the Django APIs send theirs), echoed on the response, and carried by
every line written meanwhile, with the route as the fallback step. The sign-in layers add the
user and entity (``blueprints/shared/bearer_api.py``, ``blueprints/petty_cash_api/guard.py``).
"""

from __future__ import annotations

import time

from flask import Flask, g, request
from minty_shared import logctx
from services.app_runtime.log import logger

from services.app_runtime.env import is_development

#: Route arguments whose value is a secret: ``/reset_password/<token>``,
#: ``/invitation/accept/<token>``, ``/Minty_Report/<path:entity_and_date>/`` and
#: ``/api/petty-cash/v1/public/share/<path:share_path>`` (their last segment is the share secret).
SECRET_PATH_ARGS = frozenset({"token", "entity_and_date", "share_path"})


def _secret_values() -> list[str]:
    args = request.view_args or {}
    return [str(args[name]) for name in SECRET_PATH_ARGS if args.get(name)]


def loggable_path() -> str:
    """``request.path`` with every secret segment replaced; never the query string."""
    path = request.path
    for value in _secret_values():
        path = path.replace(value, "[redacted]")
    return path


def open_trace() -> None:
    """``before_request``: start the access line's clock and the request's trace. Registered by
    the bootstrap straight after ``preview_origin.capture`` (which neither logs nor binds), so it
    precedes every hook that does - one opened later would miss their lines and wipe the user
    the sign-in hooks bind."""
    g._request_started = time.perf_counter()
    g._trace = logctx.start_trace(request.headers.get(logctx.TRACE_HEADER))
    logctx.set_default_step(request.endpoint)


def init_app(app: Flask) -> None:
    hsts = not is_development()

    @app.teardown_request
    def _end_trace(_exc):
        logctx.reset()

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
        trace = g.get("_trace")
        if trace:
            headers[logctx.TRACE_HEADER] = trace

        if request.endpoint != "static":
            started = g.pop("_request_started", None)
            took = f" {(time.perf_counter() - started) * 1000:.0f}ms" if started else ""
            logger.info(f"{request.method} {loggable_path()} {response.status_code}{took}")
        return response
