"""Company context comes from an explicit entity id, never ``user.company``. Flask's report pages,
admin pages and their templates went with its HTML on 2026-10-20 (``/index`` is
tests/test_entity_context_routes.py's); what is left is the profile API."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.user_management.routes import roles as roles_routes


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def test_get_my_profile_omits_company_field_and_returns_memberships(monkeypatch):
    app = _build_app()

    class _MembershipQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {"user_id": "user-1"}
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(entity_id="entity-1", role="accountant", approved=True)
                ]
            )

    monkeypatch.setattr(
        roles_routes,
        "current_user",
        SimpleNamespace(
            is_authenticated=True,
            id="user-1",
            email="user@test.com",
            username="user@test.com",
            first_name="Profile",
            last_name="User",
            user_phone="123",
            system_role="normal",
            approved=True,
            company="legacy-company",
        ),
    )
    monkeypatch.setattr(
        roles_routes,
        "UserEntity",
        SimpleNamespace(query=_MembershipQuery()),
    )

    with app.test_request_context("/minty/api/users/me", method="GET"):
        response, status = roles_routes.get_my_profile.__wrapped__()

    assert status == 200
    payload = response.get_json()
    assert payload["user"]["system_role"] == "normal"
    assert "company" not in payload["user"]
    assert payload["memberships"] == [
        {"entity_id": "entity-1", "role": "accountant", "approved": True}
    ]
