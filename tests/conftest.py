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

import pg_harness  # tests/ is on sys.path via rootdir conftest; no package __init__

# Twenty-odd test modules import project code at collection time, so a FIRST declarative
# registry exists before the session app fixture re-imports everything into a second one.
# SQLAlchemy's configure_mappers() configures every registry it knows about, so if that
# first registry is incomplete (a test imported blueprints.entity.models.entity but nothing
# imported EntityCashDetailV2) the first query anywhere in the session that triggers
# configuration fails with "failed to locate a name". Importing the model hub here, at
# collection start, makes the first registry complete whatever the test modules import.
import models.db  # noqa: E402,F401


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TESTS_DIR = os.path.abspath(os.path.dirname(__file__))


def _clear_cached_modules() -> None:
    """Clear cached project modules so a clean app can be created.

    Deliberately a prefix list, not "every project module": many tests import
    ``services.permission_policy`` and friends at module level and monkeypatch them,
    and evicting those would leave the tests patching a module the app no longer uses.
    """
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


def _rebind_stale_model_references() -> None:
    """Point non-evicted project modules at the live model classes and `db`.

    ``services.permission_policy``, ``services.authz``, ``services.user_presence`` and
    others are imported at collection time by test modules and are deliberately NOT
    evicted (tests monkeypatch attributes on them). But they did ``from models.db import
    User, UserEntity, db`` at that time, so they hold classes from the collection-time
    registry whose ``db`` was never ``init_app``'d. In a full run every real-database
    permission check then raised "The current Flask app is not registered with this
    'SQLAlchemy' instance" - a test-order dependence that only route tests with a real
    database ever hit, which is why the suite had almost none. Keep the module objects
    (so patches still land) and swap the model/db references to the live ones.
    """
    from flask_sqlalchemy import SQLAlchemy

    live_models = importlib.import_module("models.db")
    live_db = live_models.db
    for module_name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None) or ""
        if not path:
            continue
        path = os.path.abspath(path)
        if not path.startswith(PROJECT_ROOT) or ".venv" in path or path.startswith(TESTS_DIR):
            continue
        for attr, value in list(vars(module).items()):
            if isinstance(value, SQLAlchemy) and value is not live_db:
                setattr(module, attr, live_db)
            elif isinstance(value, type) and hasattr(value, "__tablename__"):
                live = getattr(live_models, value.__name__, None)
                if live is not None and live is not value:
                    setattr(module, attr, live)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "char: characterisation test (docs/modernisation_plan.md Part 1 B3). Pins behaviour "
        "through routes/services; in Postgres mode it is expected to fail until the models "
        "match the redesigned schema (phase C), so failures there are reported as xfail.",
    )


def pytest_collection_modifyitems(config, items):
    if not pg_harness.enabled():
        return
    for item in items:
        if item.get_closest_marker("char"):
            item.add_marker(pytest.mark.xfail(
                strict=False,
                reason="Postgres from 01_schema_rebased.sql: the current models do not match yet "
                       "(APPLICATION_CHANGES.md). Becomes a hard test as phase C lands.",
            ))


@pytest.fixture(scope="session")
def built_database() -> Iterator[pg_harness.BuiltDatabase | None]:
    """The PostgreSQL database built from docs/schema/01_schema_rebased.sql, or None.

    Only when MINTY_TEST_PG_URI is set. Built once per session, dropped at the end
    unless MINTY_TEST_PG_KEEP=1. See tests/pg_harness.py for why.
    """
    if not pg_harness.enabled():
        yield None
        return
    built = pg_harness.build()
    try:
        yield built
    finally:
        built.drop()


@pytest.fixture(scope="session")
def app(built_database) -> Iterator:
    if built_database is not None:
        db_uri = built_database.uri
    else:
        db_path = os.path.abspath("tmp_test.sqlite")
        db_uri = "sqlite:///" + db_path.replace("\\", "/")

    env = {
        "FLASK_ENV": "development",
        "ENV": "development",
        "SECRET_KEY": "test-secret-key",
        "WTF_CSRF_SECRET_KEY": "test-csrf-secret-key",
        "LOCAL_DATABASE_URI": db_uri,
        "RDS_DATABASE_URI": db_uri,
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
        _rebind_stale_model_references()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        flask_app.config["DEBUG"] = False

        # Record every endpoint the suite exercises. tests/test_zz_route_coverage.py compares
        # the set against tests/_baseline/route_inventory.json (the routes whose code touches
        # a column the schema redesign changes) and names the ones no test reached.
        from flask import request as _request

        flask_app.extensions["hit_endpoints"] = set()

        @flask_app.before_request
        def _record_endpoint():  # pragma: no cover - bookkeeping
            if _request.endpoint:
                flask_app.extensions["hit_endpoints"].add(_request.endpoint)

        if built_database is None:
            # SQLite: the models say schema "pettycashv2", which SQLite only knows as an
            # ATTACHed database. The per-file fixtures ATTACH ':memory:' on ONE pooled
            # connection, so a second connection sees no schema at all and create_all
            # fails with "unknown database pettycashv2" whenever the pool hands out a
            # different connection. Attach a shared FILE on every new connection
            # instead; the fixtures' own ATTACH then fails harmlessly (name in use).
            from sqlalchemy import event

            from models.db import db

            # Per process, so two pytest runs at once (a full run in the background
            # while one file is iterated on) do not fight over the same file.
            schema_path = os.path.abspath(f"tmp_test_pettycashv2_{os.getpid()}.sqlite")
            if os.path.exists(schema_path):
                os.remove(schema_path)
            posix = schema_path.replace("\\", "/")

            def _attach_schema(dbapi_conn, _record):
                dbapi_conn.execute(f"ATTACH DATABASE '{posix}' AS pettycashv2")

            with flask_app.app_context():
                event.listen(db.engine, "connect", _attach_schema)
                db.engine.dispose()  # so the listener applies to every connection from here on

        if built_database is not None:
            # The schema came from the file, not from the models. Every DB-backed test
            # file calls db.create_all() in its own fixture; on Postgres that would
            # add old-shape tables (roles, shop_expense, ...) beside the redesigned
            # ones and hide exactly the mismatches this mode exists to find.
            from models.db import db

            db.create_all = lambda *args, **kwargs: None  # type: ignore[method-assign]

        yield flask_app
    finally:
        if built_database is None:
            try:
                from models.db import db

                with flask_app.app_context():
                    db.engine.dispose()
                os.remove(os.path.abspath(f"tmp_test_pettycashv2_{os.getpid()}.sqlite"))
            except Exception:
                pass
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client
