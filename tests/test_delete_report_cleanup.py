"""Tests for report deletion cleanup.

Verifies:
1. delete_report cleans up ReportSaleDetail before the report row.
2. delete_report cleans up sibling drafts for the same (entity, date).

(The Jinja Expenses page and its browser-copy checks went with Flask's HTML, 2026-10-20.)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 2. delete_report cleans up dependent records
# ---------------------------------------------------------------------------

SERVICE = ROOT / "blueprints" / "report" / "services" / "report_actions.py"


def _service_delete_source() -> str:
    """``delete_report`` in services/report_actions.py - the delete behind the Petty Cash API
    since 2026-10-15 (behaviour: tests/test_report_actions_state.py)."""
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

