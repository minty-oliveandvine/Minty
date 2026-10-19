"""Petty Cash Settings' Xero account mapping: which of the company's Xero accounts and contacts the
petty cash publish posts to - shared by the Jinja page (``xero_account_mapping_post.py``) and the
Petty Cash API (``petty_cash_api/routes/settings.py``), so the two cannot disagree.

The choices are the page's own lists (``xero_mapping_form_context``: the database, synced from
Xero; a saved choice is always among them). Fixed 2026-10-16 (``tests/test_xero_mapping_state.py``):
a choice the lists do not offer is refused - it used to be looked up in Xero and, when Xero had
nothing either, saved as an "Unknown Account" / "Unknown Contact" row made up on the spot.
"""
from __future__ import annotations

import html

from loguru import logger

from blueprints.entity.services.settings import (COA_INCLUDED_TYPES, saveable_account_codes,
                                                 sync_chart_of_accounts_if_changed,
                                                 sync_contacts_if_changed_background,
                                                 sync_entity_account_xero_active,
                                                 sync_xero_accounts_to_db_background, sync_xero_coa_pettycash)
from blueprints.xero.services.settings import sync_entity_xero_status
from services.auth.token_service import ensure_valid_token, get_xero_token_user_for_entity, resolve_xero_token

#: (form key, label, kind, the context list it chooses from)
FIELDS = (
    ("main_bank", "Petty Cash Account", "account", "bank_accounts"),
    ("deposit_bank", "Deposit Bank Account", "account", "bank_accounts"),
    ("cashsale_account", "Cash Sales account code", "account", "cashsale_account"),
    ("cashsale_contact", "Cash Sales contact", "contact", "contacts"),
    ("owners_account", "Director Personal Account code", "account", "owners_account"),
    ("owners_contact", "Director / Responsible person", "contact", "contacts"),
    ("discrepancy_bank", "Discrepancy Bank Account", "account", "bank_accounts"),
    ("discrepancy_account", "Discrepancy account code", "account", "discrepancy_account"),
    ("discrepancy_contact", "Discrepancy contact", "contact", "contacts"),
)
#: the context's saved choice for each field
DEFAULTS = {
    "main_bank": "main_bank_account_default", "deposit_bank": "deposit_bank_account_default",
    "cashsale_account": "cashsale_account_default", "cashsale_contact": "cashsale_contact_default",
    "owners_account": "owners_account_default", "owners_contact": "owners_contact_default",
    "discrepancy_bank": "discrepancy_bank_default", "discrepancy_account": "discrepancy_account_default",
    "discrepancy_contact": "discrepancy_contact_default",
}


def choices(entity_id, org) -> dict:
    """The page's lists and saved choices (``build_xero_mapping_form_context``; no Xero call)."""
    from blueprints.entity.services.xero_mapping_form_context import build_xero_mapping_form_context

    return build_xero_mapping_form_context(entity_id, org, False)


def _offered(option, kind, value) -> bool:
    if kind == "contact":
        return option.get("ContactID") == value
    # bank selects post the AccountID, the others the code; either names the account
    return value in (option.get("AccountID"), option.get("Code"))


def unoffered(entity_id, org, values: dict, context: dict | None = None) -> list[str]:
    """The labels of the fields whose chosen value is not among that field's options."""
    context = context or choices(entity_id, org)
    labels = []
    for key, label, kind, listed in FIELDS:
        value = values.get(key)
        if value and not any(_offered(o, kind, value) for o in context.get(listed) or []):
            labels.append(label)
    return labels


def unoffered_sentence(labels) -> str:
    return " ".join(f"Choose the {label} from the list." for label in labels)


def read(entity_id, org) -> list[dict]:
    """The mapping for the Petty Cash API: one entry per field the person chooses (the Discrepancy
    Bank Account mirrors the Petty Cash Account, as on the page), with its options and choice."""
    context = choices(entity_id, org)
    fields = []
    for key, label, kind, listed in FIELDS:
        if key == "discrepancy_bank":
            continue
        id_key = "ContactID" if kind == "contact" else "AccountID"
        saved = context.get(DEFAULTS[key]) or {}
        fields.append({
            "key": key,
            "label": label,
            "kind": kind,
            "options": [
                {"id": o.get(id_key), "name": o.get("Name") or "", **({} if kind == "contact" else {"code": o.get("Code") or ""})}
                for o in context.get(listed) or [] if o.get(id_key)
            ],
            "selected": saved.get(id_key),
        })
    return fields


