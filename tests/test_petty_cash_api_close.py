"""The Petty Cash API's last step (``blueprints/petty_cash_api/routes/close.py``): the day's summary,
the submit and the outcome, through ``report/services/submit.py`` (the Jinja Close page's submit,
pinned by tests/test_report_submit_state.py). The door is tests/test_petty_cash_api_door.py's.
"""
from __future__ import annotations

import uuid

import char_factories as F
import pytest
from test_report_submit_state import ALL, D3, _ready, _row, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"


def _headers(app, who):
    return F.petty_cash_headers(app, who.id, origin=WEB)


def _base(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports"


def _close(app, client, who, entity, day=D3):
    return client.get(f"{_base(entity)}/close", query_string={"transaction_date": F.iso(day)},
                      headers=_headers(app, who))


def _submit(app, client, who, entity, day=D3):
    return client.post(f"{_base(entity)}/submit", json={"transaction_date": F.iso(day)}, headers=_headers(app, who))


# --- the summary -------------------------------------------------------------------------------------


def test_the_close_read_brings_the_day_as_submit_will_post_it(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _ready(app, db, entity, owner)

    resp = _close(app, client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["draft"]["id"] == report and body["currency_code"] == "HKD"
    assert (body["opening_balance"], body["cash_addition"]) == (100, 20)
    assert body["sales"]["cash"] == 50
    assert body["sales"]["yesterday_total"] is None  # no report the day before
    assert len(body["sales"]["history"]) == 30 and body["sales"]["history"][-1]["date"] == F.iso(D3)
    assert body["expenses"]["total"] == 15 and body["expenses"]["lines"][0]["item"] == "Advertising"
    assert body["cash"] == {"bank_deposit": 100, "expected": 55, "counted": 55, "safe_box": 0,
                            "difference": {"amount": 0, "kind": "none", "reason": ""}}
    assert body["closing_balance"] == 55
    assert body["problem"] is None


def test_the_sales_history_counts_the_days_before(app, client, db, shop):  # noqa: F811
    from datetime import timedelta

    from models.db import Report

    owner, entity = shop
    with app.app_context():
        for back, total in ((1, 400), (3, 250)):
            db.session.add(Report(entity_id=entity.id, transaction_date=D3 - timedelta(days=back), status="submitted",
                                  created_by=owner.id, total_sales=total, opening_balance=0))
        db.session.commit()
    _ready(app, db, entity, owner, total_sales=500)

    sales = _close(app, client, owner, entity).get_json()["sales"]

    assert sales["yesterday_total"] == 400
    totals = {h["date"]: h["total"] for h in sales["history"]}
    assert totals[F.iso(D3 - timedelta(days=1))] == 400 and totals[F.iso(D3 - timedelta(days=3))] == 250
    assert totals[F.iso(D3)] == 500 and totals[F.iso(D3 - timedelta(days=2))] == 0


def test_the_close_read_says_what_would_stop_the_submit(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    _ready(app, db, entity, owner, bank_deposit=90)  # changed after the count

    body = _close(app, client, owner, entity).get_json()

    assert body["problem"] == {"error": "The figures changed after the cash count. Check the cash count again, then submit.",
                               "to": "cash_count"}


def test_no_draft_is_a_409_to_opening_and_a_submitted_day_names_its_report(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    resp = _close(app, client, owner, entity)
    assert resp.status_code == 409 and resp.get_json()["to"] == "opening"

    report = _ready(app, db, entity, owner)
    _submit(app, client, owner, entity)
    again = _close(app, client, owner, entity)
    assert again.status_code == 409
    assert again.get_json() == {"error": "This day is already submitted.", "to": "submitted", "report_id": report}


# --- the submit --------------------------------------------------------------------------------------


def test_submitting_posts_the_day(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _ready(app, db, entity, owner)

    resp = _submit(app, client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["report_id"] == report and body["status"] == "submitted" and body["next"] == "submitted"
    assert body["closing_balance"] == 55 and body["submitted_at"]
    assert _row(app, report)["status"] == "submitted"


def test_a_refused_submit_names_the_step_and_writes_nothing(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _ready(app, db, entity, owner, completed_sections=["opening", "sales", "expenses", "deposit"])

    resp = _submit(app, client, owner, entity)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Finish Cash Count before you submit the day.", "to": "cash_count"}
    assert _row(app, report)["status"] == "draft"


def test_a_second_submit_is_told_the_day_is_already_submitted(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _ready(app, db, entity, owner)
    _submit(app, client, owner, entity)

    resp = _submit(app, client, owner, entity)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "This day is already submitted.", "to": "submitted", "report_id": report}


def test_the_submit_refuses_a_bad_date_and_a_member_without_the_right(app, client, db, shop):  # noqa: F811
    from models.db import UserEntity

    owner, entity = shop
    _ready(app, db, entity, owner)
    bad = client.post(f"{_base(entity)}/submit", json={"transaction_date": "15/10/2026"}, headers=_headers(app, owner))
    assert bad.status_code == 422
    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    assert _submit(app, client, base, entity).status_code == 403
    assert _close(app, client, base, entity).status_code == 403


# --- the outcome -------------------------------------------------------------------------------------


def test_the_outcome_says_what_was_counted_and_what_happens_next(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _ready(app, db, entity, owner, counts={50: 1}, discrepancy_amount=-5, discrepancy_type="short",
                    discrepancy_reason="Change")
    _submit(app, client, owner, entity)

    resp = client.get(f"{_base(entity)}/{report}/outcome", headers=_headers(app, owner))

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["report_id"] == report and body["submitted"] is True and body["status"] == "submitted"
    assert body["cash_counted"] == 50
    assert body["difference"] == {"amount": -5, "kind": "short", "has_reason": True}
    assert body["xero"]["xero_integrated"] is False and body["xero"]["was_published"] is False
    assert body["next_day"] == (D3.fromordinal(D3.toordinal() + 1)).isoformat()
    assert body["company_name"] == "Acme Shop" and body["submitted_at"]


def test_the_outcome_of_another_companys_or_an_unknown_report_is_404(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    assert client.get(f"{_base(entity)}/{uuid.uuid4()}/outcome", headers=_headers(app, owner)).status_code == 404
    assert client.get(f"{_base(entity)}/not-a-uuid/outcome", headers=_headers(app, owner)).status_code == 404
