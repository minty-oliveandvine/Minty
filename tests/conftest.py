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

# The models' schema is DATABASE_URL's ?schema=, read when blueprints.shared.schema is first
# imported - which is the collection-time import just below, long before the ``app`` fixture
# sets the real URL. Point it at the test database now (the harness's schema, not whatever a
# developer's .env says), so the first registry and the app's agree.
try:
    os.environ["DATABASE_URL"] = pg_harness.app_database_url(
        pg_harness._with_database(pg_harness.admin_uri(), pg_harness.test_dbname())
    )
except RuntimeError:
    pass  # no server configured: the database fixtures say so when a test needs one

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
    # The route-coverage gate runs LAST, so in a serial run every other test has made its
    # requests before it judges them (tests/test_zz_route_coverage.py).
    gate = [item for item in items if item.name == "test_every_schema_touching_route_is_exercised"]
    for item in gate:
        items.remove(item)
        items.append(item)


# Every endpoint a REAL request reached in this process (tests/test_zz_route_coverage.py;
# what counts is decided in the ``app`` fixture's recorder). One set per process: under
# pytest-xdist each worker sends its set - with the app's live endpoints and whether the gate
# test ran there - to the controller at the end, and the controller judges once.
_HIT_ENDPOINTS: set[str] = set()
_LIVE_ENDPOINTS: set[str] = set()
_GATE_RAN = False
# Controller only.
_MERGED_HITS: set[str] = set()
_MERGED_LIVE: set[str] = set()
_MERGED_GATE_RAN = False
_WORKER_CRASHED = False


def pytest_runtest_logreport(report):
    global _GATE_RAN
    if report.when == "call" and report.nodeid.endswith(
        "test_zz_route_coverage.py::test_every_schema_touching_route_is_exercised"
    ):
        _GATE_RAN = True


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("PYTEST_XDIST_WORKER"):
        workeroutput = getattr(session.config, "workeroutput", None)
        if workeroutput is not None:
            workeroutput["hit_endpoints"] = sorted(_HIT_ENDPOINTS)
            workeroutput["live_endpoints"] = sorted(_LIVE_ENDPOINTS)
            workeroutput["route_gate_ran"] = _GATE_RAN
        return
    if not session.config.pluginmanager.has_plugin("dsession"):
        return  # not an xdist controller: the gate test itself judged (or skipped)
    from test_zz_route_coverage import incomplete_run, judge, report

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    why = incomplete_run(session.config, gate_ran=_MERGED_GATE_RAN, crashed=_WORKER_CRASHED)
    if why:
        if reporter is not None:
            reporter.write_line(f"route coverage not judged (partial run: {why})")
        return
    problems, total = judge(_MERGED_HITS, _MERGED_LIVE)
    if problems:
        if reporter is not None:
            reporter.write_sep("=", "route coverage", red=True)
            reporter.write_line(report(problems, total) + "\n(merged across every xdist worker)",
                                red=True)
        session.exitstatus = 1
    elif reporter is not None:
        reporter.write_line(f"route coverage: every one of {total} in-scope routes is tested "
                            "or a listed gap")


def pytest_testnodedown(node, error):  # xdist controller: a worker finished
    global _MERGED_GATE_RAN, _WORKER_CRASHED
    output = getattr(node, "workeroutput", {}) or {}
    _MERGED_HITS.update(output.get("hit_endpoints", []))
    _MERGED_LIVE.update(output.get("live_endpoints", []))
    _MERGED_GATE_RAN = _MERGED_GATE_RAN or bool(output.get("route_gate_ran"))
    if error is not None or not output:
        _WORKER_CRASHED = True


_MARK = "minty.route_under_test"
_REFUSED = "minty.route_refused"


