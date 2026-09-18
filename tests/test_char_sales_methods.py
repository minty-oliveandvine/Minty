"""Characterisation: sales methods (payment methods) per entity.

The redesign reshapes this area most: ``entity_sale_setting`` (per-entity rows carrying
``type``/``sale_name``/``value_name``/``enabled``) becomes a thin link to a ``sale_info``
catalogue (``entity_id``, ``sale_id``, ``is_active``, ``display_order``), and
``sale_info.type`` becomes the ``sale_type`` enum ``electronic`` / ``delivery`` / ``other``
(Phase A vocabulary; the JSON ``type`` carries the enum word since C3).

What is pinned: the JSON the settings page and the onboarding wizard receive, the order,
the enable/disable semantics, and that a method used by an old report survives being
switched off. See docs/modernisation/modernisation_plan.md, Part 1 B3 group 3.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import jwt
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
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db, denominations=())  # no cash count in these tests (cash_info is C4)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def methods_api(client, entity) -> list[dict]:
    """The settings page's list: ``{"payment_methods": [{id, name, type, enabled, display_order, ...}]}``."""
    resp = client.get(f"/api/entities/{entity.id}/payment-methods")
    assert resp.status_code == 200, resp.data[:300]
    return resp.get_json()["payment_methods"]


def names_by_type(rows, mtype):
    return [m["name"] for m in sorted(rows, key=lambda m: m["display_order"]) if m["type"] == mtype and m["enabled"]]


