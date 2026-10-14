"""``GET /handoff/petty-cash-web?next=&entity_id=``: the way into minty-petty-cash-web, and back in
when its 30-minute token lapses (the app's ``lib/handoff.ts``, as minty-web's).

Flask is the only thing that mints: the app has no login and no refresh of its own, so a
lapsed token is answered by coming back here - login-gated, so a person whose Flask session
also ran out signs in first. Always for ONE company (Petty Cash has no unscoped page), and
only one the person belongs to with Petty Cash switched on; ``next`` is a path only, never an
open redirect.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

WEB = "https://petty-cash.minty.test"
HUB = "https://my.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def hosts(monkeypatch):
    monkeypatch.setenv("PETTY_CASH_WEB_URL", WEB + "/")
    monkeypatch.setenv("MINTY_WEB_URL", HUB)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, name="Vine Café Central", currency=currency, country=country)
        stranger = F.make_user(db, "stranger@test.com")
    return {"owner": owner, "entity": entity, "stranger": stranger}


def _landing(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    return parts, parse_qs(parts.query)


def _claims(app, token):
    return jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])


def _ref(client, entity_id) -> str:
    return F.co(client, entity_id)[len("/entity/"):]


def test_a_member_lands_on_the_companys_petty_cash_with_a_module_token(app, client, shop):
    F.login(client, shop["owner"])
    entity = shop["entity"]

    parts, query = _landing(client.get("/handoff/petty-cash-web", query_string={"entity_id": entity.id}))

    assert (parts.scheme, parts.netloc, parts.path) == ("https", "petty-cash.minty.test", "/landing")
    assert query["next"] == [f"/entity/{_ref(client, entity.id)}/petty-cash"]
    assert query["entity_id"] == [entity.id]
    assert query["entity_name"] == ["Vine Café Central"]
    claims = _claims(app, query["token"][0])
    assert claims["module"] == "billing"  # the claim the Petty Cash API's door checks
    assert claims["user_id"] == shop["owner"].id
    assert claims["entity_id"] == entity.id
    assert claims["role"] == "admin"
    assert claims["petty_cash_enabled"] is True
    assert claims["exp"] - claims["iat"] == 30 * 60


def test_the_apps_own_address_form_names_the_company_too(app, client, shop):
    """With no cookie left (it lapses with the token) the app knows the company only from its
    address, ``/entity/<shortid>/<name>/...`` - so the hand-off takes that form as well."""
    F.login(client, shop["owner"])
    ref = _ref(client, shop["entity"].id)

    _, query = _landing(client.get("/handoff/petty-cash-web", query_string={"entity_id": ref}))

    assert query["entity_id"] == [shop["entity"].id]
    assert _claims(app, query["token"][0])["entity_id"] == shop["entity"].id


def test_next_is_passed_on_when_it_is_a_path(client, shop):
    F.login(client, shop["owner"])
    nxt = f"/entity/{_ref(client, shop['entity'].id)}/petty-cash/closing?stage=sales"
    _, query = _landing(
        client.get("/handoff/petty-cash-web", query_string={"entity_id": shop["entity"].id, "next": nxt})
    )
    assert query["next"] == [nxt]


@pytest.mark.parametrize("bad", ["//evil.example/phish", "https://evil.example", "javascript:alert(1)"])
def test_next_is_never_an_open_redirect(client, shop, bad):
    F.login(client, shop["owner"])
    _, query = _landing(
        client.get("/handoff/petty-cash-web", query_string={"entity_id": shop["entity"].id, "next": bad})
    )
    assert query["next"] == [f"/entity/{_ref(client, shop['entity'].id)}/petty-cash"]


def test_it_needs_a_flask_sign_in(client, shop):
    resp = client.get("/handoff/petty-cash-web", query_string={"entity_id": shop["entity"].id})
    assert resp.status_code in (302, 401)
    assert "petty-cash.minty.test" not in resp.headers.get("Location", "")


def test_no_company_goes_to_the_hubs_company_list(client, shop):
    F.login(client, shop["owner"])
    parts, query = _landing(client.get("/handoff/petty-cash-web"))
    assert parts.netloc == "my.minty.test"
    assert query["next"] == ["/entities"]


@pytest.mark.parametrize("which", ["stranger", "no such company"])
def test_a_company_you_cannot_see_gets_no_token(client, shop, which):
    F.login(client, shop["stranger"] if which == "stranger" else shop["owner"])
    entity_id = shop["entity"].id if which == "stranger" else F.new_id()

    resp = client.get("/handoff/petty-cash-web", query_string={"entity_id": entity_id})

    assert resp.status_code == 302
    assert "petty-cash.minty.test" not in resp.headers["Location"]
    assert "token=" not in resp.headers["Location"]


def test_petty_cash_switched_off_gets_no_token(app, client, db, shop):
    with app.app_context():
        payments_only = F.make_entity(db, shop["owner"], name="Payments Only", modules=("PAYMENT_REQUEST",))
    F.login(client, shop["owner"])

    resp = client.get("/handoff/petty-cash-web", query_string={"entity_id": payments_only.id})

    assert resp.status_code == 302
    assert "petty-cash.minty.test" not in resp.headers["Location"]


def test_a_company_still_in_onboarding_goes_back_to_the_wizard(app, client, db, shop, monkeypatch):
    from models.db import Entity

    monkeypatch.setenv("ONBOARDING_WEB_URL", "https://onboarding.minty.test")
    with app.app_context():
        db.session.get(Entity, shop["entity"].id).status = "onboarding"
        db.session.commit()
    F.login(client, shop["owner"])

    resp = client.get("/handoff/petty-cash-web", query_string={"entity_id": shop["entity"].id})

    assert resp.status_code == 302
    assert urlsplit(resp.headers["Location"]).netloc == "onboarding.minty.test"


def test_inside_a_preview_set_it_lands_on_the_sets_petty_cash_host(client, shop, monkeypatch):
    monkeypatch.setenv(
        "PREVIEW_ORIGIN_REGEX",
        r"^https://pr-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-(?:my|payment-request|onboarding|petty-cash)\.dailyminty\.com$",
    )
    F.login(client, shop["owner"])
    with client.session_transaction() as sess:
        sess["preview_set"] = {"slug": "development", "at": int(time.time())}

    parts, _ = _landing(client.get("/handoff/petty-cash-web", query_string={"entity_id": shop["entity"].id}))

    assert parts.netloc == "pr-development-petty-cash.dailyminty.com"


def test_the_default_origin_is_the_local_app(monkeypatch):
    from blueprints.shared import bearer_api

    monkeypatch.delenv("PETTY_CASH_WEB_URL", raising=False)
    assert bearer_api.petty_cash_web_origin() == "http://localhost:3010"
