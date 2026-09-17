# -*- coding: utf-8 -*-
"""Render APPLICATION_CHANGES.docx from the model audit.

Deliberately generated from the SAME audit output as mkdoc.py, not converted
from the Markdown - so the two cannot drift apart. Run with the venv python:

    .venv/Scripts/python.exe docs/schema/generators/mkdocx.py
"""
import collections, io, os, re, subprocess, sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt, RGBColor, Inches

SP = os.path.dirname(os.path.abspath(__file__))
OUT = r"c:\dev\Minty\docs\schema\APPLICATION_CHANGES.docx"

MONO = "Consolas"
GREY = RGBColor(0x60, 0x60, 0x60)
RED = RGBColor(0xA6, 0x1B, 0x1B)

# --------------------------------------------------------------------------
env = dict(os.environ)
env["PYTHONUTF8"] = "1"
raw = subprocess.run([sys.executable, os.path.join(SP, "audit_models.py")],
                     capture_output=True, text=True, env=env,
                     encoding="utf-8").stdout

rows = []
for line in raw.splitlines():
    m = re.match(r"^(Minty|billing-backend)\s+(TABLE|MISSING|TYPE)\s+(\S+)\s+"
                 r"(\S+):(\d+)\s+(.*)$", line)
    if m:
        rows.append(dict(repo=m.group(1), kind=m.group(2), table=m.group(3),
                         file=m.group(4), line=int(m.group(5)),
                         what=m.group(6).strip()))
if not rows:
    sys.exit("audit produced no findings - refusing to write an empty document")

tables = [r for r in rows if r["kind"] == "TABLE"]
missing = [r for r in rows if r["kind"] == "MISSING"]
types = [r for r in rows if r["kind"] == "TYPE"]

RENAME = {
    "invitations": "invitation", "roles": "role", "permissions": "permission",
    "role_permissions": "role_permission", "report_sale_detail": "report_sale",
    "shop_expense": "report_expense", "entity_cash_detail_v2": "entity_cash_detail",
    "audit": "bill_audit", "bill_line_item": "bill_line",
}

doc = Document()
for name, size in (("Normal", 10),):
    st = doc.styles[name]
    st.font.name = "Calibri"
    st.font.size = Pt(size)


def para(text="", bold=False, italic=False, size=None, color=None, space_after=6):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(space_after)
    return p


def rich(parts, space_after=6):
    """parts: list of (text, style) where style in {'', 'b', 'i', 'c'}."""
    p = doc.add_paragraph()
    for text, style in parts:
        r = p.add_run(text)
        if "b" in style:
            r.bold = True
        if "i" in style:
            r.italic = True
        if "c" in style:
            r.font.name = MONO
            r.font.size = Pt(9)
    p.paragraph_format.space_after = Pt(space_after)
    return p


