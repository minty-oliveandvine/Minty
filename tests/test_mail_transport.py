"""Every SMTP connection this app opens times out (``services/app_runtime/mail.py``).

Flask-Mail 0.10.0 opened ``smtplib.SMTP(server, port)`` with no timeout, so a mail server
that accepted the connection and went quiet hung the sign-in code request (which holds its
database transaction open for the send) and the billing pass (which holds the scheduler
lock) for good.
"""
from __future__ import annotations

import inspect
from importlib.metadata import version

import pytest
from flask_mail import Message


class _FakeSMTP:
    """Records how it was opened and what it was asked to do."""

    opened: list = []

    def __init__(self, host, port, timeout=None, **kwargs):
        self.calls = []
        _FakeSMTP.opened.append((type(self).__name__, host, port, timeout, self))

    def set_debuglevel(self, level):
        pass

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username))

    def sendmail(self, *args, **kwargs):
        self.calls.append("sendmail")

    def quit(self):
        self.calls.append("quit")


class _FakeSMTP_SSL(_FakeSMTP):
    pass


@pytest.fixture
def smtp(app, monkeypatch):
    """The app's real mail state, sending for real into the fakes."""
    import smtplib

    _FakeSMTP.opened = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP_SSL)
    state = app.extensions["mail"]
    monkeypatch.setattr(state, "suppress", False)
    monkeypatch.setattr(state, "server", "smtp.example.test")
    monkeypatch.setattr(state, "username", "relay-user")
    monkeypatch.setattr(state, "password", "relay-pass")
    return state


def _message():
    return Message(subject="hello", sender="noreply@minty.test",
                   recipients=["someone@minty.test"], body="hi")


def test_a_send_through_the_app_opens_smtp_with_the_timeout(app, smtp):
    with app.app_context():
        app.extensions["mail"].send(_message())

    [(kind, host, port, timeout, conn)] = _FakeSMTP.opened
    assert (kind, host, port, timeout) == ("_FakeSMTP", "smtp.example.test", 587, 10.0)
    # Everything else is Flask-Mail's own sequence, unchanged.
    assert conn.calls == ["starttls", ("login", "relay-user"), "sendmail", "quit"]


def test_ssl_connections_time_out_too(app, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "use_ssl", True)
    monkeypatch.setattr(smtp, "use_tls", False)
    with app.app_context():
        app.extensions["mail"].send(_message())

    [(kind, _host, _port, timeout, _conn)] = _FakeSMTP.opened
    assert (kind, timeout) == ("_FakeSMTP_SSL", 10.0)


def test_the_mail_object_connects_the_same_way(app, smtp):
    """``pettycash.core.bootstrap`` hands out the ``Mail`` object itself, whose own
    ``connect`` would otherwise build Flask-Mail's plain connection."""
    from services.app_runtime.mail import Mail

    with app.app_context():
        Mail().send(_message())

    assert [entry[3] for entry in _FakeSMTP.opened] == [10.0]


def test_a_blank_timeout_falls_back_rather_than_blocking_forever():
    from services.app_runtime.mail import DEFAULT_TIMEOUT, Mail

    assert Mail().init_mail({"MAIL_TIMEOUT": None}).timeout == DEFAULT_TIMEOUT
    assert Mail().init_mail({"MAIL_TIMEOUT": "2.5"}).timeout == 2.5


def test_flask_mail_is_the_version_the_connection_was_copied_from():
    """``_Connection.configure_host`` is Flask-Mail 0.10.0's own plus ``timeout=``, and
    ``_State`` is built from the state's attributes. On an upgrade, re-check both against
    the new release, then move this pin."""
    import flask_mail

    assert version("flask-mail") == "0.10.0"
    parameters = list(inspect.signature(flask_mail._Mail.__init__).parameters)[1:]
    assert sorted(parameters) == sorted(vars(flask_mail.Mail().init_mail({})))
