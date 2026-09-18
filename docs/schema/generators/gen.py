# -*- coding: utf-8 -*-
"""Generate the one-hop loaders: pettycashv2 (alembic HEAD) -> pettycash_test.

Everything is read from information_schema so a column cannot be missed by hand.
What is NOT mechanical lives in the dictionaries below, and nowhere else:

    TABLE_SRC   target table  <- source table, where the name changed
    OVERRIDE    target column <- source column, where the name changed
    EXPR        target column <- an expression over the source row (alias `s`)
    ENUM_MAP    target column <- CASE mapping of production values onto the
                                 redesign's enum members (01 header, item 18)
    USER_REFS   columns that hold a user id and go through uid()
    EXPECT_SKIP rows a table is EXPECTED to lose to a foreign-key guard

Every foreign-key column in the target is guarded with EXISTS against the
already-loaded parent, so a child of a dropped row is dropped too and COUNTED.
The per-table skip count is asserted against EXPECT_SKIP: anything else is a
failure, not a note.

    GEN_DB   database holding BOTH schemas       default pcreh_20260915
    GEN_SRC  source schema (head pettycashv2)    default pettycashv2
    GEN_DST  target schema built from 01         default pettycash_test
    GEN_PLAN=1  print the per-column plan and stop (no files written)

Outputs, beside this script's parent:
    02_data_foundation_rebased.sql   03_data_reports_rebased.sql
    00_enum_coverage_check.sql
"""
import io, os, re, subprocess, sys

DB   = os.environ.get("GEN_DB",  "pcreh_20260915")
SRC  = os.environ.get("GEN_SRC", "pettycashv2")
DST  = os.environ.get("GEN_DST", "pettycash_test")
OUT  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLAN_ONLY = os.environ.get("GEN_PLAN") == "1"

RESERVED = {"user", "role", "permission", "order", "desc", "end", "table", "column"}
UUID_RE = r"'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"


def q(name):
    return '"%s"' % name if (name in RESERVED or not re.match(r"^[a-z_][a-z0-9_]*$", name)) else name


def _psql_bin():
    pg_bin = os.environ.get("PG_BIN")
    if pg_bin and os.path.exists(os.path.join(pg_bin, "psql.exe")):
        return os.path.join(pg_bin, "psql.exe")
    import shutil, glob
    found = shutil.which("psql")
    if found:
        return found
    hits = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe"), reverse=True)
    return hits[0] if hits else "psql"


def psql(sql):
    env = dict(os.environ)
    env["PGPASSWORD"] = PW
    p = subprocess.run(
        [_psql_bin(), "-h", "localhost", "-U", "postgres", "-d", DB, "-X", "-q", "-A", "-F", "\x01", "-t", "-c", sql],
        capture_output=True, text=True, env=env, encoding="utf-8")
    if p.returncode:
        sys.exit("psql failed: " + p.stderr)
    return [l.split("\x01") for l in p.stdout.replace("\r", "").strip().split("\n") if l]


PW = [l.split("=", 1)[1].strip() for l in io.open(os.path.join(OUT, "..", "..", ".env"), encoding="utf-8")
      if l.startswith("LOCAL_DATABASE_URI=")][0]
PW = re.match(r".*://[^:]+:([^@]+)@", PW).group(1)

# ============================================================================
#  THE NON-MECHANICAL PART
# ============================================================================

# target table <- source table. Everything else is same-name.
TABLE_SRC = {
    "invitation":         "invitations",
    "role":               "roles",
    "permission":         "permissions",
    "role_permission":    "role_permissions",
    "report_expense":     "shop_expense",
    "report_sale":        "report_sale_detail",
    "bill_line":          "bill_line_item",
    "bill_audit":         "audit",
    "entity_cash_detail": "entity_cash_detail_v2",
}

# target tables with no source at all. Loaded by a later step or left empty.
NO_SOURCE = {"report_expense_attachment"}   # 04_data_attachments.py

# target column <- source column (same table), where only the name changed.
OVERRIDE = {
    ("user_entity", "created_at"):            "create_at",
    ("xero_bank_transaction", "created_at"):  "create_at",
    ("report_history", "created_at"):         "timestamp",
    ("report_sale", "created_at"):            "create_at",
    ("xero_report_sync", "sync_status"):      "sync_statuc",
    ("xero_report_sync", "xero_response_text"): "xero_reponse_text",
    ("bill_audit", "created_at"):             "date",
    ("bill", "contact_name"):                 "contact",
    ("bill", "created_by"):                   "uploaded_by",
    ("xero_bill_sync_line", "bill_line_id"):  "bill_line_item_id",
    ("cash_info", "description"):             "desc",
    ("entity_cash_detail", "description"):    "desc",
    ("sale_info", "sale_name"):               "name",
    ("sale_info", "enabled"):                 "is_active",
    ("entity_sale_setting", "is_active"):     "enabled",
    ("report", "entity_id"):                  "company",
    ("report", "cashsale_total"):             "cash_sales",
    ("report", "expense_total"):              "expenses",
    ("report", "xero_integrated"):            "xero_integrated_yes",
    ("report", "cash_addition_type"):         "withdrawal_type",
}

# Deterministic uuid for the two non-uuid user ids (01 header, ERA 3 item 8),
# and NULL for anything that is neither a uuid nor a known user. Used for every
# column in USER_REFS. `%s` is the source expression.
def uid(expr):
    return ("(CASE WHEN %(e)s ~* %(re)s THEN %(e)s::uuid "
            "WHEN NULLIF(%(e)s,'') IS NOT NULL AND EXISTS (SELECT 1 FROM %(src)s.\"user\" _u WHERE _u.id = %(e)s) "
            "THEN md5('user:'||%(e)s)::uuid ELSE NULL END)"
            % {"e": expr, "re": UUID_RE, "src": SRC})

USER_REFS = {
    ("user", "id"), ("user_token", "user_id"), ("user_entity", "user_id"),
    ("entities", "connected_by_user_id"), ("entities", "last_accessed_by_user_id"),
    ("invitation", "invited_by"), ("report_history", "user_id"),
    ("entity_function_map", "created_by"),
    ("bill", "created_by"), ("bill_audit", "user_id"), ("payment", "created_by"),
    ("attachment", "uploaded_by"), ("bill_attachment", "created_by"),
    ("payment_attachment", "created_by"), ("xero_bill_sync", "requested_by"),
    ("entity_bill_account_xero", "created_by"), ("entity_bill_currency", "created_by"),
    ("user_stripe_customer", "user_id"), ("payer_billing_group", "payer_user_id"),
    ("entity_billing_consent", "user_id"), ("terms_consent", "user_id"),
    ("subscription_transfer", "from_user_id"), ("subscription_transfer", "to_user_id"),
    ("subscription_audit_log", "actor_user_id"), ("subscription_audit_log", "payer_before"),
    ("subscription_audit_log", "payer_after"), ("subscription_email_log", "user_id"),
    ("share_link", "created_by"),
}

# Deterministic uuid for the integer cash_id (cash_info's old serial key).
def cash_uid(expr):
    return "md5('cash:'||%s::text)::uuid" % expr

