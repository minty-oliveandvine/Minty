# -*- coding: utf-8 -*-
"""Render APPLICATION_CHANGES.md from the model audit."""
import io, os, subprocess, sys, collections, re

SP = os.path.dirname(os.path.abspath(__file__))
OUT = r"c:\dev\Minty\docs\schema\APPLICATION_CHANGES.md"

env = dict(os.environ); env["PYTHONUTF8"] = "1"
env.setdefault("AUDIT_DB", "minty_cleanse"); env.setdefault("AUDIT_SCHEMA", "pettycashv3")
raw = subprocess.run([sys.executable, os.path.join(SP, "audit_models.py")],
                     capture_output=True, text=True, env=env, encoding="utf-8").stdout

rows = []
for line in raw.splitlines():
    m = re.match(r"^(Minty|billing-backend|onboarding-backend)\s+(TABLE|MISSING|TYPE)\s+(\S+)\s+(\S+):(\d+)\s+(.*)$", line)
    if m:
        rows.append(dict(repo=m.group(1), kind=m.group(2), table=m.group(3),
                         file=m.group(4), line=int(m.group(5)), what=m.group(6).strip()))

tables  = [r for r in rows if r["kind"] == "TABLE"]
missing = [r for r in rows if r["kind"] == "MISSING"]
types   = [r for r in rows if r["kind"] == "TYPE"]

RENAME = {
    "invitations": "invitation", "roles": "role", "permissions": "permission",
    "role_permissions": "role_permission", "report_sale_detail": "report_sale",
    "shop_expense": "report_expense", "entity_cash_detail_v2": "entity_cash_detail",
    "audit": "bill_audit", "bill_line_item": "bill_line",
}

def link(r):
    return "[%s:%d](%s#L%d)" % (r["file"], r["line"], r["file"], r["line"])

d = []
w = d.append
w("# Application changes required by `pettycashv3`")
w("")
w("Generated, not hand-written. Regenerate after any schema or model change:")
w("")
w("```")
w("python docs/schema/generators/audit_models.py     # the raw findings (AUDIT_DB=minty_cleanse, AUDIT_SCHEMA=pettycashv3 by default)")
w("python docs/schema/generators/mkdoc.py            # this document")
w("```")
w("")
w("It compares every model in **Minty** (SQLAlchemy), **billing-backend** and")
w("**onboarding-backend** (Django) against the schema `01_schema_rebased.sql` builds, and")
w("reports three things: a model whose table no longer exists under that name, a model")
w("column the schema does not have, and a declared type that no longer matches the column.")
w("")
w("Paths are relative to each repo root — `c:\\dev\\Minty`, `c:\\dev\\billing-backend`,")
w("`c:\\dev\\onboarding-backend`.")
w("")
w("**%d findings: %d table, %d column, %d type.**" % (len(rows), len(tables), len(missing), len(types)))
w("")
if not rows:
    w("Zero is the closed state of Part 1 phase C (`docs/modernisation/modernisation_plan.md`),")
    w("reached 2026-09-17 and held by `tests/test_zz_schema_audit.py`, which runs this audit")
    w("against the harness's fresh build of `01` on every Postgres test run. A finding here")
    w("again means a model was edited without the schema, or the schema without the model.")
    w("")
