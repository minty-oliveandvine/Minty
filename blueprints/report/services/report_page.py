"""Facts the Daily Report and the Close stage draw beyond the ending service's totals (Part 15.7,
15.15e): each expense line with its receipts, and the audit line (who submitted, when, Xero).

One call per page, three queries: the report, its expense lines, the submitter. Read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from blueprints.report.services.shared import normalize_expense_files
from models.db import Report, ShopExpense, User, tz


def _hk(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def report_facts(report_id) -> dict:
    report = Report.query.filter(Report.id == str(report_id)).first()
    if report is None:
        return {"expenses": [], "receipts": [], "submitted_by": None, "submitted_at": None,
                "published_at": None, "publishing_status": None, "today": datetime.now(tz).date()}
    expenses = []
    receipts = []
    for line in ShopExpense.query.filter_by(report_id=report.id).order_by(ShopExpense.created_at).all():
        files = normalize_expense_files(line.files, getattr(line, "s3_key", None))
        expenses.append({
            "id": str(line.id),
            "item": line.item,
            "contact_name": line.contact_name,
            "remarks": line.remarks,
            "amount": line.amount or 0,
            "receipts": len(files),
        })
        for f in files:
            receipts.append({"key": f["s3_key"], "name": f.get("display_name") or f["s3_key"].rsplit("/", 1)[-1],
                             "item": line.item, "amount": line.amount or 0})
    submitter = None
    if report.uploaded_by:
        user = User.query.filter_by(username=report.uploaded_by).first()
        if user:
            submitter = " ".join(p for p in ((user.first_name or "").strip(), (user.last_name or "").strip()) if p) or None
    status = getattr(report.publishing_status, "value", report.publishing_status)
    return {
        "expenses": expenses,
        "receipts": receipts,
        "submitted_by": submitter,
        "submitted_at": _hk(report.submitted_at),
        "published_at": _hk(report.published_at),
        "publishing_status": status,
        #: Hong Kong's today, for "Today's report ..." wording
        "today": datetime.now(tz).date(),
    }


# ---- the Daily Report's "Where the money came from and went" (Part 15.7: charts in brand +
# neutral only, each with a table alternative). Computed here from the finalised record, so the
# template only formats. Six tones, so neighbouring segments never share one.
CHART_TONES = 6


def _amount(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _whole_percents(amounts) -> list[int]:
    """Whole percentages of the total that add up to exactly 100 (largest remainder)."""
    total = sum(amounts)
    exact = [a * 100 / total for a in amounts]
    shares = [int(e) for e in exact]
    by_remainder = sorted(range(len(amounts)), key=lambda i: (exact[i] - shares[i], amounts[i]), reverse=True)
    for i in by_remainder[: 100 - sum(shares)]:
        shares[i] += 1
    return shares


def sales_mix(parts) -> list[dict]:
    """Segments of the stacked proportion bar: ``parts`` = [(sale, label, amount)] in the page's
    order (``sale`` is the method row the template names, ``label`` a fixed name such as "Cash").
    Methods with nothing sold are left out; the rest run largest first, each with its whole
    percentage (the set adds up to 100), its exact width and a tone 1..6."""
    kept = [(sale, label, _amount(amount)) for sale, label, amount in parts if _amount(amount) > 0]
    kept.sort(key=lambda p: p[2], reverse=True)  # stable: equal amounts keep the page's order
    if not kept:
        return []
    total = sum(a for _, _, a in kept)
    percents = _whole_percents([a for _, _, a in kept])
    return [
        {"sale": sale, "label": label, "amount": amount, "pct": pct,
         "width": float((amount * 100 / total).quantize(Decimal("0.01"))), "tone": i % CHART_TONES + 1}
        for i, ((sale, label, amount), pct) in enumerate(zip(kept, percents))
    ]


def expense_bars(lines) -> list[dict]:
    """Bar rows of the expenses by account: ``lines`` = [(account name or None, amount)], one per
    expense. Summed per account, largest first (then by name); each bar's width is its share of
    the largest, so the largest fills the track."""
    sums: dict[str, Decimal] = {}
    for name, amount in lines:
        key = name or "No account"
        sums[key] = sums.get(key, Decimal("0")) + _amount(amount)
    rows = sorted(((n, a) for n, a in sums.items() if a > 0), key=lambda r: (-r[1], r[0]))
    if not rows:
        return []
    top = rows[0][1]
    return [{"name": n, "amount": a, "width": float((a * 100 / top).quantize(Decimal("0.01")))} for n, a in rows]
