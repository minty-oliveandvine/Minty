"""What happens to a submitted report afterwards - reopening it as a draft and deleting it
(``report/services/report_actions.py``) - pinned before both moved into that service
(minty-petty-cash-web's port, 2026-10-15). Driven through the Jinja routes
(``/report/<id>/convert-to-draft``, ``/report/delete/<id>``) until Flask's HTML frontend was deleted
(2026-10-20); now through the Petty Cash API's ``POST /reports/<id>/reopen`` and
``DELETE /reports/<id>``, which answer a refusal ``{error}`` where the pages flashed. (The API's own
answers: tests/test_petty_cash_api_report.py.)

Characterisation, green before and after the extraction. Tests marked FIXED or RULE pin what it
changed deliberately.
"""
from __future__ import annotations

from datetime import timedelta

import char_factories as F
import pytest
from test_report_submit_state import D3, _ready, _row, _stock, _submit, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char


def _submitted(app, client, db, entity, owner, **fields):  # noqa: F811
    report = _ready(app, db, entity, owner, **fields)
    resp = _submit(client, owner, entity)
    assert resp.status_code == 200, resp.get_json()
    return report


def _set(app, report_id, **fields):
    from models.db import Report, db as _db

    with app.app_context():
        row = _db.session.get(Report, report_id)
        for k, v in fields.items():
            setattr(row, k, v)
        _db.session.commit()


def _xero(app, report_id):
    from models.db import Report, XeroReportSync, db as _db

    with app.app_context():
        row = _db.session.get(Report, report_id)
        return {"xero_integrated": bool(row.xero_integrated),
                "publishing_status": str(getattr(row.publishing_status, "value", row.publishing_status)),
                "sync_rows": XeroReportSync.query.filter_by(report_id=report_id).count()}


def _url(entity, report_id, tail=""):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/{report_id}{tail}"


def _reopen(client, who, entity, report_id):
    return client.post(_url(entity, report_id, "/reopen"), headers=F.petty_cash_headers(client.application, who.id))


def _delete(client, who, entity, report_id):
    return client.delete(_url(entity, report_id), headers=F.petty_cash_headers(client.application, who.id))


def _older(app, db, entity, owner, days_back=1, **fields):  # noqa: F811
    from models.db import Report

    values = {"opening_balance": 0, "closing_balance": 10, "completed_sections": ["opening"],
              "current_section": "submitted"}
    values.update(fields)
    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=D3 - timedelta(days=days_back),
                     status=values.pop("status", "submitted"), created_by=owner.id, **values)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


# --- reopening ---------------------------------------------------------------------------------------


