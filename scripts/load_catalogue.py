"""Load docs/schema/seed_catalogue.sql into ONE named schema, and prove it landed.

    .venv/Scripts/python.exe scripts/load_catalogue.py                         # $DATABASE_URL, its ?schema=
    .venv/Scripts/python.exe scripts/load_catalogue.py --schema development
    .venv/Scripts/python.exe scripts/load_catalogue.py --uri postgresql://... --dry-run

Why this exists
---------------
``seed_catalogue.sql`` names its schema literally (``INSERT INTO pettycashv3.billing_plan``),
which is the convention for ``docs/schema/*.sql`` - ``blueprints/shared/schema.py`` says it out
loud: "NOT read from here, by design: ... docs/schema/*.sql (the files are the name)". That is
right for the file and wrong for any environment whose schema is called something else: piping
the file into psql against a ``development`` schema writes the catalogue into ``pettycashv3``
instead, because the statements say so. Where ``pettycashv3`` is production, that is a write into
production.

So the substitution happens here, once, with a guard that it actually happened - rather than in
each caller's shell, where a silent no-op looks exactly like success.

What it does
------------
1. Resolves the target schema: ``--schema``, else the URI's ``?schema=``, else ``pettycashv3``.
2. Refuses a schema name that is not a plain identifier (it is interpolated into SQL).
3. Refuses to run if the schema does not exist - build it first with
   ``pg_harness.build_schema(uri, rename_to="<schema>")``.
4. Rewrites ``pettycashv3.`` to ``<schema>.`` when they differ, and FAILS if nothing was
   rewritten - a renamed prefix would otherwise seed the wrong place without a word.
5. Runs the file in one transaction, then COUNTS ``billing_plan``, ``billing_policy`` and the
   HKD ``currency_info`` row, and fails loudly if any is empty. A cold start with no
   ``billing_plan`` is the bug CI caught, where a trial start had no plan and the suite read as
   a 45-second navigation timeout.

Idempotent, because the file is: every INSERT is ``ON CONFLICT DO NOTHING`` and nothing is ever
UPDATEd, so a price edited in the database is never silently reverted. Changing a price or a
window means changing the row AND ``seed_catalogue.sql`` together.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = REPO_ROOT / "docs" / "schema" / "seed_catalogue.sql"

# The schema the file is written against. Everything else is a rewrite of this.
FILE_SCHEMA = "pettycashv3"

# Identifiers we are willing to interpolate: no quoting games, no dots, no spaces.
SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def split_schema(uri: str) -> tuple[str, str | None]:
    """``(uri_without_schema_param, schema_or_None)``.

    psycopg2 does not understand ``?schema=``; it has to come off before connecting. Same
    reason tests/pg_harness.py strips it.
    """
    parts = urlsplit(uri)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    schema = next((v for k, v in pairs if k == "schema"), None)
    kept = "&".join(f"{k}={v}" for k, v in pairs if k != "schema")
    return urlunsplit(parts._replace(query=kept)), (schema or None)


def redact(uri: str) -> str:
    """The URI with its password removed - safe to print in an error."""
    parts = urlsplit(uri)
    if parts.password:
        netloc = f"{parts.username}:***@{parts.hostname}"
        if parts.port:
            netloc += f":{parts.port}"
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--uri", default=os.environ.get("DATABASE_URL", ""), help="Postgres URI (default: $DATABASE_URL)"
    )
    parser.add_argument(
        "--schema", default=None, help="target schema (default: the URI's ?schema=, else pettycashv3)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check the schema exists and report what would run; load nothing",
    )
    args = parser.parse_args()

    if not args.uri:
        print("error: no database URI. Pass --uri or set DATABASE_URL.", file=sys.stderr)
        return 2
    if not CATALOGUE.is_file():
        print(f"error: {CATALOGUE} is missing.", file=sys.stderr)
        return 2

    uri, uri_schema = split_schema(args.uri)
    schema = args.schema or uri_schema or FILE_SCHEMA

    if not SAFE_IDENTIFIER.match(schema):
        print(
            f"error: {schema!r} is not a plain lower-case identifier. The schema name is "
            "interpolated into SQL, so only [a-z_][a-z0-9_]* is accepted.",
            file=sys.stderr,
        )
        return 2

    sql = CATALOGUE.read_text(encoding="utf-8")
    if schema != FILE_SCHEMA:
        sql, rewrites = re.subn(rf"\b{re.escape(FILE_SCHEMA)}\.", f"{schema}.", sql)
        if rewrites == 0:
            print(
                f"error: nothing to rewrite - {CATALOGUE.name} holds no '{FILE_SCHEMA}.' prefix, so "
                f"it would have seeded the wrong schema in silence. Has the file changed?",
                file=sys.stderr,
            )
            return 1
        print(f"rewrote {rewrites} '{FILE_SCHEMA}.' reference(s) to '{schema}.'")
    else:
        print(f"schema is {FILE_SCHEMA}: the file is used as written")

    print(f"target: {redact(uri)}  schema={schema}")

    # Imported late so --help works without a database driver on the path.
    import psycopg2

    conn = psycopg2.connect(uri)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,)
            )
            if cur.fetchone() is None:
                print(
                    f"error: schema {schema!r} does not exist in this database. Build it first:\n"
                    f"  python -c \"import sys; sys.path.insert(0, 'tests'); import pg_harness; "
                    f"pg_harness.build_schema('<uri>', rename_to='{schema}')\"",
                    file=sys.stderr,
                )
                return 1

            if args.dry_run:
                statements = len([s for s in sql.split(";") if s.strip()])
                print(f"--dry-run: schema exists; {statements} statement(s) would run. Nothing loaded.")
                conn.rollback()
                return 0

            cur.execute(sql)
            conn.commit()

            # The catalogue is what a subscription journey cannot start without, so the counts
            # are checked rather than trusted. Same guard stack-e2e.yml runs.
            cur.execute(f"SELECT count(*) FROM {schema}.billing_plan")
            plans = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM {schema}.billing_policy")
            policy = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM {schema}.currency_info WHERE currency_code = 'HKD'")
            hkd = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"billing_plan={plans}  billing_policy={policy}  currency_info(HKD)={hkd}")
    if plans == 0 or policy == 0 or hkd == 0:
        print(
            "error: the catalogue is still empty after loading, so no subscription journey can run "
            "here: a trial start would have no plan to start.",
            file=sys.stderr,
        )
        return 1

    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
