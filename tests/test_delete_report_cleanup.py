"""Tests for report deletion cleanup and stale expense prevention.

Verifies the three fixes:
1. no stale expenses come back: the Expenses stage keeps no browser copy (was: the snapshot
   carried draft_id and the restore checked it - the copy is gone since the Part 15 redesign).
2. delete_report cleans up ReportSaleDetail before the report row.
3. delete_report cleans up sibling drafts for the same (entity, date).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Expense template sessionStorage snapshot includes draft_id
# ---------------------------------------------------------------------------

class TestExpenseStageKeepsNoBrowserCopy:
    """The redesigned Expenses stage (Part 15.15c) saves each entry the moment it is added, edited
    or deleted, and draws the list from the server. So there is no pending-expense snapshot to
    restore - and so nothing stale from another day's draft can come back: a page restored from
    the back/forward cache reloads instead (static/js/pc_closing.js). Replaces the old snapshot
    checks (draft_id in the snapshot, the restore guards), which guarded a copy that is gone."""

    def _sources(self) -> str:
        return _read(TEMPLATES / "report" / "expense.html") + _read(ROOT / "static" / "js" / "pc_expenses.js")

    def test_no_snapshot_of_expenses_is_written_or_restored(self):
        content = self._sources()
        for gone in ("pending_expenses", "refresh_expense_on_back", "pendingExpenses", "history.replaceState"):
            assert gone not in content, gone

    def test_a_restored_page_reloads_from_the_server(self):
        closing = _read(ROOT / "static" / "js" / "pc_closing.js")
        assert re.search(r"event\.persisted\)\s*window\.location\.reload\(\)", closing)
        assert "pc_closing.js" in _read(TEMPLATES / "petty_cash" / "closing_base.html")
        assert "{% extends 'petty_cash/closing_base.html' %}" in _read(TEMPLATES / "report" / "expense.html")

    def test_every_save_reloads_the_list_from_the_server(self):
        script = _read(ROOT / "static" / "js" / "pc_expenses.js")
        assert script.count("reloadWith(") >= 4  # add, edit, report edit, delete


# ---------------------------------------------------------------------------
# 2. delete_report cleans up dependent records
# ---------------------------------------------------------------------------

SERVICE = ROOT / "blueprints" / "report" / "services" / "report_actions.py"


def _service_delete_source() -> str:
    """``delete_report`` in services/report_actions.py - the delete the Jinja route and the Petty
    Cash API share since 2026-10-15 (behaviour: tests/test_report_actions_state.py)."""
    full_source = SERVICE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(full_source)):
        if isinstance(node, ast.FunctionDef) and node.name == "delete_report":
            return ast.get_source_segment(full_source, node)
    raise AssertionError("delete_report not found in services/report_actions.py")


class TestDeleteReportCleansUpChildren:
    """The delete removes a report's child rows before the report row itself (and the Xero publish
    record with it - the schema's FKs cascade; deleted explicitly so SQLite behaves like Postgres)."""

    def test_sale_rows_go_before_the_report(self):
        source = _service_delete_source()
        sale_pos = source.find("ReportSaleDetail.query.filter_by(report_id=report_id).delete()")
        report_pos = source.find("db.session.delete(report)")
        assert sale_pos != -1, "the report's sale rows must be deleted"
        assert sale_pos < report_pos, "the sale rows must go before the report row"

    def test_the_xero_publish_record_goes_with_the_report(self):
        source = _service_delete_source()
        for model in ("XeroReportSync", "XeroBankTransfer", "XeroBankTransaction"):
            assert f"{model}.query.filter_by(" in source, f"{model} rows must be deleted with the report"

    def test_receipt_files_leave_storage_only_after_the_commit(self):
        """A failed delete must leave the report AND its files (they used to go first)."""
        source = _service_delete_source()
        assert source.find("db.session.commit()") < source.find("delete_files_from_s3(files)")

    def test_a_failure_rolls_back(self):
        assert "db.session.rollback()" in _service_delete_source()


class TestOneReportPerCompanyAndDay:
    """The old route also swept "sibling drafts" of the same company and day. It could never find
    any - a draft and its report are one row, and the table holds one row per company and day - so
    the sweep went with the extraction (2026-10-15). This pins the constraint that makes it
    unnecessary."""

    def test_the_report_table_is_unique_per_company_and_day(self):
        source = (ROOT / "blueprints" / "report" / "models" / "report.py").read_text(encoding="utf-8")
        assert re.search(r"UniqueConstraint\(\s*[\"']entity_id[\"']\s*,\s*[\"']transaction_date[\"']", source)


# ---------------------------------------------------------------------------
# 4. Integration: sessionStorage cleanup keys still present after changes
# ---------------------------------------------------------------------------

class TestSessionStorageCleanupStillWorks:
    """Verify the report_history.html delete handler still clears all
    expected sessionStorage keys (regression check)."""

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

    def test_report_history_delete_still_clears_all_keys(self):
        content = _read(TEMPLATES / "report_history" / "report_history.html")
        delete_match = re.search(
            r"fetch\(`/report/delete/.*?\.then\(\(\)\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
            content,
            re.DOTALL,
        )
        assert delete_match, "Could not find delete handler in report_history.html"
        section = delete_match.group(1)
        found_keys: set[str] = set()
        for m in re.finditer(r"sessionStorage\.removeItem\(['\"]([^'\"]+)['\"]\)", section):
            found_keys.add(m.group(1))
        for m in re.finditer(r"['\"]([a-z_]+)['\"]", section):
            candidate = m.group(1)
            if candidate.startswith("bf_pending_") or candidate in (
                "pending_expenses", "refresh_expense_on_back",
            ):
                found_keys.add(candidate)
        missing = self.ALL_BF_CACHE_KEYS - found_keys
        assert not missing, (
            f"report_history.html delete handler missing cleanup for: {missing}"
        )
