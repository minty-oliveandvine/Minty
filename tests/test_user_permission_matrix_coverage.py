"""Coverage-focused tests for the user permission matrix requirements."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import permission_policy
from services.permission_policy import (
    Permission,
    can_delete_report,
    can_edit_report,
    can_view_report,
    has_permission,
)

ROOT = Path(__file__).resolve().parents[1]


def _read_function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function `{name}` not found in {path}")


def _permission_name(node: ast.AST | None) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    if isinstance(node.value, ast.Name) and node.value.id == "Permission":
        return node.attr
    return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _has_decorator_permission(function_node: ast.FunctionDef, permission: str) -> bool:
    for decorator in function_node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _call_name(decorator.func) != "require_permission":
            continue
        if decorator.args and _permission_name(decorator.args[0]) == permission:
            return True
        for keyword in decorator.keywords:
            if (
                keyword.arg == "permission"
                and _permission_name(keyword.value) == permission
            ):
                return True
    return False


def _has_call_with_permission(
    function_node: ast.FunctionDef, callee: str, permission: str
) -> bool:
    for call in ast.walk(function_node):
        if not isinstance(call, ast.Call):
            continue
        if _call_name(call.func) != callee:
            continue
        if not call.args:
            continue
        if _permission_name(call.args[1 if len(call.args) > 1 else 0]) == permission:
            return True
    return False


def _has_call_name(function_node: ast.FunctionDef, callee: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == callee
        for node in ast.walk(function_node)
    )


def test_permission_matrix_scoped_roles(monkeypatch):
    """Matrix coverage for entity-scoped permissions by role."""
    matrix = {
        "cashier": {
            "USER_INVITE": False,
            "USER_VIEW_ALL": False,
            "USER_ROLE_ASSIGN": False,
            "USER_ROLE_DELETE": False,
            "ENTITY_VIEW": True,
            "ENTITY_UPDATE": False,
            "MODULE_VIEW": True,
            "MODULE_MANAGE": False,
            "SALES_METHOD_VIEW": True,
            "SALES_METHOD_CREATE": False,
            "SALES_METHOD_UPDATE": False,
            "SALES_METHOD_DELETE": False,
            "SALES_METHOD_REORDER": False,
            "COA_VIEW": True,
            "COA_CREATE": False,
            "COA_UPDATE": False,
            "COA_DELETE": False,
            "XERO_SETTINGS_VIEW": True,
            "XERO_SETTINGS_UPDATE": False,
            "REPORT_VIEW_OWN": True,
            "REPORT_VIEW_ENTITY": True,
            "REPORT_EDIT_OWN": True,
            "REPORT_EDIT_ENTITY": False,
            "REPORT_DELETE_OWN": True,
            "REPORT_DELETE_ENTITY": False,
            "REPORT_PUBLISH": False,
        },
        "shop_manager": {
            "USER_INVITE": True,
            "USER_VIEW_ALL": True,
            "USER_ROLE_ASSIGN": True,
            "USER_ROLE_DELETE": False,
            "ENTITY_VIEW": True,
            "ENTITY_UPDATE": False,
            "MODULE_VIEW": True,
            "MODULE_MANAGE": False,
            "SALES_METHOD_VIEW": True,
            "SALES_METHOD_CREATE": False,
            "SALES_METHOD_UPDATE": False,
            "SALES_METHOD_DELETE": False,
            "SALES_METHOD_REORDER": False,
            "COA_VIEW": True,
            "COA_CREATE": False,
            "COA_UPDATE": False,
            "COA_DELETE": False,
            "XERO_SETTINGS_VIEW": True,
            "XERO_SETTINGS_UPDATE": False,
            "REPORT_VIEW_OWN": True,
            "REPORT_VIEW_ENTITY": True,
            "REPORT_EDIT_OWN": True,
            "REPORT_EDIT_ENTITY": True,
            "REPORT_DELETE_OWN": True,
            "REPORT_DELETE_ENTITY": True,
            "REPORT_PUBLISH": False,
        },
        "accountant": {
            "USER_INVITE": True,
            "USER_VIEW_ALL": True,
            "USER_ROLE_ASSIGN": True,
            "USER_ROLE_DELETE": True,
            "ENTITY_VIEW": True,
            "ENTITY_UPDATE": True,
            "MODULE_VIEW": True,
            "MODULE_MANAGE": False,
            "SALES_METHOD_VIEW": True,
            "SALES_METHOD_CREATE": True,
            "SALES_METHOD_UPDATE": True,
            "SALES_METHOD_DELETE": True,
            "SALES_METHOD_REORDER": True,
            "COA_VIEW": True,
            "COA_CREATE": True,
            "COA_UPDATE": True,
            "COA_DELETE": True,
            "XERO_SETTINGS_VIEW": True,
            "XERO_SETTINGS_UPDATE": True,
            "REPORT_VIEW_OWN": True,
            "REPORT_VIEW_ENTITY": True,
            "REPORT_EDIT_OWN": True,
            "REPORT_EDIT_ENTITY": True,
            "REPORT_DELETE_OWN": True,
            "REPORT_DELETE_ENTITY": True,
            "REPORT_PUBLISH": True,
        },
        "admin": {
            "USER_INVITE": True,
            "USER_VIEW_ALL": True,
            "USER_ROLE_ASSIGN": True,
            "USER_ROLE_DELETE": True,
            "ENTITY_VIEW": True,
            "ENTITY_UPDATE": True,
            "MODULE_VIEW": True,
            "MODULE_MANAGE": True,
            "SALES_METHOD_VIEW": True,
            "SALES_METHOD_CREATE": True,
            "SALES_METHOD_UPDATE": True,
            "SALES_METHOD_DELETE": True,
            "SALES_METHOD_REORDER": True,
            "COA_VIEW": True,
            "COA_CREATE": True,
            "COA_UPDATE": True,
            "COA_DELETE": True,
            "XERO_SETTINGS_VIEW": True,
            "XERO_SETTINGS_UPDATE": True,
            "REPORT_VIEW_OWN": True,
            "REPORT_VIEW_ENTITY": True,
            "REPORT_EDIT_OWN": True,
            "REPORT_EDIT_ENTITY": True,
            "REPORT_DELETE_OWN": True,
            "REPORT_DELETE_ENTITY": True,
            "REPORT_PUBLISH": True,
        },
        "super_admin": {
            "USER_INVITE": True,
            "USER_VIEW_ALL": True,
            "USER_ROLE_ASSIGN": True,
            "USER_ROLE_DELETE": True,
            "ENTITY_VIEW": True,
            "ENTITY_UPDATE": True,
            "MODULE_VIEW": True,
            "MODULE_MANAGE": True,
            "SALES_METHOD_VIEW": True,
            "SALES_METHOD_CREATE": True,
            "SALES_METHOD_UPDATE": True,
            "SALES_METHOD_DELETE": True,
            "SALES_METHOD_REORDER": True,
            "COA_VIEW": True,
            "COA_CREATE": True,
            "COA_UPDATE": True,
            "COA_DELETE": True,
            "XERO_SETTINGS_VIEW": True,
            "XERO_SETTINGS_UPDATE": True,
            "REPORT_VIEW_OWN": True,
            "REPORT_VIEW_ENTITY": True,
            "REPORT_EDIT_OWN": True,
            "REPORT_EDIT_ENTITY": True,
            "REPORT_DELETE_OWN": True,
            "REPORT_DELETE_ENTITY": True,
            "REPORT_PUBLISH": True,
        },
    }

    for role, expectations in matrix.items():
        membership = SimpleNamespace(role=role, approved=True)

        def _membership_for(_user_id, _entity_id):
            return membership

        monkeypatch.setattr(permission_policy, "_membership_for", _membership_for)

        user = SimpleNamespace(id="u-1", system_role="normal")
        for permission_name, expected in expectations.items():
            permission = Permission[permission_name]
            assert has_permission(user, permission, entity_id="entity-1") is expected, (
                f"{role} expects {permission_name}={expected} for entity-scoped check"
            )

        # non-scoped ENTITY_CREATE is special and now available to any authenticated user
        assert has_permission(user, Permission.ENTITY_CREATE) is True


def test_permission_matrix_scoped_permissions_require_membership(monkeypatch):
    """Entity-scoped permissions must fail when membership does not exist."""
    user = SimpleNamespace(id="u-1", system_role="normal")
    monkeypatch.setattr(
        permission_policy,
        "_membership_for",
        lambda *_args, **_kwargs: None,
    )

    for permission_name in [
        "USER_INVITE",
        "USER_VIEW_ALL",
        "USER_ROLE_ASSIGN",
        "USER_ROLE_DELETE",
        "ENTITY_VIEW",
        "ENTITY_UPDATE",
        "MODULE_VIEW",
        "MODULE_MANAGE",
        "SALES_METHOD_VIEW",
        "SALES_METHOD_CREATE",
        "SALES_METHOD_UPDATE",
        "SALES_METHOD_DELETE",
        "SALES_METHOD_REORDER",
        "COA_VIEW",
        "COA_CREATE",
        "COA_UPDATE",
        "COA_DELETE",
        "XERO_SETTINGS_VIEW",
        "XERO_SETTINGS_UPDATE",
        "REPORT_VIEW_OWN",
        "REPORT_VIEW_ENTITY",
        "REPORT_EDIT_OWN",
        "REPORT_EDIT_ENTITY",
        "REPORT_DELETE_OWN",
        "REPORT_DELETE_ENTITY",
        "REPORT_PUBLISH",
    ]:
        assert has_permission(user, Permission[permission_name], entity_id="entity-1") is False


@pytest.mark.parametrize(
    ("report_owner", "viewer_role", "viewer_name", "expected_view", "expected_edit", "expected_delete"),
    [
        ("owner", "cashier", "owner", True, True, True),
        ("owner", "cashier", "other", True, False, False),
        ("owner", "shop_manager", "other", True, True, True),
        ("owner", "accountant", "other", True, True, True),
        ("owner", "admin", "other", True, True, True),
        ("owner", "super_admin", "other", True, True, True),
    ],
)
def test_report_ownership_helpers_follow_matrix(
    monkeypatch, report_owner, viewer_role, viewer_name, expected_view, expected_edit, expected_delete
):
    report = SimpleNamespace(company="entity-1", uploaded_by="owner")

    def _membership_for(_user_id, _entity_id):
        return SimpleNamespace(role=viewer_role, approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership_for)

    actor = SimpleNamespace(
        id="actor-id",
        username=viewer_name,
        system_role="normal",
    )

    assert can_view_report(actor, report) is expected_view
    assert can_edit_report(actor, report) is expected_edit
    assert can_delete_report(actor, report) is expected_delete


def test_entity_membership_context_is_required_for_report_helpers(monkeypatch):
    actor = SimpleNamespace(id="actor", username="owner", system_role="normal")
    report = SimpleNamespace(company="entity-1", uploaded_by="owner")

    monkeypatch.setattr(permission_policy, "_membership_for", lambda *_args, **_kwargs: None)

    assert can_view_report(actor, report) is False
    assert can_edit_report(actor, report) is False
    assert can_delete_report(actor, report) is False


@pytest.mark.parametrize(
    ("path", "function_name", "permission"),
    [
        (
            "blueprints/user_management/routes/create_user.py",
            "create_user",
            "USER_INVITE",
        ),
        (
            "blueprints/user_management/routes/roles.py",
            "update_user_role",
            "USER_ROLE_ASSIGN",
        ),
        (
            "blueprints/user_management/routes/roles.py",
            "delete_user_role",
            "USER_ROLE_DELETE",
        ),
        # ``entity_create`` (ENTITY_CREATE) is not in this list: the rule is "any signed-in
        # user" (services/permission_policy.has_permission), which ``@login_required`` on the
        # route already is - the GET redirects to the onboarding wizard, the POST is the
        # legacy fallback. ENTITY_CREATE stays in the matrix as the statement of that rule.
        # ``delete_entity`` (ENTITY_DELETE) went with the entity soft-delete in C2 of
        # docs/modernisation/modernisation_plan.md: entity_status has no 'deleted' and nothing linked to
        # the route. The permission stays in the matrix for the day a real delete exists.
        (
            "blueprints/entity/routes/settings.py",
            "entity_settings_users",
            "USER_VIEW_ALL",
        ),
        # The poll behind the Users tab serves the same rows as the page above, so
        # it has to be gated the same way — otherwise it is a way around that page.
        (
            "blueprints/entity/routes/settings.py",
            "entity_settings_users_presence",
            "USER_VIEW_ALL",
        ),
        # the Module tab is a hand-over to minty-web's page (its writes live in
        # minty-billing-api since 2026-10-01); the view permission still gates the door
        (
            "blueprints/entity/routes/settings.py",
            "entity_settings_module",
            "MODULE_VIEW",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "xero_reconnect",
            "XERO_SETTINGS_UPDATE",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "get_latest_xero_bank_transactions",
            "XERO_SETTINGS_VIEW",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "update_bank_transaction",
            "XERO_SETTINGS_UPDATE",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "get_xero_sync_status",
            "XERO_SETTINGS_VIEW",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "disconnect_from_xero",
            "XERO_SETTINGS_UPDATE",
        ),
        (
            "blueprints/xero/routes/routes.py",
            "get_entity_xero_data",
            "XERO_SETTINGS_VIEW",
        ),
        (
            "blueprints/report/routes/submitted.py",
            "report_submitted_publish_to_xero",
            "REPORT_PUBLISH",
        ),
        ("blueprints/report/routes/create.py", "create_report", "REPORT_EDIT_OWN"),
        (
            "blueprints/report/routes/opening.py",
            "report_opening",
            "REPORT_EDIT_OWN",
        ),
        (
            "blueprints/report/routes/sales.py",
            "report_sale",
            "REPORT_EDIT_OWN",
        ),
        (
            "blueprints/report/routes/expense.py",
            "report_expense",
            "REPORT_EDIT_OWN",
        ),
        (
            "blueprints/report/routes/cash_count.py",
            "report_cash_count",
            "REPORT_EDIT_OWN",
        ),
        (
            "blueprints/report/routes/deposit.py",
            "report_deposit",
            "REPORT_EDIT_OWN",
        ),
    ],
)
def test_matrix_routes_use_expected_permission_checks(path, function_name, permission):
    function_node = _read_function(ROOT / path, function_name)
    permission_name = permission

    if not _has_decorator_permission(function_node, permission_name):
        assert _has_call_with_permission(function_node, "has_permission", permission_name)

    assert (
        _has_decorator_permission(function_node, permission_name)
        or _has_call_with_permission(function_node, "has_permission", permission_name)
        or _has_call_with_permission(
            function_node, "has_permission_by_user_id", permission_name
        )
    )


def test_entity_settings_entity_has_coa_and_entity_update_checks():
    function_node = _read_function(
        ROOT / "blueprints/entity/routes/settings.py",
        "entity_settings_entity",
    )

    assert _has_decorator_permission(function_node, "COA_VIEW")
    assert _has_call_with_permission(function_node, "has_permission", "ENTITY_UPDATE")
    assert _has_call_with_permission(function_node, "has_permission", "COA_UPDATE")
    assert _has_call_with_permission(function_node, "has_permission", "COA_CREATE")
    assert _has_call_with_permission(function_node, "has_permission", "COA_DELETE")


@pytest.mark.parametrize(
    ("path", "function_name", "permission", "permission_caller"),
    [
        (
            "blueprints/entity/services/payment_methods.py",
            "list_payment_methods",
            "SALES_METHOD_VIEW",
            "has_permission_by_user_id",
        ),
        (
            "blueprints/entity/services/payment_methods.py",
            "add_payment_method",
            "SALES_METHOD_CREATE",
            "has_permission_by_user_id",
        ),
        (
            "blueprints/entity/services/payment_methods.py",
            "update_payment_method",
            "SALES_METHOD_UPDATE",
            "has_permission_by_user_id",
        ),
        (
            "blueprints/entity/services/payment_methods.py",
            "delete_payment_method",
            "SALES_METHOD_DELETE",
            "has_permission_by_user_id",
        ),
        (
            "blueprints/entity/services/payment_methods.py",
            "reorder_payment_methods",
            "SALES_METHOD_REORDER",
            "has_permission_by_user_id",
        ),
    ],
)
def test_sales_method_service_functions_reference_expected_permissions(
    path, function_name, permission, permission_caller
):
    function_node = _read_function(ROOT / path, function_name)
    assert _has_call_with_permission(function_node, permission_caller, permission)


@pytest.mark.parametrize(
    ("path", "function_name", "helper", "expected_permission"),
    [
        ("blueprints/report/routes/report_detail.py", "report_detail", "can_view_report", None),
        ("blueprints/report/routes/report_detail.py", "edit_report", "has_permission", "REPORT_EDIT_OWN"),
        ("blueprints/report/routes/report_detail.py", "delete_report", "can_delete_report", None),
        ("blueprints/report/routes/submitted.py", "report_submitted", "can_view_report", None),
        ("blueprints/report/routes/export_screenshot.py", "generate_pdf_report", "can_view_report", None),
        ("blueprints/report/routes/export_screenshot.py", "report_screenshot", "can_view_report", None),
        ("blueprints/report/routes/history.py", "entity_report_history", "has_permission", "REPORT_EDIT_ENTITY"),
    ],
)
def test_report_routes_use_permission_helpers(path, function_name, helper, expected_permission):
    function_node = _read_function(ROOT / path, function_name)
    if helper == "has_permission":
        assert _has_call_with_permission(function_node, "has_permission", expected_permission)
    else:
        assert _has_call_name(function_node, helper)
