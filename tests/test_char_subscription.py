"""Characterisation: one company's subscription life, through the routes and the scheduled
jobs, on the real database (C7). The fourteen ``test_subscription_*`` files are unit-level
with the store and the biller faked; this walks the rows.

    trial started from the module card -> access on, a `trial` row
    trial ends with no card             -> `expired`, access off, the lapsed-trial restart state
    trial ends with a card + consent    -> converted: an in-house invoice with one line for the
                                            company, exact cents, the payer's cycle anchored,
                                            an audit row with outcome `succeeded`
    the payer cancels                   -> `scheduled_cancel` with access to the period end, and
                                            the audit row names module, phases and outcome

Stripe is faked at ``stripe_client.get_stripe`` (the SDK boundary); the plan comes from a real
``billing_plan`` row. Written 2026-09-17 before the C7 type changes (uuid FKs on the
subscription tables, ``module_code`` on ``function_code``), so the change is visible if it
moves any of this.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import char_factories as F

pytestmark = pytest.mark.char

MODULE = "PETTY_CASH"
PRICE_CENTS = 28000


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


@pytest.fixture
def shop(app, db):
    """An admin and a company with Petty Cash switched OFF and a sellable plan for it."""
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country, modules=())
        F.seed_module(db, MODULE, "Petty Cash")
        from models.db import BillingPlan

        db.session.add(BillingPlan(
            id=str(uuid.uuid4()), code=MODULE, display_name="Petty Cash", amount=PRICE_CENTS,
            currency="HKD", interval_months=1, is_active=True,
        ))
        db.session.commit()
    return owner, entity


# ---- Stripe, faked at the SDK boundary ------------------------------------------------------


class FakeStripe:
    """Just enough of the SDK for the in-house invoice: create -> items -> finalize -> pay."""

    def __init__(self, *, pays=True):
        self.pays = pays
        self.invoices: dict[str, dict] = {}
        self.items: list[dict] = []
        outer = self

        class Invoice:
            @staticmethod
            def create(**kw):
                inv = {"id": f"in_{len(outer.invoices) + 1}", "status": "draft", "lines": {"data": []},
                       "customer": kw.get("customer"), "metadata": kw.get("metadata") or {},
                       "amount_due": 0, "total": 0, "currency": "hkd", "hosted_invoice_url": None,
                       "payment_intent": None, "collection_method": kw.get("collection_method")}
                outer.invoices[inv["id"]] = inv
                return inv

            @staticmethod
            def retrieve(invoice_id, **kw):
                return outer.invoices[invoice_id]

            @staticmethod
            def finalize_invoice(invoice_id, **kw):
                inv = outer.invoices[invoice_id]
                total = sum(i["amount"] for i in outer.items if i["invoice"] == invoice_id)
                inv.update(status="open", total=total, amount_due=total, number=f"INV-{invoice_id}")
                return inv

            @staticmethod
            def pay(invoice_id, **kw):
                inv = outer.invoices[invoice_id]
                if outer.pays:
                    inv.update(status="paid", amount_paid=inv["total"], amount_due=0,
                               status_transitions={"paid_at": int(datetime.now(timezone.utc).timestamp())})
                else:
                    inv.update(status="open", last_finalization_error={"message": "card_declined"})
                return inv

            @staticmethod
            def void_invoice(invoice_id, **kw):
                outer.invoices[invoice_id]["status"] = "void"
                return outer.invoices[invoice_id]

            @staticmethod
            def list(**kw):
                rows = [i for i in outer.invoices.values() if not kw.get("status") or i["status"] == kw["status"]]
                return SimpleNamespace(data=rows, auto_paging_iter=lambda: iter(rows))

        class InvoiceItem:
            @staticmethod
            def create(**kw):
                item = {"id": f"ii_{len(outer.items) + 1}", "invoice": kw.get("invoice"),
                        "amount": kw.get("amount", 0), "description": kw.get("description")}
                outer.items.append(item)
                return item

        class Customer:
            @staticmethod
            def retrieve(customer_id, **kw):
                return {"id": customer_id, "invoice_settings": {"default_payment_method": "pm_card"}}

            @staticmethod
            def search(**kw):
                return {"data": []}

        class PaymentMethod:
            @staticmethod
            def retrieve(pm_id, **kw):
                return {"id": pm_id, "type": "card", "card": {"brand": "visa", "last4": "4242",
                        "exp_month": 12, "exp_year": 2099}}

        self.Invoice, self.InvoiceItem, self.Customer, self.PaymentMethod = Invoice, InvoiceItem, Customer, PaymentMethod


def install_fake_stripe(monkeypatch, *, pays=True) -> FakeStripe:
    from blueprints.subscription.services import stripe_client

    fake = FakeStripe(pays=pays)
    monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
    # modules that bound the name at import time
    import sys

    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("blueprints.subscription") and hasattr(module, "get_stripe"):
            monkeypatch.setattr(module, "get_stripe", lambda: fake)
    return fake


def set_clock(monkeypatch, moment):
    from blueprints.subscription.services import clock

    monkeypatch.setattr(clock, "now", lambda: moment)


# ---- readers (rows, through the store) ---------------------------------------------------------


def module_row(app, entity_id):
    from blueprints.subscription.services import store

    with app.app_context():
        rows = store.module_rows_for_entity(entity_id)
        return next((r for r in rows if r.function_code == MODULE), None)


def module_on(app, entity_id) -> bool:
    from blueprints.entity.routes.modules import _is_module_enabled

    with app.app_context():
        return bool(_is_module_enabled(entity_id, MODULE))


class _Outcome:
    """What the old session route answered, so the walk reads as before: 200 with the
    module map on success, 409 when the trial was already used."""

    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.data = repr(body).encode()

    def get_json(self):
        return self._body


def start_trial(client, entity):
    """Start the module's free trial THROUGH THE ENGINE. The session route that did this
    (``POST /entity/settings/module/<id>/start-trial``) went with Flask's Jinja module page on
    2026-10-01 - the page is minty-web's and posts to minty-billing-api - and what this file
    proves is the lifecycle underneath, which is unchanged."""
    from blueprints.subscription.services import checkout
    from models.db import Entity, User

    with client.application.test_request_context():
        with client.session_transaction() as sess:
            user_id = sess.get("_user_id")
    with client.application.app_context():
        entity_row = Entity.query.get(entity.id)
        user = User.query.get(str(user_id))
        try:
            checkout.start_module_trials(entity_row, user, [MODULE])
        except checkout.CheckoutError as exc:
            return _Outcome(exc.status, {"error": str(exc)})
        from blueprints.entity.services.modules import _enabled_state

        return _Outcome(200, {"modules": _enabled_state(entity.id)})


# ---- the walk ---------------------------------------------------------------------------------


def test_the_module_card_starts_a_trial_that_switches_the_module_on(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    assert module_on(app, entity.id) is False

    resp = start_trial(client, entity)

    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["modules"][MODULE] is True
    assert module_on(app, entity.id) is True
    row = module_row(app, entity.id)
    assert row is not None and str(row.phase) == "trial"
    assert str(row.payer_user_id) == owner.id
    assert row.trial_end is not None and row.trial_end > datetime.now(timezone.utc)
    # once per module: a second trial is refused, the card offers paid checkout instead
    again = start_trial(client, entity)
    assert again.status_code in (400, 409), again.data[:300]


def test_a_trial_that_ends_without_a_card_expires_and_lapses(shop, client, app, monkeypatch):
    owner, entity = shop
    F.login(client, owner)
    start_trial(client, entity)
    ended = module_row(app, entity.id).trial_end + timedelta(days=1)
    set_clock(monkeypatch, ended)
    from blueprints.subscription.services import checkout, consent

    with app.app_context():
        outcome = checkout.convert_or_expire_due_trials()
    assert outcome["expired"] == [{"entity_id": entity.id, "code": MODULE}]
    assert outcome["converted"] == []
    assert module_on(app, entity.id) is False
    assert str(module_row(app, entity.id).phase) == "expired"

    # the dashboard knows it as a lapsed trial the payer can restart
    with app.app_context():
        lapse = consent.lapsed_trial_for_entity(entity.id, owner.id)
    assert lapse["mode"] == "takeover", lapse  # every module the company had has lapsed
    assert [row["code"] for row in lapse["lapsed"]] == [MODULE]
    assert lapse["has_card"] is False
    # the gate: the report pages are closed (fresh sign-in - the sweep ran outside a request)
    F.login(client, owner)
    resp = client.get(f"/report/opening?entity_id={entity.id}&transaction_date=2026-09-01")
    assert resp.status_code == 302, resp.data[:300]
    assert "module_inactive" in resp.headers["Location"], resp.headers["Location"]


def _payer_with_a_card(app, owner, entity):
    """The payer's Stripe customer, a billing account on a card with this company on it,
    and the company's billing consent - what a conversion needs."""
    from blueprints.subscription.services import store
    from models.db import db

    with app.app_context():
        store.upsert_customer_mapping(owner.id, "cus_test")
        store.nominate_card_for_entity(entity.id, owner.id, "pm_card", source="chosen")
        store.record_billing_consent(entity.id, owner.id, source="module_card")
        db.session.commit()


