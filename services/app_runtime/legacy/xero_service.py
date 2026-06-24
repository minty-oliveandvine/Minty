"""Xero-specific helper utilities used by legacy app."""

from __future__ import annotations

from models.db import AccountInfo, XeroContactSync
from services.helpers.xero import mask_account_number


def account_info_to_xero_format(acc_info):
    """Convert an ``AccountInfo`` record to Xero API format."""
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
    """Convert an ``XeroContactSync`` record to Xero API format."""
    return {
        "ContactID": contact_sync.xero_contact_id,
        "Name": contact_sync.name,
    }


def _get_entity_xero_data_from_db(entity_id):
    """Build Xero-shaped payload from persisted records for an entity."""
    db_accounts = AccountInfo.query.filter_by(entity_id=entity_id).all()
    db_contacts = XeroContactSync.query.filter_by(entity_id=entity_id).all()

    if not db_accounts and not db_contacts:
        return None

    all_accounts = [account_info_to_xero_format(acc) for acc in db_accounts]
    contacts = [contact_sync_to_xero_format(c) for c in db_contacts]

    bank_accounts = [acc for acc in all_accounts if acc.get("Type") == "BANK"]
    cashsale_account = [
        acc for acc in all_accounts if acc.get("Type") in ["SALES", "REVENUE", "INCOME"]
    ]
    owners_account = [
        acc
        for acc in all_accounts
        if acc.get("Type") in [
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
        if not (
            isinstance(system_account, str) and system_account.strip() != ""
        ):
            filtered_owners_account.append(acc)
    owners_account = filtered_owners_account
    discrepancy_account = [acc for acc in all_accounts if acc.get("Type") in ("EXPENSE", "DIRECTCOSTS")]

    return {
        "bank_accounts": bank_accounts or [],
        "cashsale_account": cashsale_account or [],
        "owners_account": owners_account or [],
        "discrepancy_account": discrepancy_account or [],
        "contacts": contacts or [],
    }
