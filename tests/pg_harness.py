"""Build a throwaway PostgreSQL database from ``docs/schema/01_schema_rebased.sql``.

WHY THIS EXISTS

Until phase C the suite ran on SQLite, and every DB-backed test file built its tables
with ``db.create_all()``. That built whatever the *models* said — the shape the code had
that day — and SQLite has no enums, no uuid type and no ``numeric`` money, so a green run
said nothing about the schema the code was being moved to. This module builds the real
thing, from the file that is the source of truth, every time; since C10 (2026-09-17) it
is the only mode.

The server is ``MINTY_TEST_PG_URI`` (a superuser/owner URI to a Postgres *server*; its
database part is only used as the maintenance connection), or, when that is unset, the
server of ``DATABASE_URL`` (the environment's, else ``.env``'s) with the database swapped for
``postgres``. Either URI's ``?schema=`` names the schema the suite runs under (default
``pettycashv3``); it is stripped before the URI reaches psql or psycopg2::

    MINTY_TEST_PG_URI=postgresql://postgres:***@localhost:5432/postgres pytest
    MINTY_TEST_PG_URI='postgresql://postgres:***@localhost:5432/postgres?schema=pettycash_alt' pytest
    pytest                                   # the .env server

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

from services.app_runtime.env import DEFAULT_SCHEMA, parse_database_url, with_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_SQL = REPO_ROOT / "docs" / "schema" / "01_schema_rebased.sql"
BUILT_SCHEMA = "pettycash_test"  # what 01_schema_rebased.sql creates


def _server_uri() -> str | None:
    """MINTY_TEST_PG_URI, else DATABASE_URL (environment, then .env) on ``postgres``; as given,
    ``?schema=`` included. None when there is neither."""
    uri = os.environ.get("MINTY_TEST_PG_URI")
    if uri:
        return uri
    uri = os.environ.get("DATABASE_URL")
    if not uri:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL=") and line.split("=", 1)[1].startswith("postgres"):
                    uri = line.split("=", 1)[1].strip()
    return _with_database(uri, "postgres") if uri else None


# What every model's __table_args__ says: blueprints/shared/schema.SCHEMA, which is the app's
# DATABASE_URL ?schema= - read here from the harness's own URI (not imported: conftest evicts
# blueprints.* between app builds), and handed to the app on the test database's URL. The
# build renames the schema to THIS, so the whole suite runs under whatever name the URI says -
# `MINTY_TEST_PG_URI=...?schema=pettycash_alt pytest` is the proof nothing is hardcoded.
APP_SCHEMA = parse_database_url(_server_uri()).schema if _server_uri() else DEFAULT_SCHEMA


def admin_uri() -> str:
    """The maintenance URI (libpq form, no ``?schema=``): MINTY_TEST_PG_URI, else
    DATABASE_URL's server on ``postgres``."""
    uri = _server_uri()
    if uri:
        return parse_database_url(uri).libpq
    raise RuntimeError(
        "no Postgres server for the test harness: set MINTY_TEST_PG_URI, or put a "
        "postgresql:// DATABASE_URL in .env (the tests build their own database on it)"
    )


def app_database_url(db_uri: str) -> str:
    """The test database as the app's DATABASE_URL: ``db_uri`` plus ``?schema=APP_SCHEMA``."""
    return with_schema(db_uri, APP_SCHEMA)


def enabled() -> bool:
    """Kept for callers; the harness is the only mode now."""
    return True


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


def test_dbname() -> str:
    """The database this process builds: MINTY_TEST_PG_DBNAME (default ``minty_test``), one
    per pytest-xdist worker (``-n auto``) - workers build and drop their own."""
    dbname = os.environ.get("MINTY_TEST_PG_DBNAME", "minty_test")
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    return f"{dbname}_{worker}" if worker else dbname


def build() -> BuiltDatabase:
    """Create the database, run the schema file, rename the schema. Returns its URI."""
    import psycopg2

    admin = admin_uri()
    dbname = test_dbname()
    keep = os.environ.get("MINTY_TEST_PG_KEEP") == "1"
    schema_sql = Path(os.environ.get("MINTY_TEST_SCHEMA_SQL", DEFAULT_SCHEMA_SQL))

    _drop_database(admin, dbname)
    conn = psycopg2.connect(admin)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\' TEMPLATE template0')
    finally:
        conn.close()

    db_uri = _with_database(admin, dbname)
    try:
        build_schema(db_uri, schema_sql, rename_to=APP_SCHEMA)
    except Exception:
        _drop_database(admin, dbname)
        raise

    return BuiltDatabase(uri=db_uri, dbname=dbname, admin_uri=admin, keep=keep)
