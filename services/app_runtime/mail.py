"""Flask-Mail with a timeout on every SMTP step.

Flask-Mail 0.10.0 opens ``smtplib.SMTP(server, port)`` with no timeout, so a mail server that
accepts the connection and then goes quiet blocks the caller forever. Every caller is
something that must not hang: the sign-in code request holds its database transaction open
for the send (``auth.services.email_auth.request_email_otp``), and the billing jobs send
inside the scheduler pass that holds the two-worker lock. ``MAIL_TIMEOUT`` (seconds, 10 by
default) bounds each step - connect, STARTTLS, login, each command - and a stalled server
then fails the send like a refused one, which every caller already handles.

Three pieces, because Flask-Mail opens connections in two places. Every send in this app
goes through ``current_app.extensions["mail"]`` - the configuration STATE, not the ``Mail``
object - and the state's own ``connect()`` builds Flask-Mail's module-level ``Connection``.
So the state is replaced (``_State``), the connection it builds is ours (``_Connection``),
and ``Mail.connect()`` goes through the state too. ``send`` is not overridden: the tests
replace ``flask_mail._MailMixin.send`` at the library boundary.

``_Connection.configure_host`` is Flask-Mail 0.10.0's own line for line, plus ``timeout=``.
``tests/test_mail_transport.py`` pins that version: re-check this on an upgrade.
"""
from __future__ import annotations

import smtplib

import flask_mail
from flask import current_app

#: Seconds each SMTP step may take before the send fails.
DEFAULT_TIMEOUT = 10.0


class _Connection(flask_mail.Connection):
    def configure_host(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        timeout = self.mail.timeout
        host: smtplib.SMTP | smtplib.SMTP_SSL
        if self.mail.use_ssl:
            host = smtplib.SMTP_SSL(self.mail.server, self.mail.port, timeout=timeout)
        else:
            host = smtplib.SMTP(self.mail.server, self.mail.port, timeout=timeout)

        host.set_debuglevel(int(self.mail.debug))

        if self.mail.use_tls:
            host.starttls()

        if self.mail.username and self.mail.password:
            host.login(self.mail.username, self.mail.password)

        return host


class _State(flask_mail._Mail):
    """Flask-Mail's configuration state, plus ``timeout``; it connects with ``_Connection``."""

    def __init__(self, *args, timeout: float, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    def connect(self) -> _Connection:
        return _Connection(self)


class Mail(flask_mail.Mail):
    """``flask_mail.Mail`` whose connections time out (``MAIL_TIMEOUT``)."""

    def init_mail(self, config, debug=False, testing=False) -> _State:
        state = super().init_mail(config, debug, testing)
        # Never None: smtplib reads None as "block forever", the very thing this prevents.
        timeout = float(config.get("MAIL_TIMEOUT") or DEFAULT_TIMEOUT)
        # The state's attributes ARE ``_Mail.__init__``'s parameters (pinned by a test).
        return _State(**vars(state), timeout=timeout)

    def connect(self) -> _Connection:
        app = getattr(self, "app", None) or current_app
        return app.extensions["mail"].connect()