# Source row sets that are COLLAPSED before copying: the head sale_info catalogue
# is half global (12 rows) and half per-entity CUSTOM_* rows that repeat the same
# name across entities (Payme x13, JCB x9). The redesign's catalogue is global
# with UNIQUE (sale_name), so one row per exact name survives - the global one
# where there is one, else the oldest - and every reference is remapped to it.
# Measured 2026-09-15: no entity names a method twice, no name has two types,
# and no (entity, name) or (report, name) pair collapses onto itself.
# Extra source-side JOINs a table's expressions may lean on, aliased with a
# leading underscore so they cannot collide with `s`.
JOINS = {
    "report_expense": "JOIN %s.report _r ON _r.id = s.report_id" % SRC,
}

DISTINCT_ON = {
    "sale_info": ("s.name", "(s.entity_id IS NULL) DESC, s.created_at NULLS LAST, s.id"),
    # report is UNIQUE (entity_id, transaction_date) in the redesign. At head, 35
    # (entity, day) pairs hold more than one row: the abandoned report_v2 drafts
    # r-series folded in beside the real posted report (43 extra rows, none with
    # an expense or a cash count). The posted row wins; between drafts, the one
    # with a cash count, then more expenses, then the later created wins.
    "report": ("s.company, s.transaction_date",
               "(s.status = 'posted') DESC, (s.actual_cash_total IS NOT NULL) DESC, "
               "COALESCE(s.expenses,0) DESC, s.date DESC NULLS LAST, s.id"),
}

def sale_canon(expr):
    """The canonical catalogue id for whatever sale_info id `expr` names."""
    return ("(SELECT si2.id::uuid FROM %(S)s.sale_info si2 "
            " WHERE si2.name = (SELECT si1.name FROM %(S)s.sale_info si1 WHERE si1.id = (%(e)s)::text) "
            " ORDER BY (si2.entity_id IS NULL) DESC, si2.created_at NULLS LAST, si2.id LIMIT 1)"
            % {"S": SRC, "e": expr})

def report_published(alias="s"):
    """The report reached Xero: 'posted', the flag, AND a 'published' history row.

    Written once so report.status and report.publishing_status derive from the
    same fact and can never disagree (01 header, item 18). The history row is
    required because 3 rows carry the flag with no trail (2 say 'completed',
    1 says ''); by decision they load as submitted / unpublished."""
    return ("(%(a)s.status = 'posted' AND %(a)s.xero_integrated_yes IS TRUE AND EXISTS "
            "(SELECT 1 FROM %(S)s.report_history _h WHERE _h.report_id = %(a)s.id AND _h.action = 'published'))"
            % {"a": alias, "S": SRC})

# target column <- expression over the source row `s`. Wins over OVERRIDE.
EXPR = {
    # report.status: the app writes only 'draft' and 'posted' ('posted' = the
    # end-of-day wizard finished, ending.py:1568, shown as "Submitted" at
    # report_history.html:513). Whether it then reached Xero lives in
    # xero_integrated_yes / publishing_status / report_history, so 'published'
    # is DERIVED here, from report_published() above. Other posted -> submitted.
    ("report", "status"): (
        "(CASE WHEN %s THEN 'published' WHEN s.status = 'posted' THEN 'submitted' ELSE s.status::text END)"
        % report_published()),
    # report.publishing_status only exists since ~2026-03-18: 202 reports
    # published before that hold NULL beside the flag and a history row, and a
    # NULL -> unpublished rule mislabelled them. Same predicate -> completed.
    # 'partially_published' (3 posted Test_1 reports, no bank transactions) has
    # no member; the app reads it together with 'failed' (history_query.py:102,
    # api.py:1525). Everything else ('', NULL, the 2 no-trail 'completed') ->
    # unpublished.
    ("report", "publishing_status"): (
        "(CASE WHEN %s THEN 'completed'"
        " WHEN s.publishing_status IN ('failed','partially_published') THEN 'failed'"
        " ELSE 'unpublished' END)" % report_published()),
    # report: shop_sales INCLUDES cash (shop = cash + electronic; total = shop +
    # delivery, measured on 3,748 of 3,847 reports), so the non-cash roll-up is
    # total - cash, as the original 03 had it.
    ("report", "nocashsale_total"): "COALESCE(s.total_sales,0)::numeric - COALESCE(s.cash_sales,0)::numeric",
    # report.date is NULL on two rows; created_at is NOT NULL, and the
    # transaction date is the truthful fallback (not now()).
    ("report", "created_at"): "COALESCE(s.date::timestamptz, s.transaction_date::timestamptz)",
    # report.uploaded_by is a USERNAME, not an id.
    ("report", "created_by"): "(SELECT %s FROM %s.\"user\" u WHERE u.username = s.uploaded_by LIMIT 1)" % (uid("u.id"), SRC),
    # report_sale: s4a04's cash rows carry the per-entity key only; resolve
    # through entity_sale_setting to the catalogue id.
    ("report_sale", "sale_id"): sale_canon("COALESCE(NULLIF(s.sale_info_id,''), "
                                           "(SELECT NULLIF(ess.sale_info_id,'') FROM %s.entity_sale_setting ess "
                                           " WHERE ess.sale_id = s.sale_id LIMIT 1))" % SRC),
    ("entity_sale_setting", "sale_id"): sale_canon("NULLIF(s.sale_info_id,'')"),
    # item 22: stamps the source never had - the truthful dates, not the load moment
    ("xero_report_sync", "created_at"):  "COALESCE(s.reported_at::timestamptz, now())",
    ("xero_report_sync", "updated_at"):  "COALESCE(s.completed_at::timestamptz, s.reported_at::timestamptz, now())",
    ("xero_bank_transfer", "created_at"): "COALESCE(s.transfer_date::timestamptz, now())",
    ("xero_bank_transfer", "updated_at"): "COALESCE(s.transfer_date::timestamptz, now())",
    # sale_info.value_name is the sales form's field name ('visa_sales') and the key the
    # code finds the Cash row by ('cash_sales'). The source kept it as legacy_column on the
    # global rows and only on entity_sale_setting.value_name for the per-entity customs;
    # a name nobody ever linked gets the code's own derivation. Found 2026-09-16 (C3):
    # without this every row loaded NULL and the sales form rendered no inputs.
    ("sale_info", "value_name"): (
        "COALESCE(NULLIF(s.legacy_column,''), "
        "(SELECT NULLIF(ess.value_name,'') FROM %s.entity_sale_setting ess "
        " WHERE ess.sale_info_id = s.id AND NULLIF(ess.value_name,'') IS NOT NULL LIMIT 1), "
        "lower(replace(s.name, ' ', '_')) || '_sales')" % SRC
    ),
    # cash: the serial key becomes a deterministic uuid, everywhere it appears.
    ("cash_info", "id"):                 cash_uid("s.cash_id"),
    ("entity_cash_detail", "cash_id"):   cash_uid("s.cash_id"),
    ("entity_cash_setting", "cash_id"):  cash_uid("s.cash_id"),
    ("report_cash_count", "cash_id"):    cash_uid("s.cash_id"),
    # bill / payment: currency by code, contact by uuid shape (Decision 7: no FK).
    ("bill", "currency_id"):    "(SELECT ci.id FROM %s.currency_info ci WHERE ci.currency_code = s.currency_code)" % DST,
    ("payment", "currency_id"): "(SELECT ci.id FROM %s.currency_info ci WHERE ci.currency_code = s.currency_code)" % DST,
    ("bill", "contact_id"):     "(CASE WHEN s.xero_contact_id ~* %s THEN s.xero_contact_id::uuid ELSE NULL END)" % UUID_RE,
    ("bill", "amount_paid"):    ("COALESCE((SELECT sum(p.amount) FROM %s.payment p "
                                 " WHERE p.bill_id = s.id AND p.payment_status = 'completed'), 0)" % SRC),
    ("entity_bill_currency", "currency_id"): "NULLIF(s.currency_info_id,'')::uuid",
    # permission.code did not exist before the redesign; the name is the code.
    ("permission", "code"): "s.name",
    # report_expense.account_id / contact_id hold XERO ids (AccountID, ContactID)
    # in the source; the redesign's FKs want the internal row. Resolve within the
    # expense's entity - by Xero id, then by account code - and fall back to the
    # row RESTORE (below) recreates. NULL only where the source is NULL.
    ("report_expense", "account_id"): (
        "(CASE WHEN NULLIF(s.account_id,'') IS NULL THEN NULL ELSE COALESCE("
        " (SELECT NULLIF(a.id,'')::uuid FROM %(S)s.account_info a WHERE a.entity_id = %(ent)s AND a.xero_account_id::text = s.account_id ORDER BY a.id LIMIT 1),"
        " (SELECT NULLIF(a.id,'')::uuid FROM %(S)s.account_info a WHERE a.entity_id = %(ent)s AND a.xero_code = NULLIF(s.account_code,'') ORDER BY a.id LIMIT 1),"
        " md5('restored-account:'||%(ent)s||':'||s.account_id)::uuid) END)" % {"S": SRC, "ent": "_r.company"}),
    ("report_expense", "contact_id"): (
        "(CASE WHEN NULLIF(s.contact_id,'') IS NULL THEN NULL ELSE COALESCE("
        " (SELECT NULLIF(c.id,'')::uuid FROM %(S)s.xero_contact_sync c WHERE c.entity_id = %(ent)s AND c.xero_contact_id = s.contact_id ORDER BY c.id LIMIT 1),"
        " md5('restored-contact:'||%(ent)s||':'||s.contact_id)::uuid) END)" % {"S": SRC, "ent": "_r.company"}),
}

