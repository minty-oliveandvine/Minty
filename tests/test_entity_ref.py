"""Company addresses: ``/entity/<shortid>/<name>/...`` (2026-10-05, blueprints/shared/entity_ref.py).

Pins: the name as an address segment; the short id deciding the company and the name only for
reading (a rename never breaks a link - the old name redirects); an unknown company answered by
the usual guards, not a 404 that would tell a stranger which short ids exist; every old address
a 308 to the new one; the wizard under the company, and a report refused under another
company's address.
"""

from __future__ import annotations

from datetime import date

import char_factories as F
import pytest

from blueprints.shared.entity_ref import slugify_name

pytestmark = pytest.mark.char


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Ang - M11 Harbour & Vine Limited", "ang-m11-harbour-and-vine-limited"),
        ("7 Eleven Store", "7-eleven-store"),
        ("茶餐廳 Limited", "茶餐廳-limited"),
        ("  ---  ", "company"),
        ("", "company"),
        (None, "company"),
        ("A" * 100, "a" * 60),
        ("Dine at Venus (2)", "dine-at-venus-2"),
    ],
)
def test_a_name_becomes_an_address_segment(name, slug):
    assert slugify_name(name) == slug


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, name="Harbour & Vine", currency=currency, country=country)
        other = F.make_entity(db, owner, name="Other Shop", currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity)
    return owner, entity, other


def test_the_address_is_the_short_id_and_the_name(shop, client):
    owner, entity, _ = shop
    assert F.co(client, entity.id) == f"/entity/{entity.id[:8]}/harbour-and-vine"


def test_a_full_uuid_or_an_old_name_redirects_to_the_current_address(shop, client):
    owner, entity, _ = shop
    F.login(client, owner)
    canonical = F.co(client, entity.id)

    for old in (f"/entity/{entity.id}/petty-cash/reports", f"/entity/{entity.id[:8]}/an-old-name/petty-cash/reports"):
        resp = client.get(old + "?page=2")
        assert resp.status_code == 308, old
        assert resp.headers["Location"] == f"{canonical}/petty-cash/reports?page=2"

    assert client.get(f"{canonical}/petty-cash/reports").status_code == 200


def test_an_unknown_company_is_left_to_the_usual_guards(shop, client):
    # signed out: the login redirect, exactly as for a company that exists
    unknown = client.get("/entity/deadbeef/no-such-company/petty-cash/reports")
    real = client.get(f"{F.co(client, shop[1].id)}/petty-cash/reports")
    assert unknown.status_code == real.status_code == 302

    owner, _, _ = shop
    F.login(client, owner)
    assert client.get("/entity/deadbeef/no-such-company/petty-cash/reports").status_code in (302, 403)


@pytest.mark.parametrize(
    "old, tail",
    [
        ("/entity/settings/users/{id}", "/settings/users"),
        ("/entity/{id}/settings/xero", "/settings/integration"),
        ("/entity/settings/entity/{id}", "/settings/petty-cash"),
        ("/entity/settings/module/{id}", "/settings/modules"),
        ("/entity/settings/payments/{id}", "/settings/payment-request"),
        ("/entity/{id}/bills", "/payment-request"),
        ("/invitation/xero-not-connected/{id}", "/xero-not-connected"),
        ("/entity/{id}/report/opening", "/petty-cash/reports/new/opening"),
        ("/entity/{id}/ending", "/petty-cash/reports/summary"),
    ],
)
def test_every_old_address_is_a_308_to_the_new_one(shop, client, old, tail):
    owner, entity, _ = shop
    F.login(client, owner)
    resp = client.get(old.format(id=entity.id) + "?x=1")
    # one hop, straight to the readable address, query kept
    assert resp.status_code == 308
    assert resp.headers["Location"] == f"{F.co(client, entity.id)}{tail}?x=1"


def test_petty_cash_pages_moved_under_petty_cash(shop, client):
    # the dashboard and every report page sit under the module's name (2026-10-05), as the
    # payments app's pages sit under /payment-request; the old addresses move in one hop
    owner, entity, _ = shop
    F.login(client, owner)
    co = F.co(client, entity.id)

    resp = client.get(co + "?x=1")
    assert resp.status_code == 308 and resp.headers["Location"] == f"{co}/petty-cash?x=1"
    for old, new in ((f"{co}/reports", f"{co}/petty-cash/reports"),
                     (f"{co}/reports/new/sale", f"{co}/petty-cash/reports/new/sale")):
        resp = client.get(old + "?x=1")
        assert resp.status_code == 308 and resp.headers["Location"] == new + "?x=1", old
    assert client.get(f"{co}/petty-cash").status_code in (200, 302)


def _open_report(client, entity):
    from models.db import Report

    client.post("/report/opening", data={
        "entity_id": entity.id, "transaction_date": F.iso(date(2026, 9, 1)),
        "opening_balance": "1000.00", "cash_addition": "0", "action_type": "save_next",
    })
    with client.application.app_context():
        return str(Report.query.filter(Report.company == entity.id).first().id)


def test_an_old_wizard_address_moves_under_the_company(shop, client):
    owner, entity, _ = shop
    F.login(client, owner)
    report_id = _open_report(client, entity)

    resp = client.get(f"/report/{report_id}/cash_count?entity_id={entity.id}&edit=true")
    assert resp.status_code == 308
    assert resp.headers["Location"] == f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/cash-count?edit=true"

    resp = client.get(f"/report/sale?entity_id={entity.id}&transaction_date=2026-09-01")
    assert resp.headers["Location"] == f"{F.co(client, entity.id)}/petty-cash/reports/new/sale?transaction_date=2026-09-01"


def test_a_report_under_another_companys_address_is_refused(shop, client):
    owner, entity, other = shop
    F.login(client, owner)
    report_id = _open_report(client, entity)

    assert client.get(f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/sale").status_code == 200
    assert client.get(f"{F.co(client, other.id)}/petty-cash/reports/{report_id}/sale").status_code == 404


def test_signed_out_old_wizard_addresses_say_nothing_about_the_company(shop, client):
    _, entity, _ = shop
    resp = client.get(f"/report/{entity.id}/sale")
    assert resp.status_code == 302
    assert "/entity/" not in resp.headers["Location"]
