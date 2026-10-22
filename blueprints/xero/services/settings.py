"""Xero settings and connection debug routes."""

from datetime import datetime

import requests
from flask import current_app as app
from services.app_runtime.log import logger

from models.db import (AccountInfo, Entity, EntityPettycashSettings, db)
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.helpers.xero import mask_account_number


def get_account(account_id, company, xero_tenant_id, token_validated=False):
    try:
        token_user = get_xero_token_user_for_entity(company)
        if not token_validated and not ensure_valid_token(token_user):
            logger.warning("Token validation failed for account")
            return None

        url = f"{app.config['XERO_API_BASE_URL']}/Accounts/{account_id}"
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token_user.access_token}",
                "Xero-Tenant-Id": str(xero_tenant_id),
                "Accept": "application/json",
            },
        )
        logger.info(f"Fetched account {account_id} from Xero: {response}")
        account_json = response.json().get("Accounts", [])
        account = account_json[0] if account_json else None
        if account and account.get("Type") == "BANK":
            account["MaskedBankAccountNumber"] = mask_account_number(
                account.get("BankAccountNumber")
            )
        return account
    except Exception as e:
        logger.error(
            f"Error fetching account {account_id} from Xero: {str(e)}")
        return None

_ROLE_TO_PETTYCASH_SETTINGS_COLUMN = {
    "pettycash": "pettycash_account_id",
    "bank": "bank_account_id",
    "cash_sale": "cash_sale_account_id",
    "discrepancy": "discrepancy_bank_account_id",
    "discrepancy_account": "discrepancy_account_id",
    "director": "director_account_id",
}


def get_entity_account_settings(entity_id, account_type):
    """Resolve a petty cash role to its mapped Xero account.

    Roles are mapped per entity in pettycashv3.entity_pettycash_settings. Each
    role column FKs into account_info, which holds the underlying Xero account.
    The return shape matches the legacy entity_account_xero-backed lookup so
    every caller (Xero posting, reports, form rehydration) keeps working.
    """
    column_name = _ROLE_TO_PETTYCASH_SETTINGS_COLUMN.get(account_type)
    if column_name is None:
        logger.warning(
            "get_entity_account_settings: unknown account_type=%s entity=%s",
            account_type, entity_id,
        )
        return None
    try:
        settings_row = EntityPettycashSettings.query.filter_by(
            entity_id=entity_id
        ).first()
        if settings_row is None:
            return None
        account_id = getattr(settings_row, column_name)
        if not account_id:
            return None
        account = AccountInfo.query.get(account_id)
        if account is None:
            return None

        # Director / cash_sale / discrepancy callers don't need the masked bank
        # account number; everyone else (bank-shaped roles) does.
        if account_type in ("director", "cash_sale", "discrepancy"):
            return {
                "account_id": account.id,
                "xero_account_id": account.xero_account_id,
                "name": account.name,
                "account_code": account.xero_code or "",
            }
        return {
            "account_id": account.id,
            "xero_account_id": account.xero_account_id,
            "name": account.name,
            "account_code": account.xero_code or "",
            "bank_account_number": mask_account_number(
                account.bank_account_number
            ),
        }
    except Exception as e:
        logger.error(f"Error getting entity account settings: {str(e)}")
        return None

def get_contact(contact_id, company, xero_tenant_id):
    try:
        token_user = get_xero_token_user_for_entity(company)
        if ensure_valid_token(token_user):
            url = f"{app.config['XERO_API_BASE_URL']}/Contacts/{contact_id}"
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token_user.access_token}",
                    "Xero-Tenant-Id": str(xero_tenant_id),
                    "Accept": "application/json",
                },
            )
            logger.info(f"Fetched contact {contact_id} from Xero: {response}")
            return (
                response.json().get("Contacts", [])[0]
                if response.json().get("Contacts")
                else None
            )
    except Exception as e:
        logger.error(
            f"Error fetching contact {contact_id} from Xero: {str(e)}")
        return None

