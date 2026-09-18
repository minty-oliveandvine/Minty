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

# Two route-unit modules stub pandas with ``sys.modules.setdefault("pandas", SimpleNamespace(...))``
# at import time. Collected before anything imported the real library, the stub then serves
# the whole session and the CSV export 500s ("no attribute 'Index'") - the order-dependence
# test_history_csv_lists_the_days_movements used to show. Importing pandas here first makes
# their setdefault a no-op.
import pandas  # noqa: E402,F401


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
        "char: characterisation test (docs/modernisation/modernisation_plan.md Part 1 B3). Pins behaviour "
        "through routes/services; in Postgres mode it is expected to fail until the models "
        "match the redesigned schema (phase C), so failures there are reported as xfail.",
    )
    config.addinivalue_line(
        "markers",
        "pipeline: the migration rehearsal (scripts/schema_migration/rehearse.py) as a test. "
        "Opt-in via MINTY_REHEARSAL_DUMP; needs the real dataset and a Postgres server.",
    )


# Characterisation modules still waiting for their phase C unit. Their tests
# are reported as xfail (the models do not match the redesigned schema yet). A unit REMOVES its
# module here when it is green on Postgres; from then on a regression there is a hard failure.
# docs/modernisation/modernisation_plan.md, Part 1 C0 rule 4.
PG_PENDING = {
    # empty since C6: every characterisation module is green on Postgres; a regression
    # there is a hard failure. (C7-C9 add their own modules and graduate them the same way.)
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        pending = item.path.name in PG_PENDING or f"{item.path.name}::{item.originalname}" in PG_PENDING
        if item.get_closest_marker("char") and pending:
            item.add_marker(pytest.mark.xfail(
                strict=False,
                reason=f"{item.path.name} is in PG_PENDING: its phase C unit has not landed "
                       "(docs/modernisation/modernisation_plan.md). Remove it from the set when the unit is green.",
            ))


# Every endpoint a request reached in this process (tests/test_zz_route_coverage.py). One
# set per process: under pytest-xdist each worker sends its set to the controller at the
# end, and the controller - which sees every worker - runs the coverage check once.
_HIT_ENDPOINTS: set[str] = set()
_MERGED_HITS: set[str] = set()  # controller only


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("PYTEST_XDIST_WORKER"):
        workeroutput = getattr(session.config, "workeroutput", None)
        if workeroutput is not None:
            workeroutput["hit_endpoints"] = sorted(_HIT_ENDPOINTS)
        return
    if not _MERGED_HITS:  # not an xdist controller: the zz test itself did the check
        return
    from test_zz_route_coverage import MISSES, route_coverage_misses

    misses, total = route_coverage_misses(_MERGED_HITS)
    if misses:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "route coverage", red=True)
            reporter.write_line(
                f"{len(misses)} of {total} schema-touching endpoints were never requested "
                f"(see {MISSES}); merged across every xdist worker", red=True,
            )
        session.exitstatus = 1


def pytest_testnodedown(node, error):  # xdist controller: a worker finished
    _MERGED_HITS.update(getattr(node, "workeroutput", {}).get("hit_endpoints", []))


@pytest.fixture(scope="session")
def built_database() -> Iterator[pg_harness.BuiltDatabase]:
    """The PostgreSQL database built from docs/schema/01_schema_rebased.sql.

    Built once per session (per xdist worker), dropped at the end unless
    MINTY_TEST_PG_KEEP=1. The server comes from MINTY_TEST_PG_URI, or failing that from
    .env's LOCAL_DATABASE_URI. See tests/pg_harness.py for why there is no SQLite mode.
    """
    built = pg_harness.build()
    try:
        yield built
    finally:
        built.drop()


@pytest.fixture(scope="session")
def app(built_database) -> Iterator:
    db_uri = built_database.uri

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
        # the subscription feature is ON for the suite (its default is off - production cut
        # over dark); tests/test_char_subscription_dark.py flips it per test
        "SUBSCRIPTION_ENABLED": "1",
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

        flask_app.extensions["hit_endpoints"] = _HIT_ENDPOINTS

        @flask_app.before_request
        def _record_endpoint():  # pragma: no cover - bookkeeping
            if _request.endpoint:
                flask_app.extensions["hit_endpoints"].add(_request.endpoint)

        # The schema came from the file, not from the models: a create_all here would add
        # whatever shape the models say beside the real tables and hide exactly the
        # mismatches the harness exists to find.
        from models.db import db

        db.create_all = lambda *args, **kwargs: None  # type: ignore[method-assign]

        yield flask_app
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def client(app):
    # NOT ``with app.test_client()``: that keeps the last request's context alive until the
    # fixture ends, and a request made inside a test's own ``with app.app_context()`` then
    # unwinds out of order at teardown ("Working outside of application context"). Tests
    # that need the session use ``client.session_transaction()``.
    return app.test_client()