# SQL emitted immediately BEFORE a table's INSERT. Used to RESTORE the sync rows
# that report_expense references and the source no longer has.
#
# WHY THEY ARE MISSING: until 2026-07-23 (commit 5229231, pinned by
# tests/test_xero_contact_sync_no_mass_delete.py) get_contacts_from_xero
# returned [] on any failure and the nightly reconcile treated that as "Xero has
# no contacts", hard-deleting every contact row for the entity. Re-syncs only
# re-add contacts still active in Xero. The accounts are narrower: codes
# archived or renumbered in Xero, which the account sync mirrors. Either way
# the expense line still names the Xero id and, on shop_expense, the contact
# name and account code - so the row is rebuilt from what the expense kept,
# under a deterministic id the expense expression above already points at.
PRE = {
    "report_expense": """-- RESTORE the account_info and xero_contact_sync rows that expenses still name
-- (see gen.py PRE for why they are missing). One row per (entity, Xero id).
-- Re-runnable: a previous run's restored rows are removed first.
DELETE FROM %(D)s.xero_contact_sync WHERE category = 'restored';
DELETE FROM %(D)s.account_info WHERE description LIKE 'restored by the schema migration%%';

INSERT INTO %(D)s.xero_contact_sync (id, entity_id, xero_contact_id, xero_org_id, name, category)
SELECT DISTINCT ON (r.company, se.contact_id)
       md5('restored-contact:'||r.company||':'||se.contact_id)::uuid,
       r.company::uuid, se.contact_id, en.xero_org_id,
       COALESCE(NULLIF(se.contact_name,''), 'Unknown contact (restored)'), 'restored'
  FROM %(S)s.shop_expense se
  JOIN %(S)s.report r   ON r.id = se.report_id
  JOIN %(S)s.entities en ON en.id = r.company
 WHERE se.contact_id ~* %(re)s
   AND NOT EXISTS (SELECT 1 FROM %(S)s.xero_contact_sync c
                    WHERE c.entity_id = r.company AND c.xero_contact_id = se.contact_id)
 ORDER BY r.company, se.contact_id, (NULLIF(se.contact_name,'') IS NOT NULL) DESC, r.transaction_date DESC, se.id;

INSERT INTO %(D)s.account_info (id, entity_id, type, name, xero_account_id, xero_code, status, description)
SELECT DISTINCT ON (r.company, se.account_id)
       md5('restored-account:'||r.company||':'||se.account_id)::uuid,
       r.company::uuid, 'EXPENSE', COALESCE(NULLIF(se.account_code,''), se.account_id),
       se.account_id, NULLIF(se.account_code,''), 'INACTIVE',
       'restored by the schema migration: referenced by expenses, absent from the synced chart'
  FROM %(S)s.shop_expense se
  JOIN %(S)s.report r   ON r.id = se.report_id
  JOIN %(S)s.entities en ON en.id = r.company
 WHERE se.account_id ~* %(re)s
   AND NOT EXISTS (SELECT 1 FROM %(S)s.account_info a
                    WHERE a.entity_id = r.company
                      AND (a.xero_account_id::text = se.account_id OR a.xero_code = NULLIF(se.account_code,'')))
 ORDER BY r.company, se.account_id, (NULLIF(se.account_code,'') IS NOT NULL) DESC, r.transaction_date DESC, se.id;

""" % {"S": SRC, "D": DST, "re": UUID_RE},
}

# Enum mapping: production value -> redesign member. Anything not listed passes
# through unchanged (and 00 proves the enum accepts it). `None` is the source
# NULL. 01 header item 18 is the register; this is the implementation.
ENUM_MAP = {
    ("entities", "status"):          {"active": "disconnected", "cancelled": "disconnected"},
    ("user", "system_role"):         {"superuser": "superadmin", "user": "normal", None: "normal"},
    ("invitation", "status"):        {"cancelled": "revoked", "canceled": "revoked"},
    # entity_role: the app's normalize_role lower-cases and snake-cases before
    # comparing ('shop manager', 'Admin' both occur in production); so do we.
    ("invitation", "role"):          {"__norm__": "lower_snake"},
    ("user_entity", "role"):         {"__norm__": "lower_snake"},
    # report.status and report.publishing_status are NOT here: both derive from
    # report_published() and live in EXPR (which wins over this table).
    ("report", "discrepancy_type"):  {"surplus": "over", "shortage": "short", None: "none"},
    ("sale_info", "type"):           {"Electronic": "electronic", "Delivery": "delivery", "Cash": "other"},
    ("bill", "status"):              {"voided": "void"},
    ("bill", "published"):           {"not_published": "draft"},
    ("xero_bill_sync", "sync_direction"): {"outbound": "push"},
    # module_code: the module BILL becomes PAYMENT_REQUEST (01 header, item 20).
    # entity_module_subscription and subscription_audit_log hold no rows today,
    # but the same writers reach them. billing_plan.code stays text (composite
    # keys, BILL+PETTY_CASH) by decision.
    ("entity_function", "function_code"):            {"BILL": "PAYMENT_REQUEST"},
    ("entity_module_subscription", "function_code"): {"BILL": "PAYMENT_REQUEST"},
    ("subscription_audit_log", "function_code"):     {"BILL": "PAYMENT_REQUEST"},
}

