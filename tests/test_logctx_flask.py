"""The one log line (minty_shared.logctx) as Flask writes it: a trace per request, opened
before every other ``before_request`` hook, taken from a well-formed ``X-Request-ID`` and
echoed back; the person bound where the sign-in is verified, the company where a Minty
backend's assertion names it; and the trace carried into background threads."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from minty_shared import logctx

HEX8 = re.compile(r"[0-9a-f]{8}")


@pytest.fixture(autouse=True)
def _clean():
    logctx.reset()
    yield
    logctx.reset()


def _access(caplog):
    lines = [r for r in caplog.records if r.name == "minty" and re.match(r"GET /health ", r.getMessage())]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    return lines[0]


def test_the_trace_opens_before_every_hook_that_logs(app):
    # Only preview_origin.capture (no log line, no binding) runs ahead of it.
    names = [f.__name__ for f in app.before_request_funcs[None]]
    assert names[:2] == ["capture", "open_trace"]


def test_well_formed_trace_is_kept_and_echoed(client, caplog):
    resp = client.get("/health", headers={"X-Request-ID": "deadbeef"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "deadbeef"
    record = _access(caplog)
    assert (record.trace, record.step) == ("deadbeef", "health_check")
    assert re.fullmatch(r"GET /health 200 \d+ms", record.getMessage())


@pytest.mark.parametrize("incoming", [None, "short", "DEADBEEF", "deadbeef] [user=x"])
def test_a_missing_or_malformed_trace_is_replaced(client, caplog, incoming):
    headers = {"X-Request-ID": incoming} if incoming is not None else {}
    resp = client.get("/health", headers=headers)
    assert HEX8.fullmatch(resp.headers["X-Request-ID"])
    assert _access(caplog).trace == resp.headers["X-Request-ID"]


def test_nothing_outlives_the_request(client):
    client.get("/health", headers={"X-Request-ID": "deadbeef"})
    assert logctx.current() == {"trace": "-", "user": "-", "entity": "-", "step": "-"}


def test_a_verified_bearer_names_its_person_only(app):
    from blueprints.shared import bearer_api

    token = jwt.encode({"user_id": "u-1", "entity_id": "e-1"}, "test-secret-key", algorithm="HS256")
    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        logctx.start_trace()
        assert bearer_api.claims_from_bearer()["user_id"] == "u-1"
        assert (logctx.current()["user"], logctx.current()["entity"]) == ("u-1", "-")
    forged = jwt.encode({"user_id": "u-2"}, "not-the-key-not-the-key-not-the-key", algorithm="HS256")
    with app.test_request_context(headers={"Authorization": f"Bearer {forged}"}):
        logctx.start_trace()
        assert bearer_api.claims_from_bearer() is None
        assert logctx.current()["user"] == "-"


def test_a_backend_assertion_names_its_company(app):
    from blueprints.xero.routes import routes

    now = datetime.now(timezone.utc)
    claims = {"scope": "xero-access-token", "entity_id": "e-9", "user_id": "u-9",
              "iat": now, "exp": now + timedelta(minutes=1)}
    token = jwt.encode(claims, "test-secret-key", algorithm="HS256")
    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        logctx.start_trace()
        got, error = routes._authenticate_internal_caller()
        assert error is None and got["entity_id"] == "e-9"
        assert (logctx.current()["user"], logctx.current()["entity"]) == ("u-9", "e-9")


def test_a_background_job_keeps_the_trace(app):
    from blueprints.entity.services import settings as entity_settings

    seen, done = {}, threading.Event()

    def work():
        seen.update(logctx.current())
        done.set()

    with app.app_context():
        logctx.start_trace("a1b2c3d4")
        logctx.bind(user="u-1", entity="e-1")
        entity_settings._run_in_background("test job", work, entity_id="e-1", flask_app=app)
    assert done.wait(5)
    assert (seen["trace"], seen["user"], seen["entity"]) == ("a1b2c3d4", "u-1", "e-1")


def test_every_line_is_written_in_the_one_format(app):
    from minty_shared.logctx import MintyFormatter

    from services.app_runtime.log import logger

    handlers = [h for h in logging.getLogger().handlers if isinstance(h.formatter, MintyFormatter)]
    assert len(handlers) == 2  # stderr and app.log, once however often create_app ran
    logctx.start_trace("a1b2c3d4")
    record = logging.LogRecord("minty", logging.INFO, __file__, 1, "hello {}", (), None)
    line = handlers[0].formatter.format(record)
    assert re.fullmatch(r"\S+Z INFO \[trace=a1b2c3d4\] \[user=-\|entity=-\|step=-\] hello \{\}", line)
    assert logger.name == "minty"