w("---")
w("")
w("## 0. How the 287 findings were closed")
w("")
w("The count at the start of phase C, measured against `minty_cleanse` (production data on")
w("the new schema): **Minty 157, billing-backend 65, onboarding-backend 71**. The schema was")
w("authoritative throughout — where code and schema disagreed, the code changed — and each")
w("unit's gate was zero findings on its tables in all three repos. The running totals:")
w("")
w("| unit | tables | Minty | billing-backend | onboarding-backend |")
w("|---|---|---|---|---|")
w("| start (2026-09-16) | | 157 | 65 | 71 |")
w("| **C1** identity | `user`, `user_token`, `user_entity`, `email_otp` | 139 | 56 | 64 |")
w("| **C2** entities and modules | `entities`, `entity_function`, `entity_function_map`, `country_info`, `currency_info` | 121 | 43 | 43 |")
w("| **C3** sales catalogue | `sale_info`, `entity_sale_setting` | 105 | 43 | 27 |")
w("| **C4** report core | `report`, `report_sale`, `report_expense`, `report_expense_attachment`, `attachment`, `report_cash_count`, `report_history`, `entity_cash_detail`, `entity_cash_setting`, `entity_pettycash_settings`, `cash_info`, `share_link` | 50 | 43 | 2 |")
w("| **C5** Xero sync | `account_info`, `entity_account_xero`, `xero_contact_sync`, `xero_report_sync`, `xero_bank_transaction`, `xero_bank_transfer` | 26 | 39 | 2 |")
w("| **C6** access | `role`, `permission`, `role_permission`, `invitation`, `terms_consent` | 21 | 39 | 1 |")
w("| **C7** subscription and billing (Minty side) | the 13 `billing_*` / `subscription_*` / `entity_module_subscription` / `payer_billing_group` tables | **0** | 39 | **0** |")
w("| **C8** billing-backend | `bill`, `bill_line`, `bill_audit`, `payment`, the attachment links, `xero_bill_*`, `entity_bill_*` | 0 | **0** | 0 |")
w("| **C9** onboarding-backend | the mirrors, re-checked | 0 | 0 | 0 |")
w("| **C10** close-out | audit 0 against the harness build and `minty_cleanse`; Minty 1674 passed on Postgres | 0 | 0 | 0 |")
w("")
w("What each unit changed, decision by decision, is recorded in the unit's close-out in the")
w("plan document; the vocabulary the code now writes (the enum words) is item 18 of the")
w("decision register in `01_schema_rebased.sql`'s header. The three copies of that vocabulary")
w("— `blueprints/shared/enums.py`, the two `shared_models/enums.py` — are checked against `01`")
w("by `tests/test_enums_match_schema.py`.")
w("")
w("Two findings the original audit could not see, both closed: **D6** `user.system_role` was")
w("commented out in the schema (uncommented in phase A, enum `normal / admin / superadmin`,")
w("the JWT claim `superuser` → `superadmin` across all three repos in C1); and")
w("`entity_function_map.created_by` was written as an actor *label* where the schema has a")
w("uuid FK to `user` (C2: `_write_pairs(..., user_id)` — the person, or NULL for a job).")
w("")
w("---")
w("")
w("## 1. Renamed tables — %d" % len(tables))
w("")
if tables:
    w("`__tablename__` / `db_table` no longer resolves. Nothing on these models works.")
    w("")
else:
    w("None. The nine renames (`roles/permissions/role_permissions → role/permission/role_permission`,")
    w("`invitations → invitation`, `report_sale_detail → report_sale`, `shop_expense → report_expense`,")
    w("`entity_cash_detail_v2 → entity_cash_detail`, `audit → bill_audit`, `bill_line_item → bill_line`)")
    w("landed in C4, C6 and C8.")
    w("")
if tables:
    w("| repo | old | new | declared at |")
    w("|---|---|---|---|")
    for r in sorted(tables, key=lambda r: (r["repo"], r["table"])):
        w("| %s | `%s` | `%s` | %s |" % (r["repo"], r["table"],
                                         RENAME.get(r["table"], "**?**"), link(r)))
    w("")
    w("The class names follow the table where it reads oddly otherwise —")
    w("`ShopExpense` becomes report_expense, `ReportSaleDetail` becomes report_sale.")
    w("Both are more than renames: check the column lists in section 2 before assuming")
    w("a one-line change.")
    w("")
w("---")
w("")
w("## 2. Model columns the schema does not have — %d" % len(missing))
w("")
if missing:
    w("**These break every SELECT on the model**, not just writes: an ORM selects all")
    w("mapped columns, so one stale attribute takes the whole table down. Fix these first.")
    w("")
else:
    w("None.")
    w("")
by = collections.OrderedDict()
for r in sorted(missing, key=lambda r: (r["repo"], r["file"], r["line"])):
    by.setdefault((r["repo"], r["file"], r["table"]), []).append(r)
for (repo, f, t), rs in by.items():
    w("#### `%s` — %s (%s)" % (t, f, repo))
    w("")
    for r in rs:
        w("- `%s` — line %d" % (r["what"], r["line"]))
    w("")