# Value mapping for plain varchar columns - the same idea as ENUM_MAP, for a
# vocabulary the schema holds as text. Empty since module_code became an enum
# (item 20); kept so the next text vocabulary has a home. B3/R3 assert these too.
VALUE_MAP = {
}

# Rows a table is EXPECTED to lose to its foreign-key guards. Measured on the
# production dataset 2026-09-15; a fresh dump that differs fails the check, which
# is the point - a new orphan is a question, not a statistic.
EXPECT_SKIP = {
    "report": 98,               # 55 named deleted entities + 43 duplicate-day drafts (see DISTINCT_ON)
    "entity_function_map": 10,  # named deleted entities
    "sale_info": 25,            # per-entity duplicates collapsed by name (65 -> 40 on 2026-09-16; 57 -> 35 in August)
    # children of the 98 dropped reports (unchanged on the 2026-09-16 dump)
    "report_sale": 444,
    "report_cash_count": 278,
    "report_history": 5,
    "report_expense": 99,
    # bill.entity_id has NO foreign key (Decision 7), so the 2 bills naming a
    # deleted entity load as they are - the service boundary's own contract.
}

# Key-survival check: which target key a source row is expected under, where it
# is not simply its own converted key.
KEY_EXPR = {
    ("sale_info", "id"): sale_canon("s.id"),
}

FOUNDATION = ["currency_info", "country_info", "user", "user_token", "role", "permission",
              "role_permission", "entities", "user_entity", "invitation", "email_otp",
              "account_info", "entity_account_xero", "xero_contact_sync", "entity_function",
              "entity_function_map", "entity_pettycash_settings", "share_link",
              "cash_info", "entity_cash_detail", "entity_cash_setting",
              "sale_info", "entity_sale_setting", "billing_plan", "billing_policy"]

# ============================================================================
#  CATALOGUE
# ============================================================================
tgt = {}   # table -> [(col, data_type, udt, nullable, has_default)]
src = {}   # table -> {col: data_type}
for t, c, dt, udt, nul, dflt in psql(
        "select c.table_name, c.column_name, c.data_type, c.udt_name, c.is_nullable, "
        "       coalesce(c.column_default,'') "
        "from information_schema.columns c join information_schema.tables t "
        "  on t.table_schema=c.table_schema and t.table_name=c.table_name and t.table_type='BASE TABLE' "
        "where c.table_schema='%s' order by c.table_name, c.ordinal_position" % DST):
    tgt.setdefault(t, []).append((c, dt, udt, nul == "YES", dflt != ""))
for t, c, dt in psql("select table_name, column_name, data_type from information_schema.columns "
                     "where table_schema='%s' order by table_name, ordinal_position" % SRC):
    src.setdefault(t, {})[c] = dt

# foreign keys in the target: (child, col) -> (parent, parent_col)
fks = {}
for ch, col, pa, pcol in psql(
        "select ch.relname, a.attname, pa.relname, pb.attname from pg_constraint c "
        "join pg_class ch on ch.oid=c.conrelid join pg_class pa on pa.oid=c.confrelid "
        "join pg_namespace n on n.oid=ch.relnamespace "
        "join lateral unnest(c.conkey, c.confkey) as k(a1, a2) on true "
        "join pg_attribute a on a.attrelid=ch.oid and a.attnum=k.a1 "
        "join pg_attribute pb on pb.attrelid=pa.oid and pb.attnum=k.a2 "
        "where c.contype='f' and n.nspname='%s' and array_length(c.conkey,1)=1" % DST):
    fks[(ch, col)] = (pa, pcol)

# primary keys in the target
pks = {}
for t, cols in psql(
        "select c.relname, string_agg(a.attname, ',' order by k.ord) from pg_class c "
        "join pg_namespace n on n.oid=c.relnamespace "
        "join pg_constraint pk on pk.conrelid=c.oid and pk.contype='p' "
        "cross join lateral unnest(pk.conkey) with ordinality as k(att, ord) "
        "join pg_attribute a on a.attrelid=c.oid and a.attnum=k.att "
        "where n.nspname='%s' group by c.relname" % DST):
    pks[t] = cols.split(",")

# dependency order
edges = {}
for (ch, _c), (pa, _p) in fks.items():
    if ch != pa:
        edges.setdefault(ch, set()).add(pa)
order, seen = [], set()
def visit(t, stack=()):
    if t in seen or t in stack:
        return
    for p in sorted(edges.get(t, ())):
        if p in tgt:
            visit(p, stack + (t,))
    seen.add(t); order.append(t)
for t in sorted(tgt):
    visit(t)

# ============================================================================
#  PER-COLUMN EXPRESSIONS
# ============================================================================
def coerce(expr, sdt, tdt, udt, t, c):
    """Generic type coercion from the source column type to the target's."""
    if tdt == "USER-DEFINED":            # enum
        m = ENUM_MAP.get((t, c))
        if m:
            src = "%s::text" % expr
            if m.get("__norm__") == "lower_snake":
                src = "lower(replace(%s, ' ', '_'))" % src
            whens = "".join(" WHEN %s THEN '%s'" % ("NULL" if k is None else "'%s'" % k, v)
                            for k, v in m.items() if k is not None and k != "__norm__")
            base = "(CASE %s%s ELSE %s END)" % (src, whens, src) if whens else src
            if None in m:
                base = "COALESCE(%s, '%s')" % (base, m[None])
            return "%s::%s.%s" % (base, DST, udt)
        return "%s::text::%s.%s" % (expr, DST, udt)
    vm = VALUE_MAP.get((t, c))
    if vm:
        whens = "".join(" WHEN '%s' THEN '%s'" % (k, v) for k, v in vm.items())
        return "(CASE %s%s ELSE %s END)" % (expr, whens, expr)
    if tdt == "uuid" and sdt in ("character varying", "text", "character"):
        # a value that is not uuid-shaped (one report_sale_detail row holds the
        # timestamp-like id 202608171300) gets a deterministic uuid, the same way
        # the legacy user ids do (item 8). A foreign key that lands nowhere is
        # then dropped by its guard and shows up in R1, not silently kept.
        return ("(CASE WHEN %(e)s ~* %(re)s THEN %(e)s::uuid WHEN NULLIF(%(e)s,'') IS NULL THEN NULL "
                "ELSE md5('%(t)s.%(c)s:'||%(e)s)::uuid END)" % {"e": expr, "re": UUID_RE, "t": t, "c": c})
    if tdt == "uuid" and sdt in ("integer", "bigint", "smallint"):
        # a serial key becomes a deterministic uuid, the same way cash_id does
        return "md5('%s:'||%s::text)::uuid" % (t, expr)
    if tdt == "numeric" and sdt in ("double precision", "real", "integer", "bigint"):
        return "%s::numeric" % expr
    if tdt == "timestamp with time zone" and sdt == "timestamp without time zone":
        return "%s::timestamptz" % expr          # session time zone is set to Asia/Hong_Kong
    if tdt == "jsonb" and sdt == "json":
        return "%s::jsonb" % expr
    if tdt == "date" and sdt in ("character varying", "timestamp without time zone", "timestamp with time zone"):
        return "%s::date" % expr
    if tdt == "integer" and sdt in ("double precision", "numeric"):
        return "round(%s)::int" % expr
    return expr


class Missing(Exception):
    pass


