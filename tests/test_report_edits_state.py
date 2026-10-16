"""Editing a SUBMITTED report without touching its balances - the Daily Report's three edits
(``report/routes/api.py``: ``/report/<id>/edit/discrepancy-reason``, ``/report/<id>/edit/withdrawal``
and ``/report/expense/edit/<expense id>``) - before the logic moves into a service that the Jinja
pages and the Petty Cash API share (``report/services/report_edits.py``).

Characterisation, green before and after the extraction; tests marked FIXED pin what it changed
deliberately (they failed before it).
"""
from __future__ import annotations

import io

import char_factories as F
import pytest
from test_report_expenses_state import D3, _draft, _lines, db, s3, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _submitted(app, db, entity, owner, **fields):  # noqa: F811
    """A submitted day with one expense line (Advertising, ABC Supplies, 12.50, one receipt)."""
    from models.db import ShopExpense

    values = {"status": "submitted", "current_section": "submitted",
              "completed_sections": ["opening", "sales", "expenses", "deposit", "cash_count", "ending", "submitted"]}
    values.update(fields)
    report_id = _draft(app, db, entity, owner, **values)
    with app.app_context():
        line = ShopExpense(report_id=report_id, item="Advertising", amount=12.5, remarks="Flyers",
                           contact_id="con-0001", contact_name="ABC Supplies", account_id="acc-0001",
                           account_code="400")
        line.add_receipt(f"expenses/{report_id}/OLD_RECEIPT.png", original_name="old.png", mime_type="image/png")
        db.session.add(line)
        db.session.commit()
        return report_id, str(line.id)


def _report(app, report_id):
    from models.db import Report, db as _db

    with app.app_context():
        row = _db.session.get(Report, report_id)
        return {"reason": row.discrepancy_reason, "withdrawal": getattr(row.cash_addition_type, "value", row.cash_addition_type),
                "status": getattr(row.status, "value", row.status), "in_xero": row.xero_integrated}


def _reason(client, owner, report_id, reason):
    F.login(client, owner)
    return client.post(f"/report/{report_id}/edit/discrepancy-reason", data={"discrepancy_reason": reason})


def _withdrawal(client, owner, report_id, kind):
    F.login(client, owner)
    return client.post(f"/report/{report_id}/edit/withdrawal", data={"withdrawal_type": kind})


def _edit_line(client, owner, line_id, **form):
    F.login(client, owner)
    files = form.pop("files", None)
    data = dict(form)
    if files:
        for i, (name, body) in enumerate(files):
            data[f"files[0][{i}]"] = (io.BytesIO(body), name)
    return client.post(f"/report/expense/edit/{line_id}", data=data, content_type="multipart/form-data")


# --- the difference reason ----------------------------------------------------------------------


def test_the_reason_is_saved_and_the_report_leaves_xero(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, discrepancy_amount=-5, discrepancy_type="short",
                              discrepancy_reason="old", xero_integrated=True, publishing_status="completed",
                              status="published")

    resp = _reason(client, owner, report_id, "  recounted  ")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["discrepancy_reason"] == "recounted"
    assert _report(app, report_id) == {"reason": "recounted", "withdrawal": None, "status": "submitted", "in_xero": False}


def test_no_difference_may_have_no_reason(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, discrepancy_reason="note")
    assert _reason(client, owner, report_id, "").status_code == 200
    assert _report(app, report_id)["reason"] == ""


def test_fixed_a_difference_keeps_a_reason(app, client, db, shop):  # noqa: F811
    """FIXED: an empty reason was saved on a day the cash was short - the reason Cash Count and
    the submit both require."""
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, discrepancy_amount=-5, discrepancy_type="short",
                              discrepancy_reason="old")

    resp = _reason(client, owner, report_id, "  ")

    assert resp.status_code == 422
    assert resp.get_json()["message"] == "The cash was short, so the reason is still needed. Add the reason to save it."
    assert _report(app, report_id)["reason"] == "old"


def test_fixed_a_long_reason_is_refused_not_cut(app, client, db, shop):  # noqa: F811
    """FIXED: it was cut to 300 characters without a word."""
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, discrepancy_reason="old")

    resp = _reason(client, owner, report_id, "x" * 301)

    assert resp.status_code == 422
    assert resp.get_json()["message"] == "Keep the reason to 300 characters or fewer."
    assert _report(app, report_id)["reason"] == "old"


# --- the withdrawal source ----------------------------------------------------------------------


def test_the_withdrawal_source_is_saved(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, cash_addition=20, cash_addition_type="personal")

    resp = _withdrawal(client, owner, report_id, "company")

    assert resp.status_code == 200, resp.get_json()
    assert _report(app, report_id)["withdrawal"] == "company"
    assert _withdrawal(client, owner, report_id, "bank").status_code == 400


# --- a submitted report's expense line ----------------------------------------------------------


