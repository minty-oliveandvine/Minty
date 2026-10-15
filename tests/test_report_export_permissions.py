from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _get_function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function `{name}` not found in {path}")


def _decorator_names(function_node: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for decorator in function_node.decorator_list:
        target = decorator
        if isinstance(target, ast.Call):
            target = target.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _has_call(function_node: ast.FunctionDef, call_name: str) -> bool:
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == call_name:
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == call_name:
            return True
    return False


def test_report_export_routes_require_auth_and_view_permission():
    route_path = ROOT / "blueprints" / "report" / "routes" / "export_screenshot.py"
    export_fn = _get_function(route_path, "generate_pdf_report")
    screenshot_fn = _get_function(route_path, "report_screenshot")

    assert _has_call(export_fn, "can_view_report")
    assert _has_call(screenshot_fn, "can_view_report")
    assert "login_required" in _decorator_names(screenshot_fn)


def test_reopening_uses_the_report_edit_policy():
    # The Jinja convert-to-draft route and the Petty Cash API's reopen both go through
    # services/report_actions.py::reopen_report (2026-10-15), so the guards live there.
    service_path = ROOT / "blueprints" / "report" / "services" / "report_actions.py"
    reopen_fn = _get_function(service_path, "reopen_report")

    assert _has_call(reopen_fn, "has_permission")


def test_reopening_keeps_the_xero_publish_markers():
    # They are what lets a republish warn that the report was in Xero before.
    service_path = ROOT / "blueprints" / "report" / "services" / "report_actions.py"
    reopen_fn = _get_function(service_path, "reopen_report")

    assigned = {
        target.attr
        for node in ast.walk(reopen_fn)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert "publishing_status" in assigned
    assert "xero_integrated" in assigned


def test_reopening_refuses_a_report_that_is_not_the_latest():
    # Reports chain opening->closing balances; reopening an older report leaves every later
    # report's opening balance dangling. (Behaviour: tests/test_report_actions_state.py.)
    service_path = ROOT / "blueprints" / "report" / "services" / "report_actions.py"
    reopen_fn = _get_function(service_path, "reopen_report")

    raised = {
        node.exc.func.id
        for node in ast.walk(reopen_fn)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
    }
    assert "ReportActionRefused" in raised
    assert _has_call(reopen_fn, "_newer_exists")