def plan_table(t):
    """Return (source_table, [(tgt_col, expr)], [omitted], [missing])."""
    st = TABLE_SRC.get(t, t)
    scols = src.get(st)
    if scols is None:
        return st, [], [], []
    cols, omitted, missing = [], [], []
    for c, dt, udt, nullable, has_default in tgt[t]:
        if (t, c) in EXPR:
            e = EXPR[(t, c)]
            if dt == "USER-DEFINED" and not e.endswith(udt):
                e = "%s::text::%s.%s" % (e, DST, udt)
            cols.append((c, e)); continue
        sname = OVERRIDE.get((t, c), c)
        if sname in scols:
            base = "s." + q(sname)
            if (t, c) in USER_REFS:
                e = uid(base)
            else:
                e = coerce(base, scols[sname], dt, udt, t, c)
            cols.append((c, e))
        elif has_default or nullable:
            omitted.append(c)
        else:
            missing.append(c)
    return st, cols, omitted, missing


def source_rows(t):
    """The FROM clause for a table's source rows, aliased `s`, collapsed if listed."""
    st = TABLE_SRC.get(t, t)
    join = (" " + JOINS[t]) if t in JOINS else ""
    if t in DISTINCT_ON:
        on, order_by = DISTINCT_ON[t]
        return ("(SELECT DISTINCT ON (%s) s.* FROM %s.%s s ORDER BY %s, %s) s%s"
                % (on, SRC, q(st), on, order_by, join))
    return "%s.%s s%s" % (SRC, q(st), join)


def guard_clauses(t, cols):
    """EXISTS against the loaded parent for every single-column FK, using the
    same expression the INSERT uses for that column."""
    exprs = dict(cols)
    out = []
    for (ch, col), (pa, pcol) in sorted(fks.items()):
        if ch != t or col not in exprs:
            continue
        e = exprs[col]
        out.append("((%s) IS NULL OR EXISTS (SELECT 1 FROM %s.%s _p WHERE _p.%s = (%s)))"
                   % (e, DST, q(pa), q(pcol), e))
    return out


def copy_stmt(t):
    st, cols, omitted, missing = plan_table(t)
    if missing:
        raise Missing("%s: NOT NULL columns with no source and no default: %s" % (t, ", ".join(missing)))
    if not cols:
        return None
    body = ",\n   ".join(q(c) for c, _ in cols)
    sel = ",\n       ".join(e for _, e in cols)
    guards = guard_clauses(t, cols)
    where = ("\nWHERE " + "\n  AND ".join(guards)) if guards else ""
    return ("INSERT INTO %s.%s\n  (%s)\nSELECT %s\nFROM %s%s;"
            % (DST, q(t), body, sel, source_rows(t), where))


# ============================================================================
#  PLAN (always printed) and exit if GEN_PLAN=1
# ============================================================================
problems = []
print("dependency order: " + " ".join(order))
print()
for t in order:
    st, cols, omitted, missing = plan_table(t)
    tag = "" if st == t else " <- %s" % st
    if src.get(st) is None:
        print("%-28s NO SOURCE%s" % (t, "  (expected)" if t in NO_SOURCE else "  *** UNEXPECTED ***"))
        if t not in NO_SOURCE:
            problems.append(t)
        continue
    print("%-28s%s  %d cols, omitted: %s" % (t, tag, len(cols), ", ".join(omitted) or "-"))
    if missing:
        print("    *** MISSING (NOT NULL, no source, no default): %s" % ", ".join(missing))
        problems.append(t)
    unused = sorted(set(src[st]) - {OVERRIDE.get((t, c), c) for c, _ in cols}
                    - {re.sub(r".*\bs\.(\w+)\b.*", r"\1", e) for _, e in cols if "s." in e})
    if unused:
        print("    source columns not carried: %s" % ", ".join(unused))
print()
print("source tables not loaded anywhere: %s" % " ".join(sorted(set(src) - {TABLE_SRC.get(t, t) for t in tgt})))
if problems:
    sys.exit("\n*** %d table(s) cannot be generated: %s" % (len(problems), ", ".join(problems)))
if PLAN_ONLY:
    sys.exit(0)

# ============================================================================
#  EMIT
# ============================================================================
shared = [t for t in order if src.get(TABLE_SRC.get(t, t)) is not None]
f_tables = [t for t in shared if t in FOUNDATION]
r_tables = [t for t in shared if t not in FOUNDATION]


def truncate_stmt(tables):
    return ("TRUNCATE TABLE\n  " + ",\n  ".join("%s.%s" % (DST, q(t)) for t in reversed(tables))
            + "\n  RESTART IDENTITY CASCADE;")


def check_counts(label, tables):
    """Row parity, with the EXPECTED skip per guarded table."""
    pairs = ", ".join("('%s','%s',%d)" % (TABLE_SRC.get(t, t), t, EXPECT_SKIP.get(t, 0)) for t in tables)
    return """-- %(l)s1 -- row parity. src - dst must equal the EXPECTED skip for that table
-- (a child of a dropped parent, or a row naming a deleted entity). Anything else
-- is a failure.
DO $$
DECLARE r record; s bigint; d bigint; bad int := 0;
BEGIN
  FOR r IN SELECT * FROM (VALUES %(pairs)s) AS v(src, dst, skip) LOOP
    EXECUTE format('SELECT count(*) FROM %(S)s.%%I', r.src) INTO s;
    EXECUTE format('SELECT count(*) FROM %(D)s.%%I', r.dst) INTO d;
    IF s - d <> r.skip THEN bad := bad + 1; END IF;
    RAISE NOTICE '%(l)s1  %% : src=%%  dst=%%  skipped=%% (expected %%)   %%',
      rpad(r.dst,28), s, d, s - d, r.skip,
      CASE WHEN s - d = r.skip THEN 'OK' ELSE '*** MISMATCH ***' END;
  END LOOP;
  IF bad > 0 THEN RAISE EXCEPTION '%(l)s1: %% table(s) off their expected count', bad; END IF;
END $$;
""" % {"l": label, "pairs": pairs, "S": SRC, "D": DST}


def check_enums(label, tables):
    """For every ENUM_MAP column in these tables: the mapped source distribution
    (through the same expression the INSERT used, on the rows the guards kept)
    equals what the target holds. Prints the numbers item 18 records."""
    blocks = []
    for t in tables:
        st, cols, _o, _m = plan_table(t)
        exprs = dict(cols)
        guards = guard_clauses(t, cols)
        where = (" WHERE " + " AND ".join(guards)) if guards else ""
        # every enum column, mapped or not, and every VALUE_MAP column: the
        # distribution must land exactly
        for c, dt, udt, _n, _d in tgt[t]:
            if (dt != "USER-DEFINED" and (t, c) not in VALUE_MAP) or c not in exprs:
                continue
            e = exprs[c]
            blocks.append("""  FOR r IN
    SELECT COALESCE(a.v, b.v) AS v, COALESCE(a.n,0) AS src, COALESCE(b.n,0) AS dst
      FROM (SELECT (%(e)s)::text v, count(*) n FROM %(from)s%(w)s GROUP BY 1) a
      FULL JOIN (SELECT %(c)s::text v, count(*) n FROM %(D)s.%(t)s GROUP BY 1) b ON b.v = a.v
     ORDER BY 1
  LOOP
    IF r.src <> r.dst THEN bad := bad + 1; END IF;
    RAISE NOTICE '%(l)s3  %(t)s.%(c)s %% : mapped-src=%%  dst=%%   %%',
      rpad(COALESCE(r.v,'NULL'),16), r.src, r.dst, CASE WHEN r.src = r.dst THEN 'OK' ELSE '*** MOVED ***' END;
  END LOOP;""" % {"e": e, "from": source_rows(t), "w": where, "c": q(c), "D": DST, "t": q(t), "l": label})
    if not blocks:
        return ""
    return """-- %(l)s3 -- the enum mapping landed exactly. Every value the source holds, mapped
-- through the same CASE the INSERT used, must appear in the target with the same
-- count. This is where item 18's numbers are proved rather than quoted.
DO $$
DECLARE r record; bad int := 0;
BEGIN
%(b)s
  IF bad > 0 THEN RAISE EXCEPTION '%(l)s3: an enum mapping did not land'; END IF;
END $$;
""" % {"l": label, "b": "\n".join(blocks)}


