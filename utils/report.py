"""Report-related utility helpers."""

from __future__ import annotations

from datetime import datetime


def safe_float(value):
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def parse_nested_keys(data, prefix, existing_values=None):
    result = existing_values or {}
    for key, value in data.items():
        if key.startswith(prefix):
            subkey = key[len(prefix) + 1 : -1]
            if value:
                result[subkey] = safe_float(value)
    return result


def format_as_datetime(value, fallback=None):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return fallback
