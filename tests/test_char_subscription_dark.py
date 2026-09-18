"""Characterisation: the subscription feature switched OFF (``SUBSCRIPTION_ENABLED``), the
state production cut over in (docs/modernisation/modernisation_plan.md, Phase E).

    the module page      -> the plain list; an admin's switch flips ``entity_function_map``
                            directly and the request gate follows it; no notice, no panel
    the wizard           -> /plans is empty and says why; the billing routes are gone;
                            finalize keeps step 2's modules on and starts NO trial
    the payer portal     -> every /api/me/* route is 404; the subscription-notice API too
    the module actions   -> checkout, start-trial, cancel ... all 404
    the scheduler        -> does not start, whatever SUBSCRIPTION_SCHEDULER_ENABLED says
    switching it ON      -> writes nothing: no grant, no trial, no revocation
    revoke-ungranted     -> lists while dark, refuses to write while dark, writes when on

Written 2026-09-18, the day the switch was built; the suite otherwise runs with the
feature ON (tests/conftest.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

import char_factories as F

pytestmark = pytest.mark.char

PETTY_CASH, PAYMENT_REQUEST = "PETTY_CASH", "PAYMENT_REQUEST"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def dark(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "0")
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "1")  # must make no difference


@pytest.fixture
def shop(app, db):
    """An admin, a company with Petty Cash on and Payment Request off, a cashier."""
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        F.seed_module(db, PAYMENT_REQUEST, "Payment Request")
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country, modules=(PETTY_CASH,))
        cashier = F.make_user(db, "cashier@test.com")
        from models.db import UserEntity

        db.session.add(UserEntity(user_id=cashier.id, entity_id=entity.id, role="cashier", approved=True))
        db.session.commit()
    return owner, entity, cashier


def module_on(app, entity_id, code) -> bool:
    from blueprints.entity.routes.modules import _is_module_enabled

    with app.app_context():
        return bool(_is_module_enabled(entity_id, code))


def onboarding_bearer(app, user_id):
    payload = {"user_id": str(user_id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10), "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


# ---- the module page -------------------------------------------------------------------------


def test_the_module_page_is_a_plain_list_with_a_switch_for_admins(dark, shop, client, app):
    owner, entity, cashier = shop
    F.login(client, owner)

    page = client.get(f"/entity/settings/module/{entity.id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200, page.data[:300]
    assert 'data-module-switch="PETTY_CASH"' in html and 'data-module-switch="PAYMENT_REQUEST"' in html
    # nothing of the live feature: no price, no trial, no panel, no notice
    for absent in ("Next payment date", "Free trial", "Subscribe to Minty", "Manage subscription", "subscription-notice"):
        assert absent not in html, absent

    # the switches are pending until Save; the page carries the saved state on each card
    assert 'data-save-modules' in html and 'data-module-status="PETTY_CASH"' in html
    assert "Your subscription" not in html and "Your modules" not in html

    # Save writes the whole set at once and answers the saved state; the gate follows it
    resp = client.post(f"/entity/settings/module/{entity.id}/toggle",
                       json={"modules": {PAYMENT_REQUEST: True, PETTY_CASH: False}})
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json() == {"modules": {PETTY_CASH: False, PAYMENT_REQUEST: True}}
    assert module_on(app, entity.id, PAYMENT_REQUEST) is True
    assert module_on(app, entity.id, PETTY_CASH) is False
    assert client.post(f"/entity/settings/module/{entity.id}/toggle", json={"modules": {"INVOICING": True}}).status_code == 400
    assert client.post(f"/entity/settings/module/{entity.id}/toggle", json={"code": PETTY_CASH, "enabled": True}).status_code == 400

    # a cashier sees the list and the panel, not the switch or Save, and cannot write
    F.login(client, cashier)
    html = client.get(f"/entity/settings/module/{entity.id}").get_data(as_text=True)
    assert "data-module-switch" not in html and "data-save-modules" not in html
    assert "Only admins can change modules" in html
    assert client.post(f"/entity/settings/module/{entity.id}/toggle", json={"modules": {PETTY_CASH: True}}).status_code in (302, 403)
    assert module_on(app, entity.id, PETTY_CASH) is False


def test_every_subscription_action_and_the_portal_are_gone(dark, shop, client, app):
    owner, entity, _ = shop
    F.login(client, owner)
    for action in ("checkout", "start-trial", "cancel", "renew", "retry-payment", "restart-billing",
                   "confirm-billing", "manage-billing", "subscribe-preview"):
        resp = client.post(f"/entity/settings/module/{entity.id}/{action}", json={"codes": [PETTY_CASH]})
        assert resp.status_code == 404, (action, resp.status_code)
    assert client.get(f"/entity/settings/module/{entity.id}/payment-methods").status_code == 404
    # the payer portal, with a billing bearer that would otherwise be accepted
    token = jwt.encode({"user_id": str(owner.id), "entity_id": str(entity.id), "scope": "billing",
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}, app.config["SECRET_KEY"], algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    for url in ("/api/me/subscriptions", "/api/me/invoices", "/api/me/billing/payment-methods",
                f"/api/entity/{entity.id}/subscription-notice"):
        resp = client.get(url, headers=headers)
        assert resp.status_code == 404, (url, resp.status_code)
        assert resp.headers.get("Access-Control-Allow-Origin"), url  # still a CORS answer, not a CORS failure
    # the dashboard renders with no notice
    page = client.get(f"/entity/{entity.id}")
    assert page.status_code == 200 and "subscriptionNoticeModal" not in page.get_data(as_text=True)


# ---- the wizard --------------------------------------------------------------------------------


def test_the_wizard_offers_no_plan_and_finalize_starts_no_trial(dark, shop, client, app, db):
    owner, _, _ = shop
    headers = onboarding_bearer(app, owner.id)

    plans = client.get("/api/onboarding/plans", headers=headers)
    assert plans.status_code == 200 and plans.get_json() == {"plans": [], "subscriptions_enabled": False}
    for url in ("/api/onboarding/payment-method?entity_id=x", "/api/onboarding/billing/accounts"):
        assert client.get(url, headers=headers).status_code == 404, url
    assert client.post("/api/onboarding/billing/authorize", json={}, headers=headers).status_code == 404

    entity_id = client.post("/api/onboarding/create", json={
        "entity_name": "Dark Co", "country_code": "HK", "currency_code": "HKD"}, headers=headers).get_json()["entity_id"]
    assert client.post("/api/onboarding/modules", json={"entity_id": entity_id, "modules": [PETTY_CASH, PAYMENT_REQUEST]},
                       headers=headers).status_code == 200

    resp = client.post("/api/onboarding/finalize", json={"entity_id": entity_id}, headers=headers)
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json() == {"status": "success", "trial_end": None, "subscriptions_enabled": False}
    assert module_on(app, entity_id, PETTY_CASH) and module_on(app, entity_id, PAYMENT_REQUEST)
    with app.app_context():
        from models.db import Entity, EntityModuleSubscription

        assert EntityModuleSubscription.query.filter_by(entity_id=entity_id).count() == 0
        assert str(Entity.query.get(entity_id).status) == "disconnected"


# ---- the switch itself ---------------------------------------------------------------------------


def test_the_scheduler_does_not_start_while_dark(dark, app):
    from services.app_runtime.scheduler import start_scheduler

    assert start_scheduler(app) is None


def test_switching_the_feature_on_writes_nothing(shop, client, app, monkeypatch):
    """Off -> on: the grants are exactly what they were, no trial and no revocation."""
    owner, entity, _ = shop
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "0")
    before = module_on(app, entity.id, PETTY_CASH), module_on(app, entity.id, PAYMENT_REQUEST)
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "1")
    F.login(client, owner)
    assert client.get(f"/entity/settings/module/{entity.id}").status_code == 200  # the live page
    assert (module_on(app, entity.id, PETTY_CASH), module_on(app, entity.id, PAYMENT_REQUEST)) == before
    with app.app_context():
        from models.db import EntityModuleSubscription

        assert EntityModuleSubscription.query.count() == 0
    # and the dark-only Save route is gone
    assert client.post(f"/entity/settings/module/{entity.id}/toggle", json={"modules": {PAYMENT_REQUEST: True}}).status_code == 404


def test_revoke_ungranted_is_the_deliberate_launch_step(shop, app, monkeypatch):
    from blueprints.subscription.services.access_sweep import revoke_ungranted_module_access
    from cli.subscription_access import revoke_ungranted_cmd

    owner, entity, _ = shop
    # dark: it names the grant with no subscription row, and refuses to write
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "0")
    with app.app_context():
        assert revoke_ungranted_module_access(dry_run=True) == [{"entity_id": str(entity.id), "code": PETTY_CASH}]
    runner = app.test_cli_runner()
    result = runner.invoke(revoke_ungranted_cmd, ["--apply"])
    assert result.exit_code != 0 and "SUBSCRIPTION_ENABLED is off" in result.output
    assert module_on(app, entity.id, PETTY_CASH) is True
    result = runner.invoke(revoke_ungranted_cmd, [])
    assert result.exit_code == 0 and "Would switch off 1" in result.output, result.output

    # on: the same command writes, and only then
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "1")
    result = runner.invoke(revoke_ungranted_cmd, ["--apply"])
    assert result.exit_code == 0 and "Switched off 1" in result.output, result.output
    assert module_on(app, entity.id, PETTY_CASH) is False
    with app.app_context():
        assert revoke_ungranted_module_access(dry_run=True) == []  # idempotent