w("---")
w("")
w("## 3. Declared types that no longer match — %d" % len(types))
w("")
cnt = collections.Counter(r["what"].rsplit("schema is ", 1)[-1] for r in types)
if not types:
    w("None. Every id is `MintyUuid` / `UUIDField`, every money column `Money()` /")
    w("`DecimalField(14, 2)`, every stamp `DateTime(timezone=True)` / `db_default=Now()`,")
    w("every enum a `pg_enum(...)` / `PgEnumField` over the shared vocabulary")
    w("(`blueprints/shared/column_types.py`, the two `shared_models/fields.py`).")
    w("")
if types:
    w("| schema type | count | what the models declare |")
    w("|---|---|---|")
    w("| `uuid` | %d | `db.String(36)` / `models.CharField(max_length=36)` |" % cnt["uuid"])
    w("| `numeric` | %d | `db.Float` — money, so this one is a correctness fix, not cosmetic |" % cnt["numeric"])
    w("| enums | %d | `db.String` / `models.CharField(choices=...)` |"
      % sum(v for k, v in cnt.items() if k not in
            ("uuid", "numeric", "timestamp with time zone", "character", "smallint", "jsonb", "date")))
    w("| `timestamp with time zone` | %d | `db.DateTime` with no `timezone=True` |" % cnt["timestamp with time zone"])
    w("| other | %d | `character`, `smallint`, `jsonb`, `date` |"
      % (cnt["character"] + cnt["smallint"] + cnt["jsonb"] + cnt["date"]))
    w("")
    w("None of these stops the app the way section 2 does — Postgres casts a great deal")
    w("on the way in. They matter for a different reason:")
    w("")
    w("- **`uuid` vs `String(36)`** — comparisons still work, but an index on a uuid")
    w("  column is not used the same way when the parameter arrives as text, and a")
    w("  malformed value fails at the database rather than in validation.")
    w("- **`numeric` vs `Float`** — this one is a real bug. Binary floating point cannot")
    w("  represent money exactly; the schema moved to `numeric` deliberately and a model")
    w("  still declaring `Float` reintroduces the rounding the change was meant to remove.")
    w("- **enum vs `String`** — the database now rejects a value outside the enum. That is")
    w("  the point, but it turns a silent bad write into a 500, so it wants testing.")
    w("- **`DateTime` without `timezone=True`** — the column is `timestamptz`; a naive")
    w("  datetime is normalised to the *session* timezone, not to UTC.")
    w("")
    w("Full list, grouped by file:")
    w("")
    byf = collections.OrderedDict()
    for r in sorted(types, key=lambda r: (r["repo"], r["file"], r["line"])):
        byf.setdefault((r["repo"], r["file"]), []).append(r)
    for (repo, f), rs in byf.items():
        w("<details><summary><code>%s</code> (%s) — %d</summary>" % (f, repo, len(rs)))
        w("")
        for r in rs:
            w("- line %d: %s" % (r["line"], r["what"]))
        w("")
        w("</details>")
        w("")
w("---")
w("")
w("## 4. What is deliberately NOT a finding")
w("")
w("- **`Money()` reads back as `float`** (`asdecimal=False`). The database column is exact")
w("  `numeric(14,2)`; the in-process arithmetic still runs in float in a few hundred places,")
w("  and moving it to `Decimal` is a separate pass. `cents()` rounds every computed amount")
w("  before it is written, and `tests/test_char_money.py` pins the stored values.")
w("- **Behaviour the schema reversed** — the audit trail no longer survives a report's")
w("  deletion (FK cascade), `entity_status` means the Xero connection state, `sale_info` is")
w("  one global catalogue — is recorded per unit in the plan document, with the tests that")
w("  were rewritten to the new meaning.")
w("- **Alembic is frozen.** A schema change is an edit to `01_schema_rebased.sql` (ask first)")
w("  plus `gen.py`, then `minty_cleanse` is rebuilt with `rehearse.py`; `Minty/migrations/` is")
w("  deleted at the cutover (phase E) and `billing-backend/bills/migrations/` is already gone.")
w("")

io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(d) + "\n")
print("wrote", OUT, "-", len(rows), "findings")
