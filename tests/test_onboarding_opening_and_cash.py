"""Onboarding's opening balance and a company's cash denominations (2026-10-12).

* Step 5 saves the opening balance and start date on ``entity_pettycash_settings``; no
  report is written (``save_opening_balance``, behind Flask's fallback
  ``/api/onboarding/opening-balance``), and resume reads them back.
* Setting a currency writes one ``entity_cash_setting`` row per active ``cash_info`` row of
  it (``sync_cash_settings``) - on creation, on the wizard's edit and on the settings pages
  (``apply_country_currency_selection``).

minty-onboarding-api answers the same wizard paths; its tests pin the same rules.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest

import char_factories as F

pytestmark = pytest.mark.char

OPENING = "/api/onboarding/opening-balance"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def world(app, db):
    """HKD with three notes and a retired one, JPY with two, a country, the modules, an admin."""
    from blueprints.entity.services.modules import MODULE_BILL, MODULE_PETTY_CASH
    from models.db import CashInfo

    with app.app_context():
        hkd = F.seed_currency(db, "HKD", denominations=(100, 50, 10))
        jpy = F.seed_currency(db, "JPY", denominations=(1000, 500))
        db.session.add(CashInfo(currency_id=hkd.id, cash_value=1000, type="note",
                                cash_name="1000", display_order=0, is_active=False))
        db.session.commit()
        country = F.seed_country(db, hkd)
        F.seed_module(db, MODULE_PETTY_CASH, "Petty Cash")
        F.seed_module(db, MODULE_BILL, "Payment Request")
        admin = F.make_user(db, "admin@test.com")
    return {"hkd": hkd, "jpy": jpy, "country": country, "admin": admin}


def bearer(app, user_id):
    payload = {"user_id": str(user_id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
               "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


def create(client, headers, currency="HKD", name="Wizard Co"):
    resp = client.post("/api/onboarding/create", json={
        "entity_name": name, "country_code": "HK", "currency_code": currency,
    }, headers=headers)
    assert resp.status_code in (200, 201), resp.data[:300]
    return resp.get_json()["entity_id"]


def active_cash_ids(app, currency_id) -> set[str]:
    from models.db import CashInfo

    with app.app_context():
        return {str(c.id) for c in CashInfo.query.filter_by(currency_id=currency_id, is_active=True)}


def cash_rows(app, entity_id) -> dict[str, tuple]:
    from models.db import EntityCashSetting

    with app.app_context():
        return {str(r.cash_id): (r.is_active, r.display_order)
                for r in EntityCashSetting.query.filter_by(entity_id=entity_id)}


def settings_row(app, entity_id):
    from models.db import EntityPettycashSettings

    with app.app_context():
        row = EntityPettycashSettings.query.filter_by(entity_id=entity_id).first()
        return None if row is None else (row.opening_balance, row.start_date)


# ---- the opening balance ------------------------------------------------------------------


def test_the_opening_balance_lands_on_the_settings_and_writes_no_report(world, client, app):
    from models.db import Report

    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    start = date.today() - timedelta(days=3)

    resp = client.post(OPENING, json={"entity_id": entity_id, "opening_date": start.isoformat(),
                                      "opening_balance": "1500.50"}, headers=headers)

    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json() == {"opening_date": start.isoformat(), "opening_balance": 1500.5,
                               "cash_addition": 0.0, "adjusted_opening_balance": 1500.5}
    assert settings_row(app, entity_id) == (1500.5, start)
    with app.app_context():
        assert Report.query.filter_by(entity_id=entity_id).count() == 0

    state = client.get(f"/api/onboarding/state?entity_id={entity_id}", headers=headers).get_json()
    assert state["opening_balance"]["opening_date"] == start.isoformat()
    assert state["opening_balance"]["opening_balance"] == 1500.5


@pytest.mark.parametrize("body,status", [
    ({"opening_balance": "-1"}, 400),
    ({"opening_balance": "abc"}, 400),
    ({"opening_balance": "NaN"}, 400),
    ({"opening_date": "not-a-date", "opening_balance": "1"}, 400),
    ({"opening_date": (date.today() + timedelta(days=2)).isoformat(), "opening_balance": "1"}, 400),
])
def test_bad_input_is_refused_and_nothing_is_saved(world, client, app, body, status):
    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    payload = {"entity_id": entity_id, "opening_date": date.today().isoformat(), **body}

    assert client.post(OPENING, json=payload, headers=headers).status_code == status
    assert settings_row(app, entity_id) is None


def test_once_a_report_is_posted_the_opening_balance_is_409(world, client, app, db):
    from models.db import Report

    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    with app.app_context():
        db.session.add(Report(entity_id=entity_id, transaction_date=date.today() - timedelta(days=5),
                              status="submitted", opening_balance=0, cash_addition=0))
        db.session.commit()

    resp = client.post(OPENING, json={"entity_id": entity_id, "opening_date": date.today().isoformat(),
                                      "opening_balance": "10"}, headers=headers)

    assert resp.status_code == 409
    assert settings_row(app, entity_id) is None


# ---- cash denominations follow the currency -----------------------------------------------


def test_creation_copies_the_currency_s_active_denominations(world, client, app):
    entity_id = create(client, bearer(app, world["admin"].id))

    rows = cash_rows(app, entity_id)
    assert set(rows) == active_cash_ids(app, world["hkd"].id)  # the retired $1000 is left out
    assert all(on for on, _order in rows.values())


def test_the_wizard_s_currency_change_swaps_the_denominations(world, client, app):
    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)

    resp = client.put(f"/api/onboarding/entity/{entity_id}", json={"currency_id": world["jpy"].id},
                      headers=headers)

    assert resp.status_code == 200, resp.data[:300]
    assert set(cash_rows(app, entity_id)) == active_cash_ids(app, world["jpy"].id)


def test_the_settings_save_syncs_and_keeps_the_company_s_own_choices(world, client, app, db):
    from blueprints.entity.services.xero_account_mapping_post import apply_country_currency_selection
    from models.db import Entity, EntityCashSetting

    entity_id = create(client, bearer(app, world["admin"].id))
    switched_off = next(iter(active_cash_ids(app, world["hkd"].id)))
    with app.app_context():
        EntityCashSetting.query.filter_by(entity_id=entity_id, cash_id=switched_off).update(
            {"is_active": False, "display_order": 99})
        db.session.commit()

        entity = Entity.query.get(entity_id)
        apply_country_currency_selection(entity, {"currency_id": world["hkd"].id})
        db.session.commit()
    assert cash_rows(app, entity_id)[switched_off] == (False, 99)

    with app.app_context():
        entity = Entity.query.get(entity_id)
        apply_country_currency_selection(entity, {"currency_id": world["jpy"].id})
        db.session.commit()
    assert set(cash_rows(app, entity_id)) == active_cash_ids(app, world["jpy"].id)


def test_a_company_created_with_no_currency_has_no_denomination_rows(world, client, app):
    resp = client.post("/api/onboarding/create", json={"entity_name": "No Cur Co"},
                       headers=bearer(app, world["admin"].id))
    assert resp.status_code in (200, 201), resp.data[:300]
    assert cash_rows(app, resp.get_json()["entity_id"]) == {}


def test_amounts_are_stored_exactly(world, client, app):
    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    client.post(OPENING, json={"entity_id": entity_id, "opening_date": date.today().isoformat(),
                               "opening_balance": "0.1"}, headers=headers)
    client.post(OPENING, json={"entity_id": entity_id, "opening_date": date.today().isoformat(),
                               "opening_balance": "1234.56"}, headers=headers)
    assert Decimal(str(settings_row(app, entity_id)[0])) == Decimal("1234.56")


# ---- round 2 (2026-10-13) -----------------------------------------------------------------


def detail_rows(app, entity_id) -> int:
    from models.db import EntityCashDetail

    with app.app_context():
        return EntityCashDetail.query.filter_by(entity_id=entity_id).count()


def entity_value(app, entity_id, field):
    from models.db import Entity

    with app.app_context():
        return getattr(Entity.query.get(entity_id), field)


def test_setting_a_currency_writes_no_stock_rows(world, client, app):
    """entity_cash_detail is filled when a Petty Cash report is submitted, never by onboarding."""
    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    client.put(f"/api/onboarding/entity/{entity_id}", json={"currency_id": world["jpy"].id},
               headers=headers)
    assert detail_rows(app, entity_id) == 0


def test_the_opening_balance_needs_a_currency(world, client, app):
    headers = bearer(app, world["admin"].id)
    resp = client.post("/api/onboarding/create", json={"entity_name": "No Cur Co"}, headers=headers)
    entity_id = resp.get_json()["entity_id"]

    resp = client.post(OPENING, json={"entity_id": entity_id, "opening_date": date.today().isoformat(),
                                      "opening_balance": "100"}, headers=headers)

    assert resp.status_code == 400
    assert "currency" in resp.get_json()["error"].lower()
    assert settings_row(app, entity_id) is None


def test_the_creator_joins_when_the_company_is_created(world, client, app):
    from models.db import UserEntity

    entity_id = create(client, bearer(app, world["admin"].id))
    with app.app_context():
        membership = UserEntity.query.filter_by(entity_id=entity_id, user_id=world["admin"].id).one()
        assert membership.joined_at is not None


def test_a_new_company_has_no_saved_step(world, client, app):
    """NULL means "never saved"; the column's database default (9) would mean "finished"."""
    entity_id = create(client, bearer(app, world["admin"].id))
    assert entity_value(app, entity_id, "onboarding_saved_step") is None


