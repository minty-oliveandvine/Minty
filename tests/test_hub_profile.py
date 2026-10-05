"""My Profile as minty-web reads and saves it (``GET``/``PATCH /api/me/profile``), and the one
route every "open my profile" link goes through (``GET /profile``).

The save rules are billing-backend's ``update_user_profile``, ported (``services/profile.py``):
the error copy word for word, the username following the email only when it WAS the email.
The superuser refusal of that copy is deliberately not ported - it guards writes inside a
company the superuser is not a member of, and a person's own name is in no company.

Imports of project modules happen inside tests (the conftest ``app`` fixture re-imports the
blueprints).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"
PAYMENTS = "http://payments.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")
    monkeypatch.setenv("PAYMENT_REQUEST_WEB_URL", PAYMENTS)


@pytest.fixture
def people(app, db):
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        olive = F.make_user(db, "olive@test.com", first_name="Olive", last_name="Vine")
        other = F.make_user(db, "other@test.com")
        staff = F.make_user(db, "staff@test.com", system_role="superadmin", first_name="", last_name="")
        shop = F.make_entity(db, olive, name="Olive Shop", role="shop_manager",
                             modules=("PETTY_CASH", "PAYMENT_REQUEST"), currency=currency, country=country)
        theirs = F.make_entity(db, other, name="Not Hers Ltd", currency=currency, country=country)
    return {"olive": olive, "other": other, "staff": staff, "shop": shop, "theirs": theirs}


def _auth(app, user_id) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "entity_id": "", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
        app.config["SECRET_KEY"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}", "Origin": HUB}


def _user_row(app, user_id):
    from models.db import User

    with app.app_context():
        row = User.query.filter(User.id == user_id).first()
        return {"email": row.email, "username": row.username,
                "first_name": row.first_name, "last_name": row.last_name, "user_phone": row.user_phone}


# --- reading ---------------------------------------------------------------------------


def test_the_person_alone_when_opened_from_the_entity_list(app, client, people, hub):
    resp = client.get("/api/me/profile", headers=_auth(app, people["olive"].id))

    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == HUB
    assert resp.get_json() == {
        "user": {
            "id": people["olive"].id,
            "first_name": "Olive",
            "last_name": "Vine",
            "name": "Olive Vine",
            "initials": "OV",
            "email": "olive@test.com",
        },
        "entity": None,
    }


def test_the_company_it_was_opened_from_with_the_persons_role(app, client, people, hub):
    shop = people["shop"]
    body = client.get(f"/api/me/profile?entity={shop.id}", headers=_auth(app, people["olive"].id)).get_json()

    assert body["entity"] == {
        "id": shop.id,
        "name": "Olive Shop",
        "role": "shop_manager",
        "role_label": "Shop Manager",
        "modules": ["PAYMENT_REQUEST", "PETTY_CASH"],
    }


@pytest.mark.parametrize("which", ["not a member", "no such company", "not an id"])
def test_a_company_the_person_may_not_see_is_refused(app, client, people, hub, which):
    entity = {"not a member": people["theirs"].id, "no such company": F.new_id(), "not an id": "abc"}[which]
    resp = client.get(f"/api/me/profile?entity={entity}", headers=_auth(app, people["olive"].id))

    assert resp.status_code == 403
    assert resp.get_json() == {"error": "You don't have access to that company."}
    assert resp.headers["Access-Control-Allow-Origin"] == HUB


def test_a_superuser_sees_any_company_without_a_role(app, client, people, hub):
    body = client.get(
        f"/api/me/profile?entity={people['theirs'].id}", headers=_auth(app, people["staff"].id)
    ).get_json()

    assert body["entity"]["name"] == "Not Hers Ltd"
    assert body["entity"]["role"] is None and body["entity"]["role_label"] is None
    # no name at all: the email stands in, and the avatar says so
    assert body["user"]["name"] == "staff@test.com"
    assert body["user"]["initials"] == "?"


def test_no_token_no_profile(client, people, hub):
    resp = client.get("/api/me/profile", headers={"Origin": HUB})
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


# --- saving ----------------------------------------------------------------------------


def _patch(client, app, user_id, body, path="/api/me/profile"):
    return client.patch(path, json=body, headers=_auth(app, user_id))


def test_names_are_saved_trimmed_and_the_answer_is_the_fresh_profile(app, client, people, hub):
    shop = people["shop"]
    resp = _patch(client, app, people["olive"].id, {"first_name": "  Olivia ", "last_name": "Vine "},
                  path=f"/api/me/profile?entity={shop.id}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["name"] == "Olivia Vine" and body["user"]["initials"] == "OV"
    assert body["entity"]["role_label"] == "Shop Manager"
    row = _user_row(app, people["olive"].id)
    assert (row["first_name"], row["last_name"]) == ("Olivia", "Vine")


def test_the_username_follows_the_email_when_it_was_the_email(app, client, people, hub):
    resp = _patch(client, app, people["olive"].id, {"email": " olive.new@test.com "})

    assert resp.status_code == 200
    assert _user_row(app, people["olive"].id)["email"] == "olive.new@test.com"
    # sign-in reads username - it moved with the address, or the next login would fail
    assert _user_row(app, people["olive"].id)["username"] == "olive.new@test.com"


def test_a_username_chosen_separately_stays(app, client, people, hub, db):
    from models.db import User

    with app.app_context():
        User.query.filter(User.id == people["olive"].id).first().username = "olive-handle"
        db.session.commit()
    _patch(client, app, people["olive"].id, {"email": "olive.new@test.com"})

    row = _user_row(app, people["olive"].id)
    assert (row["email"], row["username"]) == ("olive.new@test.com", "olive-handle")


@pytest.mark.parametrize(
    "email, sentence",
    [
        ("  ", "I'll need an email address here."),
        ("olive at test", "That doesn't look like an email address."),
        ("two@@test.com", "That doesn't look like an email address."),
        ("OTHER@test.com", "That email address is already in use."),
        # English only (blueprints/shared/email_rules.py): Korean before the "@", an
        # international domain after it
        ("홍길동@example.com", "Email can only contain English letters, numbers and symbols."),
        ("olive@회사.com", "Email can only contain English letters, numbers and symbols."),
    ],
)
def test_an_email_that_cannot_be_used_is_refused_in_words(app, client, people, hub, email, sentence):
    resp = _patch(client, app, people["olive"].id, {"email": email})

    assert resp.status_code == 422
    assert resp.get_json() == {"error": sentence}
    assert _user_row(app, people["olive"].id)["email"] == "olive@test.com"


def test_an_ordinary_address_outside_the_common_shapes_is_saved(app, client, people, hub):
    resp = _patch(client, app, people["olive"].id, {"email": "a+b@sub.domain.museum"})

    assert resp.status_code == 200
    assert _user_row(app, people["olive"].id)["email"] == "a+b@sub.domain.museum"


def test_an_address_taken_as_somebody_elses_username_is_refused(app, client, people, hub, db):
    from models.db import User

    with app.app_context():
        User.query.filter(User.id == people["other"].id).first().username = "taken@test.com"
        db.session.commit()
    resp = _patch(client, app, people["olive"].id, {"email": "taken@test.com"})
    assert resp.status_code == 422
    assert resp.get_json() == {"error": "That email address is already in use."}


@pytest.mark.parametrize("body", [{}, {"user_phone": "123"}, {"first_name": 7}, ["first_name"]])
def test_nothing_it_can_save_is_a_400(app, client, people, hub, body):
    resp = _patch(client, app, people["olive"].id, body)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "That didn't quite save. Mind trying again?"}


def test_the_write_needs_no_csrf_token_it_is_bearer_only(app):
    csrf = app.extensions["csrf"]
    assert "blueprints.user_management.routes.me_api.my_profile_api" in csrf._exempt_views


def test_the_session_route_saves_through_the_same_service(app, client, people, hub):
    F.login(client, people["olive"])
    resp = client.patch("/minty/api/users/me", json={"first_name": " Liv ", "user_phone": "+852 1234"})

    assert resp.status_code == 200
    row = _user_row(app, people["olive"].id)
    assert (row["first_name"], row["user_phone"]) == ("Liv", "+852 1234")
    assert client.patch("/minty/api/users/me", json={}).status_code == 400


# --- /profile: which profile opens -----------------------------------------------------


def _landing(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    return parts, parse_qs(parts.query)


def test_the_profile_is_minty_webs(app, client, people, hub):
    F.login(client, people["olive"])

    parts, query = _landing(client.get("/profile"))
    assert (parts.netloc, parts.path) == ("hub.minty.test", "/landing")
    assert query["next"] == ["/profile"]
    assert jwt.decode(query["token"][0], app.config["SECRET_KEY"], algorithms=["HS256"])["entity_id"] == ""

    shop = people["shop"]
    # an old link's ?from=bills is ignored (2026-10-05): the profile's Back goes where the
    # person came from, so nothing is carried
    _, query = _landing(client.get(f"/profile?entity_id={shop.id}&from=bills"))
    assert query["next"] == ["/profile"]
    assert query["entity_id"] == [shop.id]
    claims = jwt.decode(query["token"][0], app.config["SECRET_KEY"], algorithms=["HS256"])
    assert claims["entity_id"] == shop.id and claims["role"] == "shop_manager"


def test_the_profile_is_minty_webs_with_or_without_a_company(app, client, people, hub, monkeypatch):
    """billing-frontend's profile page was deleted on 2026-10-01 (that app holds only
    Payment Request): the profile is minty-web's, scoped to a company when one is named."""
    F.login(client, people["olive"])

    parts, query = _landing(client.get("/profile"))
    assert (parts.netloc, parts.path) == ("hub.minty.test", "/landing")
    assert query["next"] == ["/profile"]

    shop = people["shop"]
    _, query = _landing(client.get(f"/profile?entity_id={shop.id}"))
    assert query["next"] == ["/profile"] and query["entity_id"] == [shop.id]


def test_a_company_the_person_is_not_in_opens_no_profile(app, client, people, hub, monkeypatch):
    F.login(client, people["olive"])

    resp = client.get(f"/profile?entity_id={people['theirs'].id}")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/entity")
    with client.session_transaction() as session:
        # the session serialises each flash as a [category, message] list
        flashes = [tuple(f) for f in session["_flashes"]]
    assert ("danger", "Hmm, it looks like you don't have permission to look there.") in flashes


def test_the_avatar_links_go_through_it_and_carry_no_token(app, people):
    from flask import render_template_string

    shop = people["shop"]
    cases = {
        "{{ bills_app_profile_unscoped_url() }}": "/profile",
        "{{ bills_app_profile_url(eid) }}": f"/profile?entity_id={shop.id}",
        "{{ bills_app_profile_url('') }}": "/entity",
    }
    with app.test_request_context():
        for template, expected in cases.items():
            assert render_template_string(template, eid=shop.id) == expected, template
