"""Persist Xero petty cash / sales / discrepancy account mapping from a POST form."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from flask import flash, jsonify, redirect, request, url_for
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.entity.services.settings import \
    sync_expense_account_info_from_xero
from blueprints.xero.services.settings import get_account, get_contact
from models.db import (AccountInfo, CountryInfo, CurrencyInfo, Entity,
                       EntityPettycashSettings, XeroContactSync, db)
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)


def _mapping_redirect(entity_id: str, _from: str | None, *, return_view: str):
    bills_kw = {"from": _from} if _from == "bills" else {}
    if return_view == "entity_settings_entity":
        return redirect(url_for("entity_settings_entity", org_id=entity_id, **bills_kw))
    return redirect(url_for("entity_settings", entity_id=entity_id, **bills_kw))


def apply_country_currency_selection(entity, form) -> None:
    """Persist the Country / Currency dropdown selections onto the entity FKs.

    The settings dropdowns submit the ISO alpha-2 ``country_code`` (the
    country_info PK) and the ``currency_id`` registry uuid; a legacy
    ``country_id`` field is accepted as a code alias so older forms keep
    working. An explicit currency selection wins; when only the country is
    supplied, its registry currency is derived. Values that don't resolve
    against country_info / currency_info are ignored (never written raw —
    both columns are FKs). Shared by the integration minimal save, the
    entity-tab save, and the Xero mapping save.
    """
    country_info = None
    country_code = (
        form.get("country_code") or form.get("country_id") or ""
    ).strip()
    if country_code:
        country_info = CountryInfo.query.get(country_code.upper())
    if country_info:
        entity.country_code = country_info.country_code

    currency_id = (form.get("currency_id") or "").strip()
    currency_info = CurrencyInfo.query.get(currency_id) if currency_id else None
    if currency_info is None and country_info and country_info.currency_id:
        currency_info = CurrencyInfo.query.get(country_info.currency_id)
    if currency_info:
        entity.currency_id = currency_info.id
        entity.currency_format = currency_info.symbol or "$"


def _trunc(value, max_len):
    if not value:
        return value
    s = str(value)
    return s[:max_len] if len(s) > max_len else s


def _resolve_account_id(
    entity_id: str,
    xero_account_id: str,
    xero_org_id: str,
    *,
    fallback_type: str,
) -> Optional[str]:
    """Return the local AccountInfo.id for a given Xero account selection.

    The form submits the Xero AccountID for bank selects and the Xero Code for
    non-bank selects (cash sales / owners / discrepancy account), so the form
    value can match either AccountInfo.xero_account_id or AccountInfo.xero_code.
    We try both before falling back to a live Xero fetch + insert (only used
    when the entity is still connected and the row is genuinely missing).
    """
    existing = AccountInfo.query.filter_by(
        entity_id=entity_id, xero_account_id=xero_account_id
    ).first()
    if existing:
        return existing.id

    existing_by_code = AccountInfo.query.filter_by(
        entity_id=entity_id, xero_code=xero_account_id
    ).first()
    if existing_by_code:
        return existing_by_code.id

    try:
        fetched = get_account(xero_account_id, entity_id, xero_org_id)
    except Exception as exc:
        logger.warning(
            "resolve_account_id: Xero fetch failed entity=%s xero_id=%s: %s",
            entity_id, xero_account_id, exc,
        )
        fetched = None

    def _add_or_existing(values: dict) -> Optional[str]:
        """Insert the account, or return the existing row's id if a concurrent
        sync inserted it first. The unique constraint on
        (entity_id, xero_account_id) makes the lost-race insert raise
        IntegrityError; a savepoint keeps the outer transaction usable."""
        try:
            with db.session.begin_nested():
                row = AccountInfo(**values)
                db.session.add(row)
            return row.id
        except IntegrityError:
            existing_row = AccountInfo.query.filter_by(
                entity_id=values["entity_id"],
                xero_account_id=values["xero_account_id"],
            ).first()
            if existing_row:
                logger.info(
                    "resolve_account_id: insert raced a concurrent sync; "
                    "using existing row entity=%s xero_id=%s",
                    values["entity_id"], values["xero_account_id"],
                )
                return existing_row.id
            raise

    if not fetched:
        logger.warning(
            "resolve_account_id: creating placeholder for missing account "
            "entity=%s xero_id=%s",
            entity_id, xero_account_id,
        )
        return _add_or_existing({
            "id": str(uuid.uuid4()),
            "entity_id": entity_id,
            "type": fallback_type,
            "name": "Unknown Account",
            "xero_account_id": xero_account_id,
            "xero_code": "",
            "status": "ACTIVE",
        })

    description = fetched.get("Description") or "No Description"
    return _add_or_existing({
        "id": str(uuid.uuid4()),
        "entity_id": entity_id,
        "type": _trunc(fetched.get("Type") or fallback_type, 50),
        "name": _trunc(fetched.get("Name") or "Unknown Account", 80),
        "xero_account_id": fetched.get("AccountID") or xero_account_id,
        "xero_code": _trunc(fetched.get("Code") or "", 50),
        "status": _trunc(fetched.get("Status") or "ACTIVE", 50),
        "class_type": _trunc(fetched.get("Class") or "", 50),
        "bank_account_number": _trunc(fetched.get("BankAccountNumber") or "", 50),
        "bank_account_type": _trunc(fetched.get("BankAccountType") or "", 50),
        "description": _trunc(description, 255),
    })


def _resolve_contact_id(
    entity_id: str,
    xero_contact_id: str,
    xero_org_id: str,
) -> Optional[str]:
    """Return the local XeroContactSync.id for a given Xero contact selection."""
    existing = XeroContactSync.query.filter_by(
        entity_id=entity_id, xero_contact_id=xero_contact_id
    ).first()
    if existing:
        return existing.id

    try:
        fetched = get_contact(xero_contact_id, entity_id, xero_org_id)
    except Exception as exc:
        logger.warning(
            "resolve_contact_id: Xero fetch failed entity=%s xero_id=%s: %s",
            entity_id, xero_contact_id, exc,
        )
        fetched = None

    name = (fetched or {}).get("Name") or "Unknown Contact"
    new_row = XeroContactSync(
        id=str(uuid.uuid4()),
        entity_id=entity_id,
        xero_contact_id=xero_contact_id,
        xero_org_id=str(xero_org_id) if xero_org_id else None,
        name=_trunc(name, 150),
        category=None,
    )
    db.session.add(new_row)
    db.session.flush()
    return new_row.id


def process_xero_account_mapping_post(
    entity_id: str,
    *,
    return_view: str,
    defer_success_redirect: bool = False,
) -> Any:
    """Apply mapping from ``request.form``.

    Returns ``None`` when no ``main_bank`` field was submitted (caller may continue).
    With ``defer_success_redirect`` a successful save also returns ``None``: the caller
    (Petty Cash Settings) saves the ticked codes next and picks the redirect. Otherwise
    returns a Flask ``Response`` (redirect or JSON error).
    """

    _from = request.form.get("_from") or request.args.get("from")
    if not request.form.get("main_bank"):
        return None
    try:
        main_bank = request.form.get("main_bank")
        deposit_bank = request.form.get("deposit_bank")
        cashsale_account = request.form.get("cashsale_account")
        cashsale_contact = request.form.get("cashsale_contact")
        owners_account = request.form.get("owners_account")
        owners_contact = request.form.get("owners_contact")
        discrepancy_bank = request.form.get("discrepancy_bank")
        discrepancy_account = request.form.get("discrepancy_account")
        discrepancy_contact = request.form.get("discrepancy_contact")

        if main_bank and deposit_bank and main_bank == deposit_bank:
            flash(
                "Main Bank Account and Deposit Bank Account can't be the same — please pick a different one for each.", "danger",
            )
            return _mapping_redirect(entity_id, _from, return_view=return_view)

        # Collect any missing fields and report them by name, so the user knows
        # exactly which setting to fill instead of a generic "enter all" error.
        required_fields = [
            (main_bank, "Petty Cash Account"),
            (deposit_bank, "Deposit Bank Account"),
            (cashsale_account, "Cash Sales account code"),
            (cashsale_contact, "Cash Sales contact"),
            (owners_account, "Director Personal Account code"),
            (owners_contact, "Director / Responsible person"),
            (discrepancy_bank, "Discrepancy Bank Account"),
            (discrepancy_account, "Discrepancy account code"),
            (discrepancy_contact, "Discrepancy contact"),
        ]
        missing = [label for value, label in required_fields if not value]
        if missing:
            flash("Please select: " + ", ".join(missing), "danger")
            return _mapping_redirect(entity_id, _from, return_view=return_view)

        entity = Entity.query.get_or_404(entity_id)

        apply_country_currency_selection(entity, request.form)

        has_existing_settings = (
            EntityPettycashSettings.query.filter_by(entity_id=entity_id).first()
            is not None
        )

        xero_org_id = entity.xero_org_id

        pettycash_account_id = _resolve_account_id(
            entity_id, main_bank, xero_org_id, fallback_type="BANK"
        )
        bank_account_id = _resolve_account_id(
            entity_id, deposit_bank, xero_org_id, fallback_type="BANK"
        )
        cash_sale_account_id = _resolve_account_id(
            entity_id, cashsale_account, xero_org_id, fallback_type="REVENUE"
        )
        discrepancy_bank_account_id = _resolve_account_id(
            entity_id, discrepancy_bank, xero_org_id, fallback_type="BANK"
        )
        discrepancy_account_id = _resolve_account_id(
            entity_id, discrepancy_account, xero_org_id, fallback_type="EXPENSE"
        )
        director_account_id = _resolve_account_id(
            entity_id, owners_account, xero_org_id, fallback_type="LIABILITY"
        )

        cash_sale_contact_id = _resolve_contact_id(
            entity_id, cashsale_contact, xero_org_id
        )
        director_contact_id = _resolve_contact_id(
            entity_id, owners_contact, xero_org_id
        )
        discrepancy_contact_id = _resolve_contact_id(
            entity_id, discrepancy_contact, xero_org_id
        )

        # Pair each resolved id with the field label and the value the user
        # submitted, so an unresolved item can be named specifically (e.g.
        # "Cash Sales account code (48001)") instead of a vague "one or more".
        resolution_checks = [
            (pettycash_account_id, "Petty Cash Account", main_bank),
            (bank_account_id, "Deposit Bank Account", deposit_bank),
            (cash_sale_account_id, "Cash Sales account code", cashsale_account),
            (discrepancy_bank_account_id, "Discrepancy Bank Account", discrepancy_bank),
            (discrepancy_account_id, "Discrepancy account code", discrepancy_account),
            (director_account_id, "Director Personal Account code", owners_account),
            (cash_sale_contact_id, "Cash Sales contact", cashsale_contact),
            (director_contact_id, "Director / Responsible person", owners_contact),
            (discrepancy_contact_id, "Discrepancy contact", discrepancy_contact),
        ]
        unresolved = [
            f"{label} ({value})" if value else label
            for resolved_id, label, value in resolution_checks
            if not resolved_id
        ]
        if unresolved:
            db.session.rollback()
            flash(
                "Couldn't find the following in your Xero data: "
                + "; ".join(unresolved)
                + ". They may not have synced from Xero yet — "
                "please retry once the Xero sync has finished.",
                "danger",
            )
            return _mapping_redirect(entity_id, _from, return_view=return_view)

        settings_row = EntityPettycashSettings.query.filter_by(
            entity_id=entity_id
        ).first()
        if settings_row is None:
            settings_row = EntityPettycashSettings(entity_id=entity_id)
            db.session.add(settings_row)

        settings_row.pettycash_account_id = pettycash_account_id
        settings_row.bank_account_id = bank_account_id
        settings_row.cash_sale_account_id = cash_sale_account_id
        settings_row.discrepancy_bank_account_id = discrepancy_bank_account_id
        settings_row.discrepancy_account_id = discrepancy_account_id
        settings_row.director_account_id = director_account_id
        settings_row.cash_sale_contact_id = cash_sale_contact_id
        settings_row.director_contact_id = director_contact_id
        settings_row.discrepancy_contact_id = discrepancy_contact_id

        db.session.commit()

        if defer_success_redirect:
            # Petty Cash Settings saves the ticked codes (and country/currency) right after
            # this returns, and decides where to go. Switching every code on here, or
            # returning the first save's dashboard redirect, threw the ticks away.
            logger.info(f"Entity settings mapping saved for entity ID: {entity_id}")
            return None

        try:
            token_user = get_xero_token_user_for_entity(entity_id)
            if ensure_valid_token(token_user):
                sync_expense_account_info_from_xero(
                    entity_id, token_user.access_token, entity.xero_org_id
                )
                db.session.commit()
                logger.info(
                    "entity_settings POST: expense account_info synced for entity %s",
                    entity_id,
                )
        except Exception as exc:
            db.session.rollback()
            logger.warning(
                "entity_settings POST: expense account_info sync failed entity=%s: %s",
                entity_id,
                exc,
            )

        flash("Entity settings saved!", "success")
        if entity_id:
            logger.info(f"Entity settings updated for entity ID: {entity_id}")

        if has_existing_settings:
            return _mapping_redirect(entity_id, _from, return_view=return_view)
        else:
            return redirect(
                url_for(
                    "entity.report_dashboard",
                    id=entity_id,
                    success="true",
                )
            )
    except Exception as e:
        db.session.rollback()
        logger.exception("Error updating Xero account mapping: {}", e)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while saving those settings. Mind trying again?",
                }
            ),
            500,
        )
