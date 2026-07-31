"""Tests for report deletion cleanup and stale expense prevention.

Verifies the three fixes:
1. sessionStorage snapshot includes draft_id and restore logic validates it.
2. delete_report cleans up ReportV2, ReportExpenseDetail, ReportSaleDetail.
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

class TestExpenseSnapshotIncludesDraftId:
    """The expense page must store draft_id in the sessionStorage/history.state
    snapshot and validate it before restoring cached expenses."""

    def _get_expense_html(self) -> str:
        return _read(TEMPLATES / "report" / "expense.html")

    def test_snapshot_contains_draft_id_field(self):
        """Both snapshot creation sites must include draft_id in the object."""
        content = self._get_expense_html()
        snapshot_pattern = re.compile(
            r"const\s+snapshot\s*=\s*\{[^}]*draft_id\s*:", re.DOTALL
        )
        matches = snapshot_pattern.findall(content)
        assert len(matches) >= 2, (
            f"Expected at least 2 snapshot definitions with draft_id, found {len(matches)}. "
            "Both submitAllExpenses() and the form-submit path must include draft_id."
        )

    def test_snapshot_reads_draft_id_from_template(self):
        """The draft_id value must come from the Jinja2 template variable."""
        content = self._get_expense_html()
        assert "draft_id or" in content or 'draft_id' in content, (
            "Snapshot must read draft_id from Jinja2 template context"
        )
        assert re.search(r"draftIdValue\s*=\s*'", content), (
            "Expected draftIdValue variable to be set from Jinja2 {{ draft_id }}"
        )

    def test_restore_validates_draft_id_from_history_state(self):
        """The pageshow handler must check draft_id when restoring from history.state."""
        content = self._get_expense_html()
        assert re.search(
            r"hs\.draft_id\s*===\s*currentDraftId", content
        ), (
            "Restore from history.state must validate hs.draft_id === currentDraftId"
        )

    def test_restore_validates_draft_id_from_session_storage(self):
        """The pageshow handler must check draft_id when restoring from sessionStorage."""
        content = self._get_expense_html()
        assert re.search(
            r"parsed\.draft_id\s*===\s*currentDraftId", content
        ), (
            "Restore from sessionStorage must validate parsed.draft_id === currentDraftId"
        )

    def test_stale_cleanup_checks_draft_id_mismatch(self):
        """The normal-page-load cleanup must detect draft_id mismatch and clear stale data."""
        content = self._get_expense_html()
        assert "draftMismatch" in content, (
            "Stale snapshot cleanup must check for draft_id mismatch"
        )

    def test_current_draft_id_declared_in_restore_block(self):
        """The pageshow restore block must declare currentDraftId from the template."""
        content = self._get_expense_html()
        assert re.search(r"const\s+currentDraftId\s*=", content), (
            "Restore block must declare currentDraftId for validation"
        )


# ---------------------------------------------------------------------------
# 2. delete_report cleans up ReportV2 and dependent records
# ---------------------------------------------------------------------------

class TestDeleteReportCleansUpReportV2:
    """The delete_report function must delete ReportV2, ReportExpenseDetail,
    ReportSaleDetail, XeroReportSync, and XeroBankTransfer records."""

    def _get_delete_report_source(self) -> str:
        path = ROOT / "blueprints" / "report" / "routes" / "report_detail.py"
        return path.read_text(encoding="utf-8")

    def _get_delete_function_node(self) -> ast.FunctionDef:
        path = ROOT / "blueprints" / "report" / "routes" / "report_detail.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "delete_report":
                return node
        raise AssertionError("delete_report function not found in report_detail.py")

    def test_imports_report_v2_model(self):
        source = self._get_delete_report_source()
        assert "ReportV2" in source, "report_detail.py must import ReportV2"

    def test_imports_report_expense_detail_model(self):
        source = self._get_delete_report_source()
        assert "ReportExpenseDetail" in source, (
            "report_detail.py must import ReportExpenseDetail"
        )

    def test_imports_report_sale_detail_model(self):
        source = self._get_delete_report_source()
        assert "ReportSaleDetail" in source, (
            "report_detail.py must import ReportSaleDetail"
        )

    def test_cascade_helper_exists(self):
        """A helper function must exist to delete ReportV2 and its FK dependents."""
        source = self._get_delete_report_source()
        assert "_delete_report_v2_cascade" in source, (
            "delete_report must define or call _delete_report_v2_cascade helper"
        )

    def test_cascade_deletes_report_expense_detail(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"ReportExpenseDetail\.query\.filter_by\(.*report_id.*\)\.delete\(\)", source
        ), "Cascade must delete ReportExpenseDetail records"

    def test_cascade_deletes_report_sale_detail(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"ReportSaleDetail\.query\.filter_by\(.*report_id.*\)\.delete\(\)", source
        ), "Cascade must delete ReportSaleDetail records"

    def test_cascade_deletes_xero_report_sync(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"XeroReportSync\.query\.filter_by\(.*report_id.*\)\.delete\(\)", source
        ), "Cascade must delete XeroReportSync records"

    def test_cascade_deletes_xero_bank_transfer(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"XeroBankTransfer\.query\.filter_by\(.*sync_report_id.*\)\.delete\(\)", source
        ), "Cascade must delete XeroBankTransfer records"

    def test_cascade_deletes_report_v2(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"ReportV2\.query\.filter_by\(.*report_id.*\)\.delete\(\)", source
        ), "Cascade must delete ReportV2 record"

    def test_cascade_called_for_draft_only_delete(self):
        """When deleting a draft-only report, the cascade must be invoked."""
        fn = self._get_delete_function_node()
        source = ast.get_source_segment(
            (ROOT / "blueprints" / "report" / "routes" / "report_detail.py")
            .read_text(encoding="utf-8"),
            fn,
        )
        # The cascade must be called in the draft-only branch (before the
        # `entity_id = report.company` line that starts the submitted-report branch)
        draft_branch = source.split("entity_id = report.company")[0]
        assert "_delete_report_v2_cascade" in draft_branch, (
            "Draft-only delete path must call _delete_report_v2_cascade"
        )

    def test_cascade_called_for_submitted_report_delete(self):
        """When deleting a submitted report, the cascade must be invoked."""
        fn = self._get_delete_function_node()
        source = ast.get_source_segment(
            (ROOT / "blueprints" / "report" / "routes" / "report_detail.py")
            .read_text(encoding="utf-8"),
            fn,
        )
        submitted_branch = source.split("entity_id = report.company")[1]
        assert "_delete_report_v2_cascade" in submitted_branch, (
            "Submitted report delete path must call _delete_report_v2_cascade"
        )

    def test_report_v2_deleted_before_report(self):
        """ReportV2 must be deleted before the Report itself to avoid FK issues."""
        source = self._get_delete_report_source()
        cascade_pos = source.find("_delete_report_v2_cascade(report.id)")
        delete_report_pos = source.find("db.session.delete(report)")
        assert cascade_pos != -1, "Must call _delete_report_v2_cascade(report.id)"
        assert cascade_pos < delete_report_pos, (
            "_delete_report_v2_cascade must be called before db.session.delete(report)"
        )


# ---------------------------------------------------------------------------
# 3. delete_report cleans up sibling drafts for same (entity, date)
# ---------------------------------------------------------------------------

class TestDeleteReportCleansSiblingDrafts:
    """When deleting a draft-only report, any other drafts for the same
    (entity, transaction_date) must also be deleted to prevent stale data
    from being picked up when creating a new report."""

    def _get_delete_function_source(self) -> str:
        path = ROOT / "blueprints" / "report" / "routes" / "report_detail.py"
        full_source = path.read_text(encoding="utf-8")
        tree = ast.parse(full_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "delete_report":
                return ast.get_source_segment(full_source, node)
        raise AssertionError("delete_report function not found")

    def test_draft_delete_queries_other_drafts(self):
        """Draft-only delete path must query for other_drafts with same (company, date)."""
        source = self._get_delete_function_source()
        # The draft-only branch is before the first "entity_id = report.company"
        # inside delete_report
        draft_branch = source.split("entity_id = report.company")[0]
        assert "other_drafts" in draft_branch, (
            "Draft-only delete must query for other drafts with same (company, date)"
        )

    def test_draft_delete_excludes_self_from_other_drafts(self):
        """The other_drafts query must exclude the draft being deleted (id != id)."""
        source = self._get_delete_function_source()
        draft_branch = source.split("entity_id = report.company")[0]
        assert "ReportDraft.id != report_draft.id" in draft_branch, (
            "other_drafts query must filter out the draft being deleted"
        )

    def test_submitted_delete_excludes_self_from_other_drafts(self):
        """The other_drafts query for submitted reports must not re-process the main draft."""
        source = self._get_delete_function_source()
        submitted_branch = source.split("entity_id = report.company")[1]
        assert "ReportDraft.id != report.id" in submitted_branch, (
            "Submitted report other_drafts query must exclude the report's own draft"
        )

    def test_other_drafts_expenses_are_deleted(self):
        """Sibling drafts' expense rows must be deleted."""
        source = self._get_delete_function_source()
        # Step 3 pointed expense writes at shop_expense; ShopExpenseDraft is
        # no longer written or deleted. Same assertion, new table.
        assert source.count("ShopExpense.query.filter_by(report_id=draft.id).delete()") >= 2, (
            "ShopExpense must be deleted for each sibling draft in both paths"
        )

    def test_exception_handler_rolls_back(self):
        """The exception handler must call db.session.rollback()."""
        source = self._get_delete_function_source()
        # Find the except block within the delete_report function
        assert "db.session.rollback()" in source, (
            "delete_report exception handler must call db.session.rollback()"
        )


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
            r"fetch\(`/report/delete/.*?\.then\(response\s*=>\s*\{(.*?)\}\s*\)\s*\.catch",
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
