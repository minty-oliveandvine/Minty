"""Flask is not a subscription engine any more - and must not quietly become one again.

minty-subscription-api is the one writer of the subscription tables and the only service that
talks to Stripe (Flask's copy of the engine was deleted on 2026-10-06). Two writers there is a
money bug, so this guard fails the moment application code:

* imports ``stripe`` or ``apscheduler`` (or the requirements pin them again), or
* reaches into ``blueprints.subscription.services`` for anything but ``store_ro`` - the
  read-only questions the rest of Flask still asks.

Checked on the import statements (AST), so comments and docstrings may still name them.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ["blueprints", "models", "services", "pettycash", "cli", "scripts", "main.py", "config.py"]
FORBIDDEN_TOP = {"stripe", "apscheduler"}
SERVICES = "blueprints.subscription.services"
ALLOWED_SERVICES = {f"{SERVICES}.store_ro"}


def _python_files():
    for entry in DIRS:
        path = ROOT / entry
        if path.is_file():
            yield path
        else:
            yield from sorted(path.rglob("*.py"))


def _imports(tree: ast.AST):
    """Every module an import statement names, ``from x import y`` as ``x.y`` too."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _offenders() -> list[str]:
    hits = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for lineno, name in _imports(tree):
            if name.split(".")[0] in FORBIDDEN_TOP:
                hits.append(f"{rel}:{lineno} imports {name}")
            elif name.startswith(f"{SERVICES}.") and not any(
                name == ok or name.startswith(f"{ok}.") for ok in ALLOWED_SERVICES
            ):
                hits.append(f"{rel}:{lineno} imports {name}")
    return hits


def test_no_application_code_is_a_subscription_engine():
    assert _offenders() == [], (
        "subscription writes and Stripe belong to minty-subscription-api; Flask may only "
        "read through blueprints.subscription.services.store_ro"
    )


def test_the_requirements_pin_neither_stripe_nor_apscheduler():
    for name in ("requirements.txt", "pyproject.toml"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        for package in FORBIDDEN_TOP:
            assert f"{package}==" not in text and f'"{package}' not in text, f"{name} pins {package}"


def test_the_guard_would_notice_an_offender(tmp_path):
    """Proof the import walk can fail: a forbidden import must be reported."""
    tree = ast.parse("import stripe\nfrom blueprints.subscription.services import checkout\n")
    names = [name for _line, name in _imports(tree)]
    assert "stripe" in names
    assert f"{SERVICES}.checkout" in names
