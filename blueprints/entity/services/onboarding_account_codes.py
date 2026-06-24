"""Token-authenticated petty-cash Account Code settings for onboarding (Step 5).

Mirrors the Petty Cash CoA section of ``entity_settings_entity`` but for the
reduced set of fields the onboarding UI collects (5 account mappings + the
expense-code selection). Contact mappings and the discrepancy bank are NOT
captured here — the user completes those later on the full Settings page.
"""

from __future__ import annotations

from loguru import logger

from blueprints.entity.services.settings import (
    COA_INCLUDED_TYPES,
    sync_entity_account_xero_active,
    sync_expense_account_info_from_xero,
)
from blueprints.entity.services.xero_account_mapping_post import (
    _resolve_account_id, _resolve_contact_id)
from models.db import (AccountInfo, EntityAccountXero, EntityPettycashSettings,
                       Entity, XeroContactSync, db)
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.helpers.xero import mask_account_number
from services.helpers.xero_bridge import (get_accounts_from_xero,
                                          get_contacts_from_xero)
from services.permission_policy import Permission, has_permission_by_user_id

# Must mirror the /api/entity/<id>/xero-data endpoint (which actually populates
# the Settings mapping dropdowns), NOT build_xero_mapping_form_context. Owners is
# liability-only by design, and only owners drops system accounts.
_OWNERS_TYPES = ("CURRENT", "CURRLIAB", "NONCURRENT", "TERMLIAB", "LIABILITY")
_CASHSALE_TYPES = ("SALES", "REVENUE", "INCOME")
_DISCREPANCY_TYPES = ("EXPENSE", "DIRECTCOSTS")


def _is_system(acc) -> bool:
    sa = acc.get("SystemAccount")
    return isinstance(sa, str) and sa.strip() != ""


def _label(acc) -> str:
    code = str(acc.get("Code") or "").strip()
    name = acc.get("Name") or ""
    return f"{code} · {name}" if code else name


def _bank_label(acc) -> str:
    """Bank accounts show the partially-masked account number (matches Settings)."""
    name = acc.get("Name") or ""
    masked = mask_account_number(acc.get("BankAccountNumber"))
    return f"{name} - {masked}" if masked else name


def _code_sort_key(acc):
    """Sort by account code: numeric codes first (in numeric order), then others."""
    code = str(acc.get("Code") or "").strip()
    try:
        return (0, int(code), "")
    except ValueError:
        return (1, 0, code.lower())


def _account_token_user(entity_id):
    """Return (entity, token_user) when the entity has a usable Xero token, else (entity, None)."""
    entity = Entity.query.get(entity_id)
    if not entity or not entity.xero_org_id:
        return entity, None
    token_user = get_xero_token_user_for_entity(entity_id)
    if token_user and ensure_valid_token(token_user):
        return entity, token_user
    return entity, None


