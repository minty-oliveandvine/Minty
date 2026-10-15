"""Adding a supplier: a new contact in the company's Xero organisation, AND its synced row
(``xero_contact_sync``) - shared by ``POST /entity/contact/create`` (the Expenses page's "+ Add as a
new contact" and the Xero mapping pages) and the Petty Cash API's ``POST /suppliers``.

Moved out of the route 2026-10-14. The route used to skip the synced row on the grounds that the
expense line kept the supplier's name; it no longer does - a line points at a synced row, and an id
with no row is stored as NO supplier - so a supplier added from the Expenses page was dropped
silently from the very line it was added for. The row is written now.
"""
from __future__ import annotations

import requests
from loguru import logger

XERO_CONTACTS = "https://api.xero.com/api.xro/2.0/Contacts"
NOT_CONNECTED = "This entity isn't connected to Xero yet. Could you ask an admin to connect it?"
NO_ENTRY = "Xero wouldn't let me in. Could you ask an admin to reconnect it?"
NOT_ADDED = "I couldn't add that contact to Xero. Mind trying again?"
NO_ID = "Xero didn't tell me which contact it created. Mind trying again?"
#: ``xero_contact_sync.name``
MAX_NAME = 150


class SupplierRefused(Exception):
    """A supplier that could not be added, with the sentence to show and the status to answer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def create_supplier(entity_id, name: str):
    """Create ``name`` as a contact in the company's Xero organisation and store its synced row
    (found again by its Xero id if one exists). Returns the ``XeroContactSync`` row, committed."""
    from models.db import Entity, XeroContactSync, db
    from services.auth.token_service import (auto_refresh_token, ensure_valid_token,
                                             get_xero_token_user_for_entity)

    entity = db.session.get(Entity, entity_id)
    if entity is None or not entity.xero_org_id:
        raise SupplierRefused(NOT_CONNECTED)
    xero_user = get_xero_token_user_for_entity(entity_id)
    if not xero_user or not xero_user.access_token:
        raise SupplierRefused(NOT_CONNECTED)
    if not ensure_valid_token(xero_user):
        raise SupplierRefused(NO_ENTRY)

    payload = {"Contacts": [{"Name": name, "IsCustomer": True, "IsSupplier": False}]}

    def post():
        return requests.post(
            XERO_CONTACTS,
            headers={
                "Authorization": "Bearer " + xero_user.access_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Xero-Tenant-Id": str(entity.xero_org_id),
            },
            json=payload,
            timeout=30,
        )

    response = post()
    if response.status_code in (401, 403) and auto_refresh_token(xero_user):
        response = post()
    if response.status_code not in (200, 201):
        logger.error(f"Xero refused a new contact for entity {entity_id}: {response.status_code} {response.text[:500]}")
        raise SupplierRefused(NOT_ADDED)
    contacts = (response.json() or {}).get("Contacts") or []
    if not contacts:
        raise SupplierRefused(NOT_ADDED)
    xero_contact_id = contacts[0].get("ContactID")
    if not xero_contact_id:
        logger.error(f"Xero created a contact for entity {entity_id} without a ContactID")
        raise SupplierRefused(NO_ID)
    created_name = (contacts[0].get("Name") or name)[:MAX_NAME]

    row = XeroContactSync.query.filter_by(entity_id=entity_id, xero_contact_id=xero_contact_id).first()
    if row is None:
        row = XeroContactSync(entity_id=entity_id, xero_contact_id=xero_contact_id, xero_org_id=entity.xero_org_id,
                              name=created_name)
        db.session.add(row)
    else:
        row.name = created_name
    db.session.commit()
    logger.info(f"Supplier {xero_contact_id} added for entity {entity_id}")
    return row
