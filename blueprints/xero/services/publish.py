"""Xero publishing helpers moved out of the legacy app shim."""

from __future__ import annotations

import json
import mimetypes
import uuid
from datetime import datetime, date, timedelta
import time
import requests

from flask import jsonify, current_app
from flask_login import current_user
from loguru import logger

from blueprints.report.services.shared import update_report_after_deposit_change
from blueprints.report.services.s3_storage import get_s3_bucket, get_s3_client
from models.db import (AccountInfo, Report, ReportExpenseDetail, ReportHistory,
                       ReportDraft, User, XeroReportSync,
                       Entity,
                       ShopExpense, ShopExpenseDraft, XeroContactSync, db)
from services.auth.token_service import ensure_valid_token, resolve_xero_token
from services.helpers.xero_bridge import (get_entity_account_settings,
                                          get_entity_contact_settings)
from blueprints.xero.services.publish_errors import (
    PublishFailureReason, translate_xero_error)
from blueprints.xero.services import publish_errors as _pub_err


# Which Xero contact/account mappings each entity-level module depends on.
# Used so the report-history page can later confirm a failure is resolved
# (every dependency is valid again).  Each entry is [kind, role].
DEPS_CASH_SALES = [["contact", "cashsale_contact"], ["account", "cash_sale"]]
DEPS_DISCREPANCY = [["contact", "discrepancy_contact"], ["account", "discrepancy_account"]]
DEPS_DEPOSIT = [["account", "pettycash"], ["account", "bank"]]
DEPS_WITHDRAWAL_PERSONAL = [
    ["contact", "director_contact"], ["account", "director"], ["account", "pettycash"]
]
DEPS_WITHDRAWAL_COMPANY = [["account", "bank"], ["account", "pettycash"]]


def _record_module_error(pfr, module_label, reason, error_meta=None):
    """Attach a plain-English failure reason (+resolution metadata) to the accumulator."""
    if pfr is not None and module_label and reason:
        meta = error_meta or {}
        pfr.add_module_error(
            module_label,
            reason,
            scope=meta.get("scope"),
            expense_id=meta.get("expense_id"),
            deps=meta.get("deps"),
            failed_contact_id=meta.get("failed_contact_id"),
            module=meta.get("module"),
        )


def _resolve_access_token(entity_id):
    """Look up a Xero access token for ``entity_id``.

    Returns ``(access_token, None)`` on success, or ``(None, failure)`` where
    ``failure`` is:

    - ``"no_token"``  — the lookup succeeded but there is no usable token;
    - ``"no_user"``   — ``current_user`` isn't in scope (e.g. a background
      thread) and the caller passed no ``access_token``.

    The two are kept distinct because they mean different things when
    debugging a failed publish, and each call site logs its own message.

    Callers keep their own failure handling: the low-level ``create_*`` helpers
    return ``False``, the module-level ``xero_*`` publishers return ``(0, 1)``
    after ``_record_module_error``, and ``xero_integrated_module`` aggregates.
    This shares only the lookup, which is identical at every call site.
    """
    try:
        token_user = resolve_xero_token(entity_id, current_user)
    except RuntimeError:
        return None, "no_user"
    if token_user:
        return token_user.access_token, None
    return None, "no_token"


def _normalize_xero_date(value):
    if isinstance(value, datetime) or isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value.replace("T", " ").split(" ")[0]
    if value is None:
        return None
    return str(value)


