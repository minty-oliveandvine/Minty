"""Pytest fixtures for creating the Flask test application.

The legacy bootstrap loads required environment variables during import time, so
this fixture injects a deterministic minimal environment before importing `main`.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator

import pytest


def _clear_cached_modules() -> None:
    """Clear cached project modules so a clean app can be created."""
    for module_name in list(sys.modules):
        if module_name.startswith(
            (
                "app",
                "main",
                "pettycash",
                "services.app_runtime",
                "services.auth",
                "services.helpers",
                "models",
                "blueprints",
            )
        ):
            sys.modules.pop(module_name, None)


@pytest.fixture(scope="session")
def app() -> Iterator:
    db_path = os.path.abspath("tmp_test.sqlite")
    sqlite_uri = "sqlite:///" + db_path.replace("\\", "/")

    env = {
        "FLASK_ENV": "development",
        "ENV": "development",
        "SECRET_KEY": "test-secret-key",
        "WTF_CSRF_SECRET_KEY": "test-csrf-secret-key",
        "LOCAL_DATABASE_URI": sqlite_uri,
        "RDS_DATABASE_URI": sqlite_uri,
        "S3_BUCKET": "dummy-bucket",
        "S3_KEY": "dummy-key",
        "S3_SECRET": "dummy-secret",
        "S3_REGION": "us-east-1",
        "XERO_CLIENT_ID": "dummy-xero-client-id",
        "XERO_CLIENT_SECRET": "dummy-xero-secret",
        "XERO_REDIRECT_URI": "https://localhost/xero/callback",
        "SPIRE_KEY": "dummy-spire-key",
        "XERO_API_BASE_URL": "https://api.xero.com",
        "MAIL_SERVER": "localhost",
        "MAIL_PORT": "587",
        "FLASK_DEBUG": "False",
    }

    old_env = {key: os.environ.get(key) for key in env}
    try:
        for key, value in env.items():
            os.environ[key] = value

        _clear_cached_modules()
        main_module = importlib.import_module("main")
        flask_app = main_module.app
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        flask_app.config["DEBUG"] = False

        yield flask_app
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client
