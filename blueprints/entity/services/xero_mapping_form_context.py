"""Shared Xero account/contact lists and mapping defaults for classic templates."""

from flask import g
from loguru import logger

from models.db import AccountInfo, EntityPettycashSettings, XeroContactSync
from services.app_runtime.legacy.xero_service import (
    account_info_to_xero_format, contact_sync_to_xero_format)


def _with_saved(options, *saved, key="AccountID"):
    """``options`` plus each saved choice it lacks (a new list; the request cache is shared)."""
    have = {o.get(key) for o in options}
    extra = []
    for choice in saved:
        if choice and choice.get(key) and choice.get(key) not in have:
            have.add(choice.get(key))
            extra.append(choice)
    return list(options) + extra if extra else options


def build_xero_mapping_form_context(entity_id, org, token_valid):
    """Return kwargs dict for Petty Cash / Xero mapping cards (classic HTML).

    Dropdowns are always populated from the database, regardless of whether
    the entity is connected to Xero. Routes that render these dropdowns are
    expected to kick off a background Xero -> DB sync separately so the DB
    stays current; this function never calls the Xero API.
    """
    if not hasattr(g, "_xero_data_cache"):
        g._xero_data_cache = {}

    cache_key = f"{entity_id}_{org.xero_org_id}"

    if cache_key not in g._xero_data_cache:
        db_accounts = AccountInfo.query.filter(
            AccountInfo.entity_id == entity_id,
            AccountInfo.status == "ACTIVE",
        ).all()
        db_contacts = XeroContactSync.query.filter_by(
            entity_id=entity_id).all()

        all_accounts = [account_info_to_xero_format(acc) for acc in db_accounts]
        contacts = [contact_sync_to_xero_format(c) for c in db_contacts]

        bank_accounts = [
            acc for acc in all_accounts if acc.get("Type") == "BANK"]
        cashsale_account = [
            acc
            for acc in all_accounts
            if acc.get("Type") in ["SALES", "REVENUE", "INCOME"]
        ]
        owners_account = [
            acc
            for acc in all_accounts
            if acc.get("Type") in [
                "NONCURRENT",
                "CURRLIAB",
                "TERMLIAB",
                "FIXED",
                "INVENTORY",
                "DIRECTCOSTS",
                "EXPENSE",
            ]
            and not (
                isinstance(acc.get("SystemAccount"), str)
                and acc.get("SystemAccount", "").strip() != ""
            )
        ]
        discrepancy_account = [
            acc for acc in all_accounts
            if acc.get("Type") in ("EXPENSE", "DIRECTCOSTS")
        ]

        g._xero_data_cache[cache_key] = {
            "bank_accounts": bank_accounts,
            "cashsale_account": cashsale_account,
            "owners_account": owners_account,
            "discrepancy_account": discrepancy_account,
            "contacts": contacts,
        }
    else:
        cached_data = g._xero_data_cache[cache_key]
        bank_accounts = cached_data["bank_accounts"]
        cashsale_account = cached_data["cashsale_account"]
        owners_account = cached_data["owners_account"]
        discrepancy_account = cached_data["discrepancy_account"]
        contacts = cached_data["contacts"]

    settings_row = EntityPettycashSettings.query.filter_by(
        entity_id=entity_id
    ).first()

    def _account_default(account_id):
        if not account_id:
            return None
        acc = AccountInfo.query.get(account_id)
        return account_info_to_xero_format(acc) if acc else None

    def _contact_default(contact_id):
        if not contact_id:
            return None
        contact = XeroContactSync.query.get(contact_id)
        return contact_sync_to_xero_format(contact) if contact else None

    if settings_row is None:
        main_bank_account_default = None
        deposit_bank_account_default = None
        cashsale_account_default = None
        owners_account_default = None
        discrepancy_bank_default = None
        discrepancy_account_default = None
        cashsale_contact_default = None
        owners_contact_default = None
        discrepancy_contact_default = None
    else:
        main_bank_account_default = _account_default(
            settings_row.pettycash_account_id
        )
        deposit_bank_account_default = _account_default(
            settings_row.bank_account_id
        )
        cashsale_account_default = _account_default(
            settings_row.cash_sale_account_id
        )
        owners_account_default = _account_default(
            settings_row.director_account_id
        )
        discrepancy_bank_default = _account_default(
            settings_row.discrepancy_bank_account_id
        )
        discrepancy_account_default = _account_default(
            settings_row.discrepancy_account_id
        )
        cashsale_contact_default = _contact_default(
            settings_row.cash_sale_contact_id
        )
        owners_contact_default = _contact_default(
            settings_row.director_contact_id
        )
        discrepancy_contact_default = _contact_default(
            settings_row.discrepancy_contact_id
        )

    # A saved choice is always one of its field's options. The page selects it by setting a
    # hidden <select>'s value, which silently stays empty when the option is missing - and the
    # save is then refused ("Please select: Discrepancy account code"). That happened while
    # Petty Cash's ticks still wrote account_info.status; keep the guarantee regardless.
    bank_accounts = _with_saved(bank_accounts, main_bank_account_default,
                                deposit_bank_account_default, discrepancy_bank_default)
    cashsale_account = _with_saved(cashsale_account, cashsale_account_default)
    owners_account = _with_saved(owners_account, owners_account_default)
    discrepancy_account = _with_saved(discrepancy_account, discrepancy_account_default)
    contacts = _with_saved(contacts, cashsale_contact_default, owners_contact_default,
                           discrepancy_contact_default, key="ContactID")

    logger.info(
        "xero mapping context loaded for entity %s contacts=%s",
        entity_id,
        len(contacts),
    )
    return {
        "bank_accounts": bank_accounts,
        "cashsale_account": cashsale_account,
        "owners_account": owners_account,
        "discrepancy_account": discrepancy_account,
        "contacts": contacts,
        "main_bank_account_default": main_bank_account_default,
        "deposit_bank_account_default": deposit_bank_account_default,
        "cashsale_account_default": cashsale_account_default,
        "cashsale_contact_default": cashsale_contact_default,
        "owners_account_default": owners_account_default,
        "owners_contact_default": owners_contact_default,
        "discrepancy_bank_default": discrepancy_bank_default,
        "discrepancy_account_default": discrepancy_account_default,
        "discrepancy_contact_default": discrepancy_contact_default,
    }
