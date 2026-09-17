"""No template or static script may name a column a finished phase C unit removed.

The route tests render Jinja and the browser suite (e2e/) runs the wizard's JavaScript, but
neither reads every template. This is the cheap backstop: once a unit has landed, the words it
retired may not appear under templates/ or static/js/ at all. The list grows per unit -
add the unit's retired names when its gate is green (docs/modernisation_plan.md, Part 1 C0.9).

Deliberately word-boundary matches on identifiers, so ``cash_sales`` does not trip on
``totalCashSales`` and ``date`` is not on the list at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# unit -> the identifiers it retires. Empty until C1 lands; every entry here is enforced.
RETIRED: dict[str, tuple[str, ...]] = {
    "C1": ("xero_entity_id", "access_token", "refresh_token", "id_token", "expires_in",
           "token_created_at", "current_entity_id", "xero_token"),
    "C2": ("minimum_qty", "deposit_frequency", "deposit_day", "xero_short_code",
           "period_lock_date", "end_of_year_lock_date"),
    # C3 retires the per-company copies of the catalogue's columns and the old type words.
    # ``value_name`` itself STAYS (it is the form-field convention, now on sale_info).
    "C3": ("sale_info_id", "legacy_column", "create_date"),
    # C4 retires what the report no longer has. ``cash_sales`` / ``expenses`` / ``uploaded_by`` /
    # ``xero_integrated_yes`` / ``withdrawal_type`` STAY as model synonyms (and ``cash_sales``
    # is the form-field convention); ``shop_sales`` / ``delivery_sales`` / ``actual_cash_total``
    # stay as derived hybrids. ``partially_published`` went with the enum (``posted`` is an
    # English word in comments, so it is checked by hand). ``item_code`` is still posted by
    # expense.html's form and dropped by the model - the JS field is C4 leftover, not a column.
    "C4": ("receipt_files", "withdrawal_bank_account", "shop_expense", "report_sale_detail",
           "report_draft", "partially_published"),
    "C5": ("sync_statuc", "xero_reponse_text", "create_at"),
    # "C6": ("role_permissions", "invitations"),
}

SCAN = [ROOT / "templates", ROOT / "static" / "js"]
SUFFIXES = {".html", ".js", ".jinja", ".jinja2"}


def _files():
    for base in SCAN:
        if base.exists():
            yield from (p for p in base.rglob("*") if p.suffix in SUFFIXES)


@pytest.mark.parametrize("unit", sorted(RETIRED) or ["(no unit finished yet)"])
def test_retired_column_names_are_gone_from_templates_and_scripts(unit):
    words = RETIRED.get(unit, ())
    if not words:
        pytest.skip("no phase C unit has retired any names yet")
    pattern = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, words)) + r")(?![A-Za-z0-9_])")
    hits: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    assert not hits, f"{unit} retired {words} but they are still referenced:\n" + "\n".join(hits[:40])