def test_the_browser_timezone_is_saved(world, client, app):
    headers = bearer(app, world["admin"].id)
    resp = client.post("/api/onboarding/create", json={
        "entity_name": "Tz Co", "country_code": "HK", "currency_code": "HKD",
        "timezone": "Asia/Hong_Kong",
    }, headers=headers)
    entity_id = resp.get_json()["entity_id"]
    assert entity_value(app, entity_id, "timezone") == "Asia/Hong_Kong"

    client.put(f"/api/onboarding/entity/{entity_id}", json={"timezone": "Asia/Singapore"},
               headers=headers)
    assert entity_value(app, entity_id, "timezone") == "Asia/Singapore"


def test_an_unknown_timezone_is_refused(world, client, app):
    resp = client.post("/api/onboarding/create", json={
        "entity_name": "Bad Tz Co", "country_code": "HK", "timezone": "Mars/Olympus",
    }, headers=bearer(app, world["admin"].id))
    assert resp.status_code == 400


def test_create_takes_the_country_s_currency_when_none_is_sent(world, client, app):
    resp = client.post("/api/onboarding/create", json={"entity_name": "Country Co", "country_code": "HK"},
                       headers=bearer(app, world["admin"].id))
    entity_id = resp.get_json()["entity_id"]
    assert str(entity_value(app, entity_id, "currency_id")) == str(world["hkd"].id)


def test_countries_carry_their_currency(world, client, app):
    resp = client.get("/api/onboarding/countries", headers=bearer(app, world["admin"].id))
    hk = next(c for c in resp.get_json()["countries"] if c["country_code"] == "HK")
    assert str(hk["currency_id"]) == str(world["hkd"].id)


def test_currencies_carry_their_decimal_places(world, client, app):
    resp = client.get("/api/onboarding/currencies", headers=bearer(app, world["admin"].id))
    hkd = next(c for c in resp.get_json()["currencies"] if c["iso_code"] == "HKD")
    assert hkd["decimal_places"] == 2


def test_an_amount_finer_than_the_currency_is_refused(world, client, app):
    headers = bearer(app, world["admin"].id)
    entity_id = create(client, headers)
    resp = client.post(OPENING, json={"entity_id": entity_id, "opening_date": date.today().isoformat(),
                                      "opening_balance": "10.005"}, headers=headers)
    assert resp.status_code == 400
