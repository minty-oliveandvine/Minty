"""Xero-specific utility helpers."""

from flask import session


def mask_account_number(account_number):
    if not account_number:
        return ""
    return f"****{str(account_number)[-4:]}"


def get_xero_response_text():
    """Return last Xero API response text stored in session."""
    return session.get("xero_response_text")