def test_reopening_the_latest_report_makes_it_a_draft_from_opening(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    assert _stock(app, entity) == {50: 50, 5: 5}

    resp = _reopen(client, owner, entity, report)

    assert resp.status_code == 200, resp.get_json()
    row = _row(app, report)
    assert row["status"] == "draft" and row["section"] == "opening" and row["completed"] == []
    assert row["closing"] == 55  # the figures stay
    assert _stock(app, entity) == {}  # no submitted report left: the stock falls back


def test_only_the_latest_report_can_be_reopened(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    _submitted(app, client, db, entity, owner)

    resp = _reopen(client, owner, entity, older)

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "You can only edit the most recent report. Delete or edit the newer "
                                        "reports first."}
    assert _row(app, older)["status"] == "submitted"


def test_a_report_in_xero_reopens_and_keeps_its_xero_markers(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")

    resp = _reopen(client, owner, entity, report)

    assert resp.status_code == 200
    assert _xero(app, report)["xero_integrated"] is True
    assert _xero(app, report)["publishing_status"] == "completed"


def test_an_unknown_report_is_404(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    import uuid

    resp = _reopen(client, owner, entity, str(uuid.uuid4()))

    assert resp.status_code == 404 and resp.get_json() == {"error": "Hmm, I couldn't find that report."}


def test_fixed_a_draft_cannot_be_reopened(app, client, db, shop):  # noqa: F811
    """FIXED: there was no status check, so "reopening" a draft wiped its progress."""
    owner, entity = shop
    draft = _ready(app, db, entity, owner)  # every step done, not submitted

    resp = _reopen(client, owner, entity, draft)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "This report is already a draft. Carry on with the Daily Closing."}
    assert _row(app, draft)["completed"] == ["opening", "sales", "expenses", "deposit", "cash_count"]


def test_fixed_a_report_xero_is_publishing_cannot_be_reopened(app, client, db, shop):  # noqa: F811
    """FIXED: the publish worker then marked a DRAFT as published."""
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, publishing_status="publishing")

    resp = _reopen(client, owner, entity, report)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Xero is still publishing this report. Wait until it finishes, then edit it."}
    assert _row(app, report)["status"] == "submitted"


def test_fixed_resubmitting_a_report_reopened_from_xero_is_no_longer_published(app, client, db, shop):  # noqa: F811
    """FIXED: it kept xero_integrated, so a changed report still read "Published to Xero"."""
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")
    _reopen(client, owner, entity, report)
    from models.db import Report, db as _db

    with app.app_context():
        row = _db.session.get(Report, report)
        row.completed_sections = ["opening", "sales", "expenses", "deposit", "cash_count"]
        _db.session.commit()

    _submit(client, owner, entity)

    assert _row(app, report)["status"] == "submitted"
    assert _xero(app, report) == {"xero_integrated": False, "publishing_status": "completed", "sync_rows": 0}


# --- deleting ----------------------------------------------------------------------------------------


def test_deleting_the_latest_report_removes_it_and_refreshes_the_stock(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = _delete(client, owner, entity, report)

    assert resp.status_code == 200, resp.get_json()
    assert _row(app, report) is None
    assert _stock(app, entity) == {}


def test_only_the_latest_report_can_be_deleted(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    _submitted(app, client, db, entity, owner)

    resp = _delete(client, owner, entity, older)

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "I can only delete the most recent report, and there's a newer one after this."}
    assert _row(app, older) is not None


def test_a_report_in_xero_is_deleted_with_its_publish_record(app, client, db, shop):  # noqa: F811
    """Kept by the owner's rule (2026-10-15) - allowed, the page warns and points to Edit report.
    (That the publish record goes with it is tests/test_char_xero_sync.py's.)"""
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")

    _delete(client, owner, entity, report)

    assert _row(app, report) is None


def test_rule_a_report_xero_is_publishing_cannot_be_deleted(app, client, db, shop):  # noqa: F811
    """RULE (owner, 2026-10-15): the publish worker would find no report."""
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, publishing_status="publishing")

    resp = _delete(client, owner, entity, report)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Xero is still publishing this report. Wait until it finishes before deleting it."}
    assert _row(app, report) is not None


def test_fixed_deleting_an_unknown_report_says_so(app, client, db, shop):  # noqa: F811
    """FIXED: the Jinja route's 404 was caught by the generic handler, which used the report id as the
    company id."""
    import uuid

    owner, entity = shop

    resp = _delete(client, owner, entity, str(uuid.uuid4()))

    assert resp.status_code == 404 and resp.get_json() == {"error": "Hmm, I couldn't find that report."}


def test_deleting_keeps_the_receipts_until_the_rows_are_gone(app, client, db, shop, monkeypatch):  # noqa: F811
    """FIXED: the receipt files went before the commit, so a failed delete lost them."""
    from models.db import ShopExpense

    s3 = F.install_fake_s3(monkeypatch)
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    with app.app_context():
        line = ShopExpense.query.filter_by(report_id=report).first()
        line.add_receipt("expenses/x/RECEIPT_15.jpg", original_name="r.jpg", mime_type="image/jpeg")
        db.session.commit()
    s3.objects["expenses/x/RECEIPT_15.jpg"] = b"bytes"

    def fail(*_a, **_k):
        raise RuntimeError("the stock rebuild failed")

    # patched where nothing binds it at import (the conftest re-import trap)
    monkeypatch.setattr("blueprints.report.services.cash_denominations.refresh_cash_stock", fail)
    _delete(client, owner, entity, report)

    assert _row(app, report) is not None
    assert "expenses/x/RECEIPT_15.jpg" in s3.objects
