"""Characterisation: companies and their modules - creation, status, settings, the module map.

Written before C2 of docs/modernisation/modernisation_plan.md (entities / entity_function /
entity_function_map follow the rebased schema). Everything is observed through endpoints
and the CLI; the two places a column is read directly (``created_by``, the country /
currency FKs) are the facts the redesign changes and nothing renders.

Where C2 *decided* a new behaviour the test asserts the decision (they were strict xfails
on the pre-C2 code):

* ``entity_status`` is ``onboarding / connected / disconnected`` - finalize writes
  ``disconnected`` unless a Xero org is linked (today: ``active``); the soft-delete route
  and its ``deleted`` status go (nothing links to it, production holds no such row).
* ``entity_function_map.created_by`` is the creator's user id (uuid FK), NULL for the
  CLI (today: labels such as ``entity_create``).
* the module code for the Payment Request module is ``PAYMENT_REQUEST`` (today ``BILL``);
  the tests use the constants so they follow the rename.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


@pytest.fixture
def world(app, db):
    """A currency, its country, the two catalogue modules and an admin with no company yet."""
    from blueprints.entity.services.modules import MODULE_BILL, MODULE_PETTY_CASH

    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        F.seed_module(db, MODULE_PETTY_CASH, "Petty Cash")
        F.seed_module(db, MODULE_BILL, "Payment Request")
        admin = F.make_user(db, "admin@test.com")
    return {"currency": currency, "country": country, "admin": admin}


def onboarding_bearer(app, user_id):
    payload = {"user_id": str(user_id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
               "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


def module_map(app, entity_id):
    """{code: (is_enabled, created_by)} straight from the map - the one fact no page shows."""
    from models.db import EntityFunction, EntityFunctionMap

    with app.app_context():
        rows = (
            EntityFunctionMap.query.join(EntityFunction, EntityFunction.id == EntityFunctionMap.entity_function_id)
            .filter(EntityFunctionMap.entity_id == entity_id)
            .with_entities(EntityFunction.function_code, EntityFunctionMap.is_enabled, EntityFunctionMap.created_by)
            .all()
        )
    return {code: (enabled, created_by) for code, enabled, created_by in rows}


def entity_row(app, entity_id):
    from models.db import Entity

    with app.app_context():
        e = Entity.query.get(entity_id)
        return F.snapshot(e, "id", "name", "status", "country_code", "currency_id", "xero_org_id")


# ---- the entity-create form -------------------------------------------------------------------


def test_creating_a_company_makes_the_creator_its_admin_and_seeds_every_module_off(world, client, app):
    from blueprints.entity.services.modules import MODULE_BILL, MODULE_PETTY_CASH

    admin = world["admin"]
    F.login(client, admin)
    resp = client.post("/entity/create", data={
        "entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
        "contact_phone": "91234567", "business_email": "shop@test.com",
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.data[:300]

    from models.db import Entity, UserEntity

    with app.app_context():
        entity = Entity.query.filter_by(name="Corner Shop").one()
        membership = UserEntity.query.filter_by(user_id=admin.id, entity_id=entity.id).one()
        assert membership.role == "admin"
        assert entity.country_code == world["country"].country_code
        assert entity.currency_id == world["currency"].id
        entity_id = entity.id

    state = module_map(app, entity_id)
    assert set(state) == {MODULE_PETTY_CASH, MODULE_BILL}
    assert all(enabled is False for enabled, _ in state.values()), "creation grants nothing; a trial or subscription switches a module on"

    assert "Corner Shop" in [row["name"] for row in F.hub_list(client, app, admin.id)]


def test_the_module_rows_a_creation_seeds_carry_the_creator(world, client, app):
    admin = world["admin"]
    F.login(client, admin)
    client.post("/entity/create", data={
        "entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
        "contact_phone": "91234567", "business_email": "shop@test.com",
    })
    from models.db import Entity

    with app.app_context():
        entity_id = Entity.query.filter_by(name="Corner Shop").one().id
    assert {created_by for _, created_by in module_map(app, entity_id).values()} == {admin.id}


def test_a_second_company_with_the_same_name_is_refused(world, client, app):
    admin = world["admin"]
    F.login(client, admin)
    data = {"entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
            "contact_phone": "91234567", "business_email": "shop@test.com"}
    client.post("/entity/create", data=data)
    resp = client.post("/entity/create", data=data)
    assert resp.status_code in (200, 302), "back to the form, not created again"
    from models.db import Entity

    with app.app_context():
        assert Entity.query.filter_by(name="Corner Shop").count() == 1


# ---- the onboarding wizard's API --------------------------------------------------------------


def test_onboarding_create_starts_the_company_in_onboarding_and_the_wizard_can_read_it_back(world, client, app):
    admin = world["admin"]
    headers = onboarding_bearer(app, admin.id)
    resp = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD",
    }, headers=headers)
    assert resp.status_code in (200, 201), resp.data[:300]
    entity_id = resp.get_json()["entity_id"]

    state = client.get(f"/api/onboarding/state?entity_id={entity_id}", headers=headers)
    assert state.status_code == 200, state.data[:300]
    assert state.get_json()["status"] == "onboarding"

    # a repeated Step 1 for the same name rebinds the wizard to the same row
    again = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD",
    }, headers=headers)
    assert again.get_json()["entity_id"] == entity_id


def test_module_selection_turns_the_chosen_modules_on_and_the_rest_off(world, client, app):
    from blueprints.entity.services.modules import MODULE_BILL, MODULE_PETTY_CASH

    admin = world["admin"]
    headers = onboarding_bearer(app, admin.id)
    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD"}, headers=headers).get_json()["entity_id"]

    resp = client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_BILL]}, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["modules"] == {MODULE_PETTY_CASH: False, MODULE_BILL: True}

    resp = client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_PETTY_CASH, MODULE_BILL]}, headers=headers)
    assert resp.get_json()["modules"] == {MODULE_PETTY_CASH: True, MODULE_BILL: True}

    resp = client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": ["INVOICING"]}, headers=headers)
    assert resp.status_code == 400


def test_module_selection_records_who_chose(world, client, app):
    from blueprints.entity.services.modules import MODULE_BILL

    admin = world["admin"]
    headers = onboarding_bearer(app, admin.id)
    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD"}, headers=headers).get_json()["entity_id"]
    client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_BILL]}, headers=headers)
    assert {created_by for _, created_by in module_map(app, entity_id).values()} == {admin.id}


def test_a_stranger_cannot_read_or_shape_someone_elses_onboarding(world, client, app, db):
    from blueprints.entity.services.modules import MODULE_BILL

    admin = world["admin"]
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")
    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD"},
        headers=onboarding_bearer(app, admin.id)).get_json()["entity_id"]

    theirs = onboarding_bearer(app, stranger.id)
    assert client.get(f"/api/onboarding/state?entity_id={entity_id}", headers=theirs).status_code == 403
    assert client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_BILL]}, headers=theirs).status_code == 403
    assert client.post("/api/onboarding/finalize", json={"entity_id": entity_id}, headers=theirs).status_code == 403
    assert client.get(f"/api/onboarding/state?entity_id={entity_id}").status_code == 401


def test_finalizing_a_company_without_xero_leaves_it_disconnected(world, client, app, monkeypatch):
    from blueprints.entity.services.modules import MODULE_PETTY_CASH

    admin = world["admin"]
    headers = onboarding_bearer(app, admin.id)
    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD"}, headers=headers).get_json()["entity_id"]
    client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_PETTY_CASH]}, headers=headers)

    resp = client.post("/api/onboarding/finalize", json={"entity_id": entity_id}, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert entity_row(app, entity_id).status == "disconnected"


def test_finalizing_takes_the_company_out_of_onboarding_and_the_list_stops_offering_the_wizard(world, client, app):
    from blueprints.entity.services.modules import MODULE_PETTY_CASH

    admin = world["admin"]
    headers = onboarding_bearer(app, admin.id)
    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD"}, headers=headers).get_json()["entity_id"]
    client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [MODULE_PETTY_CASH]}, headers=headers)

    resp = client.post("/api/onboarding/finalize", json={"entity_id": entity_id}, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert entity_row(app, entity_id).status != "onboarding"

    rows = {row["name"]: row for row in F.hub_list(client, app, admin.id)}
    # "Setup in progress" is a row still onboarding
    assert rows["Wizard Co"]["status"] != "onboarding"


# ---- settings -----------------------------------------------------------------------------------


@pytest.fixture
def company(app, db, world):
    with app.app_context():
        entity = F.make_entity(db, world["admin"], name="Corner Shop",
                               currency=world["currency"], country=world["country"])
    return entity


def test_the_settings_pages_render_for_an_admin(world, company, client):
    F.login(client, world["admin"])
    for url in (f"{F.co(client, company.id)}/settings/petty-cash", f"{F.co(client, company.id)}/modules"):
        resp = client.get(url, follow_redirects=True)
        assert resp.status_code == 200, (url, resp.status_code, resp.data[:200])
    # the Module, Users and Entity & Integration tabs are minty-web's pages: hand-overs, not
    # renders (test_minty_web_handoff, test_hub_company_settings)
    for tab in ("modules", "users", "integration"):
        resp = client.get(f"{F.co(client, company.id)}/settings/{tab}")
        assert resp.status_code == 302 and "/landing?next=" in resp.headers["Location"], tab


def test_a_cashier_cannot_change_the_company_settings(world, company, client, app, db):
    from models.db import UserEntity

    with app.app_context():
        cashier = F.make_user(db, "cashier@test.com")
        db.session.add(UserEntity(user_id=cashier.id, entity_id=company.id, role="cashier", approved=True))
        db.session.commit()
    F.login(client, cashier)
    resp = client.post(f"{F.co(client, company.id)}/settings/petty-cash", data={"country_code": "HK", "currency_code": "HKD"})
    assert resp.status_code in (302, 403)
    assert entity_row(app, company.id).name == "Corner Shop"


def test_xero_disconnect_flips_the_company_to_disconnected(world, company, client, app, db, monkeypatch):
    import requests

    calls = []

    class _Resp:
        status_code = 204
        text = ""

        def json(self):
            return None

    monkeypatch.setattr(requests, "delete", lambda url, **kw: calls.append(url) or _Resp())
    monkeypatch.setattr(requests, "get", lambda url, **kw: type("R", (), {"status_code": 200, "text": "[]", "json": lambda self: [{"id": "conn-1", "tenantId": "t-1"}]})())
    with app.app_context():
        F.connect_xero(db, world["admin"], company, tenant_id="t-1",
                       tokens={"access_token": "a", "refresh_token": "r", "id_token": "i", "expires_in": 1800})
    assert entity_row(app, company.id).status == "connected"

    # minty-web's Entity & Integration tab, through Flask's bearer route (phase 2)
    resp = client.post("/api/me/company/xero/disconnect", query_string={"entity": company.id},
                       headers=F.hub_headers(app, world["admin"].id))
    assert resp.status_code == 200, resp.data[:300]
    assert calls == ["https://api.xero.com/connections/conn-1"], "the grant is revoked at Xero"
    row = entity_row(app, company.id)
    assert row.status == "disconnected"
    assert row.xero_org_id is None


# ---- deleting -----------------------------------------------------------------------------------


def test_there_is_no_soft_delete_route(world, company, client):
    F.login(client, world["admin"])
    assert client.post(f"{F.co(client, company.id)}/delete").status_code == 404


# ---- the CLI ------------------------------------------------------------------------------------


def test_the_cli_can_switch_a_module_and_records_no_person(world, company, app):
    from blueprints.entity.services.modules import MODULE_BILL

    runner = app.test_cli_runner()
    result = runner.invoke(args=["modules", "set", company.id, MODULE_BILL, "on"])
    assert result.exit_code == 0, result.output
    state = module_map(app, company.id)
    assert state[MODULE_BILL][0] is True
    # decided (schema section 4): the CLI is nobody - created_by is NULL, never a label
    assert state[MODULE_BILL][1] is None
