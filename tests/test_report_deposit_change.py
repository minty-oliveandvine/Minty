from __future__ import annotations

from datetime import date
from types import SimpleNamespace


class _FakeQueryResult:
    def __init__(self, result):
        self._result = result

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeFilterQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return _FakeQueryResult(self._result)


class _FakeFilterSequenceQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *_args, **_kwargs):
        if self._results:
            return _FakeQueryResult(self._results.pop(0))
        return _FakeQueryResult(None)


def _build_report(**overrides):
    values = {
        "id": "report-1",
        "company": "entity-1",
        "transaction_date": date(2025, 3, 2),
        "opening_balance": 20000.0,
        "cash_addition": 0.0,
        "adjusted_opening_balance": 20000.0,
        "cash_sales": 0.0,
        "visa_sales": 0.0,
        "alipay_sales": 0.0,
        "wechat_sales": 0.0,
        "master_sales": 0.0,
        "unionpay_sales": 0.0,
        "amex_sales": 0.0,
        "octopus_sales": 0.0,
        "foodpanda_sales": 0.0,
        "keeta_sales": 0.0,
        "openrice_sales": 0.0,
        "shop_sales": 0.0,
        "delivery_sales": 0.0,
        "total_sales": 0.0,
        "expenses": 0.0,
        "bank_deposit": 5000.0,
        "closing_balance": 15000.0,
        "discrepancy_amount": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_update_report_after_deposit_change_replaces_deposit_and_updates_next_day_draft(
    app,
    monkeypatch,
):
    from blueprints.report.services import shared

    previous_day_report = _build_report()
    same_day_draft = _build_report(
        id="draft-same-day",
        transaction_date=date(2025, 3, 2),
        bank_deposit=5000.0,
        closing_balance=15000.0,
    )
    next_day_draft = _build_report(
        id="draft-1",
        transaction_date=date(2025, 3, 3),
        opening_balance=18000.0,
        adjusted_opening_balance=18000.0,
        bank_deposit=0.0,
        closing_balance=18000.0,
    )
    commit_calls: list[str] = []

    with app.app_context():
        monkeypatch.setattr(
            shared,
            "get_cash_sales_from_detail",
            lambda _report_id, fallback_value=0.0: fallback_value,
        )
        # recalculate_report sums report_sale_detail, which has no table in the
        # sqlite fixture. Previously this went unnoticed: the ReportV2 patch this
        # test used to install sat in front of it. Stub it so the test exercises
        # the balance arithmetic it is actually about.
        monkeypatch.setattr(
            shared,
            "sum_sales_by_type",
            lambda _report_id: {"Cash": 0.0, "Electronic": 0.0, "Delivery": 0.0},
        )
        # Patch Report, not ReportDraft: the write flip pointed both
        # propagation helpers at `report`. The same-day lookup now returns
        # None by construction — a submitted report and a same-day draft were
        # two rows before and are one row now, so it cannot be both.
        monkeypatch.setattr(
            shared.Report,
            "query",
            _FakeFilterSequenceQuery([None, next_day_draft]),
        )
        monkeypatch.setattr(
            shared.db.session,
            "commit",
            lambda: commit_calls.append("commit"),
        )
        monkeypatch.setattr(
            shared.db.session,
            "rollback",
            lambda: commit_calls.append("rollback"),
        )

        updated_report = shared.update_report_after_deposit_change(
            previous_day_report,
            3000.0,
        )

    assert updated_report is previous_day_report
    assert previous_day_report.bank_deposit == 3000.0
    assert previous_day_report.closing_balance == 17000.0
    # same_day_draft is deliberately NOT asserted: post write-flip the
    # same-day lookup returns None (one row cannot be both posted and draft),
    # and the correction is applied to previous_day_report directly above.
    assert next_day_draft.opening_balance == 17000.0
    assert next_day_draft.adjusted_opening_balance == 17000.0
    assert next_day_draft.closing_balance == 17000.0
    assert commit_calls == ["commit"]


def _make_endpoint_report(**overrides):
    values = {
        "id": "report-1",
        "bank_deposit": 5000.0,
        "closing_balance": 15000.0,
        "publishing_status": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_db_helper(monkeypatch, legacy, report, helper_calls, *, updated_closing=17000.0):
    monkeypatch.setattr(legacy.Report, "query", _FakeFilterQuery(report))

    def _fake_update(entity_id, report_date, amount):
        helper_calls.update(
            {"entity_id": entity_id, "date": report_date, "amount": amount}
        )
        report.closing_balance = updated_closing
        report.bank_deposit = amount
        return report

    monkeypatch.setattr(legacy, "update_after_deposit_change", _fake_update)
    # Default: both settings present, so the new "missing settings" guard
    # doesn't fire. Individual tests can override this.
    monkeypatch.setattr(
        legacy,
        "get_entity_account_settings",
        lambda entity_id, role: {"xero_account_id": f"acc-{role}", "name": role},
    )


def test_report_check_dept_bank_yest_unpublished_change_skips_xero(app, monkeypatch):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report()
    helper_calls = {}
    xero_calls = []

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls)
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: xero_calls.append((args, kwargs)) or (True, None),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 3000,
                "date": "2025-03-02",
                "kind": "change",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    assert helper_calls == {
        "entity_id": "entity-1",
        "date": "2025-03-02",
        "amount": 3000.0,
    }
    assert xero_calls == []
    assert payload["status"] == "success"
    assert payload["bank_deposit"] == 3000.0
    assert payload["closing_balance"] == 17000.0
    assert payload["is_published"] is False
    assert payload["xero_status"] == "skipped"
    assert payload["redirect_url"].endswith("transaction_date=2025-03-03")


def test_report_check_dept_bank_yest_unpublished_no_deposit_zeros_out(app, monkeypatch):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report()
    helper_calls = {}
    xero_calls = []

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls, updated_closing=20000.0)
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: xero_calls.append((args, kwargs)) or (True, None),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 0,
                "date": "2025-03-02",
                "kind": "no",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    assert helper_calls["amount"] == 0.0
    assert xero_calls == []
    assert payload["status"] == "success"
    assert payload["bank_deposit"] == 0.0
    assert payload["xero_status"] == "skipped"


