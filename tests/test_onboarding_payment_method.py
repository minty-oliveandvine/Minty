"""Card capture for onboarding Step 2.

Adding a card is OPTIONAL — it decides how the trial ends (converts to paid vs
lapses), not whether it can start. When the user does add one, the capture is a
setup-mode Stripe Checkout that saves a card and does NOTHING else; the trials
themselves are still created at finalize. These tests pin that separation (a
card-only setup must not create subscriptions), the "has a card?" flag the wizard
reads, and the endpoints' auth contract.

NOTE: imports are done INSIDE each test (see the note in the other subscription
tests) so lazy re-imports stay mutually consistent.
"""
from __future__ import annotations

# The price catalog is patched BY DOTTED PATH, not via an imported reference:
# conftest re-imports project modules mid-session, so a module object captured at
# import time is not the one the code under test ends up calling.
_CATALOG = "blueprints.subscription.services.catalog"

from datetime import datetime, timedelta, timezone

import jwt
import pytest


_schema_attached = False


@pytest.fixture()
def db_session(app):
    """A live schema for the membership lookup the routes do. Mirrors the fixture in
    tests/test_entity_create.py — the models live in the ``pettycashv2`` schema, so
    attach it in memory before create_all."""
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
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


class _FakeEntity:
    id = "e1"
    name = "Acme"


class _FakeUser:
    id = "u1"
    email = "u1@example.com"


def _plan(code="BILL", fn_id="fn_bill"):
    from blueprints.subscription.services import catalog

    return catalog.PlanView(
        entity_function_id=fn_id,
        function_code=code,
        display_name=code.title().replace("_", " "),
        amount=28000,
        currency_code="HKD",
        billing_interval="month",
        billing_interval_count=1,
        is_available_for_subscription=True,
    )


# --- the card gate ---------------------------------------------------------

def test_entity_has_payment_method_reads_stripe(monkeypatch):
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(checkout, "_customer_id_for_entity", lambda eid: "cus_1")
    monkeypatch.setattr(checkout, "customer_default_payment_method", lambda cid: "pm_1")
    assert checkout.entity_has_payment_method(_FakeEntity()) is True

    monkeypatch.setattr(checkout, "customer_default_payment_method", lambda cid: None)
    assert checkout.entity_has_payment_method(_FakeEntity()) is False


def test_entity_without_a_stripe_customer_has_no_card(monkeypatch):
    """A brand-new entity has no Stripe customer at all — that's "no card", not a crash."""
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(checkout, "_customer_id_for_entity", lambda eid: None)
    assert checkout.entity_has_payment_method(_FakeEntity()) is False


def test_trial_payment_method_is_none_without_a_card(monkeypatch):
    """The card is optional, so this reports its absence rather than raising — a
    card-free trial is a supported outcome, not an error."""
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(checkout, "customer_default_payment_method", lambda cid: None)
    assert checkout.trial_payment_method("cus_1") is None

    monkeypatch.setattr(checkout, "customer_default_payment_method", lambda cid: "pm_1")
    assert checkout.trial_payment_method("cus_1") == "pm_1"


# --- capturing the card ----------------------------------------------------

def test_setup_session_is_card_only(monkeypatch):
    """The session must NOT carry modules_to_subscribe — if it did, the paid
    completion handler would create subscriptions off a card-only capture."""
    from blueprints.subscription.services import checkout
    from blueprints.subscription.services import store

    captured = {}

    def fake_session(customer_id, success_url, cancel_url, currency, metadata=None):
        captured.update(
            customer_id=customer_id, success_url=success_url,
            cancel_url=cancel_url, currency=currency, metadata=metadata or {},
        )
        return {"url": "https://checkout.stripe.com/pay/cs_1"}

    monkeypatch.setattr(f"{_CATALOG}.available_plans", lambda: [_plan()])
    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: "cus_1")
    monkeypatch.setattr(checkout, "create_setup_checkout_session", fake_session)

    result = checkout.start_payment_method_setup(
        _FakeEntity(), _FakeUser(), "https://app/ok", "https://app/no"
    )

    assert result == {"url": "https://checkout.stripe.com/pay/cs_1"}
    assert captured["currency"] == "HKD"  # from the live plan, not hardcoded
    assert captured["metadata"]["purpose"] == "payment_method"
    assert "modules_to_subscribe" not in captured["metadata"]
    assert captured["customer_id"] == "cus_1"  # existing customer reused, not duplicated


