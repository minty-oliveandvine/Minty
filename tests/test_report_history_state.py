"""Report history's list (``report/services/history_query.py::get_entity_report_history``), which the
Jinja history page and the Petty Cash API's ``GET /reports`` share.

Characterisation, green before and after the rewrite. Tests marked FIXED pin what it changed
deliberately.
"""
from __future__ import annotations

from datetime import timedelta

import char_factories as F
import pytest
from test_report_actions_state import _older
from test_report_submit_state import D3, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char


def _history(app, entity, **kwargs):
    from blueprints.report.services.history_query import get_entity_report_history

    with app.app_context():
        data = get_entity_report_history(str(entity.id), **kwargs)
        rows = [{"id": str(r.id), "day": r.transaction_date, "first_name": r.first_name,
                 "status": str(getattr(r.status, "value", r.status)), "reasons": r.publish_reasons}
                for r in data["report_history"]]
        return data, rows


def _days(app, db, entity, owner, n, **fields):  # noqa: F811
    """``n`` submitted reports, on D3 and the n-1 days before it; ids newest first."""
    return [_older(app, db, entity, owner, days_back=i, **fields) for i in range(n)]


def test_newest_first_with_counts_and_pages(app, db, shop):  # noqa: F811
    owner, entity = shop
    ids = _days(app, db, entity, owner, 12)

    data, rows = _history(app, entity)
    assert [r["id"] for r in rows] == ids[:10]
    assert (data["page"], data["total_pages"], data["total_count"]) == (1, 2, 12)
    assert rows[0]["day"] == D3 and rows[0]["first_name"] == "Olive"

    data, rows = _history(app, entity, page=2)
    assert [r["id"] for r in rows] == ids[10:]
    assert _history(app, entity, page=3)[1] == []
    assert _history(app, entity, per_page=25)[0]["total_pages"] == 1


def test_no_reports_is_one_empty_page(app, db, shop):  # noqa: F811
    _owner, entity = shop
    data, rows = _history(app, entity)
    assert rows == [] and (data["total_pages"], data["total_count"], data["latest_report_id"]) == (1, 0, None)


@pytest.mark.parametrize("status, kept", [
    ("draft", {"draft"}),
    ("submitted", {"submitted", "edited_after_publish"}),
    ("published", {"published"}),
    ("failed", {"failed", "publishing"}),
    (None, {"draft", "submitted", "edited_after_publish", "published", "failed", "publishing"}),
])
def test_the_status_filter_keeps_one_pill(app, db, shop, status, kept):  # noqa: F811
    owner, entity = shop
    made = {
        "draft": _older(app, db, entity, owner, days_back=0, status="draft"),
        "submitted": _older(app, db, entity, owner, days_back=1),
        "edited_after_publish": _older(app, db, entity, owner, days_back=2, publishing_status="completed"),
        "published": _older(app, db, entity, owner, days_back=3, status="published", xero_integrated=True,
                            publishing_status="completed"),
        "failed": _older(app, db, entity, owner, days_back=4, publishing_status="failed"),
        "publishing": _older(app, db, entity, owner, days_back=5, publishing_status="publishing"),
    }
    data, rows = _history(app, entity, status=status)
    assert {r["id"] for r in rows} == {made[k] for k in kept}
    assert data["total_count"] == len(kept)


def test_a_date_range_is_inclusive_and_one_date_alone_is_ignored(app, db, shop):  # noqa: F811
    owner, entity = shop
    ids = _days(app, db, entity, owner, 5)
    start, end = F.iso(D3 - timedelta(days=3)), F.iso(D3 - timedelta(days=1))

    assert [r["id"] for r in _history(app, entity, start_date=start, end_date=end)[1]] == ids[1:4]
    assert len(_history(app, entity, start_date=start)[1]) == 5
    assert len(_history(app, entity, end_date=end)[1]) == 5
    with pytest.raises(ValueError):
        _history(app, entity, start_date=end, end_date=start)


def test_the_latest_report_is_the_newest_day_of_any_status(app, db, shop):  # noqa: F811
    owner, entity = shop
    _older(app, db, entity, owner, days_back=2)
    draft = _older(app, db, entity, owner, days_back=0, status="draft")
    assert _history(app, entity)[0]["latest_report_id"] == draft


def test_one_report_by_id(app, db, shop):  # noqa: F811
    owner, entity = shop
    ids = _days(app, db, entity, owner, 3)
    assert [r["id"] for r in _history(app, entity, report_id=ids[1])[1]] == [ids[1]]


def test_another_companys_reports_are_not_listed(app, db, shop):  # noqa: F811
    owner, entity = shop
    with app.app_context():
        other = F.make_entity(db, owner, name="Other Co")
    _older(app, db, other, owner, days_back=0)
    assert _history(app, entity)[1] == []


def test_publish_reasons_only_for_a_failed_row(app, db, shop, monkeypatch):  # noqa: F811
    owner, entity = shop
    failed = _older(app, db, entity, owner, days_back=0, publishing_status="failed")
    _older(app, db, entity, owner, days_back=1)
    monkeypatch.setattr("blueprints.report.services.history_query.annotate_resolution",
                        lambda entity_id, items, report_id=None, cache=None: [{"text": f"why {report_id}"}])

    rows = {r["id"]: r["reasons"] for r in _history(app, entity)[1]}

    assert rows[failed] == [{"text": f"why {failed}"}]
    assert [v for k, v in rows.items() if k != failed] == [[]]


def test_fixed_reasons_are_worked_out_only_for_the_page_shown(app, db, shop, monkeypatch):  # noqa: F811
    """FIXED: every failed report the company ever had was resolved against live Xero on every page
    load, then all but one page thrown away."""
    owner, entity = shop
    _days(app, db, entity, owner, 12, publishing_status="failed")
    calls = []
    monkeypatch.setattr("blueprints.report.services.history_query.annotate_resolution",
                        lambda entity_id, items, report_id=None, cache=None: calls.append(report_id) or [])

    _history(app, entity)

    assert len(calls) == 10


def test_fixed_the_query_count_does_not_grow_with_the_rows(app, db, shop):  # noqa: F811
    """FIXED: one user lookup per row (and every report of the company loaded to show ten)."""
    from sqlalchemy import event

    owner, entity = shop
    _days(app, db, entity, owner, 3)

    def count(n_more):
        for i in range(n_more):
            _older(app, db, entity, owner, days_back=10 + i)
        statements = []
        with app.app_context():
            from models.db import db as _db

            engine = _db.engine
            listener = lambda *a, **k: statements.append(1)  # noqa: E731
            event.listen(engine, "before_cursor_execute", listener)
            try:
                _history(app, entity)
            finally:
                event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    few = count(0)
    many = count(6)
    assert many == few
