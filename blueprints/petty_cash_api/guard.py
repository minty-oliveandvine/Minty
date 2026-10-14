"""The door every Petty Cash API request goes through, before any view - and it FAILS CLOSED.

In order: the preflight; a valid MODULE token (the ``module`` claim ``_generate_module_token``
stamps - an onboarding token is for the onboarding API alone); an approved person who still
exists; a company they belong to (or any, for a superuser); a company past onboarding; Petty
Cash switched on for it. Each miss is refused. Anything that throws is the blueprint's 500
(``api._failure``) - never a pass, unlike ``report.routes.module_guard``, which lets a request
through when it cannot find the company or the check itself fails.

The token's ``entity_id`` claim is not the company: the address is, checked against
membership here on every request, so a token minted for one company opens no other.
"""
from __future__ import annotations

from flask import g, make_response, request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import refuse

NO_COMPANY = "You don't have access to that company."
ONBOARDING = "This company is still setting up. Finish setting it up to use Petty Cash."
NO_MODULE = "Petty Cash isn't switched on for this company. An admin can turn it on in the company's modules."


def _membership(user, entity_id: str) -> dict | None:
    """The company as the person may see it, or None (``profile.entity_context``: the test
    ``/handoff/minty-web`` and the hub's company tabs apply)."""
    from blueprints.user_management.services import profile

    return profile.entity_context(user, entity_id)


@petty_cash_api_bp.before_request
def guard():
    if request.method == "OPTIONS":
        return make_response("", 204)

    from blueprints.entity.routes.modules import MODULE_TOKEN_CLAIM, _is_module_enabled
    from blueprints.shared import bearer_api
    from models.db import Entity, User, db

    claims = bearer_api.claims_from_bearer()
    if not claims or claims.get("module") != MODULE_TOKEN_CLAIM or not claims.get("user_id"):
        return refuse("unauthorized", 401)
    user = db.session.get(User, str(claims["user_id"]))
    if user is None or not user.approved:
        return refuse("unauthorized", 401)

    company = _membership(user, g.petty_cash_entity_id)
    if company is None:
        return refuse(NO_COMPANY, 403)
    if db.session.get(Entity, company["id"]).status == "onboarding":
        return refuse(ONBOARDING, 409)
    if not _is_module_enabled(company["id"], "PETTY_CASH"):
        return refuse(NO_MODULE, 403)

    g.petty_cash_user = user
    g.petty_cash_company = company
    return None
