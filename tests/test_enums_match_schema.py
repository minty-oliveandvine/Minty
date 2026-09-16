"""The code's enums are the database's enums - read from ``01_schema_rebased.sql``, not typed twice.

Three copies of every Postgres enum exist: ``blueprints/shared/enums.py`` (Minty),
``billing-backend/shared_models/enums.py`` and ``onboarding-backend/shared_models/enums.py``
(Django ``TextChoices``). This test parses the ``CREATE TYPE … AS ENUM`` statements out of the
schema file and fails when any copy names a ``pg_name`` the schema lacks, or holds a member set
different from the schema's. It grows with each phase C unit: a new Python enum is covered the
moment it declares ``pg_name``; a Django copy is covered when its class name appears in
``DJANGO_CLASSES``.

The sibling repos are located through ``MINTY_SIBLING_REPOS`` (default: beside this checkout);
a missing sibling is a skip, not a failure, so the test runs on a lone Minty clone.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs" / "schema" / "01_schema_rebased.sql"

# Django copies: class name -> Postgres enum name. Extend per unit (C2: EntityStatus,
# ModuleCode; C4: ReportStatus …).
DJANGO_CLASSES = {
    "SystemRole": "system_role",
    "EntityRole": "entity_role",
}

_ENUM_RE = re.compile(
    r"CREATE TYPE\s+\w+\.(?P<name>\w+)\s+AS ENUM\s*\((?P<members>[^)]*)\)", re.S
)


def schema_enums() -> dict[str, tuple[str, ...]]:
    text = SCHEMA.read_text(encoding="utf-8")
    found = {}
    for m in _ENUM_RE.finditer(text):
        members = tuple(re.findall(r"'([^']*)'", m.group("members")))
        found[m.group("name")] = members
    assert found, f"no CREATE TYPE … AS ENUM in {SCHEMA}"
    return found


@pytest.fixture(scope="module")
def db_enums():
    return schema_enums()


def _minty_enums():
    from blueprints.shared import enums

    out = {}
    for name in dir(enums):
        obj = getattr(enums, name)
        if isinstance(obj, type) and issubclass(obj, enums._DbEnum) and obj is not enums._DbEnum:
            out[obj] = obj.pg_name
    return out


def test_every_minty_enum_matches_the_schema(db_enums):
    seen = _minty_enums()
    assert seen, "blueprints/shared/enums.py declares no enums"
    for cls, pg_name in seen.items():
        assert pg_name in db_enums, f"{cls.__name__}: no enum {pg_name!r} in the schema"
        assert cls.values() == db_enums[pg_name], (
            f"{cls.__name__} ({pg_name}) drifted: code {cls.values()} vs schema {db_enums[pg_name]}"
        )


def _sibling(repo: str) -> Path | None:
    for base in os.environ.get("MINTY_SIBLING_REPOS", str(ROOT.parent)).split(os.pathsep):
        candidate = Path(base) / repo / "shared_models" / "enums.py"
        if candidate.exists():
            return candidate
    return None


def _text_choices_members(path: Path) -> dict[str, tuple[str, ...]]:
    """Member values of each TextChoices class in a Django enums module, without importing
    Django: the file is parsed, and every ``NAME = "value"`` (or ``NAME = "value", "Label"``)
    assignment in a class body is a member."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        members = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                value = stmt.value
                if isinstance(value, ast.Tuple) and value.elts:
                    value = value.elts[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    members.append(value.value)
        out[node.name] = tuple(members)
    return out


@pytest.mark.parametrize("repo", ["billing-backend", "onboarding-backend"])
def test_every_django_copy_matches_the_schema(repo, db_enums):
    path = _sibling(repo)
    if path is None:
        pytest.skip(f"{repo} is not checked out beside Minty (set MINTY_SIBLING_REPOS)")
    classes = _text_choices_members(path)
    for class_name, pg_name in DJANGO_CLASSES.items():
        assert class_name in classes, f"{repo}: shared_models/enums.py has no {class_name}"
        assert classes[class_name] == db_enums[pg_name], (
            f"{repo}.{class_name} ({pg_name}) drifted: {classes[class_name]} vs schema {db_enums[pg_name]}"
        )
