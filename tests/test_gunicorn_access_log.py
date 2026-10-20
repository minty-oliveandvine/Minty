"""Gunicorn writes no access line: ``gunicorn.conf.py`` names ``NoAccessLogger``.

Render's native Python runtime switches gunicorn's access log on (``GUNICORN_CMD_ARGS``) although
neither the start command nor the Procfile asks for it, and that log prints the whole request
line - ``/entity/<id>/enter?token=<module JWT>``, ``/callback?code=...`` (found in production's
log 2026-10-20). The one access line is ``pettycash/core/http_hardening.py``'s, which prints the
path only with its secrets blanked. ``GUNICORN_CMD_ARGS`` can turn ``accesslog`` back on, but
``logger_class`` comes only from the config file, so the logger is where it is stopped.

Gunicorn imports ``fcntl``/``pwd``/``grp`` and Unix sockets, so on Windows the logger test runs
with stand-ins for the missing modules and the config test (gunicorn's own loader) is skipped;
CI runs both on Linux.
"""
from __future__ import annotations

import io
import logging
import os
import socket
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SECRET = "SECRET-module-token"


@pytest.fixture
def glogging(monkeypatch):
    for name in ("fcntl", "pwd", "grp"):
        try:
            __import__(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for name in ("geteuid", "getegid"):  # Config()'s user/group defaults
        if not hasattr(os, name):
            monkeypatch.setattr(os, name, lambda: 0, raising=False)
    import gunicorn.glogging

    return gunicorn.glogging


def _request_log(glogging, logger_cls):
    """What ``logger_cls`` writes for one request whose query holds a token."""
    from gunicorn.config import Config

    cfg = Config()
    cfg.set("accesslog", "-")
    log = logger_cls(cfg)
    stream = io.StringIO()
    for handler in log.access_log.handlers:
        handler.setStream(stream)

    req = types.SimpleNamespace(
        method="GET", path="/entity/x/enter", query=f"token={SECRET}",
        uri=f"/entity/x/enter?token={SECRET}", version=(1, 1), headers=[],
    )
    resp = types.SimpleNamespace(status="302 FOUND", sent=0, headers=[], response_length=0)
    environ = {
        "REMOTE_ADDR": "10.0.0.1", "REQUEST_METHOD": "GET", "RAW_URI": req.uri,
        "PATH_INFO": req.path, "QUERY_STRING": req.query, "SERVER_PROTOCOL": "HTTP/1.1",
    }
    log.access(resp, req, environ, __import__("datetime").timedelta(milliseconds=3))
    for handler in log.access_log.handlers:
        handler.flush()
    return stream.getvalue()


def test_gunicorns_own_logger_would_print_the_token(glogging):
    """The leak this file exists for - and proof the capture below can see one."""
    assert SECRET in _request_log(glogging, glogging.Logger)


def test_no_access_logger_prints_nothing(glogging):
    from services.app_runtime.gunicorn_logging import NoAccessLogger

    assert _request_log(glogging, NoAccessLogger) == ""


def test_the_error_log_still_works(glogging):
    from gunicorn.config import Config

    from services.app_runtime.gunicorn_logging import NoAccessLogger

    log = NoAccessLogger(Config())
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    log.error_log.addHandler(handler)
    try:
        log.error("worker timeout")
    finally:
        log.error_log.removeHandler(handler)
    assert "worker timeout" in stream.getvalue()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="gunicorn's loader needs Unix sockets; CI (Linux) runs this")
def test_the_environment_cannot_turn_the_access_line_back_on(monkeypatch):
    """Render's GUNICORN_CMD_ARGS sets ``--access-logfile -``; the config file's logger still wins."""
    from gunicorn.app.wsgiapp import WSGIApplication

    from services.app_runtime.gunicorn_logging import NoAccessLogger

    monkeypatch.chdir(REPO)
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--preload --access-logfile - --bind=0.0.0.0:10000")
    monkeypatch.setattr(sys, "argv", ["gunicorn", "app:app"])

    cfg = WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]").cfg

    assert cfg.accesslog == "-"  # the environment did switch it on...
    assert cfg.logger_class is NoAccessLogger  # ...and the logger writes nothing anyway
    assert cfg.bind == ["0.0.0.0:10000"]  # the config file overrides nothing else


def test_the_config_file_sets_the_logger_and_nothing_else():
    """``gunicorn.conf.py`` sits where gunicorn looks for it (the working directory, the repo root
    for Render's ``gunicorn app:app`` and docker/Dockerfile's ``gunicorn ... main:app``)."""
    namespace: dict = {}
    exec(compile((REPO / "gunicorn.conf.py").read_text(encoding="utf-8"), "gunicorn.conf.py", "exec"), namespace)
    settings = {k: v for k, v in namespace.items() if not k.startswith("__")}
    assert settings == {"logger_class": "services.app_runtime.gunicorn_logging.NoAccessLogger"}
    assert os.path.isfile(REPO / "services" / "app_runtime" / "gunicorn_logging.py")
