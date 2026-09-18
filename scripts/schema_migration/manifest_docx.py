#!/usr/bin/env python
"""Render a rehearse.py manifest (<db>_not_carried.md) as a Word document.

    .venv/Scripts/python.exe scripts/schema_migration/manifest_docx.py backups/pcreh_20260916_not_carried.md

Writes the .docx beside the .md. Each "## section - N row(s)" becomes a heading
and a table; the column names come from the query that produced the section
(HEADERS below), so the reader does not have to guess what "f | t | 2026-06-11"
means. rehearse.py calls this after writing the manifest when python-docx is
importable, and says so in its log.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt, RGBColor

GREY = RGBColor(0x60, 0x60, 0x60)

# section title prefix -> column names (the manifest queries in rehearse.py)
HEADERS = {
    "Reports not carried (entity deleted)": ["report id", "entity id (deleted)", "transaction date", "status"],
    "Reports not carried (second row": ["report id", "entity", "transaction date", "status", "total sales", "expenses"],
    "Report children not carried": ["table", "rows"],
    "entity_function_map rows not carried": ["entity id (deleted)", "function", "enabled", "created"],
    "sale_info rows collapsed": ["sale_info id", "name", "type", "code", "entity"],
    "Users whose Xero tokens": ["user id", "username", "token created"],
    "Zero-counted reports with no denomination": ["report id", "entity", "currency", "transaction date"],
    "Source tables not loaded": ["table", "rows"],
}


def headers_for(title: str) -> list[str] | None:
    for prefix, cols in HEADERS.items():
        if title.startswith(prefix):
            return cols
    return None


def render(md_path: Path) -> Path:
    text = io.open(md_path, encoding="utf-8").read()
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    lines = text.splitlines()
    i = 0
    # title and preamble
    while i < len(lines):
        l = lines[i]
        if l.startswith("# "):
            doc.add_heading(l[2:].strip(), level=0)
        elif l.startswith("## "):
            break
        elif l.strip():
            doc.add_paragraph(l.strip())
        i += 1

    while i < len(lines):
        l = lines[i]
        if l.startswith("## "):
            title = l[3:].strip()
            m = re.match(r"^(.*?) - (\d+) row\(s\)$", title)
            name, count = (m.group(1), int(m.group(2))) if m else (title, None)
            doc.add_heading(name, level=1)
            if count is not None:
                p = doc.add_paragraph()
                r = p.add_run(f"{count} row(s)")
                r.font.color.rgb = GREY
            i += 1
            rows = []
            while i < len(lines) and not lines[i].startswith("## "):
                if lines[i].startswith("- "):
                    rows.append([c.strip() for c in lines[i][2:].split(" | ")])
                elif lines[i].strip() and not lines[i].startswith("#"):
                    doc.add_paragraph(lines[i].strip())
                i += 1
            if rows:
                cols = headers_for(name) or [f"col {n + 1}" for n in range(max(len(r) for r in rows))]
                width = max(len(cols), max(len(r) for r in rows))
                table = doc.add_table(rows=1, cols=width)
                table.style = "Light Grid Accent 1"
                table.alignment = WD_TABLE_ALIGNMENT.LEFT
                for n, c in enumerate(cols + [""] * (width - len(cols))):
                    cell = table.rows[0].cells[n]
                    cell.text = c
                    for p in cell.paragraphs:
                        for run in p.runs:
                            run.font.bold = True
                            run.font.size = Pt(9)
                for r in rows:
                    cells = table.add_row().cells
                    for n, v in enumerate(r + [""] * (width - len(r))):
                        cells[n].text = v
                        for p in cells[n].paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(8.5)
                                if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", v):
                                    run.font.name = "Consolas"
            continue
        i += 1

    # the trailing "## Columns" block is free text; it was consumed above as
    # paragraphs if present. Nothing else to do.
    out = md_path.with_suffix(".docx")
    doc.save(str(out))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(render(Path(sys.argv[1])))
