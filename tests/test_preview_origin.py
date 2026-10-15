"""Preview sets (blueprints/shared/preview_origin.py): a branch's previews live on
``https://pr-<slug>-<app>.dailyminty.com``, and Flask - where ``PREVIEW_ORIGIN_REGEX`` is set -
hands a person back into the set they came from rather than to the configured front ends.

The front end names itself with ``?return_origin=`` on its way to Flask; Flask keeps the SET
(the slug) in the session, so every later hand-off - to any of the three apps - stays inside
it. Unset, the parameter does nothing; a configured origin, or logging out, leaves the set.

Only a SAME-SITE navigation may name a set (``Sec-Fetch-Site``: our front ends share the
registrable domain), and a set lapses after 30 minutes - so a crafted link from an email or
another site cannot route a signed-in person's tokens into a preview (security review,
2026-10-13).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import time

import char_factories as F
import pytest
from flask import make_response, redirect, session

pytestmark = pytest.mark.char

REGEX = r"^https://pr-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-(?:my|payment-request|onboarding)\.dailyminty\.com$"
SET_MY = "https://pr-feat-x-my.dailyminty.com"
#: What a browser sends on a navigation from one of our front ends (another dailyminty.com host).
SAME_SITE = {"Sec-Fetch-Site": "same-site"}
#: A hop that starts on a Flask page - the only kind (with Xero's return) that reads a stored set.
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def owner(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        user = F.make_user(db, "owner@test.com")
        F.make_entity(db, user, currency=currency, country=country)
        db.session.commit()
    return user


@pytest.fixture
def hosts(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", "https://my.minty.test")
    monkeypatch.setenv("PAYMENT_REQUEST_WEB_URL", "https://payment.minty.test")
    monkeypatch.setenv("ONBOARDING_WEB_URL", "https://onboarding.minty.test")


@pytest.fixture
def on(monkeypatch, hosts):
    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", REGEX)


def _stored(client):
    with client.session_transaction() as sess:
        return (sess.get("preview_set") or {}).get("slug")


def _set(slug="feat-x", age=0):
    """What the session holds once a set is remembered (``age`` seconds ago)."""
    return {"slug": slug, "at": int(time.time()) - age}


# --- remembering the set ---------------------------------------------------------------------


def test_capture_runs_before_every_other_request_hook(app):
    assert app.before_request_funcs[None][0].__name__ == "capture"


def test_a_preview_origin_is_remembered_as_its_set(client, on):
    client.get(f"/?return_origin={SET_MY}/", headers=SAME_SITE)
    assert _stored(client) == "feat-x"


def test_unset_the_parameter_does_nothing(client, hosts, monkeypatch):
    monkeypatch.delenv("PREVIEW_ORIGIN_REGEX", raising=False)
    client.get(f"/?return_origin={SET_MY}", headers=SAME_SITE)
    assert _stored(client) is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://pr-feat-x-my.dailyminty.com.evil.com",
        "https://pr-feat-x-my.dailyminty.com@evil.com",
        "https://pr-feat-x-my.dailyminty.com/path",
        "http://pr-feat-x-my.dailyminty.com",
        "https://pr-feat-x-my.dailyminty.com:443",
        "https://PR-FEAT-X-MY.DAILYMINTY.COM",
        f"https://pr-{'a' * 41}-my.dailyminty.com",
        "https://pr--my.dailyminty.com",
        "https://pr-feat--my.dailyminty.com",
        "https://pr-feat-x-www.dailyminty.com",
        "https://pr-feat-x-my.dailyminty.com\r\nX: y",
        "https://evil.com",
        "",
    ],
)
def test_anything_else_is_ignored(client, on, origin):
    client.get("/", query_string={"return_origin": origin}, headers=SAME_SITE)
    assert _stored(client) is None


@pytest.mark.parametrize("fetch_site", ["cross-site", "none", None])
def test_only_a_same_site_navigation_names_a_set(client, on, fetch_site):
    """A link in an email (``none``), on another site (``cross-site``) or from a browser that
    sends no fetch metadata never chooses where Flask hands a signed-in person's token."""
    headers = {"Sec-Fetch-Site": fetch_site} if fetch_site else {}
    client.get(f"/?return_origin={SET_MY}", headers=headers)
    assert _stored(client) is None