def test_report_check_dept_bank_yest_published_change_calls_xero_with_prev_amount(
    app, monkeypatch
):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report(publishing_status="completed")
    helper_calls = {}
    xero_calls = []

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls)
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: xero_calls.append((args, kwargs)) or (True, None),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 3000,
                "date": "2025-03-02",
                "kind": "change",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    assert len(xero_calls) == 1
    args, _ = xero_calls[0]
    assert args == ("entity-1", "2025-03-02", 5000.0, 3000.0)
    assert payload["status"] == "success"
    assert payload["xero_status"] == "success"
    assert payload["is_published"] is True


def test_report_check_dept_bank_yest_published_no_deposit_reverses_xero(app, monkeypatch):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report(publishing_status="completed")
    helper_calls = {}
    xero_calls = []

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls, updated_closing=20000.0)
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: xero_calls.append((args, kwargs)) or (True, None),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 0,
                "date": "2025-03-02",
                "kind": "no",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    assert len(xero_calls) == 1
    args, _ = xero_calls[0]
    assert args == ("entity-1", "2025-03-02", 5000.0, 0.0)
    assert payload["status"] == "success"
    assert payload["xero_status"] == "success"


def test_report_check_dept_bank_yest_published_xero_failure_returns_warning(
    app, monkeypatch
):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report(publishing_status="completed")
    helper_calls = {}

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls)
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: (False, "Xero: Cannot delete reconciled transfer"),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 3000,
                "date": "2025-03-02",
                "kind": "change",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    # DB update still happened; Xero failure surfaces as warning, not error.
    assert helper_calls["amount"] == 3000.0
    assert payload["status"] == "warning"
    assert payload["xero_status"] == "failed"
    assert "Xero" in payload["message"]
    assert "Cannot delete reconciled transfer" in payload["message"]


def test_report_check_dept_bank_yest_blocks_when_bank_setting_missing(app, monkeypatch):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report(publishing_status="completed")
    helper_calls = {}
    xero_calls = []

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls)
        # Override the default "both settings present" stub to simulate the
        # "Unknown Bank" scenario: deposit bank account is missing.
        monkeypatch.setattr(
            legacy,
            "get_entity_account_settings",
            lambda entity_id, role: (
                None
                if role == "bank"
                else {"xero_account_id": "acc-pettycash", "name": "Petty Cash"}
            ),
        )
        monkeypatch.setattr(
            legacy,
            "update_xero_deposit_after_change",
            lambda *args, **kwargs: xero_calls.append((args, kwargs)) or (True, None),
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 3000,
                "date": "2025-03-02",
                "kind": "change",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    # Critical: no DB mutation, no Xero call. Hard-stop before either.
    assert helper_calls == {}
    assert xero_calls == []
    assert response.status_code == 409
    assert payload["status"] == "error"
    assert "Deposit Bank Account" in payload["message"]
    assert payload["missing_settings"] == ["Deposit Bank Account"]


def test_report_check_dept_bank_yest_blocks_when_both_settings_missing(app, monkeypatch):
    from blueprints.report.routes import legacy

    report = _make_endpoint_report(publishing_status="completed")
    helper_calls = {}

    with app.app_context():
        _patch_db_helper(monkeypatch, legacy, report, helper_calls)
        monkeypatch.setattr(
            legacy,
            "get_entity_account_settings",
            lambda entity_id, role: None,
        )

        with app.test_request_context(
            "/api/check-dept-bank-yest/entity-1",
            method="POST",
            json={
                "amount": 0,
                "date": "2025-03-02",
                "kind": "no",
            },
        ):
            response = legacy.report_check_dept_bank_yest("entity-1")

    payload = response.get_json()
    assert helper_calls == {}
    assert response.status_code == 409
    assert payload["missing_settings"] == [
        "Deposit Bank Account",
        "Petty Cash Account",
    ]