def _add_account(app, db, entity, xero_id="acc-0003", code="404", name="Bank Fees"):  # noqa: F811
    import uuid

    from models.db import AccountInfo, EntityAccountXero

    with app.app_context():
        row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id=xero_id, xero_code=code,
                          name=name, type="EXPENSE", status="ACTIVE")
        db.session.add(row)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=row.id, name=name, type="EXPENSE", xero_account_id=xero_id,
                                         is_active=True))
        db.session.commit()


def test_a_line_s_details_change_and_its_amount_does_not(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report_id, line_id = _submitted(app, db, entity, owner, xero_integrated=True, publishing_status="completed")

    resp = _edit_line(client, owner, line_id, remarks="Posters", contactId="con-0002", contactName="Taxi Co")

    assert resp.status_code == 200, resp.get_json()
    line = _lines(app, report_id)[0]
    assert (line["remarks"], line["contact"], line["amount"]) == ("Posters", "Taxi Co", 12.5)
    assert _report(app, report_id)["in_xero"] is False


def test_fixed_a_new_account_renames_the_line(app, client, db, shop):  # noqa: F811
    """FIXED: a line's item is its account's name (the Expenses step), but a new account kept the
    old name."""
    owner, entity = shop
    _add_account(app, db, entity)
    report_id, line_id = _submitted(app, db, entity, owner)

    resp = _edit_line(client, owner, line_id, accountId="acc-0003", account_code="404")

    assert resp.status_code == 200, resp.get_json()
    assert (_lines(app, report_id)[0]["item"], _lines(app, report_id)[0]["account"]) == ("Bank Fees", "404")


@pytest.mark.parametrize("form, message", [
    ({"accountId": "acc-elsewhere"}, "Choose an account code from the list."),
    ({"accountId": "acc-0002"}, "Choose an account code from the list."),  # switched off for Petty Cash
    ({"contactId": "con-elsewhere", "contactName": "Someone"}, "Choose a supplier from the list."),
])
def test_fixed_an_account_or_supplier_must_be_the_company_s(app, client, db, shop, form, message):  # noqa: F811
    """FIXED: any id the browser sent was stored."""
    owner, entity = shop
    report_id, line_id = _submitted(app, db, entity, owner)

    resp = _edit_line(client, owner, line_id, **form)

    assert resp.status_code == 422 and resp.get_json()["message"] == message
    assert _lines(app, report_id)[0]["account"] == "400" and _lines(app, report_id)[0]["contact"] == "ABC Supplies"


def test_fixed_a_new_receipt_is_checked_and_the_old_file_goes(app, client, db, shop, s3):  # noqa: F811
    """FIXED: the new file skipped the Expenses step's checks, and the replaced one stayed in the
    bucket with nothing pointing at it."""
    owner, entity = shop
    report_id, line_id = _submitted(app, db, entity, owner)
    old = f"expenses/{report_id}/OLD_RECEIPT.png"
    s3.objects[old] = PNG

    refused = _edit_line(client, owner, line_id, files=[("notes.txt", b"just text")])
    assert refused.status_code == 422 and refused.get_json()["message"] == "Attach a PDF, JPEG or PNG file."
    assert _lines(app, report_id)[0]["keys"] == [old]

    done = _edit_line(client, owner, line_id, files=[("new.png", PNG)])
    assert done.status_code == 200, done.get_json()
    keys = _lines(app, report_id)[0]["keys"]
    assert keys != [old] and keys[0] in s3.objects
    assert old not in s3.objects


# --- what may be edited -------------------------------------------------------------------------


@pytest.mark.parametrize("fields, message", [
    ({"status": "draft"}, "This report is still a draft. Change it in the Daily Closing."),
    ({"publishing_status": "publishing"}, "Xero is still publishing this report. Wait until it finishes, then edit it."),
])
def test_fixed_a_draft_or_a_report_being_published_is_not_edited_here(app, client, db, shop, fields, message):  # noqa: F811
    """FIXED: the three edits took any report - a draft (whose reason Cash Count owns) or one the
    publish worker was sending to Xero."""
    owner, entity = shop
    report_id, line_id = _submitted(app, db, entity, owner, discrepancy_reason="old", **fields)

    for resp in (_reason(client, owner, report_id, "new"), _withdrawal(client, owner, report_id, "company"),
                 _edit_line(client, owner, line_id, remarks="Posters")):
        assert resp.status_code == 409 and resp.get_json()["message"] == message
    assert _report(app, report_id)["reason"] == "old" and _lines(app, report_id)[0]["remarks"] == "Flyers"


def test_someone_without_the_right_is_refused(app, client, db, shop):  # noqa: F811
    from models.db import UserEntity

    owner, entity = shop
    report_id, line_id = _submitted(app, db, entity, owner)
    with app.app_context():
        viewer = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=viewer.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()

    assert _reason(client, viewer, report_id, "new").status_code == 403
    assert _edit_line(client, viewer, line_id, remarks="Posters").status_code == 403