# --- the connection and the account codes (moved from routes/settings.py, 2026-10-16) -------------


def disconnected(org, user) -> bool:
    """Whether the company was connected to a Xero organisation but is no longer live. Only a
    company that is SUPPOSED to be connected (``xero_org_id`` set) counts. The authoritative live
    check first: ``sync_entity_xero_status`` asks Xero's /connections and reconciles
    ``org.status`` (a connection revoked on Xero's website can leave the token valid)."""
    from models.db import Entity

    if org is None or not getattr(org, "xero_org_id", None):
        return False
    token_resolved = resolve_xero_token(org.id, user) is not None
    if token_resolved:
        try:
            sync_entity_xero_status(org.id)
            refreshed = Entity.query.get(org.id)
            if refreshed is not None:
                org = refreshed
        except Exception as sync_error:
            logger.warning("Xero live status sync failed for entity %s: %s", org.id, sync_error)
    return not (token_resolved and getattr(org, "status", None) != "disconnected")


def is_live(org, user) -> bool:
    """A live Xero connection: never connected, or disconnected inside Minty (``xero_org_id``
    nulled), is not live either."""
    return bool(org is not None and getattr(org, "xero_org_id", None)) and not disconnected(org, user)


def refresh_from_xero(org, user, app) -> None:
    """What opening the settings does on a live company: accounts (every type) and contacts are
    refreshed from Xero in the background, the chart of accounts compared now, and the Petty Cash
    code list backfilled from ``account_info`` (no Xero call), so the lists are whole on first
    load. Failures are logged and the page still opens."""
    try:
        token_user = get_xero_token_user_for_entity(org.id)
        if token_user and ensure_valid_token(token_user):
            sync_xero_accounts_to_db_background(org.id, token_user.access_token, org.xero_org_id, flask_app=app)
            sync_contacts_if_changed_background(org.id, token_user.access_token, org.xero_org_id, flask_app=app)
            sync_chart_of_accounts_if_changed(org.id, token_user.access_token, org.xero_org_id, user_id=str(user.id))
    except Exception as rec_err:
        logger.warning("Petty Cash settings: chart sync skipped for %s: %s", org.id, rec_err)
    try:
        sync_xero_coa_pettycash(org.id, org.xero_org_id)
    except Exception as backfill_err:
        logger.warning("Petty Cash settings: petty cash CoA backfill skipped entity={}: {}", org.id, backfill_err)


def account_codes(entity_id) -> list[dict]:
    """The Petty Cash account codes in code order, ``{code, name, selected}`` - ``selected`` is
    ``entity_account_xero.is_active``: the codes an expense line may use."""
    from models.db import AccountInfo, EntityAccountXero, db
    from services.app_runtime.legacy.xero_service import account_info_to_xero_format

    rows = (
        db.session.query(AccountInfo, EntityAccountXero.is_active)
        .join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
        .filter(AccountInfo.entity_id == entity_id, AccountInfo.type.in_(list(COA_INCLUDED_TYPES)))
        .order_by(AccountInfo.xero_code)
        .all()
    )
    codes = []
    for account, is_active in rows:
        entry = account_info_to_xero_format(account)
        codes.append({"code": entry.get("Code") or "", "name": html.unescape(entry.get("Name", "") or ""),
                      "selected": bool(is_active)})
    return codes


def save_account_codes(org, codes) -> str | None:
    """Tick exactly ``codes``. Returns the refusal, or None. At least one of the company's own
    codes stays ticked - an expense line can use only the ticked codes - unless it has none at all."""
    saveable = saveable_account_codes(org.id)
    posted = {str(c).strip() for c in codes or [] if c and str(c).strip()}
    if saveable and not posted & saveable:
        return "Pick at least one account code."
    sync_entity_account_xero_active(org.id, org.xero_org_id, sorted(posted))
    return None
