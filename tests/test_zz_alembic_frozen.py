"""Alembic is frozen (owner, 2026-10-30): every schema change is a minty-db migration.

``migrations/`` stays only so ``scripts/schema_migration/rehearse.py`` can lift an old
pettycashv2 dump to head. This fails if any file there is added, changed or removed - a new
revision here would be a second schema owner. The manifest is ``tests/_baseline/alembic_frozen.json``
(sha256 of each tracked file, line endings normalised).
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "_baseline" / "alembic_frozen.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_the_alembic_chain_is_frozen():
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    present = {
        p.relative_to(ROOT).as_posix(): _digest(p)
        for p in (ROOT / "migrations").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    added = sorted(set(present) - set(frozen))
    removed = sorted(set(frozen) - set(present))
    changed = sorted(f for f in set(present) & set(frozen) if present[f] != frozen[f])
    assert (added, removed, changed) == ([], [], []), (
        "migrations/ is frozen: put the schema change in minty-db instead "
        f"(added {added}, removed {removed}, changed {changed})"
    )


def test_no_workflow_runs_alembic_against_a_database():
    workflows = ROOT / ".github" / "workflows"
    hits = [p.name for p in workflows.glob("*.yml") if "flask db upgrade" in p.read_text(encoding="utf-8")]
    assert hits == []