def _install_route_recorder(flask_app) -> None:
    """Record an endpoint only when a request really ran its view (tests/test_zz_route_coverage.py).

    * Marked by an app-level ``before_request`` registered LAST, so it runs only once every
      earlier app-level hook (the terms gate, the token middleware, the read-only superuser
      block) has let the request through. Never for OPTIONS: Flask answers those without
      calling the view, and an OPTIONS sweep alone once "covered" ~50 routes.
    * Refusals flag the request: the ``services.authz`` helpers that every access decorator,
      ``permission_denied`` and the report module guard answer with (looked up by name at
      call time, so wrapping them here catches all of them), and Flask-Login's
      ``user_unauthorized`` signal, sent before its sign-in redirect.
    * Recorded in ``after_request`` unless refused, a server error, or a 401/403/404/405.

    The mark lives in ``request.environ``, not ``g``: requests made inside a test's own app
    context share one ``g``, so a mark there could leak into the next request.
    """
    import functools

    from flask import request as _request
    from flask_login import user_unauthorized

    from services import authz

    _LIVE_ENDPOINTS.update(rule.endpoint for rule in flask_app.url_map.iter_rules())
    flask_app.extensions["hit_endpoints"] = _HIT_ENDPOINTS

    def _flag_refusal(*_args, **_kwargs):
        try:
            _request.environ[_REFUSED] = True
        except RuntimeError:  # outside a request: nothing to flag
            pass

    def _flagging(helper):
        @functools.wraps(helper)
        def wrapper(*args, **kwargs):
            _flag_refusal()
            return helper(*args, **kwargs)

        return wrapper

    for name in ("_auth_redirect", "_forbidden", "_bad_request"):
        current = getattr(authz, name)
        if not getattr(current, "_route_recorder", False):
            wrapped = _flagging(current)
            wrapped._route_recorder = True
            setattr(authz, name, wrapped)
    user_unauthorized.connect(_flag_refusal, flask_app, weak=False)

    @flask_app.before_request
    def _mark_endpoint():  # pragma: no cover - bookkeeping
        if _request.endpoint and _request.method != "OPTIONS":
            _request.environ[_MARK] = _request.endpoint

    @flask_app.after_request
    def _record_endpoint(response):  # pragma: no cover - bookkeeping
        endpoint = _request.environ.get(_MARK)
        if (
            endpoint
            and not _request.environ.get(_REFUSED)
            and response.status_code < 500
            and response.status_code not in (401, 403, 404, 405)
        ):
            flask_app.extensions["hit_endpoints"].add(endpoint)
        return response


@pytest.fixture(scope="session")
def built_database() -> Iterator[pg_harness.BuiltDatabase]:
    """The PostgreSQL database built from docs/schema/01_schema_rebased.sql.

    Built once per session (per xdist worker), dropped at the end unless
    MINTY_TEST_PG_KEEP=1. The server comes from MINTY_TEST_PG_URI, or failing that from
    DATABASE_URL. See tests/pg_harness.py for why there is no SQLite mode.
    """
    built = pg_harness.build()
    try:
        yield built
    finally:
        built.drop()


@pytest.fixture(scope="session")
def app(built_database) -> Iterator:
    env = {
        "APP_ENV": "development",
        "SECRET_KEY": "test-secret-key",
        "DATABASE_URL": pg_harness.app_database_url(built_database.uri),
        "S3_URL": "https://dummy-key:dummy-secret@s3.us-east-1.backblazeb2.com/dummy-bucket",
        "XERO_CLIENT_ID": "dummy-xero-client-id",
        "XERO_CLIENT_SECRET": "dummy-xero-secret",
        "SPIRE_KEY": "dummy-spire-key",
        "SMTP_URL": "smtp://localhost:587",
        "MAIL_FROM": "noreply@minty.test",
        # empty = config.py's MAIL_FROM fallback; a developer's .env may name a real sender
        "SUBSCRIPTION_EMAIL": "",
        # empty = config.py's localhost:8010 default; the local .env runs Flask on 5001
        "PETTY_CASH_URL": "",
        # the entity list and the profile hand over to minty-web when this is on - a developer's
        # .env may say so (load_dotenv never overrides what is set here); the suite keeps the
        # Jinja list its tests describe, and tests/test_hub_*.py flip it per test
        "MINTY_WEB_HUB": "0",
        # the app starts the daily billing jobs when this is on - a developer's .env may say so;
        # a test app must never run them (tests/test_subscription_scheduler.py flips it per test)
        "SUBSCRIPTION_SCHEDULER_ENABLED": "0",
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
        # No test opens an SMTP connection. Flask-Mail decides ``suppress`` from TESTING
        # when the app is built - before TESTING is set above - so an unpatched send dialled
        # SMTP_URL (localhost:587). Suppressed sends still fire ``email_dispatched``, so
        # ``record_messages`` works; the fakes in char_factories replace ``send`` outright.
        flask_app.extensions["mail"].suppress = True

        _install_route_recorder(flask_app)

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


@pytest.fixture
def caplog(caplog):
    """pytest's ``caplog``, also fed by loguru - which the services log through, and which
    pytest does not see on its own. With it a test asserts on what the engine logged the
    same way in both engines (``minty-billing-api`` logs through stdlib ``logging``)."""
    from loguru import logger

    handler_id = logger.add(caplog.handler, format="{message}", level=0)
    yield caplog
    logger.remove(handler_id)
