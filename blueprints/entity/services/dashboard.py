"""What the Petty Cash dashboard knows about a company - read by the Jinja page
(``entity/routes/list.py::report_dashboard``) and by the Petty Cash API's ``GET /home``
(minty-petty-cash-web's port of the same page), so the two can never disagree.

Plain values only (dates as ``date``, money as ``float``): the HTML route copies them onto the
template's ``org`` as it always did, and the API serialises them. The live Xero bank-account
read and the subscription notice stay in the HTML route - the first feeds a control the page
never shows, the second is claimed once per Flask session.
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def dashboard_state(entity_id: str) -> dict:
    from blueprints.xero.services.settings import (check_entity_xero_settings_complete,
                                                   get_entity_account_settings,
                                                   get_missing_xero_settings_fields)
    from models.db import CurrencyInfo, Entity, Report, User, db, tz

    entity_id = str(entity_id)
    org = db.session.get(Entity, entity_id)

    # Deliberately INCLUDES drafts: this drives the "latest report" summary (transaction_date /
    # closing_balance / latest_deposit), and a draft genuinely is the most recent report for
    # those purposes. Anything that means "last SUBMITTED report" filters status separately.
    latest_report = (
        Report.query.filter(Report.company == entity_id)
        .order_by(Report.transaction_date.desc())
        .first()
    )
    latest = {
        "date": None,
        "closing_balance": 0,
        "deposit": 0,
        "deposit_bank_name": "No deposit",
        "deposit_bank_number": "",
        "deposit_correction_missing_settings": [],
        "can_correct_deposit": True,
    }
    if latest_report:
        latest["date"] = latest_report.transaction_date
        latest["closing_balance"] = latest_report.closing_balance
        latest["deposit"] = latest_report.bank_deposit
        if latest_report.bank_deposit > 0:
            deposit_bank_account = get_entity_account_settings(entity_id, "bank")
            pettycash_account = get_entity_account_settings(entity_id, "pettycash")
            if deposit_bank_account:
                latest["deposit_bank_name"] = deposit_bank_account["name"]
                latest["deposit_bank_number"] = deposit_bank_account.get("bank_account_number", "****")
            else:
                latest["deposit_bank_name"] = "Unknown Bank"
                latest["deposit_bank_number"] = "****"
            # Blocks "change" / "no" in the Before You Start modal when the company is missing
            # the settings needed to reconcile a deposit correction (locally or in Xero).
            latest["deposit_correction_missing_settings"] = [
                label
                for label, present in (
                    ("Deposit Bank Account", bool(deposit_bank_account)),
                    ("Petty Cash Account", bool(pettycash_account)),
                )
                if not present
            ]
            latest["can_correct_deposit"] = not latest["deposit_correction_missing_settings"]

    # The "Continue Report" card reads the NEWEST draft.
    current_draft = (
        Report.query.filter(Report.company == entity_id, Report.status == "draft")
        .order_by(Report.transaction_date.desc())
        .first()
    )
    # The calendar uses the EARLIEST draft as its onboarding FLOOR (the earliest date a first
    # report may use): with drafts for both 29 and 30 July, a floor of the 30th made the 29th
    # unclickable even though that was the company's own opening date.
    earliest_draft_date = (
        db.session.query(db.func.min(Report.transaction_date))
        .filter(Report.company == entity_id, Report.status == "draft")
        .scalar()
    )
    draft = None
    if current_draft is not None:
        # "last edited" is updated_at (timestamptz since C4; SQLite hands it back naive)
        last_edit = current_draft.updated_at or current_draft.created_at
        if last_edit is not None and last_edit.tzinfo is None:
            last_edit = last_edit.replace(tzinfo=timezone.utc)
        draft = {
            "id": current_draft.id,
            "current_section": current_draft.current_section,
            # NULL on legacy drafts (6 of 25 in production)
            "completed_sections": current_draft.completed_sections or [],
            "last_edit_seconds": (
                int((datetime.now(timezone.utc) - last_edit).total_seconds()) if last_edit is not None else 0
            ),
        }
    draft_date = earliest_draft_date or (current_draft.transaction_date if current_draft else None)

    latest_submitter_first_name = None
    if latest_report and latest_report.uploaded_by:
        lr_user = User.query.filter_by(username=latest_report.uploaded_by).first()
        if lr_user and lr_user.first_name:
            latest_submitter_first_name = lr_user.first_name.strip()

    # PUBLISHED means submitted: `report` also holds draft-shaped rows (status='draft'), and an
    # in-progress draft is not a finished report.
    published_reports = (
        Report.query.filter(
            Report.company == entity_id,
            db.or_(Report.status.is_(None), Report.status != "draft"),
        )
        .with_entities(
            Report.transaction_date,
            Report.id,
            Report.closing_balance,
            Report.bank_deposit,
            Report.xero_integrated_yes,
            Report.uploaded_by,
        )
        .all()
    )
    uploaders = {r.uploaded_by for r in published_reports if r.uploaded_by}
    first_by_username = {}
    if uploaders:
        for u in User.query.filter(User.username.in_(uploaders)).all():
            first_by_username[u.username] = (u.first_name or "").strip() or None
    published = {
        r.transaction_date.strftime("%Y-%m-%d"): {
            "id": r.id,
            "closing_balance": r.closing_balance,
            "bank_deposit": r.bank_deposit or 0.0,
            "xero_integrated_yes": r.xero_integrated_yes,
            "submitter_first_name": first_by_username.get(r.uploaded_by),
        }
        for r in published_reports
    }

    # The server's own date, as the page always used it for "today's report is submitted".
    today = datetime.now().strftime("%Y-%m-%d")
    today_has_report = today in published
    latest_date_str = latest_report.transaction_date.strftime("%Y-%m-%d") if latest_report else None
    today_report_id = published[today]["id"] if today_has_report else None

    complete = check_entity_xero_settings_complete(entity_id)
    currency_code = None
    if org is not None and org.currency_id:
        currency = db.session.get(CurrencyInfo, org.currency_id)
        if currency and currency.currency_code:
            currency_code = currency.currency_code.strip()

    return {
        "is_new_user": latest_report is None,
        "latest": latest,
        "latest_submitter_first_name": latest_submitter_first_name,
        "draft": draft,
        "draft_date": draft_date,
        "published": published,
        "today_has_report": today_has_report,
        "today_report_id": today_report_id,
        "today_is_latest_report": today == latest_date_str,
        "has_complete_xero_settings": complete,
        "missing_settings_fields": [] if complete else get_missing_xero_settings_fields(entity_id),
        # Server-authoritative "today" in Hong Kong time: the future-date boundary for a new
        # report, whatever the device's clock or zone.
        "server_today_hk": datetime.now(tz).date().isoformat(),
        "currency_code": currency_code,
    }


def iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
