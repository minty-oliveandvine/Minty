"""Log-in mode's "is this address known?" gate (`POST /auth/email/request-code` with
``mode: "login"``) follows the same identity rule as the verify step:
`resolve_user_by_email`, the ``email`` or ``xero_email`` column.

Until 2026-10-05 the gate read ``username`` and the ``email_otp`` table, so an account
only Xero could resolve was told "Please sign up first" while its Xero login worked,
and an address that was once sent a code passed the gate only for verify to refuse it.
"""
from __future__ import annotations

import pytest

import char_factories as F

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


def _user(app, db, *, username, email=None, xero_email=None):
    from models.db import User

    with app.app_context():
        made = F.make_user(db, username)
        row = db.session.get(User, made.id)
        row.email = email
        row.xero_email = xero_email
        db.session.commit()


def _login_code(client, address):
    return client.post(
        "/auth/email/request-code", json={"email": address, "mode": "login"}
    )


def test_an_address_held_only_as_the_xero_email_gets_a_code(app, client, db, mail):
    _user(app, db, username="someone-else@test.com", xero_email="Xero.Only@Test.com")

    sent = _login_code(client, "xero.only@test.com")
    assert sent.status_code == 200
    assert mail.to("xero.only@test.com")


def test_an_address_held_only_as_the_personal_email_gets_a_code(app, client, db, mail):
    _user(app, db, username="old-name@test.com", email="personal@test.com")

    assert _login_code(client, "personal@test.com").status_code == 200


def test_a_username_alone_no_longer_opens_the_gate(app, client, db):
    """Verify signs in by email/xero_email only, so a code sent to a username-only
    address could never be used."""
    _user(app, db, username="username-only@test.com", email="real@test.com")

    refused = _login_code(client, "username-only@test.com")
    assert refused.status_code == 404
    assert refused.get_json()["message"] == "Please sign up first"


def test_an_address_that_was_only_ever_sent_a_code_is_refused(app, client, db):
    from blueprints.auth.services.email_auth import request_email_otp

    with app.app_context():
        ok, _error = request_email_otp("code-only@test.com")
    assert ok

    assert _login_code(client, "code-only@test.com").status_code == 404


def test_an_unknown_address_is_refused_in_login_mode_and_open_for_sign_up(app, client, db):
    assert _login_code(client, "nobody@test.com").status_code == 404
    assert (
        client.post("/auth/email/request-code", json={"email": "nobody@test.com"}).status_code
        == 200
    )
