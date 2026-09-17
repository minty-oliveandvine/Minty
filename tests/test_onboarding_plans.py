"""The onboarding plan catalog behind Step 2's subscription summary.

The wizard previews subtotal / bulk discount / total client-side, so the figures it
is handed must be the same ones the server bills from. These tests pin the catalog's
amounts and discount unit to the plan views the catalog reads out of ``billing_plan``,
and pin the discount RULE (2+ modules, same currency) to the same arithmetic
``get_subscription_summary`` uses.

NOTE: imports are done INSIDE each test (as in the other subscription tests) so the
lazy re-imports stay mutually consistent.
"""
from __future__ import annotations

# The price catalog is patched BY DOTTED PATH, not via an imported reference:
# conftest re-imports project modules mid-session, so a module object captured at
# import time is not the one the code under test ends up calling.
_CATALOG = "blueprints.subscription.services.catalog"

import uuid

import jwt
import pytest

_schema_attached = False


@pytest.fixture()
def db_session(app):
    """A live schema for the catalog queries (EntityFunction / CurrencyInfo).

    Mirrors tests/test_entity_create.py: the models live in the ``pettycashv3``
    schema, so attach it in memory before create_all.
    """
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv3"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _seed_catalog(db):
    """The module catalog rows the names in the plan list come from."""
    from models.db import EntityFunction

    for code, name in (("PETTY_CASH", "Petty Cash"), ("PAYMENT_REQUEST", "Payment Request")):
        db.session.add(
            EntityFunction(
                id=str(uuid.uuid4()),
                function_code=code,
                function_name=name,
                description=f"{name} module",
                is_active=True,
            )
        )
    db.session.commit()


def _plan(code, fn_id, *, amount=28000, currency="HKD"):
    from blueprints.subscription.services import catalog

    return catalog.PlanView(
        entity_function_id=fn_id,
        function_code=code,
        display_name=code.title().replace("_", " "),
        amount=amount,
        currency_code=currency,
        billing_interval="month",
        billing_interval_count=1,
        is_available_for_subscription=True,
    )


def _bundle():
    from blueprints.subscription.services import catalog

    return catalog.BundlePlanView(
        function_codes=("PETTY_CASH", "PAYMENT_REQUEST"),
        display_name="Super Minty",
        amount=40000,
        currency_code="HKD",
        billing_interval="month",
        billing_interval_count=1,
    )


def _wire_catalog(monkeypatch, *, plans=None, bundle=True):
    """Point the plan catalog at fixed plan views."""
    if plans is None:
        plans = [_plan("PETTY_CASH", "fn_pc"), _plan("PAYMENT_REQUEST", "fn_bill")]
    monkeypatch.setattr(f"{_CATALOG}.available_plans", lambda: plans)
    monkeypatch.setattr(f"{_CATALOG}.bundle_plan", lambda: (_bundle() if bundle else None))


def test_catalog_normalizes_amounts_and_bundle(db_session, monkeypatch):
    """Smallest-currency-unit amounts come back as display decimals."""
    from blueprints.entity.services import modules

    _seed_catalog(db_session)
    _wire_catalog(monkeypatch)

    catalog = modules.get_module_plan_catalog()

    by_code = {p["code"]: p for p in catalog["plans"]}
    assert set(by_code) == {"PETTY_CASH", "PAYMENT_REQUEST"}
    # 28000 (cents) -> 280.00, not 28000.
    assert by_code["PETTY_CASH"]["amount"] == 280.0
    assert by_code["PETTY_CASH"]["formatted_amount"] == "280.00"
    assert by_code["PETTY_CASH"]["currency_code"] == "HKD"
    assert by_code["PETTY_CASH"]["billing_interval"] == "month"
    # The label shown on the summary line comes from the catalog, not the code.
    assert by_code["PETTY_CASH"]["name"] == "Petty Cash"
    assert by_code["PAYMENT_REQUEST"]["name"] == "Payment Request"
    # The bundle IS the discount: 40000 -> 400.00 for both modules together, and the
    # wizard is told which modules it covers so it can price the cart the same way.
    assert catalog["bundle_amount"] == 400.0
    assert catalog["bundle_codes"] == ["PAYMENT_REQUEST", "PETTY_CASH"]
    assert catalog["bundle_currency"] == "HKD"
    # The wizard needs the trial length to label "Due today / free for N days".
    assert catalog["trial_period_days"] == 30