def get_account_code_options(user_id, entity_id):
    """Return the Xero-sourced option lists + current selections for Step 5.

    Returns ``(data, status)``. 409 when the entity isn't connected to Xero yet
    (the account lists only exist after a real Xero connection in Step 3).
    """
    if not has_permission_by_user_id(user_id, Permission.COA_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    entity, token_user = _account_token_user(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if token_user is None:
        return {
            "error": "Connect to Xero first to load account codes.",
            "connected": False,
        }, 409

    accounts = get_accounts_from_xero(
        token_user.access_token,
        entity.xero_org_id,
        where='Status=="ACTIVE"',
        order="Code",
        token_validated=True,
    ) or []

    # Mapping dropdowns come from the live Xero list — same source the original
    # /api/entity/<id>/xero-data uses. AccountInfo.status now tracks the petty
    # cash ticked selection (sync_expense_account_info_from_xero flips
    # non-selected codes to INACTIVE), so a DB-active filter would silently hide
    # Director / Cash Sale / Discrepancy codes after any save.
    def opts(types, *, bank=False, drop_system=False):
        rows = [
            a for a in accounts
            if a.get("Type") in types and a.get("AccountID")
            and (not drop_system or not _is_system(a))
        ]
        rows.sort(key=_code_sort_key)
        make_label = _bank_label if bank else _label
        return [{"id": a.get("AccountID"), "label": make_label(a)} for a in rows]

    bank_accounts = opts(("BANK",), bank=True)
    cash_sale_accounts = opts(_CASHSALE_TYPES)
    director_accounts = opts(_OWNERS_TYPES, drop_system=True)
    discrepancy_accounts = opts(_DISCREPANCY_TYPES)

    xero_contacts = get_contacts_from_xero(
        token_user.access_token,
        entity.xero_org_id,
        order="Name ASC",
        token_validated=True,
    ) or []
    contacts = []
    _seen_contact_ids = set()
    for c in xero_contacts:
        cid = c.get("ContactID")
        if not cid or cid in _seen_contact_ids:
            continue
        _seen_contact_ids.add(cid)
        contacts.append({"id": cid, "label": c.get("Name") or ""})

    expense_codes = []
    for a in accounts:
        if a.get("Type") not in COA_INCLUDED_TYPES or _is_system(a):
            continue
        code = str(a.get("Code") or "").strip()
        if not code:
            continue
        expense_codes.append({"code": code, "name": a.get("Name") or ""})
    expense_codes.sort(key=lambda e: _code_sort_key({"Code": e["code"]}))

    selected_rows = (
        db.session.query(AccountInfo.xero_code)
        .join(EntityAccountXero, AccountInfo.id == EntityAccountXero.account_id)
        .filter(
            AccountInfo.entity_id == entity_id,
            AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
            EntityAccountXero.is_active.is_(True),
        )
        .all()
    )
    selected_codes = [r[0] for r in selected_rows if r[0]]
    inactive_count = (
        db.session.query(EntityAccountXero)
        .join(AccountInfo, AccountInfo.id == EntityAccountXero.account_id)
        .filter(
            AccountInfo.entity_id == entity_id,
            AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
            EntityAccountXero.is_active.is_(False),
        )
        .count()
    )
    default_all = not selected_codes and inactive_count == 0

    settings_row = EntityPettycashSettings.query.filter_by(
        entity_id=entity_id
    ).first()

    def _xero_id(account_id):
        if not account_id:
            return None
        acc = AccountInfo.query.get(account_id)
        return acc.xero_account_id if acc else None

    mapping_defaults = {
        "pettycash": _xero_id(getattr(settings_row, "pettycash_account_id", None)),
        "deposit": _xero_id(getattr(settings_row, "bank_account_id", None)),
        "director": _xero_id(getattr(settings_row, "director_account_id", None)),
        "cash_sale": _xero_id(getattr(settings_row, "cash_sale_account_id", None)),
        "discrepancy": _xero_id(getattr(settings_row, "discrepancy_account_id", None)),
    }

    def _xero_contact_id(contact_id):
        if not contact_id:
            return None
        c = XeroContactSync.query.get(contact_id)
        return c.xero_contact_id if c else None

    contact_defaults = {
        "director": _xero_contact_id(getattr(settings_row, "director_contact_id", None)),
        "cash_sale": _xero_contact_id(getattr(settings_row, "cash_sale_contact_id", None)),
        "discrepancy": _xero_contact_id(getattr(settings_row, "discrepancy_contact_id", None)),
    }

    return {
        "connected": True,
        "bank_accounts": bank_accounts,
        "cash_sale_accounts": cash_sale_accounts,
        "director_accounts": director_accounts,
        "discrepancy_accounts": discrepancy_accounts,
        "expense_codes": expense_codes,
        "selected_codes": selected_codes,
        "default_all": default_all,
        "mapping_defaults": mapping_defaults,
        "contacts": contacts,
        "contact_defaults": contact_defaults,
    }, 200


def save_account_codes(user_id, entity_id, *, expense_codes, mapping):
    """Persist the Step 5 selections.

    ``expense_codes`` is the list of Xero account codes to activate for petty
    cash. ``mapping`` is a dict of Xero account ids keyed by pettycash / deposit
    / director / cash_sale / discrepancy (any subset; missing keys are skipped).
    Returns ``(data, status)``.
    """
    if not has_permission_by_user_id(user_id, Permission.COA_UPDATE, entity_id):
        return {"error": "Access denied"}, 403
    if not isinstance(expense_codes, list):
        return {"error": "expense_codes must be an array"}, 400
    mapping = mapping or {}

    pettycash_sel = (mapping.get("pettycash") or "").strip()
    deposit_sel = (mapping.get("deposit") or "").strip()
    if pettycash_sel and deposit_sel and pettycash_sel == deposit_sel:
        return {
            "error": "Petty Cash Account and Deposit Bank Account cannot be the same.",
        }, 400

    entity, token_user = _account_token_user(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if token_user is None:
        return {
            "error": "Connect to Xero first to save account codes.",
            "connected": False,
        }, 409

    xero_org_id = entity.xero_org_id

    try:
        settings_row = EntityPettycashSettings.query.filter_by(
            entity_id=entity_id
        ).first()
        if settings_row is None:
            settings_row = EntityPettycashSettings(entity_id=entity_id)
            db.session.add(settings_row)

        field_specs = [
            ("pettycash", "pettycash_account_id", "BANK"),
            ("deposit", "bank_account_id", "BANK"),
            ("director", "director_account_id", "LIABILITY"),
            ("cash_sale", "cash_sale_account_id", "REVENUE"),
            ("discrepancy", "discrepancy_account_id", "EXPENSE"),
        ]
        for key, column, fallback_type in field_specs:
            xero_account_id = (mapping.get(key) or "").strip() if mapping.get(key) else ""
            if not xero_account_id:
                continue
            resolved = _resolve_account_id(
                entity_id, xero_account_id, xero_org_id, fallback_type=fallback_type
            )
            if resolved:
                setattr(settings_row, column, resolved)

        # No discrepancy-bank field in onboarding; default it to the petty cash
        # bank (as Settings does) — it's required by the completeness check.
        if settings_row.pettycash_account_id:
            settings_row.discrepancy_bank_account_id = settings_row.pettycash_account_id

        db.session.commit()

        sync_expense_account_info_from_xero(
            entity_id,
            token_user.access_token,
            xero_org_id,
            selected_account_codes=expense_codes,
        )
        db.session.commit()
        sync_entity_account_xero_active(entity_id, xero_org_id)

        logger.info(
            "save_account_codes: entity=%s expense_codes=%s mapping_keys=%s",
            entity_id, len(expense_codes),
            [k for k in mapping if mapping.get(k)],
        )
        return {"ok": True, "expense_codes": expense_codes}, 200
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.exception(f"save_account_codes failed entity={entity_id}: {exc}")
        return {"error": "Failed to save account codes. Please try again."}, 500


def save_contacts(user_id, entity_id, contacts):
    """Persist the Step 6 (Others) contact mappings into entity_pettycash_settings.

    ``contacts`` is a dict of Xero contact ids keyed by director / cash_sale /
    discrepancy (any subset; missing keys are skipped). Resolves each to a local
    XeroContactSync.id via the shared ``_resolve_contact_id``. Returns
    ``(data, status)``.
    """
    if not has_permission_by_user_id(user_id, Permission.COA_UPDATE, entity_id):
        return {"error": "Access denied"}, 403
    contacts = contacts or {}

    entity, token_user = _account_token_user(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if token_user is None:
        return {
            "error": "Connect to Xero first to save contacts.",
            "connected": False,
        }, 409

    xero_org_id = entity.xero_org_id

    try:
        settings_row = EntityPettycashSettings.query.filter_by(
            entity_id=entity_id
        ).first()
        if settings_row is None:
            settings_row = EntityPettycashSettings(entity_id=entity_id)
            db.session.add(settings_row)

        contact_specs = [
            ("director", "director_contact_id"),
            ("cash_sale", "cash_sale_contact_id"),
            ("discrepancy", "discrepancy_contact_id"),
        ]
        for key, column in contact_specs:
            xero_contact_id = (contacts.get(key) or "").strip() if contacts.get(key) else ""
            if not xero_contact_id:
                continue
            resolved = _resolve_contact_id(entity_id, xero_contact_id, xero_org_id)
            if resolved:
                setattr(settings_row, column, resolved)

        db.session.commit()
        logger.info(
            "save_contacts: entity=%s contact_keys=%s",
            entity_id, [k for k in contacts if contacts.get(k)],
        )
        return {"ok": True}, 200
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error("save_contacts failed entity=%s: %s", entity_id, exc)
        return {"error": "Failed to save contacts. Please try again."}, 500


def create_contact(user_id, entity_id, name):
    """Create a brand-new Xero contact during onboarding (Step 6 / Others).

    Pushes a new contact to the entity's connected Xero org and mirrors it into
    ``xero_contact_sync`` (via ``create_xero_contact``), so it immediately shows
    up in the contact dropdowns. Returns ``({"id", "label"}, status)`` for the
    new contact, which the frontend can append to its options and select.

    Gated on CONTACT_CREATE (the same permission the report/expense module's
    create-contact path uses), not COA_UPDATE — creating a contact is a distinct
    action from mapping existing ones. The entity must have a live Xero token.
    """
    if not has_permission_by_user_id(user_id, Permission.CONTACT_CREATE, entity_id):
        return {"error": "Access denied"}, 403

    name = (name or "").strip()
    if not name:
        return {"error": "Contact name is required."}, 400

    entity, token_user = _account_token_user(entity_id)
    if entity is None:
        return {"error": "Entity not found"}, 404
    if token_user is None:
        return {
            "error": "Connect to Xero first to create contacts.",
            "connected": False,
        }, 409

    from blueprints.xero.services.publish import create_xero_contact

    new_contact_id = create_xero_contact(
        entity_id, name, token_user.access_token, entity.xero_org_id
    )
    if not new_contact_id:
        # create_xero_contact logs the Xero-side detail; surface a clean message.
        return {"error": "Failed to create contact in Xero. Please try again."}, 502

    logger.info(
        "create_contact: entity=%s created xero_contact=%s", entity_id, new_contact_id
    )
    return {"id": new_contact_id, "label": name}, 201
