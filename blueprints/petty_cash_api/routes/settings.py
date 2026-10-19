"""Petty Cash settings for minty-petty-cash-web: the cards that need no Xero - Country & currency
and the Electronic / Delivery sales methods - through the code Flask's settings page uses
(``entity/services/country_currency.py``, ``xero_account_mapping_post.apply_country_currency_selection``,
``entity/services/payment_methods.py``).

The Xero cards (the owner's go-ahead, 2026-10-16) - ``GET /settings/xero``,
``PUT /settings/xero/mapping``, ``PUT /settings/xero/account-codes`` - go through
``entity/services/xero_mapping.py``, the Jinja page's own: opening them checks the Xero connection
live and refreshes the lists from Xero, as the page does. Connecting to Xero stays Flask's (its
callback). A new contact for the mapping is ``POST /suppliers``.

- ``GET /settings``: the country and currency with the lists offered, the two method lists, the
  catalogue methods not on them, whether Xero is connected, and what this person may change.
- ``PUT /settings/country`` ``{country_code, currency_id}``: as the page's Country & currency Save.
- ``POST /sales-methods`` ``{type, sale_info_id | name}``, ``PUT /sales-methods/<id>`` ``{name}``,
  ``DELETE /sales-methods/<id>``, ``PUT /sales-methods/order`` ``{type, method_ids}``: as the
  page's sales-method cards.

Where Flask's JSON routes let a bad request through, these refuse it (422) with a sentence.
"""
from __future__ import annotations

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user

TYPES = ("electronic", "delivery")
NAME_MAX = 100
#: the Settings page's Save, which writes the country only with all four (routes/settings.py)
COUNTRY_RIGHTS = ("ENTITY_UPDATE", "COA_UPDATE", "COA_CREATE", "COA_DELETE")
NO_RIGHT = "You don't have permission to change these settings. Ask an Accountant or an Admin."
NOT_FOUND = "That sales method isn't on this company's list."


def _may(*names) -> bool:
    from services.permission_policy import Permission, has_permission

    return all(has_permission(user(), getattr(Permission, n), company()["id"]) for n in names)


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _methods(entity_id) -> dict:
    """The company's switched-on methods by type, in list order. ``shared``: another company has
    the method too, so a rename is refused (it would rename theirs) - the app can say so as typed."""
    from blueprints.entity.services.payment_methods import LISTABLE_TYPES, _build_method_payload, _links
    from models.db import EntitySaleSetting, db

    links = _links(entity_id, enabled_only=True, types=LISTABLE_TYPES)
    shared = {
        str(sale_id)
        for (sale_id,) in db.session.query(EntitySaleSetting.sale_id)
        .filter(EntitySaleSetting.sale_id.in_([link.sale_id for link in links]),
                EntitySaleSetting.entity_id != entity_id)
        .distinct()
    } if links else set()
    grouped = {t: [] for t in TYPES}
    for link in links:
        row = _build_method_payload(link)
        grouped[row["type"]].append({"id": str(row["id"]), "name": row["name"], "value_name": row["value_name"],
                                     "shared": str(row["id"]) in shared})
    return grouped


def _service(answer, *, ok_status=(200, 201)):
    """A payment_methods service answer as this API's: its 403/404 as our sentences, a 409 as its own."""
    body, status = answer
    if status in ok_status:
        return None
    if status == 403:
        return refuse(NO_RIGHT, 403)
    if status == 404:
        return refuse(NOT_FOUND, 404)
    if status == 409:
        return refuse(body.get("error") or "That clashes with another method.", 409)
    return refuse("The sales method couldn't be saved. Check it and try again.", 422)


