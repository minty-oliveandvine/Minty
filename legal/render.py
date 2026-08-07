"""Render the legal Markdown subset to HTML.

Deliberately not a general Markdown library. The `.md` files under `terms/` and
`privacy/` are generated from the source `.docx` by a converter we control, so
they only ever contain four constructs:

    # Title            -> <h1>
    ## 1. Section      -> <h2>
    - bullet           -> <ul><li>
    **bold**           -> <strong>

Everything else is a paragraph.

The text is HTML-escaped BEFORE any markup is applied, so a legal document can
never inject HTML into the page — including a future revision written by
someone who has no reason to think about that. A general Markdown library would
pass raw HTML through by default, which is the wrong default for a document
whose whole purpose is to be quoted back verbatim in a dispute.
"""

from __future__ import annotations

import re
from html import escape

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """Escape, then apply the one inline construct we allow."""
    return _BOLD.sub(r"<strong>\1</strong>", escape(text))


def render_markdown(md: str) -> str:
    """Return HTML for the legal Markdown subset."""
    html: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line.startswith("## "):
            close_list()
            html.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            close_list()
            html.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(line[2:])}</li>")
        else:
            close_list()
            html.append(f"<p>{_inline(line)}</p>")

    close_list()
    return "\n".join(html)
