"""The Petty Cash API's report routes (``blueprints/petty_cash_api/routes/report.py``): the Daily Report,
reopen, delete and the share link, through ``report/services/report_actions.py`` (pinned by
tests/test_report_actions_state.py). The door is tests/test_petty_cash_api_door.py's.
"""
from __future__ import annotations

import uuid

import char_factories as F
import pytest
from test_report_actions_state import _older, _set, _submitted  # noqa: F401
from test_report_submit_state import D3, _ready, _row, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"


def _headers(app, who):
    return F.petty_cash_headers(app, who.id, origin=WEB)


def _url(entity, report_id, tail=""):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/{report_id}{tail}"


# --- the Daily Report --------------------------------------------------------------------------------


def test_the_daily_report_brings_the_day_and_what_may_be_done(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = client.get(_url(entity, report), headers=_headers(app, owner))

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["report_id"] == report and body["transaction_date"] == F.iso(D3)
    assert (body["status"], body["status_label"], body["status_tone"]) == ("submitted", "Submitted", "info")
    assert body["is_latest"] is True and body["was_published"] is False
    assert body["kpis"] == {"total_sales": 0, "total_expenses": 15, "cash_position": 55}
    assert body["expenses"]["total"] == 15 and body["expenses"]["lines"][0]["item"] == "Advertising"
    assert body["cash"]["expected"] == 55 and body["cash"]["counted"] == 55
    assert body["cash"]["difference"] == {"amount": 0, "kind": "none", "reason": ""}
    assert body["closing_balance"] == 55 and body["submitted_at"]
    assert body["permissions"] == {"edit": True, "delete": True, "publish": True, "share": True, "edit_details": True}
    assert body["options"] == {"suppliers": [], "accounts": []}


def test_the_daily_report_compares_with_the_day_before_as_close_does(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    _set(app, older, total_sales=40)
    report = _submitted(app, client, db, entity, owner)

    sales = client.get(_url(entity, report), headers=_headers(app, owner)).get_json()["sales"]

    assert sales["yesterday_total"] == 40
    assert len(sales["history"]) == 30 and sales["history"][-1] == {"date": F.iso(D3), "total": 0}
    assert {"date": sales["history"][-2]["date"], "total": 40} == sales["history"][-2]


def test_an_older_report_can_be_read_but_not_edited_or_deleted(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    _submitted(app, client, db, entity, owner)

    body = client.get(_url(entity, older), headers=_headers(app, owner)).get_json()

    assert body["is_latest"] is False
    assert body["permissions"]["edit"] is False and body["permissions"]["delete"] is False


def test_a_report_in_xero_says_so(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")

    body = client.get(_url(entity, report), headers=_headers(app, owner)).get_json()

    assert (body["status_label"], body["status_tone"]) == ("Published to Xero", "success")
    assert body["was_published"] is True


def test_a_method_switched_off_since_still_shows_its_amount(app, client, db, shop):  # noqa: F811
    from models.db import ReportSaleDetail, SaleInfo
    from blueprints.shared.enums import SaleType

    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    with app.app_context():
        old = SaleInfo.ensure("Old Wallet", SaleType.ELECTRONIC, value_name="oldwallet_sales")
        db.session.add(ReportSaleDetail(report_id=report, sale_id=old.id, amount=12))
        db.session.commit()

    methods = client.get(_url(entity, report), headers=_headers(app, owner)).get_json()["sales"]["methods"]

    assert {"name": "Old Wallet", "amount": 12} == {k: m[k] for m in methods if m["value_name"] == "oldwallet_sales"
                                                    for k in ("name", "amount")}


def test_another_companys_or_an_unknown_report_is_404(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    assert client.get(_url(entity, uuid.uuid4()), headers=_headers(app, owner)).status_code == 404
    assert client.get(_url(entity, "nope"), headers=_headers(app, owner)).status_code == 404
    assert client.post(_url(entity, uuid.uuid4(), "/reopen"), headers=_headers(app, owner)).status_code == 404
    assert client.delete(_url(entity, uuid.uuid4()), headers=_headers(app, owner)).status_code == 404


# --- reopen ------------------------------------------------------------------------------------------


def test_reopening_makes_the_latest_report_a_draft(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = client.post(_url(entity, report, "/reopen"), headers=_headers(app, owner))

    assert resp.status_code == 200
    assert resp.get_json() == {"report_id": report, "transaction_date": F.iso(D3), "status": "draft", "next": "opening"}
    assert _row(app, report)["status"] == "draft"


@pytest.mark.parametrize("setup, status, message", [
    ({"status": "draft"}, 409, "This report is already a draft. Carry on with the Daily Closing."),
    ({"publishing_status": "publishing"}, 409, "Xero is still publishing this report. Wait until it finishes, then edit it."),
])
def test_reopening_is_refused_for_a_draft_or_while_xero_publishes(app, client, db, shop, setup, status, message):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, **setup)

    resp = client.post(_url(entity, report, "/reopen"), headers=_headers(app, owner))

    assert resp.status_code == status and resp.get_json() == {"error": message}


# --- delete ------------------------------------------------------------------------------------------


def test_deleting_the_latest_report(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = client.delete(_url(entity, report), headers=_headers(app, owner))

    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": report, "transaction_date": F.iso(D3), "next": "dashboard"}
    assert _row(app, report) is None


def test_deleting_is_refused_for_an_older_report_or_while_xero_publishes(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    latest = _submitted(app, client, db, entity, owner)

    resp = client.delete(_url(entity, older), headers=_headers(app, owner))
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "I can only delete the most recent report, and there's a newer one after this."}

    _set(app, latest, publishing_status="publishing")
    resp = client.delete(_url(entity, latest), headers=_headers(app, owner))
    assert resp.status_code == 409
    assert _row(app, latest) is not None


def test_a_report_in_xero_can_be_deleted(app, client, db, shop):  # noqa: F811
    """The owner's rule (2026-10-15): allowed; the app warns with was_published."""
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")

    assert client.delete(_url(entity, report), headers=_headers(app, owner)).status_code == 200


# --- share link --------------------------------------------------------------------------------------


def test_a_submitted_day_gets_a_share_link_and_a_draft_does_not(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)

    resp = client.post(_url(entity, report, "/share-link"), headers=_headers(app, owner))
    assert resp.status_code == 200, resp.get_json()
    assert "/Minty_Report/" in resp.get_json()["url"]
    again = client.post(_url(entity, report, "/share-link"), headers=_headers(app, owner)).get_json()
    assert again["url"] == resp.get_json()["url"]  # the same link, renewed

    _set(app, report, status="draft")
    refused = client.post(_url(entity, report, "/share-link"), headers=_headers(app, owner))
    assert refused.status_code == 409


# --- a submitted report's details (report_edits; pinned by tests/test_report_edits_state.py) ------


def test_the_reason_and_the_withdrawal_are_edited_and_the_day_comes_back(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, xero_integrated=True, publishing_status="completed", status="published")

    resp = client.put(_url(entity, report, "/difference-reason"), json={"reason": " recounted "}, headers=_headers(app, owner))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["cash"]["difference"]["reason"] == "recounted"
    assert resp.get_json()["status_label"] == "Submitted"  # out of Xero until it is published again

    resp = client.put(_url(entity, report, "/withdrawal"), json={"withdrawal_type": "company"}, headers=_headers(app, owner))
    assert resp.status_code == 200 and resp.get_json()["cash"]["cash_addition_type"] == "company"
    bad = client.put(_url(entity, report, "/withdrawal"), json={"withdrawal_type": "bank"}, headers=_headers(app, owner))
    assert bad.status_code == 400


def test_an_older_report_s_details_may_be_edited(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    older = _older(app, db, entity, owner)
    _submitted(app, client, db, entity, owner)

    body = client.get(_url(entity, older), headers=_headers(app, owner)).get_json()
    assert body["permissions"]["edit"] is False and body["permissions"]["edit_details"] is True
    resp = client.put(_url(entity, older, "/difference-reason"), json={"reason": "late note"}, headers=_headers(app, owner))
    assert resp.status_code == 200, resp.get_json()


@pytest.mark.parametrize("fields, status, message", [
    ({"status": "draft"}, 409, "This report is still a draft. Change it in the Daily Closing."),
    ({"publishing_status": "publishing"}, 409, "Xero is still publishing this report. Wait until it finishes, then edit it."),
])
def test_a_draft_or_a_report_being_published_keeps_its_details(app, client, db, shop, fields, status, message):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    _set(app, report, **fields)

    assert client.get(_url(entity, report), headers=_headers(app, owner)).get_json()["permissions"]["edit_details"] is False
    resp = client.put(_url(entity, report, "/difference-reason"), json={"reason": "x"}, headers=_headers(app, owner))
    assert resp.status_code == status and resp.get_json() == {"error": message}


def test_an_expense_line_of_another_report_or_company_is_not_found(app, client, db, shop):  # noqa: F811
    from models.db import ShopExpense

    owner, entity = shop
    older = _older(app, db, entity, owner)
    report = _submitted(app, client, db, entity, owner)
    with app.app_context():
        line_id = str(ShopExpense.query.filter_by(report_id=report).first().id)

    assert client.patch(_url(entity, older, f"/expense-lines/{line_id}"), data={"remarks": "x"},
                        headers=_headers(app, owner)).status_code == 404
    assert client.patch(_url(entity, report, f"/expense-lines/{uuid.uuid4()}"), data={"remarks": "x"},
                        headers=_headers(app, owner)).status_code == 404
    done = client.patch(_url(entity, report, f"/expense-lines/{line_id}"), data={"remarks": "Posters"},
                        headers=_headers(app, owner))
    assert done.status_code == 200, done.get_json()
    assert done.get_json()["expenses"]["lines"][0]["remarks"] == "Posters"
    refused = client.patch(_url(entity, report, f"/expense-lines/{line_id}"), data={"account_id": "acc-elsewhere"},
                           headers=_headers(app, owner))
    assert refused.status_code == 422 and refused.get_json() == {"error": "Choose an account code from the list."}