def test_setup_session_creates_no_customer_for_a_new_payer(monkeypatch):
    """The invariant: opening the card form must not create a Stripe customer.

    A payer with no customer yet gets a session with customer_id=None, which makes
    create_setup_checkout_session use customer_creation="always" — so Stripe creates
    the customer at confirmation and an abandoned form leaves nothing behind.
    """
    from blueprints.subscription.services import checkout
    from blueprints.subscription.services import store
    from blueprints.subscription.services import stripe_client

    captured = {}

    def fake_session(customer_id, success_url, cancel_url, currency, metadata=None):
        captured.update(customer_id=customer_id, metadata=metadata or {})
        return {"url": "https://checkout.stripe.com/pay/cs_1"}

    monkeypatch.setattr(f"{_CATALOG}.available_plans", lambda: [_plan()])
    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: None)  # no mapping row
    monkeypatch.setattr(checkout, "create_setup_checkout_session", fake_session)

    # ...and Stripe has never heard of them either. Resolution asks BOTH — a missing
    # mapping row alone doesn't mean "no customer" — so this is what makes the payer
    # genuinely new rather than merely unmapped.
    searched: list = []
    monkeypatch.setattr(
        checkout, "find_customer_by_user", lambda uid: searched.append(uid) or None
    )

    # Beyond that lookup nothing may reach the Stripe SDK. The session builder and the
    # search are both faked, so any surviving call would be an unintended write — a
    # re-added customer create being the one we actually care about.
    def _no_stripe():
        raise AssertionError("opening the card form must not call Stripe directly")

    monkeypatch.setattr(stripe_client, "get_stripe", _no_stripe)

    checkout.start_payment_method_setup(
        _FakeEntity(), _FakeUser(), "https://app/ok", "https://app/no"
    )

    assert searched == ["u1"]
    assert captured["customer_id"] is None
    # The payer still has to be recoverable at completion.
    assert captured["metadata"]["user_id"] == "u1"
    assert captured["metadata"]["entity_id"] == "e1"


def test_complete_payment_method_setup_saves_card_and_creates_no_subscription(monkeypatch):
    """The whole point of the card-only path: a card is saved as the default and NOT
    a single subscription is created (those come at finalize)."""
    from blueprints.subscription.services import changes, checkout
    from blueprints.subscription.services import store

    defaults: list = []
    subs: list = []

    stamped: list = []
    mapped: list = []
    consents: list = []
    nominations: list = []

    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: None)
    monkeypatch.setattr(
        store, "record_billing_consent",
        lambda eid, uid, source: consents.append((eid, uid, source)),
    )
    # Capturing a card in a Checkout opened FOR this company also puts the company on
    # that card. Two records, one step: consent says the payer may be billed for it, the
    # nomination says on what.
    monkeypatch.setattr(
        store, "nominate_card_for_entity",
        lambda eid, uid, pm, source="chosen": nominations.append((eid, uid, pm, source)),
    )
    monkeypatch.setattr(
        checkout, "retrieve_checkout_session",
        lambda sid: {
            # Stripe created this at confirmation — it did not exist when the
            # session was opened.
            "customer": "cus_1",
            "setup_intent": {"payment_method": "pm_new"},
            "metadata": {
                "purpose": "payment_method", "entity_id": "e1", "user_id": "u1",
            },
        },
    )
    monkeypatch.setattr(
        checkout, "set_customer_identity", lambda cid, **kw: stamped.append((cid, kw))
    )
    monkeypatch.setattr(
        checkout, "_payer_identity",
        lambda uid: {"name": "Pat Payer", "description": "@patpayer",
                     "email": "pat@example.com"},
    )
    monkeypatch.setattr(
        checkout, "_seed_user_customer_mapping",
        lambda uid, cid: mapped.append((uid, cid)),
    )
    monkeypatch.setattr(
        checkout, "set_customer_default_payment_method",
        lambda cid, pm: defaults.append((cid, pm)),
    )
    # Billing is the only way money could move on this path; the card capture must not
    # reach it. (A Stripe SUBSCRIPTION can no longer be created at all — checkout
    # imports nothing that would make one — so there is nothing left to stub for that.)
    monkeypatch.setattr(
        changes, "issue_change",
        lambda *a, **kw: subs.append(kw) or {"id": "in_1", "status": "paid"},
    )

    assert checkout.complete_payment_method_setup(_FakeEntity(), "cs_1") is True
    assert defaults == [("cus_1", "pm_new")]
    assert subs == []  # nothing billed, nothing subscribed
    # The Stripe-made customer is adopted: stamped so find_customer_by_user can
    # recover it, named after the PAYER (not the entity), and mapped locally.
    assert stamped == [(
        "cus_1",
        {"metadata": {"user_id": "u1"}, "name": "Pat Payer",
         "description": "@patpayer", "email": "pat@example.com"},
    )]
    assert mapped == [("u1", "cus_1")]
    # Entering a card in THIS entity's Checkout is consent to bill it — otherwise the
    # payer would be asked to confirm again straight after typing their card.
    assert consents == [("e1", "u1", "card")]
    # ...and it is the choice of card for it. Two records, one step. Without the second,
    # the company would be authorised to be billed and billed to nothing — its renewal
    # skipped and its trial expiring at term end having been told it would convert.
    assert nominations == [("e1", "u1", "pm_new", "capture")]


