"""The words a declined retry answers with (``entity/routes/settings.py::declined_message``) -
the same as minty-billing-api's ``api/_retry.py``: Stripe's generic "Your card was declined." is
never repeated after our own "That card was declined" (the user, 2026-09-28)."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("Your card was declined.", "That card was declined. Try a different payment method."),
        ("Your card was declined. Your request was in live mode, but used a known test card.",
         "That card was declined. Your request was in live mode, but used a known test card."),
        ("Your card has insufficient funds.",
         "That card was declined: Your card has insufficient funds."),
        ("insufficient funds", "That card was declined: insufficient funds"),
        (None, "That card was declined. Try a different payment method."),
    ],
)
def test_a_decline_never_repeats_itself(app, reason, message):
    from blueprints.entity.routes.settings import declined_message

    assert declined_message(reason) == message
