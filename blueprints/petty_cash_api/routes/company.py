"""``GET /api/petty-cash/v1/companies/<id>``: the company the app is in and who is using it -
what the app shell needs before any page (its name, the person's role there, the currency every
amount is in)."""
from __future__ import annotations

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, respond, user


def company_payload(person, context: dict) -> dict:
    from blueprints.user_management.services import profile
    from models.db import CurrencyInfo, Entity, db

    org = db.session.get(Entity, context["id"])
    currency = db.session.get(CurrencyInfo, org.currency_id) if org.currency_id else None
    return {
        "company": {
            "id": context["id"],
            "name": context["name"],
            "role": context["role"],
            "role_label": context["role_label"],
            "currency": (
                {"code": currency.currency_code.strip(), "decimal_places": currency.decimal_places}
                if currency is not None
                else None
            ),
        },
        "person": profile.profile_payload(person)["user"],
    }


@petty_cash_api_bp.get("")
def company_context():
    return respond(company_payload(user(), company()))
