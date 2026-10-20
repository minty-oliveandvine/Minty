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


def test_a_payment_number_lands_on_that_request(shop, client, monkeypatch):
    # the payments app sends the Payment No. (free text) since 2026-10-20, decoded
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)
    base = f"{F.co(client, entity.id)}/payment-request"
    origin = urlsplit(bearer_api.frontend_origin())

    parts, query = _landing(client.get(base, query_string={"request": "MBIOLI-101530201026"}))
    assert (parts.scheme, parts.netloc) == (origin.scheme, origin.netloc)
    assert query["next"] == [f"{base}/MBIOLI-101530201026"]

    # a '/' stays inside the one segment
    parts, query = _landing(client.get(base, query_string={"request": "PR/0001"}))
    assert (parts.scheme, parts.netloc) == (origin.scheme, origin.netloc)
    assert query["next"] == [f"{base}/PR%2F0001"]


@pytest.mark.parametrize(
    "raw",
    ["..", ".", "a/../b", "PR/", "/PR", "PR\\0001", "PR\n0001", "PR\x7f", "x" * 256, "   "],
)
def test_a_payment_number_that_is_not_a_plain_reference_lands_on_the_list(shop, client, monkeypatch, raw):
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)
    base = f"{F.co(client, entity.id)}/payment-request"
    origin = urlsplit(bearer_api.frontend_origin())

    parts, query = _landing(client.get(base, query_string={"request": raw}))

    assert (parts.scheme, parts.netloc, parts.path) == (origin.scheme, origin.netloc, "/landing")
    assert query["next"] == [base]


def test_a_255_character_payment_number_is_kept(shop, client, monkeypatch):
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)
    base = f"{F.co(client, entity.id)}/payment-request"

    _, query = _landing(client.get(base, query_string={"request": "x" * 255}))

    assert query["next"] == [f"{base}/{'x' * 255}"]


def _hand_off_claims(app, resp):
    import jwt as pyjwt

    _, query = _landing(resp)
    return pyjwt.decode(query["token"][0], app.config["SECRET_KEY"], algorithms=["HS256"])


def test_a_superadmin_outside_the_company_gets_a_view_only_token(app, db, shop, client, monkeypatch):
    from models.db import User

    _, entity, _ = shop
    with app.app_context():
        root = F.make_user(db, "root@test.com", system_role=User.SYSTEM_ROLE_SUPERUSER)
    _bill_module_on(monkeypatch)
    F.login(client, root)

    claims = _hand_off_claims(app, client.get(f"{F.co(client, entity.id)}/payment-request"))

    assert claims["system_role"] == "superadmin"
    assert claims["role"] == "super_admin"
    assert claims["is_view_only"] is True


def test_the_company_owner_gets_a_token_that_is_not_view_only(app, shop, client, monkeypatch):
    owner, entity, _ = shop
    _bill_module_on(monkeypatch)
    F.login(client, owner)

    claims = _hand_off_claims(app, client.get(f"{F.co(client, entity.id)}/payment-request"))

    assert claims["is_view_only"] is False