def settings_payload(entity_id) -> dict:
    from blueprints.entity.services.country_currency import country_currency_choices
    from blueprints.entity.services.payment_methods import list_available_methods
    from models.db import Entity, db

    org = db.session.get(Entity, entity_id)
    countries, currencies, country, currency = country_currency_choices(org)
    may_view_sales = _may("SALES_METHOD_VIEW")
    available, status = list_available_methods(user().id, entity_id) if may_view_sales else ({}, 403)
    return {
        "country": {
            "country_code": org.country_code,
            "currency_id": str(org.currency_id) if org.currency_id else None,
            "countries": [{"code": c["country_code"], "name": c["country_name"]} for c in countries],
            "currencies": [{"id": str(c["currency_id"]), "name": c["currency_name"]} for c in currencies],
            "selected_country": country["country_name"] if country else None,
            "selected_currency": currency["currency_name"] if currency else None,
        },
        "sales_methods": _methods(entity_id) if may_view_sales else {t: [] for t in TYPES},
        "available": {t: [{"id": str(m["id"]), "name": m["name"]} for m in available.get(t, [])] for t in TYPES}
        if status == 200 else {t: [] for t in TYPES},
        "xero_connected": bool(org.xero_org_id),
        "permissions": {
            "edit_country": _may(*COUNTRY_RIGHTS),
            "view_sales_methods": may_view_sales,
            "add_sales_method": _may("SALES_METHOD_CREATE"),
            "rename_sales_method": _may("SALES_METHOD_UPDATE"),
            "remove_sales_method": _may("SALES_METHOD_DELETE"),
            "reorder_sales_methods": _may("SALES_METHOD_REORDER"),
        },
    }


@petty_cash_api_bp.get("/settings")
def settings_page():
    if not _may("COA_VIEW"):
        return refuse("You don't have permission to see these settings.", 403)
    return respond(settings_payload(company()["id"]))


@petty_cash_api_bp.put("/settings/country")
def save_country():
    from blueprints.entity.services.country_currency import checked_country_currency
    from blueprints.entity.services.xero_account_mapping_post import apply_country_currency_selection
    from loguru import logger
    from models.db import Entity, db

    if not _may(*COUNTRY_RIGHTS):
        return refuse(NO_RIGHT, 403)
    data = _body()
    if not str(data.get("country_code") or "").strip() and not str(data.get("currency_id") or "").strip():
        return refuse("Choose a country or a currency to save.", 422)
    fields, problem = checked_country_currency(data)
    if problem:
        return refuse(problem, 422)
    entity_id = company()["id"]
    try:
        apply_country_currency_selection(db.session.get(Entity, entity_id), fields)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Petty Cash API: the country and currency were not saved entity={}", entity_id)
        raise
    return respond({**settings_payload(entity_id), "message": "Country and currency saved."})


@petty_cash_api_bp.post("/sales-methods")
def add_sales_method():
    from blueprints.entity.services.payment_methods import add_payment_method
    from models.db import SaleInfo, db

    if not _may("SALES_METHOD_CREATE"):
        return refuse(NO_RIGHT, 403)
    data = _body()
    kind = data.get("type")
    if kind not in TYPES:
        return refuse("Choose Electronic or Delivery for the method.", 422)
    entity_id = company()["id"]
    if data.get("sale_info_id"):
        row = db.session.get(SaleInfo, str(data["sale_info_id"])) if _uuid(data["sale_info_id"]) else None
        if row is None or not row.enabled or getattr(row.type, "value", row.type) != kind:
            return refuse("Pick one of the methods offered, or type a new name.", 422)
        body = {"sale_info_id": str(row.id), "name": row.sale_name, "type": kind}
    else:
        name = str(data.get("name") or "").strip()
        if not name:
            return refuse("The method's name is still empty. Type a name to add it.", 422)
        if len(name) > NAME_MAX:
            return refuse(f"That name is too long. Keep it to {NAME_MAX} characters or fewer.", 422)
        body = {"name": name, "type": kind}
    if any(m["name"].casefold() == body["name"].casefold() for m in _methods(entity_id)[kind]):
        return refuse(f"{body['name']} is already on the list.", 409)
    refused = _service(add_payment_method(user().id, entity_id, body))
    if refused is not None:
        return refused
    return respond({**settings_payload(entity_id), "message": f"{body['name']} added."}, 201)


