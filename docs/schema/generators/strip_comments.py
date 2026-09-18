# -*- coding: utf-8 -*-
"""Write a comment-free copy of 01_schema_rebased.sql for pasting into a SQL editor.

    python docs/schema/generators/strip_comments.py

Reads 01 / 00 / 02 / 03, writes them under supabase/ - 01 as pettycashv3.sql with the
schema renamed to pettycashv3, the others under their own names. Strips
`--` line comments and `/* */` blocks (the dead app_user block included), inside
$$-quoted bodies too, but never the inside of a string literal, and
keeps every COMMENT ON statement - those are DDL, the register the schema
carries inside the database (01 header, ERA 1 A4). Blank runs collapse to one
line. The result must build byte-for-byte the same schema; rehearse.py's
build step proves the commented file, docs/schema/README.md says how to prove
this one.
"""
import io, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["01_schema_rebased.sql", "00_enum_coverage_check.sql",
         "02_data_foundation_rebased.sql", "03_data_reports_rebased.sql"]
SRC_DIR = os.path.join(HERE, "..")
DST_DIR = os.path.join(HERE, "..", "supabase")


def strip(sql: str) -> str:
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        # single-quoted literal (with '' escapes)
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1]); i = j + 1; continue
        # dollar-quoted body: $$ or $tag$
        m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
        if m:
            tag = m.group(0)
            j = sql.find(tag, i + len(tag))
            if j < 0:
                out.append(sql[i:]); i = n; continue
            body = sql[i + len(tag):j]
            # a PL/pgSQL body has the same comment syntax; strip it the same way
            out.append(tag + strip(body).rstrip("\n") + "\n" + tag); i = j + len(tag); continue
        # double-quoted identifier
        if c == '"':
            j = sql.find('"', i + 1)
            j = n if j < 0 else j
            out.append(sql[i:j + 1]); i = j + 1; continue
        # line comment
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            continue
        # block comment
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c); i += 1
    text = "".join(out)
    # trailing spaces, then collapse blank runs
    text = "\n".join(l.rstrip() for l in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text


# The schema file is written as supabase/pettycashv3.sql with the schema renamed
# pettycash_test -> pettycashv3, the name it will carry on Supabase. The 01
# header's own rule: the name appears only as a qualifier, so a plain
# replacement is exact (asserted below).
SUPABASE_SCHEMA = "pettycashv3"

if __name__ == "__main__":
    os.makedirs(DST_DIR, exist_ok=True)
    for name in FILES:
        sql = io.open(os.path.join(SRC_DIR, name), encoding="utf-8").read()
        plain = strip(sql)
        if name == "01_schema_rebased.sql":
            assert not re.search(r"pettycash_test(?![.\s;])", plain), "schema name used other than as a qualifier"
            renamed = plain.replace("pettycash_test", SUPABASE_SCHEMA)
            out = os.path.join(DST_DIR, SUPABASE_SCHEMA + ".sql")
            io.open(out, "w", encoding="utf-8", newline="\n").write(renamed)
            print("wrote supabase/%s.sql (schema %s): %d -> %d lines"
                  % (SUPABASE_SCHEMA, SUPABASE_SCHEMA, sql.count("\n"), renamed.count("\n")))
            continue
        io.open(os.path.join(DST_DIR, name), "w", encoding="utf-8", newline="\n").write(plain)
        print("wrote supabase/%s: %d -> %d lines" % (name, sql.count("\n"), plain.count("\n")))
