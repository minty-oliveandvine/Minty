"""Flask logs through the standard library - and must not quietly start using loguru again.

Since 2026-10-22 every Minty backend writes one line format (``minty_shared.logctx``) through
stdlib ``logging``; Flask's ``logger`` is ``services/app_runtime/log.py``, loguru's call shape
over the ``minty`` logger. A loguru import would write a second format that carries no trace,
user or entity, so this guard fails the moment any code (tests included) imports it again or
the requirements pin it.

Checked on the import statements (AST), so comments and docstrings may still name it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ["blueprints", "models", "services", "pettycash", "cli", "scripts", "utils", "tests",
        "app.py", "main.py", "config.py"]


def _python_files():
    for entry in DIRS:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.py"))


def test_nothing_imports_loguru():
    hits = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            hits += [f"{path.relative_to(ROOT).as_posix()}:{node.lineno}" for n in names
                     if n.split(".")[0] == "loguru"]
    assert not hits, "loguru is gone; log through services.app_runtime.log: " + ", ".join(hits)


def test_the_requirements_do_not_pin_loguru():
    for name in ("requirements.txt", "pyproject.toml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"(?im)^\s*\"?loguru\b", text), f"{name} pins loguru"
