"""The door into Petty Cash's bearer API (``blueprints/petty_cash_api``): what minty-petty-cash-web
reads and writes a company's petty cash through, at ``/api/petty-cash/v1/companies/<id>/...``.

Unlike the old report routes' module gate (``report.routes.module_guard``, which lets a request
through when it cannot find the company or the check itself throws), this door FAILS CLOSED: no
valid module token, no approved person, no membership, a company still in onboarding or Petty Cash
switched off - each is refused, and anything that throws is a 500, never a pass. Every refusal
carries the CORS headers, so the app sees a 401 it can act on rather than a CORS failure.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

WEB = "http://petty-cash.minty.test"
REGEX = (
    r"^https://pr-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-(?:my|payment-request|onboarding|petty-cash)"
    r"\.dailyminty\.com$"
)
BASE = "/api/petty-cash/v1/companies"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def web(monkeypatch):
    monkeypatch.setenv("PETTY_CASH_WEB_URL", WEB + "/")


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Tan")
        entity = F.make_entity(db, owner, name="Vine Café Central", currency=currency, country=country)
        stranger = F.make_user(db, "stranger@test.com")
    return {"owner": owner, "entity": entity, "stranger": stranger}


def _get(client, app, entity_id, user_id, **kw):
    return client.get(f"{BASE}/{entity_id}", headers=F.petty_cash_headers(app, user_id, origin=WEB), **kw)


def test_the_company_reads_its_name_role_and_currency(app, client, shop):
    resp = _get(client, app, shop["entity"].id, shop["owner"].id)

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["company"] == {
        "id": shop["entity"].id,
        "name": "Vine Café Central",
        "role": "admin",
        "role_label": "Admin",
        "currency": {"code": "HKD", "decimal_places": 2},
    }
    assert resp.get_json()["person"]["first_name"] == "Olive"
    assert resp.headers["Access-Control-Allow-Origin"] == WEB
    assert "Origin" in resp.headers["Vary"]
    assert resp.headers["Cache-Control"] == "no-store"


def test_the_preflight_answers_before_any_token(client, shop):
    resp = client.options(
        f"{BASE}/{shop['entity'].id}",
        headers={"Origin": WEB, "Access-Control-Request-Method": "PUT"},
    )
    assert resp.status_code == 204
    assert resp.headers["Access-Control-Allow-Origin"] == WEB
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert method in resp.headers["Access-Control-Allow-Methods"]


def _token(app, claims: dict, *, secret=None) -> dict:
    token = jwt.encode(claims, secret or app.config["SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}", "Origin": WEB}


def _later(minutes=30):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


@pytest.mark.parametrize(
    "kind",
    ["none", "bad signature", "expired", "no module claim", "onboarding scope", "garbage"],
)
def test_anything_but_a_live_module_token_is_a_401_the_app_can_read(app, client, shop, kind):
    uid = shop["owner"].id
    headers = {
        "none": {"Origin": WEB},
        "bad signature": _token(app, {"user_id": uid, "module": "billing", "exp": _later()}, secret="x" * 32),
        "expired": _token(app, {"user_id": uid, "module": "billing", "exp": _later(-1)}),
        "no module claim": _token(app, {"user_id": uid, "exp": _later()}),
        "onboarding scope": _token(app, {"user_id": uid, "scope": "onboarding", "exp": _later()}),
        "garbage": {"Authorization": "Bearer not-a-jwt", "Origin": WEB},
    }[kind]

    resp = client.get(f"{BASE}/{shop['entity'].id}", headers=headers)

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_a_signed_in_session_without_a_token_is_refused(app, client, shop):
    """The surface never reads the session cookie, which is why it may be CSRF-exempt."""
    F.login(client, shop["owner"])
    assert client.get(f"{BASE}/{shop['entity'].id}", headers={"Origin": WEB}).status_code == 401


def test_a_person_who_is_gone_or_switched_off_is_refused(app, client, db, shop):
    from models.db import User

    with app.app_context():
        db.session.get(User, shop["owner"].id).approved = False
        db.session.commit()
    assert _get(client, app, shop["entity"].id, shop["owner"].id).status_code == 401
    assert _get(client, app, shop["entity"].id, F.new_id()).status_code == 401


@pytest.mark.parametrize("which", ["stranger", "no such company", "not an id"])
def test_a_company_you_cannot_see_is_one_answer(app, client, shop, which):
    """Not a member, no such company and a malformed id all read the same: nothing to tell an
    outsider which ids exist."""
    entity_id = {"stranger": shop["entity"].id, "no such company": F.new_id(), "not an id": "abc"}[which]
    user_id = shop["stranger"].id if which == "stranger" else shop["owner"].id

    resp = _get(client, app, entity_id, user_id)

    assert resp.status_code == 403
    assert resp.get_json() == {"error": "You don't have access to that company."}
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_a_superuser_sees_any_company_with_no_role(app, client, db, shop):
    with app.app_context():
        boss = F.make_user(db, "boss@test.com", system_role="superadmin")
    resp = _get(client, app, shop["entity"].id, boss.id)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["company"]["role"] is None


def test_a_company_still_in_onboarding_is_a_409(app, client, db, shop):
    from models.db import Entity

    with app.app_context():
        db.session.get(Entity, shop["entity"].id).status = "onboarding"
        db.session.commit()
    resp = _get(client, app, shop["entity"].id, shop["owner"].id)
    assert resp.status_code == 409
    assert "setting up" in resp.get_json()["error"]


def test_petty_cash_switched_off_is_a_403(app, client, db, shop):
    with app.app_context():
        payments_only = F.make_entity(db, shop["owner"], name="Payments Only", modules=("PAYMENT_REQUEST",))
    resp = _get(client, app, payments_only.id, shop["owner"].id)
    assert resp.status_code == 403
    assert resp.get_json()["error"].startswith("Petty Cash isn't switched on")


def test_a_failure_inside_is_a_generic_500_never_a_pass(app, client, shop, monkeypatch):
    import blueprints.petty_cash_api.routes.company as company

    def boom(*_a, **_k):
        raise RuntimeError("database fell over: secret detail")

    monkeypatch.setattr(company, "company_payload", boom)
    resp = _get(client, app, shop["entity"].id, shop["owner"].id)

    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Something went wrong on our side. Please try again."}
    assert "secret detail" not in resp.get_data(as_text=True)
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_a_guard_failure_is_a_500_too(app, client, shop, monkeypatch):
    import blueprints.petty_cash_api.guard as guard

    def boom(*_a, **_k):
        raise RuntimeError("membership lookup failed")

    monkeypatch.setattr(guard, "_membership", boom)
    resp = _get(client, app, shop["entity"].id, shop["owner"].id)
    assert resp.status_code == 500
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_an_unknown_path_under_the_company_is_a_json_404(app, client, shop):
    resp = client.get(
        f"{BASE}/{shop['entity'].id}/nothing-here",
        headers=F.petty_cash_headers(app, shop["owner"].id, origin=WEB),
    )
    assert resp.status_code == 404


# --- who may call it -------------------------------------------------------------------------------


def test_another_origin_is_answered_with_ours_so_the_browser_refuses_it(app, client, shop):
    resp = client.get(
        f"{BASE}/{shop['entity'].id}",
        headers=F.petty_cash_headers(app, shop["owner"].id, origin="https://evil.example"),
    )
    assert resp.headers["Access-Control-Allow-Origin"] == WEB


def test_a_preview_set_origin_is_allowed_only_with_the_regex(app, client, shop, monkeypatch):
    preview = "https://pr-feat-x-petty-cash.dailyminty.com"
    headers = F.petty_cash_headers(app, shop["owner"].id, origin=preview)

    monkeypatch.delenv("PREVIEW_ORIGIN_REGEX", raising=False)
    assert client.get(f"{BASE}/{shop['entity'].id}", headers=headers).headers["Access-Control-Allow-Origin"] == WEB

    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", REGEX)
    assert client.get(f"{BASE}/{shop['entity'].id}", headers=headers).headers["Access-Control-Allow-Origin"] == preview

    # another app's set host is not this surface's caller
    headers = F.petty_cash_headers(app, shop["owner"].id, origin="https://pr-feat-x-my.dailyminty.com")
    assert client.get(f"{BASE}/{shop['entity'].id}", headers=headers).headers["Access-Control-Allow-Origin"] == WEB


# --- the contract the CSRF exemption rests on --------------------------------------------------------


def _package() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / "blueprints" / "petty_cash_api"


def test_the_package_never_reads_the_session_or_the_logged_in_user():
    """The whole blueprint is CSRF-exempt because nothing in it reads the session cookie. A
    ``current_user`` or ``session`` here would make a cross-site form post act as the person."""
    offenders = []
    for path in _package().rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # ``db.session`` is the database, not the cookie: only a bare name counts, and
            # ``current_user`` however it is reached
            name = node.id if isinstance(node, ast.Name) else None
            if isinstance(node, ast.Attribute) and node.attr == "current_user":
                name = node.attr
            if name in {"current_user", "session", "login_required"}:
                offenders.append(f"{path.name}:{node.lineno} {name}")
            if isinstance(node, ast.ImportFrom) and any(a.name in {"current_user", "session"} for a in node.names):
                offenders.append(f"{path.name}:{node.lineno} import")
    assert not offenders, offenders


def test_the_blueprint_is_csrf_exempt(app):
    csrf = app.extensions["csrf"]
    assert "petty_cash_api" in {getattr(bp, "name", bp) for bp in csrf._exempt_blueprints}


def test_every_route_names_the_company(app):
    """The guard reads the company from the address; a rule without it would skip the check."""
    rules = [str(r) for r in app.url_map.iter_rules() if r.endpoint.startswith("petty_cash_api.")]
    assert rules
    assert all(rule.startswith(f"{BASE}/<entity_id>") for rule in rules), rules
