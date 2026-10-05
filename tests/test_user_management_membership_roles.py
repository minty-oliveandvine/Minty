from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.user_management.routes import create_user as create_user_routes


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


class _QueryStub:
    def __init__(self, result=None):
        self._result = result
        self.filter_calls: list[dict[str, object]] = []

    def filter_by(self, **kwargs):
        self.filter_calls.append(kwargs)
        return self

    def first(self):
        return self._result

    def get(self, _user_id):
        return self._result


class _SessionStub:
    def __init__(self):
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def add(self, item):
        self.added.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def test_create_user_assigns_membership_role_but_keeps_system_role_normal(
    monkeypatch,
):
    app = _build_app()
    session = _SessionStub()
    created_users: list[object] = []
    created_memberships: list[object] = []

    class FakeUser:
        SYSTEM_ROLE_DEFAULT = "normal"
        query = _QueryStub(result=None)

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = "new-user-id"
            created_users.append(self)

    class FakeUserEntity:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            created_memberships.append(self)

    monkeypatch.setattr(
        create_user_routes,
        "current_user",
        SimpleNamespace(id="actor-1", is_authenticated=True),
    )
    monkeypatch.setattr(
        create_user_routes,
        "can_manage_role_assignment_for_entity",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        create_user_routes,
        "bcrypt_hash_password",
        lambda password: f"hashed::{password}",
    )
    monkeypatch.setattr(create_user_routes, "User", FakeUser)
    monkeypatch.setattr(create_user_routes, "UserEntity", FakeUserEntity)
    monkeypatch.setattr(create_user_routes, "db", SimpleNamespace(session=session))

    with app.test_request_context(
        "/minty/api/users/create",
        method="POST",
        json={
            "email": "member@test.com",
            "first_name": "Member",
            "last_name": "User",
            "password": "password123",
            "company_uuid": "entity-1",
            "role": "cashier",
        },
    ):
        response, status = create_user_routes.create_user.__wrapped__.__wrapped__()

    assert status == 201
    assert response.get_json()["status"] == "success"
    assert created_users[0].system_role == "normal"
    assert "company" not in created_users[0].__dict__
    assert created_memberships[0].role == "cashier"
    assert created_memberships[0].user_id == "new-user-id"
    assert session.commit_calls == 2


