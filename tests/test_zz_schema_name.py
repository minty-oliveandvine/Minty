"""The schema name is a setting, not a literal: ``blueprints/shared/schema.SCHEMA``.

Every model, FK string, enum, raw query and the Flask-Session table read it from there, and
``tests/pg_harness.py`` builds the schema under the same variable - so a full run with
``MINTY_DB_SCHEMA=pettycash_alt`` is the proof. This test is the cheap guard between such
runs: no string constant in application code may carry the name. Comments and docstrings
are free to say it; the Alembic revisions (the OLD ``pettycashv2`` database) and the schema
SQL files are outside the rule by design.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "pettycashv3"
DIRS = ["blueprints", "models", "services", "pettycash", "cli", "scripts"]
ALLOWED = {
    "blueprints/shared/schema.py",
    # reads the same variable with the same default, deliberately without importing the app
    "scripts/subscription/copy_replay_to_rds.py",
}
SKIP_PREFIXES = ("scripts/schema_migration/",)  # the pipeline names the schema it builds


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _offenders() -> list[str]:
    hits = []
    for d in DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED or rel.startswith(SKIP_PREFIXES):
                continue
            source = path.read_text(encoding="utf-8-sig")
            if NAME not in source:
                continue
            tree = ast.parse(source)
            docs = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and NAME in node.value and id(node) not in docs:
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_application_string_carries_the_schema_name():
    assert _offenders() == [], "read blueprints/shared/schema.SCHEMA instead of spelling the schema"


def test_the_constant_follows_the_environment(monkeypatch):
    import importlib

    from blueprints.shared import schema

    monkeypatch.setenv("MINTY_DB_SCHEMA", "pettycash_alt")
    reloaded = importlib.reload(schema)
    try:
        assert reloaded.SCHEMA == "pettycash_alt" and reloaded.qualified("report") == "pettycash_alt.report"
    finally:
        monkeypatch.delenv("MINTY_DB_SCHEMA")
        importlib.reload(schema)
