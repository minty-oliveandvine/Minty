"""Minor-unit money helpers, keyed off ``currency_info``.

ONE place decides how many decimal places a currency has. It used to be decided in
three, and they disagreed: ``entity.services.modules`` read ``currency_info.decimal_places``
correctly, while the invoice memo (``billing._money``) and the first-charge confirm
dialog both divided by a hardcoded 100. On HKD the three agree by luck — it is a
two-decimal currency — so the split went unnoticed. On a zero-decimal currency the
module card would read 280 while the memo explaining that very charge read 2.80, and
the dialog asking the customer to authorise it read 2.80 as well.

Deliberately NOT in ``billing.py``. That module is pure arithmetic — no ORM, no clock,
no Stripe — which is what makes the money rules testable without a database. So it takes
``decimal_places`` as a plain parameter and this module is what resolves one.

The lookup is cached on the Flask application-context global ``g``, like
``clock.database_now``: per-request, thread-safe, and enough to keep a renewal that
prices many entities from re-reading one tiny table per line.
"""
from __future__ import annotations

from decimal import Decimal

from flask import g, has_app_context
from loguru import logger

# Used when the currency is unknown or unreadable. Two is right for almost every
# currency in circulation, so it keeps money rendering rather than blowing up a page —
# but it is a GUESS, so it logs. A currency missing from ``currency_info`` is a data
# problem to fix, not a condition to absorb silently.
FALLBACK_DECIMAL_PLACES = 2

_G_KEY = "_subscription_decimal_places"


def decimal_places(currency_code: str | None) -> int:
    """How many minor units make one major unit, from ``currency_info``.

    Falls back to :data:`FALLBACK_DECIMAL_PLACES` (loudly) when the code is missing,
    unknown, or the table cannot be read. Never raises: a currency lookup must not be
    the thing that breaks an invoice or a settings page.
    """
    if not currency_code:
        logger.warning("money: no currency code given; assuming 2 decimal places")
        return FALLBACK_DECIMAL_PLACES

    code = str(currency_code).strip().upper()
    cache = getattr(g, _G_KEY, None) if has_app_context() else None
    if cache is None:
        cache = {}
        if has_app_context():
            setattr(g, _G_KEY, cache)
    if code in cache:
        return cache[code]

    places = FALLBACK_DECIMAL_PLACES
    try:
        # Imported here, not at module scope: the subscription services are imported by
        # the Stripe client, and pulling the model layer in at import time drags the
        # whole entity model graph along with it (same reason as ``clock.database_now``).
        from models.db import CurrencyInfo

        row = CurrencyInfo.query.filter_by(currency_code=code).first()
        if row is None:
            logger.warning(
                "money: {} is not in currency_info; assuming {} decimal places",
                code, FALLBACK_DECIMAL_PLACES,
            )
        elif row.decimal_places is not None:
            places = int(row.decimal_places)
    except Exception:
        logger.exception(
            "money: could not read currency_info for {}; assuming {} decimal places",
            code, FALLBACK_DECIMAL_PLACES,
        )

    cache[code] = places
    return places


def to_major(amount_minor, currency_code: str | None) -> Decimal:
    """Minor units to a major-unit Decimal. HKD 28000 -> 280.00; JPY 280 -> 280."""
    if amount_minor is None:
        return Decimal("0")
    return Decimal(int(amount_minor)) / (Decimal(10) ** decimal_places(currency_code))


def format_minor(amount_minor, currency_code: str | None) -> str:
    """Minor units as a plain grouped decimal — no symbol, no currency code.

    For the invoice memo and the confirm dialog, both of which state the currency
    separately. Repeating it here invites the two disagreeing.
    """
    places = decimal_places(currency_code)
    value = abs(Decimal(int(amount_minor or 0))) / (Decimal(10) ** places)
    return f"{value:,.{places}f}"
