"""Convert one of the owner's design-guideline Word files to the Markdown mirror in docs/design/.

    python -I scripts/design_docs_to_md.py "<Downloads>/UX & User Flow/Part 13. ....docx" docs/design/part-13-....md

Why this exists
---------------
The guidelines (Parts 1-15, Stage 4) are written and approved as Word files outside any repo.
The Word file stays the master; ``docs/design/*.md`` is a read-only mirror so code work can
read and grep the rules. When a Part is revised, re-run this on the new file - never hand-edit
the Markdown, or the mirror and the master silently drift.

Several of the files store their body as ``word/document2.xml``, which plain unzip-and-read
extraction misses; python-docx follows the package relationships, so it reads them.

What it maps
------------
Title -> ``#``, Heading 1/2/3 -> ``##``/``###``/``####``; numbered or bulleted paragraphs ->
``1.`` / ``-`` indented by their level; bold runs -> ``**``; tables -> pipe tables (``|``
escaped, cell paragraphs joined with ``<br>``). It FAILS if the document has no text, or if the
output holds fewer table rows than the source - a dropped table must not look like success.
"""
import re
import sys
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

HEADING = {"Title": "#", "Heading 1": "##", "Heading 2": "###", "Heading 3": "####", "Heading 4": "#####"}


def _num_format(document, p):
    """'decimal'-like or 'bullet' for a numbered paragraph, else None; plus its level."""
    ppr = p._p.pPr
    if ppr is None or ppr.numPr is None or ppr.numPr.numId is None:
        return None, 0
    num_id = ppr.numPr.numId.val
    ilvl = ppr.numPr.ilvl.val if ppr.numPr.ilvl is not None else 0
    numbering = document.part.numbering_part.element
    ns = numbering.nsmap
    w = "{%s}" % ns["w"]
    for num in numbering.findall("w:num", ns):
        if num.get(w + "numId") != str(num_id):
            continue
        abs_id = num.find("w:abstractNumId", ns).get(w + "val")
        for absn in numbering.findall("w:abstractNum", ns):
            if absn.get(w + "abstractNumId") != abs_id:
                continue
            for lvl in absn.findall("w:lvl", ns):
                if lvl.get(w + "ilvl") == str(ilvl):
                    fmt = lvl.find("w:numFmt", ns)
                    return (fmt.get(w + "val") if fmt is not None else "bullet"), ilvl
    return "bullet", ilvl


def _escape(text):
    return re.sub(r"<(?=[A-Za-z/!])", "&lt;", text)


def _inline(p):
    out = []
    for item in p.iter_inner_content():
        runs = [item] if isinstance(item, Run) else list(item.runs)
        for r in runs:
            t = _escape(r.text)
            if not t:
                continue
            if r.bold and t.strip():
                lead = t[: len(t) - len(t.lstrip())]
                trail = t[len(t.rstrip()):]
                t = f"{lead}**{t.strip()}**{trail}"
            out.append(t)
    text = "".join(out).replace("****", "")
    return text.replace("\n", "  \n").strip()


def _cell(cell):
    parts = [_inline(p) for p in cell.paragraphs]
    return "<br>".join(x for x in parts if x).replace("  \n", "<br>").replace("|", "\\|")


def _table(t):
    rows = [[_cell(c) for c in row.cells] for row in t.rows]
    if not rows:
        return [], 0
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines, len(rows)


def convert(src: Path) -> tuple[str, int, int]:
    document = docx.Document(str(src))
    blocks, source_rows, written_rows = [], 0, 0
    first = True
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            source_rows += len(item.rows)
            lines, n = _table(item)
            written_rows += n
            if lines:
                blocks.append("\n".join(lines))
            continue
        assert isinstance(item, Paragraph)
        text = _inline(item)
        if not text:
            continue
        style = item.style.name if item.style is not None else ""
        if style in HEADING:
            blocks.append(f"{HEADING[style]} {text.replace('**', '')}")
        elif first:
            blocks.append(f"# {text.replace('**', '')}")
        else:
            fmt, level = _num_format(document, item)
            if fmt is None:
                blocks.append(text)
            else:
                marker = "-" if fmt in ("bullet", "none") else "1."
                blocks.append("  " * level + f"{marker} {text}")
        first = False
    if not blocks:
        raise SystemExit(f"{src.name}: no text extracted")
    if written_rows < source_rows:
        raise SystemExit(f"{src.name}: wrote {written_rows} table rows of {source_rows}")
    # consecutive list items stay together; everything else is a paragraph
    out = []
    for b in blocks:
        is_item = bool(re.match(r"\s*(-|1\.) ", b))
        if out and is_item and re.match(r"\s*(-|1\.) ", out[-1]):
            out[-1] += "\n" + b
        else:
            out.append(b)
    return "\n\n".join(out) + "\n", len(document.tables), written_rows


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    body, tables, rows = convert(src)
    header = (
        f"<!-- Mirror of \"{src.name}\" (converted by scripts/design_docs_to_md.py). "
        "The Word file is the master: do not edit here - re-run the script on the new file. -->\n\n"
    )
    dst.write_text(header + body, encoding="utf-8", newline="\n")
    print(f"{dst.name}: {len(body.splitlines())} lines, {tables} tables, {rows} table rows")


if __name__ == "__main__":
    main()
