"""Tests for stale cache / sessionStorage cleanup after report operations.

These tests verify:
1. The expense template checks the correct API field (``total_expenses``,
   not ``expenses``) when deciding whether to restore from sessionStorage.
2. Delete handlers in report_history and ending templates clear ALL
   BFCache-related sessionStorage keys, not just expense keys.
3. The ``get_draft_totals`` API response includes ``expenses_count`` so
   the front-end can detect saved expenses even when dollar total is 0.
4. The ``bfcache_helpers.js`` pageshow handler registers all expected
   restore keys.
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

class TestExpenseTemplateFieldName:
    """The pageshow handler in expense.html must check ``total_expenses``
    (or ``expenses_count``) from the API, never the non-existent ``expenses``."""

    def test_no_bare_data_dot_expenses_check(self):
        content = _read(TEMPLATES / "report" / "expense.html")
        bad_pattern = re.compile(r"data\s*\.\s*expenses\s*&&\s*data\s*\.\s*expenses\s*>")
        matches = bad_pattern.findall(content)
        assert not matches, (
            "expense.html still references data.expenses (should be "
            "data.total_expenses or data.expenses_count)"
        )

    def test_uses_total_expenses_field(self):
        content = _read(TEMPLATES / "report" / "expense.html")
        assert "data.total_expenses" in content, (
            "expense.html should check data.total_expenses from get_draft_totals API"
        )

    def test_uses_expenses_count_field(self):
        content = _read(TEMPLATES / "report" / "expense.html")
        assert "data.expenses_count" in content, (
            "expense.html should also check data.expenses_count for robustness"
        )


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
            r"fetch\(`/report/delete/.*?\.then\(response\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
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
            r"fetch\(`/report/delete/.*?\.then\(response\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
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
# 4. BFCache helpers register all expected keys for cleanup
# ---------------------------------------------------------------------------

class TestBFCacheHelpers:
    """The ``bfcache_helpers.js`` pageshow handler must attempt to restore
    (and subsequently clean up) all known snapshot keys."""

    EXPECTED_RESTORE_KEYS = {
        "pending_expenses",
        "pending_sales",
        "pending_opening",
        "pending_deposit",
        "pending_cash_count",
        "pending_ending",
    }

    def test_pageshow_registers_all_restore_keys(self):
        content = _read(STATIC_JS / "bfcache_helpers.js")
        found_keys: set[str] = set()
        for m in re.finditer(r"['\"]([a-z_]+)['\"]", content):
            candidate = m.group(1)
            if candidate.startswith("pending_"):
                found_keys.add(candidate)
        missing = self.EXPECTED_RESTORE_KEYS - found_keys
        assert not missing, (
            f"bfcache_helpers.js does not reference these restore keys: {missing}"
        )

    def test_cleanup_after_restore(self):
        """After restoring, BFCache must clear the snapshot from
        sessionStorage and history.state."""
        content = _read(STATIC_JS / "bfcache_helpers.js")
        assert "sessionStorage.removeItem" in content
        assert "mergeHistoryState" in content


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
            r"fetch\(`/report/delete/.*?\.then\(response\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
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
