from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

sys.modules.setdefault("pandas", types.SimpleNamespace(DataFrame=object))
sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.auth.routes import dashboard as dashboard_routes
from blueprints.report.routes import api as api_routes
from blueprints.report.routes import create as create_routes
from blueprints.report.routes import report_detail as report_detail_routes
from blueprints.report.routes import cash_count as cash_count_routes
from blueprints.report.routes import deposit as deposit_routes
from blueprints.report.routes import expense as expense_routes
from blueprints.report.routes import opening as opening_routes
from blueprints.report.routes import sales as sales_routes
from blueprints.report.services import ending as ending_service
from blueprints.user_management.routes import find_user as find_user_routes
from blueprints.user_management.routes import roles as roles_routes
from blueprints.xero.routes import settings as xero_settings_routes
from blueprints.user_management.routes import admin_dashboard as admin_dashboard_routes


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


class _FakeQueryResult:
    def __init__(self, results):
        self._results = list(results)

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._results)


class _FakeReportQuery:
    def __init__(self, results):
        self._results = results
        self.filter_by_calls: list[dict[str, object]] = []

    def filter_by(self, **kwargs):
        self.filter_by_calls.append(kwargs)
        return _FakeQueryResult(self._results)


def test_index_redirects_to_entity_list_when_entity_is_not_selected(monkeypatch):
    app = _build_app()

    monkeypatch.setattr(
        dashboard_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1"),
    )

    with app.test_request_context("/index", method="GET"):
        response = dashboard_routes.index.__wrapped__()

    assert response.status_code == 302
    assert response.location == "/entity"


def test_index_uses_explicit_entity_id_without_user_company(monkeypatch):
    app = _build_app()
    reports = [
        SimpleNamespace(
            id="report-1",
            shop_sales=75.0,
            delivery_sales=0.0,
            shop_expenses=[],
            opening_balance=100.0,
            cash_addition=0.0,
            cash_sales=50.0,
            bank_deposit=20.0,
        )
    ]
    fake_query = _FakeReportQuery(reports)

    monkeypatch.setattr(
        dashboard_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", company=None),
    )
    monkeypatch.setattr(dashboard_routes, "has_permission", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        dashboard_routes,
        "Report",
        SimpleNamespace(query=fake_query, date=SimpleNamespace(desc=lambda: None)),
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_cash_sales_from_detail",
        lambda _report_id, fallback_value=0.0: fallback_value,
    )
    monkeypatch.setattr(
        dashboard_routes,
        "render_template",
        lambda template_name, **context: {"template": template_name, "context": context},
    )

    with app.test_request_context("/index?entity_id=entity-1", method="GET"):
        response = dashboard_routes.index.__wrapped__()

    assert response["template"] == "report_list.html"
    assert response["context"]["entity_id"] == "entity-1"
    assert fake_query.filter_by_calls == [{"company": "entity-1"}]