def test_complete_adopts_the_payers_existing_customer_over_a_duplicate(monkeypatch):
    """Two setup sessions confirming (two tabs, a back-button replay) must not leave
    the payer billing a second customer: the pre-existing one wins and the card is
    moved onto it."""
    from blueprints.subscription.services import checkout
    from blueprints.subscription.services import store

    defaults: list = []
    attached: list = []
    stamped: list = []

    monkeypatch.setattr(store, "customer_id_for_user", lambda uid: "cus_FIRST")
    monkeypatch.setattr(store, "record_billing_consent", lambda eid, uid, source: None)
    monkeypatch.setattr(
        store, "nominate_card_for_entity", lambda eid, uid, pm, source="chosen": None
    )
    monkeypatch.setattr(
        checkout, "retrieve_checkout_session",
        lambda sid: {
            "customer": "cus_DUPLICATE",
            "setup_intent": {"payment_method": "pm_new"},
            "metadata": {"entity_id": "e1", "user_id": "u1"},
        },
    )
    monkeypatch.setattr(
        checkout, "attach_payment_method", lambda pm, cid: attached.append((pm, cid))
    )
    monkeypatch.setattr(
        checkout, "set_customer_identity", lambda cid, **kw: stamped.append((cid, kw))
    )
    monkeypatch.setattr(
        checkout, "set_customer_default_payment_method",
        lambda cid, pm: defaults.append((cid, pm)),
    )

    assert checkout.complete_payment_method_setup(_FakeEntity(), "cs_1") is True
    assert attached == [("pm_new", "cus_FIRST")]
    assert defaults == [("cus_FIRST", "pm_new")]
    # The duplicate must NOT be stamped — two customers carrying the same user_id
    # would make the find_customer_by_user fallback ambiguous.
    assert stamped == []


def test_payer_identity_names_the_customer_after_the_user_not_the_entity(monkeypatch):
    """One customer can pay for several entities, so an entity name would be wrong the
    moment a second entity is added. The username rides in ``description`` because
    first/last names are not unique."""
    import models.db as models_db
    from blueprints.subscription.services import checkout

    class _Payer:
        first_name = "Pat"
        last_name = "Payer"
        username = "patpayer"
        email = "pat@example.com"

    class _UserModel:
        query = type("_Q", (), {"get": staticmethod(lambda uid: _Payer())})()

    monkeypatch.setattr(models_db, "User", _UserModel)

    assert checkout._payer_identity("u1") == {
        "name": "Pat Payer",
        "description": "@patpayer",
        "email": "pat@example.com",
    }


