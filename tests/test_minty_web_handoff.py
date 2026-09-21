"""Flask's two doors into minty-web (Part 2 step 4a).

``GET /entity/settings/module/<id>``, live, is minty-web's page now: Flask mints the company's
module token and sends the browser to minty-web's ``/landing`` with it (``MINTY_WEB_MODULE_PAGE``,
on by default; the suite runs with it off so the Jinja-page tests still describe what they
exercise). ``GET /handoff/minty-web?next=&entity_id=`` is the re-entry minty-web uses when its
token lapses (``lib/handoff.ts``): login-gated, a scoped or unscoped token, never an open
redirect. Dark, neither door exists.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import char_factories as F
import jwt
import pytest

from blueprints.shared import bearer_api

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        stranger = F.make_user(db, "stranger@test.com")
        db.session.commit()
    return owner, entity, stranger


@pytest.fixture
def live_page(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_MODULE_PAGE", "1")
    monkeypatch.setenv("MINTY_WEB_URL", "http://hub.minty.test/")


def _landing(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    return parts, parse_qs(parts.query)


def _claims(app, token: str) -> dict:
    return jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])


def test_live_the_module_page_is_minty_webs(shop, client, app, live_page):
    owner, entity, _ = shop
    F.login(client, owner)

    parts, query = _landing(client.get(f"/entity/settings/module/{entity.id}?from=bills"))

    assert (parts.scheme, parts.netloc, parts.path) == ("http", "hub.minty.test", "/landing")
    assert query["next"] == [f"/subscription/entities/{entity.id}/modules?from=bills"]
    assert query["entity_id"] == [entity.id]
    assert query["entity_name"] == [entity.name]
    claims = _claims(app, query["token"][0])
    assert claims["user_id"] == owner.id
    assert claims["entity_id"] == entity.id
    assert claims["role"] == "admin"
    assert claims["petty_cash_enabled"] is True

    # without ?from=bills the way back is Minty's, and next carries no query
    _, query = _landing(client.get(f"/entity/settings/module/{entity.id}"))
    assert query["next"] == [f"/subscription/entities/{entity.id}/modules"]


def test_the_jinja_page_stays_when_the_switch_is_off(shop, client, monkeypatch):
    owner, entity, _ = shop
    monkeypatch.setenv("MINTY_WEB_MODULE_PAGE", "0")
    F.login(client, owner)
    resp = client.get(f"/entity/settings/module/{entity.id}")
    assert resp.status_code == 200
    assert b"Module" in resp.data


def test_dark_the_plain_page_stays_whatever_the_switch(shop, client, monkeypatch, live_page):
    owner, entity, _ = shop
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "0")
    F.login(client, owner)
    assert client.get(f"/entity/settings/module/{entity.id}").status_code == 200


def test_the_handoff_mints_a_scoped_token_for_a_company(shop, client, app, live_page):
    owner, entity, _ = shop
    F.login(client, owner)

    parts, query = _landing(
        client.get(f"/handoff/minty-web?next=/subscription/entities/{entity.id}/modules&entity_id={entity.id}")
    )

    assert parts.netloc == "hub.minty.test" and parts.path == "/landing"
    assert query["next"] == [f"/subscription/entities/{entity.id}/modules"]
    assert query["entity_id"] == [entity.id]
    assert _claims(app, query["token"][0])["entity_id"] == entity.id


def test_the_handoff_mints_an_unscoped_token_for_the_portal(shop, client, app, live_page):
    owner, _, _ = shop
    F.login(client, owner)

    _, query = _landing(client.get("/handoff/minty-web?next=/subscription/billing"))

    assert query["next"] == ["/subscription/billing"]
    assert query.get("entity_id", [""]) == [""]  # parse_qs drops the empty value
    claims = _claims(app, query["token"][0])
    assert claims["user_id"] == owner.id and claims["entity_id"] == ""


def test_the_handoff_is_not_an_open_redirect_and_needs_a_login(shop, client, live_page):
    owner, entity, stranger = shop

    anonymous = client.get("/handoff/minty-web?next=/subscription")
    assert anonymous.status_code in (302, 401)
    assert "hub.minty.test" not in anonymous.headers.get("Location", "")

    F.login(client, owner)
    _, query = _landing(client.get("/handoff/minty-web?next=//evil.example/phish"))
    assert query["next"] == ["/subscription"]

    # a company the person is not a member of: no token for it
    F.login(client, stranger)
    refused = client.get(f"/handoff/minty-web?next=/subscription&entity_id={entity.id}")
    assert refused.status_code == 302
    assert "hub.minty.test" not in refused.headers.get("Location", "")


def test_the_default_origin_is_the_local_hub(monkeypatch):
    monkeypatch.delenv("MINTY_WEB_URL", raising=False)
    assert bearer_api.minty_web_origin() == "http://localhost:3002"
