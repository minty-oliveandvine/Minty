"""Email addresses are English only: printable ASCII (the user's call, 2026-10-01).

The browser half is ``static/js/email_input.js`` (minty-web's ``lib/emailInput.ts`` twin): it
strips anything else as it is typed and shows ``EMAIL_ASCII_MESSAGE``. This is the half a
direct request cannot skip — every path that writes or keys on a typed address (invite, OTP
sign-in and sign-up, profile, business email, billing email) refuses one with a character
outside 0x21-0x7E, loudly, in the same words. minty-billing-api says it too
(``billing/services/billing_accounts.py`` ``EMAIL_NOT_ENGLISH``).

Why it matters server-side: ``홍길동@example.com`` or ``user@회사.com`` (an international
domain, which ``email_validator`` and the browser's ``type="email"`` both accept) is not an
address Minty can reliably mail or match, and it would be stored as typed.

Only new input is checked. Addresses already stored are not rewritten.
"""

from __future__ import annotations

from wtforms.validators import ValidationError

#: The frontends' ``EMAIL_ASCII_HINT``, word for word.
EMAIL_ASCII_MESSAGE = "Email can only contain English letters, numbers and symbols."


def is_ascii_email(value: str | None) -> bool:
    """True when every character of ``value`` (trimmed) is printable ASCII (0x21-0x7E).

    The character rule only: an empty value passes (each caller has its own "required"
    answer) and so does one that is not shaped like an address (ditto its format check).
    Whitespace inside the value fails, as no address contains any.
    """
    return all("\x21" <= ch <= "\x7e" for ch in (value or "").strip())


def ascii_email_validator(form, field) -> None:
    """WTForms validator: ``email_validator`` (behind ``Email()``) accepts IDN and SMTPUTF8
    addresses, so a form's email field needs this too."""
    if not is_ascii_email(field.data):
        raise ValidationError(EMAIL_ASCII_MESSAGE)