def test_payer_identity_omits_a_missing_email_rather_than_blanking_it(monkeypatch):
    """``User.email`` is nullable. Sending email=None would wipe the address Stripe
    collected at Checkout, which is the only one we'd have — so it's omitted."""
    import models.db as models_db
    from blueprints.subscription.services import checkout

    class _Payer:
        first_name = "Pat"
        last_name = "Payer"
        username = "patpayer"
        email = None

    class _UserModel:
        query = type("_Q", (), {"get": staticmethod(lambda uid: _Payer())})()

    monkeypatch.setattr(models_db, "User", _UserModel)

    assert "email" not in checkout._payer_identity("u1")


def test_payer_identity_is_empty_when_the_user_is_gone(monkeypatch):
    """A missing user must not block the adoption — the user_id stamp still has to go
    on, since being resolvable matters more than having a display name."""
    import models.db as models_db
    from blueprints.subscription.services import checkout

    class _UserModel:
        query = type("_Q", (), {"get": staticmethod(lambda uid: None)})()

    monkeypatch.setattr(models_db, "User", _UserModel)

    assert checkout._payer_identity("u_gone") == {}


def test_complete_rejects_another_entitys_session(monkeypatch):
    """A crafted session id from another entity must not save a card here.

    The binding is the session's ``metadata.entity_id`` (stamped when we opened it),
    not the customer — on a payer's first card there is no customer to compare against.
    """
    from blueprints.subscription.services import checkout

    monkeypatch.setattr(
        checkout, "retrieve_checkout_session",
        lambda sid: {
            "customer": "cus_OTHER",
            "setup_intent": {"payment_method": "pm_x"},
            "metadata": {"entity_id": "e_SOMEONE_ELSE", "user_id": "u9"},
        },
    )

    with pytest.raises(checkout.CheckoutError) as exc:
        checkout.complete_payment_method_setup(_FakeEntity(), "cs_1")
    assert exc.value.status == 404


# --- the settings-page nudge -----------------------------------------------

def _seed_catalog(db):
    import uuid

    from models.db import EntityFunction

    rows = {}
    for code, name in (("PETTY_CASH", "Petty Cash"), ("BILL", "Payment Request")):
        row = EntityFunction(
            id=str(uuid.uuid4()), function_code=code, function_name=name,
            description=f"{name} module", is_active=True,
        )
        db.session.add(row)
        rows[code] = row
    db.session.commit()
    return rows


@pytest.mark.parametrize(
    "card,consent,expected_nudge,expected_consent_only",
    [
        (None, False, True, False),
        ("pm_1", False, True, True),
        ("pm_1", True, False, False),
    ],
    ids=[
        "no card -> nudge to add one",
        "card but entity not authorised -> nudge to confirm billing",
        "card + consent -> converts, no nudge",
    ],
)
def test_trialing_module_nudges_unless_the_trial_will_actually_convert(
    db_session, monkeypatch, card, consent, expected_nudge, expected_consent_only
):
    """A trial that won't convert lapses when it ends, so its settings card must warn.

    Two distinct reasons it won't convert, and the fix differs: no card at all, or a
    card the payer has never authorised for THIS entity (their card is shared across
    every entity they pay for, so it doesn't authorise this one on its own).
    """
    from blueprints.entity.services import modules
    from blueprints.subscription.services import clock
    from blueprints.subscription.services import store

    _seed_catalog(db_session)
    now = clock.now()

    monkeypatch.setattr(store, "has_billing_consent", lambda eid, user_id=None: consent)

    # A running app-level trial, as a module ROW. The card used to read this from a
    # live Stripe subscription view; a trial has no Stripe object at all, which is why
    # the two sources had to be merged and could disagree.
    class _Row:
        entity_id = "e1"
        function_code = "BILL"
        payer_user_id = "u1"
        phase = "trial"
        trial_end = now + timedelta(days=20)
        app_access_until = now + timedelta(days=20)
        first_billed_at = None

    monkeypatch.setattr(modules, "_entity_customer_id", lambda eid: "cus_1")
    monkeypatch.setattr(store, "module_rows_for_entity", lambda eid: [_Row()])
    monkeypatch.setattr(store, "paid_through_for_user", lambda uid: None)
    # Same value per company: these cases describe an account with one card.
    monkeypatch.setattr(store, "paid_through_for_entity", lambda _e: None)
    monkeypatch.setattr(f"{_CATALOG}.available_plans", lambda: [_plan()])
    # get_module_cards imports this lazily from stripe_client — patch it at the source.
    monkeypatch.setattr(
        "blueprints.subscription.services.stripe_client.customer_default_payment_method",
        lambda cid: card,
    )

    cards = {c["code"]: c for c in modules.get_module_cards("e1")}

    assert cards["BILL"]["subscription_status"] == "trialing"
    assert cards["BILL"]["needs_card"] is expected_nudge
    # Which banner to show: "add a payment method" vs "confirm billing for this company".
    assert cards["BILL"]["needs_consent_only"] is expected_consent_only
    # A module with no subscription at all is never nudged — there's no trial to save.
    assert cards["PETTY_CASH"]["needs_card"] is False


