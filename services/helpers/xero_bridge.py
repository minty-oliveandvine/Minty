"""Compat helper functions extracted from legacy app for service modules."""

from __future__ import annotations

from typing import Any

import requests
from flask import current_app
from flask_login import current_user
from loguru import logger

from models.db import (AccountInfo, Entity, EntityPettycashSettings,
                       XeroContactSync)
from services.auth.token_service import (apply_refreshed_tokens,
                                         ensure_valid_token,
                                         refresh_access_token_for_user,
                                         resolve_xero_token)
from services.helpers.xero import mask_account_number


_ROLE_TO_PETTYCASH_SETTINGS_COLUMN = {
    "pettycash": "pettycash_account_id",
    "bank": "bank_account_id",
    "cash_sale": "cash_sale_account_id",
    "discrepancy": "discrepancy_bank_account_id",
    "discrepancy_account": "discrepancy_account_id",
    "director": "director_account_id",
}

_CONTACT_ROLE_TO_PETTYCASH_SETTINGS_COLUMN = {
    "cashsale_contact": "cash_sale_contact_id",
    "director_contact": "director_contact_id",
    "discrepancy_contact": "discrepancy_contact_id",
}


def get_entity_contact_settings(entity_id, contact_role):
    """Return the configured XeroContactSync row for a petty cash role.

    contact_role is one of: 'cashsale_contact', 'director_contact',
    'discrepancy_contact'. Returns the XeroContactSync ORM object or None.
    """
    column_name = _CONTACT_ROLE_TO_PETTYCASH_SETTINGS_COLUMN.get(contact_role)
    if column_name is None:
        logger.warning(
            "get_entity_contact_settings: unknown contact_role=%s entity=%s",
            contact_role, entity_id,
        )
        return None
    try:
        settings_row = EntityPettycashSettings.query.filter_by(
            entity_id=entity_id
        ).first()
        if settings_row is None:
            return None
        contact_id = getattr(settings_row, column_name)
        if not contact_id:
            return None
        return XeroContactSync.query.get(contact_id)
    except Exception as e:
        logger.error(f"Error getting entity contact settings: {str(e)}")
        return None


def resolve_contact_name(entity_id, xero_contact_id):
    """Best contact name for (entity_id, xero_contact_id) from xero_contact_sync.

    xero_contact_sync has no unique constraint, so the same (entity_id,
    xero_contact_id) pair can have duplicate rows. Pick deterministically:
    prefer the row whose xero_org_id matches the entity's current xero_org_id,
    then the longest (least-truncated) name.

    Returns the name string, or None if entity_id/xero_contact_id is missing or
    no synced row with a name exists.
    """
    if not entity_id or not xero_contact_id:
        return None
    try:
        rows = XeroContactSync.query.filter_by(
            entity_id=entity_id, xero_contact_id=xero_contact_id
        ).all()
        rows = [r for r in rows if r.name]
        if not rows:
            return None
        entity = Entity.query.get(entity_id)
        current_org = getattr(entity, "xero_org_id", None)
        rows.sort(
            key=lambda r: (r.xero_org_id == current_org, len(r.name or "")),
            reverse=True,
        )
        return rows[0].name
    except Exception as e:
        logger.error(
            "resolve_contact_name failed entity=%s xero_contact_id=%s: %s",
            entity_id, xero_contact_id, e,
        )
        return None