def _setup_summary(entity_id):
    """The company's ``entity_setup_summary`` row, or None (unknown company)."""
    from blueprints.shared.views import EntitySetupSummary

    return db.session.get(EntitySetupSummary, str(entity_id))


def check_entity_xero_settings_complete(entity_id):
    """True when all six petty-cash accounts and all three contacts are mapped.

    Read from the ``entity_setup_summary`` view - one row, not the settings row plus a count
    in Python. Logs and answers False on any error, as the dashboard and the publish guard
    have always relied on.
    """
    try:
        row = _setup_summary(entity_id)
        if row is None:
            logger.info(f"Entity {entity_id} has no entity_setup_summary row")
            return False
        is_complete = (
            row.pettycash_accounts_set >= row.pettycash_accounts_total
            and row.pettycash_contacts_set >= row.pettycash_contacts_total
        )
        logger.info(
            f"Entity {entity_id} Xero settings check: "
            f"accounts={row.pettycash_accounts_set}/{row.pettycash_accounts_total}, "
            f"contacts={row.pettycash_contacts_set}/{row.pettycash_contacts_total}, "
            f"complete={is_complete}"
        )
        return is_complete
    except Exception as e:
        logger.error(f"Error checking entity Xero settings: {str(e)}")
        return False

def get_missing_xero_settings_fields(entity_id):
    """Labels of the account and contact slots not mapped yet, in the dashboard's order.

    All nine slots (``blueprints/shared/views.PETTYCASH_SLOTS``) - the discrepancy bank
    account was missing until 2026-10-13, so a company lacking only it saw "Setup Required"
    with nothing named.
    """
    from blueprints.shared.views import PETTYCASH_SLOTS

    try:
        row = _setup_summary(entity_id)
        missing_fields = (
            [label for _, label in PETTYCASH_SLOTS] if row is None else row.missing_pettycash_slots
        )
        logger.info(f"Entity {entity_id} missing settings: {missing_fields}")
        return missing_fields
    except Exception as e:
        logger.error(f"Error getting missing Xero settings fields: {str(e)}")
        return []

def sync_entity_xero_status(entity_id, token_validated=False):
    """Synchronize connection status for an entity from Xero connections endpoint."""
    try:
        entity = Entity.query.get_or_404(entity_id)
        token_user = get_xero_token_user_for_entity(entity_id)
        if not token_validated and not ensure_valid_token(token_user):
            logger.warning(
                f"Invalid token for entity status sync: {entity_id}, preserving existing status"
            )
            return False

        get_conn_response = requests.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {token_user.access_token}"},
        )

        if get_conn_response.status_code != 200:
            logger.warning(
                f"Failed to get Xero connections for status sync: {get_conn_response.status_code}, preserving existing status"
            )
            return False

        connections = get_conn_response.json()
        is_connected_in_xero = any(
            conn.get("tenantId") == str(
                entity.xero_org_id) for conn in connections)

        if is_connected_in_xero:
            if entity.status != "connected":
                entity.status = "connected"
                entity.last_connected_at = datetime.now()
                db.session.commit()
                logger.info(
                    f"Updated entity {entity_id} status to 'connected' (was out of sync)"
                )
                return True
        else:
            # The entity's own token user has a valid token (token_user is the
            # user whose Xero account holds this entity's connection), yet the
            # tenant is absent from Xero's /connections response. That means the
            # connection was revoked on the Xero side, so flip to disconnected.
            if entity.status != "disconnected":
                entity.status = "disconnected"
                db.session.commit()
                logger.info(
                    f"Updated entity {entity_id} status to 'disconnected' "
                    f"(tenant {entity.xero_org_id} no longer in Xero connections)"
                )
                return True
            logger.info(
                f"Entity {entity_id} already 'disconnected' (tenant {entity.xero_org_id} not in Xero connections)"
            )
            return False

        logger.info(f"Entity {entity_id} status is already in sync")
        return False
    except Exception as e:
        logger.error(f"Error syncing entity status: {str(e)}")
        db.session.rollback()
        return False

