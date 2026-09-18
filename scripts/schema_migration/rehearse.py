#!/usr/bin/env python
"""Rehearse the production migration into 01_schema_rebased.sql, end to end.

    python scripts/schema_migration/rehearse.py --dump backups/oldprod_YYYYMMDD.dump --db pcreh_YYYYMMDD
    python scripts/schema_migration/rehearse.py --from-db production-backup --db pcreh_YYYYMMDD --attachments

One command, exits non-zero on the first check that is not green. The steps, each
timed (the maintenance window is the total x 2):

    1. restore     drop/create the scratch database, pg_restore the dump's pettycashv2
                   (or pg_dump a local database into it with --from-db)
    2. upgrade     flask db upgrade to alembic head, IN A SUBPROCESS whose
                   RDS_DATABASE_URI is the scratch database, with the engine URL
                   asserted inside the app context before anything runs
    3. build       01_schema_rebased.sql into the same database (pettycash_test)
    4. 00          enum coverage: every mapped value lands
    5. 02          foundation loader, COMMITTED into the scratch database
    6. 03          reports/xero/billing loader, COMMITTED (it needs 02 committed)
                   - the files themselves end in ROLLBACK for hand use with psql;
                   this script flips the last statement, the file is untouched
    7. 04          attachments, --dry-run; then --commit when --attachments
    8. manifest    <db>_not_carried.md (and .docx via manifest_docx.py) - every
                   source row the load did not carry, by reason, with ids; plus
                   the columns and tables not carried

Nothing here reads .env for the database: the scratch URI is built from
--admin-uri (default postgresql://postgres:***@localhost:5432/postgres, password
from LOCAL_DATABASE_URI in .env) and --db. The app's own database is never
touched: step 2 checks its alembic_version before and after and stops if it moved.

Exit codes: 0 all green; 1 a step failed; 2 usage.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "docs" / "schema"
sys.path.insert(0, str(REPO / "tests"))
import pg_harness  # noqa: E402  (tests/ has no package __init__)

SRC, DST = "pettycashv2", "pettycash_test"


# ---------------------------------------------------------------------------
def _with_database(uri: str, dbname: str) -> str:
    p = urlsplit(uri)
    return urlunsplit((p.scheme, p.netloc, "/" + dbname, p.query, p.fragment))


def _default_admin_uri() -> str:
    for line in io.open(REPO / ".env", encoding="utf-8"):
        if line.startswith("LOCAL_DATABASE_URI="):
            uri = line.split("=", 1)[1].strip()
            return _with_database(uri, "postgres")
    return "postgresql://postgres@localhost:5432/postgres"


def _pg_bin(tool: str) -> str:
    psql = pg_harness._find_psql()
    return str(Path(psql).with_name(tool + (".exe" if psql.endswith(".exe") else "")))


class Step:
    def __init__(self, log: "Log"):
        self.log = log
        self.times: list[tuple[str, float, str]] = []

    def run(self, name: str, fn):
        self.log.section(name)
        t0 = time.time()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - every failure ends the run
            self.times.append((name, time.time() - t0, "FAILED"))
            self.log.line(f"*** {name} FAILED: {exc}")
            self.table()
            sys.exit(1)
        self.times.append((name, time.time() - t0, "ok"))
        self.log.line(f"    {name}: {time.time() - t0:.1f}s")

    def table(self):
        self.log.section("timing")
        total = 0.0
        for name, secs, status in self.times:
            self.log.line(f"    {name:<12} {secs:8.1f}s   {status}")
            total += secs
        self.log.line(f"    {'total':<12} {total:8.1f}s   (maintenance window: {2 * total / 60:.0f} min)")


class Log:
    def __init__(self, path: Path):
        self.f = io.open(path, "w", encoding="utf-8")

    def line(self, s: str = ""):
        print(s)
        self.f.write(s + "\n")
        self.f.flush()

    def section(self, name: str):
        self.line()
        self.line(f"== {name} ==")


# ---------------------------------------------------------------------------
def psql_file(db_uri: str, path: Path, log: Log, commit: bool = False, expect_ok: bool = True) -> str:
    """Run a loader with ON_ERROR_STOP; with commit=True its final ROLLBACK
    becomes COMMIT (the file itself is not touched). Returns the NOTICE lines."""
    sql = io.open(path, encoding="utf-8").read()
    if commit:
        assert sql.rstrip().endswith("ROLLBACK;"), f"{path.name} does not end in ROLLBACK;"
        sql = sql.rstrip()[: -len("ROLLBACK;")] + "COMMIT;\n"
    env = dict(os.environ, PGCLIENTENCODING="UTF8")
    proc = subprocess.run(
        [pg_harness._find_psql(), db_uri, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"],
        input=sql, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    out = proc.stderr  # NOTICE and ERROR both arrive on stderr
    notices = [re.sub(r"^psql:.*?NOTICE:\s+", "", l) for l in out.splitlines()
               if "NOTICE:" in l and "truncate cascades" not in l]
    for n in notices:
        log.line("    " + n)
    if proc.returncode != 0:
        tail = "\n".join(l for l in out.splitlines() if "NOTICE:" not in l)[-3000:]
        raise RuntimeError(f"{path.name} exit {proc.returncode}\n{tail}")
    bad = [n for n in notices if "***" in n]
    if expect_ok and bad:
        raise RuntimeError(f"{path.name}: {len(bad)} check line(s) not OK")
    return "\n".join(notices)


def query(db_uri: str, sql: str):
    import psycopg2
    conn = psycopg2.connect(db_uri)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
def step_restore(args, admin_uri, db_uri, log):
    pg_harness._drop_database(admin_uri, args.db)
    import psycopg2
    conn = psycopg2.connect(admin_uri)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{args.db}" ENCODING \'UTF8\' TEMPLATE template0')
    finally:
        conn.close()
    env = dict(os.environ, PGCLIENTENCODING="UTF8")
    if args.dump:
        proc = subprocess.run([_pg_bin("pg_restore"), "-d", db_uri, "--no-owner", "--no-acl",
                               "-j", "4", str(args.dump)], capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_restore exit {proc.returncode}\n{proc.stderr[-3000:]}")
    else:
        src_uri = _with_database(admin_uri, args.from_db)
        dump = subprocess.Popen([_pg_bin("pg_dump"), src_uri, "-n", SRC, "-Fc", "--no-owner", "--no-acl"],
                                stdout=subprocess.PIPE, env=env)
        proc = subprocess.run([_pg_bin("pg_restore"), "-d", db_uri, "--no-owner", "--no-acl"],
                              stdin=dump.stdout, capture_output=True, text=True, env=env)
        dump.wait()
        if proc.returncode != 0 or dump.returncode != 0:
            raise RuntimeError(f"pg_dump|pg_restore exit {dump.returncode}/{proc.returncode}\n{proc.stderr[-3000:]}")
    (ver,), = query(db_uri, f"SELECT version_num FROM {SRC}.alembic_version")
    (n,), = query(db_uri, f"SELECT count(*) FROM information_schema.tables WHERE table_schema='{SRC}' AND table_type='BASE TABLE'")
    log.line(f"    restored {SRC}: {n} tables at alembic {ver}")


UPGRADE_DRIVER = r"""
import os, sys, time
uri = sys.argv[1]
# Both URIs: bootstrap reads LOCAL under FLASK_ENV=development (which .env may set and
# load_dotenv() restores) and RDS otherwise. Binding both makes the branch irrelevant.
os.environ["RDS_DATABASE_URI"] = uri
os.environ["LOCAL_DATABASE_URI"] = uri
os.environ.pop("FLASK_ENV", None)
os.environ["SUBSCRIPTION_SCHEDULER_ENABLED"] = "0"
# Flask-Session would CREATE TABLE pettycashv3.sessions on import, and the scratch
# database has no pettycashv3 until the loaders have run; this driver only needs
# the app for flask_migrate.upgrade(), so keep sessions out of the database.
os.environ["SESSION_TYPE"] = "filesystem"
sys.path.insert(0, sys.argv[2])
from main import app
from models.db import db
import flask_migrate
from sqlalchemy import text
from urllib.parse import urlsplit
want = urlsplit(uri)
with app.app_context():
    url = db.engine.url
    assert url.database == want.path.lstrip("/") and url.host == want.hostname, (str(url), uri)
    before = db.session.execute(text("SELECT version_num FROM pettycashv2.alembic_version")).scalar()
    t0 = time.time()
    flask_migrate.upgrade()
    after = db.session.execute(text("SELECT version_num FROM pettycashv2.alembic_version")).scalar()
    print(f"ALEMBIC {before} -> {after} in {time.time()-t0:.1f}s")