# --- the endpoints the wizard calls ----------------------------------------

def _token(app, user_id="u1"):
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


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/onboarding/payment-method?entity_id=e1"),
        ("post", "/api/onboarding/payment-method/setup"),
        ("post", "/api/onboarding/payment-method/complete"),
    ],
)
def test_payment_method_endpoints_require_a_token(app, method, path):
    client = app.test_client()
    res = getattr(client, method)(path)
    assert res.status_code == 401


def test_payment_method_status_endpoint_requires_membership(app, db_session):
    """A token for a user who isn't a member of the entity gets 403, not the answer."""
    client = app.test_client()
    res = client.get(
        "/api/onboarding/payment-method?entity_id=not-mine",
        headers={"Authorization": f"Bearer {_token(app)}"},
    )
    assert res.status_code == 403

# --- "Buy now": the payer's cards, and consent to bill this entity ----------
#
# Step 2's Buy now shows the payer their saved cards, takes one (or a new one), and
# records consent to bill THIS entity. It charges nothing — the 30-day trial still runs
# its term; consent is what makes it convert at the end instead of lapsing.


def _entity_with_member(db, user_id="u1"):
    """A real entity the bearer is a member of, so the routes' membership check passes."""
    import uuid as _uuid

    from models.db import Entity, User, UserEntity

    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        username=f"{user_id}@example.com",
        first_name="Pay",
        last_name="Er",
        password="x",
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    entity = Entity(id=str(_uuid.uuid4()), name="Acme")
    db.session.add_all([user, entity])
    db.session.flush()
    db.session.add(UserEntity(user_id=user.id, entity_id=entity.id, role="admin"))
    db.session.commit()
    # The ID, not the instance: the request the test then makes closes the session out
    # from under it, and reading .id afterwards raises DetachedInstanceError.
    return entity.id


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/onboarding/billing/payment-methods"),
        ("post", "/api/onboarding/billing/payment-methods/setup-intent"),
        ("post", "/api/onboarding/billing/payment-methods/confirm"),
        ("post", "/api/onboarding/billing/payment-methods/default"),
        ("post", "/api/onboarding/billing/authorize"),
    ],
)
def test_buy_now_endpoints_require_a_token(app, method, path):
    client = app.test_client()
    assert getattr(client, method)(path).status_code == 401


