"""The report wizard's Opening step: what it shows and what saving it writes - shared by the Jinja
page (``report/routes/opening.py``) and the Petty Cash API (``petty_cash_api/routes/opening.py``,
minty-petty-cash-web's port), so the two cannot disagree.

Extracted 2026-10-14 under ``tests/test_report_opening_state.py`` (characterisation, green before
and after). The rules are Flask's as they were, quirks included: the opening chains off the
previous report whatever its status; a FIRST report (nothing submitted before) opens at, and is
saved at, the onboarding balance from ``entity_pettycash_settings`` and may not be dated before its
start date; a save on a draft does not recompute its closing balance; save_next moves an advanced
draft back to Sales.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm.attributes import flag_modified

NEGATIVE = "Hmm, it looks like your cash balance is negative. Could you fix that first?"


class OpeningRefused(Exception):
    """A save the rules refuse, with the sentence to show. ``to`` is where the Jinja page goes
    next: the dashboard (a date rule) or back to the Opening page (a negative balance)."""

    def __init__(self, message: str, *, to: str = "dashboard"):
        super().__init__(message)
        self.message = message
        self.to = to


def onboarding_floor_date(entity_id):
    """The earliest date a first report may use: the onboarding start date.

    Onboarding saves the date the user chose to start reporting from as
    ``entity_pettycash_settings.start_date``; it is the floor for the first report (it replaced the
    legacy "within 7 days from today" window). None when not set.
    """
    from blueprints.report.services.shared import first_report_defaults

    return first_report_defaults(entity_id)[1]


def first_report_opening(entity_id, day):
    """The onboarding balance when ``day``'s report is the company's FIRST (onboarding gave a start
    date and nothing is dated before ``day``) - read on the server, never trusted from a form - else
    None."""
    from blueprints.report.services.shared import first_report_defaults
    from models.db import Report

    onboarding_opening, onboarding_start = first_report_defaults(entity_id)
    if onboarding_start and not Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date < day,
    ).first():
        return onboarding_opening
    return None


def first_report_date_error(selected_date, today, entity_id):
    """A first report's date: never in the future, and not before the onboarding date (the opening
    draft's ``transaction_date``) when there is one. The error sentence, or None."""
    from blueprints.report.services.shared import future_date_error

    future_err = future_date_error(selected_date, today)
    if future_err:
        return future_err

    onboarding_date = onboarding_floor_date(entity_id)
    if onboarding_date and selected_date < onboarding_date:
        return f"Transaction date must be on or after your onboarding date ({onboarding_date})."
    return None


def _last_submitted(entity_id, before=None):
    from models.db import Report, db

    query = Report.query.filter(
        Report.company == entity_id,
        db.or_(Report.status.is_(None), Report.status != "draft"),
    )
    if before is not None:
        query = query.filter(Report.transaction_date < before)
    return query.order_by(Report.transaction_date.desc()).first()


def new_report_date_problem(entity_id, day):
    """The date rules a new day's report must pass (Hong Kong "today"): not in the future; after a
    submitted report, exactly the next day; before any, not before the onboarding date. The
    sentence to show, or None."""
    from blueprints.report.services.shared import future_date_error
    from models.db import tz

    today = datetime.now(tz).date()
    future_err = future_date_error(day, today)
    if future_err:
        return future_err
    last_report = _last_submitted(entity_id)
    if last_report:
        expected = last_report.transaction_date + timedelta(days=1)
        if expected > today:
            return f"Transaction date cannot be in the future. You can only create reports for dates up to {today}."
        if day != expected:
            return (
                f"Reports go one day at a time - this one needs to be {expected}, "
                f"the day after your last submitted report ({last_report.transaction_date})."
            )
        return None
    return first_report_date_error(day, today, entity_id)


def find_draft(entity_id, day, draft_id=None):
    """The draft a save writes to: the one named, else the one for (company, day)."""
    from models.db import Report

    if draft_id:
        return Report.query.filter(
            Report.id == draft_id,
            Report.company == entity_id,
            Report.status == "draft",
        ).first()
    return Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == day,
        Report.status == "draft",
    ).first()


def submitted_report_for(entity_id, day):
    from models.db import Report, db

    return Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == day,
        db.or_(Report.status.is_(None), Report.status != "draft"),
    ).first()


