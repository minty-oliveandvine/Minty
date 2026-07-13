from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace


class _FakeFilterQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeGetQuery:
    def __init__(self, result):
        self._result = result

    def get(self, *_args, **_kwargs):
        return self._result


def test_generate_share_link_route_does_not_call_permission_checks(
    app, monkeypatch
):
    from blueprints.report.routes import api

    handler = getattr(api.generate_share_link, "__wrapped__", api.generate_share_link)
    called = {}

    def fake_create_share_link(user_id, payload):
        called["user_id"] = user_id
        called["payload"] = payload
        return {"url": "https://example.test/Minty_Report/AB/01_Jan_2026"}, 200

    with app.app_context():
        with app.test_request_context(
            "/api/generate_share_link",
            method="POST",
            json={"entity_id": "entity-1", "transaction_date": "2026-01-01"},
        ):
            monkeypatch.setattr(
                api,
                "has_permission",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("generate_share_link should not check has_permission")
                ),
            )
            monkeypatch.setattr(api, "current_user", SimpleNamespace(id="user-1"))
            monkeypatch.setattr(
                api, "create_share_link_for_report", fake_create_share_link
            )

            response, status = handler()

    assert status == 200
    assert response.get_json()["url"] == "https://example.test/Minty_Report/AB/01_Jan_2026"
    assert called["user_id"] == "user-1"
    assert called["payload"]["entity_id"] == "entity-1"


def test_create_share_link_for_report_uses_membership_not_role_permissions(
    app, monkeypatch
):
    from blueprints.report.services import share

    captured = {}

    with app.app_context():
        monkeypatch.setattr(
            share.UserEntity, "query", _FakeFilterQuery(SimpleNamespace(id="membership"))
        )
        monkeypatch.setattr(
            share.Entity, "query", _FakeGetQuery(SimpleNamespace(name="Acme Bistro"))
        )
        monkeypatch.setattr(share.ShareLink, "query", _FakeFilterQuery(None))

        monkeypatch.setattr(
            share,
            "generate_share_token",
            lambda *_args, **_kwargs: captured.setdefault("token", "token-value"),
        )

        def fake_add(link):
            captured["added_link"] = link

        def fake_commit():
            captured["committed"] = True

        monkeypatch.setattr(share.db.session, "add", fake_add)
        monkeypatch.setattr(share.db.session, "delete", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(share.db.session, "commit", fake_commit)

        with app.test_request_context("/"):
            response, status = share.create_share_link_for_report(
                "user-1",
                {"entity_id": "entity-1", "transaction_date": "2026-01-01"},
            )

    assert status == 200
    assert response["url"].endswith("/Minty_Report/AB/01_Jan_2026/")
    assert captured["committed"] is True
    assert captured["added_link"].path_segment == "AB/01_Jan_2026"
    assert captured["added_link"].entity_id == "entity-1"
    assert captured["added_link"].transaction_date == "2026-01-01"


def test_generate_share_link_denies_membership_missing(app, monkeypatch):
    from blueprints.report.services import share

    with app.app_context():
        monkeypatch.setattr(share.UserEntity, "query", _FakeFilterQuery(None))

        response, status = share.create_share_link_for_report(
            "user-1",
            {"entity_id": "entity-1", "transaction_date": "2026-01-01"},
        )

    assert status == 403
    assert response["error"] == "Hmm, it looks like you don't have permission to look there."


def test_create_share_link_for_report_reuses_existing_path_segment(
    app, monkeypatch
):
    from blueprints.report.services import share

    captured = {}
    existing_link = SimpleNamespace(
        path_segment="AB/12_Mar_2026",
        token="old-token",
        entity_id="entity-1",
        transaction_date="2026-03-12",
        expires_at=None,
    )

    with app.app_context():
        monkeypatch.setattr(
            share.UserEntity, "query", _FakeFilterQuery(SimpleNamespace(id="membership"))
        )
        monkeypatch.setattr(
            share.Entity, "query", _FakeGetQuery(SimpleNamespace(name="Acme Bistro"))
        )
        monkeypatch.setattr(share.ShareLink, "query", _FakeFilterQuery(existing_link))
        monkeypatch.setattr(
            share,
            "generate_share_token",
            lambda *_args, **_kwargs: "new-token",
        )
        monkeypatch.setattr(
            share.db.session,
            "add",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("existing share link should be updated in place")
            ),
        )
        monkeypatch.setattr(share.db.session, "delete", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            share.db.session, "commit", lambda: captured.setdefault("committed", True)
        )

        with app.test_request_context("/"):
            response, status = share.create_share_link_for_report(
                "user-1",
                {"entity_id": "entity-1", "transaction_date": "2026-03-12"},
            )

    assert status == 200
    assert response["url"].endswith("/Minty_Report/AB/12_Mar_2026/")
    assert captured["committed"] is True
    assert existing_link.token == "new-token"
    assert existing_link.entity_id == "entity-1"
    assert existing_link.transaction_date == "2026-03-12"


def test_public_share_route_calls_report_ending_without_auth_gate(app, monkeypatch):
    from blueprints.report.routes import legacy
    from blueprints.report.services import ending as ending_service

    called = {}
    future = datetime.now() + timedelta(days=1)
    share_link = SimpleNamespace(
        token="signed-token",
        entity_id="entity-1",
        expires_at=future,
    )

    with app.app_context():
        monkeypatch.setattr(legacy.ShareLink, "query", _FakeFilterQuery(share_link))
        monkeypatch.setattr(legacy.Entity, "query", _FakeGetQuery(SimpleNamespace()))
        monkeypatch.setattr(
            legacy.Report, "query", _FakeFilterQuery(SimpleNamespace(id="report-1"))
        )
        monkeypatch.setattr(
            legacy,
            "verify_share_token",
            lambda *_args, **_kwargs: (
                True,
                {"entity_id": "entity-1", "transaction_date": "2026-03-11"},
            ),
        )

        def fake_report_ending(id=None, entity_id=None, skip_auth=False):
            called["id"] = id
            called["entity_id"] = entity_id
            called["skip_auth"] = skip_auth
            return ("shared-report", 200)

        monkeypatch.setattr(ending_service, "report_ending", fake_report_ending)

        with app.test_request_context("/Minty_Report/AB/11_Mar_2026/"):
            response = legacy.minty_report_share("AB/11_Mar_2026")

    assert response == ("shared-report", 200)
    assert called["id"] == "report-1"
    assert called["entity_id"] == "entity-1"
    assert called["skip_auth"] is True