def get_xero_data_dynamic(
        endpoint_path,
        params=None,
        xero_org_id=None,
        entity_id=None,
        paginate=False,
        page_size=100):
    """Call a Xero endpoint with entity-aware token/tenant resolution.

    When paginate=True, fetches all pages and returns a merged response dict
    keyed by endpoint_path (e.g. "Contacts").
    """
    try:
        token_user = resolve_xero_token(entity_id, current_user)
        if token_user is None:
            return {
                "error": "Xero connection unavailable. Please reconnect.",
                "reconnect_required": True,
            }

        base_url = f"{current_app.config.get('XERO_API_BASE_URL')}/"
        endpoint = base_url + endpoint_path

        if xero_org_id:
            tenant_id = xero_org_id
        elif entity_id:
            ent = Entity.query.get(entity_id)
            tenant_id = (
                ent.xero_org_id if ent else getattr(
                    token_user, "xero_entity_id", None))
        else:
            tenant_id = getattr(token_user, "xero_entity_id", None)

        headers = {
            "Authorization": "Bearer " + token_user.access_token,
            "Accept": "application/json",
            "Xero-Tenant-Id": tenant_id,
        }

        def _do_request(request_params):
            response = requests.get(endpoint, headers=headers, params=request_params)

            if response.status_code == 401:
                response_data = response.json()
                if "TokenExpired" in str(response_data):
                    logger.warning(
                        "Token expired during API call, attempting refresh...")
                    new_tokens = refresh_access_token_for_user(token_user)
                    if new_tokens and apply_refreshed_tokens(token_user, new_tokens):
                        logger.info(
                            "Access token refreshed successfully after API call")
                        headers["Authorization"] = "Bearer " + token_user.access_token
                        response = requests.get(
                            endpoint, headers=headers, params=request_params)
                    else:
                        logger.error(
                            "Failed to refresh access token after API call")
                        return {
                            "error": "Authentication failed. Please re-authenticate with Xero."}

            return response.json()

        if not paginate:
            return _do_request(params)

        resource_key = endpoint_path
        all_items = []
        page = 1
        result = None
        while True:
            page_params = dict(params or {})
            page_params["page"] = page
            page_params["pageSize"] = page_size
            result = _do_request(page_params)

            if isinstance(result, dict) and "error" in result:
                if page == 1:
                    return result
                logger.warning(
                    "Pagination error on page %d for %s: %s",
                    page, endpoint_path, result.get("error"),
                )
                break

            page_items = result.get(resource_key, []) if isinstance(result, dict) else []
            all_items.extend(page_items)

            if len(page_items) < page_size:
                break
            page += 1

        merged: dict[str, Any] = dict(result) if isinstance(result, dict) else {}
        merged[resource_key] = all_items
        return merged
    except Exception as e:
        # Callers only test for the presence of "error", never its text, so the
        # exception detail stays in the log rather than riding out to the UI.
        logger.exception(f"Error in get_xero_data_dynamic: {str(e)}")
        return {"error": "I couldn't reach Xero just now. Mind trying again?"}


def get_entity_account_settings(entity_id, account_type):
    """Return configured Xero account mapping for entity and role."""
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

        return {
            "account_id": account.id,
            "xero_account_id": account.xero_account_id,
            "name": account.name,
            "account_code": account.xero_code or "",
            "bank_account_number": (
                mask_account_number(account.bank_account_number)
                if account_type not in ["director", "cash_sale", "discrepancy"]
                else account.bank_account_number
            ),
        }
    except Exception as e:
        logger.error(f"Error getting entity account settings: {str(e)}")
        return None


def get_accounts_from_xero(
    access_token, xero_org_id, where=None, order=None, token_validated=False
):
    try:
        if not token_validated and not ensure_valid_token(current_user):
            logger.warning("Token validation failed for accounts")
            return []

        base_url = f"{current_app.config.get('XERO_API_BASE_URL')}/Accounts"
        url = base_url
        if where:
            url += f"?where={where}"
        if order and where:
            url += f"&order={order}"
        if order and not where:
            url += f"?order={order}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }

        accounts = []
        response = requests.get(url, headers=headers)
        logger.info(f"Request URL: {url}")
        logger.info(f"Fetched accounts from Xero: {response}")

        for account in response.json().get("Accounts", []):
            if account.get("Type") == "BANK":
                account["MaskedBankAccountNumber"] = mask_account_number(
                    account.get("BankAccountNumber")
                )
            accounts.append(account)
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts from Xero: {str(e)}")
        return []


def get_contacts_from_xero(
    access_token, xero_org_id, where=None, order=None, token_validated=False
):
    try:
        if not token_validated and not ensure_valid_token(current_user):
            logger.warning("Token validation failed for contacts")
            return []

        url = f"{current_app.config.get('XERO_API_BASE_URL')}/Contacts"
        if where:
            url += f"?where={where}"
        if order and where:
            url += f"&order={order}"
        if order and not where:
            url += f"?order={order}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }
        response = requests.get(url, headers=headers)
        logger.info(f"Request URL: {url}")
        logger.info(f"Fetched contacts from Xero: {response}")
        return response.json().get("Contacts", [])
    except Exception as e:
        logger.error(f"Error fetching contacts from Xero: {str(e)}")
        return []


def account_info_to_xero_format(acc_info):
    account_dict = {
        "AccountID": acc_info.xero_account_id,
        "Name": acc_info.name,
        "Type": acc_info.type,
        "Code": acc_info.xero_code or "",
        "Status": acc_info.status or "ACTIVE",
        "Class": acc_info.class_type or "",
        "BankAccountNumber": acc_info.bank_account_number or "",
        "BankAccountType": acc_info.bank_account_type or "",
        "Description": acc_info.description or "",
    }
    if acc_info.type == "BANK" and acc_info.bank_account_number:
        account_dict["MaskedBankAccountNumber"] = mask_account_number(
            acc_info.bank_account_number
        )
    return account_dict


def contact_sync_to_xero_format(contact_sync):
    return {
        "ContactID": contact_sync.xero_contact_id,
        "Name": contact_sync.name,
    }