def bank_transaction_to_xero(entity, token, payload):
    # Make a POST request to the banktransactions API
    headers = {
        "Authorization": f"Bearer {token}",
        "Xero-Tenant-Id": str(entity),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Add timeout to prevent hanging requests (30 seconds for connection, 60 seconds total)
    response = requests.post(
        url=f"{current_app.config['XERO_API_BASE_URL']}/BankTransactions",
        data=json.dumps(payload),
        headers=headers,
        timeout=(30, 60),
    )

    return response


def bank_transfer_to_xero(entity, token, payload):
    headers = {
        "Authorization": f"Bearer {token}",
        "Xero-Tenant-Id": str(entity),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    refresh_token_value = None
    try:
        if hasattr(current_user, 'refresh_token') and current_user.refresh_token:
            refresh_token_value = current_user.refresh_token
    except (RuntimeError, AttributeError):
        pass

    logger.info(
        f"func bank_transfer_to_xero | token: {token} | refresh token: {refresh_token_value}"
    )

    response = requests.post(
        url=f"{current_app.config['XERO_API_BASE_URL']}/BankTransfers",
        data=json.dumps(payload),
        headers=headers,
    )

    return response


def create_xero_contact(entity_id, contact_name, access_token, xero_org_id):
    """
    Create a new contact in Xero and sync it to our database.
    Returns the new contact_id or None if creation failed.
    """
    try:
        endpoint = "https://api.xero.com/api.xro/2.0/Contacts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Xero-Tenant-Id": str(xero_org_id),
        }

        contact_data = {
            "Contacts": [{"Name": contact_name, "IsCustomer": False, "IsSupplier": True}]
        }

        logger.info(f"Creating contact in Xero: {contact_name}")
        response = requests.post(endpoint, headers=headers, json=contact_data, timeout=10)

        if response.status_code in (200, 201):
            xero_contact_data = response.json()
            contacts = xero_contact_data.get("Contacts", [])

            if contacts:
                created_contact = contacts[0]
                new_contact_id = created_contact.get("ContactID")
                contact_name_from_xero = created_contact.get("Name")

                logger.info(
                    f"Successfully created contact in Xero: {contact_name_from_xero} (ID: {new_contact_id})"
                )

                # Sync to our database
                try:
                    contact_sync = XeroContactSync(
                        entity_id=entity_id,
                        xero_contact_id=new_contact_id,
                        name=contact_name_from_xero,
                        category="expense_contact",
                    )
                    db.session.add(contact_sync)
                    db.session.commit()
                    logger.info(f"Contact sync record created: {new_contact_id}")
                except Exception as db_error:
                    logger.error(
                        f"Failed to save contact sync to database: {str(db_error)}"
                    )
                    db.session.rollback()
                    # Still return the contact ID even if DB sync failed

                return new_contact_id
            else:
                logger.error("Xero returned success but no contacts in response")
                return None
        else:
            logger.error(
                f"Failed to create contact in Xero. Status: {response.status_code}, Response: {response.text}"
            )
            return None
    except Exception as e:
        logger.error(f"Exception creating contact in Xero: {str(e)}", exc_info=True)
        return None


def ensure_contact_exists_in_xero(entity_id, contact_id, contact_name, access_token, xero_org_id):
    """
    Ensure a contact exists in Xero. If contact_id is provided but doesn't exist,
    create a new contact using contact_name. Returns the valid contact_id.
    """
    if not contact_id:
        # No contact ID provided - create new contact if name is provided
        if contact_name:
            return create_xero_contact(entity_id, contact_name, access_token, xero_org_id)
        return None

    # Check if contact exists in Xero
    try:
        url = f"{current_app.config['XERO_API_BASE_URL']}/Contacts/{contact_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"Contact {contact_id} exists in Xero")
            return contact_id
        elif response.status_code == 404:
            logger.warning(
                f"Contact {contact_id} not found in Xero. Creating new contact with name: {contact_name}"
            )
            if contact_name:
                new_contact_id = create_xero_contact(
                    entity_id, contact_name, access_token, xero_org_id
                )
                if new_contact_id:
                    try:
                        expenses = ShopExpense.query.filter_by(
                            contact_id=contact_id
                        ).all()
                        for expense in expenses:
                            expense.contact_id = new_contact_id
                        db.session.commit()
                        logger.info(
                            f"Updated {len(expenses)} expense(s) contact_id from {contact_id} to {new_contact_id}"
                        )
                    except Exception as update_error:
                        logger.error(
                            f"Error updating expense contact_ids: {str(update_error)}"
                        )
                        db.session.rollback()
                return new_contact_id
            else:
                logger.error(f"Contact {contact_id} not found and no contact_name provided to create new contact")
                return None
        else:
            logger.error(
                f"Error checking contact {contact_id} in Xero: {response.status_code} - {response.text}"
            )
            if contact_name:
                return create_xero_contact(
                    entity_id, contact_name, access_token, xero_org_id
                )
            return None
    except Exception as e:
        logger.error(f"Exception checking contact in Xero: {str(e)}", exc_info=True)
        if contact_name:
            return create_xero_contact(entity_id, contact_name, access_token, xero_org_id)
        return None


def create_bank_transaction(
    entity_id,
    date,
    type="RECEIVE",
    contact_id="",
    amount=0,
    bank_account_id="",
    line_items=[{}],
    type_of_transaction="",
    access_token=None,
    report_id=None,  # Optional: for posted reports (ShopExpense), None for draft reports (ShopExpenseDraft)
    pfr=None,  # Optional PublishFailureReason accumulator (out-parameter)
    subject=None,  # "contact" / "account" — helps phrase the failure reason
    module_label=None,  # short label for the failing module/line, used in the reason bullet
    error_meta=None,  # resolution metadata: {scope, expense_id, deps}
):
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available for bank transaction")
                return False
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided for bank transaction")
                return False

        entity = Entity.query.filter(Entity.id == entity_id).first()
        if not entity:
            logger.error(f"Entity not found: {entity_id}")
            return False

        # Get contact name from expense if available and ensure contact exists in Xero
        contact_name = None
        expense_record = None
        original_contact_id = contact_id
        if contact_id and report_id and type == "SPEND" and type_of_transaction == "expense":
            try:
                expense_record = ShopExpense.query.filter_by(
                    report_id=report_id,
                    contact_id=contact_id
                ).first()
                if expense_record:
                    # Try to get contact_name from expense record first
                    if expense_record.contact_name:
                        contact_name = expense_record.contact_name
                        logger.info(f"Found contact_name '{contact_name}' from expense record for contact_id {contact_id}")
                    else:
                        # Fallback: try to get contact name from XeroContactSync table
                        try:
                            contact_sync = XeroContactSync.query.filter_by(
                                xero_contact_id=contact_id,
                                entity_id=entity_id
                            ).first()
                            if contact_sync and contact_sync.name:
                                contact_name = contact_sync.name
                                logger.info(f"Found contact_name '{contact_name}' from XeroContactSync for contact_id {contact_id}")
                            else:
                                # Last resort: use expense item as contact name or create a default
                                if expense_record.item:
                                    contact_name = expense_record.item
                                    logger.info(f"Using expense item '{contact_name}' as contact name for contact_id {contact_id}")
                                else:
                                    contact_name = f"Expense Contact {contact_id[:8]}"
                                    logger.info(f"Using default contact name '{contact_name}' for contact_id {contact_id}")
                        except Exception as sync_error:
                            logger.warning(f"Could not retrieve contact_name from XeroContactSync: {str(sync_error)}")
                            # Use expense item as fallback
                            if expense_record.item:
                                contact_name = expense_record.item
                                logger.info(f"Using expense item '{contact_name}' as contact name fallback")
                else:
                    logger.warning(f"Expense record not found for report_id {report_id}, contact_id {contact_id}")
            except Exception as e:
                logger.warning(f"Could not retrieve contact_name from expense: {str(e)}")

        # Ensure contact exists in Xero before creating bank transaction
        if contact_id:
            valid_contact_id = ensure_contact_exists_in_xero(
                entity_id=entity_id,
                contact_id=contact_id,
                contact_name=contact_name,
                access_token=access_token,
                xero_org_id=entity.xero_org_id
            )

            if not valid_contact_id:
                logger.warning(
                    f"Could not ensure contact exists in Xero. contact_id: {contact_id}, contact_name: {contact_name}"
                )
                logger.warning("Proceeding with bank transaction without contact due to contact creation/verification failure")
                contact_id = None
            else:
                contact_id = valid_contact_id

                # If a new contact was created and we have an expense record, update it
                if expense_record and valid_contact_id != original_contact_id:
                    try:
                        expense_record.contact_id = valid_contact_id
                        db.session.commit()
                        logger.info(f"Updated expense record {expense_record.id} with new contact_id {valid_contact_id}")
                    except Exception as update_error:
                        logger.error(f"Error updating expense contact_id: {str(update_error)}")
                        db.session.rollback()

        tx_date = _normalize_xero_date(date)
        if not tx_date:
            logger.error("Invalid date provided for bank transaction")
            return False
        date_ref = tx_date.replace("-", "")

        if type == "SPEND" and type_of_transaction == "expense":
            reference = "MT" + date_ref + "Expense"
        elif (
            type == "SPEND"
            and type_of_transaction == "discrepancy"
            or type == "RECEIVE"
            and type_of_transaction == "discrepancy"
        ):
            reference = "MT" + date_ref + "Discrepancy"
        else:
            reference = "MT" + date_ref + "Withdrawal"

        bank_transaction_payload = {
            "bankTransactions": [
                {
                    "type": type,
                    "lineItems": line_items,
                    "Date": tx_date,
                    "bankAccount": {"accountID": bank_account_id},
                    "Reference": reference,
                }
            ]
        }

        # Only add contact if we have a valid contact_id
        if contact_id:
            bank_transaction_payload["bankTransactions"][0]["contact"] = {"contactID": contact_id}

        response = bank_transaction_to_xero(
            entity.xero_org_id, access_token, bank_transaction_payload
        )

        logger.info(f"Bank transaction | {type} | {type_of_transaction} response: {response.text}")

        if response.status_code == 200:
            if type == "SPEND" and type_of_transaction == 'expense':
                try:
                    response_data = json.loads(response.text)
                    bank_transction_id = response_data["BankTransactions"][0][
                        "BankTransactionID"
                    ]

                    # Get expense details from line_items
                    first_unit_amount = line_items[0].get("unitAmount", 0)
                    item = line_items[0].get("description", "")
                    account_code = line_items[0].get("accountCode", "")
                    logger.info(f"Looking for expense: {line_items[0]}")

                    expense = None

                    # If report_id is provided, we're working with posted reports (ShopExpense)
                    if report_id:
                        expense = ShopExpense.query.filter(
                            ShopExpense.report_id == report_id,
                            ShopExpense.amount == first_unit_amount,
                            ShopExpense.item == item,
                            ShopExpense.account_code == account_code,
                            ShopExpense.contact_id == contact_id,
                        ).first()
                        if expense:
                            logger.info(f"Found ShopExpense for {item} in posted report {report_id}")
                    else:
                        # Otherwise, we're working with draft reports (ShopExpenseDraft)
                        # Get user email from report_draft (since current_user may not be available in background thread)
                        report_draft = ReportDraft.query.filter(
                            ReportDraft.transaction_date == date
                        ).first()
                        email = report_draft.uploaded_by if report_draft else None

                        if not email:
                            # Try to get from current_user as fallback
                            try:
                                if hasattr(current_user, 'username') and current_user.username:
                                    email = current_user.username
                                else:
                                    logger.warning("Could not determine user email for expense file upload")
                                    return True  # Transaction was created, return success
                            except RuntimeError:
                                logger.warning("Could not determine user email for expense file upload")
                                return True  # Transaction was created, return success

                        report_draft_id = (
                            ReportDraft.query.filter(
                                ReportDraft.transaction_date == date,
                                ReportDraft.uploaded_by == email,
                            )
                            .first()
                            .id
                        )
                        expense = ShopExpenseDraft.query.filter(
                            ShopExpenseDraft.report_draft_id == report_draft_id,
                            ShopExpenseDraft.amount == first_unit_amount,
                            ShopExpenseDraft.item == item,
                            ShopExpenseDraft.account_code == account_code,
                        ).first()
                        if expense:
                            logger.info(f"Found ShopExpenseDraft for {item} in draft report")

                    if expense:
                        file_upload_result = upload_each_file(expense, entity, bank_transction_id, access_token=access_token)
                        if not file_upload_result:
                            logger.warning(
                                f"Bank transaction created but file upload failed for {item}"
                            )
                        return True
                    else:
                        logger.warning(
                            f"Expense not found for {item} (report_id={report_id}), but bank transaction was created"
                        )
                        return True
                except Exception as file_error:
                    logger.error(
                        f"Error processing file upload for expense: {str(file_error)}",
                        exc_info=True
                    )
                    # Transaction was created successfully, so return True even if file upload failed
                    return True
            else:
                logger.info("Bank transaction for type RECEIVE successful")
                return True
        else:
            logger.error(
                f"Bank transaction failed with status {response.status_code}: {response.text}"
            )
            _record_module_error(
                pfr, module_label,
                translate_xero_error(response.status_code, response.text, subject=subject),
                error_meta,
            )
            return False
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error creating bank transaction: {str(e)}")
        _record_module_error(pfr, module_label, "Xero did not respond, please try again", error_meta)
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error creating bank transaction: {str(e)}")
        _record_module_error(pfr, module_label, "could not reach Xero, please try again", error_meta)
        return False
    except Exception as e:
        logger.error(f"Error creating bank transaction: {str(e)}", exc_info=True)
        _record_module_error(pfr, module_label, "Xero rejected this entry", error_meta)
        return False


def create_bank_transfer(
    entity_id, date, bank_account, withdrawal_amount, to_bank_account_id, access_token=None, transfer_type="company", reference_override=None,
    pfr=None, module_label=None, error_meta=None
):
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available for bank transfer")
                return False
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided for bank transfer")
                return False

        entity = Entity.query.filter(Entity.id == entity_id).first()
        from_bank_account_id = bank_account
        to_bank_account_id = to_bank_account_id
        amount = withdrawal_amount

        xero_date = _normalize_xero_date(date)
        if not xero_date:
            logger.error("Invalid date provided for bank transfer")
            return False
        date_clean = xero_date.replace("-", "")

        # Ensure date is in correct format and construct reference
        logger.info(f"Date parameter type: {type(date)}, value: {date}")
        logger.info(f"Date after removing dashes: {date_clean}")
        if reference_override:
            reference = reference_override
        elif transfer_type == 'company':
            reference = f"MT{date_clean}Withdrawal"
        else:
            reference = f"MT{date_clean}Deposit"

        logger.info(f"Final reference: {reference}")

        logger.info(f"Xero date format: {xero_date}")

        bank_transfer_payload = {
            "BankTransfers": [
                {
                    "FromBankAccount": {
                        "AccountID": from_bank_account_id,
                        "CurrencyCode": "HKD",
                    },
                    "ToBankAccount": {
                        "AccountID": to_bank_account_id,
                        "CurrencyCode": "HKD",
                    },
                    "Date": xero_date,
                    "Amount": amount,
                    "Reference": reference,
                }
            ]
        }

        logger.info(
            f"Bank transfer payload: {json.dumps(bank_transfer_payload, indent=2)}"
        )

        response_withdrawal = bank_transfer_to_xero(
            entity.xero_org_id, access_token, bank_transfer_payload
        )

        logger.info(
            f"Bank transfer response status: {response_withdrawal.status_code}"
        )
        logger.info(f"Bank transfer response text: {response_withdrawal.text}")

        if response_withdrawal.status_code == 200:
            logger.info("Bank transfer for company successful")
            return True
        else:
            logger.error(
                f"Bank transfer for company error: {response_withdrawal.text}"
            )
            _record_module_error(
                pfr, module_label,
                translate_xero_error(
                    response_withdrawal.status_code, response_withdrawal.text,
                    subject="account",
                ),
                error_meta,
            )
            return False
    except Exception as e:
        logger.error(f"Error creating bank transfer: {str(e)}")
        _record_module_error(pfr, module_label, "Xero rejected this entry", error_meta)
        return False


def create_invoice(
    entity_id,
    contact_id,
    description,
    quantity,
    unit_amount,
    tax_type,
    line_amount,
    date,
    duedate,
    account_code,
    access_token=None,
    pfr=None,
    module_label=None,
    error_meta=None,
):
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available for invoice")
                return False
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided for invoice")
                return False

        entity = Entity.query.filter(Entity.id == entity_id).first()
        invoice_payload = {
            "Invoices": [
                {
                    "Type": "ACCREC",
                    "Contact": {"ContactID": contact_id},
                    "LineItems": [
                        {
                            "Description": description,
                            "Quantity": quantity,
                            "UnitAmount": unit_amount,
                            "AccountCode": account_code,
                            "TaxType": tax_type,
                            "LineAmount": line_amount,
                        }
                    ],
                    "Date": _normalize_xero_date(date),
                    "DueDate": _normalize_xero_date(duedate),
                    "Reference": description,
                    "Status": "AUTHORISED",
                }
            ]
        }

        response_invoice = invoice_to_xero(
            entity.xero_org_id, access_token, invoice_payload
        )
        if response_invoice and response_invoice.status_code == 200:
            return True
        else:
            if response_invoice is None:
                logger.error(
                    "Invoice creation failed: no response object from Xero API helper"
                )
                _record_module_error(pfr, module_label, "could not reach Xero, please try again", error_meta)
            else:
                _record_module_error(
                    pfr, module_label,
                    translate_xero_error(
                        response_invoice.status_code, response_invoice.text,
                        subject="account",
                    ),
                    error_meta,
                )
            return False
    except Exception as e:
        logger.error(f"Error in create_invoice: {str(e)}")
        _record_module_error(pfr, module_label, "Xero rejected this entry", error_meta)
        return False


def invoice_to_xero(entity_id, access_token, invoice_payload):
    try:

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(entity_id),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = requests.put(
            url=f"{current_app.config['XERO_API_BASE_URL']}/Invoices",
            data=json.dumps(invoice_payload),
            headers=headers,
        )
        return response
    except Exception as e:
        logger.error(f"Error in invoice_to_xero: {str(e)}")
        return None


def upload_each_file(expense, entity, bank_transction_id, access_token=None):
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(
                entity.id if entity else None
            )
            if failure == "no_token":
                logger.error("No access token available for file upload")
                return False
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided for file upload")
                return False

        if not expense or not expense.files:
            logger.warning("No file found for expense, skipping upload")
            return False

        file_url = expense.files
        file_format = file_url.split(".")[-1]
        file_name = (expense.remarks or expense.item) + "." + file_format
        file_name = file_name.replace(" ", "_")

        try:
            # Determine how to fetch the file (S3 key or full URL)
            if file_url.startswith("http://") or file_url.startswith("https://"):
                resp = requests.get(file_url, timeout=(10, 30))
                resp.raise_for_status()
                file_bytes = resp.content
            else:
                # Assume file_url is an S3 key
                s3_resp = get_s3_client().get_object(Bucket=get_s3_bucket(), Key=file_url)
                file_bytes = s3_resp["Body"].read()
            # Prepare multipart file payload
            content_type = (
                mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            )
            upload_url = f"https://api.xero.com/api.xro/2.0/BankTransactions/{bank_transction_id}/Attachments/{file_name}"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": str(entity.xero_org_id),
                "Content-Type": content_type,
                # Do not set Content-Type; requests will set the multipart boundary
            }
            # Xero expects PUT for attachments to /BankTransactions/{id}/Attachments/{filename}
            # Add timeout: 10s connection, 60s total
            attach_resp = requests.put(
                upload_url, headers=headers, data=file_bytes, timeout=(10, 60)
            )
            # Removed session["xero_response_text"] as session is not available in background threads
            if attach_resp.status_code in (200, 201, 204):
                logger.info(
                    f"Attachment uploaded successfully to Xero for bank transaction {bank_transction_id}"
                )
                return True
            else:
                logger.error(
                    f"Failed to upload attachment to Xero. Status: {attach_resp.status_code}, Response: {attach_resp.text}"
                )
                return False
        except requests.exceptions.Timeout as ex:
            logger.error(f"Timeout error uploading attachment to Xero: {ex}")
            return False
        except requests.exceptions.RequestException as ex:
            logger.error(f"Request error uploading attachment to Xero: {ex}")
            return False
        except Exception as ex:
            logger.error(f"Error uploading attachment to Xero: {ex}", exc_info=True)
            return False
    except Exception as error:
        db.session.rollback()
        logger.error(f"Error in upload_each_file: {str(error)}", exc_info=True)
        return False