def check_keys(label, tables):
    """Every primary key survives, except the ones this file deliberately mints."""
    minted = {"user": "id", "cash_info": "id"}
    entries = []
    for t in tables:
        st = TABLE_SRC.get(t, t)
        pk = pks.get(t)
        if not pk or any(c not in dict(plan_table(t)[1]) for c in pk):
            continue
        exprs = dict(plan_table(t)[1])
        guards = guard_clauses(t, exprs.items())
        where = (" AND " + " AND ".join(guards)) if guards else ""
        cond = " AND ".join("d.%s = (%s)" % (q(c), KEY_EXPR.get((t, c), exprs[c])) for c in pk)
        entries.append("""  SELECT count(*) INTO n FROM %(from)s
   WHERE NOT EXISTS (SELECT 1 FROM %(D)s.%(t)s d WHERE %(cond)s)%(w)s;
  IF n > 0 THEN bad := bad + 1; END IF;
  RAISE NOTICE '%(l)s5  %% key(%%) : %% lost   %%', rpad('%(t)s',26), '%(pk)s', n,
    CASE WHEN n = 0 THEN 'OK' ELSE '*** LOST ***' END;""" % {
            "from": source_rows(t), "D": DST, "t": q(t), "cond": cond, "w": where, "l": label, "pk": ",".join(pk)})
    return """-- %(l)s5 -- no key was lost. Each source row that passed the guards is found in
-- the target under the key the INSERT computed for it (the two md5 user ids and
-- the cash ids are converted, everything else is copied).
DO $$
DECLARE n bigint; bad int := 0;
BEGIN
%(b)s
  IF bad > 0 THEN RAISE EXCEPTION '%(l)s5: %% table(s) lost keys', bad; END IF;
END $$;
""" % {"l": label, "b": "\n".join(entries)}


def check_money(label, tables):
    """Sum of every numeric target column that came from a double precision
    source column, compared as numeric(14,2): the type change must not move a
    cent. Only for tables with no skipped rows, where the sums must be equal."""
    entries = []
    for t in tables:
        st, cols, _o, _m = plan_table(t)
        scols = src[st]
        guards = guard_clauses(t, cols)
        where = (" WHERE " + " AND ".join(guards)) if guards else ""
        for c, dt, udt, _n, _d in tgt[t]:
            sname = OVERRIDE.get((t, c), c)
            if dt == "numeric" and scols.get(sname) == "double precision" and (t, c) not in EXPR:
                entries.append("('%s','%s','%s','%s')" % (
                    ("SELECT round(coalesce(sum(s.%s),0)::numeric, 2) FROM %s%s" % (q(sname), source_rows(t), where)).replace("'", "''"),
                    sname, t, c))
    if not entries:
        return ""
    return """-- %(l)s6 -- money did not move. Every double precision -> numeric column sums to
-- the same value on both sides, at two decimals - the source side summed over
-- exactly the rows the guards let through.
DO $$
DECLARE r record; a numeric; b numeric; bad int := 0;
BEGIN
  FOR r IN SELECT * FROM (VALUES %(v)s) AS v(q, sc, t, c) LOOP
    EXECUTE r.q INTO a;
    EXECUTE format('SELECT round(coalesce(sum(%%I),0), 2) FROM %(D)s.%%I', r.c, r.t) INTO b;
    IF a <> b THEN bad := bad + 1; END IF;
    RAISE NOTICE '%(l)s6  %%.%% : src=%%  dst=%%   %%', rpad(r.t,22), rpad(r.c,24), a, b,
      CASE WHEN a = b THEN 'OK' ELSE '*** MOVED ***' END;
  END LOOP;
  IF bad > 0 THEN RAISE EXCEPTION '%(l)s6: %% money column(s) changed', bad; END IF;
END $$;
""" % {"l": label, "v": ", ".join(entries), "S": SRC, "D": DST}


HEAD02 = """-- ===========================================================================
-- pettycash_test :: the foundation loader   (GENERATED by generators/gen.py)
--
--   reads   pettycashv2      at alembic HEAD (v1a01_billing_account)
--   writes  pettycash_test   built by 01_schema_rebased.sql
--
-- Both schemas live in the SAME database. One hop: the application's own
-- alembic chain has already merged the report tables, normalised sales and
-- turned the wide cash counts into rows on the way to head. What is left here
-- is the rebase itself - uuid keys, numeric money, timestamptz, the enum
-- vocabulary of item 18, nine renames and the token split - and every one of
-- those is a dictionary entry in gen.py, not a hand-written statement.
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/02_data_foundation_rebased.sql
--
-- Ends in ROLLBACK. rehearse.py flips it to COMMIT with --commit.
--
-- Naive timestamps in the source are Hong Kong local (the app writes them so);
-- the session time zone below is what makes the ::timestamptz cast honest.
--
-- THE CHECKS
--   B1  row parity, with the EXPECTED skip per guarded table
--   B3  every enum mapping landed with exactly the mapped counts
--   B4  what deliberately starts empty is empty
--   B5  no key was lost
--   B6  money did not move (double precision -> numeric)
-- ===========================================================================

BEGIN;
SET LOCAL TIME ZONE 'Asia/Hong_Kong';

-- Nothing below tolerates a partial previous run.
"""

HEAD03 = """-- ===========================================================================
-- pettycash_test :: reports, xero and billing   (GENERATED by generators/gen.py)
--
--   reads   pettycashv2      at alembic HEAD (v1a01_billing_account)
--   writes  pettycash_test   built by 01_schema_rebased.sql; needs 02 COMMITTED
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/03_data_reports_rebased.sql
--
-- Ends in ROLLBACK. rehearse.py flips it to COMMIT with --commit.
--
-- report_expense_attachment is NOT loaded here: scripts/schema_migration/
-- 04_data_attachments.py fills it from shop_expense.files / s3_key through the
-- application's own parser (01 header, ERA 3 item 11).
--
-- THE CHECKS
--   R1  row parity, with the EXPECTED skip per guarded table
--   R3  every enum mapping landed with exactly the mapped counts
--   R5  no key was lost
--   R6  money did not move (double precision -> numeric)
--   R7  the sales breakdown is the same number: per report, the report_sale
--       rows sum to what the legacy columns said
--   R8  the cash count view reproduces report.actual_cash_total, NULL for NULL
-- ===========================================================================

BEGIN;
SET LOCAL TIME ZONE 'Asia/Hong_Kong';

-- Nothing below tolerates a partial previous run.
"""