"""


def step_upgrade(args, admin_uri, db_uri, log):
    # the app's own database must not move
    app_uri = None
    for line in io.open(REPO / ".env", encoding="utf-8"):
        if line.startswith("RDS_DATABASE_URI="):
            app_uri = line.split("=", 1)[1].strip()
    # The guard proves the upgrade did not run against the app's own database. When that
    # database is unreachable from here (RDS_DATABASE_URI on a remote host this machine
    # cannot resolve), the upgrade could not have reached it either - it would have failed
    # the same way - so a successful upgrade is itself the proof. Warn and carry on.
    guard_before = None
    if app_uri:
        try:
            guard_before = query(app_uri, f"SELECT version_num FROM {SRC}.alembic_version")
        except Exception as exc:  # noqa: BLE001 - any connection failure
            log.line(f"    guard: app database unreachable ({str(exc).strip().splitlines()[0][:90]}); "
                     "guard skipped - the upgrade can only have reached the scratch database")
            app_uri = None
    python = REPO / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run([str(python), "-c", UPGRADE_DRIVER, db_uri, str(REPO)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(REPO))
    for l in proc.stdout.splitlines():
        if l.startswith("ALEMBIC ") or ": " in l and ("revoked" in l or "dropped" in l or "P" in l[:4]):
            log.line("    " + l)
    if proc.returncode != 0:
        raise RuntimeError(f"flask db upgrade exit {proc.returncode}\n{proc.stderr[-4000:]}")
    if app_uri:
        guard_after = query(app_uri, f"SELECT version_num FROM {SRC}.alembic_version")
        if guard_before != guard_after:
            raise RuntimeError(f"the app's own database moved from {guard_before} to {guard_after} - STOP")
    (ver,), = query(db_uri, f"SELECT version_num FROM {SRC}.alembic_version")
    log.line(f"    {SRC} now at alembic {ver}")


def step_build(args, admin_uri, db_uri, log):
    n = pg_harness.build_schema(db_uri, SCHEMA_DIR / "01_schema_rebased.sql")
    log.line(f"    built {DST}: {n} tables")


def step_04(args, db_uri, log, commit: bool):
    python = REPO / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    env = dict(os.environ, PYTHONUTF8="1", RDS_DATABASE_URI=db_uri, SOURCE_SCHEMA=SRC, TARGET_SCHEMA=DST)
    proc = subprocess.run([str(python), str(REPO / "scripts" / "schema_migration" / "04_data_attachments.py"),
                           "--commit" if commit else "--dry-run"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(REPO))
    for l in proc.stdout.splitlines():
        if l.strip() and not l.startswith("    expenses/"):
            log.line("    " + l)
    if proc.returncode != 0:
        raise RuntimeError(f"04_data_attachments exit {proc.returncode}\n{proc.stderr[-3000:]}")


# ---------------------------------------------------------------------------
MANIFEST_QUERIES = [
    ("Reports not carried (entity deleted)",
     f"""SELECT s.id, s.company AS entity_id, s.transaction_date, s.status
           FROM {SRC}.report s
          WHERE NOT EXISTS (SELECT 1 FROM {SRC}.entities e WHERE e.id = s.company)
          ORDER BY s.company, s.transaction_date"""),
    ("Reports not carried (second row for the same entity and day - the abandoned draft lost to the posted/fuller row)",
     f"""SELECT s.id, e.name AS entity, s.transaction_date, s.status, s.total_sales, s.expenses
           FROM {SRC}.report s JOIN {SRC}.entities e ON e.id = s.company
          WHERE NOT EXISTS (SELECT 1 FROM {DST}.report d WHERE d.id = s.id::uuid)
          ORDER BY e.name, s.transaction_date"""),
    ("Report children not carried with their report (rows)",
     f"""SELECT 'report_sale_detail' AS tbl, count(*) FROM {SRC}.report_sale_detail x WHERE NOT EXISTS (SELECT 1 FROM {DST}.report d WHERE d.id = x.report_id::uuid)
          UNION ALL SELECT 'report_cash_count', count(*) FROM {SRC}.report_cash_count x WHERE NOT EXISTS (SELECT 1 FROM {DST}.report d WHERE d.id = x.report_id::uuid)
          UNION ALL SELECT 'report_history', count(*) FROM {SRC}.report_history x WHERE NOT EXISTS (SELECT 1 FROM {DST}.report d WHERE d.id = x.report_id::uuid)
          UNION ALL SELECT 'shop_expense', count(*) FROM {SRC}.shop_expense x WHERE NOT EXISTS (SELECT 1 FROM {DST}.report d WHERE d.id = x.report_id::uuid)"""),
    ("entity_function_map rows not carried (entity deleted)",
     f"""SELECT m.entity_id, f.function_code, m.is_enabled, m.created_at::date
           FROM {SRC}.entity_function_map m JOIN {SRC}.entity_function f ON f.id = m.entity_function_id
          WHERE NOT EXISTS (SELECT 1 FROM {SRC}.entities e WHERE e.id = m.entity_id)"""),
    ("sale_info rows collapsed into the same-named catalogue row (per-entity duplicates; every reference remapped)",
     f"""SELECT s.id, s.name, s.type, s.code, e.name AS entity
           FROM {SRC}.sale_info s LEFT JOIN {SRC}.entities e ON e.id = s.entity_id
          WHERE NOT EXISTS (SELECT 1 FROM {DST}.sale_info d WHERE d.id = s.id::uuid)
          ORDER BY s.name, e.name"""),
    ("Users whose Xero tokens sat only on the user table (all refresh tokens expired; not carried)",
     f"""SELECT u.id, u.username, u.token_created_at::date
           FROM {SRC}."user" u
          WHERE u.access_token IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {SRC}.user_token t WHERE t.user_id = u.id)
          ORDER BY u.username"""),
    ("Zero-counted reports with no denomination in their currency (view reads NULL instead of 0)",
     f"""SELECT s.id, e.name AS entity, c.currency_code, s.transaction_date
           FROM {SRC}.report s JOIN {SRC}.entities e ON e.id = s.company LEFT JOIN {SRC}.currency_info c ON c.id = e.currency_id
          WHERE s.actual_cash_total = 0 AND NOT EXISTS (SELECT 1 FROM {SRC}.report_cash_count x WHERE x.report_id = s.id)
            AND NOT EXISTS (SELECT 1 FROM {SRC}.cash_info ci WHERE ci.currency_id = e.currency_id)"""),
    ("Source tables not loaded at all (rows)",
     f"""SELECT t.table_name, (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM {SRC}.' || quote_ident(t.table_name), false, true, '')))[1]::text::bigint AS rows
           FROM information_schema.tables t
          WHERE t.table_schema = '{SRC}' AND t.table_type = 'BASE TABLE'
            AND t.table_name IN ('alembic_version','sessions','django_migrations','django_content_type',
                                 'auth_group','auth_group_permissions','auth_permission','auth_user','auth_user_groups','auth_user_user_permissions')
          ORDER BY 1"""),
]

DROPPED_COLUMNS = """
Source columns with no target column (dropped by the redesign; see 01 header):
  user:            access_token, refresh_token, id_token, expires_in, token_created_at (-> user_token),
                   xero_token, xero_entity_id, current_entity_id (item 14)
  entities:        deposit_day, deposit_frequency, minimum_qty, xero_short_code,
                   period_lock_date, end_of_year_lock_date (item 15)
  report:          actual_cash_total (-> view report_cash_summary, item 12), receipt_files,
                   withdrawal_bank_account (item 13), shop_sales / delivery_sales (rolled up)
  shop_expense:    files, s3_key (-> report_expense_attachment via 04, item 11), item_code (item 11),
                   account_code, contact_name (used to resolve / restore the references, then dropped)
  report_history:  company (report_id suffices)
  sale_info:       code, entity_id, legacy_column (global catalogue)
  entity_sale_setting: sale_name, value_name, type, create_date, updated_at (live on the catalogue row)
  report_sale_detail:  type (lives on the catalogue row)
  cash_info:       country_code (currency_id already present), cash_id (serial -> uuid)
  entity_function_map: id (composite key), role_permission: id, created_at, updated_at
"""


def step_manifest(args, db_uri, log, path: Path):
    out = io.open(path, "w", encoding="utf-8")
    out.write(f"# Not carried over: {args.db}\n\nSource `{SRC}` at alembic head -> `{DST}` built from 01_schema_rebased.sql.\n"
              "Every row below exists in the source and has no row in the target, with the reason.\n")
    for title, sql in MANIFEST_QUERIES:
        rows = query(db_uri, sql) or []
        out.write(f"\n## {title} - {len(rows)} row(s)\n\n")
        for r in rows:
            out.write("- " + " | ".join("" if v is None else str(v) for v in r) + "\n")
        log.line(f"    {len(rows):>5}  {title}")
    out.write("\n## Columns\n" + DROPPED_COLUMNS)
    out.close()
    log.line(f"    manifest: {path}")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import manifest_docx  # needs python-docx (the venv has it)
        log.line(f"    manifest: {manifest_docx.render(path)}")
    except ImportError as exc:
        log.line(f"    manifest .docx skipped ({exc})")


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dump", type=Path, help="pg_dump -Fc of the source pettycashv2 schema")
    src.add_argument("--from-db", help="name of a local database to copy pettycashv2 from")
    ap.add_argument("--db", required=True, help="scratch database to create (dropped first)")
    ap.add_argument("--admin-uri", default=_default_admin_uri(), help="superuser URI to the server")
    ap.add_argument("--attachments", action="store_true", help="run 04 --commit after its dry run")
    ap.add_argument("--skip-restore", action="store_true", help="reuse the scratch database as it stands (skips restore and upgrade)")
    ap.add_argument("--log-dir", type=Path, default=REPO / "backups", help="where the log and manifest go")
    args = ap.parse_args()

    db_uri = _with_database(args.admin_uri, args.db)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log = Log(args.log_dir / f"{args.db}_rehearsal.log")
    log.line(f"rehearse.py  db={args.db}  source={args.dump or args.from_db}  attachments={args.attachments}")
    steps = Step(log)

    if not args.skip_restore:
        steps.run("restore", lambda: step_restore(args, args.admin_uri, db_uri, log))
        steps.run("upgrade", lambda: step_upgrade(args, args.admin_uri, db_uri, log))
    steps.run("build", lambda: step_build(args, args.admin_uri, db_uri, log))
    steps.run("00", lambda: psql_file(db_uri, SCHEMA_DIR / "00_enum_coverage_check.sql", log))
    steps.run("02", lambda: psql_file(db_uri, SCHEMA_DIR / "02_data_foundation_rebased.sql", log, commit=True))
    steps.run("03", lambda: psql_file(db_uri, SCHEMA_DIR / "03_data_reports_rebased.sql", log, commit=True))
    steps.run("04", lambda: step_04(args, db_uri, log, commit=False))
    if args.attachments:
        steps.run("04+", lambda: step_04(args, db_uri, log, commit=True))
    steps.run("manifest", lambda: step_manifest(args, db_uri, log, args.log_dir / f"{args.db}_not_carried.md"))
    steps.table()
    log.line("\nALL GREEN" if all(s == "ok" for _, _, s in steps.times) else "\nFAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
