"""The subscription notice on the Petty Cash dashboard: when Flask asks, and how.

What the notice SAYS is minty-subscription-api's (``GET /api/entities/{id}/subscription-notice``,
tested there). What stays in Flask, and is pinned here:

* **When to ask** - once per entity per login (``claim_subscription_notice``), with the login
  id that lets the Payment app honour the same rule (``LOGIN_SID_SESSION_KEY``, the ``sid``
  claim).
* **How to ask** - ``services.subscription_api.fetch_notice``: server-side, as the person
  viewing the dashboard, with a five-minute self-minted token; any failure is no notice, never
  a broken dashboard.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# --- when to ask --------------------------------------------------------------


def test_the_notice_is_claimed_once_per_session():
    from blueprints.entity.services.modules import claim_subscription_notice

    session: dict = {}

    assert claim_subscription_notice(session, "entity-1") is True
    assert claim_subscription_notice(session, "entity-1") is False
    assert claim_subscription_notice(session, "entity-1") is False


def test_each_entity_is_claimed_separately():
    """Switching companies is a new question, even in the same login."""
    from blueprints.entity.services.modules import claim_subscription_notice

    session: dict = {}

    assert claim_subscription_notice(session, "entity-1") is True
    assert claim_subscription_notice(session, "entity-2") is True
    assert claim_subscription_notice(session, "entity-1") is False


def test_a_fresh_login_asks_again():
    """The flag lives in the session, so a new session shows the notice again —
    a problem the user didn't fix is worth repeating tomorrow."""
    from blueprints.entity.services.modules import claim_subscription_notice

    assert claim_subscription_notice({}, "entity-1") is True
    assert claim_subscription_notice({}, "entity-1") is True


def test_signing_in_stamps_a_new_login_id(app):
    """The id Module 2 keys its own flag by. It must CHANGE on every sign-in.

    That app cannot read this session, so without an id that turns over per login
    its flag was per-TAB: signing out and back in without closing the tab left the
    notice suppressed there while the dashboard correctly showed it again.
    """
    from types import SimpleNamespace

    from flask import session as flask_session
    from flask_login import user_logged_in

    from blueprints.entity.services.modules import LOGIN_SID_SESSION_KEY

    with app.test_request_context("/"):
        user_logged_in.send(app, user=SimpleNamespace(id="user-1"))
        first = flask_session.get(LOGIN_SID_SESSION_KEY)

        user_logged_in.send(app, user=SimpleNamespace(id="user-1"))
        second = flask_session.get(LOGIN_SID_SESSION_KEY)

    assert first and second
    assert first != second