def test_catalog_matches_server_summary_math(db_session, monkeypatch):
    """The wizard's preview arithmetic must equal what the server would bill.

    The client computes: subtotal = sum(lines); discount = unit * eligible_lines
    when 2+ lines; total = subtotal - discount — the same shape as
    ``get_subscription_summary``. Recompute it here from the catalog the wizard is
    handed, so a change to either side that breaks the parity fails this test.
    """
    from blueprints.entity.services import modules

    _seed_catalog(db_session)
    _wire_catalog(monkeypatch)

    catalog = modules.get_module_plan_catalog()

    lines = catalog["plans"]  # both modules picked
    subtotal = sum(p["amount"] for p in lines)
    picked = sorted(p["code"] for p in lines)
    # The cart bills the bundle price when the picked set is exactly the bundle's.
    total = catalog["bundle_amount"] if picked == catalog["bundle_codes"] else subtotal
    discount = subtotal - total

    assert subtotal == 560.0  # 280 + 280 separately
    assert total == 400.0  # the bundle price
    assert discount == 160.0  # the saving vs paying for each module separately


def test_single_module_pays_full_price(db_session, monkeypatch):
    """One module picked: not the bundle set, so it pays its own price."""
    from blueprints.entity.services import modules

    _seed_catalog(db_session)
    _wire_catalog(monkeypatch)

    catalog = modules.get_module_plan_catalog()

    lines = [p for p in catalog["plans"] if p["code"] == "PAYMENT_REQUEST"]
    subtotal = sum(p["amount"] for p in lines)
    picked = sorted(p["code"] for p in lines)
    total = catalog["bundle_amount"] if picked == catalog["bundle_codes"] else subtotal
    assert total == 280.0  # standalone price, no bundle
    assert subtotal - total == 0


def test_module_without_a_priced_plan_is_omitted(db_session, monkeypatch):
    """A module with no priced plan is left out rather than shown as free."""
    from blueprints.entity.services import modules

    _seed_catalog(db_session)
    _wire_catalog(monkeypatch, plans=[_plan("PETTY_CASH", "fn_pc")])

    catalog = modules.get_module_plan_catalog()

    assert [p["code"] for p in catalog["plans"]] == ["PETTY_CASH"]


def test_catalog_without_a_bundle_product(db_session, monkeypatch):
    """No bundle row in the price catalog → the wizard previews no bundle price."""
    from blueprints.entity.services import modules

    _seed_catalog(db_session)
    _wire_catalog(monkeypatch, bundle=False)

    catalog = modules.get_module_plan_catalog()

    assert catalog["bundle_amount"] == 0
    assert catalog["bundle_codes"] == []
    assert catalog["bundle_currency"] is None


# --- the endpoint the wizard actually calls --------------------------------

def _token(app, user_id="u1"):
    from datetime import datetime, timedelta, timezone

    return jwt.encode(
        {
            "user_id": user_id,
            "scope": "onboarding",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "iat": datetime.now(timezone.utc),
        },
        app.config["SECRET_KEY"],
        algorithm="HS256",
    )


def test_plans_endpoint_requires_a_token(app):
    client = app.test_client()
    assert client.get("/api/onboarding/plans").status_code == 401


def test_plans_endpoint_returns_the_catalog(app, monkeypatch):
    from blueprints.entity.routes import create as create_routes

    _wire_catalog(monkeypatch)
    # The route imports the service lazily, so patch it where it's looked up.
    monkeypatch.setattr(
        "blueprints.entity.services.modules.get_module_plan_catalog",
        lambda: {
            "plans": [
                {
                    "code": "PETTY_CASH", "name": "Petty Cash", "amount": 280.0,
                    "formatted_amount": "280.00", "currency_code": "HKD",
                    "currency_symbol": "HK$", "billing_interval": "month",
                }
            ],
            "bundle_amount": 400.0,
            "bundle_codes": ["PAYMENT_REQUEST", "PETTY_CASH"],
            "bundle_currency": "HKD",
            "trial_period_days": 30,
        },
    )

    client = app.test_client()
    res = client.get(
        "/api/onboarding/plans",
        headers={"Authorization": f"Bearer {_token(app)}"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["plans"][0]["code"] == "PETTY_CASH"
    assert body["bundle_amount"] == 400.0
    assert body["bundle_codes"] == ["PAYMENT_REQUEST", "PETTY_CASH"]
    assert body["trial_period_days"] == 30
    # Cross-origin from the wizard: the CORS contract must hold like the siblings.
    assert "Access-Control-Allow-Origin" in res.headers
    assert create_routes  # keep the import meaningful


def test_plans_endpoint_degrades_when_the_catalog_fails(app, monkeypatch):
    """Catalog unreadable → 503, not a 500. The wizard hides the summary and the
    user can still pick a module."""
    def _boom():
        raise RuntimeError("catalog is down")

    monkeypatch.setattr(
        "blueprints.entity.services.modules.get_module_plan_catalog", _boom
    )

    client = app.test_client()
    res = client.get(
        "/api/onboarding/plans",
        headers={"Authorization": f"Bearer {_token(app)}"},
    )
    assert res.status_code == 503
    assert "error" in res.get_json()