def test_a_set_lapses_after_thirty_minutes(app, on):
    from blueprints.auth.services.hub_login import hub_login_url

    with app.test_request_context("/", headers=SAME_ORIGIN):
        session["preview_set"] = _set(age=29 * 60)
        assert hub_login_url(carry_flashes=False) == "https://pr-feat-x-my.dailyminty.com/login"
        session["preview_set"] = _set(age=31 * 60)
        assert hub_login_url(carry_flashes=False) == "https://my.minty.test/login"


def test_naming_the_set_again_renews_it(client, on):
    with client.session_transaction() as sess:
        sess["preview_set"] = _set(age=29 * 60)
    client.get(f"/?return_origin={SET_MY}", headers=SAME_SITE)
    with client.session_transaction() as sess:
        assert time.time() - sess["preview_set"]["at"] < 60


def test_a_configured_origin_leaves_the_set(client, on):
    client.get(f"/?return_origin={SET_MY}", headers=SAME_SITE)
    client.get("/?return_origin=https://my.minty.test", headers=SAME_SITE)
    assert _stored(client) is None


def test_logging_out_leaves_the_set(client, on, owner):
    F.login(client, owner)
    client.get(f"/?return_origin={SET_MY}", headers=SAME_SITE)
    client.get("/logout")
    assert _stored(client) is None


# --- every hand-off stays in the set ---------------------------------------------------------


def test_the_minty_web_handoff_lands_on_the_set(client, on, owner):
    F.login(client, owner)
    resp = client.get(f"/handoff/minty-web?next=/subscription&return_origin={SET_MY}", headers=SAME_SITE)
    assert resp.status_code == 302
    parts = urlsplit(resp.headers["Location"])
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "pr-feat-x-my.dailyminty.com", "/landing")
    assert parse_qs(parts.query)["token"]


def test_without_a_set_the_handoff_keeps_the_configured_hub(client, on, owner):
    F.login(client, owner)
    resp = client.get("/handoff/minty-web?next=/subscription")
    assert urlsplit(resp.headers["Location"]).netloc == "my.minty.test"


# --- side by side: each trip names its own target ---------------------------------------------


def _with_stored_set(client, slug="feat-x"):
    with client.session_transaction() as sess:
        sess["preview_set"] = _set(slug)


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"},  # from production's hub
        {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"},  # typed or bookmarked
        {},  # a browser that sends no fetch metadata
    ],
)
def test_a_trip_from_a_normal_host_goes_to_the_configured_hub(client, on, owner, headers):
    """Production's front ends name no set, so a set stored by a preview tab in the SAME
    session must not pull a production tab into the preview - and that trip leaves the set."""
    F.login(client, owner)
    _with_stored_set(client)
    resp = client.get("/handoff/minty-web?next=/subscription", headers=headers)
    assert urlsplit(resp.headers["Location"]).netloc == "my.minty.test"
    assert _stored(client) is None


def test_the_trip_s_own_set_beats_the_stored_one(client, on, owner):
    F.login(client, owner)
    _with_stored_set(client, "other")
    resp = client.get(f"/handoff/minty-web?next=/subscription&return_origin={SET_MY}", headers=SAME_SITE)
    assert urlsplit(resp.headers["Location"]).netloc == "pr-feat-x-my.dailyminty.com"


def test_naming_a_configured_origin_needs_no_same_site_trip(client, on, owner):
    """Leaving a set is never risky, so a typed visit to a normal host leaves it at once."""
    F.login(client, owner)
    _with_stored_set(client)
    resp = client.get(
        "/handoff/minty-web?next=/subscription&return_origin=https://my.minty.test",
        headers={"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"},
    )
    assert urlsplit(resp.headers["Location"]).netloc == "my.minty.test"
    assert _stored(client) is None


@pytest.mark.parametrize("fetch_site", ["same-origin", "cross-site"])
def test_a_flask_page_or_xero_return_keeps_the_stored_set(client, on, owner, fetch_site):
    """A link on a Flask page (``same-origin``) and Xero's OAuth return (``cross-site``) can't
    name a set, so they follow the one stored by the front end the person came from."""
    F.login(client, owner)
    _with_stored_set(client)
    resp = client.get(
        "/handoff/minty-web?next=/subscription",
        headers={"Sec-Fetch-Site": fetch_site, "Sec-Fetch-Mode": "navigate"},
    )
    assert urlsplit(resp.headers["Location"]).netloc == "pr-feat-x-my.dailyminty.com"
    assert _stored(client) == "feat-x"