B4 = """-- B4 -- what deliberately starts empty. The 29 users whose Xero tokens sit only
-- on the user table (May 2026, before user_token existed) are NOT carried: every
-- one of those refresh tokens is past its 60-day life. Counted, not copied.
DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM %(S)s."user" u
   WHERE u.access_token IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM %(S)s.user_token t WHERE t.user_id = u.id);
  RAISE NOTICE 'B4  user.access_token without a user_token row : %% (dead, not carried)', n;
  FOR n IN SELECT count(*) FROM %(D)s.report_expense_attachment LOOP
    RAISE NOTICE 'B4  report_expense_attachment : %% (filled by 04)', n;
  END LOOP;
END $$;
""" % {"S": SRC, "D": DST}

R2 = """-- R2 -- expense references. Every kept expense that named a Xero account or
-- contact in the source still points at a row here (resolved, or RESTORED - see
-- gen.py PRE for why rows were missing). The restored counts are the measured
-- ones; a fresh dump that differs is re-measured, not waved through.
DO $$
DECLARE a bigint; c bigint; lost_a bigint; lost_c bigint;
BEGIN
  SELECT count(*) INTO c FROM %(D)s.xero_contact_sync WHERE category = 'restored';
  SELECT count(*) INTO a FROM %(D)s.account_info WHERE description LIKE 'restored by the schema migration%%%%';
  SELECT count(*) INTO lost_a FROM %(S)s.shop_expense se JOIN %(D)s.report_expense d ON d.id = se.id::uuid
   WHERE NULLIF(se.account_id,'') IS NOT NULL AND d.account_id IS NULL;
  SELECT count(*) INTO lost_c FROM %(S)s.shop_expense se JOIN %(D)s.report_expense d ON d.id = se.id::uuid
   WHERE NULLIF(se.contact_id,'') IS NOT NULL AND d.contact_id IS NULL;
  RAISE NOTICE 'R2  restored xero_contact_sync rows : %%   (expected 238)   %%', c, CASE WHEN c = 238 THEN 'OK' ELSE '*** CHANGED ***' END;
  RAISE NOTICE 'R2  restored account_info rows      : %%   (expected 10)    %%', a, CASE WHEN a = 10 THEN 'OK' ELSE '*** CHANGED ***' END;
  RAISE NOTICE 'R2  expenses that lost their account : %%   %%', lost_a, CASE WHEN lost_a = 0 THEN 'OK' ELSE '*** LOST ***' END;
  RAISE NOTICE 'R2  expenses that lost their contact : %%   %%', lost_c, CASE WHEN lost_c = 0 THEN 'OK' ELSE '*** LOST ***' END;
  IF lost_a > 0 OR lost_c > 0 THEN RAISE EXCEPTION 'R2: an expense lost a reference the source had'; END IF;
  IF c <> 238 OR a <> 10 THEN RAISE EXCEPTION 'R2: restored-row counts changed - re-measure before trusting the load'; END IF;
END $$;
""" % {"S": SRC, "D": DST}

ZERO_COUNTS = """-- ==================================================================
--  DECISION 12's NULL CONTRACT, KEPT
-- ==================================================================
-- report.actual_cash_total is replaced by the view report_cash_summary, which
-- sums report_cash_count rows and is NULL where a report has none. The app
-- stores no row for a denomination counted as zero - so a report counted as
-- ALL zero has no rows either, and the source told the two apart only by the
-- column: 0 for "counted, nothing in the till", NULL for "never counted".
-- 284 posted reports (2026-09-16 dump; 190 in August) are the former.
-- Without help the view would report them as never counted.
--
-- So each of them gets ONE row: quantity 0 of the smallest denomination of the
-- entity's currency, under a deterministic id. The view then returns 0, which
-- is what the column said. The row is inert - the app would delete it on the
-- next save, and posted reports are not saved again.
INSERT INTO %(D)s.report_cash_count (id, report_id, cash_id, quantity, cash_value)
SELECT md5('zero-count:'||s.id)::uuid, d.id, ci.id, 0, ci.cash_value
  FROM %(S)s.report s
  JOIN %(D)s.report d ON d.id = NULLIF(s.id,'')::uuid
  JOIN %(D)s.entities e ON e.id = d.entity_id
  JOIN LATERAL (SELECT ci.id, ci.cash_value FROM %(D)s.cash_info ci
                 WHERE ci.currency_id = e.currency_id ORDER BY ci.cash_value, ci.id LIMIT 1) ci ON true
 WHERE s.actual_cash_total = 0
   AND NOT EXISTS (SELECT 1 FROM %(D)s.report_cash_count c WHERE c.report_id = d.id);

-- R4 -- how many reports needed the zero row, and none of them still reads NULL.
DO $$
DECLARE n bigint; still_null bigint;
BEGIN
  SELECT count(*) INTO n FROM %(D)s.report_cash_count WHERE id IN
    (SELECT md5('zero-count:'||s.id)::uuid FROM %(S)s.report s WHERE s.actual_cash_total = 0);
  SELECT count(*) INTO still_null FROM %(S)s.report s
    JOIN %(D)s.report d ON d.id = NULLIF(s.id,'')::uuid
    LEFT JOIN %(D)s.report_cash_summary v ON v.report_id = d.id
   WHERE s.actual_cash_total = 0 AND v.actual_cash_total IS NULL;
  -- 7 of the 284 are Test_1 (PHP): the catalogue has no PHP denominations, so
  -- there is no row to carry the zero on and the app could never have counted
  -- them either. Reported and asserted, not carried.
  RAISE NOTICE 'R4  zero-count rows added : %%   (expected 277)   %%', n, CASE WHEN n = 277 THEN 'OK' ELSE '*** CHANGED ***' END;
  RAISE NOTICE 'R4  zero-counted reports with no denomination for their currency (still NULL) : %%   (expected 7)   %%', still_null, CASE WHEN still_null = 7 THEN 'OK' ELSE '*** CHANGED ***' END;
  IF n <> 277 OR still_null <> 7 THEN RAISE EXCEPTION 'R4: zero-count numbers changed - re-measure before trusting the load'; END IF;
END $$;
""" % {"S": SRC, "D": DST}