def test_a_trial_that_ends_with_a_card_converts_to_an_exact_in_house_invoice(shop, client, app, monkeypatch):
    owner, entity = shop
    F.login(client, owner)
    start_trial(client, entity)
    _payer_with_a_card(app, owner, entity)
    stripe = install_fake_stripe(monkeypatch, pays=True)
    ended = module_row(app, entity.id).trial_end + timedelta(minutes=1)
    set_clock(monkeypatch, ended)
    from blueprints.subscription.services import checkout, store
    from models.db import SubscriptionAuditLog, SubscriptionInvoice, SubscriptionInvoiceLine

    with app.app_context():
        outcome = checkout.convert_or_expire_due_trials()
        assert outcome["converted"] == [{"entity_id": entity.id, "code": MODULE}], outcome
        assert outcome["expired"] == []

        row = module_row(app, entity.id)
        assert str(row.phase) == "active"
        assert module_on(app, entity.id) is True

        invoices = SubscriptionInvoice.query.filter_by(payer_user_id=owner.id).all()
        assert len(invoices) == 1
        invoice = invoices[0]
        lines = SubscriptionInvoiceLine.query.filter_by(invoice_id=invoice.id).all()
        assert [str(l.entity_id) for l in lines] == [entity.id]
        # cents are integers: exact, and the invoice total is the line
        assert Decimal(invoice.total) == Decimal(sum(l.amount for l in lines))
        assert 0 < invoice.total <= PRICE_CENTS
        assert invoice.status in ("paid", "open")
        # Stripe was asked for exactly that
        assert len(stripe.invoices) == 1 and stripe.items and stripe.items[0]["amount"] == lines[0].amount

        anchor, currency = store.billing_cycle_for_user(owner.id)
        assert anchor is not None and currency.upper() == "HKD"

        # a cancellation is what the audit log records (conversions are the invoice's story):
        # the module is scheduled to cancel, keeps access to the period end, and the row
        # names the module, both phases and the outcome
        from models.db import User

        cancelled = checkout.cancel_module(
            db_entity(app, entity.id), User.query.get(owner.id), MODULE, reason="moving on"
        )
        assert cancelled, cancelled
        row = module_row(app, entity.id)
        assert str(row.phase) == "scheduled_cancel"
        assert row.app_access_until is not None and row.app_access_until > ended
        audit = SubscriptionAuditLog.query.filter_by(entity_id=entity.id).all()
        assert len(audit) == 1
        (entry,) = audit
        assert str(entry.function_code) == MODULE
        assert str(entry.payer_user_id) == owner.id and str(entry.actor_user_id) == owner.id
        assert entry.action == "cancel" and str(entry.outcome) == "succeeded"
        assert (str(entry.phase_before), str(entry.phase_after)) == ("active", "scheduled_cancel")
        assert entry.cancel_reason == "moving on"


