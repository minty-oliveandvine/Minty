"""Gunicorn's logger, minus its access line (``gunicorn.conf.py`` names it).

Gunicorn's access log prints the whole request line, query string and path included:
``/entity/<id>/enter?token=<module JWT>``, ``/callback?code=...``, ``/reset_password/<token>``.
Render's native Python runtime switches it on through ``GUNICORN_CMD_ARGS`` even though neither
the start command nor the Procfile asks for it, and production's log held both kinds of secret
(2026-10-20). The environment can set ``accesslog``, but only the config file sets
``logger_class``, so the line is stopped here. Every request is still logged once, by
``pettycash.core.http_hardening``: the path only, its secret segments blanked. The error log is
gunicorn's, unchanged.
"""
from __future__ import annotations

from gunicorn.glogging import Logger


class NoAccessLogger(Logger):
    """Writes no access line, whatever ``accesslog`` says."""

    def access(self, resp, req, environ, request_time):
        return
