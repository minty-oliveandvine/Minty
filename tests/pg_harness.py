"""Build a throwaway PostgreSQL database from ``docs/schema/01_schema_rebased.sql``.

WHY THIS EXISTS

The suite runs on SQLite by default, and every DB-backed test file builds its tables
with ``db.create_all()``. That builds whatever the *models* say — the shape the code
has today — and SQLite has no enums, no uuid type and no ``numeric`` money. So a green
SQLite run says nothing about the schema the code is being moved to. This module
builds the real thing, from the file that is the source of truth, every time.

Opt in with ``MINTY_TEST_PG_URI`` (a superuser/owner URI to a Postgres *server*; its
database part is only used as the maintenance connection)::

    MINTY_TEST_PG_URI=postgresql://postgres:***@localhost:5432/postgres pytest

Knobs:

    MINTY_TEST_PG_DBNAME   database to (re)create           default minty_test
    MINTY_TEST_PG_KEEP=1   leave the database behind for inspection
    MINTY_TEST_SCHEMA_SQL  path to the schema file           default docs/schema/01_schema_rebased.sql
    PG_BIN                 directory holding psql.exe        default: PATH, then C:\\Program Files\\PostgreSQL\\*\\bin

The file creates schema ``pettycash_test``; the models say ``pettycashv3``. The build
ends with ``ALTER SCHEMA pettycash_test RENAME TO pettycashv3`` — the same rename the
rehearsal ends with before the schema is dumped for Supabase (docs/modernisation/modernisation_plan.md,
Part 1 phase E; ``pettycashv3`` is the permanent name, decided 2026-09-16). Enum types, the
``set_updated_at`` trigger function and the ``tracker`` view travel with the schema;
nothing in the file names the schema inside a function body, so the rename is safe.

Never uses ``create_all``. If a model names a column the schema does not have, the
test fails on the SELECT — that failure is the spec for the code change, not a harness
bug.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_SQL = REPO_ROOT / "docs" / "schema" / "01_schema_rebased.sql"
BUILT_SCHEMA = "pettycash_test"  # what 01_schema_rebased.sql creates
APP_SCHEMA = "pettycashv3"       # what every model's __table_args__ says


def enabled() -> bool:
    return bool(os.environ.get("MINTY_TEST_PG_URI"))


def _with_database(uri: str, dbname: str) -> str:
    parts = urlsplit(uri)
    return urlunsplit((parts.scheme, parts.netloc, "/" + dbname, parts.query, parts.fragment))


def _find_psql() -> str:
    pg_bin = os.environ.get("PG_BIN")
    if pg_bin:
        cand = Path(pg_bin) / ("psql.exe" if os.name == "nt" else "psql")
        if cand.exists():
            return str(cand)
    found = shutil.which("psql")
    if found:
        return found
    for cand in sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe"), reverse=True):
        return cand
    raise RuntimeError(
        "psql not found. Set PG_BIN to the PostgreSQL bin directory "
        "(e.g. C:\\Program Files\\PostgreSQL\\18\\bin)."
    )


@dataclass
class BuiltDatabase:
    uri: str
    dbname: str
    admin_uri: str
    keep: bool

    def drop(self) -> None:
        if self.keep:
            return
        _drop_database(self.admin_uri, self.dbname)


def _drop_database(admin_uri: str, dbname: str) -> None:
    import psycopg2

    conn = psycopg2.connect(admin_uri)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Kick our own leftover connections, then drop.
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (dbname,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


def build_schema(db_uri: str, schema_sql: Path = DEFAULT_SCHEMA_SQL, rename_to: str | None = None) -> int:
    """Run ``01_schema_rebased.sql`` into an EXISTING database and return the table count.

    The file drops and recreates ``pettycash_test``; whatever else the database
    holds (a ``pettycashv3`` being migrated, say) is untouched. ``rename_to``
    applies the cutover's rename-swap afterwards — the test suite asks for
    ``pettycashv3`` so the models see the schema they name; the migration
    rehearsal (scripts/schema_migration/rehearse.py) leaves it as built, because
    its loaders address ``pettycash_test`` explicitly.
    """
    import psycopg2

    schema_sql = Path(schema_sql)
    if not schema_sql.exists():
        raise RuntimeError(f"schema file not found: {schema_sql}")

    # psql, not psycopg2: the file has $$-quoted bodies and a DO block, and psql's
    # parser is the one the file was written for. ON_ERROR_STOP so a half-built
    # schema cannot masquerade as a built one.
    env = dict(os.environ, PGCLIENTENCODING="UTF8")
    proc = subprocess.run(
        [_find_psql(), db_uri, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(schema_sql)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"schema build failed (psql exit {proc.returncode}):\n{proc.stderr[-4000:]}"
        )

    schema = rename_to or BUILT_SCHEMA
    conn = psycopg2.connect(db_uri)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            if rename_to:
                cur.execute(f"ALTER SCHEMA {BUILT_SCHEMA} RENAME TO {rename_to}")
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (schema,),
            )
            (n_tables,) = cur.fetchone()
    finally:
        conn.close()
    if n_tables < 50:
        raise RuntimeError(f"schema build produced only {n_tables} tables in {schema}")
    return n_tables


def build() -> BuiltDatabase:
    """Create the database, run the schema file, rename the schema. Returns its URI."""
    import psycopg2

    admin_uri = os.environ["MINTY_TEST_PG_URI"]
    dbname = os.environ.get("MINTY_TEST_PG_DBNAME", "minty_test")
    # one database per pytest-xdist worker (``-n auto``): workers build and drop their own
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        dbname = f"{dbname}_{worker}"
    keep = os.environ.get("MINTY_TEST_PG_KEEP") == "1"
    schema_sql = Path(os.environ.get("MINTY_TEST_SCHEMA_SQL", DEFAULT_SCHEMA_SQL))

    _drop_database(admin_uri, dbname)
    conn = psycopg2.connect(admin_uri)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\' TEMPLATE template0')
    finally:
        conn.close()

    db_uri = _with_database(admin_uri, dbname)
    try:
        build_schema(db_uri, schema_sql, rename_to=APP_SCHEMA)
    except Exception:
        _drop_database(admin_uri, dbname)
        raise

    return BuiltDatabase(uri=db_uri, dbname=dbname, admin_uri=admin_uri, keep=keep)