def xero_withdrawal_from(report_draft, entity_id, date, access_token=None, pfr=None):
    """Publish the cash withdrawal/addition.  Returns (succeeded, failed) counts."""
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available in xero_withdrawal_from")
                _record_module_error(pfr, "Withdrawal", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided in xero_withdrawal_from")
                _record_module_error(pfr, "Withdrawal", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)

        if report_draft:
            # Handle draft report
            withdrawal_type = report_draft.withdrawal_type
            if withdrawal_type == "personal":
                draft_report = ReportDraft.query.filter(
                    ReportDraft.company == entity_id,
                    ReportDraft.transaction_date == date,
                ).first()
                amount = draft_report.cash_addition
                director_contact = get_entity_contact_settings(
                    entity_id, "director_contact"
                )
                if director_contact is None:
                    logger.error(
                        f"Director contact missing for entity {entity_id}"
                    )
                    if pfr is not None:
                        pfr.add_missing(_pub_err.LABEL_DIRECTOR_CONTACT,
                                        deps=[["contact", "director_contact"]],
                                        module="withdrawal_from")
                    return (0, 1)
                contact_id = director_contact.xero_contact_id
                contact_name = director_contact.name
                logger.info(f"Contact name: {contact_name}")

                pettycash_settings = (
                    get_entity_account_settings(entity_id, "pettycash") or {}
                )
                bank_account_id = pettycash_settings.get("xero_account_id")

                director_account_settings = get_entity_account_settings(entity_id, "director")
                director_account_code = (
                    director_account_settings.get("account_code")
                    if director_account_settings
                    else None
                )
                if not director_account_code:
                    logger.error(
                        f"Director account code missing for entity {entity_id}"
                    )
                    if pfr is not None:
                        pfr.add_missing(_pub_err.LABEL_DIRECTOR_ACCOUNT_CODE,
                                        deps=[["account", "director"]],
                                        module="withdrawal_from")
                    return (0, 1)
                logger.info(f"Director account code: {director_account_code}")

                line_items = [
                    {
                        "description": f"Amount due to {contact_name}",
                        "quantity": 1,
                        "unitAmount": amount,
                        "accountCode": director_account_code,
                        "taxType": "NONE",
                    }
                ]
                # Type, bank account (pettycash), amount, date, contact (director), line_items(description, quantity, unitAmount, accountCode, taxType)
                ok = create_bank_transaction(
                    entity_id,
                    date,
                    type="RECEIVE",
                    contact_id=contact_id,
                    amount=amount,
                    bank_account_id=bank_account_id,
                    line_items=line_items,
                    access_token=access_token,
                    pfr=pfr,
                    subject="contact",
                    module_label="Withdrawal",
                    error_meta={"scope": "entity", "deps": DEPS_WITHDRAWAL_PERSONAL, "module": "withdrawal_from"},
                )
                return (1, 0) if ok else (0, 1)
            elif withdrawal_type == "company":
                deposit_bank_settings = (
                    get_entity_account_settings(entity_id, "bank") or {}
                )
                from_bank_account = deposit_bank_settings.get(
                    "xero_account_id"
                )
                cash_addition = report_draft.cash_addition
                pettycash_settings = (
                    get_entity_account_settings(entity_id, "pettycash") or {}
                )
                to_bank_account_id = pettycash_settings.get(
                    "xero_account_id"
                )
                ok = create_bank_transfer(
                    entity_id,
                    date,
                    bank_account=from_bank_account,
                    withdrawal_amount=cash_addition,
                    to_bank_account_id=to_bank_account_id,
                    access_token=access_token,
                    transfer_type=withdrawal_type,
                    pfr=pfr,
                    module_label="Withdrawal",
                    error_meta={"scope": "entity", "deps": DEPS_WITHDRAWAL_COMPANY, "module": "withdrawal_from"},
                )
                return (1, 0) if ok else (0, 1)
        # No draft / unrecognised withdrawal type — nothing to post.
        _record_module_error(pfr, "Withdrawal", "withdrawal type is not set")
        return (0, 1)
    except Exception as e:
        logger.error(f"Error in withdrawal_from: {str(e)}")
        _record_module_error(pfr, "Withdrawal", "Xero rejected this entry")
        return (0, 1)

def xero_invoices(entity_id, posted_report, date, amount, access_token=None, pfr=None):
    """Publish cash sales as an invoice.  Returns (succeeded, failed) counts."""
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available in xero_invoices")
                _record_module_error(pfr, "Cash sales", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided in xero_invoices")
                _record_module_error(pfr, "Cash sales", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)

        cash_sale_contact = get_entity_contact_settings(
            entity_id, "cashsale_contact"
        )
        if cash_sale_contact is None:
            logger.error(
                f"Cash sale contact missing for entity {entity_id}"
            )
            if pfr is not None:
                pfr.add_missing(_pub_err.LABEL_CASHSALE_CONTACT,
                                deps=[["contact", "cashsale_contact"]],
                                module="invoices")
            return (0, 1)
        contact_id = cash_sale_contact.xero_contact_id

        cash_sale_settings = (
            get_entity_account_settings(entity_id, "cash_sale") or {}
        )
        account_code = cash_sale_settings.get("account_code")

        description = "MT" + date.strftime("%Y%m%d") + "Cash Sales"
        quantity = 1
        unit_amount = amount
        tax_type = "NONE"
        line_amount = quantity * unit_amount
        date = posted_report.transaction_date.strftime("%Y-%m-%d")
        duedate = date

        invoice_success = create_invoice(
            entity_id,
            contact_id,
            description,
            quantity,
            unit_amount,
            tax_type,
            line_amount,
            date,
            duedate,
            account_code,
            access_token=access_token,
            pfr=pfr,
            module_label="Cash sales",
            error_meta={"scope": "entity", "deps": DEPS_CASH_SALES, "module": "invoices"},
        )
        return (1, 0) if invoice_success else (0, 1)
    except Exception as e:
        logger.error(f"Error in xero_invoices: {str(e)}")
        _record_module_error(pfr, "Cash sales", "Xero rejected this entry",
                             {"scope": "entity", "deps": DEPS_CASH_SALES, "module": "invoices"})
        return (0, 1)



def xero_expenses(entity_id, posted_report, date, access_token=None, pfr=None, retry_expense_ids=None):
    """Publish each shop expense.  Returns (succeeded, failed) line counts.

    ``retry_expense_ids`` (selective re-publish) restricts processing to the
    given ShopExpense ids — the ones that failed last time — so already-posted
    expenses are not duplicated.
    """
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available in xero_expenses")
                _record_module_error(pfr, "Expenses", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided in xero_expenses")
                _record_module_error(pfr, "Expenses", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
        
        if posted_report.expenses and posted_report.expenses > 0:
            expense_query = ShopExpense.query.filter(
                ShopExpense.report_id == posted_report.id
            )
            if retry_expense_ids is not None:
                # Selective re-publish: only the previously-failed expenses.
                expense_query = expense_query.filter(
                    ShopExpense.id.in_(list(retry_expense_ids))
                )
            shop_expenses = expense_query.all()
            if not shop_expenses and retry_expense_ids is not None:
                # The failed expenses were since deleted — nothing left to post.
                logger.info("Selective expense retry: target expenses no longer exist")
                return (0, 0)
            if shop_expenses:
                pettycash_settings = (
                    get_entity_account_settings(entity_id, "pettycash") or {}
                )
                bank_account_id = pettycash_settings.get("xero_account_id")

                expenses_submitted = []
                failed_expenses = []
                total_count = len(shop_expenses)
                batch_size = 5
                
                logger.info(
                    f"Starting to process {total_count} expenses for report {posted_report.id} in batches of {batch_size}"
                )
                
                # Process expenses in batches of 5
                for batch_start in range(0, total_count, batch_size):
                    batch_end = min(batch_start + batch_size, total_count)
                    batch_expenses = shop_expenses[batch_start:batch_end]
                    batch_number = (batch_start // batch_size) + 1
                    total_batches = (total_count + batch_size - 1) // batch_size
                    
                    logger.info(
                        f"Processing batch {batch_number}/{total_batches} "
                        f"(expenses {batch_start + 1}-{batch_end} of {total_count})"
                    )
                    
                    for expense in batch_expenses:
                        index = shop_expenses.index(expense) + 1
                        try:
                            logger.info(
                                f"Processing expense {index}/{total_count}: {expense.item} - ${expense.amount}"
                            )
                            result = create_bank_transaction(
                                entity_id,
                                date,
                                type="SPEND",
                                contact_id=expense.contact_id,
                                bank_account_id=bank_account_id,
                                line_items=[
                                    {
                                        "description": expense.item,
                                        "unitAmount": expense.amount,
                                        "accountCode": expense.account_code or "200",
                                        "taxType": "NONE",
                                    }
                                ],
                                type_of_transaction="expense",
                                access_token=access_token,
                                report_id=posted_report.id,  # Pass report_id for posted reports
                                pfr=pfr,
                                subject="contact",
                                module_label=f"Expense '{expense.item}'",
                                error_meta={
                                    "scope": "expense",
                                    "expense_id": expense.id,
                                    "failed_contact_id": expense.contact_id,
                                    "module": "expenses",
                                },
                            )
                            if result:
                                expenses_submitted.append(True)
                                logger.info(
                                    f"Expense {index}/{total_count} submitted successfully: {expense.item}"
                                )
                            else:
                                expenses_submitted.append(False)
                                failed_expenses.append(f"Expense {index}: {expense.item} (${expense.amount})")
                                logger.error(
                                    f"Expense {index}/{total_count} failed to submit: {expense.item} - ${expense.amount}"
                                )
                        except Exception as e:
                            expenses_submitted.append(False)
                            failed_expenses.append(f"Expense {index}: {expense.item} (${expense.amount}) - {str(e)}")
                            _record_module_error(
                                pfr, f"Expense '{expense.item}'", "Xero rejected this entry",
                                {
                                    "scope": "expense",
                                    "expense_id": expense.id,
                                    "failed_contact_id": expense.contact_id,
                                    "module": "expenses",
                                },
                            )
                            logger.error(
                                f"Exception processing expense {index}/{total_count} ({expense.item}): {str(e)}",
                                exc_info=True
                            )
                    
                    # Log batch completion
                    batch_successful = sum(expenses_submitted[batch_start:batch_end])
                    batch_total = len(batch_expenses)
                    logger.info(
                        f"Batch {batch_number}/{total_batches} complete: "
                        f"{batch_successful}/{batch_total} expenses successful"
                    )
                    
                    # Small delay between batches to avoid overwhelming the API
                    if batch_end < total_count:
                        time.sleep(0.5)  # 500ms delay between batches
                
                successful_count = sum(expenses_submitted)
                logger.info(
                    f"Expense processing complete: {successful_count}/{total_count} successful"
                )
                
                if failed_expenses:
                    logger.error(f"Failed expenses ({len(failed_expenses)}): {failed_expenses}")

                # Return line-level (succeeded, failed) counts so the report can be
                # marked partially published when only some expenses go through.
                failed_count = total_count - successful_count
                if failed_count:
                    logger.warning(
                        f"Partial success: {successful_count}/{total_count} expenses submitted successfully"
                    )
                return (successful_count, failed_count)
            else:
                logger.info("No shop expenses found in report")
                _record_module_error(pfr, "Expenses", "expense details are missing")
                return (0, 1)
        else:
            logger.info("No expenses amount in report")
            return (0, 0)
    except Exception as e:
        logger.error(f"Error in xero_expenses: {str(e)}", exc_info=True)
        _record_module_error(pfr, "Expenses", "Xero rejected this entry")
        return (0, 1)


def xero_deposit(entity_id, posted_report, date, access_token=None, pfr=None):
    """Publish the bank deposit transfer.  Returns (succeeded, failed) counts."""
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available in xero_deposit")
                _record_module_error(pfr, "Deposit", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided in xero_deposit")
                _record_module_error(pfr, "Deposit", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)

        pettycash_settings = (
            get_entity_account_settings(entity_id, "pettycash") or {}
        )
        from_bank_account = pettycash_settings.get("xero_account_id")
        deposit_bank_settings = (
            get_entity_account_settings(entity_id, "bank") or {}
        )
        to_bank_account = deposit_bank_settings.get("xero_account_id")
        deposit = posted_report.bank_deposit
        ok = create_bank_transfer(
            entity_id,
            date,
            bank_account=from_bank_account,
            withdrawal_amount=deposit,
            to_bank_account_id=to_bank_account,
            access_token=access_token,
            transfer_type="deposit",
            pfr=pfr,
            module_label="Deposit",
            error_meta={"scope": "entity", "deps": DEPS_DEPOSIT, "module": "deposit"},
        )
        return (1, 0) if ok else (0, 1)
    except Exception as e:
        logger.error(f"Error in xero_deposit: {str(e)}")
        _record_module_error(pfr, "Deposit", "Xero rejected this entry",
                             {"scope": "entity", "deps": DEPS_DEPOSIT, "module": "deposit"})
        return (0, 1)


def xero_discrepancy(entity_id, report, date, access_token=None, pfr=None):
    """Publish the cash discrepancy.  Returns (succeeded, failed) counts."""
    try:
        # Get access_token if not provided
        if access_token is None:
            access_token, failure = _resolve_access_token(entity_id)
            if failure == "no_token":
                logger.error("No access token available in xero_discrepancy")
                _record_module_error(pfr, "Discrepancy", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)
            if failure == "no_user":
                logger.error("current_user not available and no access_token provided in xero_discrepancy")
                _record_module_error(pfr, "Discrepancy", _pub_err.XERO_AUTH_EXPIRED)
                return (0, 1)

        discrepancy_date = _normalize_xero_date(date)
        if not discrepancy_date:
            logger.error(f"Invalid discrepancy date for report {report.id}")
            _record_module_error(pfr, "Discrepancy", "the discrepancy date is invalid")
            return (0, 1)
        # NB: the Xero "Reference" is derived inside create_bank_transaction
        # from type_of_transaction ("discrepancy"), so it isn't built here.
        discrepancy_type = report.discrepancy_type

        # Validate discrepancy_type is set correctly
        if not discrepancy_type or discrepancy_type not in ["surplus", "shortage"]:
            logger.error(
                f"Invalid or missing discrepancy_type '{discrepancy_type}' for report {report.id}. "
                f"Expected 'surplus' or 'shortage'"
            )
            _record_module_error(pfr, "Discrepancy", "the discrepancy type is not set")
            return (0, 1)

        # Set Xero transaction type based on discrepancy type
        if discrepancy_type == "shortage":
            type = "SPEND"
        elif discrepancy_type == "surplus":
            type = "RECEIVE"
        else:
            # This should never happen due to validation above, but adding as safety check
            logger.error(f"Unexpected discrepancy_type '{discrepancy_type}' after validation")
            _record_module_error(pfr, "Discrepancy", "the discrepancy type is not set")
            return (0, 1)

        pettycash_settings = (
            get_entity_account_settings(entity_id, "pettycash") or {}
        )
        bank_account_id = pettycash_settings.get("xero_account_id")

        discrepancy_amount = report.discrepancy_amount
        discrepancy_description = report.discrepancy_reason
        discrepancy_account_settings = (
            get_entity_account_settings(entity_id, "discrepancy_account") or {}
        )
        discrepancy_account_code = discrepancy_account_settings.get(
            "account_code"
        )

        discrepancy_contact = get_entity_contact_settings(
            entity_id, "discrepancy_contact"
        )
        if discrepancy_contact is None:
            logger.error(
                f"Discrepancy contact missing for entity {entity_id}"
            )
            _record_module_error(pfr, "Discrepancy", "discrepancy contact is not set up in Xero settings",
                                 {"scope": "entity", "deps": [["contact", "discrepancy_contact"]], "module": "discrepancy"})
            return (0, 1)
        contact_id = discrepancy_contact.xero_contact_id

        ok = create_bank_transaction(
            entity_id,
            date,
            type=type,
            contact_id=contact_id,
            bank_account_id=bank_account_id,
            pfr=pfr,
            subject="contact",
            module_label="Discrepancy",
            error_meta={"scope": "entity", "deps": DEPS_DISCREPANCY, "module": "discrepancy"},
            line_items=[
                {
                    "description": discrepancy_description,
                    "unitAmount": abs(discrepancy_amount),
                    "accountCode": discrepancy_account_code,
                    "taxType": "NONE",
                }
            ],
            type_of_transaction="discrepancy",
            access_token=access_token,
        )
        return (1, 0) if ok else (0, 1)

    except Exception as error:
        logger.error(f"Error in xero_discrepancy: {str(error)}")
        _record_module_error(pfr, "Discrepancy", "Xero rejected this entry",
                             {"scope": "entity", "deps": DEPS_DISCREPANCY, "module": "discrepancy"})
        return (0, 1)

def _is_system_account_code(account_code: str) -> bool:
    """Conservative filter for system accounts that should not be posted to Xero."""
    system_account_codes = {"497"}
    if not account_code:
        return False
    return str(account_code).strip() in system_account_codes


def validate_expenses_for_system_accounts(
        entity_id, report_id, access_token=None):
    """
    Validate whether a report contains expense lines mapped to system Xero accounts.

    `access_token` is kept for signature compatibility with the existing callsite.
    """
    try:
        expense_details = ReportExpenseDetail.query.filter_by(
            report_id=report_id).all()
        if not expense_details:
            return []

        account_ids = [detail.account_id for detail in expense_details]
        accounts = {
            account.id: account
            for account in AccountInfo.query.filter(
                AccountInfo.id.in_(account_ids), AccountInfo.entity_id == entity_id
            ).all()
        }

        errors = []
        for detail in expense_details:
            account = accounts.get(detail.account_id)
            if not account:
                continue
            if _is_system_account_code(account.xero_code):
                errors.append(
                    {
                        "expense": (
                            account.name
                            if account.name
                            else f"Expense {detail.expense_id}"
                        ),
                        "account_code": account.xero_code,
                        "message": "System accounts are not allowed to be published to Xero.",
                    }
                )

        return errors
    except Exception as exc:
        logger.error(
            f"System-account validation failed for report {report_id}: {str(exc)}"
        )
        return [
            {
                "expense": "unknown",
                "account_code": "unknown",
                # Rendered back to the user in the validation list — keep the
                # exception in the log above, not on screen.
                "message": "I couldn't check this report's accounts against Xero. Mind trying again?",
            }
        ]


def _aggregate_error_result(reason):
    """Build the orchestrator result shape for a whole-publish failure."""
    pfr = PublishFailureReason()
    if reason:
        pfr.add_module_error("Publish", reason)
    return {
        "modules": {
            "withdrawal_from": {"status": "error"},
            "deposit": {"status": "error"},
            "invoices": {"status": "error"},
            "expenses": {"status": "error"},
            "discrepancy": {"status": "error"},
        },
        "succeeded": 0,
        "failed": 1,
        "reasons": pfr.to_reason_bullets(),
        "reason_items": pfr.to_reason_items(),
    }


def xero_integrated_module(entity_id, date, posted_report, access_token=None, retry_filter=None):
    """Publish every transaction type for a report.

    Returns a dict::

        {"modules": {<module>: {"status": "success"|"error"}, ...},
         "succeeded": int,   # transactions that landed in Xero (line-level for expenses)
         "failed": int,      # transactions that did not
         "reasons": [str]}   # plain-English bullets for the failures

    The per-type handlers keep going when one fails, so the report can be
    marked partially published when some transactions succeed and some fail.

    ``retry_filter`` (selective re-publish) limits which parts run so already-
    published transactions are not posted again.  Shape::

        {"modules": {"invoices", "expenses", ...}, "expense_ids": {"<id>", ...}}

    When ``None``, every module with an amount runs (a fresh publish).  When set,
    only modules whose key is in ``retry_filter["modules"]`` run; the rest are
    skipped entirely (neither counted as success nor failure).
    """
    try:
        # If access_token not provided, try to get from current_user (for backward compatibility)
        if access_token is None:
            try:
                token_user = resolve_xero_token(entity_id, current_user)
                if token_user:
                    access_token = token_user.access_token
                else:
                    logger.error("No access token available in xero_integrated_module")
                    return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)
            except RuntimeError:
                # current_user not available (e.g., in background thread)
                logger.error("current_user not available and no access_token provided")
                return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        pfr = PublishFailureReason()
        modules = {}
        total_succeeded = 0
        total_failed = 0

        retry_modules = retry_filter.get("modules") if retry_filter else None
        retry_expense_ids = retry_filter.get("expense_ids") if retry_filter else None

        def _should_run(module_key):
            # Selective re-publish: only retry the previously-failed parts.
            return retry_modules is None or module_key in retry_modules

        def _record(module_key, counts):
            nonlocal total_succeeded, total_failed
            succeeded, failed = counts
            total_succeeded += succeeded
            total_failed += failed
            modules[module_key] = {"status": "error" if failed else "success"}

        # Check if we have a draft report first
        report_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id, ReportDraft.transaction_date == date
        ).first()

        # A rejected token (HTTP 401) is an account-wide condition, not a
        # per-module one.  As soon as any module reports it, stop the run and
        # surface the expiry a single time — otherwise every remaining module
        # makes a doomed Xero call and appends the same reason, producing a
        # toast like "Withdrawal — …; Cash sales — …; Expense 'X' — …".
        def _auth_expired():
            return pfr.has_auth_expired()

        #Cash addition/withdrawal from start
        if report_draft.cash_addition and report_draft.cash_addition > 0:
            if _should_run("withdrawal_from"):
                _record("withdrawal_from", xero_withdrawal_from(
                    report_draft, entity_id, date, access_token=access_token, pfr=pfr))
        else:
            modules["withdrawal_from"] = {"status": "success"}
        if _auth_expired():
            return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        #Cash sales
        if posted_report.cash_sales and posted_report.cash_sales > 0:
            if _should_run("invoices"):
                _record("invoices", xero_invoices(
                    entity_id, posted_report, date, posted_report.cash_sales,
                    access_token=access_token, pfr=pfr))
        else:
            modules["invoices"] = {"status": "success"}
        if _auth_expired():
            return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        #Expenses
        if posted_report.expenses and posted_report.expenses > 0:
            if _should_run("expenses"):
                _record("expenses", xero_expenses(
                    entity_id, posted_report, date, access_token=access_token, pfr=pfr,
                    retry_expense_ids=retry_expense_ids))
        else:
            modules["expenses"] = {"status": "success"}
        if _auth_expired():
            return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        #Bank deposit
        if posted_report.bank_deposit and posted_report.bank_deposit > 0:
            if _should_run("deposit"):
                _record("deposit", xero_deposit(
                    entity_id, posted_report, date, access_token=access_token, pfr=pfr))
        else:
            modules["deposit"] = {"status": "success"}
        if _auth_expired():
            return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        #Discrepancy
        if (posted_report.discrepancy_amount and
            (posted_report.discrepancy_amount > 0 or posted_report.discrepancy_amount < 0) and
            posted_report.discrepancy_type in ["surplus", "shortage"]):
            if _should_run("discrepancy"):
                _record("discrepancy", xero_discrepancy(
                    entity_id, posted_report, date, access_token=access_token, pfr=pfr))
        else:
            modules["discrepancy"] = {"status": "success"}
        if _auth_expired():
            return _aggregate_error_result(_pub_err.XERO_AUTH_EXPIRED)

        return {
            "modules": modules,
            "succeeded": total_succeeded,
            "failed": total_failed,
            "reasons": pfr.to_reason_bullets(),
            "reason_items": pfr.to_reason_items(),
        }
    except Exception as e:
        logger.error(f"Error in xero integrated module: {str(e)}", exc_info=True)
        return _aggregate_error_result("Xero rejected this entry")


def send_to_xero(
    entity_id,
    xero_org_id,
    date=None,
    *,
    report_date=None,
    change_deposit_amount=None,
    **kwargs,
):
    """
    Minimal compatibility shim. Keep the same response shape expected by legacy callsites.
    """
    resolved_date = report_date or date
    amount = change_deposit_amount or kwargs.get("amount")
    logger.info(
        f"send_to_xero called for entity {entity_id}, org {xero_org_id}, date {resolved_date}, amount {amount}"
    )
    transfer_id = str(uuid.uuid4())
    return (
        jsonify(
            {
                "status": "success",
                "message": "Xero sync staged",
                "bank_transfer_id": transfer_id,
                "entity_id": str(entity_id),
                "date": resolved_date,
            }
        ),
        200,
    )


def update_after_deposit_change(entity_id, date, amount):
    logger.info(
        f"update_after_deposit_change: entity={entity_id}, date={date}, amount={amount}"
    )
    try:
        normalized_date = _normalize_xero_date(date)
        if not normalized_date:
            logger.warning(
                f"update_after_deposit_change skipped due to invalid date: {date}"
            )
            return None

        report_date = datetime.strptime(normalized_date, "%Y-%m-%d").date()
        report_to_update = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == report_date,
        ).first()
        if not report_to_update:
            logger.info(
                f"update_after_deposit_change found no report for entity={entity_id}, date={report_date}"
            )
            return None

        updated_report = update_report_after_deposit_change(report_to_update, amount)
        if updated_report:
            logger.info(
                f"update_after_deposit_change updated report {updated_report.id} deposit to {amount}"
            )
        return updated_report
    except Exception as exc:
        logger.error(f"Error updating after deposit change: {str(exc)}")
        db.session.rollback()
        return None


def find_xero_bank_transfer_for_deposit(
    entity_id, date_str, amount, access_token
):
    """Look up the BankTransfer in Xero that was posted as a deposit for this
    date/amount.

    Returns ``(transfer_id, message)``. ``transfer_id`` is the BankTransferID on
    success, else ``None``; ``message`` is ``None`` on success and a short
    diagnostic on failure (for surfacing in API responses / toasts).
    """
    entity = Entity.query.filter(Entity.id == entity_id).first()
    if not entity:
        return None, "Entity not found"
    xero_date = _normalize_xero_date(date_str)
    if not xero_date:
        return None, f"Invalid date: {date_str!r}"
    try:
        report_date = datetime.strptime(xero_date, "%Y-%m-%d").date()
    except Exception as exc:
        return None, f"Could not parse date {xero_date!r}: {exc}"

    next_date = report_date + timedelta(days=1)
    # Use a half-open range so a transfer stored at any time-of-day on the
    # report date matches, regardless of how Xero serialised the timestamp.
    where_clause = (
        f"Date>=DateTime({report_date.year},{report_date.month},{report_date.day})"
        f"&&Date<DateTime({next_date.year},{next_date.month},{next_date.day})"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Xero-Tenant-Id": str(entity.xero_org_id),
        "Accept": "application/json",
    }
    try:
        response = requests.get(
            url=f"{current_app.config['XERO_API_BASE_URL']}/BankTransfers",
            headers=headers,
            params={"where": where_clause},
            timeout=(30, 60),
        )
    except Exception as exc:
        logger.error(f"find_xero_bank_transfer_for_deposit request error: {exc}")
        return None, f"Xero request failed: {exc}"

    if response.status_code not in (200, 201):
        body_snippet = (response.text or "")[:500]
        logger.warning(
            f"find_xero_bank_transfer_for_deposit: status={response.status_code} "
            f"where={where_clause!r} body={body_snippet}"
        )
        return None, (
            f"Xero GET /BankTransfers returned {response.status_code}"
            + (f": {body_snippet}" if body_snippet else "")
        )

    try:
        transfers = response.json().get("BankTransfers", []) or []
    except Exception as exc:
        return None, f"Could not parse Xero response: {exc}"

    expected_reference = f"MT{xero_date.replace('-', '')}Deposit"
    target_amount = float(amount or 0)

    for transfer in transfers:
        try:
            t_amount = float(transfer.get("Amount") or 0)
        except (TypeError, ValueError):
            continue
        if (transfer.get("Reference") == expected_reference
                and abs(t_amount - target_amount) < 0.005):
            return transfer.get("BankTransferID"), None

    for transfer in transfers:
        try:
            t_amount = float(transfer.get("Amount") or 0)
        except (TypeError, ValueError):
            continue
        if abs(t_amount - target_amount) < 0.005:
            return transfer.get("BankTransferID"), None

    candidate_summary = [
        {
            "BankTransferID": t.get("BankTransferID"),
            "Reference": t.get("Reference"),
            "Date": t.get("Date"),
            "Amount": t.get("Amount"),
        }
        for t in transfers[:10]
    ]
    logger.warning(
        f"find_xero_bank_transfer_for_deposit: no match for date={xero_date} "
        f"amount={target_amount} expected_reference={expected_reference!r}; "
        f"candidates={candidate_summary}"
    )
    return None, (
        f"No BankTransfer in Xero matched date {xero_date} and amount "
        f"{target_amount:g} (saw {len(transfers)} same-day transfer(s))"
    )


def update_xero_deposit_after_change(
    entity_id,
    transaction_date,
    previous_amount,
    new_amount,
    access_token=None,
):
    """Reconcile a published report's deposit in Xero after the user changed
    or removed the deposit amount.

    Xero's BankTransfers API is write-only — transfers cannot be updated or
    deleted via the API. The supported way to "undo" one is to post an
    offsetting BankTransfer in the reverse direction. So this helper:

      1. Verifies the original deposit transfer still exists in Xero (safety
         check against the local "published" flag drifting from Xero state).
      2. Posts a reversal BankTransfer (deposit bank → petty cash) for
         ``previous_amount`` on the same date.
      3. If ``new_amount > 0``, posts a replacement BankTransfer
         (petty cash → deposit bank) for the new amount on the same date.

    Returns ``(success, message)`` — ``message`` is ``None`` on success and
    a user-facing diagnostic on failure (suitable for a toast).
    """
    if previous_amount is None or previous_amount <= 0:
        return True, None

    if access_token is None:
        try:
            token_user = resolve_xero_token(entity_id, current_user)
        except RuntimeError:
            logger.warning(
                "update_xero_deposit_after_change: current_user unavailable"
            )
            return False, "Xero token unavailable in this session"
        if not token_user:
            logger.warning(
                "update_xero_deposit_after_change: no token user resolved"
            )
            return False, "This entity is not connected to Xero"
        if not ensure_valid_token(token_user):
            logger.warning(
                "update_xero_deposit_after_change: token refresh failed"
            )
            return False, "Xero token is expired and could not be refreshed"
        access_token = token_user.access_token

    transfer_id, lookup_msg = find_xero_bank_transfer_for_deposit(
        entity_id, transaction_date, previous_amount, access_token
    )
    if not transfer_id:
        return False, lookup_msg or "Original deposit transfer not found in Xero"

    pettycash = get_entity_account_settings(entity_id, "pettycash") or {}
    bank = get_entity_account_settings(entity_id, "bank") or {}
    pettycash_account = pettycash.get("xero_account_id")
    bank_account = bank.get("xero_account_id")
    if not pettycash_account or not bank_account:
        return False, (
            "Petty cash or deposit bank account is not configured for this "
            "entity — cannot post deposit correction to Xero"
        )

    xero_date = _normalize_xero_date(transaction_date) or ""
    date_clean = xero_date.replace("-", "")

    reversal_ok = create_bank_transfer(
        entity_id,
        transaction_date,
        bank_account=bank_account,
        withdrawal_amount=previous_amount,
        to_bank_account_id=pettycash_account,
        access_token=access_token,
        reference_override=f"MT{date_clean}DepositReversal",
    )
    if not reversal_ok:
        return False, (
            "Could not post reversal BankTransfer in Xero. The original "
            "deposit is still in Xero — check server logs for details."
        )

    if not new_amount or new_amount <= 0:
        return True, None

    replacement_ok = create_bank_transfer(
        entity_id,
        transaction_date,
        bank_account=pettycash_account,
        withdrawal_amount=new_amount,
        to_bank_account_id=bank_account,
        access_token=access_token,
        reference_override=f"MT{date_clean}DepositUpdated",
    )
    if not replacement_ok:
        return False, (
            "Reversal was posted in Xero, but the replacement deposit "
            "BankTransfer could not be created. Check server logs for details."
        )
    return True, None


def update_xero_report_sync(report_id, xero_response_text=None):
    try:
        sync = XeroReportSync.query.filter_by(report_id=report_id).first()
        if not sync:
            sync = XeroReportSync(report_id=report_id)
            db.session.add(sync)

        sync.sync_statuc = "completed"
        sync.completed_at = datetime.now()
        sync.xero_reponse_text = xero_response_text
        db.session.commit()
        return True
    except Exception as exc:
        logger.error(f"Failed to update Xero report sync row: {str(exc)}")
        db.session.rollback()
        return False


def _set_report_processing_status(
    report_id, status, user_id=None, publish_message=None
):
    report = Report.query.get(report_id)
    if not report:
        return None
    report.publishing_status = status
    if publish_message is not None:
        history = ReportHistory(
            report_id=report.id,
            company=report.company,
            user_id=user_id,
            action=publish_message,
            timestamp=datetime.now(),
        )
        db.session.add(history)
    return report


def process_xero_integration_background(
    entity_id, date, report_id, user_email, access_token, app, prior_status=None
):
    """
    Background function to process Xero integration without blocking the HTTP request.

    ``prior_status`` is the report's publishing_status *before* this run flipped it
    to "processing".  When it is "partially_published" we do a *selective
    re-publish*: only the parts that failed last time are retried, so already-
    published transactions are never posted to Xero again.
    """
    try:
        if app is None:
            raise RuntimeError("Flask application object is required for background publishing.")

        with app.app_context():
            posted_report = None
            try:
                posted_report = Report.query.get(report_id)
                if not posted_report:
                    logger.error(
                        f"Report {report_id} not found for background processing"
                    )
                    return

                user = User.query.filter_by(username=user_email).first()
                if not user:
                    logger.error(
                        f"User {user_email} not found for background processing"
                    )
                    posted_report.publishing_status = "failed"
                    db.session.commit()
                    return

                if not user.refresh_token:
                    logger.error(
                        f"User {user_email} has no refresh_token. Cannot refresh Xero token."
                    )
                    posted_report.publishing_status = "failed"
                    db.session.commit()
                    return

                if not ensure_valid_token(user):
                    logger.error(
                        f"User {user_email} token validation failed. Stopping background publish."
                    )
                    posted_report.publishing_status = "failed"
                    db.session.commit()
                    return

                # Selective re-publish: when re-publishing a partial report, only
                # retry the parts that didn't make it to Xero last time.
                retry_filter = None
                if prior_status == "partially_published":
                    recent_history = (
                        ReportHistory.query.filter(
                            ReportHistory.report_id == report_id,
                        )
                        .order_by(ReportHistory.timestamp.desc())
                        .limit(5)
                        .all()
                    )
                    items = _pub_err.latest_publish_reason_items(recent_history)
                    targets = _pub_err.retry_targets_from_items(items)
                    has_targets = bool(targets["modules"] or targets["expense_ids"])
                    if targets["unmappable"] or not has_targets:
                        logger.warning(
                            "Selective re-publish unavailable for report %s "
                            "(unmappable=%s, targets=%s) — running full re-publish",
                            report_id, targets["unmappable"], has_targets,
                        )
                    else:
                        retry_filter = {
                            "modules": targets["modules"],
                            "expense_ids": targets["expense_ids"],
                        }
                        logger.info(
                            "Selective re-publish for report %s: %s",
                            report_id, retry_filter,
                        )

                result = xero_integrated_module(
                    entity_id, date, posted_report, access_token=user.access_token,
                    retry_filter=retry_filter)
                selective = retry_filter is not None
                if isinstance(result, dict):
                    succeeded = result.get("succeeded", 0)
                    failed = result.get("failed", 0)
                    reasons = result.get("reasons", []) or []
                    reason_items = result.get("reason_items", []) or []
                    modules = result.get("modules", {})
                else:
                    succeeded, failed = 0, 1
                    reasons = ["Xero rejected this entry"]
                    reason_items = [{"text": "Xero rejected this entry"}]
                    modules = {}

                posted_report = Report.query.get(report_id)
                if not posted_report:
                    logger.error(
                        f"Report {report_id} not found after Xero integration")
                    return

                if failed == 0:
                    # Everything attempted landed in Xero (or nothing to publish).
                    posted_report.xero_integrated_yes = True
                    posted_report.publishing_status = "completed"
                    db.session.add(
                        ReportHistory(
                            report_id=posted_report.id,
                            company=posted_report.company,
                            user_id=user.id,
                            action="published",
                            timestamp=datetime.now(),
                        )
                    )
                else:
                    # Some or all transactions failed.  Distinguish a full
                    # failure from a partial publish (some succeeded, some not).
                    posted_report.xero_integrated_yes = False
                    if selective or succeeded > 0:
                        # Selective re-publish always keeps the report partial when
                        # anything remains: earlier parts are already live in Xero,
                        # so it can never regress to a full "failed".
                        posted_report.publishing_status = "partially_published"
                        logger.warning(
                            "Xero publish partial for report "
                            f"{posted_report.id}: {succeeded} ok, {failed} failed. "
                            f"Reasons: {reasons}")
                    else:
                        posted_report.publishing_status = "failed"
                        failed_modules = [
                            key for key, val in modules.items()
                            if val.get("status") != "success"
                        ]
                        logger.error(
                            "Xero integration failed for report "
                            f"{posted_report.id}. Failed modules: {', '.join(failed_modules)}")
                    db.session.add(
                        ReportHistory(
                            report_id=posted_report.id,
                            company=posted_report.company,
                            user_id=user.id,
                            action=PublishFailureReason.HISTORY_ACTION_LABEL,
                            new_value=json.dumps(reason_items),
                            timestamp=datetime.now(),
                        )
                    )
                db.session.commit()

            except Exception as exc:
                db.session.rollback()
                logger.error(
                    f"Background Xero integration failed: {str(exc)}",
                    exc_info=True)
                if posted_report:
                    posted_report.publishing_status = "failed"
                    try:
                        db.session.commit()
                    except Exception as history_error:
                        logger.error(
                            f"Failed to persist publish failure state for report {report_id}: {str(history_error)}"
                        )
                        db.session.rollback()
                        # Ensure we at least clear stuck processing status
                        try:
                            posted_report = Report.query.get(report_id)
                            if posted_report:
                                posted_report.publishing_status = "failed"
                                db.session.commit()
                        except Exception as fallback_error:
                            logger.error(
                                f"Failed to fallback publish failure state for report {report_id}: {str(fallback_error)}"
                            )
                            db.session.rollback()
            finally:
                try:
                    posted_report = Report.query.get(report_id)
                    if not posted_report:
                        return

                    if posted_report.publishing_status == "processing":
                        # If processing leaked here, never block forever.
                        posted_report.publishing_status = "failed"

                    db.session.commit()
                except Exception as exc:
                    logger.error(
                        f"Failed to finalize publishing status for report {report_id}: {str(exc)}"
                    )
                    db.session.rollback()
                    try:
                        posted_report = Report.query.get(report_id)
                        if posted_report and posted_report.publishing_status == "processing":
                            posted_report.publishing_status = "failed"
                            db.session.commit()
                    except Exception as fallback_error:
                        logger.error(
                            f"Failed fallback status cleanup for report {report_id}: {str(fallback_error)}"
                        )
                        db.session.rollback()
    except Exception as exc:
        logger.error(
            f"Critical error during background Xero integration: {str(exc)}",
            exc_info=True,
        )
