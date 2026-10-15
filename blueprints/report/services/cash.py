"""The report wizard's Bank Deposit and Cash Count steps: the cash on hand, the expected cash, saving
the deposit and saving the count - shared by the Jinja pages (``report/routes/deposit.py``,
``report/routes/cash_count.py``) and the Petty Cash API (``petty_cash_api/routes/cash.py``,
minty-petty-cash-web's port), so the two cannot disagree.

Extracted 2026-10-15 under ``tests/test_report_deposit_cash_count_state.py`` (characterisation,
green before and after). Flask's formulas are kept: the cash on hand is
``opening + cash_addition + cash sales - expenses`` (the stored cash-sales column, as Flask's gates
read it), the expected cash is that less the deposit, the difference is
``(counted - expected) + safebox`` (negative = short), the deposit writes the closing balance without
the difference (submit adds it), and Save & Exit on the count puts the report back on Cash Count.

The owner's rules (2026-10-15), each a deliberate change from Flask:
- a deposit above the cash on hand is refused at Deposit (Flask accepted it and blocked at Cash Count);
- any difference counts, a single cent included (Flask's check was "more than 0.01");
- Save & Next needs a reason when there is a difference (Flask asked only in the browser).
Also: quantities are whole numbers of 0 or more, a reason is at most 300 characters (a database
error in Flask), each save commits once (the count committed three times), and a report that is no
longer a draft is refused (the count's stock-refresh branch for one was unreachable).
"""
from __future__ import annotations

from blueprints.shared.column_types import cents

NEGATIVE = "Hmm, it looks like your cash balance is negative. Could you fix that first?"
NOT_A_DRAFT = "This report isn't a draft anymore, so its cash can't change here."
NO_DENOMINATIONS = (
    "I don't have any cash denominations set up for this entity yet. Please check the entity's country settings."
)
MAX_REASON = 300


class CashRefused(Exception):
    """A save the rules refuse, with the sentence to show. ``field`` names the input it is about,
    when there is one (``bank_deposit``, ``discrepancy_reason``, a denomination)."""

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


def _money(report, value: float) -> str:
    """``HKD1,234.50`` - the company's currency code, as every amount on the pages is written."""
    from models.db import CurrencyInfo, Entity, db

    entity = db.session.get(Entity, report.company)
    currency = db.session.get(CurrencyInfo, entity.currency_id) if entity is not None and entity.currency_id else None
    code = (currency.currency_code or "").strip() if currency is not None else ""
    return f"{code or '$'}{value:,.2f}"


def cash_on_hand(report) -> float:
    """The cash before the deposit: opening + addition + cash sales - expenses."""
    return cents(
        (report.opening_balance or 0)
        + (report.cash_addition or 0)
        + (report.cash_sales or 0)
        - (report.expenses or 0)
    )


def expected_cash(report) -> float:
    """What the count should come to: the cash on hand less the deposit."""
    return cents(cash_on_hand(report) - (report.bank_deposit or 0))


def difference(report, counted: float, safe_box: float) -> float:
    """``(counted - expected) + safebox``, to the cent: negative is short, positive is over."""
    return cents((counted - expected_cash(report)) + safe_box)


def difference_kind(amount: float) -> str:
    """Any cent counts (the owner, 2026-10-15)."""
    if amount < 0:
        return "short"
    if amount > 0:
        return "over"
    return "none"


def _draft_only(report):
    if report.status != "draft":
        raise CashRefused(NOT_A_DRAFT)


def _apply_deposit(report, user, amount: float, action_type: str) -> float:
    """The deposit's checks and writes, uncommitted. Returns the amount stored."""
    from blueprints.report.services.shared import get_cash_sales_from_detail, update_draft_progress

    _draft_only(report)
    on_hand = cash_on_hand(report)
    if on_hand < 0:
        raise CashRefused(NEGATIVE)
    amount = cents(amount)
    if amount < 0:
        raise CashRefused("Enter the deposit as an amount of 0 or more.", field="bank_deposit")
    if amount > on_hand:
        raise CashRefused(
            f"The deposit can't be more than the cash on hand. Enter {_money(report, on_hand)} or less.",
            field="bank_deposit",
        )
    report.uploaded_by = user.username
    report.bank_deposit = amount
    report.closing_balance = (
        (report.opening_balance or 0)
        + (report.cash_addition or 0)
        + get_cash_sales_from_detail(report.id, fallback_value=report.cash_sales or 0.0)
        - (report.expenses or 0)
        - amount
    )
    if action_type == "save_next":
        update_draft_progress(report, action_type, "deposit", "cash_count")
    return amount


