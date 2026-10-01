"""Re-check whether stored Xero publish failures have since been resolved.

When a report is only *partially published*, each failure is stored as a
structured item (see ``PublishFailureReason.to_reason_items``).  This module
re-checks each item against the *current* state so the report-history page can
show, per reason, whether the user has fixed it — e.g. edited an expense to use
a valid contact, or un-archived the contact in Xero.

Design goals:
  * **Live Xero is the source of truth** for contact status.  A contact the user
    just un-archived (or re-picked) is ACTIVE immediately, even if the local
    ``xero_contact_sync`` table hasn't caught up.  We look the contact up live
    (``GET /Contacts/{id}``), cached per contact per render, and only fall back
    to the synced table if Xero is unreachable.
  * **Works for legacy rows too.**  Failures recorded before structured metadata
    existed only carry the reason text (e.g. "Expense 'Coffee' — contact is
    archived in Xero").  We recover the target expense by name + ``report_id`` so
    those rows can resolve as well.

Account validity stays DB-only: archived accounts are removed from
``account_info`` on sync, so an ``status == "ACTIVE"`` row reflects Xero. Petty
cash's code ticks never write ``status`` (they live on
``entity_account_xero.is_active``), so an unticked code still publishes.
"""

from __future__ import annotations

import logging
import re

from models.db import AccountInfo, ShopExpense, XeroContactSync
from services.helpers.xero_bridge import (get_entity_account_settings,
                                          get_entity_contact_settings,
                                          get_xero_data_dynamic)

logger = logging.getLogger(__name__)

# Matches the "Expense '<item name>'" prefix our reason bullets use.
_EXPENSE_TEXT_RE = re.compile(r"^Expense '(.+?)'")


# ── Contact validity (live Xero, cached per contact, with fallback) ─────────

def _fetch_contact_active(entity_id, contact_id):
    """Return True/False if Xero says the contact is ACTIVE, or None on error."""
    try:
        resp = get_xero_data_dynamic(f"Contacts/{contact_id}", entity_id=entity_id)
        if isinstance(resp, dict) and "error" not in resp:
            contacts = resp.get("Contacts") or []
            if contacts and isinstance(contacts[0], dict):
                return str(contacts[0].get("ContactStatus", "")).upper() == "ACTIVE"
            return False  # not returned by Xero — treat as not active
        return None  # connection/token error — unknown
    except Exception as exc:  # never break a render over a badge
        logger.warning(f"live Xero contact lookup failed ({contact_id}): {exc}")
        return None


def _contact_in_sync(entity_id, contact_id) -> bool:
    if not contact_id:
        return False
    return (
        XeroContactSync.query.filter_by(
            entity_id=entity_id, xero_contact_id=contact_id
        ).first()
        is not None
    )


def _contact_active(entity_id, contact_id, cache) -> bool:
    """True when ``contact_id`` is an active, non-archived Xero contact."""
    if not contact_id:
        return False
    statuses = cache.setdefault("contact_status", {}) if cache is not None else {}
    if contact_id in statuses:
        live = statuses[contact_id]
    else:
        live = _fetch_contact_active(entity_id, contact_id)
        statuses[contact_id] = live
    if live is None:
        # Xero unreachable — fall back to the (possibly stale) synced table.
        return _contact_in_sync(entity_id, contact_id)
    return live


# ── Account validity (DB-only) ──────────────────────────────────────────────

def _account_not_known_bad(entity_id, account_code) -> bool:
    """True unless the account code maps to a known *inactive/archived* account."""
    if not account_code:
        return True
    row = AccountInfo.query.filter_by(
        entity_id=entity_id, xero_code=str(account_code)
    ).first()
    if row is None:
        return True  # unknown/default code — don't hold it against the user
    return row.status == "ACTIVE"


