"""Bootstrap adapters for Flask app factory.

Keep compatibility with existing ``create_app()`` usage while routing to the
legacy monolith module for now. This file is intentionally thin: it should only
coordinate app wiring and return the shared application instance.
"""

from __future__ import annotations

from services.app_runtime.legacy import app
from services.app_runtime.legacy.compat import (csrf, db, login_manager, mail,
                                                migrate)


def _configure_app(application=app):
    return application


def _init_extensions(application=app):
    return application


def _init_session(application=app):
    return application


def create_app():
    # Legacy bootstrap is already assembled in legacy_app.py, including
    # blueprint loading and hook registration.
    return _configure_app(_init_extensions(_init_session(app)))


__all__ = ["app", "create_app", "db", "login_manager", "csrf", "mail", "migrate"]
