"""The Petty Cash API's report history (``blueprints/petty_cash_api/routes/history.py``), over the
list the Jinja page uses (pinned by tests/test_report_history_state.py). The door is
tests/test_petty_cash_api_door.py's."""
from __future__ import annotations

from datetime import timedelta

import char_factories as F
import pytest
from test_report_actions_state import _older
from test_report_submit_state import D3, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char


def _get(app, client, entity, who, **query):
    headers = F.petty_cash_headers(app, who.id, origin="http://localhost:3010")
    return client.get(f"/api/petty-cash/v1/companies/{entity.id}/reports", query_string=query, headers=headers)


def test_one_page_newest_first_with_what_may_be_done(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner, days_back=1, publishing_status="failed")
    latest = _older(app, db, entity, owner, days_back=0)

    resp = _get(app, client, entity, owner)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert [r["id"] for r in body["reports"]] == [latest, older]
    first = body["reports"][0]
    assert first["transaction_date"] == F.iso(D3)
    assert (first["status"], first["status_label"], first["status_tone"]) == ("submitted", "Submitted", "info")
    assert first["submitted_by"] == "Olive" and first["publish_reasons"] == []
    assert first["was_published"] is False and body["reports"][1]["was_published"] is True
    assert first["permissions"] == {"edit": True, "delete": True}
    assert body["reports"][1]["status_label"] == "Publish failed"
    assert body["reports"][1]["permissions"] == {"edit": False, "delete": False}
    assert {k: body[k] for k in ("page", "per_page", "total_pages", "total_count", "latest_report_id", "can_publish")} == {
        "page": 1, "per_page": 10, "total_pages": 1, "total_count": 2, "latest_report_id": latest, "can_publish": True}
    assert body["currency_code"]


def test_filters_and_pages(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    ids = [_older(app, db, entity, owner, days_back=i) for i in range(12)]
    draft = _older(app, db, entity, owner, days_back=20, status="draft")

    page2 = _get(app, client, entity, owner, page=2).get_json()
    assert [r["id"] for r in page2["reports"]] == ids[10:] + [draft] and page2["total_pages"] == 2
    drafts = _get(app, client, entity, owner, status="draft").get_json()["reports"]
    assert [(r["id"], r["current_section"]) for r in drafts] == [(draft, "submitted")]
    assert drafts[0]["created_at"] and drafts[0]["submitted_at"] is None
    ranged = _get(app, client, entity, owner, start_date=F.iso(D3 - timedelta(days=2)), end_date=F.iso(D3)).get_json()
    assert [r["id"] for r in ranged["reports"]] == ids[:3]
    assert _get(app, client, entity, owner, per_page=25).get_json()["total_pages"] == 1


@pytest.mark.parametrize("query, message", [
    ({"status": "nonsense"}, "That status filter isn't one I know. Choose Draft, Submitted, Published or Failed."),
    ({"per_page": 7}, "Show 10, 25, 50 or 100 reports a page."),
    ({"page": 0}, "Pages start at 1. Choose a page from the list."),
    ({"page": "x"}, "The page or the page size isn't a whole number. Choose a page from the list."),
    ({"start_date": "2026-10-01"}, "Choose both dates to see the reports between them."),
    ({"start_date": "01/10/2026", "end_date": "2026-10-02"}, "A date isn't in the YYYY-MM-DD form. Choose it from the calendar."),
    ({"start_date": "2026-10-05", "end_date": "2026-10-02"}, "The start date is after the end date. Choose a start on or before the end."),
])
def test_a_bad_filter_is_refused(app, client, db, shop, query, message):  # noqa: F811
    owner, entity = shop
    resp = _get(app, client, entity, owner, **query)
    assert resp.status_code == 422 and resp.get_json() == {"error": message}


def test_a_failed_publish_brings_its_reasons(app, client, db, shop, monkeypatch):  # noqa: F811
    owner, entity = shop
    _older(app, db, entity, owner, days_back=0, publishing_status="failed")
    monkeypatch.setattr("blueprints.report.services.history_query.annotate_resolution",
                        lambda *a, **k: [{"text": "No account code for Cleaning", "resolved": False, "resolvable": True}])

    row = _get(app, client, entity, owner).get_json()["reports"][0]

    assert row["publish_reasons"] == [{"text": "No account code for Cleaning", "resolved": False}]


def test_another_companys_history_is_refused_at_the_door(app, client, db, shop):  # noqa: F811
    owner, _entity = shop
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com", first_name="Sam")
        theirs = F.make_entity(db, stranger, name="Their Shop")
    assert _get(app, client, theirs, owner).status_code == 403