R7 = """-- R7 -- the sales did not move. Per kept report, the report_sale rows sum to
-- what the source's report_sale_detail rows summed to, and the two roll-up
-- columns equal the source's (cashsale_total = cash_sales, nocashsale_total =
-- total_sales - cash_sales). Reports whose SOURCE columns already disagree with
-- their own rows are counted and shown; they are the source's inconsistency,
-- carried faithfully, not the load's.
DO $$
DECLARE rows_moved bigint; cols_moved bigint; src_inconsistent bigint; total bigint;
BEGIN
  SELECT count(*) INTO total FROM %(D)s.report;
  SELECT count(*) INTO rows_moved FROM %(D)s.report d JOIN %(S)s.report s ON NULLIF(s.id,'')::uuid = d.id
   WHERE round(COALESCE((SELECT sum(rs.amount) FROM %(D)s.report_sale rs WHERE rs.report_id = d.id), 0), 2)
      <> round(COALESCE((SELECT sum(x.amount) FROM %(S)s.report_sale_detail x WHERE x.report_id = s.id), 0)::numeric, 2);
  SELECT count(*) INTO cols_moved FROM %(D)s.report d JOIN %(S)s.report s ON NULLIF(s.id,'')::uuid = d.id
   WHERE round(COALESCE(d.cashsale_total,0), 2) <> round(COALESCE(s.cash_sales,0)::numeric, 2)
      OR round(COALESCE(d.nocashsale_total,0), 2) <> round(COALESCE(s.total_sales,0)::numeric - COALESCE(s.cash_sales,0)::numeric, 2)
      OR round(COALESCE(d.total_sales,0), 2) <> round(COALESCE(s.total_sales,0)::numeric, 2);
  SELECT count(*) INTO src_inconsistent FROM %(D)s.report d
   WHERE EXISTS (SELECT 1 FROM %(D)s.report_sale rs WHERE rs.report_id = d.id)
     AND round(COALESCE(d.cashsale_total,0) + COALESCE(d.nocashsale_total,0), 2)
      <> round(COALESCE((SELECT sum(rs.amount) FROM %(D)s.report_sale rs WHERE rs.report_id = d.id), 0), 2);
  RAISE NOTICE 'R7  sales : %% reports, rows moved on %%, columns moved on %%   %%', total, rows_moved, cols_moved,
    CASE WHEN rows_moved = 0 AND cols_moved = 0 THEN 'OK' ELSE '*** MOVED ***' END;
  RAISE NOTICE 'R7  sales : %% report(s) whose own columns disagree with their rows (source inconsistency, carried as-is)', src_inconsistent;
  IF rows_moved > 0 OR cols_moved > 0 THEN RAISE EXCEPTION 'R7: sales moved during the load'; END IF;
END $$;

-- R8 -- the cash-count view reproduces report.actual_cash_total, and NULL stays
-- NULL (01 header, item 12: an uncounted report is not a zero count).
DO $$
DECLARE bad bigint; counted bigint;
BEGIN
  SELECT count(*) INTO counted FROM %(S)s.report WHERE actual_cash_total IS NOT NULL;
  SELECT count(*) INTO bad
    FROM %(S)s.report s
    JOIN %(D)s.report d ON d.id = NULLIF(s.id,'')::uuid
    LEFT JOIN %(D)s.report_cash_summary v ON v.report_id = d.id
   WHERE ((s.actual_cash_total IS NULL) <> (v.actual_cash_total IS NULL)
      OR round(s.actual_cash_total::numeric, 2) <> round(v.actual_cash_total, 2))
     AND EXISTS (SELECT 1 FROM %(D)s.cash_info ci JOIN %(D)s.entities e ON e.currency_id = ci.currency_id WHERE e.id = d.entity_id);
  RAISE NOTICE 'R8  actual_cash_total via view : %% counted reports, %% mismatched (currencies with denominations)   %%',
    counted, bad, CASE WHEN bad = 0 THEN 'OK' ELSE '*** MISMATCH ***' END;
  IF bad > 0 THEN RAISE EXCEPTION 'R8: %% report(s) where the view disagrees with actual_cash_total', bad; END IF;
END $$;
""" % {"S": SRC, "D": DST}


def emit(path, head, tables, label):
    stmts = "\n\n".join(filter(None, (PRE.get(t, "") + (copy_stmt(t) or "") for t in tables)))
    body = (head + truncate_stmt(tables) + "\n\n\n-- ==================================================================\n"
            "--  THE COPY\n-- ==================================================================\n\n"
            + stmts + "\n\n\n-- ==================================================================\n"
            "--  CHECKS\n-- ==================================================================\n\n"
            + check_counts(label, tables) + "\n" + check_enums(label, tables) + "\n"
            + (B4 + "\n" if label == "B" else "")
            + check_keys(label, tables) + "\n" + check_money(label, tables) + "\n"
            + (R2 + "\n" + ZERO_COUNTS + "\n" + R7 + "\n" if label == "R" else "")
            + "ROLLBACK;\n")
    io.open(path, "w", encoding="utf-8", newline="\n").write(body)
    print("wrote %s (%d tables)" % (os.path.basename(path), len(tables)))


emit(os.path.join(OUT, "02_data_foundation_rebased.sql"), HEAD02, f_tables, "B")
emit(os.path.join(OUT, "03_data_reports_rebased.sql"), HEAD03, r_tables, "R")


# ---- 00: every distinct source value, through its mapping, against the enum --
def emit_00():
    rows = []
    for t in order:
        st, cols, _o, _m = plan_table(t)
        exprs = dict(cols)
        for c, dt, udt, _n, _d in tgt[t]:
            if dt != "USER-DEFINED" or c not in exprs:
                continue
            # the expression up to the final enum cast
            e = exprs[c]
            e = re.sub(r"::%s\.%s$" % (DST, udt), "", e)
            e = re.sub(r"::text$", "", e)
            rows.append((t, c, udt, st, e))
    blocks = "\n".join(
        """  ntot := 0; nbad := 0; bad := '';
  FOR v IN EXECUTE 'SELECT DISTINCT (%(e)s)::text AS val FROM %(S)s.%(st)s s' LOOP
    ntot := ntot + 1;
    BEGIN
      EXECUTE format('SELECT %%L::%(D)s.%(udt)s', v.val);
    EXCEPTION WHEN others THEN
      nbad := nbad + 1; bad := bad || CASE WHEN bad = '' THEN '' ELSE ', ' END || coalesce(quote_literal(v.val),'NULL');
    END;
  END LOOP;
  IF nbad > 0 THEN total_bad := total_bad + 1; END IF;
  RAISE NOTICE '%% %%.%%  %% distinct value(s)%%',
    CASE WHEN nbad = 0 THEN 'OK      ' ELSE 'REJECTS ' END, rpad('%(t)s',24), rpad('%(c)s',18), ntot,
    CASE WHEN nbad = 0 THEN '' ELSE '   -> rejected: ' || bad END;""" % {
            "e": e.replace("'", "''"), "S": SRC, "st": q(st), "D": DST, "udt": udt, "t": t, "c": c}
        for t, c, udt, st, e in rows)
    body = """-- ===========================================================================
-- pettycash_test :: enum coverage check   (GENERATED by generators/gen.py)
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/00_enum_coverage_check.sql
--
-- Read-only. Run it against a database that has BOTH pettycashv2 at head and
-- pettycash_test built by 01_schema_rebased.sql, BEFORE 02 and 03.
--
-- Every DISTINCT value each enum-backed column holds in the source is pushed
-- through the SAME mapping expression the loader will use (gen.py ENUM_MAP) and
-- then cast to the enum that will receive it. A value the mapping does not know
-- and the enum does not accept prints as REJECTS and the script exits non-zero.
--
-- That is the first half of the problem - values the data holds. The second
-- half, a value the code can PRODUCE but no row holds yet, is listed in the 01
-- header under item 18 and can only be found by reading the writers.
--
-- EXPECTED OUTPUT: every line OK.
-- ===========================================================================
DO $$
DECLARE v record; bad text; nbad int; ntot int; total_bad int := 0;
BEGIN
%s
  IF total_bad > 0 THEN RAISE EXCEPTION '00: %% column(s) hold a value their enum rejects', total_bad; END IF;
END $$;
""" % blocks
    io.open(os.path.join(OUT, "00_enum_coverage_check.sql"), "w", encoding="utf-8", newline="\n").write(body)
    print("wrote 00_enum_coverage_check.sql (%d columns)" % len(rows))


emit_00()