@pytest.fixture
def stub_token_user(monkeypatch):
    """_generate_module_token reads the user's system_role; these tests don't care."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "blueprints.entity.routes.modules.User",
        SimpleNamespace(
            query=SimpleNamespace(get=lambda _id: SimpleNamespace(system_role="normal"))
        ),
    )


def test_the_handoff_token_carries_the_login_id(app, stub_token_user):
    """Module 2 receives the id as a claim — that is the whole delivery mechanism."""
    import jwt as pyjwt
    from flask import session as flask_session

    from blueprints.entity.routes.modules import _generate_module_token
    from blueprints.entity.services.modules import LOGIN_SID_SESSION_KEY

    with app.test_request_context("/"):
        flask_session[LOGIN_SID_SESSION_KEY] = "sid-abc"
        token = _generate_module_token("user-1", "entity-1", "xero-1", "admin")

    decoded = pyjwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    assert decoded["sid"] == "sid-abc"


def test_a_token_minted_without_a_session_has_an_empty_login_id(app, stub_token_user):
    """The CLI mints tokens too. An empty sid is the frontend's signal to fall back
    to its previous per-tab flag rather than crash or key by "None"."""
    import jwt as pyjwt

    from blueprints.entity.routes.modules import _generate_module_token

    with app.app_context():
        token = _generate_module_token("user-1", "entity-1", "xero-1", "admin")

    decoded = pyjwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    assert decoded["sid"] == ""


def test_signing_in_clears_the_seen_flags(app):
    """"Once per login" only holds if something actually resets it on login.

    ``logout_user()`` leaves the session cookie intact, so the flag survived a
    logout AND the next sign-in — the notice was really once-per-browser-forever,
    and a different user on the same browser inherited the previous one's flags.
    The app wires ``user_logged_in`` to clear them; this is that contract.
    """
    from types import SimpleNamespace

    from flask import session as flask_session
    from flask_login import user_logged_in

    from blueprints.entity.services.modules import NOTICE_SEEN_SESSION_KEY

    with app.test_request_context("/"):
        flask_session[NOTICE_SEEN_SESSION_KEY] = ["entity-1", "entity-2"]
        user_logged_in.send(app, user=SimpleNamespace(id="user-1"))

        assert NOTICE_SEEN_SESSION_KEY not in flask_session


def test_claim_reassigns_rather_than_mutating():
    """Flask's session only marks itself dirty on __setitem__ — an in-place append
    would be silently dropped, and the modal would return on every page load."""
    from blueprints.entity.services.modules import (NOTICE_SEEN_SESSION_KEY,
                                                    claim_subscription_notice)

    original: list[str] = []
    session = {NOTICE_SEEN_SESSION_KEY: original}

    claim_subscription_notice(session, "entity-1")

    assert original == []
    assert session[NOTICE_SEEN_SESSION_KEY] == ["entity-1"]


def test_no_entity_id_claims_nothing():
    from blueprints.entity.services.modules import claim_subscription_notice

    assert claim_subscription_notice({}, "") is False


def test_the_claim_is_spent_even_when_there_was_nothing_to_show():
    """Documenting the trade-off, because it is surprising.

    The claim is consumed before the notice is built, so a visit that had nothing
    to report still burns the session's one look. That is deliberate — checking
    first is what keeps the billing queries off every dashboard load — but it means
    a state that becomes true mid-session is not announced until the next login.
    The ``?notice=1`` debug bypass exists for exactly this.
    """
    from blueprints.entity.services.modules import claim_subscription_notice

    session: dict = {}
    assert claim_subscription_notice(session, "entity-1") is True  # nothing to show
    assert claim_subscription_notice(session, "entity-1") is False  # now there is


# --- how to ask ---------------------------------------------------------------


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


@pytest.fixture
def fetch(app, monkeypatch):
    """``fetch_notice`` with ``requests.get`` recorded; returns ``(result, calls)``."""
    import requests

    from services import subscription_api

    def _run(*, response=None, raises=None):
        calls = []

        def _get(url, **kwargs):
            calls.append((url, kwargs))
            if raises:
                raise raises
            return response

        monkeypatch.setattr(requests, "get", _get)
        user = SimpleNamespace(id="user-1", system_role="normal")
        with app.app_context():
            return subscription_api.fetch_notice("entity-1", user), calls

    return _run


NOTICE = {
    "items": [{"kind": "past_due", "severity": "critical", "title": "Petty Cash payment failed"}],
    "can_manage": True,
    "payer": None,
    "severity": "critical",
    "settings_path": "/handoff/minty-web?next=x",
}


def test_the_notice_comes_from_the_subscription_api_as_the_viewer(app, fetch):
    import jwt

    result, [(url, kwargs)] = fetch(response=_Resp(200, NOTICE))

    assert result == NOTICE
    assert url.endswith("/api/entities/entity-1/subscription-notice")
    token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    assert claims["user_id"] == "user-1"
    assert claims["entity_id"] == "entity-1"
    # One request's worth of life, no more.
    assert claims["exp"] - claims["iat"] <= 5 * 60
    assert kwargs["timeout"]


def test_nothing_to_report_is_no_notice(fetch):
    result, _ = fetch(response=_Resp(200, {**NOTICE, "items": []}))
    assert result is None


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_a_refusal_or_failure_is_no_notice(fetch, status):
    result, _ = fetch(response=_Resp(status, {"error": "x"}))
    assert result is None


def test_an_unreachable_api_is_no_notice(fetch):
    import requests

    result, _ = fetch(raises=requests.ConnectionError("down"))
    assert result is None


def test_a_non_json_answer_is_no_notice(fetch):
    result, _ = fetch(response=_Resp(200, None))
    assert result is None