def test_create_report_requires_explicit_entity_id(monkeypatch):
    app = _build_app()

    monkeypatch.setattr(
        create_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", company="legacy-entity"),
    )
    monkeypatch.setattr(create_routes, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(create_routes, "url_for", lambda *_args, **_kwargs: "/entity")

    with app.test_request_context("/create", method="GET"):
        response = create_routes.create_report.__wrapped__()

    assert response.status_code == 302
    assert response.location == "/entity"


def test_report_ending_resolves_entity_from_report_id(monkeypatch):
    app = _build_app()
    permission_entity_ids: list[str | None] = []

    monkeypatch.setattr(
        ending_service,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", username="user"),
    )
    monkeypatch.setattr(
        ending_service,
        "resolve_report_entity_id",
        lambda report_id: "entity-42" if report_id == "draft-1" else None,
    )
    monkeypatch.setattr(
        ending_service,
        "has_permission",
        lambda _user, _permission, entity_id=None: permission_entity_ids.append(entity_id)
        or False,
    )
    monkeypatch.setattr(ending_service, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ending_service, "url_for", lambda *_args, **_kwargs: "/entity")

    with app.test_request_context("/report/ending", method="GET"):
        response = ending_service.report_ending(id="draft-1", entity_id=None)

    assert response.status_code == 302
    assert response.location == "/entity"
    assert permission_entity_ids == ["entity-42"]


def test_resume_report_uses_report_entity_when_query_param_missing(monkeypatch):
    app = _build_app()
    get_next_calls: list[tuple[object, str, str | None, str | None]] = []

    monkeypatch.setattr(
        report_detail_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", username="user"),
    )
    monkeypatch.setattr(
        report_detail_routes,
        "resolve_report_entity_id",
        lambda report_id: "entity-77" if report_id == "draft-1" else None,
    )
    monkeypatch.setattr(
        report_detail_routes,
        "get_next_section_for_user",
        lambda user, company, transaction_date, draft_id=None: get_next_calls.append(
            (user, company, transaction_date, draft_id)
        )
        or ("opening", draft_id, True),
    )
    monkeypatch.setattr(report_detail_routes, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        report_detail_routes,
        "url_for",
        lambda route_name, **_kwargs: f"/{route_name.replace('.', '/')}",
    )

    with app.test_request_context(
        "/report/resume?draft_id=draft-1&transaction_date=2025-03-02", method="GET"
    ):
        response = report_detail_routes.resume_report.__wrapped__()

    assert response.status_code == 302
    assert response.location.endswith("entity_id=entity-77")
    assert get_next_calls == [
        (
            report_detail_routes.current_user,
            "entity-77",
            "2025-03-02",
            "draft-1",
        )
    ]


def test_get_draft_totals_requires_explicit_entity_id(monkeypatch):
    app = _build_app()

    monkeypatch.setattr(
        api_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", company="legacy-entity"),
    )

    with app.test_request_context(
        "/api/get_draft_totals?transaction_date=2025-03-02", method="GET"
    ):
        response, status = api_routes.get_draft_totals.__wrapped__()

    assert status == 400
    assert response.get_json()["message"] == "I need to know which entity we're working with first!"


def test_remove_connections_all_requires_explicit_entity_id(monkeypatch):
    app = _build_app()

    monkeypatch.setattr(
        xero_settings_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", company="legacy-entity"),
    )

    with app.test_request_context("/remove/connections/all", method="GET"):
        response, status = xero_settings_routes.remove_connections_all.__wrapped__()

    assert status == 400
    assert response.get_json()["message"] == "I need to know which entity we're working with first!"


def test_admin_dashboard_passes_membership_summary_map(monkeypatch):
    app = _build_app()
    pending_users = [SimpleNamespace(id="u-1", approved=False)]
    approved_users = [SimpleNamespace(id="u-2", approved=True)]

    class _QueryStub:
        def __init__(self, results):
            self._results = list(results)

        def filter_by(self, **kwargs):
            approved = kwargs.get("approved")
            if approved is False:
                return SimpleNamespace(all=lambda: pending_users)
            if approved is True:
                return SimpleNamespace(all=lambda: approved_users)
            raise AssertionError(f"Unexpected filter: {kwargs}")

    monkeypatch.setattr(
        admin_dashboard_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, system_role="superuser"),
    )
    monkeypatch.setattr(
        admin_dashboard_routes,
        "User",
        SimpleNamespace(SYSTEM_ROLE_SUPERUSER="superuser", query=_QueryStub([])),
    )
    monkeypatch.setattr(
        admin_dashboard_routes,
        "_build_membership_summary_by_user",
        lambda user_ids: {user_id: f"{user_id}-membership" for user_id in user_ids},
    )
    monkeypatch.setattr(
        admin_dashboard_routes,
        "render_template",
        lambda template_name, **context: {"template": template_name, "context": context},
    )

    with app.test_request_context("/admin_dashboard", method="GET"):
        response = admin_dashboard_routes.admin_dashboard.__wrapped__()

    assert response["template"] == "admin_dashboard.html"
    assert response["context"]["membership_summary_by_user"] == {
        "u-1": "u-1-membership",
        "u-2": "u-2-membership",
    }


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


