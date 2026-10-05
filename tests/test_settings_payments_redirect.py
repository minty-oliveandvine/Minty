"""``GET /entity/<co>/settings/payment-request`` sends a member on to the payments app's settings
page with a freshly minted module token - the Payment Settings tab as a URL a page outside
Flask can link to (the module settings page in minty-web, Part 2 step 4). Flask stays the only
minter; this route is how another app borrows that.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import char_factories as F
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


def _landing(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    return parts, parse_qs(parts.query)


def test_a_member_is_sent_to_the_payments_app_settings_with_a_token(shop, client):
    owner, entity, _ = shop
    F.login(client, owner)

    parts, query = _landing(client.get(f"{F.co(client, entity.id)}/settings/payment-request"))

    origin = urlsplit(bearer_api.frontend_origin())
    assert (parts.scheme, parts.netloc, parts.path) == (origin.scheme, origin.netloc, "/landing")
    # the company's own address in the payments app since 2026-10-05
    assert query["next"] == [f"{F.co(client, entity.id)}/settings/payment-request"]
    assert query["entity_id"] == [entity.id]
    assert query["entity_name"] == [entity.name]
    assert query["token"][0].count(".") == 2  # a JWT, minted here and nowhere else
    assert "from" not in query


def test_an_old_from_bills_is_not_passed_on(shop, client):
    # the payments app never read it; the flag went 2026-10-05
    owner, entity, _ = shop
    F.login(client, owner)

    _, query = _landing(client.get(f"{F.co(client, entity.id)}/settings/payment-request?from=bills"))

    assert "from" not in query


def test_anonymous_and_non_members_do_not_get_a_token(shop, client):
    owner, entity, stranger = shop

    anonymous = client.get(f"{F.co(client, entity.id)}/settings/payment-request")
    assert anonymous.status_code in (302, 401)
    assert "/landing" not in anonymous.headers.get("Location", "")

    F.login(client, stranger)
    refused = client.get(f"{F.co(client, entity.id)}/settings/payment-request")
    assert refused.status_code in (302, 403)
    assert "/landing" not in refused.headers.get("Location", "")


def _bill_module_on(monkeypatch):
    from blueprints.entity.routes import modules

    monkeypatch.setattr(modules, "_is_module_enabled", lambda entity_id, code: True)


def test_the_payment_request_hand_off_lands_on_the_company_address(shop, client, monkeypatch):
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)

    parts, query = _landing(client.get(f"{F.co(client, entity.id)}/payment-request"))

    assert parts.path == "/landing"
    assert query["next"] == [f"{F.co(client, entity.id)}/payment-request"]
    assert query["entity_id"] == [entity.id]


def test_a_payment_request_id_lands_on_that_request(shop, client, monkeypatch):
    # the payments app sends a page of another company here, its cookie holding one company
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)
    request_id = F.new_id()

    _, query = _landing(client.get(f"{F.co(client, entity.id)}/payment-request?request={request_id}"))
    assert query["next"] == [f"{F.co(client, entity.id)}/payment-request/{request_id}"]

    _, query = _landing(client.get(f"{F.co(client, entity.id)}/payment-request?request=../settings"))
    assert query["next"] == [f"{F.co(client, entity.id)}/payment-request"]
