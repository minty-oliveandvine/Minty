"""minty-web's entity list: ``GET /api/me/entities`` and the ``/entity`` hand-off to it.

The API is the Jinja list's own builder (``services/entity_list.build_entity_list``) behind
minty-web's bearer surface (``blueprints/shared/hub_api.py``). ``/entity`` sends the browser
on to minty-web - always, since the ``MINTY_WEB_HUB`` switch and the Jinja list went in phase 2
(2026-10-05), Terms owed or not - and carries what the redirect that brought the person there
flashed, signed, so nothing flashed on the way is lost.

Imports of project modules happen inside tests: the conftest ``app`` fixture re-imports the
blueprints, so a module captured at import time is not the one under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"


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


@pytest.fixture
def people(app, db):
    """Olive belongs to three companies; Stranger to one of her own; Staff is a superuser."""
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        olive = F.make_user(db, "olive@test.com", first_name="Olive", last_name="Vine")
        stranger = F.make_user(db, "stranger@test.com")
        staff = F.make_user(db, "staff@test.com", system_role="superadmin")
        both = F.make_entity(db, olive, name="Both Modules Ltd", modules=("PETTY_CASH", "PAYMENT_REQUEST"),
                             currency=currency, country=country)
        petty = F.make_entity(db, olive, name="Petty Only Ltd", currency=currency, country=country)
        setup = F.make_entity(db, olive, name="Setup Ltd", status="onboarding", currency=currency, country=country)
        other = F.make_entity(db, stranger, name="Somebody Else Ltd", currency=currency, country=country)

        from models.db import Entity

        # Petty Only was opened an hour ago by Olive; Both Modules yesterday; Setup never.
        # Aware, as record_entity_access writes it - the column is a TIMESTAMPTZ.
        now = datetime.now(timezone.utc).replace(microsecond=0)
        rows = {e.id: Entity.query.filter(Entity.id == e.id).first() for e in (both, petty)}
        rows[petty.id].last_accessed_at = now - timedelta(hours=1)
        rows[petty.id].last_accessed_by_user_id = olive.id
        rows[both.id].last_accessed_at = now - timedelta(days=1)
        db.session.commit()
    return {"olive": olive, "stranger": stranger, "staff": staff,
            "both": both, "petty": petty, "setup": setup, "other": other}


def _token(app, user_id, **overrides) -> str:
    claims = {"user_id": user_id, "entity_id": "", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    claims.update(overrides)
    return jwt.encode(claims, app.config["SECRET_KEY"], algorithm="HS256")


def _get(client, app, user_id=None, path="/api/me/entities", **token_overrides):
    headers = {"Origin": HUB}
    if user_id is not None:
        headers["Authorization"] = f"Bearer {_token(app, user_id, **token_overrides)}"
    return client.get(path, headers=headers)


# --- the door --------------------------------------------------------------------------


def test_the_preflight_names_the_hub_and_its_methods(client, hub):
    resp = client.options(
        "/api/me/entities",
        headers={"Origin": HUB, "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code == 204
    assert resp.headers["Access-Control-Allow-Origin"] == HUB
    assert "GET" in resp.headers["Access-Control-Allow-Methods"]
    assert "Origin" in resp.headers["Vary"]  # Flask adds Cookie once the session is touched


@pytest.mark.parametrize(
    "case",
    ["missing", "forged", "expired", "unknown user", "switched off"],
)
def test_every_bad_token_is_one_401_the_browser_can_read(app, client, people, hub, case):
    olive = people["olive"]
    if case == "missing":
        resp = _get(client, app)
    elif case == "forged":
        forged = jwt.encode({"user_id": olive.id}, "not-the-secret", algorithm="HS256")
        resp = client.get("/api/me/entities", headers={"Authorization": f"Bearer {forged}"})
    elif case == "expired":
        resp = _get(client, app, olive.id, exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    elif case == "unknown user":
        resp = _get(client, app, F.new_id())
    else:
        from models.db import User

        with app.app_context():
            User.query.filter(User.id == olive.id).first().approved = False
            from models.db import db as _db

            _db.session.commit()
        resp = _get(client, app, olive.id)

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}
    # through the CORS headers, or the browser reads a network failure, not a lapsed token
    assert resp.headers["Access-Control-Allow-Origin"] == HUB


# --- the list --------------------------------------------------------------------------


def test_the_list_is_the_persons_own_in_the_lists_order(app, client, people, hub):
    body = _get(client, app, people["olive"].id).get_json()

    names = [e["name"] for e in body["entities"]]
    # setup in progress first, then most recently opened, never-opened last
    assert names == ["Setup Ltd", "Petty Only Ltd", "Both Modules Ltd"]
    assert "Somebody Else Ltd" not in names
    assert body["notices"] == []

    setup, petty, both = body["entities"]
    assert setup["status"] == "onboarding"
    assert setup["last_accessed_at"] is None and setup["last_accessed_by"] is None
    assert both["modules"] == ["PAYMENT_REQUEST", "PETTY_CASH"]
    assert petty["modules"] == ["PETTY_CASH"]
    assert petty["last_accessed_by"] == "Olive Vine"
    # an ISO instant in UTC - minty-web renders it in the viewer's zone
    opened = datetime.fromisoformat(petty["last_accessed_at"])
    assert opened.utcoffset() == timedelta(0)
    assert timedelta(minutes=55) < datetime.now(timezone.utc) - opened < timedelta(minutes=65)


def test_opening_a_company_stamps_the_instant_whatever_the_sessions_zone(app, client, people, hub):
    """The column is a TIMESTAMPTZ. The write used to hand it a NAIVE UTC value, which
    Postgres reads in the session's zone - so on any session not running in UTC (this
    machine's local server is UTC+8) every "last opened" landed hours early."""
    from blueprints.entity.routes.modules import record_entity_access
    from models.db import db as _db
    from sqlalchemy import text

    with app.app_context():
        _db.session.execute(text("SET TIME ZONE 'Asia/Hong_Kong'"))
        record_entity_access(people["setup"].id, people["olive"].id)

    entries = {e["name"]: e for e in _get(client, app, people["olive"].id).get_json()["entities"]}
    stamped = datetime.fromisoformat(entries["Setup Ltd"]["last_accessed_at"])
    assert abs(datetime.now(timezone.utc) - stamped) < timedelta(minutes=2)
    assert entries["Setup Ltd"]["last_accessed_by"] == "Olive Vine"