def db_entity(app, entity_id):
    from models.db import Entity

    return Entity.query.get(entity_id)


def _billing_token(app, user_id):
    import jwt

    return jwt.encode({"user_id": user_id, "exp": int(datetime.now(timezone.utc).timestamp()) + 600},
                      app.config["SECRET_KEY"], algorithm="HS256")


def test_the_payer_portal_answers_for_a_payer_with_nothing_yet(shop, client, app):
    """F5 (fixed in C7): a payer with no companies billed answered 500 - the summary read a
    per-company figure from a loop that never ran."""
    owner, entity = shop
    resp = client.get("/api/me/subscriptions", headers={"Authorization": f"Bearer {_billing_token(app, owner.id)}"})
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["entities"] == [] and body["total"] == 0
    assert body["billing"]["paid_through"] is None


def test_the_payer_portal_lists_the_converted_company(shop, client, app, monkeypatch):
    owner, entity = shop
    F.login(client, owner)
    start_trial(client, entity)
    _payer_with_a_card(app, owner, entity)
    install_fake_stripe(monkeypatch, pays=True)
    set_clock(monkeypatch, module_row(app, entity.id).trial_end + timedelta(minutes=1))
    from blueprints.subscription.services import checkout

    with app.app_context():
        assert checkout.convert_or_expire_due_trials()["converted"]

    resp = client.get("/api/me/subscriptions", headers={"Authorization": f"Bearer {_billing_token(app, owner.id)}"})
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert [e["entity_id"] if "entity_id" in e else e.get("id") for e in body["entities"]] == [entity.id]
    module = next(m for m in body["entities"][0]["modules"] if m["code"] == MODULE)
    assert module["status"] == "active"
    assert body["billing"]["paid_through"] is not None