def test_buy_now_card_routes_answer_the_onboarding_origin(app, monkeypatch):
    """The whole reason these exist beside the payer portal's identical routes.

    The portal's own ``/api/me/billing/payment-methods`` names FRONTEND_APP_URL in its
    ``Access-Control-Allow-Origin``, so a browser on the onboarding origin is blocked
    before the bearer token is ever read. If this header ever comes back as the billing
    frontend, the Buy now sheet silently stops loading cards.
    """
    from blueprints.subscription.services import payment_methods

    monkeypatch.setenv("ONBOARDING_APP_URL", "https://onboard.example.com")
    monkeypatch.setattr(
        payment_methods,
        "list_for_user",
        lambda user_id: {"has_account": True, "default_id": "pm_1", "methods": [], "total": 0},
    )

    client = app.test_client()
    res = client.get(
        "/api/onboarding/billing/payment-methods",
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 200
    assert res.headers["Access-Control-Allow-Origin"] == "https://onboard.example.com"
    assert res.get_json()["default_id"] == "pm_1"


def test_buy_now_card_route_reports_the_service_error_verbatim(app, monkeypatch):
    """``PaymentMethodError`` messages are written for the payer, so they're passed through
    with their own status rather than flattened to a generic 500."""
    from blueprints.subscription.services import payment_methods

    def _boom(user_id):
        raise payment_methods.PaymentMethodError(
            "Card payments aren't configured on this environment.", status=503
        )

    monkeypatch.setattr(payment_methods, "start_setup", _boom)

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/payment-methods/setup-intent",
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 503
    assert "aren't configured" in res.get_json()["error"]


def test_confirm_makes_the_new_card_the_default_when_asked(app, monkeypatch):
    """A card added inside Buy now is the one the payer was shown, so it must be the one
    that gets charged — the flag reaches the service rather than being dropped."""
    from blueprints.subscription.services import payment_methods

    seen = {}

    def _confirm(user_id, setup_intent, *, make_default=False):
        seen.update(user_id=user_id, setup_intent=setup_intent, make_default=make_default)
        return {"has_account": True, "default_id": "pm_new", "methods": [], "total": 1}

    monkeypatch.setattr(payment_methods, "confirm_setup", _confirm)

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/payment-methods/confirm",
        json={"setup_intent": "seti_1", "make_default": True},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 200
    assert seen == {"user_id": "u1", "setup_intent": "seti_1", "make_default": True}


def test_authorize_records_consent_for_this_entity_and_charges_nothing(
    app, db_session, monkeypatch
):
    """Buy now's actual effect: a consent row, and no Stripe call of any kind.

    Nothing here may reach Stripe — the trial has paid time left, so the right outcome is
    "convert at term end", not "charge now". A subscription created here would bill the
    payer on the day they agreed to be billed *later*.
    """
    from blueprints.subscription.services import checkout, store

    entity_id = _entity_with_member(db_session)
    def _never(*a, **k):
        raise AssertionError("Buy now must not subscribe or charge anything")

    monkeypatch.setattr(checkout, "start_modules_checkout", _never)
    monkeypatch.setattr(checkout, "_create_paid_subscriptions", _never)

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/authorize",
        json={"entity_id": entity_id},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 200
    assert res.get_json() == {"has_billing_consent": True}
    assert store.has_billing_consent(entity_id, "u1") is True
    # Per (entity, PAYER) — someone else's agreement is not this payer's.
    assert store.has_billing_consent(entity_id, "u2") is False


def test_authorize_nominates_the_card_it_was_given(app, db_session, monkeypatch):
    """Buy now names the card rather than leaving Minty to infer one.

    The sheet used to make every card it captured the ACCOUNT DEFAULT and rely on
    ``_ensure_nominated`` finding it again from there — which re-pointed what every other
    company that payer owns would be offered, as a side effect of confirming one. Sending
    the id says which card THIS company goes on and moves nothing else.
    """
    from blueprints.subscription.services import payment_methods

    entity_id = _entity_with_member(db_session)
    seen = {}

    def _set_for_entity(user_id, ent, pm_id, *, source="chosen"):
        seen.update(user_id=user_id, entity_id=str(ent), payment_method=pm_id)
        return {"methods": [], "nominated_id": pm_id}

    monkeypatch.setattr(payment_methods, "set_for_entity", _set_for_entity)

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/authorize",
        json={"entity_id": entity_id, "payment_method": "pm_chosen"},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 200
    assert seen == {
        "user_id": "u1",
        "entity_id": str(entity_id),
        "payment_method": "pm_chosen",
    }


def test_authorize_nominates_before_it_records_consent(app, db_session, monkeypatch):
    """Order, not just presence. Consent recorded while the company still points at a
    different card authorises a charge the payer was never shown, so a nomination that
    fails must take the consent down with it."""
    from blueprints.subscription.services import checkout, payment_methods, store

    entity_id = _entity_with_member(db_session)

    def _refuse(*a, **k):
        raise payment_methods.PaymentMethodError(
            "That payment method couldn't be found.", status=404
        )

    monkeypatch.setattr(payment_methods, "set_for_entity", _refuse)
    monkeypatch.setattr(
        checkout,
        "authorize_entity_billing",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("consent must not be recorded when the card is refused")
        ),
    )

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/authorize",
        json={"entity_id": entity_id, "payment_method": "pm_someone_elses"},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 404
    assert store.has_billing_consent(entity_id, "u1") is False


