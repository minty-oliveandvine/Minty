"""The schema name is a setting, not a literal: ``blueprints/shared/schema.SCHEMA``.

Every model, FK string, enum, raw query and the Flask-Session table read it from there (it is
``DATABASE_URL``'s ``?schema=``), and ``tests/pg_harness.py`` builds the schema under the same
name - so a full run with ``MINTY_TEST_PG_URI=...?schema=pettycash_alt`` is the proof. This test is the cheap guard between such
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
    # the default when DATABASE_URL carries no ?schema= (blueprints/shared/schema.py reads it)
    "services/app_runtime/env.py",
    # the name docs/schema/seed_catalogue.sql is WRITTEN against, which this script rewrites to
    # whatever schema it is loading into. That literal is a property of the file, not of the
    # environment - the SQL files are outside this rule by design (see the module docstring), so
    # the one script that rewrites them has to know the name they use.
    "scripts/load_catalogue.py",
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

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db?sslmode=disable&schema=pettycash_alt")
    reloaded = importlib.reload(schema)
    try:
        assert reloaded.SCHEMA == "pettycash_alt" and reloaded.qualified("report") == "pettycash_alt.report"
    finally:
        monkeypatch.undo()
        importlib.reload(schema)
