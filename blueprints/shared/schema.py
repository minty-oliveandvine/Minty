"""The database schema every model lives in - one name, read once, from the environment.

``pettycashv3`` is the permanent production schema (docs/modernisation/modernisation_plan.md,
decided 2026-09-16); ``DATABASE_URL``'s ``?schema=`` exists so the name is a setting rather
than a literal in seventy files: the test harness builds the schema under whatever name its
URL says (tests/pg_harness.py), and Part 2's ``minty-db`` inherits a knob instead of a
find-and-replace. The sibling Django APIs read the same ``?schema=``, with the same default,
into ``config.settings.DB_SCHEMA`` for their ``search_path``.

Everything that names the schema reads it from here: ``__table_args__`` on every model,
every ``ForeignKey("<schema>.table.column")`` string, ``pg_enum(schema=...)``, the
Flask-Session table, raw SQL. ``tests/test_zz_schema_name.py`` fails on any other literal.

NOT read from here, by design: the Alembic revisions (they describe the OLD ``pettycashv2``
database and must stay literal) and ``docs/schema/*.sql`` (the files are the name).
"""

from __future__ import annotations

from dotenv import load_dotenv

from services.app_runtime.env import database_schema

# Read at import, which can be before the app's own load_dotenv: a ?schema= that lives only
# in .env must still name the schema the models are mapped to.
load_dotenv()

SCHEMA: str = database_schema()


def qualified(name: str) -> str:
    """``schema.table`` for raw SQL: ``qualified("report")`` -> ``"pettycashv3.report"``."""
    return f"{SCHEMA}.{name}"