def test_the_payer_portal_lists_the_invoice_the_conversion_raised(shop, client, app, monkeypatch):
    """``GET /api/me/invoices`` on the real tables: the conversion's invoice, paid, for the
    exact amount, with the company offered as a filter - all of it, and filtered."""
    owner, entity = shop
    F.login(client, owner)
    start_trial(client, entity)
    _payer_with_a_card(app, owner, entity)
    install_fake_stripe(monkeypatch, pays=True)
    set_clock(monkeypatch, module_row(app, entity.id).trial_end + timedelta(minutes=1))
    from blueprints.subscription.services import checkout
    from models.db import SubscriptionInvoice

    with app.app_context():
        assert checkout.convert_or_expire_due_trials()["converted"]
        invoice = SubscriptionInvoice.query.filter_by(payer_user_id=owner.id).one()
        invoice_id, total = str(invoice.id), int(invoice.total)
    headers = {"Authorization": f"Bearer {_billing_token(app, owner.id)}"}

    everything = client.get("/api/me/invoices", headers=headers)
    filtered = client.get(f"/api/me/invoices?entity={entity.id}", headers=headers)

    for resp in (everything, filtered):
        assert resp.status_code == 200, resp.data[:300]
        body = resp.get_json()
        assert body["total"] == 1
        (row,) = body["invoices"]
        assert row["id"] == invoice_id and row["amount_minor"] == total
        assert row["status"] == "paid"
        assert body["entity_options"] == [{"id": entity.id, "name": "Acme Shop"}]
        assert "Access-Control-Allow-Origin" in resp.headers
    assert filtered.get_json()["entity_id"] == entity.id


def test_the_payer_invites_an_admin_from_the_portal(shop, client, app, mail):
    """``POST /api/me/subscriptions/invite-admin``: the portal's one write to Minty's own
    tables adds a pending admin invitation and mails it."""
    owner, entity = shop
    F.login(client, owner)
    start_trial(client, entity)  # makes the owner this company's payer

    resp = client.post(
        "/api/me/subscriptions/invite-admin",
        json={"entity": entity.id, "email": "second.admin@test.com"},
        headers={"Authorization": f"Bearer {_billing_token(app, owner.id)}"},
    )

    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    assert len(mail.to("second.admin@test.com")) == 1
    with app.app_context():
        from models.db import Invitation

        (invitation,) = Invitation.query.filter_by(email="second.admin@test.com").all()
        assert str(invitation.role) == "admin" and str(invitation.status) == "pending"
        assert str(invitation.entity_id) == entity.id
