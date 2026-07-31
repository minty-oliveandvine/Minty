"""Pair every ShopExpenseDraft with a ShopExpense row, and keep it current.

TEMPORARY — scaffolding for the shop_expense_draft -> shop_expense
consolidation. Deleted in Stage 5 once nothing reads shop_expense_draft.

-----------------------------------------------------------------------------
WHY

shop_expense_draft and shop_expense are the same shape as report_draft and
report: the submit path copies draft -> real reusing the PRIMARY KEY
(ending.py:1617 does ``ShopExpense(id=shop_expense_draft.id, ...)``) and
leaves the draft row in place. One logical expense, one id, two tables.

The difference — and the reason expense reads could not be migrated alongside
the report reads — is that no ShopExpense row exists until SUBMIT. During data
entry the expense lives only in shop_expense_draft, so pointing any read at
shop_expense would return nothing for every in-progress report.

This module closes that gap the same way Stage 4a did for reports:

  * ensure_shop_expense_for_draft()  creates the paired row at draft creation
  * the before_flush listener        keeps it current as the draft is edited

Once both are in place, reads can move to shop_expense, then writes, then
shop_expense_draft can be dropped.

-----------------------------------------------------------------------------
EASIER THAN THE REPORT CASE

shop_expense.report_id points at report.id, and Stage 4a already guarantees a
report row exists from draft creation. So there is no unconstrained interval
here — no equivalent of the r2a02 -> r4a04 gap where the FK had to be dropped
and later re-added. The value is correct the moment it is written, because
report_draft_id IS the report id.

It also dissolves the duplicate-id problem rather than solving it. Today a
submitted expense exists in BOTH tables under one id, which would need a merge
with a winner. Once the real row exists from entry onward there is only ever
one row, and the collision never happens.

-----------------------------------------------------------------------------
WHAT IT DOES NOT DO

* No report_id invention. report_draft_id is copied straight across — the two
  are the same value by construction.
* One direction only: draft -> real. The draft is still the write target.
* Never touches ``id``: re-keying would be a bug, not a sync.
* Does not delete draft rows. Removing them is Stage 5, deliberately separate.

-----------------------------------------------------------------------------
FAILURE POLICY

Non-fatal. The draft remains the source of truth while this module exists, so
a failed mirror is a stale read, never lost data. Failures are logged loudly.
"""
from loguru import logger
from sqlalchemy import event, inspect

# models.db imports this module to register the listener, so every model
# reference is resolved lazily inside the functions below.

_MIRRORED_COLUMNS = ()


def _compute_mirrored_columns():
    """Columns on BOTH tables, minus the primary key.

    Derived rather than hardcoded so a column added to both is picked up
    automatically. ``report_id``/``report_draft_id`` are deliberately NOT in
    here — they are named differently and handled explicitly.
    """
    from models.db import ShopExpense, ShopExpenseDraft

    return tuple(
        sorted(
            {c.name for c in ShopExpenseDraft.__table__.columns}
            & {c.name for c in ShopExpense.__table__.columns}
            - {"id"}
        )
    )


def ensure_shop_expense_for_draft(draft, commit=False):
    """Create the paired ``shop_expense`` row for ``draft`` if absent.

    Draft and real share one id (ending.py:1607 matches them on exactly that),
    so this is an existence check on the primary key, not a search.

    ``report_id`` comes from ``report_draft_id`` unchanged: a draft and its
    report share an id too, so the value is already correct for the FK.

    Idempotent and non-fatal — never raises into the caller's request.
    """
    from models.db import ShopExpense, db

    if draft is None or not getattr(draft, "id", None):
        return None
    try:
        existing = db.session.get(ShopExpense, draft.id)
        if existing is not None:
            return existing

        report_id = getattr(draft, "report_draft_id", None)
        if not report_id:
            logger.warning(
                f"ensure_shop_expense_for_draft: draft {draft.id} has no "
                "report_draft_id; skipping shop_expense row"
            )
            return None

        values = {c: getattr(draft, c, None) for c in _MIRRORED_COLUMNS}
        # item and amount are NOT NULL on shop_expense. The multi-file upload
        # path (api.py:1737) deliberately creates a skeleton draft with
        # item="" and amount=0.0 until the PATCH fills it in, so mirror those
        # placeholders rather than rejecting the row.
        if values.get("item") is None:
            values["item"] = ""
        if values.get("amount") is None:
            values["amount"] = 0.0

        expense = ShopExpense(id=draft.id, report_id=report_id, **values)
        db.session.add(expense)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        logger.info(
            f"Created shop_expense {expense.id} alongside its draft "
            f"(report_id={report_id})"
        )
        return expense
    except Exception as exc:
        logger.error(
            f"ensure_shop_expense_for_draft failed for draft "
            f"{getattr(draft, 'id', '?')}: {exc}"
        )
        return None


def _mirror_draft_to_expense(session, draft):
    """Copy the fields that actually changed onto the paired ShopExpense."""
    from models.db import ShopExpense

    expense = session.get(ShopExpense, draft.id)
    if expense is None:
        # No paired row: a draft predating this module, or one created outside
        # ensure_shop_expense_for_draft. Not this function's job to create it.
        return

    state = inspect(draft)
    changed = []
    for name in _MIRRORED_COLUMNS:
        if not state.attrs[name].history.has_changes():
            continue
        new_value = getattr(draft, name)
        if getattr(expense, name) != new_value:
            setattr(expense, name, new_value)
            changed.append(name)

    if changed:
        logger.debug(f"draft->expense mirror {draft.id}: {', '.join(changed)}")


def _before_flush(session, _flush_context, _instances):
    from models.db import ShopExpenseDraft

    for obj in list(session.dirty) + list(session.new):
        if isinstance(obj, ShopExpenseDraft):
            try:
                _mirror_draft_to_expense(session, obj)
            except Exception as exc:
                logger.error(
                    f"draft->expense mirror failed for "
                    f"{getattr(obj, 'id', '?')}: {exc}"
                )


_registered = False


def register_expense_draft_mirror():
    """Install the listener. Idempotent."""
    global _registered, _MIRRORED_COLUMNS
    if _registered:
        return
    from models.db import db

    _MIRRORED_COLUMNS = _compute_mirrored_columns()
    event.listen(db.session, "before_flush", _before_flush)
    _registered = True
    logger.info(
        f"draft->expense mirror active ({len(_MIRRORED_COLUMNS)} columns)"
    )
