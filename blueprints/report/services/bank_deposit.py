"""The day's bank deposit - the cash taken out of the drawer to the bank.

Since the Part 15 redesign the deposit is the first block of the Cash Count stage (D15-05), so
two routes write it: the old deposit step (report.report_deposit, POST only now) and the Cash
Count stage (report.report_cash_count), which saves the deposit and the count in one commit.
Both use these, so the rule and the arithmetic live once. Nothing here commits.
"""
from __future__ import annotations

from blueprints.report.services.shared import get_cash_sales_from_detail


class NegativeCashBeforeDeposit(ValueError):
    """There is less than nothing in the drawer before the deposit - fix an earlier stage first."""


def cash_before_deposit(report) -> float:
    """What the drawer holds before any deposit: opening + addition + cash sales - expenses."""
    return (
        (report.opening_balance or 0)
        + (report.cash_addition or 0)
        + (report.cash_sales or 0)
        - (report.expenses or 0)
    )


def apply_bank_deposit(report, bank_deposit, username) -> None:
    """Record the deposit and re-derive the closing balance:
    opening + cash addition + cash sales (from the sale rows) - expenses - deposit.

    Refuses (NegativeCashBeforeDeposit) when the drawer is already below zero before the deposit,
    the rule the deposit step has always enforced.
    """
    if cash_before_deposit(report) < 0:
        raise NegativeCashBeforeDeposit(report.id)
    report.uploaded_by = username
    report.bank_deposit = bank_deposit
    cash_sales = get_cash_sales_from_detail(report.id, fallback_value=report.cash_sales or 0.0)
    report.closing_balance = (
        report.opening_balance
        + (report.cash_addition or 0)
        + cash_sales
        - (report.expenses or 0)
        - report.bank_deposit
    )