def table(headers, data, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(9)
    for row in data:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(str(v))
            r.font.size = Pt(9)
            if i == 0 or str(v).startswith(("`", "blueprints/", "bills/", "shared_models/")):
                r.font.name = MONO
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


# ==========================================================================
doc.add_heading("Application changes required by pettycash_test", 0)
para("Generated from the model audit, not hand-written. Regenerate after any "
     "schema or model change.", italic=True, color=GREY)
rich([(".venv/Scripts/python.exe docs/schema/generators/mkdocx.py", "c")])
para()

para("It compares every model in Minty (SQLAlchemy) and billing-backend (Django) against "
     "the schema 01_schema_rebased.sql builds, and reports three things: a model whose "
     "table no longer exists under that name, a model column the schema does not have, "
     "and a declared type that no longer matches the column.")
rich([("%d findings: " % len(rows), "b"),
      ("%d table, %d column, %d type." % (len(tables), len(missing), len(types)), "")])
para("Paths are relative to each repo root - c:\\dev\\Minty and c:\\dev\\billing-backend.",
     color=GREY)

para("The audit reads source with utf-8-sig. Several of these files carry a BOM, and an "
     "earlier version used utf-8, so ast.parse raised and the file was skipped silently - "
     "which hid the entire User model and 57 other findings. The script now reports any "
     "file it cannot parse instead of skipping quietly.", italic=True, color=GREY)

# ---- 0. decisions --------------------------------------------------------
doc.add_heading("0.  Six open decisions - the code side", 1)
para("The schema files carry these as D1-D6 (DECISIONS REQUIRED AT REVIEW in "
     "01_schema_rebased.sql, and again beside the statement each one lands on in 02/03). "
     "This is what each costs here, in the application.")
para("The enums were widened so the merge would be lossless. The consequence is that "
     "where the merged data and the code disagree, the database accepts both and nothing "
     "raises - the feature just returns nothing. None of these is a crash; all of them "
     "are silent.", bold=True)

table(["", "Column", "If the DATA wins (map on the way in)", "If the CODE wins (change these)"],
      [["D3", "report.status\n3,724 rows say published, code says posted",
        "one mapping in 03",
        "ending.py:483, :1568; history_query.py:90, :111; models/report.py:51"],
       ["D4", "sale_info.type\ndata electric/delivery, code Electronic/Delivery",
        "one mapping in 03",
        "46 Python sites - onboarding_state.py:166, :172-173; payment_methods.py:89, "
        ":209, :268; models/sale_info.py:109 - plus five electronic_delivery_* templates"],
       ["D5", "invitation.status\n40 rows say revoked, code writes cancelled",
        "one mapping in 02", "one site"]],
      widths=[0.4, 2.0, 1.6, 2.5])

para("D1 and D2 have no code side. They are data already lost upstream, in the schema-2 "
     "build, before 02/03 read it - 460 report.discrepancy_type rows flattened to none, "
     "and 9 entities folded into onboarding. Recovering them means fixing that build; "
     "leaving them means the code keeps writing values the migrated data never shows.")
para("D4 is the one to look at twice. 'electric' is a misspelling of electronic, so "
     "letting the data win writes a typo permanently into 46 call sites and five templates.")

# ---- D6 ------------------------------------------------------------------
doc.add_heading("D6  -  fix the schema, not the code", 1)
doc.add_heading("user.system_role does not exist", 2)
para("01_schema_rebased.sql declares the enum - CREATE TYPE pettycash_test.system_role "
     "AS ENUM ('normal','admin','superadmin') - but the column is commented out in the "
     "user table, at both the live definition and the dead block above it. No column "
     "anywhere uses that type.")
para("It was commented out in the original 01_schema 2.sql, with no reason given, and the "
     "rebase inherited it. The application depends on it:")
table(["", "Where"],
      [["declared", "blueprints/auth/models/user.py:41"],
       ["gates superuser at login", "blueprints/auth/routes/login.py:31, "
        "blueprints/auth/routes/email_auth.py:48"],
       ["written", "blueprints/invitation/services/invite.py:82"],
       ["read", "blueprints/user_management/routes/admin_dashboard.py:38, "
        "blueprints/legal/routes/accept.py:134"],
       ["mirrored in billing-backend", "shared_models/models.py:13"]],
      widths=[1.8, 4.7])
para("There is nowhere else to put a global superuser flag - user_entity.role is "
     "per-entity and role is a different concept. Uncommenting the column is the fix; "
     "the enum is already there and already correct. Until then the superuser gate has "
     "no backing store.", bold=True)

# ---- 1. renamed tables ---------------------------------------------------
doc.add_heading("1.  Renamed tables  -  %d" % len(tables), 1)
para("__tablename__ / db_table no longer resolves. Nothing on these models works.")
table(["Repo", "Old", "New", "Declared at"],
      [[r["repo"], r["table"], RENAME.get(r["table"], "?"),
        "%s:%d" % (r["file"], r["line"])]
       for r in sorted(tables, key=lambda r: (r["repo"], r["table"]))],
      widths=[1.1, 1.6, 1.5, 2.3])
para("The class names follow the table where it reads oddly otherwise - ShopExpense "
     "becomes report_expense, ReportSaleDetail becomes report_sale. Both are more than "
     "renames: check the column lists in section 2 before assuming a one-line change.")

# ---- 2. missing columns --------------------------------------------------
doc.add_heading("2.  Model columns the schema does not have  -  %d" % len(missing), 1)
para("These break every SELECT on the model, not just writes: an ORM selects all mapped "
     "columns, so one stale attribute takes the whole table down. Fix these first.",
     bold=True, color=RED)
by = collections.OrderedDict()
for r in sorted(missing, key=lambda r: (r["repo"], r["file"], r["line"])):
    by.setdefault((r["repo"], r["file"], r["table"]), []).append(r)
table(["Table", "File", "Columns"],
      [[t, f, ", ".join("%s (%d)" % (r["what"], r["line"]) for r in rs)]
       for (repo, f, t), rs in by.items()],
      widths=[1.4, 2.3, 2.8])

# ---- 3. types ------------------------------------------------------------
doc.add_heading("3.  Declared types that no longer match  -  %d" % len(types), 1)
cnt = collections.Counter(r["what"].rsplit("schema is ", 1)[-1] for r in types)
enum_n = sum(v for k, v in cnt.items() if k not in
             ("uuid", "numeric", "timestamp with time zone", "character",
              "smallint", "jsonb", "date"))
table(["Schema type", "Count", "What the models declare"],
      [["uuid", cnt["uuid"], "db.String(36) / models.CharField(max_length=36)"],
       ["numeric", cnt["numeric"], "db.Float - money, so a correctness fix, not cosmetic"],
       ["enums", enum_n, "db.String / models.CharField(choices=...)"],
       ["timestamp with time zone", cnt["timestamp with time zone"],
        "db.DateTime with no timezone=True"],
       ["other", cnt["character"] + cnt["smallint"] + cnt["jsonb"] + cnt["date"],
        "character, smallint, jsonb, date"]],
      widths=[2.0, 0.7, 3.8])

para("None of these stops the app the way section 2 does - Postgres casts a great deal on "
     "the way in. They matter for a different reason:")
for t in [
    "uuid vs String(36) - comparisons still work, but an index on a uuid column is not "
    "used the same way when the parameter arrives as text, and a malformed value fails at "
    "the database rather than in validation.",
    "numeric vs Float - this one is a real bug. Binary floating point cannot represent "
    "money exactly; the schema moved to numeric deliberately and a model still declaring "
    "Float reintroduces the rounding the change was meant to remove.",
    "enum vs String - the database now rejects a value outside the enum. That is the "
    "point, but it turns a silent bad write into a 500, so it wants testing.",
    "DateTime without timezone=True - the column is timestamptz; a naive datetime is "
    "normalised to the session timezone, not to UTC.",
]:
    doc.add_paragraph(t, style="List Bullet")

doc.add_heading("Full list, grouped by file", 2)
byf = collections.OrderedDict()
for r in sorted(types, key=lambda r: (r["repo"], r["file"], r["line"])):
    byf.setdefault((r["repo"], r["file"]), []).append(r)
for (repo, f), rs in byf.items():
    doc.add_heading("%s  (%s)  -  %d" % (f, repo, len(rs)), 3)
    table(["Line", "Change"], [[r["line"], r["what"]] for r in rs],
          widths=[0.7, 5.8])

# ---- 4. created_by -------------------------------------------------------
doc.add_heading("4.  Behavioural change: entity_function_map.created_by", 1)
para("Not a type mismatch - the audit passes it, because the model and the schema now "
     "disagree about meaning rather than about type. Recorded as item 10 of the decision "
     "register in 01_schema_rebased.sql.")
para("The column is a foreign key to user. The code writes an actor label:")
table(["", "Where"],
      [["the only write site",
        "blueprints/entity/services/modules.py:534, inside _write_pairs at :497"],
       ["the labels",
        "blueprints/entity/services/modules.py:60-62 - onboarding, cli, entity_create"],
       ["callers", "blueprints/entity/routes/create.py:1169; "
        "blueprints/entity/services/modules.py:393; "
        "blueprints/entity/routes/settings.py:1921 (\"subscription\")"],
       ["model", "blueprints/entity/models/entity_function.py:34 - String(36), no ForeignKey"],
       ["tests", "tests/test_module_access_gate.py:86, "
        "tests/test_onboarding_module_state.py:77"]],
      widths=[1.5, 5.0])
para("_write_pairs needs a user id parameter. Two of the four callers - cli and "
     "subscription - are jobs with no user, so their rows land NULL and the four paths "
     "stop being distinguishable. A nullable actor VARCHAR(20) beside the column keeps "
     "that provenance if it is wanted; not assumed here.")

# ---- order ---------------------------------------------------------------
doc.add_heading("Order to do this in", 1)
for i, t in enumerate([
    "Settle D1-D5 (section 0). Two of them change what the data says, so anything built "
    "against the current values may be built against the wrong ones.",
    "Uncomment user.system_role - D6, its own section above. A schema edit, and everything "
    "else is easier once the schema is settled.",
    "Section 2, the missing columns. Nothing can be tested until an ORM query against "
    "these tables runs at all.",
    "Section 1, the renames. Mechanical once the columns are right.",
    "Section 3's numeric rows. The money bug is the only type finding that is wrong "
    "rather than merely untidy.",
    "Section 4, whenever - the column accepts NULL, so nothing breaks meanwhile.",
    "The rest of section 3 as tidy-up.",
]):
    doc.add_paragraph(t, style="List Number")

doc.save(OUT)
print("wrote", OUT, "-", len(rows), "findings")