def _entity_account_valid(entity_id, role) -> bool:
    try:
        settings = get_entity_account_settings(entity_id, role)
    except Exception:
        return False
    if not settings:
        return False
    account_id = settings.get("account_id")
    if not account_id:
        return False
    acc = AccountInfo.query.get(account_id)
    return bool(acc and acc.status == "ACTIVE")


def _entity_contact_valid(entity_id, role, cache) -> bool:
    try:
        row = get_entity_contact_settings(entity_id, role)
    except Exception:
        return False
    if row is None or not getattr(row, "xero_contact_id", None):
        return False
    return _contact_active(entity_id, row.xero_contact_id, cache)


def _dep_valid(entity_id, kind, role, cache) -> bool:
    if kind == "contact":
        return _entity_contact_valid(entity_id, role, cache)
    if kind == "account":
        return _entity_account_valid(entity_id, role)
    return False


# ── Target resolution (handles structured + legacy text rows) ───────────────

def _expense_targets(report_id, item):
    """Return the ShopExpense rows this item refers to, or None if not an expense.

    ``[]`` means the expense was identified but no longer exists (treated as
    resolved upstream).
    """
    expense_id = item.get("expense_id")
    if expense_id:
        expense = ShopExpense.query.get(expense_id)
        return [expense] if expense else []
    if item.get("scope") == "expense":
        # Structured expense item but no id — fall through to text matching.
        pass
    match = _EXPENSE_TEXT_RE.match(item.get("text") or "")
    if match and report_id:
        return ShopExpense.query.filter_by(
            report_id=report_id, item=match.group(1)
        ).all()
    return None


def _infer_entity_deps(text):
    """Best-effort (kind, role) deps for a legacy entity reason with no metadata."""
    t = (text or "").lower()
    if "cash sale" in t:
        return [["contact", "cashsale_contact"], ["account", "cash_sale"]]
    if "discrepancy" in t:
        return [["contact", "discrepancy_contact"], ["account", "discrepancy_account"]]
    if "deposit" in t:
        return [["account", "pettycash"], ["account", "bank"]]
    if "withdrawal" in t or "director" in t:
        return [
            ["contact", "director_contact"],
            ["account", "director"],
            ["account", "pettycash"],
        ]
    return []


def _resolve_item(entity_id, report_id, item, cache):
    """Return ``(resolved, resolvable)`` for a single failure item."""
    # 1. Expense-scoped (structured id or recovered from the reason text).
    targets = _expense_targets(report_id, item)
    if targets is not None:
        if not targets:
            return True, True  # expense removed — issue gone
        resolved = all(
            _contact_active(entity_id, e.contact_id, cache)
            and _account_not_known_bad(entity_id, e.account_code)
            for e in targets
        )
        return resolved, True

    # 2. Entity-scoped: explicit deps, else inferred from legacy text.
    deps = item.get("deps") or _infer_entity_deps(item.get("text"))
    if deps:
        resolved = all(
            _dep_valid(entity_id, kind, role, cache) for kind, role in deps
        )
        return resolved, True

    # 3. Nothing we can re-check.
    return False, False


def annotate_resolution(entity_id, items, report_id=None, cache=None) -> list[dict]:
    """Annotate each failure item with its current resolution state.

    Returns a list of ``{"text", "resolved", "resolvable"}`` dicts.  Pass a
    shared ``cache`` dict across reports to reuse live Xero lookups, and
    ``report_id`` so legacy text-only rows can still be matched to their expense.
    """
    if cache is None:
        cache = {}
    annotated: list[dict] = []
    for item in items or []:
        text = item.get("text")
        if not text:
            continue
        try:
            resolved, resolvable = _resolve_item(entity_id, report_id, item, cache)
        except Exception as exc:  # never break a render over a badge
            logger.warning(f"resolution check failed for '{text}': {exc}")
            resolved, resolvable = False, False
        annotated.append(
            {"text": text, "resolved": resolved, "resolvable": resolvable}
        )
    return annotated
