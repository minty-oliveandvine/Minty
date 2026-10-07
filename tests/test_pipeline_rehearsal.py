"""The migration pipeline as a test. Opt-in: needs a dump and a Postgres server.

    MINTY_REHEARSAL_DUMP=backups/production-backup_20260915.dump pytest -m pipeline tests/test_pipeline_rehearsal.py

Runs scripts/schema_migration/rehearse.py end to end into a scratch database
(dropped and recreated each time) and passes only when every check it contains
is green - see docs/schema/README.md. Not part of the default run: it takes a few
minutes and it needs the real dataset.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DUMP = os.environ.get("MINTY_REHEARSAL_DUMP")

pytestmark = pytest.mark.pipeline


@pytest.mark.skipif(not DUMP, reason="set MINTY_REHEARSAL_DUMP to a pg_dump -Fc of pettycashv3")
def test_rehearsal_is_all_green(tmp_path: Path) -> None:
    dbname = os.environ.get("MINTY_REHEARSAL_DB", "pcreh_pytest")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "schema_migration" / "rehearse.py"),
         "--dump", DUMP, "--db", dbname, "--log-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(REPO),
        env=dict(os.environ, PYTHONUTF8="1"),
    )
    log = (tmp_path / f"{dbname}_rehearsal.log").read_text(encoding="utf-8") if (tmp_path / f"{dbname}_rehearsal.log").exists() else proc.stdout
    assert proc.returncode == 0, log[-6000:]
    assert "ALL GREEN" in log
    assert "***" not in log, "a check line was not OK:\n" + "\n".join(line for line in log.splitlines() if "***" in line)
    assert (tmp_path / f"{dbname}_not_carried.md").exists()
