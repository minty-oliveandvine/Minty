import base64
import re
from datetime import datetime

import pytz
import requests
from flask import current_app as app
from flask_login import current_user
from loguru import logger

from models.db import AccountInfo, XeroContactSync
from services.auth.token_service import ensure_valid_token
from services.helpers.xero import mask_account_number
from services.helpers.xero_bridge import (account_info_to_xero_format,
                                          contact_sync_to_xero_format)


def get_auth_token(code, state):
    # Encode client_id:client_secret to build authorization header to pass in
    # headers
    client_id_secret = f"{app.config['CLIENT_ID']}:{app.config['CLIENT_SECRET']}"
    base64_id_secret = base64.b64encode(
        client_id_secret.encode("utf-8")).decode("utf-8")
    authorization_header = f"Basic {base64_id_secret}"
    # Exchange the code for a token
    url = "https://identity.xero.com/connect/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": app.config["REDIRECT_URI"],
    }
    headers = {
        "Authorization": authorization_header,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = requests.post(url, data=payload, headers=headers)
    response = response.json()
    return response

def get_contacts_from_xero(
    access_token, xero_org_id, where=None, order=None, token_validated=False
):
    """Fetch all contacts for an org.

    Returns a list on success (``[]`` only when Xero genuinely reports zero
    contacts), or ``None`` when the fetch failed or completed only partially.

    The None/[] distinction is load-bearing: callers such as
    ``sync_contacts_if_changed`` reconcile the local contact table against this
    result, so an API failure that returned ``[]`` would be read as "this org
    has no contacts" and deactivate every local row.
    """
    try:
        if not token_validated and not ensure_valid_token(current_user):
            logger.warning("Token validation failed for contacts")
            return None

        base_url = f"{app.config['XERO_API_BASE_URL']}/Contacts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }

        all_contacts = []
        page = 1
        page_size = 1000

        while True:
            params = [f"page={page}", f"pageSize={page_size}"]
            if where:
                params.append(f"where={where}")
            if order:
                params.append(f"order={order}")
            url = base_url + "?" + "&".join(params)

            response = requests.get(url, headers=headers)
            logger.info(f"Request URL: {url}")
            logger.info(f"Fetched contacts from Xero (page {page}): {response}")

            if response.status_code != 200:
                # Discard anything already collected: a truncated list is
                # indistinguishable from contacts having been removed in Xero.
                logger.error(
                    f"Xero contacts API returned {response.status_code} on page "
                    f"{page} — discarding {len(all_contacts)} partial result(s)"
                )
                return None

            contacts = response.json().get("Contacts", [])
            if not contacts:
                break

            all_contacts.extend(contacts)

            if len(contacts) < page_size:
                break
            page += 1

        logger.info(f"Total contacts fetched from Xero: {len(all_contacts)}")
        return all_contacts
    except Exception as e:
        logger.error(f"Error fetching contacts from Xero: {str(e)}")
        return None

def get_accounts_from_xero(
    access_token, xero_org_id, where=None, order=None, token_validated=False
):
    try:
        if not token_validated and not ensure_valid_token(current_user):
            logger.warning("Token validation failed for accounts")
            return []

        url = f"{app.config['XERO_API_BASE_URL']}/Accounts"
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
                    account.get("BankAccountNumber"))
            accounts.append(account)
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts from Xero: {str(e)}")
        return []


def get_organisation_lock_dates(access_token, xero_org_id):
    """Fetch PeriodLockDate and EndOfYearLockDate from Xero Organisation API.

    Nothing in Minty stores or acts on them any more (the ``entities`` columns went with
    the schema redesign; billing-backend asks Xero itself at publish time). Kept as the
    ``accounting.settings``-scope probe ``tests/test_xero_scopes.py`` exercises.

    Returns:
        dict with keys ``period_lock_date`` and ``end_of_year_lock_date``,
        each a ``datetime.date`` or None.
    """
    _hk = pytz.timezone("Asia/Hong_Kong")
    _ms_re = re.compile(r"/Date\((-?\d+)[+-]\d+\)/")

    def _parse_xero_date(raw):
        if not raw:
            return None
        m = _ms_re.search(str(raw))
        if not m:
            return None
        ms = int(m.group(1))
        dt_utc = datetime.utcfromtimestamp(ms / 1000)
        dt_hk = pytz.utc.localize(dt_utc).astimezone(_hk)
        return dt_hk.date()

    try:
        url = "https://api.xero.com/api.xro/2.0/Organisation"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }
        response = requests.get(url, headers=headers, timeout=15)
        logger.info("get_organisation_lock_dates: status=%s org=%s", response.status_code, xero_org_id)

        if response.status_code != 200:
            logger.warning(
                "get_organisation_lock_dates: non-200 response org=%s status=%s",
                xero_org_id, response.status_code,
            )
            return {"period_lock_date": None, "end_of_year_lock_date": None}

        orgs = response.json().get("Organisations", [])
        org = next(
            (o for o in orgs if o.get("OrganisationID") == xero_org_id),
            orgs[0] if orgs else None,
        )
        if not org:
            logger.warning("get_organisation_lock_dates: no org found for org=%s", xero_org_id)
            return {"period_lock_date": None, "end_of_year_lock_date": None}

        period_lock_date = _parse_xero_date(org.get("PeriodLockDate"))
        end_of_year_lock_date = _parse_xero_date(org.get("EndOfYearLockDate"))
        logger.info(
            "get_organisation_lock_dates: org=%s period=%s eoy=%s",
            xero_org_id, period_lock_date, end_of_year_lock_date,
        )
        return {"period_lock_date": period_lock_date, "end_of_year_lock_date": end_of_year_lock_date}
    except Exception as exc:
        logger.warning("get_organisation_lock_dates: failed org=%s: %s", xero_org_id, exc)
        return {"period_lock_date": None, "end_of_year_lock_date": None}


def _get_entity_xero_data_from_db(entity_id):
    db_accounts = AccountInfo.query.filter_by(entity_id=entity_id).all()
    # xero_contact_sync has no is_active column - filtering on one threw, so this fallback
    # always answered 500
    db_contacts = XeroContactSync.query.filter_by(entity_id=entity_id).all()
    if not db_accounts and not db_contacts:
        return None
    all_accounts = [account_info_to_xero_format(acc) for acc in db_accounts]
    contacts = [contact_sync_to_xero_format(c) for c in db_contacts]
    bank_accounts = [acc for acc in all_accounts if acc.get("Type") == "BANK"]
    cashsale_account = [
        acc for acc in all_accounts if acc.get("Type") in [
            "SALES", "REVENUE", "INCOME"]]
    owners_account = [
        acc
        for acc in all_accounts
        if acc.get("Type")
        in [
            "CURRENT",
            "CURRLIAB",
            "NONCURRENT",
            "TERMLIAB",
            "LIABILITY",
        ]
    ]
    filtered_owners_account = []
    for acc in owners_account:
        system_account = acc.get("SystemAccount")
        if not (isinstance(system_account, str)
                and system_account.strip() != ""):
            filtered_owners_account.append(acc)
    owners_account = filtered_owners_account
    discrepancy_account = [
        acc for acc in all_accounts if acc.get("Type") in ("EXPENSE", "DIRECTCOSTS")]
    return {
        "bank_accounts": bank_accounts or [],
        "cashsale_account": cashsale_account or [],
        "owners_account": owners_account or [],
        "discrepancy_account": discrepancy_account or [],
        "contacts": contacts or [],
    }

