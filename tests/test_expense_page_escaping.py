"""The Expenses page (templates/report/expense.html) builds parts of its markup as JavaScript template
literals - the Suppliers and Account Code dropdowns, "+ Add '<q>' as a new contact", Expense Details,
the report-edit selects. Supplier and account names come from the company's Xero, the description
and the search text from whoever types them: interpolated raw, a contact named
``<img src=x onerror=...>`` ran script for every cashier who opened the page (stored XSS, fixed
2026-10-15).

The pytest suite runs none of the page's JavaScript, so this pins the rule on the source: every
``${...}`` inside a template literal that builds HTML is ``escapeHtml(...)`` or one of the values
listed below, each safe for the reason given. A new interpolation fails here until it is escaped or
argued onto the list.
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "report" / "expense.html"

#: Interpolations that are not text from a person or from Xero.
SAFE = {
    # markup this page built itself, from escaped parts
    "accountOptions", "contactOptions", "deleteBtnHtml", "remarksHtml",
    "detailRow('Contact Name', contactName)", "detailRow('Description', descriptionText)",
    # numbers, and the amount written from one
    "amountText", "formattedAmount", "index", "thumbIndex",
    "expense.amount.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})",
    # a server id (uuid), a fixed attribute, a class list
    "expense.id", "sel", "fileGridCols",
    # the company's currency code, from the server's own catalogue
    "window.CURRENCY_SYMBOL",
    # /preview/<key>: the key is minted by the server as expenses/<uuid>/<[A-Z0-9_]+>.<ext>
    "fileUrl",
}

_LITERAL = re.compile(r"`([^`]*)`", re.S)
_INTERPOLATION = re.compile(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}")


def _html_interpolations(source: str) -> list[str]:
    found = []
    for literal in _LITERAL.finditer(source):
        body = literal.group(1)
        if "<" not in body:  # not markup
            continue
        found.extend(e.strip() for e in _INTERPOLATION.findall(body))
    return found


def test_every_name_or_typed_text_in_built_markup_is_escaped():
    source = TEMPLATE.read_text(encoding="utf-8")

    raw = sorted({e for e in _html_interpolations(source) if not e.startswith("escapeHtml(") and e not in SAFE})

    assert raw == [], f"escape these with escapeHtml(...) or argue them onto SAFE: {raw}"


def test_the_names_that_were_raw_are_escaped():
    source = TEMPLATE.read_text(encoding="utf-8")

    for expected in ("${escapeHtml(contact.Name)}", "${escapeHtml(addNewContactQuery)}", "${escapeHtml(query)}",
                     "${escapeHtml(account.Name)}", "${escapeHtml(account.Code)}", "${escapeHtml(value)}",
                     "${escapeHtml(c.Name)}", "${escapeHtml(a.Name)}", "${escapeHtml(fileName)}"):
        assert expected in source, expected


def test_escape_html_covers_the_five_characters():
    source = TEMPLATE.read_text(encoding="utf-8")
    body = source[source.index("function escapeHtml(value)"):]
    body = body[: body.index("}[ch]));") + len("}[ch]));")]

    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#39;")):
        assert f"'{char}': '{entity}'" in body or f"\"{char}\": '{entity}'" in body, char
    assert "/[&<>\"']/g" in body
