"""Submitting the day: the last step of the report wizard - shared by the Jinja Close page's POST
(``report/services/ending.py::report_ending``) and the Petty Cash API's ``POST /reports/submit``
(minty-petty-cash-web's port), so the two cannot disagree.

Extracted 2026-10-15 under ``tests/test_report_submit_state.py`` (characterisation, green before and
after). Flask's rules are kept: every step done; the day not in the future (Hong Kong); the expected
cash not below zero; the closing balance = opening + addition + cash sales - expenses - deposit +
the difference (so it is what was counted); the submitter becomes the report's creator and its
date is stamped now; the company's cash in stock follows the submitted count.

Changed on the way out, deliberately:
- **Nothing is ever deleted.** A failure rolls back and leaves the draft as it was - Flask's
  clean-up deleted a day with no expense lines (with lines, its delete failed silently instead).
- **A difference that no longer matches the count is refused** (the owner, 2026-10-15): a Deposit,
  Sales or Expenses change after the count made Flask submit the old difference, so the closing
  and Xero were wrong. The person is sent back to Cash Count.
- **A difference needs its reason** at submit too (the owner's rule of 2026-10-15).
- An expense line with no item or no amount is refused with the step to fix, not a crash.
- One commit, under a row lock, and a second submit is told the day is already submitted.
- A report reopened after it was in Xero is no longer marked "Published to Xero" once resubmitted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import lazyload
from sqlalchemy.orm.attributes import flag_modified

from blueprints.shared.column_types import cents

REQUIRED = ("opening", "sales", "expenses", "deposit", "cash_count")
#: Where each unfinished step is fixed (the Part 15 stage names; Deposit is Cash Count's first block).
STEP_NAMES = {"opening": "Addition to Drawer", "sales": "Sales", "expenses": "Expenses",
              "deposit": "Cash Count", "cash_count": "Cash Count"}


class SubmitRefused(Exception):
    """A submit the rules refuse: the sentence to show and ``to``, the step that fixes it
    (``opening`` / ``sales`` / ``expenses`` / ``cash_count`` / ``submitted`` / ``dashboard``)."""

    def __init__(self, message: str, to: str):
        super().__init__(message)
        self.message = message
        self.to = to


def counted_now(report) -> tuple[float, float]:
    """``(counted in the drawer + safebox, the difference that count makes against the expected
    cash NOW)`` - the till from its report_cash_count rows (``Report.actual_cash_total``)."""
    from blueprints.report.services.cash import difference

    till = float(report.actual_cash_total or 0)
    safe_box = float(report.safe_box_balance or 0)
    return cents(till + safe_box), difference(report, till, safe_box)


def closing_at_submit(report) -> float:
    """opening + addition + cash sales (the sale rows) - expenses - deposit + the difference."""
    from blueprints.report.services.shared import get_cash_sales_from_detail

    return cents(
        (report.opening_balance or 0)
        + (report.cash_addition or 0)
        + get_cash_sales_from_detail(report.id, fallback_value=report.cash_sales or 0.0)
        - (report.expenses or 0)
        - (report.bank_deposit or 0)
        + (report.discrepancy_amount or 0)
    )


def _check(report):
    from blueprints.report.services.cash import expected_cash
    from blueprints.report.services.shared import future_date_error
    from blueprints.shared.enums import ReportStatus
    from models.db import ShopExpense

    if str(getattr(report.status, "value", report.status)) != ReportStatus.DRAFT.value:
        raise SubmitRefused("This day is already submitted.", "submitted")
    done = set(report.completed_sections or [])
    missing = [s for s in REQUIRED if s not in done]
    if missing:
        first = missing[0]
        raise SubmitRefused(f"Finish {STEP_NAMES[first]} before you submit the day.",
                            "cash_count" if first == "deposit" else first)
    problem = future_date_error(report.transaction_date)
    if problem:
        raise SubmitRefused(problem, "dashboard")
    if expected_cash(report) < 0:
        raise SubmitRefused("Hmm, it looks like your cash balance is negative. Could you fix that first?",
                            "cash_count")
    for line in ShopExpense.query.filter(ShopExpense.report_id == report.id).all():
        if not (line.item or "").strip() or not line.amount or line.amount <= 0:
            raise SubmitRefused("An expense has no account or no amount. Fix it in Expenses, then submit.",
                                "expenses")
    _, now = counted_now(report)
    if cents(now) != cents(report.discrepancy_amount or 0):
        raise SubmitRefused(
            "The figures changed after the cash count. Check the cash count again, then submit.", "cash_count"
        )
    if cents(now) != 0 and not (report.discrepancy_reason or "").strip():
        raise SubmitRefused("The count has a difference with no reason. Add the reason in Cash Count.",
                            "cash_count")


def submit_report(report, user):
    """Post the day. Refused (``SubmitRefused``, nothing written) when a rule says no; any other
    failure rolls back and is raised - the draft stays as it was. One commit. Returns the report."""
    from blueprints.report.services.cash_denominations import refresh_cash_stock
    from blueprints.shared.enums import ReportStatus
    from models.db import Report, db, tz

    # The row only: Report eager-joins its creator, and Postgres can't lock an outer join's
    # nullable side - so the joins are not loaded here and the lock names the report alone.
    locked = (
        db.session.query(Report)
        .options(lazyload("*"))
        .filter(Report.id == report.id)
        .populate_existing()
        .with_for_update(of=Report)
        .one()
    )
    try:
        _check(locked)
        locked.closing_balance = closing_at_submit(locked)
        locked.date = datetime.now(tz)
        locked.uploaded_by = user.username
        sections = [s for s in (locked.completed_sections or []) if s not in ("ending", "submitted")]
        locked.completed_sections = sections + ["ending", "submitted"]
        flag_modified(locked, "completed_sections")
        locked.current_section = "submitted"
        locked.status = ReportStatus.SUBMITTED
        # A report reopened after it was in Xero no longer matches what Xero holds: it is not
        # "Published to Xero" any more. publishing_status / published_at stay - the record that it
        # went there, which is what makes the outcome page offer "Publish to Xero again".
        locked.xero_integrated = False
        locked.submitted_at = datetime.now(timezone.utc)
        db.session.flush()
        refresh_cash_stock(locked.company)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    logger.info(f"Report {locked.id} submitted: closing {locked.closing_balance}")
    return locked


def submit_problem(report) -> SubmitRefused | None:
    """What would stop the day being submitted right now (the Close page shows it before Submit),
    or None. Reads only."""
    try:
        _check(report)
    except SubmitRefused as refused:
        return refused
    return None
