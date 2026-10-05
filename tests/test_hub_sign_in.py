"""Sign-in is minty-web's ``/login`` since phase 2 (2026-10-05); Flask stays the identity behind it.

Flask's side: every way in to signing in (the front door ``/``, Flask-Login's redirect, ``/register``,
an invitation link) is a redirect to the hub's page built by ``hub_login_url`` - carrying ``next``
when it is a path on this site, and the messages flashed on the way, signed (``/auth/notices``
reads them back). An OTP sign-in then comes back through ``/auth/email/handoff`` to that ``next``.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

import char_factories as F

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def hub(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


def _sign_in_page(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{HUB}/login"
    return parse_qs(parts.query)


def test_the_front_door_is_the_hubs_sign_in_page_with_next(client, db):
    assert _sign_in_page(client.get("/?next=/profile")) == {"next": ["/profile"]}


def test_a_next_that_leaves_the_site_is_dropped(client, db):
    for outside in ("//evil.example/x", "https://evil.example", "/\\evil.example", "/\t/evil.example"):
        assert "next" not in _sign_in_page(client.get("/", query_string={"next": outside})), outside


def test_signed_in_the_front_door_is_the_entity_list(app, client, db):
    with app.app_context():
        person = F.make_user(db, "front.door@test.com")
    F.login(client, person)

    resp = client.get("/")
    assert resp.status_code == 302
    assert urlsplit(resp.headers["Location"]).path == "/entity"


def test_a_protected_page_sends_its_message_and_its_address_along(client, db):
    """Flask-Login's redirect lands on ``/``, which hands both to the hub: the page asked for as
    ``next`` and "Please log in…" signed into ``flash`` - as information, not a success."""
    first = client.get("/profile")
    assert first.status_code == 302
    query = _sign_in_page(client.get(first.headers["Location"]))

    assert query["next"] == ["/profile"]
    notices = client.get("/auth/notices", query_string={"flash": query["flash"][0]}).get_json()
    assert notices == {
        "notices": [{"category": "info", "message": "Please log in to access this page."}]
    }


def test_notices_read_nothing_from_a_forged_or_missing_value(client, db):
    assert client.get("/auth/notices?flash=forged.value.here").get_json() == {"notices": []}
    assert client.get("/auth/notices").get_json() == {"notices": []}


def test_register_forwards_to_the_hubs_sign_up(client, db):
    assert _sign_in_page(client.get("/register")) == {"mode": ["signup"]}
    assert _sign_in_page(client.post("/register", data={"email": "x@test.com"})) == {"mode": ["signup"]}


def test_the_login_pages_own_endpoints_are_gone(client, db):
    """``/auth/email/check`` served only Flask's login page; log-in mode's request-code refuses an
    unknown address itself. ``/validate_register`` served only the register page."""
    assert client.post("/auth/email/check", json={"email": "a@test.com"}).status_code == 404
    assert client.post("/validate_register", json={"email": "a@test.com"}).status_code == 404


def _sign_in_by_code(client, monkeypatch, email, **extra):
    import blueprints.auth.services.email_auth as email_auth

    sent = {}
    real_gen = email_auth.generate_otp

    def capture():
        sent["code"] = real_gen()
        return sent["code"]

    monkeypatch.setattr(email_auth, "generate_otp", capture)
    assert client.post("/auth/email/request-code", json={"email": email, "mode": "login"}).status_code == 200
    verify = client.post("/auth/email/verify-code", json={"email": email, "code": sent["code"], **extra})
    assert verify.status_code == 200, verify.get_json()
    handoff = urlsplit(verify.get_json()["redirect_url"])
    return client.get(f"{handoff.path}?{handoff.query}")


def test_a_code_sign_in_returns_to_where_it_was_headed(app, client, db, monkeypatch):
    with app.app_context():
        F.make_user(db, "headed@test.com")

    landed = _sign_in_by_code(client, monkeypatch, "headed@test.com", next="/profile")

    assert landed.status_code == 302
    assert landed.headers["Location"] == "/profile"


def test_a_code_sign_in_never_follows_an_outside_next(app, client, db, monkeypatch):
    with app.app_context():
        F.make_user(db, "careful@test.com")

    landed = _sign_in_by_code(client, monkeypatch, "careful@test.com", next="//evil.example/x")

    assert landed.status_code == 302
    assert urlsplit(landed.headers["Location"]).path == "/index"


def test_an_invitation_link_opens_the_hubs_sign_in_for_that_address(app, client, db):
    from blueprints.invitation.services.invite import create_invitation

    with app.app_context():
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner)
        invitation, error = create_invitation(entity.id, "invitee@test.com", "cashier", owner.id)
        assert error is None
        token = invitation.token

    query = _sign_in_page(client.get(f"/invitation/accept/{token}?fn=Ivy&ln=Lee"))

    assert query == {
        "invite": [token],
        "email": ["invitee@test.com"],
        "fn": ["Ivy"],
        "ln": ["Lee"],
    }


def test_a_used_invitation_says_so_on_the_sign_in_page(client, db):
    first = client.get("/invitation/accept/not-a-real-token")
    assert first.status_code == 302 and urlsplit(first.headers["Location"]).path == "/"

    query = _sign_in_page(client.get("/"))
    notices = client.get("/auth/notices", query_string={"flash": query["flash"][0]}).get_json()
    assert notices["notices"][0]["category"] == "warning"
    assert "doesn't work anymore" in notices["notices"][0]["message"]
