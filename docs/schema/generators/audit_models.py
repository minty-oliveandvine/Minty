# -*- coding: utf-8 -*-
"""Diff every model in Minty, minty-payment-request-api, minty-onboarding-api and minty-billing-api against
the schema.

Reports, with file:line:
  * a model whose table does not exist under the new name
  * a model column the new schema does not have  -> breaks every SELECT
  * a declared type that no longer matches the column

Which database it reads is taken from the environment, so the same script audits the
dev database (postgres/pettycashv3, the default since 2026-09-21; minty_cleanse, the phase C
database with production data, was dropped that day), the
test harness's build (tests/pg_harness.py -> minty_test_<worker>, schema pettycashv3) or
production. Since phase C closed (2026-09-17) it reports 0 findings for the three original
repos; tests/test_zz_schema_audit.py keeps it that way, and a repo that is not checked out is
a finding (a missing path used to read as 0 findings).

    AUDIT_URI      full postgres URI            default: DATABASE_URL (environment, else Minty's
                                                .env) with its database swapped for AUDIT_DB
    AUDIT_DB       database name                default postgres        (ignored if AUDIT_URI)
    AUDIT_SCHEMA   schema to read               default: DATABASE_URL's ?schema= (pettycashv3)
    AUDIT_REPOS    comma list of repo names     default Minty,minty-payment-request-api,minty-onboarding-api,minty-billing-api
    MINTY_REPOS_ROOT  the folder the repos sit in   default: this checkout's parent (C:\\Github)
    AUDIT_STRICT=1 exit 1 when there is any finding (for use as a test)
    PG_BIN         directory holding psql       default: PATH

minty-onboarding-api was NOT in the original audit; its shared_models (585 lines) mirror the
same tables and drift the same way. minty-billing-api (Part 2, 2026-09-21) mirrors the 13
subscription tables and the read-only rows it needs. Do not remove either from the default list.
"""
import ast, glob, io, os, shutil, subprocess, sys
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from services.app_runtime.env import DEFAULT_SCHEMA, parse_database_url  # noqa: E402


