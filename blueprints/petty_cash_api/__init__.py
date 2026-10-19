"""Petty Cash's bearer API: what minty-petty-cash-web reads and writes a company's petty cash
through (docs/features/petty-cash-api.md).

Every rule lives under ``/api/petty-cash/v1/companies/<entity_id>``, and the company comes from
that address and nowhere else - never the body, never the token. ``guard`` checks it on every
request before a view runs and FAILS CLOSED; ``api`` stamps CORS on every answer, refusals and
failures included. Nothing here reads the session cookie, which is why the whole blueprint is
CSRF-exempt (``services/app_runtime/legacy/bootstrap.py``; a test holds the package to it).

Flask stays this API's home until a ``minty-pettycash-api`` replaces it (modernisation plan,
Part 3 step 6); the HTML pages and these routes call the same services.
"""
from flask import Blueprint, g

petty_cash_api_bp = Blueprint(
    "petty_cash_api", __name__, url_prefix="/api/petty-cash/v1/companies/<entity_id>"
)

#: The ONE unauthenticated read beside it: a shared Daily Report (``routes/public_share.py``). A
#: blueprint of its own so ``guard`` (registered on ``petty_cash_api_bp`` alone) stays fail-closed
#: for everything else; tests/test_petty_cash_api_public_share.py pins that it holds one GET.
petty_cash_public_bp = Blueprint("petty_cash_public", __name__, url_prefix="/api/petty-cash/v1/public")


@petty_cash_api_bp.url_value_preprocessor
def _take_the_company(_endpoint, values):
    """The company in the address is the guard's business, not each view's argument."""
    g.petty_cash_entity_id = (values or {}).pop("entity_id", "")
