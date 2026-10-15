"""Formatting helpers for template and report rendering."""


def comma_format(value, decimals=2):
    """Format a numeric value with comma separators."""
    if value is None:
        return "0.00"
    try:
        return "{:,.{}f}".format(float(value), decimals)
    except (ValueError, TypeError):
        return str(value)


def money(value, code="$"):
    """An amount as the redesigned Petty Cash pages write it: the currency's ISO code, a space,
    then the amount grouped with two decimals - "HKD 4,800.00", "HKD -20.00" (the user's choice,
    2026-10-14, as minty-payment-request-web's ``formatMoney``). ``code`` is what the
    ``currency_symbol`` global gives ("$" when the company names no currency). Empty for no value,
    so a template decides what a missing amount reads as. Decimal, never float, so 0.1 + 0.2
    style drift can't reach the page.
    """
    from decimal import Decimal, InvalidOperation

    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"money(): not an amount: {value!r}")
    if amount == 0:
        amount = abs(amount)  # never "-0.00"
    label = (code or "").strip()
    text = f"{amount:,.2f}"
    return f"{label} {text}" if label else text


def day(value, weekday=True):
    """A date as Part 15 writes it: "Sun 4 Oct 2026" (D MMM YYYY, the weekday first by default)."""
    if value is None:
        return ""
    text = f"{value.day} {value:%b %Y}"
    return f"{value:%a} {text}" if weekday else text


def clock(value):
    """A time as the pages write it: "6:02 pm"."""
    if value is None:
        return ""
    return f"{value.hour % 12 or 12}:{value:%M} {'am' if value.hour < 12 else 'pm'}"