def bearer(app, user):
    """The short-lived onboarding JWT Flask mints for the wizard (create.py::_mint_onboarding_token)."""
    payload = {"user_id": str(user.id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=5), "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


# ---------------------------------------------------------------------------------------------


def test_new_entity_has_no_methods_until_they_are_set(shop, client):
    owner, entity = shop
    F.login(client, owner)
    payload = methods_api(client, entity)
    assert names_by_type(payload, "electronic") == []
    assert names_by_type(payload, "delivery") == []


def test_onboarding_sales_setup_round_trips_through_the_bearer_api(shop, client, app):
    """Step 4 of the wizard writes the methods and reads them back grouped by type, in order."""
    owner, entity = shop
    headers = bearer(app, owner)

    resp = client.post("/api/onboarding/sales-methods", headers=headers,
                       json={"entity_id": entity.id, "electronic": ["Visa", "Alipay", "WeChat Pay"],
                             "delivery": ["Foodpanda", "Deliveroo"]})
    assert resp.status_code == 200, resp.data[:300]

    resp = client.get(f"/api/onboarding/sales-methods?entity_id={entity.id}", headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["electronic"] == ["Visa", "Alipay", "WeChat Pay"]
    assert body["delivery"] == ["Foodpanda", "Deliveroo"]


def test_onboarding_sales_api_rejects_a_missing_or_foreign_token(shop, client, app, db):
    owner, entity = shop
    assert client.get(f"/api/onboarding/sales-methods?entity_id={entity.id}").status_code == 401
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")
    resp = client.get(f"/api/onboarding/sales-methods?entity_id={entity.id}", headers=bearer(app, stranger))
    assert resp.status_code == 403


def test_settings_api_lists_what_onboarding_wrote_typed_and_ordered(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": ["Foodpanda"]})
    F.login(client, owner)

    payload = methods_api(client, entity)

    assert names_by_type(payload, "electronic") == ["Visa", "Alipay"]
    assert names_by_type(payload, "delivery") == ["Foodpanda"]
    types = {m["type"] for m in payload}
    assert types <= {"electronic", "delivery", "other"}, types  # the sale_type enum's words


def test_replacing_the_list_hides_dropped_methods(shop, client, app):
    """A method taken off the list disappears from the settings list (it is switched off, not
    deleted - the next test shows re-adding it brings back the same row)."""
    owner, entity = shop
    headers = bearer(app, owner)
    client.post("/api/onboarding/sales-methods", headers=headers,
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": []})

    client.post("/api/onboarding/sales-methods", headers=headers,
                json={"entity_id": entity.id, "electronic": ["Visa"], "delivery": []})

    F.login(client, owner)
    by_name = {m["name"]: m for m in methods_api(client, entity)}
    assert by_name["Visa"]["enabled"] is True
    assert "Alipay" not in by_name, by_name


def test_re_adding_a_disabled_method_re_enables_the_same_row(shop, client, app):
    owner, entity = shop
    headers = bearer(app, owner)
    client.post("/api/onboarding/sales-methods", headers=headers,
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": []})
    F.login(client, owner)
    before = {m["name"]: m["id"] for m in methods_api(client, entity)}
    client.post("/api/onboarding/sales-methods", headers=headers,
                json={"entity_id": entity.id, "electronic": ["Visa"], "delivery": []})

    client.post("/api/onboarding/sales-methods", headers=headers,
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": []})

    after = {m["name"]: (m["id"], m["enabled"]) for m in methods_api(client, entity)}
    assert after["Alipay"] == (before["Alipay"], True), "re-adding should re-enable, not duplicate"
    assert len(methods_api(client, entity)) == 2


def test_names_are_deduplicated_case_insensitively(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "visa", " VISA "], "delivery": []})
    F.login(client, owner)
    assert names_by_type(methods_api(client, entity), "electronic") == ["Visa"]


def test_add_method_through_the_settings_api(shop, client):
    owner, entity = shop
    F.login(client, owner)

    resp = client.post(f"/api/entities/{entity.id}/payment-methods",
                       json={"name": "Octopus", "type": "Electronic", "value_name": "octopus_sales"})

    assert resp.status_code in (200, 201), resp.data[:300]
    assert "Octopus" in names_by_type(methods_api(client, entity), "electronic")


def test_add_method_rejects_an_unknown_type(shop, client):
    owner, entity = shop
    F.login(client, owner)
    resp = client.post(f"/api/entities/{entity.id}/payment-methods",
                       json={"name": "Barter", "type": "Goats", "value_name": "barter_sales"})
    assert resp.status_code == 400
    assert "type" in resp.get_json()["error"].lower()


def test_reorder_changes_display_order(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay", "WeChat Pay"], "delivery": []})
    F.login(client, owner)
    ids = {m["name"]: m["id"] for m in methods_api(client, entity)}

    resp = client.put(f"/api/entities/{entity.id}/payment-methods/reorder",
                      json={"method_ids": [ids["WeChat Pay"], ids["Visa"], ids["Alipay"]]})

    assert resp.status_code == 200, resp.data[:300]
    assert names_by_type(methods_api(client, entity), "electronic") == ["WeChat Pay", "Visa", "Alipay"]


def test_delete_method_removes_it_from_the_list(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": []})
    F.login(client, owner)
    ids = {m["name"]: m["id"] for m in methods_api(client, entity)}

    resp = client.delete(f"/api/entities/{entity.id}/payment-methods/{ids['Alipay']}")

    assert resp.status_code == 200, resp.data[:300]
    assert "Alipay" not in {m["name"] for m in methods_api(client, entity)}


def test_a_member_without_settings_rights_cannot_change_methods(shop, client, app, db):
    owner, entity = shop
    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com")
        from models.db import UserEntity
        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
    F.login(client, cashier)
    resp = client.post(f"/api/entities/{entity.id}/payment-methods",
                       json={"name": "Octopus", "type": "Electronic", "value_name": "octopus_sales"})
    assert resp.status_code == 403


def test_methods_switched_on_are_the_ones_the_sales_form_offers(shop, client, app):
    """Settings and the report wizard agree: what is enabled here is what the sales page shows."""
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": ["Foodpanda"]})
    F.login(client, owner)
    from test_char_report_lifecycle import open_report

    open_report(client, entity, date(2026, 9, 1))
    page = client.get(f"/report/sale?entity_id={entity.id}&transaction_date=2026-09-01")

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for name in ("Visa", "Alipay", "Foodpanda"):
        assert name in html
    offered = F.enabled_sales_methods(app, entity.id)
    assert sorted(n for _, n in offered.values()) == ["Alipay", "Foodpanda", "Visa"]


# ---- C3: the catalogue is global, Cash is the 'other' bucket, the sales page follows ----------


def test_the_sales_page_offers_one_input_per_enabled_method_plus_cash(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": ["Foodpanda"]})
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa"], "delivery": ["Foodpanda"]})  # Alipay off
    F.login(client, owner)
    from test_char_report_lifecycle import open_report

    open_report(client, entity, date(2026, 9, 1))
    html = client.get(f"/report/sale?entity_id={entity.id}&transaction_date=2026-09-01").get_data(as_text=True)

    assert 'name="sales[shop_sales][visa]"' in html
    assert 'name="sales[delivery_sales][foodpanda]"' in html
    assert 'name="sales[shop_sales][alipay]"' not in html, "a method switched off is not offered"
    assert "sales[shop_sales][cash]" in html, "cash always has its own line"


def test_a_new_company_starts_with_cash_in_the_other_bucket(world_admin, client, app):
    """Creating a company links the default methods; Cash is type 'other', keyed cash_sales."""
    F.login(client, world_admin)
    client.post("/entity/create", data={
        "entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
        "contact_phone": "91234567", "business_email": "shop@test.com",
    })
    from models.db import Entity

    with app.app_context():
        entity = F.snapshot(Entity.query.filter_by(name="Corner Shop").one(), "id")
    rows = methods_api(client, entity)
    cash = [m for m in rows if m["name"] == "Cash"]
    assert cash and cash[0]["type"] == "other" and cash[0]["value_name"] == "cash_sales"
    assert names_by_type(rows, "electronic")[:3] == ["Visa", "Alipay", "WeChat Pay"]
    assert names_by_type(rows, "delivery") == ["Food Panda", "Keeta", "OpenRice"]


@pytest.fixture
def world_admin(app, db):
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        F.seed_country(db, currency)
        from blueprints.entity.services.modules import MODULE_BILL, MODULE_PETTY_CASH
        F.seed_module(db, MODULE_PETTY_CASH, "Petty Cash")
        F.seed_module(db, MODULE_BILL, "Payment Request")
        admin = F.make_user(db, "admin@test.com")
    return admin


def test_two_companies_that_type_the_same_method_share_one_catalogue_row(shop, client, app, db):
    """The catalogue is global (sale_info.sale_name is unique): "Payme" typed by two companies
    is one row, offered once to a third, and each company's on/off is its own."""
    owner, entity_a = shop
    with app.app_context():
        entity_b = F.make_entity(db, owner, name="Second Shop")
        entity_c = F.make_entity(db, owner, name="Third Shop")
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity_a.id, "electronic": ["Payme"], "delivery": []})
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity_b.id, "electronic": ["payme"], "delivery": []})
    F.login(client, owner)

    a = {m["name"].lower(): m["id"] for m in methods_api(client, entity_a)}
    b = {m["name"].lower(): m["id"] for m in methods_api(client, entity_b)}
    assert a["payme"] == b["payme"], "one catalogue row, two links"

    offered = client.get(f"/api/entities/{entity_c.id}/payment-methods/available").get_json()
    assert [m["name"] for m in offered["electronic"]].count("Payme") == 1

    client.delete(f"/api/entities/{entity_a.id}/payment-methods/{a['payme']}")
    assert "payme" not in {m["name"].lower() for m in methods_api(client, entity_a)}
    assert "payme" in {m["name"].lower() for m in methods_api(client, entity_b)}, "B's link is untouched"


def test_switching_a_method_off_keeps_the_amount_an_old_report_recorded(shop, client, app):
    owner, entity = shop
    client.post("/api/onboarding/sales-methods", headers=bearer(app, owner),
                json={"entity_id": entity.id, "electronic": ["Visa", "Alipay"], "delivery": []})
    F.login(client, owner)
    from test_char_report_lifecycle import open_report, post_sales

    day = date(2026, 9, 1)
    open_report(client, entity, day)
    post_sales(client, entity, day, cash="100", by_method={"visa_sales": "250", "alipay_sales": "50"})

    def sales_page():
        return client.get(f"/report/sale?entity_id={entity.id}&transaction_date=2026-09-01").get_data(as_text=True)

    assert "50" in sales_page()
    ids = {m["name"]: m["id"] for m in methods_api(client, entity)}
    assert client.delete(f"/api/entities/{entity.id}/payment-methods/{ids['Alipay']}").status_code == 200

    # the day's figures are unchanged: the amount recorded against Alipay still counts
    from blueprints.report.services.shared import sum_sales_by_type
    from models.db import Report

    with app.app_context():
        report = Report.query.filter_by(company=entity.id).one()
        totals = sum_sales_by_type(report.id)
    assert totals == {"electronic": 300.0, "delivery": 0.0, "cash": 0.0}, totals
    assert 'name="sales[shop_sales][alipay]"' not in sales_page(), "but the form no longer offers it"