def test_authorize_without_a_card_still_works(app, db_session):
    """The id is OPTIONAL. An older client that does not send one still gets consent, and
    ``_ensure_nominated`` backstops the card the way it always did."""
    entity_id = _entity_with_member(db_session)
    from blueprints.subscription.services import store

    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/authorize",
        json={"entity_id": entity_id},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )

    assert res.status_code == 200
    assert store.has_billing_consent(entity_id, "u1") is True


def test_authorize_is_idempotent(app, db_session):
    """A double-click, or a sheet re-opened before the status read caught up."""
    from blueprints.subscription.models.entity_billing_consent import (
        EntityBillingConsent,
    )

    entity_id = _entity_with_member(db_session)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {_token(app)}"}

    for _ in range(2):
        res = client.post(
            "/api/onboarding/billing/authorize",
            json={"entity_id": entity_id},
            headers=headers,
        )
        assert res.status_code == 200

    assert (
        EntityBillingConsent.query.filter_by(entity_id=entity_id, user_id="u1").count()
        == 1
    )


def test_authorize_requires_membership(app, db_session):
    """Consent is given about an entity you belong to. A stranger's token gets 403."""
    client = app.test_client()
    res = client.post(
        "/api/onboarding/billing/authorize",
        json={"entity_id": "not-mine"},
        headers={"Authorization": f"Bearer {_token(app)}"},
    )
    assert res.status_code == 403


def test_status_reports_card_and_consent_separately(app, db_session, monkeypatch):
    """The two facts Step 2 reads, and why they are two.

    The card belongs to the PAYER and is shared by every entity they pay for, so it says
    nothing about this entity. Only consent does. Collapsing them would offer Buy now to
    a payer who has already bought, or hide it from one who hasn't.
    """
    from blueprints.subscription.services import checkout, store

    entity_id = _entity_with_member(db_session)
    monkeypatch.setattr(checkout, "entity_has_payment_method", lambda e: True)

    client = app.test_client()
    headers = {"Authorization": f"Bearer {_token(app)}"}

    before = client.get(
        f"/api/onboarding/payment-method?entity_id={entity_id}", headers=headers
    ).get_json()
    assert before == {"has_payment_method": True, "has_billing_consent": False}

    store.record_billing_consent(entity_id, "u1", "confirmed")

    after = client.get(
        f"/api/onboarding/payment-method?entity_id={entity_id}", headers=headers
    ).get_json()
    assert after == {"has_payment_method": True, "has_billing_consent": True}


def test_status_still_reports_consent_when_stripe_is_down(app, db_session, monkeypatch):
    """An unreachable Stripe must not be able to answer "no consent".

    The card read is allowed to fail closed (report no card); the consent read is local
    and must not be dragged down with it, or a payer who has already bought is offered
    Buy now again for something they already agreed to.
    """
    from blueprints.subscription.services import checkout, store

    entity_id = _entity_with_member(db_session)
    store.record_billing_consent(entity_id, "u1", "confirmed")

    def _down(_entity):
        raise RuntimeError("stripe is down")

    monkeypatch.setattr(checkout, "entity_has_payment_method", _down)

    client = app.test_client()
    body = client.get(
        f"/api/onboarding/payment-method?entity_id={entity_id}",
        headers={"Authorization": f"Bearer {_token(app)}"},
    ).get_json()

    assert body == {"has_payment_method": False, "has_billing_consent": True}
