"""Formatting helpers for template and report rendering."""


def comma_format(value, decimals=2):
    """Format a numeric value with comma separators."""
    if value is None:
        return "0.00"
    try:
        return "{:,.{}f}".format(float(value), decimals)
    except (ValueError, TypeError):
        return str(value)
