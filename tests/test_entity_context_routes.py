from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault("pandas", types.SimpleNamespace(DataFrame=object))
sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.auth.routes import dashboard as dashboard_routes
from blueprints.report.routes import api as report_api_routes
from blueprints.report.routes import report_detail as report_detail_routes
from blueprints.xero.routes import settings as xero_settings_routes


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def test_index_redirects_to_entity_list_without_entity_context(monkeypatch):
    app = _build_app()
    monkeypatch.setattr(
        dashboard_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1"),
    )

    with app.test_request_context("/index"):
        response = dashboard_routes.index.__wrapped__()

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/entity")


def test_report_expense_create_contact_requires_explicit_entity_id(monkeypatch):
    app = _build_app()
    monkeypatch.setattr(
        report_api_routes,
        "current_user",
        SimpleNamespace(
            is_authenticated=True,
            id="user-1",
            username="user@test.com",
            company="legacy-company",
            access_token="access-token",
            xero_entity_id="tenant-1",
        ),
    )

    with app.test_request_context(
        "/report/expense/create_contact",
        method="POST",
        json={"name": "Supplier"},
    ):
        response, status = report_api_routes.report_expense_create_contact.__wrapped__()

    assert status == 400
    assert response.get_json()["message"] == "Hmm, something went wrong disconnecting from Xero — mind heading back to your entities and trying again?"


def test_xero_remove_connections_requires_explicit_entity_id(monkeypatch):
    app = _build_app()
    monkeypatch.setattr(
        xero_settings_routes,
        "current_user",
        SimpleNamespace(
            is_authenticated=True,
            company="legacy-company",
            access_token="access-token",
        ),
    )

    with app.test_request_context("/remove/connections/all"):
        response, status = xero_settings_routes.remove_connections_all.__wrapped__()

    assert status == 400
    assert response.get_json()["message"] == "Hmm, something went wrong disconnecting from Xero — mind heading back to your entities and trying again?"


def test_resume_report_derives_entity_from_report_identifier(monkeypatch):
    app = _build_app()
    captured: dict[str, str | None] = {}

    monkeypatch.setattr(
        report_detail_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", username="user@test.com"),
    )
    monkeypatch.setattr(
        report_detail_routes,
        "resolve_report_entity_id",
        lambda report_id: "entity-1" if report_id == "draft-1" else None,
    )

    def _fake_get_next_section_for_user(user, company, transaction_date, draft_id=None):
        captured["company"] = company
        captured["draft_id"] = draft_id
        return "opening", None, False

    monkeypatch.setattr(
        report_detail_routes,
        "get_next_section_for_user",
        _fake_get_next_section_for_user,
    )
    monkeypatch.setattr(
        report_detail_routes,
        "redirect",
        lambda location: SimpleNamespace(status_code=302, location=location),
    )
    monkeypatch.setattr(
        report_detail_routes,
        "url_for",
        lambda route_name, **_kwargs: f"/{route_name}",
    )

    with app.test_request_context("/report/resume?draft_id=draft-1"):
        response = report_detail_routes.resume_report.__wrapped__()

    assert captured == {"company": "entity-1", "draft_id": "draft-1"}
    assert response.status_code == 302
    assert response.location == "/report.report_opening?entity_id=entity-1"
