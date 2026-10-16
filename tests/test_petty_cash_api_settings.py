"""The Petty Cash API's settings (``blueprints/petty_cash_api/routes/settings.py``): Country &
currency and the Electronic / Delivery sales methods, over the services Flask's settings page uses
(pinned by tests/test_petty_cash_settings_page.py and tests/test_char_sales_methods.py). The door
is tests/test_petty_cash_api_door.py's."""
from __future__ import annotations

import char_factories as F
import pytest
from test_report_submit_state import db  # noqa: F401  (fixture)

pytestmark = pytest.mark.char

BASE = "/api/petty-cash/v1/companies/{}"


@pytest.fixture
def shop(app, db):  # noqa: F811
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa", "Alipay"), delivery=("Foodpanda",))
        F.seed_country(db, currency, code="SG")
    return owner, entity


def call(app, client, method, entity, who, path="", **kwargs):
    headers = F.petty_cash_headers(app, who.id, origin="http://localhost:3010")
    return client.open(BASE.format(entity.id) + path, method=method, headers=headers, **kwargs)


def names(body, kind):
    return [m["name"] for m in body["sales_methods"][kind]]


def cashier(app, db, entity):  # noqa: F811
    from models.db import UserEntity

    with app.app_context():
        person = F.make_user(db, "cashier@test.com", first_name="Cass")
        db.session.add(UserEntity(user_id=person.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
        return person


def test_the_settings_read(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "GET", entity, owner, "/settings")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["country"]["country_code"] == "HK" and body["country"]["currency_id"]
    assert {c["code"] for c in body["country"]["countries"]} == {"HK", "SG"}
    assert names(body, "electronic") == ["Visa", "Alipay"] and names(body, "delivery") == ["Foodpanda"]
    assert "Cash" not in names(body, "electronic") + names(body, "delivery")
    assert {m["name"]: m["shared"] for m in body["sales_methods"]["electronic"]} == {"Visa": False, "Alipay": False}


def test_a_method_another_company_uses_is_marked_shared(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    with app.app_context():
        other = F.make_entity(db, owner, name="Other Co")
        F.seed_sales_methods(db, owner, other, electronic=("Visa",), delivery=())
    body = call(app, client, "GET", entity, owner, "/settings").get_json()
    assert {m["name"]: m["shared"] for m in body["sales_methods"]["electronic"]} == {"Visa": True, "Alipay": False}
    assert body["xero_connected"] is False
    assert all(body["permissions"].values())


def test_a_cashier_reads_settings_but_may_change_nothing(app, client, db, shop):  # noqa: F811
    """As on Flask's page: COA_VIEW and SALES_METHOD_VIEW reach a cashier, who sees it read-only."""
    _owner, entity = shop
    resp = call(app, client, "GET", entity, cashier(app, db, entity), "/settings")
    assert resp.status_code == 200
    permissions = resp.get_json()["permissions"]
    assert permissions.pop("view_sales_methods") is True and not any(permissions.values())


def test_saving_the_country_brings_its_currency(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "PUT", entity, owner, "/settings/country", json={"country_code": "sg"})

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["message"] == "Country and currency saved."
    assert resp.get_json()["country"]["country_code"] == "SG"


@pytest.mark.parametrize("body, message", [
    ({}, "Choose a country or a currency to save."),
    ({"country_code": "ZZ"}, "Pick one of the countries offered."),
    ({"currency_id": "not-a-uuid"}, "Pick one of the currencies offered."),
    ({"currency_id": "6d0b6d55-0000-4000-8000-000000000000"}, "Pick one of the currencies offered."),
])
def test_a_bad_country_or_currency_is_refused(app, client, db, shop, body, message):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "PUT", entity, owner, "/settings/country", json=body)
    assert resp.status_code == 422 and resp.get_json() == {"error": message}


def test_a_cashier_may_not_change_the_country(app, client, db, shop):  # noqa: F811
    _owner, entity = shop
    resp = call(app, client, "PUT", entity, cashier(app, db, entity), "/settings/country", json={"country_code": "SG"})
    assert resp.status_code == 403


def test_adding_a_method_from_the_catalogue_or_by_name(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    with app.app_context():
        from blueprints.shared.enums import SaleType
        from models.db import SaleInfo

        octopus = str(SaleInfo.ensure("Octopus", SaleType.ELECTRONIC, value_name="octopus_sales").id)
        db.session.commit()
    offered = call(app, client, "GET", entity, owner, "/settings").get_json()["available"]["electronic"]
    assert octopus in [m["id"] for m in offered]

    added = call(app, client, "POST", entity, owner, "/sales-methods", json={"type": "electronic", "sale_info_id": octopus})
    assert added.status_code == 201, added.get_json()
    assert names(added.get_json(), "electronic") == ["Visa", "Alipay", "Octopus"]
    assert added.get_json()["message"] == "Octopus added."

    typed = call(app, client, "POST", entity, owner, "/sales-methods", json={"type": "delivery", "name": " Keeta "})
    assert typed.status_code == 201 and names(typed.get_json(), "delivery") == ["Foodpanda", "Keeta"]


@pytest.mark.parametrize("body, status, message", [
    ({"type": "other", "name": "Cheque"}, 422, "Choose Electronic or Delivery for the method."),
    ({"type": "electronic", "name": "  "}, 422, "The method's name is still empty. Type a name to add it."),
    ({"type": "electronic", "name": "x" * 101}, 422, "That name is too long. Keep it to 100 characters or fewer."),
    ({"type": "electronic", "sale_info_id": "nope"}, 422, "Pick one of the methods offered, or type a new name."),
    ({"type": "electronic", "name": "visa"}, 409, "visa is already on the list."),
])
def test_a_bad_method_is_refused(app, client, db, shop, body, status, message):  # noqa: F811
    owner, entity = shop
    resp = call(app, client, "POST", entity, owner, "/sales-methods", json=body)
    assert resp.status_code == status and resp.get_json() == {"error": message}


def test_renaming_removing_and_ordering(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    body = call(app, client, "GET", entity, owner, "/settings").get_json()
    visa, alipay = (m["id"] for m in body["sales_methods"]["electronic"])

    ordered = call(app, client, "PUT", entity, owner, "/sales-methods/order",
                   json={"type": "electronic", "method_ids": [alipay, visa]})
    assert ordered.status_code == 200, ordered.get_json()
    assert names(ordered.get_json(), "electronic") == ["Alipay", "Visa"]
    assert names(ordered.get_json(), "delivery") == ["Foodpanda"]

    stale = call(app, client, "PUT", entity, owner, "/sales-methods/order", json={"type": "electronic", "method_ids": [visa]})
    assert stale.status_code == 409

    renamed = call(app, client, "PUT", entity, owner, f"/sales-methods/{alipay}", json={"name": "AlipayHK"})
    assert renamed.status_code == 200, renamed.get_json()
    assert names(renamed.get_json(), "electronic") == ["AlipayHK", "Visa"]

    removed = call(app, client, "DELETE", entity, owner, f"/sales-methods/{visa}")
    assert removed.status_code == 200 and names(removed.get_json(), "electronic") == ["AlipayHK"]
    assert visa in [m["id"] for m in removed.get_json()["available"]["electronic"]]


def test_cash_and_unknown_methods_are_not_found(app, client, db, shop):  # noqa: F811
    from models.db import EntitySaleSetting, SaleInfo

    from blueprints.shared.enums import SaleType

    owner, entity = shop
    with app.app_context():
        cash = SaleInfo.ensure("Cash", SaleType.OTHER, value_name="cash_sales")
        db.session.add(EntitySaleSetting(entity_id=entity.id, sale_id=cash.id, is_active=True, display_order=0))
        db.session.commit()
        cash_id = str(cash.id)
    for method_id in (cash_id, F.new_id(), "nope"):
        assert call(app, client, "DELETE", entity, owner, f"/sales-methods/{method_id}").status_code == 404
        assert call(app, client, "PUT", entity, owner, f"/sales-methods/{method_id}", json={"name": "X"}).status_code == 404


def test_a_cashier_may_not_change_the_methods(app, client, db, shop):  # noqa: F811
    _owner, entity = shop
    person = cashier(app, db, entity)
    assert call(app, client, "POST", entity, person, "/sales-methods", json={"type": "electronic", "name": "Octopus"}).status_code == 403