def test_a_superuser_sees_every_company(app, client, people, hub):
    names = {e["name"] for e in _get(client, app, people["staff"].id).get_json()["entities"]}
    assert names == {"Setup Ltd", "Petty Only Ltd", "Both Modules Ltd", "Somebody Else Ltd"}


def test_a_trial_badge_never_claims_a_module_that_is_off(app, client, people, hub, monkeypatch):
    petty = people["petty"]
    # Petty Only runs a Payment Request trial row although the module is not switched on,
    # and a Petty Cash trial that is.
    monkeypatch.setattr(
        "blueprints.entity.services.entity_list.get_trial_modules_for_entities",
        lambda ids: {petty.id: {"PETTY_CASH", "PAYMENT_REQUEST"}},
    )
    entries = {e["name"]: e for e in _get(client, app, people["olive"].id).get_json()["entities"]}

    assert entries["Petty Only Ltd"]["trial_modules"] == ["PETTY_CASH"]
    assert entries["Petty Only Ltd"]["trial_module_names"] == ["Petty Cash"]
    assert entries["Both Modules Ltd"]["trial_modules"] == []


def test_a_person_with_no_company_gets_an_empty_list(app, client, db, hub):
    with app.app_context():
        lonely = F.make_user(db, "lonely@test.com")
    assert _get(client, app, lonely.id).get_json() == {"entities": [], "notices": []}


# --- the flash hand-over ---------------------------------------------------------------


def test_a_signed_hand_over_comes_back_as_notices(app, client, people, hub):
    from blueprints.entity.services.entity_list import sign_notices

    with app.test_request_context():
        signed = sign_notices([("danger", "Hmm, I looked everywhere but couldn't find that one."),
                               ("message", "Welcome back!")])
    body = _get(client, app, people["olive"].id, path=f"/api/me/entities?flash={signed}").get_json()

    assert body["notices"] == [
        {"category": "error", "message": "Hmm, I looked everywhere but couldn't find that one."},
        {"category": "success", "message": "Welcome back!"},
    ]


def test_a_forged_or_expired_hand_over_says_nothing(app, client, people, hub, monkeypatch):
    from itsdangerous import URLSafeTimedSerializer

    forged = URLSafeTimedSerializer("not-the-secret", salt="hub-flash").dumps(
        [{"category": "danger", "message": "Call +852 0000 0000 to unlock your account"}]
    )
    olive = people["olive"].id
    assert _get(client, app, olive, path=f"/api/me/entities?flash={forged}").get_json()["notices"] == []
    assert _get(client, app, olive, path="/api/me/entities?flash=junk").get_json()["notices"] == []

    from blueprints.entity.services.entity_list import sign_notices

    with app.test_request_context():
        signed = sign_notices([("info", "old news")])
    monkeypatch.setattr("blueprints.entity.services.entity_list.NOTICE_MAX_AGE_SECONDS", -1)
    assert _get(client, app, olive, path=f"/api/me/entities?flash={signed}").get_json()["notices"] == []


