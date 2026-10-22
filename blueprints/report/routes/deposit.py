# Report deposit step. Since the Part 15 redesign Bank Deposit is not a stage of its own: it is
# the first block of the Cash Count stage (D15-05), which saves the deposit with the count
# (cash_count.py). So a GET here goes on to the Cash Count page - the wizard's resume, the
# expenses step and old links still name this route - and the POST stays for any client that
# still sends the deposit on its own. The deposit rule and arithmetic live in
# blueprints/report/services/cash.py (shared with the Petty Cash API).
from datetime import datetime

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required
from services.app_runtime.log import logger

from blueprints.report import report_bp
from blueprints.report.services.shared import (check_user_has_entities,
                                               resolve_report_entity_id,
                                               safe_float)
from models.db import Report, db
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/new/deposit", methods=["GET", "POST"])
@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/<string:id>/deposit", methods=["GET"])
@report_bp.route("/report/deposit", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/deposit", methods=["GET"])
@login_required
def report_deposit(id=None, entity_id=None):
    entity_id = entity_id or request.args.get("entity_id") or request.form.get("entity_id")
    if not entity_id:
        entity_id = resolve_report_entity_id(id)
    if not entity_id:
        flash("I need to know which entity we're working with first!", "danger")
        return redirect(url_for("entity.entity_list"))
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You do not have permission to edit reports for this entity.",
            entity_id=entity_id,
        )
    if id:
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you any reports.",
            "warning")
        return redirect(url_for("entity.entity_list"))

    if request.method == "GET":
        # The deposit is drawn on the Cash Count page now; carry the day and the edit flags on.
        carried = {k: v for k, v in request.args.items() if k not in ("entity_id", "id")}
        return redirect(url_for("report.report_cash_count", entity_id=entity_id, id=id, **carried))

    selected_date = request.args.get("transaction_date") or request.form.get("transaction_date")
    try:
        transaction_date = (
            datetime.strptime(selected_date, "%Y-%m-%d").date() if selected_date else datetime.now().date()
        )
    except ValueError:
        logger.warning(f"Deposit form - Invalid date format: {selected_date}, using today")
        transaction_date = datetime.now().date()
    day = transaction_date.strftime("%Y-%m-%d")

    current_draft = Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == transaction_date,
        Report.status == "draft",
    ).first()
    if not current_draft:
        flash("I don't see a draft yet - let's start with the opening entry.", "danger")
        return redirect(url_for("report.report_opening"))

    from blueprints.report.services.cash import CashRefused, save_deposit

    here = url_for("report.report_cash_count", entity_id=entity_id, transaction_date=day)
    action_type = request.form.get("action_type", "save_next")
    try:
        save_deposit(current_draft, current_user, safe_float(request.form.get("bank_deposit", 0)), action_type)
    except CashRefused as refused:
        # the rule's own sentence: a negative drawer, or a deposit above the cash on hand
        flash(refused.message, "danger")
        return redirect(here)
    except Exception:
        db.session.rollback()
        logger.exception(f"Deposit save failed for draft {current_draft.id}")
        flash("Something went wrong saving your deposit. Mind trying again?", "danger")
        return redirect(here)

    if action_type == "save_exit":
        return redirect(url_for("entity.report_dashboard", id=entity_id))
    return redirect(here)
