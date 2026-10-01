"""Email addresses are English only (printable ASCII) - the server half of the rule
(``blueprints/shared/email_rules.py``; the browser half is ``static/js/email_input.js``).

Every path that takes a typed address refuses Korean before the "@" and an international
domain after it, in the hint's words, and still takes an ordinary address such as
``a+b@sub.domain.museum``. My Profile's refusal is in ``test_hub_profile.py`` with its other
email refusals (422, that endpoint's status for an address it will not save).

Imports of project modules happen inside tests (the conftest ``app`` fixture re-imports the
blueprints).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

HINT = "Email can only contain English letters, numbers and symbols."
NOT_ENGLISH = ["홍길동@example.com", "user@회사.com"]
ENGLISH = "a+b@sub.domain.museum"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


@pytest.fixture
def world(app, db):
    """A currency, its country, an admin and the company they run."""
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return {"owner": owner, "entity": entity}


def onboarding_bearer(app, user_id):
    payload = {"user_id": str(user_id), "scope": "onboarding",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
               "iat": datetime.now(timezone.utc)}
    return {"Authorization": "Bearer " + jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")}


def invitations_for(app, address):
    from blueprints.invitation.models.invitation import Invitation

    with app.app_context():
        return Invitation.query.filter_by(email=address).count()


# ---- the rule ---------------------------------------------------------------------------------


def test_the_rule_is_printable_ascii_only(app):
    from blueprints.shared.email_rules import EMAIL_ASCII_MESSAGE, is_ascii_email

    assert EMAIL_ASCII_MESSAGE == HINT
    assert is_ascii_email(ENGLISH)
    assert is_ascii_email("  padded@test.com  ")
    assert is_ascii_email("") and is_ascii_email(None), "empty is each caller's own 'required' answer"
    for address in NOT_ENGLISH + ["café@test.com", "a b@test.com", "tab\t@test.com", "ｆｕｌｌ@test.com"]:
        assert not is_ascii_email(address), address


# ---- inviting someone (Settings -> Users, and the onboarding wizard's step) --------------------


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_an_invite_to_a_non_english_address_is_a_400(app, client, world, mail, address):
    F.login(client, world["owner"])
    resp = client.post("/minty/api/invitation/send", json={
        "entity_id": world["entity"].id, "email": address, "role": "cashier",
    })

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error", "message": HINT}
    assert invitations_for(app, address.lower()) == 0
    assert mail.messages == []


def test_an_invite_to_an_ordinary_address_goes_out(app, client, world, mail):
    F.login(client, world["owner"])
    resp = client.post("/minty/api/invitation/send", json={
        "entity_id": world["entity"].id, "email": ENGLISH, "role": "cashier",
    })

    assert resp.status_code == 201, resp.data[:300]
    assert resp.get_json()["invitation"]["email"] == ENGLISH
    assert invitations_for(app, ENGLISH) == 1


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_the_onboarding_invite_refuses_a_non_english_address(app, client, world, mail, address):
    resp = client.post("/api/onboarding/invite", json={
        "entity_id": world["entity"].id, "email": address, "role": "cashier",
    }, headers=onboarding_bearer(app, world["owner"].id))

    assert resp.status_code == 400
    assert resp.get_json() == {"error": HINT}
    assert invitations_for(app, address.lower()) == 0


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_the_payer_portal_invite_refuses_a_non_english_address(app, address):
    from blueprints.subscription.services import portal

    with app.app_context():
        # refused before the entity or the payer is even looked up
        assert portal.invite_admin_to_entity(F.new_id(), F.new_id(), address) == (False, HINT)


# ---- the sign-in / sign-up code ----------------------------------------------------------------


@pytest.mark.parametrize("mode", ["login", None])
@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_no_code_is_sent_to_a_non_english_address(app, client, db, mail, address, mode):
    """Login mode included: its usual unknown-address answer (404 "Please sign up first")
    would send the person to a sign-up that refuses the same address."""
    from blueprints.auth.models.email_otp import EmailOtp

    body = {"email": address, **({"mode": mode} if mode else {})}
    resp = client.post("/auth/email/request-code", json=body)

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error", "message": HINT}
    with app.app_context():
        assert EmailOtp.query.count() == 0
    assert mail.messages == []


def test_the_service_refuses_it_too(app, db, mail):
    from blueprints.auth.services.email_auth import request_email_otp

    with app.app_context():
        assert request_email_otp("홍길동@example.com") == (False, HINT)


def test_a_code_goes_to_an_ordinary_address(app, client, db, mail):
    resp = client.post("/auth/email/request-code", json={"email": ENGLISH})

    assert resp.status_code == 200, resp.data[:300]
    assert len(mail.messages) == 1


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_the_register_form_reports_it_against_the_email_field(app, client, db, address):
    """``Email()`` (email_validator) takes SMTPUTF8 and IDN addresses; the form's own
    validator is what refuses them."""
    resp = client.post("/validate_register",
                       json={"first_name": "New", "last_name": "User", "email": address})

    assert resp.get_json()["errors"].get("email") == [HINT]


# ---- a company's business email ----------------------------------------------------------------


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_onboarding_create_refuses_a_non_english_business_email(app, client, world, address):
    from models.db import Entity

    resp = client.post("/api/onboarding/create", json={
        "entity_name": "Wizard Co", "country_code": "HK", "currency_code": "HKD",
        "business_email": address,
    }, headers=onboarding_bearer(app, world["owner"].id))

    assert resp.status_code == 400
    assert resp.get_json() == {"error": HINT}
    with app.app_context():
        assert Entity.query.filter_by(name="Wizard Co").count() == 0, "refused before it is created"


@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_onboarding_edit_refuses_a_non_english_business_email(app, client, world, address):
    from models.db import Entity, db as _db

    entity = world["entity"]
    resp = client.put(f"/api/onboarding/entity/{entity.id}", json={"business_email": address},
                      headers=onboarding_bearer(app, world["owner"].id))

    assert resp.status_code == 400
    assert resp.get_json() == {"error": HINT}
    with app.app_context():
        assert _db.session.get(Entity, entity.id).business_email is None


def test_an_ordinary_business_email_is_saved(app, client, world):
    from models.db import Entity, db as _db

    entity = world["entity"]
    resp = client.put(f"/api/onboarding/entity/{entity.id}", json={"business_email": ENGLISH},
                      headers=onboarding_bearer(app, world["owner"].id))

    assert resp.status_code == 200, resp.data[:300]
    with app.app_context():
        assert _db.session.get(Entity, entity.id).business_email == ENGLISH


def test_the_entity_create_form_refuses_it_and_shows_why(app, client, world):
    from models.db import Entity

    F.login(client, world["owner"])
    resp = client.post("/entity/create", data={
        "entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
        "contact_phone": "91234567", "business_email": "홍길동@example.com",
    }, follow_redirects=False)

    assert resp.status_code == 200, "the form again, not a redirect to success"
    page = resp.get_data(as_text=True)
    assert HINT in page
    # the field the page renders is the English-only one (static/js/email_input.js)
    assert 'id="businessEmail"' in page and 'data-email-ascii=' in page and 'type="email"' not in page
    with app.app_context():
        assert Entity.query.filter_by(name="Corner Shop").count() == 0


def test_the_entity_create_form_refuses_a_malformed_address_instead_of_saving_null(app, client, world):
    # type="email" used to stop this in the browser; with the field now type="text", the form's
    # own shape check must, or entity_create would save the entity with business_email NULL.
    from models.db import Entity

    F.login(client, world["owner"])
    resp = client.post("/entity/create", data={
        "entity_name": "Corner Shop", "country_code": "HK", "currency_code": "HKD",
        "contact_phone": "91234567", "business_email": "not-an-address",
    }, follow_redirects=False)

    assert resp.status_code == 200, "the form again, not a redirect to success"
    assert "Please enter a valid business email." in resp.get_data(as_text=True)
    with app.app_context():
        assert Entity.query.filter_by(name="Corner Shop").count() == 0


# ---- a billing account's email (onboarding) ----------------------------------------------------


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/onboarding/billing/payment-methods/confirm", {"setup_intent": "seti_x"}),
        ("/api/onboarding/billing/accounts", {"payment_method": "pm_x"}),
    ],
)
@pytest.mark.parametrize("address", NOT_ENGLISH)
def test_a_non_english_billing_email_is_refused_before_stripe_is_asked(
    app, client, world, monkeypatch, path, body, address
):
    def _no_stripe(*_a, **_k):
        raise AssertionError("Stripe was reached with a refused billing email")

    monkeypatch.setattr("blueprints.entity.routes.create._billing_call", _no_stripe)
    resp = client.post(path, json={**body, "billing_email": address},
                       headers=onboarding_bearer(app, world["owner"].id))

    assert resp.status_code == 400
    assert resp.get_json() == {"error": HINT}


# ---- the pages carry the English-only field ----------------------------------------------------


def test_the_sign_up_and_sign_in_pages_use_the_english_only_field(client):
    for path in ("/register", "/", "/login"):
        page = client.get(path).get_data(as_text=True)
        assert "js/email_input.js" in page, path
        assert "data-email-ascii=" in page, path
        assert 'type="email"' not in page, path