@petty_cash_api_bp.put("/sales-methods/order")
def reorder_sales_methods():
    from blueprints.entity.services.payment_methods import reorder_payment_methods

    if not _may("SALES_METHOD_REORDER"):
        return refuse(NO_RIGHT, 403)
    data = _body()
    kind = data.get("type")
    ids = data.get("method_ids")
    if kind not in TYPES or not isinstance(ids, list):
        return refuse("Send the type and the methods in their new order.", 422)
    entity_id = company()["id"]
    current = [m["id"] for m in _methods(entity_id)[kind]]
    if sorted(str(i) for i in ids) != sorted(current):
        return refuse("The list changed since it was loaded. Reload the page and order it again.", 409)
    # one type at a time, as the page's cards save it: the other type keeps its own order
    refused = _service(reorder_payment_methods(user().id, entity_id, [str(i) for i in ids]))
    if refused is not None:
        return refused
    return respond({**settings_payload(entity_id), "message": "Order saved."})


@petty_cash_api_bp.put("/sales-methods/<method_id>")
def rename_sales_method(method_id):
    from blueprints.entity.services.payment_methods import update_payment_method

    if not _may("SALES_METHOD_UPDATE"):
        return refuse(NO_RIGHT, 403)
    entity_id = company()["id"]
    if not _uuid(method_id) or not _listed(entity_id, method_id):
        return refuse(NOT_FOUND, 404)
    name = str(_body().get("name") or "").strip()
    if not name:
        return refuse("The method's name is still empty. Type a name to save it.", 422)
    if len(name) > NAME_MAX:
        return refuse(f"That name is too long. Keep it to {NAME_MAX} characters or fewer.", 422)
    refused = _service(update_payment_method(user().id, entity_id, method_id, {"name": name}))
    if refused is not None:
        return refused
    return respond({**settings_payload(entity_id), "message": "Name saved."})


@petty_cash_api_bp.delete("/sales-methods/<method_id>")
def remove_sales_method(method_id):
    from blueprints.entity.services.payment_methods import delete_payment_method

    if not _may("SALES_METHOD_DELETE"):
        return refuse(NO_RIGHT, 403)
    entity_id = company()["id"]
    if not _uuid(method_id) or not _listed(entity_id, method_id):
        return refuse(NOT_FOUND, 404)
    refused = _service(delete_payment_method(user().id, entity_id, method_id))
    if refused is not None:
        return refused
    return respond({**settings_payload(entity_id), "message": "Method removed. Reports that used it keep their amounts."})


def _listed(entity_id, method_id) -> bool:
    """Whether ``method_id`` is one of the company's Electronic / Delivery methods - Cash (and any
    other type) is managed on the report, never here."""
    return any(m["id"] == str(method_id) for t in TYPES for m in _methods(entity_id)[t])


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


# --- the Xero cards ---------------------------------------------------------------------------------

MAPPING_KEYS = ("main_bank", "deposit_bank", "cashsale_account", "cashsale_contact", "owners_account",
                "owners_contact", "discrepancy_account", "discrepancy_contact")
NOT_LIVE = "Xero isn't connected for this company. Connect it in the company's settings first."
XERO_ACTIONS = ("read", "mapping", "account-codes")