def test_find_user_looks_up_membership_by_entity_id(monkeypatch):
    app = _build_app()
    captured: dict[str, object] = {}

    class _Field:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return (self.name, "==", other)

        def is_(self, other):
            return (self.name, "is", other)

    class _MembershipQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {"user_id": "actor-1", "approved": True}
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(entity_id="entity-2"),
                    SimpleNamespace(entity_id="entity-1"),
                ]
            )

    class _UserLookupQuery:
        def with_entities(self, *entities):
            captured["entities"] = entities
            return self

        def join(self, model, condition):
            captured["join"] = (model, condition)
            return self

        def filter(self, *conditions):
            captured["conditions"] = conditions
            return self

        def first(self):
            return SimpleNamespace(username="found-user")

    class _FakeForm:
        def __init__(self):
            self.first_name = SimpleNamespace(data="Casey", label="First Name")
            self.last_name = SimpleNamespace(data="Jones", label="Last Name")
            self.entity_id = SimpleNamespace(data="", choices=[], label="Entity")

    fake_user_model = SimpleNamespace(
        query=_UserLookupQuery(),
        username=_Field("username"),
        id=_Field("id"),
        first_name=_Field("first_name"),
        last_name=_Field("last_name"),
    )
    fake_membership_model = SimpleNamespace(
        query=_MembershipQuery(),
        user_id=_Field("user_id"),
        entity_id=_Field("entity_id"),
        approved=_Field("approved"),
    )

    monkeypatch.setattr(
        find_user_routes,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="actor-1"),
    )
    monkeypatch.setattr(find_user_routes, "FindUserForm", _FakeForm)
    monkeypatch.setattr(find_user_routes, "User", fake_user_model)
    monkeypatch.setattr(find_user_routes, "UserEntity", fake_membership_model)
    monkeypatch.setattr(find_user_routes, "has_permission", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        find_user_routes,
        "render_template",
        lambda template_name, **context: {"template": template_name, "context": context},
    )

    with app.test_request_context("/find_user", method="GET"):
        response = find_user_routes.find_user.__wrapped__()

    assert response["template"] == "find_user.html"
    assert response["context"]["userid"].username == "found-user"
    assert response["context"]["form"].entity_id.choices == [
        ("entity-1", "entity-1"),
        ("entity-2", "entity-2"),
    ]
    assert captured["entities"] == (fake_user_model.username,)
    assert captured["join"] == (
        fake_membership_model,
        ("user_id", "==", fake_user_model.id),
    )
    assert captured["conditions"] == (
        ("first_name", "==", "Casey"),
        ("last_name", "==", "Jones"),
        ("entity_id", "==", "entity-1"),
        ("approved", "is", True),
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "templates/components/sidepanel.html",
        "templates/index.html",
        "templates/admin_dashboard.html",
        "templates/user approval.html",
        "templates/report/submitted.html",
        "templates/find_user.html",
    ],
)
def test_templates_use_explicit_entity_context_not_user_company(relative_path):
    template_path = Path(__file__).resolve().parents[1] / relative_path
    contents = template_path.read_text(encoding="utf-8")

    assert "current_user.company" not in contents
    assert "user.company" not in contents
    if relative_path == "templates/find_user.html":
        assert "form.company" not in contents


@pytest.mark.parametrize(
    ("route_module", "view_name", "path"),
    [
        (opening_routes, "report_opening", "/report/opening"),
        (sales_routes, "report_sale", "/report/sale"),
        (expense_routes, "report_expense", "/report/expense"),
        (deposit_routes, "report_deposit", "/report/deposit"),
        (cash_count_routes, "report_cash_count", "/report/cash_count"),
    ],
)
def test_report_steps_redirect_to_entity_list_without_explicit_entity_context(
    route_module, view_name, path, monkeypatch
):
    app = _build_app()

    monkeypatch.setattr(
        route_module,
        "current_user",
        SimpleNamespace(is_authenticated=True, id="user-1", company=None),
    )
    monkeypatch.setattr(route_module, "url_for", lambda *_args, **_kwargs: "/entity")

    with app.test_request_context(path, method="GET"):
        response = getattr(route_module, view_name).__wrapped__()

    assert response.status_code == 302
    assert response.location == "/entity"
