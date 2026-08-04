"""Petty Cash module gate for the report blueprint.

Every route in this blueprint is part of the Petty Cash feature, so access is
denied wholesale when the PETTY_CASH module is disabled for the relevant
entity. This is enforced once here as a ``before_request`` rather than
decorating each of the ~30 routes individually — a single, auditable gate that
can't be forgotten when a new report route is added.

Entity resolution mirrors how the routes themselves find their entity:
  * ``entity_id`` / ``org_id`` in the URL, query string, form, or JSON body;
  * a report id (``id`` / ``report_id``) -> Report.company;
  * an expense / expense-draft id (``expense_id`` / ``draft_id``)
    -> the owning report(_draft)'s ``company``.

When no entity can be resolved (generic file downloads, the admin statements
tool, legacy public links) the request is allowed through — those routes carry
no entity context to gate on. Any unexpected error also fails open so a
transient DB hiccup never locks users out of an otherwise-permitted route.
"""

from __future__ import annotations

from flask import request
from loguru import logger

from blueprints.report import report_bp


def _from_request(keys):
    """First non-empty value for any of ``keys`` across URL args, query
    string, form, and JSON body."""
    view_args = request.view_args or {}
    for key in keys:
        if view_args.get(key):
            return str(view_args[key])
    for key in keys:
        value = request.args.get(key) or request.form.get(key)
        if value:
            return str(value)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        for key in keys:
            if body.get(key):
                return str(body[key])
    return None


def _resolve_entity_id():
    """Best-effort entity id for the current report-blueprint request, or
    None when the route carries no entity context."""
    # 1. Entity id carried directly on the request.
    entity_id = _from_request(("entity_id", "org_id"))
    if entity_id:
        return entity_id

    # Models imported lazily: importing them at module load creates a circular
    # import with the report models package (the routes package is imported
    # while those models are still initializing), which would silently disable
    # this guard.
    from blueprints.report.models.report import Report
    from blueprints.report.models.shop_expense import ShopExpense

    # 2. A report id -> owning entity. The ReportDraft second-try went with
    #    Step 4a-6: drafts and reports share one id AND one table now, so the
    #    first lookup already answers for both. No status filter — this is an
    #    authorization guard and must resolve an entity whatever the state.
    report_id = _from_request(("id", "report_id"))
    if report_id:
        report = Report.query.get(report_id)
        if report:
            return report.company

    # 3. An expense id -> owning report's entity (submitted expense first,
    #    then a draft expense).
    expense_id = _from_request(("expense_id",))
    if expense_id:
        expense = ShopExpense.query.get(expense_id)
        if expense:
            report = Report.query.get(expense.report_id)
            if report:
                return report.company

    # 4. An expense-draft id -> owning report's entity.
    #    The ShopExpenseDraft lookups that used to sit in both branches went
    #    with Step 4a-3: draft and real share one id, so ShopExpense.get()
    #    answers for both. `draft_id` stays a distinct request key because
    #    routes still pass it under that name.
    draft_id = _from_request(("draft_id",))
    if draft_id:
        expense = ShopExpense.query.get(draft_id)
        if expense:
            report = Report.query.get(expense.report_id)
            if report:
                return report.company

    return None


@report_bp.before_request
def _enforce_petty_cash_module():
    """Deny report-blueprint access when PETTY_CASH is off for the entity."""
    if request.method == "OPTIONS":
        return None

    try:
        entity_id = _resolve_entity_id()
        if not entity_id:
            return None

        from blueprints.entity.routes.modules import _is_module_enabled

        if _is_module_enabled(entity_id, "PETTY_CASH"):
            return None
    except Exception as exc:  # never lock users out on a transient error
        logger.error(f"Petty Cash module guard error: {exc}")
        return None

    from services.authz import permission_denied

    return permission_denied(
        "Petty Cash is not activated for this entity.", entity_id=entity_id
    )