def _apply_count(report, user, counts: dict, safe_box: float, reason: str, action_type: str) -> float:
    """The count's checks and writes, uncommitted. Returns the cash counted (till + safebox)."""
    from blueprints.report.services.cash_denominations import (resolve_denominations_for_entity,
                                                               save_cash_count_details)
    from blueprints.report.services.shared import update_draft_progress

    _draft_only(report)
    if expected_cash(report) < 0:
        raise CashRefused(NEGATIVE)
    denominations = resolve_denominations_for_entity(report.company)
    if not denominations:
        raise CashRefused(NO_DENOMINATIONS)
    safe_box = cents(safe_box)
    if safe_box < 0:
        raise CashRefused("Enter the safebox cash as an amount of 0 or more.", field="safe_box_balance")
    reason = (reason or "").strip()
    if len(reason) > MAX_REASON:
        raise CashRefused(f"Keep the reason to {MAX_REASON} characters or fewer.", field="discrepancy_reason")

    quantities, counted = {}, 0.0
    for denomination in denominations:
        quantity = counts.get(str(denomination.cash_id), counts.get(denomination.cash_id, 0)) or 0
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise CashRefused("Enter each count as a whole number of 0 or more.", field=str(denomination.cash_id))
        quantities[denomination.cash_id] = quantity
        counted += float(denomination.cash_value or 0) * quantity
    counted = cents(counted)

    amount = difference(report, counted, safe_box)
    kind = difference_kind(amount)
    if action_type == "save_next" and kind != "none" and not reason:
        word = "short" if kind == "short" else "over"
        raise CashRefused(
            f"The count is {_money(report, abs(amount))} {word}. Add the reason to continue.",
            field="discrepancy_reason",
        )

    report.uploaded_by = user.username
    report.discrepancy_amount = amount if kind != "none" else 0.0
    report.discrepancy_type = kind
    report.discrepancy_reason = reason
    report.safe_box_balance = safe_box
    save_cash_count_details(report.id, quantities)
    if action_type == "save_next":
        update_draft_progress(report, action_type, "cash_count", "ending")
    else:
        report.current_section = "cash_count"
    return cents(counted + safe_box)


def _log_deposit(report, user, amount):
    from blueprints.report.services.history import log_history

    log_history(report_id=report.id, company=report.company, user_id=user.id, action="updated",
                field_changed="bank_deposit", old_value="previous_deposit", new_value=f"Bank Deposit: ${amount}")


def _log_count(report, user, total):
    from blueprints.report.services.history import log_history

    log_history(report_id=report.id, company=report.company, user_id=user.id, action="added",
                field_changed="cash_count", old_value="previous_cash_count", new_value=f"Cash Count: ${total}")


def save_deposit(report, user, amount: float, action_type: str):
    """Store the day's bank deposit. Refused when the cash on hand is already negative, or when the
    deposit is more than the cash on hand. Save & Next marks Deposit done and moves the report on to
    Cash Count. Commits once; nothing is written when refused. Returns the report."""
    from models.db import db

    try:
        stored = _apply_deposit(report, user, amount, action_type)
    except CashRefused:
        db.session.rollback()
        raise
    db.session.commit()
    _log_deposit(report, user, stored)
    return report


def save_cash_count(report, user, counts: dict, safe_box: float, reason: str, action_type: str):
    """Store the day's count: ``counts`` maps each denomination's ``cash_id`` to a whole quantity of
    0 or more (a missing one is 0), ``safe_box`` the safebox cash. Works out the difference against
    the expected cash; Save & Next needs ``reason`` when there is one, and moves the report on to
    Ending; anything else puts it back on Cash Count. Commits once; nothing is written when
    refused. Returns the report."""
    from models.db import db

    try:
        total = _apply_count(report, user, counts, safe_box, reason, action_type)
    except CashRefused:
        db.session.rollback()
        raise
    db.session.commit()
    _log_count(report, user, total)
    return report


def save_deposit_and_count(report, user, deposit: float, counts: dict, safe_box: float, reason: str,
                           action_type: str):
    """Part 15's Cash Count stage: the deposit (an optional first section) and the count, in ONE
    transaction - the deposit first, since the expected cash reads it. Save & Next marks both done;
    a refusal of either leaves nothing written. Returns the report."""
    from models.db import db

    try:
        stored = _apply_deposit(report, user, deposit, action_type)
        total = _apply_count(report, user, counts, safe_box, reason, action_type)
    except CashRefused:
        db.session.rollback()
        raise
    db.session.commit()
    _log_deposit(report, user, stored)
    _log_count(report, user, total)
    return report
