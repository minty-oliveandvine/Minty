"""No log line may interpolate a Xero bearer or refresh token.

``bank_transfer_to_xero`` logged both at INFO until 2026-09-18; the log is shipped off the
box, so that was the token in plain text on a third party's disk. This walks every logger
call in the application and fails on an f-string that formats a value named like a token.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("blueprints", "services", "pettycash", "cli", "utils")
TOKEN_NAMES = re.compile(r"^(access_token|refresh_token|refresh_token_value|id_token|bearer|token)$")
LOG_OBJECTS = {"logger", "logging", "log", "current_app"}


def _formatted_names(node: ast.JoinedStr):
    for value in node.values:
        if not isinstance(value, ast.FormattedValue):
            continue
        expr = value.value
        if isinstance(expr, ast.Name):
            yield expr.id
        elif isinstance(expr, ast.Attribute):
            yield expr.attr


def _is_log_call(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in {"debug", "info", "warning", "error", "exception", "critical", "log"}:
        return False
    base = func.value
    while isinstance(base, ast.Attribute):  # current_app.logger.info
        base = base.value
    return isinstance(base, ast.Name) and base.id in LOG_OBJECTS


def _python_files():
    for folder in SCANNED:
        yield from (ROOT / folder).rglob("*.py")


@pytest.mark.parametrize("path", sorted(_python_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_log_call_formats_a_token(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))  # a few files carry a BOM
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_log_call(node)):
            continue
        for arg in node.args:
            if isinstance(arg, ast.JoinedStr):
                names = [n for n in _formatted_names(arg) if TOKEN_NAMES.match(n)]
                if names:
                    offenders.append(f"line {arg.lineno}: {{{', '.join(names)}}}")
    assert not offenders, f"{path.relative_to(ROOT)} logs a token: {offenders}"
