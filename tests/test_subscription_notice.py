"""The login id (``LOGIN_SID_SESSION_KEY``, the ``sid`` claim): what lets the payments app show
its subscription notice once per sign-in, though it cannot read this session.

Flask's own dashboard notice (``claim_subscription_notice`` and ``services.subscription_api``) went
with its Petty Cash pages on 2026-10-20; minty-petty-cash-web asks minty-subscription-api itself.
"""
from __future__ import annotations

import pytest


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
