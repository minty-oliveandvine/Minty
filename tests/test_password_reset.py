"""Password reset - the legacy /login page's "Forgot Password?" modal.

``POST /reset_password`` saves a uuid4 on ``user.reset_token`` with a one-hour
``reset_token_expiry`` and emails a link to ``/reset_password/<token>``, where the
new password is set. Pinned here: the email is real HTML with its link on
PETTY_CASH_URL, an unknown address gets exactly the answer a known one gets (no
account-existence leak), and the expiry check works on Postgres's aware timestamps
(comparing them with a naive now() raised TypeError, so every link answered 500).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

PETTY_CASH_URL = "https://app.minty.test"


@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db

        import char_factories

        char_factories.truncate_all(app)  # TRUNCATE ... CASCADE on Postgres


@pytest.fixture
def mail(monkeypatch):
    import char_factories

    return char_factories.install_fake_mail(monkeypatch)


def _make_user(db_session, *, email, reset_token=None, reset_token_expiry=None) -> str:
    """A password account; returns its id (pettycash/core/hooks.py removes the
    session after every request, so a row held across one comes back detached)."""
    from models.db import User

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        username=email,
        first_name="Pat",
        last_name="Reset",
        password=generate_password_hash("old-password", method="pbkdf2:sha256"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
        reset_token=reset_token,
        reset_token_expiry=reset_token_expiry,
    )
    db_session.session.add(user)
    db_session.session.commit()
    return user.id


def _reload(db_session, user_id):
    from models.db import User

    db_session.session.expire_all()
    return db_session.session.get(User, user_id)


def _take_flashes(client) -> list:
    """The queued ``(category, message)`` flashes, removed from the session. The
    server-side session store hands each pair back as a list."""
    with client.session_transaction() as sess:
        return [tuple(flash) for flash in sess.pop("_flashes", [])]


def test_reset_request_emails_an_html_link_on_public_url(
    app, client, db_session, mail, monkeypatch
):
    """A known address typed in another case gets ONE html email whose link is on
    PETTY_CASH_URL and carries the token now saved on the account."""
    from blueprints.auth.routes import password_reset

    monkeypatch.setitem(app.config, "PETTY_CASH_URL", PETTY_CASH_URL + "/")  # the trailing slash is trimmed
    user_id = _make_user(db_session, email="Pat.Reset@Example.com")

    resp = client.post("/reset_password", data={"email": "pat.reset@EXAMPLE.com"})

    assert resp.status_code == 302
    assert resp.location.endswith("/login")
    assert _take_flashes(client) == [("info", password_reset._RESET_REQUESTED_FLASH)]

    saved = _reload(db_session, user_id)
    token = saved.reset_token
    assert token
    lifetime = saved.reset_token_expiry - datetime.now(timezone.utc)
    assert timedelta(minutes=59) < lifetime <= timedelta(hours=1)

    assert len(mail.messages) == 1
    msg = mail.messages[0]
    assert msg.subject == "Reset your Minty password"
    assert msg.recipients == ["Pat.Reset@Example.com"]
    assert f'href="{PETTY_CASH_URL}/reset_password/{token}"' in msg.html
    assert f'src="{PETTY_CASH_URL}/static/img/minty-mark.png' in msg.html
    assert "expires in 1 hour" in msg.html
    # The old mail put "<br> <a href=...>" in the plain-text body, shown raw.
    assert "<" not in (msg.body or "")


def test_reset_link_falls_back_to_the_request_host_without_petty_cash_url(
    app, client, db_session, mail, monkeypatch
):
    """No PETTY_CASH_URL: the link and the logo use the request host - and the logo is
    /static/img/..., not the /static/static/img/... invite.py's fallback builds."""
    monkeypatch.setitem(app.config, "PETTY_CASH_URL", None)
    user_id = _make_user(db_session, email="no.public.url@example.com")

    client.post("/reset_password", data={"email": "no.public.url@example.com"})

    token = _reload(db_session, user_id).reset_token
    [msg] = mail.messages
    assert f'href="http://localhost/reset_password/{token}"' in msg.html
    assert 'src="http://localhost/static/img/minty-mark.png' in msg.html


def test_unknown_address_gets_the_same_answer_and_no_email(
    app, client, db_session, mail, monkeypatch
):
    """Whether an address has an account must not show: an unknown one gets the
    same redirect and the same flash - words and category - as a known one, and
    no email goes out."""
    monkeypatch.setitem(app.config, "PETTY_CASH_URL", PETTY_CASH_URL)
    _make_user(db_session, email="known@example.com")

    unknown = client.post("/reset_password", data={"email": "nobody@example.com"})
    unknown_flashes = _take_flashes(client)
    assert mail.messages == []

    known = client.post("/reset_password", data={"email": "known@example.com"})
    known_flashes = _take_flashes(client)
    assert len(mail.messages) == 1

    assert (unknown.status_code, unknown.location) == (known.status_code, known.location)
    assert unknown_flashes == known_flashes
    assert [category for category, _ in unknown_flashes] == ["info"]
    assert "nobody@example.com" not in unknown_flashes[0][1]


def test_failed_send_is_logged_and_flagged(app, client, db_session, monkeypatch, caplog):
    """A send that raises is logged with its traceback (it used to be print()ed)
    and answered with the failure flash rather than a 500."""
    import flask_mail

    def _refuse(self, message):
        raise OSError("SMTP is down")

    monkeypatch.setattr(flask_mail._MailMixin, "send", _refuse)
    _make_user(db_session, email="smtp.down@example.com")

    resp = client.post("/reset_password", data={"email": "smtp.down@example.com"})

    assert resp.status_code == 302
    assert resp.location.endswith("/login")
    assert [category for category, _ in _take_flashes(client)] == ["danger"]
    assert "Could not send a password reset link" in caplog.text


def test_expired_link_sends_the_user_back_to_ask_again(app, client, db_session):
    token = str(uuid.uuid4())
    _make_user(
        db_session,
        email="expired.link@example.com",
        reset_token=token,
        reset_token_expiry=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    resp = client.get(f"/reset_password/{token}")

    assert resp.status_code == 302
    assert resp.location.endswith("/reset_password")
    assert _take_flashes(client) == [
        ("warning", "This reset link has expired. Want me to send a fresh one?")
    ]


def test_valid_link_sets_the_new_password_and_spends_the_token(app, client, db_session):
    token = str(uuid.uuid4())
    user_id = _make_user(
        db_session,
        email="new.password@example.com",
        reset_token=token,
        reset_token_expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    assert client.get(f"/reset_password/{token}").status_code == 200  # the form

    resp = client.post(
        f"/reset_password/{token}",
        data={"password": "brand-new-pw", "confirm_password": "brand-new-pw"},
    )

    assert resp.status_code == 302
    assert resp.location.endswith("/login")
    assert [category for category, _ in _take_flashes(client)] == ["success"]
    saved = _reload(db_session, user_id)
    assert check_password_hash(saved.password, "brand-new-pw")
    assert saved.reset_token is None
    assert saved.reset_token_expiry is None

    # A spent link is dead.
    again = client.get(f"/reset_password/{token}")
    assert again.status_code == 302
    assert again.location.endswith("/reset_password")
