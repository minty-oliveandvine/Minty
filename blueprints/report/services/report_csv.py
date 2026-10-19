"""Report history's movements CSV: one line per money movement of each submitted report in a range
(or of one report), in the columns a bank-statement import reads.

Used by the Jinja history page's Export CSV (``report.download_reports_csv``) and the Petty Cash
API's ``GET /reports/export.csv``; minty-petty-cash-api ports it byte for byte
(``petty_cash/services/report_csv.py``). Database only - no Xero call.

Per report, in this order: the cash added at the start (the owner's account when it came from the
owner, else the petty-cash account), each expense line as entered (its own account code, or
``N/A``), the cash sales, the bank deposit (the petty-cash account) and the cash difference
(negative when short). Amounts are signed as the cash moved and written as Python floats
(``300.0``, ``-25.1``) - what the pandas export wrote, kept so the file does not change.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from urllib.parse import quote

COLUMNS = ("Date", "Account Code", "Amount", "Description", "Reference", "Check Number")
#: The longest range one export covers, in days counted inclusively (a leap year).
MAX_DAYS = 366
#: Pinned: pandas wrote ``os.linesep``, so the same export differed between Windows and Linux.
LINE_END = "\n"
#: The account roles the rows book against (``entity_pettycash_settings`` columns).
_ROLES = {
    "pettycash": "pettycash_account_id",
    "director": "director_account_id",
    "cash_sale": "cash_sale_account_id",
    "discrepancy_account": "discrepancy_account_id",
}


class RangeRefused(ValueError):
    """A range the export refuses. ``reason`` is ``missing``, ``format``, ``order`` or ``too_long``;
    each caller words it its own way."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse_range(start: str | None, end: str | None) -> tuple[date, date]:
    """Both dates, ``YYYY-MM-DD``, start on or before end, at most ``MAX_DAYS`` days."""
    if not start or not end:
        raise RangeRefused("missing")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise RangeRefused("format") from None
    if first > last:
        raise RangeRefused("order")
    if (last - first).days + 1 > MAX_DAYS:
        raise RangeRefused("too_long")
    return first, last


def may_export(user, entity_id) -> bool:
    """The range spans everyone's reports, so it takes the company-wide view."""
    from services.permission_policy import Permission, has_permission

    return has_permission(user, Permission.REPORT_VIEW_ENTITY, entity_id)


def submitted_reports(entity_id, first: date, last: date) -> list:
    """The company's submitted and published reports in the range, by day. A draft is a day still
    being counted - its figures are not the books' yet."""
    from blueprints.shared.enums import ReportStatus
    from models.db import Report

    return (
        Report.query.filter(
            Report.entity_id == entity_id,
            Report.transaction_date >= first,
            Report.transaction_date <= last,
            Report.status != ReportStatus.DRAFT,
        )
        .order_by(Report.transaction_date.asc())
        .all()
    )


def _codes(entity_id) -> dict:
    """Each configured role's account code: ``""`` when the account has no code, absent when the
    role has no account."""
    from models.db import AccountInfo, EntityPettycashSettings

    settings = EntityPettycashSettings.query.filter_by(entity_id=entity_id).first()
    if settings is None:
        return {}
    ids = {role: getattr(settings, column) for role, column in _ROLES.items() if getattr(settings, column)}
    accounts = {str(a.id): a for a in AccountInfo.query.filter(AccountInfo.id.in_(list(ids.values()))).all()} if ids else {}
    return {role: accounts[str(i)].xero_code or "" for role, i in ids.items() if str(i) in accounts}


def _lines(report_ids) -> dict:
    """Each report's expense lines, as entered."""
    from models.db import ShopExpense

    out: dict[str, list] = {}
    if not report_ids:
        return out
    rows = (
        ShopExpense.query.filter(ShopExpense.report_id.in_(report_ids))
        .order_by(ShopExpense.created_at.asc(), ShopExpense.id.asc())
        .all()
    )
    for line in rows:
        out.setdefault(str(line.report_id), []).append(line)
    return out


def _amount(value) -> str:
    return str(float(value))


def _word(value) -> str:
    return str(getattr(value, "value", value))


def movements(entity_id, reports) -> list[list[str]]:
    """The CSV's rows (without the header) for ``reports``, all of ``entity_id``."""
    from blueprints.shared.enums import DiscrepancyType

    codes = _codes(entity_id)
    petty = codes.get("pettycash")
    lines = _lines([str(r.id) for r in reports])
    rows: list[list[str]] = []
    for report in reports:
        day = report.transaction_date.strftime("%Y-%m-%d")

        def row(code, amount, description, day=day):
            rows.append([day, code, _amount(amount), description, " ", " "])

        if report.cash_addition:
            from_owner = report.cash_addition_type == "personal" and "director" in codes
            row((codes["director"] if from_owner else petty) or "", report.cash_addition,
                "Cash Addition/Withdrawal From (Start)")
        for line in lines.get(str(report.id), []):
            remarks = line.remarks
            row(line.account_code or "N/A", -(line.amount or 0),
                "Expense" if remarks in ("No description", "-") else remarks or "Expense")
        if report.cashsale_total and report.cashsale_total > 0:
            row(codes.get("cash_sale", ""), report.cashsale_total, "Cash Sale (Pettycash)")
        if report.bank_deposit and report.bank_deposit > 0:
            row(petty or "", -report.bank_deposit, "Bank Deposit")
        kind, difference = report.discrepancy_type, report.discrepancy_amount
        if kind and _word(kind) != "none" and difference:
            short = DiscrepancyType.normalize(kind) == DiscrepancyType.SHORT
            row(codes.get("discrepancy_account") or "", -abs(difference) if short else abs(difference),
                f"Discrepancy ({_word(kind)})")
    return rows


def to_csv(rows) -> bytes:
    """The file: the header, then ``rows``; UTF-8 without a byte-order mark."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=LINE_END)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def range_filename(first: date, last: date) -> str:
    """The Jinja export's file name."""
    return f"reports_{first.isoformat()}_to_{last.isoformat()}.csv"


def export_disposition(company_name: str | None, first: date, last: date) -> str:
    """The API's ``Content-Disposition``: the company's address name and the range. A name with
    letters outside ASCII travels as ``filename*`` (RFC 6266), with an ASCII ``filename`` beside it."""
    from blueprints.shared.entity_ref import EMPTY_SLUG, slugify_name

    tail = f"_reports_{first.isoformat()}_to_{last.isoformat()}.csv"
    slug = slugify_name(company_name)
    if slug.isascii():
        return f"attachment; filename={slug}{tail}"
    plain = re.sub(r"-{2,}", "-", "".join(ch if ch.isascii() else "-" for ch in slug)).strip("-") or EMPTY_SLUG
    return f"attachment; filename={plain}{tail}; filename*=UTF-8''{quote(slug + tail, safe='')}"

