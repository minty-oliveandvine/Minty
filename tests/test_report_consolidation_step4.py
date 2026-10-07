"""Step 4 invariants — the ones that fail silently if they regress.

The report consolidation collapsed report_draft / shop_expense_draft /
report_cashcount_draft / report_detail / report_expense_detail / report_v2 /
report_history_draft into `report` and `shop_expense`. Two classes of bug
survived that collapse and neither raises:

  1. A lookup that used to be scoped by the TABLE it queried is now unscoped,
     because `report` holds drafts and submitted reports alike. The runbook
     records six production incidents of exactly this shape.
  2. A predicate that is right at one point in the lifecycle applied where the
     opposite meaning holds — three of those six were caused by *fixes*.

These tests pin the specific decisions that were made, so a later edit that
quietly reverses one is caught here rather than in production.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _fake_db_returning(scalar_value):
    """Minimal stand-in for `db` whose session.get(Report, id) answers with a report
    whose ``actual_cash_total`` is ``scalar_value``.

    legacy_column_counts_for_report reads report.actual_cash_total (a derived figure
    since C4: None when never counted, 0.0 for an all-zero count); that one value is the
    whole dependency, so faking it keeps the test on the logic under test.
    """
    report = SimpleNamespace(actual_cash_total=scalar_value)
    return SimpleNamespace(session=SimpleNamespace(get=lambda *_a, **_k: report))


# ---------------------------------------------------------------------------
# 1. The cross-tenant lookup in the Xero publish path
#
# publish.py used to resolve a report from `transaction_date` ALONE, with no
# company filter, so it could return a DIFFERENT ENTITY'S report and attach
# this entity's receipt to it. The runbook flagged it as needing "its own fix
# and a test"; Step 4a-3 rewrote those lines, so the fix landed there.
# ---------------------------------------------------------------------------

class TestPublishReportLookupIsTenantScoped:

    def _create_bank_transaction_source(self) -> str:
        src = _source("blueprints/xero/services/publish.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_bank_transaction":
                return ast.get_source_segment(src, node) or ""
        raise AssertionError("create_bank_transaction not found in publish.py")

    def test_report_lookup_filters_by_company(self):
        """The (entity, date) lookup must constrain on company.

        Without it the query matches on date alone and can return another
        tenant's report — a cross-tenant data leak.
        """
        source = self._create_bank_transaction_source()
        assert re.search(r"Report\.company\s*==\s*entity_id", source), (
            "the report lookup in create_bank_transaction must filter "
            "Report.company == entity_id, or it can resolve another tenant's "
            "report from transaction_date alone"
        )

    def test_report_lookup_has_no_status_filter(self):
        """It must NOT filter on status.

        Publishing runs AFTER submit, so the row is status='posted'. Adding a
        "draft" predicate here returned None and broke every Xero publish once
        already — the runbook's headline lifecycle lesson.
        """
        source = self._create_bank_transaction_source()
        window = source[source.find("Report.company == entity_id"):][:400]
        assert 'Report.status == "draft"' not in window, (
            "the publish-path report lookup must not filter for drafts: "
            "publishing runs after submit, so the row is 'posted'"
        )

    def test_null_guard_before_dereference(self):
        """A miss must not dereference `.id`.

        The pre-Step-4 code dereferenced `.id` on an unguarded lookup, so an
        over-narrow filter raised AttributeError mid-publish rather than
        skipping the upload.
        """
        source = self._create_bank_transaction_source()
        assert re.search(r"if not _report_row:", source), (
            "the report lookup must be None-guarded before .id is read"
        )


# ---------------------------------------------------------------------------
# 2. Load-bearing status filters
#
# Each of these used to be implied by querying report_draft. Collapsing onto
# `report` makes the implication vanish; the filter is now the only thing
# preventing the query from matching a SUBMITTED report.
# ---------------------------------------------------------------------------

class TestLoadBearingStatusFilters:

    def test_sales_recovery_path_is_scoped_to_drafts(self):
        """sales.py's recovery lookup must be draft-scoped.

        It was deliberately status-AGNOSTIC and forces status="draft" on
        whatever it finds. That was survivable while report_draft was its own
        table. Post-collapse an unfiltered match can return a genuinely
        submitted report — and the forced flip would UN-SUBMIT it.
        """
        src = _source("blueprints/report/routes/sales.py")
        idx = src.find("any_draft = Report.query.filter(")
        assert idx != -1, "sales.py recovery lookup (any_draft) not found"
        block = src[idx:idx + 400]
        assert 'Report.status == "draft"' in block, (
            "the sales.py recovery lookup must be constrained to drafts; "
            "without it, forcing status='draft' can un-submit a posted report"
        )

    def test_sibling_delete_is_scoped_to_drafts(self):
        """delete_report's sibling sweep must be draft-scoped.

        It matches siblings on (company, transaction_date) and duplicates per
        date do occur. Unscoped, it deletes submitted reports for the same
        entity and date.
        """
        src = _source("blueprints/report/routes/report_detail.py")
        idx = src.find("other_drafts = (")
        assert idx != -1, "delete_report sibling query (other_drafts) not found"
        block = src[idx:idx + 400]
        assert 'Report.status == "draft"' in block, (
            "the sibling delete sweep must filter status == 'draft'"
        )

    def test_onboarding_floor_date_is_scoped_to_drafts(self):
        """The onboarding floor date must come from the opening DRAFT.

        Unfiltered, "earliest row for this entity" resolves to the oldest
        SUBMITTED report and silently moves the floor date, letting a first
        report be back-dated before onboarding.
        """
        src = _source("blueprints/report/routes/opening.py")
        idx = src.find("def _onboarding_floor_date")
        assert idx != -1
        block = src[idx:idx + 1200]
        assert 'Report.status == "draft"' in block, (
            "_onboarding_floor_date must filter status == 'draft'"
        )

    def test_statement_export_excludes_drafts_null_safely(self):
        """The statements export must exclude drafts, NULL-safely.

        `status != 'draft'` evaluates to NULL — not true — for a NULL-status
        row and silently drops it. r0 PART 1 left NULL-status rows behind.
        """
        src = _source("blueprints/report/services/report_detail.py")
        assert "Report.status.is_(None)" in src, (
            "submitted-only filters must be NULL-safe: use "
            'db.or_(Report.status.is_(None), Report.status != "draft")'
        )


# ---------------------------------------------------------------------------
# 3. The dropped tables must stay gone
# ---------------------------------------------------------------------------

DROPPED = [
    "ReportDraft", "ShopExpenseDraft", "ReportCashCountDraft",
    "ReportHistoryDraft", "ReportV2", "ReportExpenseDetail",
]


class TestDroppedModelsAreNotReferenced:

    def test_no_model_files_remain(self):
        models = ROOT / "blueprints" / "report" / "models"
        for name in ("report_draft", "shop_expense_draft", "report_cash_count_draft",
                     "report_history_draft", "report_v2", "report_detail",
                     "report_expense_detail"):
            assert not (models / f"{name}.py").exists(), (
                f"{name}.py was dropped in Step 4b and must not come back"
            )

    @pytest.mark.parametrize("model", DROPPED)
    def test_model_not_imported_anywhere(self, model):
        """No live import of a dropped model.

        A stale `db.relationship("ReportV2", ...)` raises InvalidRequestError
        at mapper configuration; a stale query raises ProgrammingError from
        the middle of a route. Both are cheap to prevent here.
        """
        offenders = []
        for path in list((ROOT / "blueprints").rglob("*.py")) + [ROOT / "models" / "db.py"]:
            if "__pycache__" in str(path):
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                if re.search(rf"\b{model}\b", stripped) and (
                    "import" in stripped or f"{model}." in stripped or f'"{model}"' in stripped
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{i}: {stripped[:80]}")
        assert not offenders, f"{model} is still referenced:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# 4. Cash count: "counted, all zero" vs "never counted"
#
# save_cash_count_details deletes the row for a denomination counted as zero,
# so an all-zero count has NO report_cash_count rows. Before Step 4 the
# presence of a report_cashcount_draft row distinguished the two; that table
# is gone, and the signal is now report.actual_cash_total IS NOT NULL.
#
# Getting this wrong makes the export 404 on a legitimately-counted report.
# ---------------------------------------------------------------------------

class TestAllZeroCashCountIsDistinguishable:

    def test_helper_uses_actual_cash_total_as_the_signal(self):
        src = _source("blueprints/report/services/cash_denominations.py")
        idx = src.find("def legacy_column_counts_for_report")
        assert idx != -1
        block = src[idx:idx + 1800]
        assert "actual_cash_total" in block, (
            "legacy_column_counts_for_report must decide 'was this counted' "
            "from report.actual_cash_total — count rows alone cannot tell an "
            "all-zero count from a report that was never counted"
        )

    def test_returns_zeros_not_none_for_an_all_zero_count(self, monkeypatch):
        """Behavioural: an all-zero count must yield zeros, not None.

        None makes the export 404 with "I couldn't find a cash count".

        Uses fakes rather than the sqlite fixture, matching
        test_report_deposit_change.py — the models are schema-qualified
        (pettycashv3.*) and sqlite has no schemas.
        """
        from blueprints.report.services import cash_denominations as cd

        monkeypatch.setattr(cd, "get_cash_count_details", lambda _rid: {})
        # counted, and it came to zero -> actual_cash_total is 0.0, NOT None
        monkeypatch.setattr(cd, "db", _fake_db_returning(0.0))

        result = cd.legacy_column_counts_for_report("any-report-id")
        assert result is not None, (
            "an all-zero cash count must not read as 'never counted' — "
            "returning None 404s the PDF export"
        )
        assert set(result.values()) == {0}
        assert "thousand_note" in result and "one_coin" in result

    def test_returns_none_when_never_counted(self, monkeypatch):
        from blueprints.report.services import cash_denominations as cd

        monkeypatch.setattr(cd, "get_cash_count_details", lambda _rid: {})
        monkeypatch.setattr(cd, "db", _fake_db_returning(None))

        assert cd.legacy_column_counts_for_report("any-report-id") is None, (
            "a report that was never counted must return None so the export "
            "can 404"
        )

    def test_count_rows_win_over_the_zero_path(self, monkeypatch):
        """Real counts must come from the rows, not the zero fallback."""
        from blueprints.report.services import cash_denominations as cd

        row = SimpleNamespace(quantity=3, cash_value=100.0)
        monkeypatch.setattr(cd, "get_cash_count_details", lambda _rid: {7: row})
        monkeypatch.setattr(
            cd, "counts_to_legacy_columns", lambda counts: {"onehundred_note": counts[7]}
        )
        monkeypatch.setattr(cd, "db", _fake_db_returning(300.0))

        assert cd.legacy_column_counts_for_report("any-report-id") == {
            "onehundred_note": 3
        }


# ---------------------------------------------------------------------------
# 5. The Xero audit trail must survive a report deletion (r9a09 / Step 4d)
# ---------------------------------------------------------------------------

class TestXeroSyncRowsGoWithTheReport:
    """The schema (C5) reversed r9a09: xero_report_sync.report_id and
    xero_bank_transfer.sync_report_id are NOT NULL and ON DELETE CASCADE. A publish record
    for a report that no longer exists protects nothing, so it goes with the report - and the
    application deletes the rows itself so SQLite (no FK enforcement) behaves like Postgres.
    """

    def test_app_deletes_the_sync_rows_with_the_report(self):
        src = _source("blueprints/report/routes/report_detail.py")
        for model, col in (("XeroReportSync", "report_id"),
                           ("XeroBankTransfer", "sync_report_id"),
                           ("XeroBankTransaction", "sync_report_id")):
            assert re.search(
                rf"{model}\.query\.filter_by\({col}=report_id\)\.delete\(\)", src
            ), f"{model} rows must be deleted with the report (schema: ON DELETE CASCADE)"

    def test_models_declare_cascade_and_not_null(self):
        for rel, col in (("blueprints/xero/models/xero_report_sync.py", "report_id"),
                         ("blueprints/xero/models/xero_bank_transfer.py", "sync_report_id")):
            src = _source(rel)
            block = src.split(f"{col} = db.Column(")[1][:300]
            assert 'ondelete="CASCADE"' in block, f"{rel}: {col} goes with the report (schema)"
            assert "nullable=False" in block, f"{rel}: {col} is NOT NULL (schema)"
            assert "primary_key=True" not in block, f"{rel}: {col} is not part of the primary key"