def test_an_api_call_leaves_the_stored_set_alone(client, on):
    """A preview hub's own fetches to Flask carry no ``return_origin``; they must not wipe its set."""
    _with_stored_set(client)
    client.get("/", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors"})
    assert _stored(client) == "feat-x"


def test_every_app_is_reached_in_the_same_set(app, on):
    from blueprints.auth.services.hub_login import hub_login_url
    from blueprints.entity.routes import create, modules
    from blueprints.xero.routes import routes as xero

    with app.test_request_context("/", headers=SAME_ORIGIN):
        session["preview_set"] = _set()
        assert hub_login_url(carry_flashes=False) == "https://pr-feat-x-my.dailyminty.com/login"
        assert modules._frontend_origin() == "https://pr-feat-x-payment-request.dailyminty.com"
        assert create._onboarding_base_url() == "https://pr-feat-x-onboarding.dailyminty.com"
        assert xero._onboarding_app_url() == "https://pr-feat-x-onboarding.dailyminty.com"


def test_an_app_the_regex_leaves_out_keeps_its_configured_origin(app, hosts, monkeypatch):
    from blueprints.entity.routes import create
    from blueprints.shared import preview_origin

    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", r"^https://pr-[a-z0-9-]+-my\.dailyminty\.com$")
    with app.test_request_context("/", headers=SAME_ORIGIN):
        session["preview_set"] = _set()
        assert preview_origin.handoff_origin("my", "https://my.minty.test") == SET_MY
        assert create._onboarding_base_url() == "https://onboarding.minty.test"


def test_a_stored_set_is_dropped_once_the_regex_is_gone(app, hosts, monkeypatch):
    from blueprints.auth.services.hub_login import hub_login_url

    monkeypatch.delenv("PREVIEW_ORIGIN_REGEX", raising=False)
    with app.test_request_context("/", headers=SAME_ORIGIN):
        session["preview_set"] = _set()
        assert hub_login_url(carry_flashes=False) == "https://my.minty.test/login"


# --- CORS ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (SET_MY, True),
        ("https://pr-feat-x-payment-request.dailyminty.com", True),
        ("https://pr-feat-x-onboarding.dailyminty.com", False),  # not a hub caller
        ("https://my.minty.test", True),
        ("https://evil.com", False),
    ],
)
def test_the_hub_api_answers_a_set_origin_for_its_own_callers(app, on, origin, allowed):
    from blueprints.shared import hub_api

    with app.test_request_context("/", headers={"Origin": origin}):
        resp = hub_api.cors(make_response("{}"))
    assert (resp.headers["Access-Control-Allow-Origin"] == origin) is allowed


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://pr-feat-x-onboarding.dailyminty.com", True),
        (SET_MY, False),
        ("https://onboarding.minty.test", True),
    ],
)
def test_the_onboarding_api_answers_only_the_wizard_set_origin(app, on, origin, allowed):
    from blueprints.entity.routes import create

    with app.test_request_context("/", headers={"Origin": origin}):
        resp = create._cors(make_response("{}"))
    assert (resp.headers["Access-Control-Allow-Origin"] == origin) is allowed


def test_cors_ignores_the_session_set(app, on):
    """A stored set moves the hand-offs, never the CORS answer: that is the request's Origin."""
    from blueprints.entity.routes import create

    with app.test_request_context("/"):
        session["preview_set"] = _set()
        resp = create._cors(make_response("{}"))
    assert resp.headers["Access-Control-Allow-Origin"] == "https://onboarding.minty.test"


# --- flashes ---------------------------------------------------------------------------------


def test_flashes_are_dropped_on_the_way_into_a_set(app, on):
    from pettycash.core.hooks import drop_flashes_leaving_flask

    with app.test_request_context("/"):
        session["_flashes"] = [("info", "Connected to Xero!")]
        drop_flashes_leaving_flask(redirect("https://pr-feat-x-onboarding.dailyminty.com/?xero=1"))
        assert "_flashes" not in session


def test_outside_a_request_every_handoff_is_the_configured_one(app, on):
    """Mails and jobs build links with no request - and no person, so no set."""
    from blueprints.entity.routes import create

    with app.app_context():
        assert create._onboarding_base_url() == "https://onboarding.minty.test"