def xero_settings_answer(entity_id, person, action, body) -> tuple[dict, int]:
    """The Xero cards for ``person`` - ``read`` (``GET /settings/xero``), ``mapping``
    (``PUT /settings/xero/mapping``) or ``account-codes`` (``PUT /settings/xero/account-codes``) -
    shared with the internal route minty-petty-cash-api forwards them to
    (``xero/routes/routes.py::internal_xero_settings``): each asks Xero."""
    from flask import current_app
    from loguru import logger

    from blueprints.entity.services import xero_mapping
    from blueprints.entity.services.xero_account_mapping_post import save_mapping
    from models.db import Entity, EntityPettycashSettings, db
    from services.permission_policy import Permission, has_permission

    org = db.session.get(Entity, entity_id)
    may = all(has_permission(person, getattr(Permission, n), entity_id) for n in COUNTRY_RIGHTS)

    def payload() -> dict:
        live = xero_mapping.is_live(org, person)
        if live:
            xero_mapping.refresh_from_xero(org, person, current_app._get_current_object())
        return {
            "live": live,
            "organisation": org.xero_tenant_name if live else None,
            "mapping": xero_mapping.read(org.id, org) if live else None,
            "mapping_saved": EntityPettycashSettings.query.filter_by(entity_id=org.id).first() is not None,
            "account_codes": xero_mapping.account_codes(org.id) if live else None,
            "permissions": {"edit_mapping": may, "edit_account_codes": may},
        }

    if action == "read":
        if not has_permission(person, Permission.COA_VIEW, entity_id):
            return {"error": "You don't have permission to see these settings."}, 403
        return payload(), 200
    if not may:
        return {"error": NO_RIGHT}, 403
    if not xero_mapping.is_live(org, person):
        return {"error": NOT_LIVE}, 409
    body = body if isinstance(body, dict) else {}

    if action == "account-codes":
        codes = body.get("codes")
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            return {"error": "Send the ticked account codes as a list."}, 422
        problem = xero_mapping.save_account_codes(org, codes)
        if problem:
            return {"error": problem}, 422
        return {**payload(), "message": "Account codes saved."}, 200

    values = {key: str(body.get(key) or "").strip() for key in MAPPING_KEYS}
    labels = {key: label for key, label, *_ in xero_mapping.FIELDS}
    missing = [labels[key] for key in MAPPING_KEYS if not values[key]]
    if missing:
        return {"error": " ".join(f"Choose the {label}." for label in missing)}, 422
    if values["main_bank"] == values["deposit_bank"]:
        return {"error": "The Petty Cash Account and the Deposit Bank Account can't be the same. "
                         "Choose a different one for each."}, 422
    values["discrepancy_bank"] = values["main_bank"]  # it mirrors the Petty Cash Account, as on the page
    not_offered = xero_mapping.unoffered(org.id, org, values)
    if not_offered:
        return {"error": xero_mapping.unoffered_sentence(not_offered)}, 422
    first_save = EntityPettycashSettings.query.filter_by(entity_id=org.id).first() is None
    try:
        unresolved = save_mapping(org, values)
        if unresolved:
            db.session.rollback()
            return {"error": "Some choices haven't synced from Xero yet: " + "; ".join(unresolved)
                             + ". Try again once the Xero sync has finished."}, 409
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Petty Cash API: the Xero mapping was not saved entity={}", org.id)
        raise
    return {**payload(), "message": "Xero account mapping saved.", "first_save": first_save}, 200


@petty_cash_api_bp.get("/settings/xero")
def xero_settings():
    body, status = xero_settings_answer(company()["id"], user(), "read", None)
    return respond(body, status)


@petty_cash_api_bp.put("/settings/xero/mapping")
def save_xero_mapping():
    """``{main_bank, deposit_bank, cashsale_account, cashsale_contact, owners_account,
    owners_contact, discrepancy_account, discrepancy_contact}`` - Xero ids from ``GET``'s options."""
    body, status = xero_settings_answer(company()["id"], user(), "mapping", _body())
    return respond(body, status)


@petty_cash_api_bp.put("/settings/xero/account-codes")
def save_xero_account_codes():
    """``{codes: [..]}``: exactly these account codes ticked for Petty Cash (at least one)."""
    body, status = xero_settings_answer(company()["id"], user(), "account-codes", _body())
    return respond(body, status)