def opening_state(entity_id, selected_date, draft=None) -> dict:
    """What the Opening page shows for a new day's report (no report id): the day's draft when there
    is one, else what the day opens from.

    ``opening_balance`` chains off the previous report whatever its status (closing balance, else
    its counted cash), else - nothing before - the onboarding balance. ``yesterday_closing_balance``
    and ``safebox_balance`` read the last SUBMITTED report before the day when there is no draft; a
    first report shows the opening it starts from. With no ``selected_date``, the latest draft of
    the last 7 days stands in, as on the page.
    """
    from blueprints.report.services.shared import first_report_defaults
    from models.db import Report, tz

    # ``draft``: the one the caller already holds (the Jinja page opened by a draft's id).
    if draft is None and selected_date:
        draft = find_draft(entity_id, selected_date)
    if not draft and not selected_date:
        today = datetime.now(tz).date()
        draft = (
            Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date >= today - timedelta(days=7),
                Report.status == "draft",
            )
            .order_by(Report.transaction_date.desc())
            .first()
        )

    if draft:
        yesterday_report = (
            Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date < draft.transaction_date,
            )
            .order_by(Report.transaction_date.desc())
            .first()
        )
        withdrawal = draft.withdrawal_type if draft.withdrawal_type else "personal"
        return {
            "draft": draft,
            "opening_balance": draft.opening_balance or 0,
            "yesterday_closing_balance": _closing(yesterday_report),
            "safebox_balance": _safebox(yesterday_report),
            "report": {
                "adjusted_opening_balance": draft.adjusted_opening_balance or 0,
                "cash_addition": draft.cash_addition or 0,
                "withdrawal": withdrawal,
                "bank_account": "",  # the main bank account on the settings, not per report
            },
            "next_transaction_date": draft.transaction_date,
            "is_first_report": False,
            "withdrawal_type": withdrawal,
        }

    if selected_date:
        last_report = _last_submitted(entity_id, before=selected_date)
        # The opening chains off the PREVIOUS report whatever its status: a draft's closing balance
        # is exactly what the next report should open from.
        previous = (
            Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date < selected_date,
            )
            .order_by(Report.transaction_date.desc())
            .first()
        )
    else:
        last_report = previous = Report.query.filter_by(company=entity_id).order_by(Report.transaction_date.desc()).first()

    if previous is not None:
        opening_balance = 0
        if previous.closing_balance is not None:
            opening_balance = previous.closing_balance
        elif previous.actual_cash_total is not None:
            # actual_cash_total lives on `report` since r1a01 (counted cash; old rows only)
            opening_balance = previous.actual_cash_total
    else:
        # No report yet: the first one opens at the onboarding balance.
        opening_balance = first_report_defaults(entity_id)[0]

    if selected_date:
        next_transaction_date = selected_date
    else:
        # A first report defaults to the onboarding start date.
        next_transaction_date = (
            (last_report.transaction_date + timedelta(days=1)) if last_report else first_report_defaults(entity_id)[1]
        )

    is_first_report = last_report is None
    return {
        "draft": None,
        "opening_balance": opening_balance,
        # The page shows (and posts) this as the starting cash; a first report starts from the
        # opening worked out above - the onboarding one.
        "yesterday_closing_balance": (
            last_report.closing_balance
            if last_report and last_report.closing_balance is not None
            else (opening_balance if is_first_report else 0)
        ),
        "safebox_balance": _safebox(last_report),
        "report": {
            "adjusted_opening_balance": opening_balance,
            "cash_addition": 0,
            "withdrawal": "personal",
            "bank_account": "",
        },
        "next_transaction_date": next_transaction_date,
        "is_first_report": is_first_report,
        "withdrawal_type": "personal",
    }


def _closing(report):
    return report.closing_balance if report and report.closing_balance is not None else 0


def _safebox(report):
    return report.safe_box_balance if report and report.safe_box_balance is not None else 0


def starting_cash_balance(state: dict):
    """The "Starting Cash Balance" the page shows - and what it saves as the opening balance:
    yesterday's closing when there is one, else the draft's own opening (an onboarding-seeded
    amount), else 0."""
    draft = state["draft"]
    return state["yesterday_closing_balance"] or (draft.opening_balance if draft and draft.opening_balance else 0)