def _database_url():
    """DATABASE_URL from the environment, else from Minty's .env; None when neither has one."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), ".env")
    if os.path.exists(env_file):
        for l in io.open(env_file, encoding="utf-8"):
            if l.startswith("DATABASE_URL="):
                return l.split("=", 1)[1].strip()
    return None


DB = os.environ.get("AUDIT_DB", "postgres")
SCHEMA = os.environ.get("AUDIT_SCHEMA") or (
    parse_database_url(_database_url()).schema if _database_url() else DEFAULT_SCHEMA)
# The repos live side by side (C:\Github since the 2026-09-21 move; the old C:\dev is dead).
# MINTY_REPOS_ROOT overrides the parent; this file's own location is the fallback, so the
# audit follows the checkout wherever it is.
ROOT = os.environ.get("MINTY_REPOS_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# minty-billing-api (Part 2 of the modernisation plan) mirrors the 13 subscription tables and
# the read-only rows it needs; it drifts the same way the other two Django repos do.
ALL_REPOS = {name: os.path.join(ROOT, name) for name in
             ("Minty", "minty-payment-request-api", "minty-onboarding-api", "minty-billing-api")}
REPOS = {k: ALL_REPOS[k] for k in
         os.environ.get("AUDIT_REPOS", ",".join(ALL_REPOS)).split(",") if k}
# A repo that is not checked out is a finding, not a silent pass: os.walk on a missing path
# yields nothing, which is how a stale path once made the audit report 0 for a repo it never
# read.
MISSING_REPOS = [k for k, root in REPOS.items() if not os.path.isdir(root)]
SKIP = ("\\.venv\\", "/.venv/", "site-packages", "__pycache__", "\\migrations\\", "/migrations/",
        "\\tests\\", "/tests/", "\\node_modules\\")


def _psql_bin():
    pg_bin = os.environ.get("PG_BIN")
    if pg_bin and os.path.exists(os.path.join(pg_bin, "psql.exe")):
        return os.path.join(pg_bin, "psql.exe")
    found = shutil.which("psql")
    if found:
        return found
    hits = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe"), reverse=True)
    return hits[0] if hits else "psql"


def _target():
    uri = os.environ.get("AUDIT_URI")
    if uri:
        return [uri]
    base = _database_url()
    if not base:
        sys.exit("no AUDIT_URI, and no DATABASE_URL in the environment or Minty's .env")
    parts = urlsplit(parse_database_url(base).libpq)
    return [urlunsplit((parts.scheme, parts.netloc, "/" + DB, parts.query, parts.fragment))]


def psql(sql):
    p = subprocess.run([_psql_bin(), *_target(),
                        "-X", "-q", "-A", "-F", "\x01", "-t", "-c", sql],
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        sys.exit(p.stderr)
    return [l.split("\x01") for l in p.stdout.replace("\r", "").strip().split("\n") if l]


cat = {}
for t, c, dt, udt in psql(
        "select table_name, column_name, data_type, udt_name from information_schema.columns "
        "where table_schema='%s'" % SCHEMA):
    cat.setdefault(t, {})[c] = udt if dt == "USER-DEFINED" else dt

# ---- expected postgres type for a declared model type ----------------------
SA = {
    "String": "character varying", "Unicode": "character varying", "VARCHAR": "character varying",
    "Text": "text", "UnicodeText": "text",
    "Integer": "integer", "BigInteger": "bigint", "SmallInteger": "smallint",
    "Boolean": "boolean", "Float": "double precision", "Numeric": "numeric",
    "Date": "date", "Time": "time without time zone",
    "JSON": "json", "JSONB": "jsonb", "UUID": "uuid", "ARRAY": "ARRAY",
    "LargeBinary": "bytea", "Uuid": "uuid", "MintyUuid": "uuid", "uuid_column": "uuid",
}
DJ = {
    "CharField": "character varying", "CharNField": "character", "TextField": "text", "SlugField": "character varying",
    "EmailField": "character varying", "URLField": "character varying",
    "IntegerField": "integer", "BigIntegerField": "bigint",
    "PositiveIntegerField": "integer", "SmallIntegerField": "smallint",
    "BooleanField": "boolean", "FloatField": "double precision",
    "DecimalField": "numeric", "DateField": "date", "UUIDField": "uuid",
    "JSONField": "jsonb", "BinaryField": "bytea", "AutoField": "integer",
    "BigAutoField": "bigint",
    # minty-billing-api's uuid column whose Python value is str (shared_models/fields.py);
    # without this entry an unknown class is skipped by the type check, silently.
    "MintyUUIDField": "uuid",
}


def type_of(call, django):
    """Return (expected_pg_type, rendered) for a Column()/Field() call."""
    def name(n):
        if isinstance(n, ast.Attribute):
            return n.attr
        if isinstance(n, ast.Name):
            return n.id
        return None

    if django:
        fn = name(call.func)
        if fn in ("ForeignKey", "OneToOneField"):
            return None, fn                      # target's pk type; not checked
        if fn == "PgEnumField":
            # shared_models/fields.py: the first positional argument names the enum type
            first = call.args[0] if call.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value, "PgEnumField(%s)" % first.value
            return None, "PgEnumField(?)"
        if fn in ("DateTimeField",):
            return "timestamp", fn
        return DJ.get(fn), fn

    # SQLAlchemy: first positional arg is the type
    if not call.args:
        return None, "Column(?)"
    a = call.args[0]
    fn = name(a.func) if isinstance(a, ast.Call) else name(a)
    if fn == "Enum" and isinstance(a, ast.Call):
        # db.Enum(PyEnum, name="report_status", ...): the Postgres type IS the name kwarg,
        # so an enum column is checked against the enum, not waved through as unknown.
        for k in a.keywords:
            if k.arg == "name" and isinstance(k.value, ast.Constant):
                return k.value.value, "Enum(%s)" % k.value.value
        return None, "Enum(?)"
    if fn == "TIMESTAMP" and isinstance(a, ast.Call):
        tz = any(k.arg == "timezone" and isinstance(k.value, ast.Constant) and k.value.value for k in a.keywords)
        return ("timestamp with time zone" if tz else "timestamp without time zone"), ("TIMESTAMP(tz)" if tz else "TIMESTAMP")
    if fn == "DateTime":
        tz = False
        if isinstance(a, ast.Call):
            for k in a.keywords:
                if k.arg == "timezone" and isinstance(k.value, ast.Constant):
                    tz = bool(k.value.value)
        return ("timestamp with time zone" if tz else "timestamp without time zone"), \
               ("DateTime(tz)" if tz else "DateTime")
    return SA.get(fn), fn or "?"


def const(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


findings, unparsed = [], []
for repo, root in REPOS.items():
    django = repo != "Minty"
    for dirpath, _, files in os.walk(root):
        if any(s in dirpath + os.sep for s in SKIP):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            # utf-8-sig, NOT utf-8: several of these files carry a BOM, and
            # ast.parse rejects U+FEFF. Skipping them silently is how an audit
            # comes back clean while missing a model - it hid the User model.
            try:
                tree = ast.parse(io.open(path, encoding="utf-8-sig",
                                         errors="replace").read())
            except SyntaxError as e:
                unparsed.append("%s: %s" % (path, e))
                continue
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                table, cols, managed = None, [], True
                for node in cls.body:
                    if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                            and isinstance(node.targets[0], ast.Name):
                        tgt = node.targets[0].id
                        if tgt == "__tablename__":
                            table = const(node.value)
                        elif isinstance(node.value, ast.Call):
                            f = node.value.func
                            nm = f.attr if isinstance(f, ast.Attribute) else \
                                 (f.id if isinstance(f, ast.Name) else "")
                            if nm == "Column" or nm.endswith("Field") or nm == "ForeignKey":
                                # SQLAlchemy: Column("db_name", Type, ...) names the column
                                # explicitly; the attribute is then a code-side name.
                                call = node.value
                                if nm == "Column" and call.args and isinstance(call.args[0], ast.Constant)                                         and isinstance(call.args[0].value, str):
                                    tgt = call.args[0].value
                                    call = ast.Call(func=call.func, args=call.args[1:], keywords=call.keywords)
                                    ast.copy_location(call, node.value)
                                # Django: a relation's column is db_column=..., else <name>_id
                                if nm in ("ForeignKey", "OneToOneField"):
                                    db_col = next((k.value.value for k in call.keywords
                                                   if k.arg == "db_column" and isinstance(k.value, ast.Constant)), None)
                                    tgt = db_col or (tgt + "_id")
                                cols.append((tgt, call, node.lineno))
                    if isinstance(node, ast.ClassDef) and node.name == "Meta":
                        for m in node.body:
                            if isinstance(m, ast.Assign) and isinstance(m.targets[0], ast.Name):
                                if m.targets[0].id == "db_table":
                                    table = const(m.value)
                                if m.targets[0].id == "managed" and \
                                        isinstance(m.value, ast.Constant):
                                    managed = bool(m.value.value)
                if not table or not cols:
                    continue
                rel = os.path.relpath(path, root).replace("\\", "/")
                if table not in cat:
                    findings.append((repo, table, rel, cls.lineno, "TABLE",
                                     cls.name, "table not in the new schema", ""))
                    continue
                for cname, call, lineno in cols:
                    if django and cname not in cat[table]:
                        # Django FK fields store <name>_id
                        if cname + "_id" in cat[table]:
                            continue
                    if cname not in cat[table]:
                        findings.append((repo, table, rel, lineno, "MISSING",
                                         cname, "column not in the new schema",
                                         "breaks every SELECT on this model"))
                        continue
                    want, rendered = type_of(call, django)
                    got = cat[table][cname]
                    if want is None:
                        continue
                    if want == "timestamp" and got.startswith("timestamp"):
                        continue
                    if want != got:
                        findings.append((repo, table, rel, lineno, "TYPE", cname,
                                         "%s -> declared %s, schema is %s" % (cname, rendered, got),
                                         "" if not managed else ""))

order = {"TABLE": 0, "MISSING": 1, "TYPE": 2}
findings.sort(key=lambda f: (order[f[4]], f[0], f[1], f[3]))
for f in findings:
    print("%-16s %-9s %-26s %-46s %s" % (f[0], f[4], f[1], f[2]+":"+str(f[3]), f[5] if f[4]!="TYPE" else f[6]))
print()
if unparsed:
    print()
    print("!!! %d FILE(S) COULD NOT BE PARSED - the audit does not cover them:" % len(unparsed))
    for u in unparsed:
        print("   ", u)
if MISSING_REPOS:
    print()
    print("!!! %d REPO(S) NOT FOUND - the audit did not read them (set MINTY_REPOS_ROOT or AUDIT_REPOS):"
          % len(MISSING_REPOS))
    for k in MISSING_REPOS:
        print("   ", k, "->", REPOS[k])
print("TOTAL %d  (table %d, missing-column %d, type %d)  repos=%s  schema=%s" % (
    len(findings), *(sum(1 for f in findings if f[4] == k) for k in ("TABLE", "MISSING", "TYPE")),
    ",".join(REPOS), SCHEMA))
if os.environ.get("AUDIT_STRICT") == "1" and (findings or unparsed or MISSING_REPOS):
    sys.exit(1)
