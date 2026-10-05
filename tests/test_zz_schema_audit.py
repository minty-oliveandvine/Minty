"""The four repos' models match the schema the harness built - the phase C gate, as a test.

``docs/schema/generators/audit_models.py`` diffs every SQLAlchemy model in Minty and every
Django model in minty-payment-request-api, minty-onboarding-api and minty-billing-api (Part 2, 2026-09-21)
against a live database: a table the schema no longer has, a column the schema no longer has
(which breaks every SELECT on the model), a declared type that no longer matches - and a repo
that is not checked out beside Minty (``MINTY_REPOS_ROOT``), which used to read as 0 findings.
Phase C took it from 287 findings to 0 (docs/modernisation/modernisation_plan.md); this keeps
it there. Postgres mode only: the database it reads is the one ``tests/pg_harness.py`` built
from ``01_schema_rebased.sql`` for this worker.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pg_harness

AUDIT = Path(__file__).resolve().parents[1] / "docs" / "schema" / "generators" / "audit_models.py"


@pytest.mark.skipif(not pg_harness.enabled(), reason="the audit reads a Postgres build of 01_schema_rebased.sql")
def test_every_model_in_the_four_repos_matches_the_schema(built_database):
    env = dict(os.environ, PYTHONUTF8="1", AUDIT_URI=built_database.uri,
               AUDIT_SCHEMA=pg_harness.APP_SCHEMA, AUDIT_STRICT="1")
    result = subprocess.run([sys.executable, str(AUDIT)], capture_output=True, text=True,
                            encoding="utf-8", env=env)
    summary = [l for l in result.stdout.splitlines() if l.startswith("TOTAL")]
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert summary and summary[0].startswith("TOTAL 0 "), summary
