"""The Expenses page puts supplier and account names (from the company's Xero), the description, file
names and the search text on screen. Built as markup with those values interpolated raw, a contact
named ``<img src=x onerror=...>`` ran script for every cashier who opened the page (stored XSS,
fixed 2026-10-15).

Since the Parts 13-15 redesign the page's script is ``static/js/pc_expenses.js``, and it builds every
node with ``createElement`` + ``textContent`` - no HTML string ever carries a name. The pytest suite
runs none of the page's JavaScript, so this pins the rule on the source: the script has no HTML sink,
and no template literal that builds markup, in the script or in ``templates/report/expense.html``,
interpolates anything.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "report" / "expense.html"
SCRIPT = ROOT / "static" / "js" / "pc_expenses.js"

_LITERAL = re.compile(r"`([^`]*)`", re.S)
_INTERPOLATION = re.compile(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}")
_HTML_SINK = re.compile(r"\.innerHTML\s*[+]?=|\.outerHTML\s*[+]?=|insertAdjacentHTML\(|document\.write\(")


def _html_interpolations(source: str) -> list[str]:
    found = []
    for literal in _LITERAL.finditer(source):
        body = literal.group(1)
        if "<" not in body:  # not markup
            continue
        found.extend(e.strip() for e in _INTERPOLATION.findall(body))
    return found


def test_the_page_script_builds_nodes_never_html_strings():
    source = SCRIPT.read_text(encoding="utf-8")

    assert _HTML_SINK.findall(source) == [], "build nodes with el()/textContent, never an HTML string"
    assert "node.textContent = text" in source  # el(), the one way the script puts text on screen


def test_no_markup_literal_interpolates_a_value():
    for path in (TEMPLATE, SCRIPT):
        raw = _html_interpolations(path.read_text(encoding="utf-8"))

        assert raw == [], f"{path.name}: build these with el()/textContent instead: {raw}"


def test_names_reach_the_script_as_json_never_as_markup():
    source = TEMPLATE.read_text(encoding="utf-8")

    for expected in ("contacts: {{ ((xero_contacts or {}).get('Contacts') or [])|tojson }}",
                     "accounts: {{ (xero_accounts or [])|tojson }}"):
        assert expected in source, expected
