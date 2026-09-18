"""Tests for report deletion cleanup and stale expense prevention.

Verifies the three fixes:
1. sessionStorage snapshot includes draft_id and restore logic validates it.
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
# 2. delete_report cleans up dependent records
# ---------------------------------------------------------------------------

class TestDeleteReportCleansUpChildren:
    """The delete_report function must delete ReportSaleDetail before the
    report row it hangs off.

    The list has shrunk twice, each time because the code it described was
    deliberately removed rather than the assertion weakened:

    * Step 3.5 — ReportExpenseDetail: nothing writes that table any more (it
      duplicated shop_expense), so there is nothing to clean up.
    * Step 4a-2 — ReportV2: no writers since r2a02, and the table is dropped
      in r10a10. There is no successor, so these assertions are gone, not
      re-pointed.
    * Step 4a-2 — XeroReportSync / XeroBankTransfer: their deletes were
      removed ON PURPOSE. They are the Xero publish audit trail, and r9a09
      flips their FKs to ON DELETE SET NULL so the trail survives a report
      deletion. Asserting the app still deletes them would lock in the very
      behaviour that migration removes.
    """

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

    def test_imports_report_sale_detail_model(self):
        source = self._get_delete_report_source()
        assert "ReportSaleDetail" in source, (
            "report_detail.py must import ReportSaleDetail"
        )

    def test_cascade_helper_exists(self):
        """A helper must exist to delete a report's children before the report."""
        source = self._get_delete_report_source()
        assert "_delete_report_children" in source, (
            "delete_report must define or call _delete_report_children helper"
        )

    def test_cascade_deletes_report_sale_detail(self):
        source = self._get_delete_report_source()
        assert re.search(
            r"ReportSaleDetail\.query\.filter_by\(.*report_id.*\)\.delete\(\)", source
        ), "Cascade must delete ReportSaleDetail records"

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
        assert "_delete_report_children" in draft_branch, (
            "Draft-only delete path must call _delete_report_children"
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
        assert "_delete_report_children" in submitted_branch, (
            "Submitted report delete path must call _delete_report_children"
        )

    def test_children_deleted_before_report(self):
        """Child rows must be deleted before the Report itself to avoid FK issues."""
        source = self._get_delete_report_source()
        cascade_pos = source.find("_delete_report_children(report.id)")
        delete_report_pos = source.find("db.session.delete(report)")
        assert cascade_pos != -1, "Must call _delete_report_children(report.id)"
        assert cascade_pos < delete_report_pos, (
            "_delete_report_children must be called before db.session.delete(report)"
        )


# ---------------------------------------------------------------------------
# 3. delete_report cleans up sibling drafts for same (entity, date)
# ---------------------------------------------------------------------------

class TestDeleteReportCleansSiblingDrafts:
    """When deleting a report, any other DRAFT rows for the same
    (entity, transaction_date) must also be deleted, so stale data is not
    picked up when creating a new report.

    Step 4a-6 collapsed the two delete branches into one. There used to be a
    draft-only path (no Report row, fall back to ReportDraft) and a submitted
    path; since Stage 4a every draft has a `report` row with the same id, and
    with report_draft dropped the fallback is unreachable. So these assertions
    now target a single branch instead of two, and name `Report` rather than
    `ReportDraft`.

    The status filter is the part that matters most: it used to be implied by
    the table, and is now the only thing keeping this from deleting SUBMITTED
    reports that share an entity and date.
    """

    def _get_delete_function_source(self) -> str:
        path = ROOT / "blueprints" / "report" / "routes" / "report_detail.py"
        full_source = path.read_text(encoding="utf-8")
        tree = ast.parse(full_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "delete_report":
                return ast.get_source_segment(full_source, node)
        raise AssertionError("delete_report function not found")

    def test_delete_queries_other_drafts(self):
        """delete_report must query siblings with the same (company, date)."""
        source = self._get_delete_function_source()
        assert "other_drafts" in source, (
            "delete_report must query for sibling rows with same (company, date)"
        )

    def test_other_drafts_excludes_self(self):
        """The sibling query must exclude the row being deleted."""
        source = self._get_delete_function_source()
        assert "Report.id != report.id" in source, (
            "sibling query must filter out the report being deleted"
        )

    def test_other_drafts_is_scoped_to_drafts(self):
        """The sibling query MUST be status-scoped.

        Without this it deletes submitted reports for the same entity and
        date — the table no longer implies "draft".
        """
        source = self._get_delete_function_source()
        assert 'Report.status == "draft"' in source, (
            "sibling query must filter status == 'draft' or it will delete "
            "submitted reports sharing an entity and transaction_date"
        )

    def test_other_drafts_expenses_are_deleted(self):
        """Sibling rows' expense records must be deleted."""
        source = self._get_delete_function_source()
        # C4: the lines go through the receipts-aware helper, so their attachments
        # leave S3 with them (F2).
        assert "_delete_expenses_with_receipts(draft.id)" in source, (
            "the expense lines (and their receipts) must be deleted for each sibling draft"
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