def save_opening(entity_id, user, transaction_date, opening_balance, cash_addition, withdrawal, action_type, existing_draft):
    """Write the Opening step: update ``existing_draft``, else reuse the day's draft, else create
    the day's draft (after the date rules). Then the withdrawal source, the progress, the history.

    Returns the draft. Raises ``OpeningRefused`` for a date rule, ``ValueError`` when the day
    already has a submitted report. The caller has checked the date format and the negative
    balance, and found ``existing_draft`` (``find_draft``).
    """
    from blueprints.report.services.history import log_history
    from blueprints.report.services.shared import update_draft_progress
    from models.db import Report, db, tz

    if existing_draft:
        # Preserve all existing data, update only the opening fields; track the last editor.
        report_draft = existing_draft
        report_draft.uploaded_by = user.username
        report_draft.opening_balance = opening_balance
        report_draft.cash_addition = cash_addition
        report_draft.adjusted_opening_balance = opening_balance + cash_addition
        report_draft.next_transaction_date = transaction_date + timedelta(days=1)
    else:
        if submitted_report_for(entity_id, transaction_date):
            raise ValueError(f"A report for {transaction_date} already exists.")
        any_draft_for_date = find_draft(entity_id, transaction_date)
        if any_draft_for_date:
            report_draft = any_draft_for_date
            report_draft.uploaded_by = user.username
            report_draft.opening_balance = opening_balance
            report_draft.cash_addition = cash_addition
            report_draft.adjusted_opening_balance = opening_balance + cash_addition
            report_draft.next_transaction_date = transaction_date + timedelta(days=1)
            report_draft.cash_addition_type = withdrawal
            if not report_draft.completed_sections:
                report_draft.completed_sections = []
            if "opening" not in report_draft.completed_sections:
                report_draft.completed_sections.append("opening")
            flag_modified(report_draft, "completed_sections")
        else:
            today = datetime.now(tz).date()
            last_report = _last_submitted(entity_id)
            if last_report:
                # After a submitted report, only the next day (consecutive days, no gaps).
                expected_date = last_report.transaction_date + timedelta(days=1)
                if expected_date > today:
                    raise OpeningRefused(
                        f"Transaction date cannot be in the future. You can only create reports for dates up to {today}."
                    )
                if transaction_date != expected_date:
                    raise OpeningRefused(
                        f"Reports go one day at a time - this one needs to be {expected_date}, "
                        f"the day after your last submitted report ({last_report.transaction_date})."
                    )
            else:
                first_err = first_report_date_error(transaction_date, today, entity_id)
                if first_err:
                    raise OpeningRefused(first_err)

            adjusted_opening_balance = opening_balance + cash_addition
            # The row IS the draft - status='draft' distinguishes it.
            report_draft = Report(
                transaction_date=transaction_date,
                next_transaction_date=transaction_date + timedelta(days=1),
                opening_balance=opening_balance,
                cash_addition=cash_addition,
                adjusted_opening_balance=adjusted_opening_balance,
                cashsale_total=0.0,
                nocashsale_total=0.0,
                total_sales=0.0,
                expense_total=0.0,
                bank_deposit=0.0,
                closing_balance=adjusted_opening_balance,
                current_section="opening",
                completed_sections=[],
                created_by=user.id,
                cash_addition_type=withdrawal,
                entity_id=entity_id,
                status="draft",
            )
        db.session.add(report_draft)
        # flush() to assign the id before anything downstream uses it.
        db.session.flush()

    db.session.commit()

    # The withdrawal source is kept for publishing to Xero; the bank account is the one on
    # entity_pettycash_settings (schema item 13), not per report.
    if withdrawal:
        report_draft.cash_addition_type = withdrawal

    update_draft_progress(report_draft, action_type, "opening", "sales")
    db.session.commit()

    log_history(
        report_id=report_draft.id,
        company=entity_id,
        user_id=user.id,
        action="created" if not existing_draft else "updated",
        field_changed="opening_entry",
        old_value="None" if not existing_draft else "previous_opening_state",
        new_value=f"Opening: {opening_balance}, Addition: {cash_addition}, Adjusted: {opening_balance + cash_addition}",
    )
    return report_draft
