"""Shared user-identity resolution across the email-OTP and Xero login flows.

A person has two addresses we may learn about: their personal/OTP ``email`` and
their Xero ``xero_email`` (the ``email`` claim on the Xero id_token). The rule:

    same address  -> one user (a single row holds both)
    different      -> two users (two rows)

Both login flows route lookups through :func:`resolve_user_by_email` so the rule
is enforced in exactly one place, on top of the DB unique constraints on
``user.email`` and ``user.xero_email``.
"""

from sqlalchemy import func, or_

from models.db import User


def normalize_email(value: str | None) -> str | None:
    """Lowercase + trim an address. Returns ``None`` for empty input.

    Mirrors the normalization used in ``services/email_auth.py`` so OTP and Xero
    addresses compare identically.
    """
    normalized = (value or "").strip().lower()
    return normalized or None


def same_identity(email: str | None, xero_email: str | None) -> bool:
    """True iff both addresses are present and equal once normalized.

    This is the literal "are these one user?" check: the personal email and the
    Xero email belong to the same person when they match.
    """
    a = normalize_email(email)
    b = normalize_email(xero_email)
    return a is not None and a == b


def resolve_user_by_email(address: str | None) -> User | None:
    """Find the single user owning ``address`` on either identity column.

    Matches case-insensitively against ``user.email`` OR ``user.xero_email`` so
    an address learned from one flow resolves the row created by the other.
    Returns ``None`` when no user owns the address.
    """
    normalized = normalize_email(address)
    if normalized is None:
        return None
    return User.query.filter(
        or_(
            func.lower(User.email) == normalized,
            func.lower(User.xero_email) == normalized,
        )
    ).first()
