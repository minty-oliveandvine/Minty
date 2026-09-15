# Test-suite baselines

The suite is **not green at HEAD** and some tests only pass in full-suite order, so the only
valid comparison is a full run against a full run. These files are those runs.

| File | What | Command |
|---|---|---|
| `sqlite_head_full.txt` | full run, SQLite (`db.create_all()` from the current models), HEAD `b43d9d5`, 2026-09-15: **62 failed, 29 errors, 1508 passed** | `python -m pytest -q -p no:cacheprovider --no-header -rfE` |
| `sqlite_head_ids.txt` | the non-passing test ids from that run, one per line | derived |
| `postgres_01_current_models_full.txt` | full run against a PostgreSQL database built from `docs/schema/01_schema_rebased.sql` (see `tests/pg_harness.py`), **current models** — every failure that is not in the SQLite list is a schema mismatch the code must absorb (Part 1 phase C) | `MINTY_TEST_PG_URI=postgresql://... python -m pytest -q -p no:cacheprovider --no-header -rfE` |

Compare two runs:

    python tests/_baseline/compare.py tests/_baseline/sqlite_head_full.txt <new-run.txt>

prints tests that newly fail (regressions or, in Postgres mode, schema findings) and tests that
newly pass. Regenerate a baseline only from a clean HEAD, and say which commit in this table.
Always use the venv's interpreter (`.venv/Scripts/python.exe`); the system Python has no pytest.
