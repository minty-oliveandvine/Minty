"""Tests for stale cache / sessionStorage cleanup after report operations.

These tests verify:
1. The expense template checks the correct API field (``total_expenses``,
   not ``expenses``) when deciding whether to restore from sessionStorage.
2. Delete handlers in report_history and ending templates clear ALL
   BFCache-related sessionStorage keys, not just expense keys.
3. The ``get_draft_totals`` API response includes ``expenses_count`` so
   the front-end can detect saved expenses even when dollar total is 0.
4. (``bfcache_helpers.js`` and its restore checks went with the Part 15 redesign: no page
   writes a snapshot any more, and a restored stage reloads - static/js/pc_closing.js.)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEMPLATES = ROOT / "templates"
STATIC_JS = ROOT / "static" / "js"

ALL_BF_CACHE_KEYS = {
    "pending_expenses",
    "refresh_expense_on_back",
    "bf_pending_expenses",
    "bf_pending_sales",
    "bf_pending_deposit",
    "bf_pending_opening",
    "bf_pending_cash_count",
    "bf_pending_ending",
    "bf_pending_generic",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Expense template uses correct API field name
# ---------------------------------------------------------------------------

class TestExpenseStageReadsNoDraftTotals:
    """The old expense page re-read ``/api/get_draft_totals`` on a back navigation and checked the
    wrong field (``data.expenses``). The redesigned stage draws its list and total from the server
    on every load and reloads a restored page, so it asks that endpoint nothing."""

    def test_no_draft_totals_poll(self):
        for path in (TEMPLATES / "report" / "expense.html", ROOT / "static" / "js" / "pc_expenses.js"):
            content = _read(path)
            assert "get_draft_totals" not in content, path.name
            assert not re.search(r"data\s*\.\s*expenses\s*&&", content), path.name


# ---------------------------------------------------------------------------
# 2. Delete handlers clear ALL BFCache keys
# ---------------------------------------------------------------------------

class TestDeleteHandlersClearAllKeys:
    """Both report_history.html and ending.html must clear all BFCache
    sessionStorage keys when a report is deleted."""

    def _extract_removed_keys(self, content: str) -> set[str]:
        """Extract all sessionStorage key names removed after a successful delete."""
        keys: set[str] = set()
        for m in re.finditer(r"sessionStorage\.removeItem\(['\"]([^'\"]+)['\"]\)", content):
            keys.add(m.group(1))
        for m in re.finditer(r"['\"]([a-z_]+)['\"]", content):
            candidate = m.group(1)
            if candidate.startswith("bf_pending_") or candidate in (
                "pending_expenses", "refresh_expense_on_back",
            ):
                keys.add(candidate)
        return keys

    def test_report_history_clears_all_bf_keys(self):
        content = _read(TEMPLATES / "report_history" / "report_history.html")
        delete_section_match = re.search(
            r"fetch\(`/report/delete/.*?\.then\(\(\)\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
            content,
            re.DOTALL,
        )
        assert delete_section_match, "Could not find delete fetch handler in report_history.html"
        delete_section = delete_section_match.group(1)
        removed = self._extract_removed_keys(delete_section)
        missing = ALL_BF_CACHE_KEYS - removed
        assert not missing, (
            f"report_history.html delete handler does not clear: {missing}"
        )

    def test_ending_clears_all_bf_keys(self):
        content = _read(TEMPLATES / "report" / "ending.html")
        delete_section_match = re.search(
            r"fetch\(`/report/delete/.*?\.then\(\(\)\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
            content,
            re.DOTALL,
        )
        assert delete_section_match, "Could not find delete fetch handler in ending.html"
        delete_section = delete_section_match.group(1)
        removed = self._extract_removed_keys(delete_section)
        missing = ALL_BF_CACHE_KEYS - removed
        assert not missing, (
            f"ending.html delete handler does not clear: {missing}"
        )


# ---------------------------------------------------------------------------
# 3. get_draft_totals API returns expenses_count
# ---------------------------------------------------------------------------

class TestGetDraftTotalsAPI:
    """The ``get_draft_totals`` route must return ``expenses_count`` alongside
    ``total_expenses`` so the front-end can distinguish 0-total from no-data."""

    def _get_function(self, name: str) -> ast.FunctionDef:
        path = ROOT / "blueprints" / "report" / "routes" / "api.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"Function `{name}` not found in api.py")

    def _find_jsonify_keys(self, func_node: ast.FunctionDef) -> set[str]:
        """Return all string-literal keys passed to ``jsonify({...})``."""
        keys: set[str] = set()
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id == "jsonify":
                pass
            elif isinstance(callee, ast.Attribute) and callee.attr == "jsonify":
                pass
            else:
                continue
            for kw in node.keywords:
                if kw.arg:
                    keys.add(kw.arg)
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    for k in arg.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
        return keys

    def test_expenses_count_in_response(self):
        fn = self._get_function("get_draft_totals")
        keys = self._find_jsonify_keys(fn)
        assert "expenses_count" in keys, (
            "get_draft_totals must return expenses_count in its JSON response"
        )

    def test_total_expenses_in_response(self):
        fn = self._get_function("get_draft_totals")
        keys = self._find_jsonify_keys(fn)
        assert "total_expenses" in keys, (
            "get_draft_totals must return total_expenses in its JSON response"
        )


# ---------------------------------------------------------------------------
# 5. Delete handlers also clear history.state for all pending keys
# ---------------------------------------------------------------------------

class TestDeleteClearsHistoryState:
    """Delete handlers must nullify all ``pending_*`` keys in
    ``history.state`` (not just ``pendingExpenses``)."""

    PENDING_KEYS_IN_STATE = {
        "pendingExpenses",
        "pending_expenses",
        "pending_sales",
        "pending_deposit",
        "pending_opening",
        "pending_cash_count",
        "pending_ending",
    }

    def _check_template_clears_state_keys(self, path: Path):
        content = _read(path)
        delete_section_match = re.search(
            r"fetch\(`/report/delete/.*?\.then\(\(\)\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
            content,
            re.DOTALL,
        )
        assert delete_section_match, f"Could not find delete handler in {path.name}"
        section = delete_section_match.group(1)

        for key in self.PENDING_KEYS_IN_STATE:
            assert key in section, (
                f"{path.name} delete handler does not clear history.state key: {key}"
            )

    def test_report_history_clears_history_state(self):
        self._check_template_clears_state_keys(
            TEMPLATES / "report_history" / "report_history.html"
        )

    def test_ending_clears_history_state(self):
        self._check_template_clears_state_keys(
            TEMPLATES / "report" / "ending.html"
        )
