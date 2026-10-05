"""``GET /entity/<co>/modules`` - the router every way into a company goes through (the entity list's
rows, minty-web's ``/enter``). It decides, from the database, where the person lands:

* a company still onboarding resumes its wizard;
* someone who is not a member (and not a superuser) is refused, back to the list;
* one module switched on goes straight into it - Petty Cash's dashboard, or the payments app;
* both: minty-web's module choice (``/entities/<shortid>/<name>``, phase 2 - 2026-10-05; it was
  the payments app's ``/module-selection``), with a token scoped to the company.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

import char_factories as F

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"
PAYMENTS = "http://payments.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def origins(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")
    monkeypatch.setenv("PAYMENT_REQUEST_WEB_URL", PAYMENTS)


@pytest.fixture
def owner(app, db):
    with app.app_context():
        return F.make_user(db, "owner@test.com")


def _company(app, db, owner, **kwargs):
    with app.app_context():
        return F.make_entity(db, owner, **kwargs)


def _open(client, entity_id):
    resp = client.get(f"{F.co(client, entity_id)}/modules")
    assert resp.status_code == 302, resp.data[:300]
    return urlsplit(resp.headers["Location"])


def test_both_modules_open_minty_webs_module_choice_with_a_company_token(app, client, db, owner):
    company = _company(app, db, owner, name="Olive & Vine", modules=("PETTY_CASH", "PAYMENT_REQUEST"))
    F.login(client, owner)

    where = _open(client, company.id)

    assert (f"{where.scheme}://{where.netloc}", where.path) == (HUB, "/landing")
    query = parse_qs(where.query)
    assert query["next"] == [f"/entities/{company.id[:8]}/olive-and-vine"]
    claims = jwt.decode(query["token"][0], app.config["SECRET_KEY"], algorithms=["HS256"])
    assert claims["entity_id"] == company.id and claims["user_id"] == owner.id
    assert claims["petty_cash_enabled"] is True and claims["billing_enabled"] is True


def test_petty_cash_alone_goes_straight_to_its_dashboard(app, client, db, owner):
    company = _company(app, db, owner, modules=("PETTY_CASH",))
    F.login(client, owner)

    where = _open(client, company.id)

    assert where.netloc == "" and where.path.endswith("/petty-cash")


def test_payment_request_alone_goes_straight_to_the_payments_app(app, client, db, owner):
    company = _company(app, db, owner, modules=("PAYMENT_REQUEST",))
    F.login(client, owner)

    where = _open(client, company.id)

    assert f"{where.scheme}://{where.netloc}" == PAYMENTS
    assert "token" in parse_qs(where.query)


def test_a_company_still_onboarding_resumes_its_wizard(app, client, db, owner, monkeypatch):
    monkeypatch.setenv("ONBOARDING_WEB_URL", "http://onboarding.minty.test")
    company = _company(app, db, owner, status="onboarding")
    F.login(client, owner)

    where = _open(client, company.id)

    assert where.netloc == "onboarding.minty.test"
    assert parse_qs(where.query)["entity_id"] == [company.id]


def test_someone_outside_the_company_is_sent_back_to_the_list(app, client, db, owner):
    company = _company(app, db, owner, modules=("PETTY_CASH", "PAYMENT_REQUEST"))
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")
    F.login(client, stranger)

    where = _open(client, company.id)

    assert where.netloc == "" and where.path == "/entity"