def test_nothing_to_tell_signs_nothing(app):
    from blueprints.entity.services.entity_list import sign_notices

    with app.test_request_context():
        assert sign_notices([]) is None
        assert sign_notices([("info", "   ")]) is None


# --- /entity ---------------------------------------------------------------------------


def _landing(resp):
    assert resp.status_code == 302, resp.data[:300]
    parts = urlsplit(resp.headers["Location"])
    return parts, parse_qs(parts.query)


def test_the_list_is_minty_webs_with_an_unscoped_token(app, client, people, hub, monkeypatch):
    F.login(client, people["olive"])

    parts, query = _landing(client.get("/entity"))

    assert (parts.scheme, parts.netloc, parts.path) == ("http", "hub.minty.test", "/landing")
    assert query["next"] == ["/entities"]
    claims = jwt.decode(query["token"][0], app.config["SECRET_KEY"], algorithms=["HS256"])
    assert claims["user_id"] == people["olive"].id and claims["entity_id"] == ""


def test_what_was_flashed_travels_with_it(app, client, people, hub, monkeypatch):
    F.login(client, people["olive"])
    # a company she is not a member of: the handoff flashes and redirects to /entity
    first = client.get(f"/handoff/minty-web?next=/subscription&entity_id={people['other'].id}")
    assert first.status_code == 302 and first.headers["Location"].endswith("/entity")

    _, query = _landing(client.get("/entity"))
    next_path = urlsplit(query["next"][0])
    assert next_path.path == "/entities"
    signed = parse_qs(next_path.query)["flash"][0]

    notices = _get(client, app, people["olive"].id, path=f"/api/me/entities?flash={signed}").get_json()["notices"]
    assert notices == [
        {"category": "error", "message": "Hmm, it looks like you don't have permission to look there."}
    ]
    # drained: the next Flask page does not show it a second time
    with client.session_transaction() as session:
        assert not session.get("_flashes")


ONBOARDING = "http://onboarding.minty.test"


def _queue_flash(client, *messages):
    with client.session_transaction() as session:
        session["_flashes"] = list(messages)


@pytest.mark.parametrize("hop", ["onboarding", "minty-web"])
def test_a_redirect_into_another_app_drops_the_flash_queue(app, client, people, hub, monkeypatch, hop):
    """Onboarding's Xero connect flashed on every attempt, but the wizard reads the outcome
    from the URL - so the queue sat in the session until finishing onboarding opened /entity,
    and minty-web's list toasted all of it. A redirect into another app never carries it."""
    monkeypatch.setenv("ONBOARDING_WEB_URL", ONBOARDING)
    F.login(client, people["olive"])
    _queue_flash(client, ("success", "Connected to Xero!"), ("danger", "Connection failed"))

    if hop == "onboarding":
        resp = client.get("/entity/create")
        assert resp.headers["Location"].startswith(ONBOARDING + "/")
    else:
        resp = client.get(f"/handoff/minty-web?next=/subscription&entity_id={people['petty'].id}")
        assert resp.headers["Location"].startswith(HUB + "/landing")

    with client.session_transaction() as session:
        assert not session.get("_flashes")
    _, query = _landing(client.get("/entity"))
    assert query["next"] == ["/entities"]  # no ?flash= - nothing left to toast


def test_a_redirect_within_flask_keeps_the_flash_queue(app, client, people, hub, monkeypatch):
    F.login(client, people["olive"])
    _queue_flash(client, ("info", "Still here"))
    resp = client.get(f"/handoff/minty-web?next=/subscription&entity_id={people['other'].id}")
    assert resp.headers["Location"].endswith("/entity")
    with client.session_transaction() as session:
        assert ["info", "Still here"] in [list(f) for f in session["_flashes"]]


def test_terms_owed_minty_web_takes_the_acceptance(app, client, people, hub, monkeypatch):
    """minty-web draws the Terms panel itself (its TermsGate over legal/routes/hub.py), so
    the list hands over even while an acceptance is owed - the gate's redirect to /entity
    carries on to minty-web, where the modal is waiting."""
    F.login(client, people["olive"], accepted_terms=False)
    parts, query = _landing(client.get("/entity"))
    assert (parts.netloc, parts.path) == ("hub.minty.test", "/landing")
    assert query["next"] == ["/entities"]


