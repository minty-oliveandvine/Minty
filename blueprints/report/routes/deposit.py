# Report deposit routes; delegates to app implementation.
# Deposit step: report_deposit transferred from app.py (single function,
# no new functions).
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (check_user_has_entities,
                                               get_cash_sales_from_detail,
                                               header_publishing_status_for,
                                               resolve_report_entity_id,
                                               safe_float,
                                               update_draft_progress)
from blueprints.shared.entity_display import build_entity_acronym
from models.db import (AccountInfo, Entity, EntityAccountXero, Report,
                       ReportCashCountDraft, ReportDraft, ReportV2, UserEntity,
                       db)
from services.authz import permission_denied
from services.helpers.xero_bridge import get_xero_data_dynamic
from services.permission_policy import (Permission, can_edit_report,
                                        has_permission)


@report_bp.route("/report/deposit", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/deposit", methods=["GET"])
@login_required
def report_deposit(id=None):
    entity_id = request.args.get("entity_id") or request.form.get("entity_id")
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
        if not report_for_access:
            report_for_access = ReportDraft.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
    # Check if user has any entities before allowing access to reports
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you any reports.",
            "warning")
        return redirect(url_for("entity.entity_list"))

    # Check if edit mode is enabled
    is_edit_mode = (request.args.get("edit") ==
                    "true" or request.form.get("edit") == "true")

    def get_entity_badge_data(entity):
        acronym = build_entity_acronym(entity.name) if entity else ""

        badge_date = None
        if entity and entity.created_at:
            if isinstance(entity.created_at, datetime):
                badge_date = entity.created_at.date()
            else:
                badge_date = entity.created_at
        return acronym, badge_date

    entity_acronym = ""
    display_date = None

    # For GET request, get the current draft data (use entity owner's token
    # when entity_id present)
    all_accounts = get_xero_data_dynamic("Accounts", entity_id=entity_id)
    xero_bank_accounts = [
        acc
        for acc in all_accounts.get("Accounts", [])
        if acc.get("BankAccountType") == "BANK"
    ]
    if id:
        report = (
            Report.query.join(
                ReportDraft,
                ReportDraft.id == Report.id,
                full=True) .filter(
                Report.id == id,
                ReportDraft.id == id) .with_entities(
                Report.id,
                Report.transaction_date,
                Report.next_transaction_date,
                Report.date,
                Report.opening_balance,
                Report.cash_addition,
                Report.adjusted_opening_balance,
                Report.cash_sales,
                Report.visa_sales,
                Report.alipay_sales,
                Report.wechat_sales,
                Report.master_sales,
                Report.unionpay_sales,
                Report.amex_sales,
                Report.octopus_sales,
                Report.foodpanda_sales,
                Report.keeta_sales,
                Report.openrice_sales,
                Report.shop_sales,
                Report.delivery_sales,
                Report.total_sales,
                Report.expenses,
                Report.bank_deposit,
                Report.closing_balance,
                Report.receipt_files,
                Report.uploaded_by,
                Report.company,
                Report.xero_integrated_yes,
                ReportDraft.completed_sections,
                ReportDraft.current_section,
                ReportCashCountDraft.thousand_note,
                ReportCashCountDraft.fivehundred_note,
                ReportCashCountDraft.onehundred_note,
                ReportCashCountDraft.fifty_note,
                ReportCashCountDraft.twenty_note,
                ReportCashCountDraft.ten_note,
                ReportCashCountDraft.five_coin,
                ReportCashCountDraft.two_coin,
                ReportCashCountDraft.one_coin,
                ReportCashCountDraft.safe_box_balance,
                ReportCashCountDraft.discrepancy_amount,
                ReportCashCountDraft.discrepancy_type,
                ReportCashCountDraft.discrepancy_reason,
            ) .first())
        entity = (
            Entity.query.join(UserEntity, UserEntity.entity_id == Entity.id)
            .filter(UserEntity.entity_id == report.company)
            .first()
        )
        entity_acronym, display_date = get_entity_badge_data(entity)
        completed_sections = (
            report.completed_sections if report.completed_sections else []
        )
        current_draft = report

        # Determine if this is the latest report (most recent transaction_date)
        # or old report
        latest_report_date = (
            db.session.query(
                db.func.max(
                    db.func.coalesce(
                        Report.transaction_date,
                        ReportDraft.transaction_date))) .filter(
                db.or_(
                    Report.company == entity_id,
                    ReportDraft.company == entity_id),
            ) .scalar())

        is_latest_report = report.transaction_date == latest_report_date

        return render_template(
            "report/deposit.html",
            org=entity,
            current_draft=current_draft,
            header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
            current_section="deposit",  # Always set to current page
            completed_sections=completed_sections,
            draft_id=current_draft.id if current_draft else None,
            xero_bank_accounts=xero_bank_accounts,
            datenow=datetime.now(),
            transaction_date=report.transaction_date,
            is_latest_report=is_latest_report,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
        )

    # Get transaction date from URL parameter or form data if provided,
    # otherwise use today
    selected_date = request.args.get("transaction_date") or request.form.get(
        "transaction_date"
    )
    if selected_date:
        try:
            transaction_date = datetime.strptime(
                selected_date, "%Y-%m-%d").date()
            logger.info(
                f"Deposit form - Using selected date from URL/form: {transaction_date}"
            )
        except ValueError:
            logger.warning(
                f"Deposit form - Invalid date format: {selected_date}, using today"
            )
            transaction_date = datetime.now().date()
    else:
        transaction_date = datetime.now().date()
        logger.info(
            f"Deposit form - No date provided, using today: {transaction_date}")

    # If edit mode is enabled and no id provided, try to load any existing
    # report for this date
    if is_edit_mode and not id:
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
        ).first()
        if existing_report:
            # Redirect to deposit page with report id
            return redirect(
                url_for(
                    "report.report_deposit",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )

    # Check for existing draft: by id when in URL, else by (entity,
    # transaction_date)
    if id:
        current_draft = ReportDraft.query.filter(
            ReportDraft.id == id,
            ReportDraft.company == entity_id,
            ReportDraft.status == "draft",
        ).first()
    else:
        current_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.transaction_date == transaction_date,
            ReportDraft.status == "draft",
        ).first()

    logger.info("Deposit form - Looking for existing draft:")
    logger.info(f"  Company: {entity_id}")
    logger.info(f"  Transaction date: {transaction_date}")
    logger.info(f"  Username: {current_user.username}")
    logger.info(
        f"  Found existing draft: {current_draft.id if current_draft else 'None'}"
    )

    if not current_draft and not is_edit_mode:
        flash("I don't see a draft yet - let's start with the opening entry.", "danger")
        return redirect(url_for("report.report_opening"))

    if request.method == "POST":
        logger.info("Deposit form - Submission received")

        pre_deposit_balance = (
            (current_draft.opening_balance or 0)
            + (current_draft.cash_addition or 0)
            + (current_draft.cash_sales or 0)
            - (current_draft.expenses or 0)
        )
        if pre_deposit_balance < 0:
            flash("Hmm, it looks like your cash balance is negative. Could you fix that first?", "danger")
            return redirect(
                url_for(
                    "report.report_deposit",
                    entity_id=entity_id,
                    transaction_date=transaction_date.strftime("%Y-%m-%d"),
                )
            )

        try:
            # Get action type from form
            action_type = request.form.get("action_type", "save_next")

            # Get form data for deposit
            bank_deposit = safe_float(request.form.get("bank_deposit", 0))

            # Update draft with deposit amount; track last editor
            current_draft.uploaded_by = current_user.username
            current_draft.bank_deposit = bank_deposit

            # Recalculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
            # Get cash sales from ReportSaleDetail with fallback to
            # current_draft.cash_sales
            cash_sales = get_cash_sales_from_detail(
                current_draft.id, fallback_value=current_draft.cash_sales or 0.0)
            current_draft.closing_balance = (
                current_draft.opening_balance
                + (current_draft.cash_addition or 0)
                + cash_sales
                - (current_draft.expenses or 0)
                - current_draft.bank_deposit
            )

            # Update or create ReportV2 with the new bank_deposit value, and
            # store old value for logging
            report_v2 = ReportV2.query.filter_by(
                report_id=current_draft.id).first()
            old_bank_deposit = report_v2.cash_deposit if report_v2 else None

            if report_v2:
                report_v2.cash_deposit = bank_deposit
                logger.info(
                    f"Updated ReportV2 {report_v2.report_id} with bank_deposit: {bank_deposit} (old: {old_bank_deposit})"
                )
            else:
                report_v2 = ReportV2(
                    report_id=current_draft.id,
                    entity_id=entity_id,
                    report_date=current_draft.transaction_date,
                    status=current_draft.status or "draft",
                    starting_balance=current_draft.opening_balance,
                    opening_balance=current_draft.opening_balance,
                    adjusted_opening_balance=current_draft.adjusted_opening_balance,
                    add_cash_amount=current_draft.cash_addition,
                    cash_from_type="shop",
                    add_cash_bank_account_id=current_draft.withdrawal_bank_account,
                    xero_organiztion_id=current_user.xero_entity_id,
                    cashsale_total=current_draft.cash_sales or 0,
                    nocashsale_total=current_draft.delivery_sales or 0,
                    expense_total=current_draft.expenses or 0,
                    cash_deposit=bank_deposit,
                )
                db.session.add(report_v2)
                logger.info(
                    f"Created new ReportV2 {report_v2.report_id} with bank_deposit: {bank_deposit}"
                )

            # Update progress tracking (only for save_next)
            if action_type == "save_next":
                update_draft_progress(
                    current_draft, action_type, "deposit", "cash_count"
                )

            # Always commit the deposit data regardless of action type
            db.session.commit()

            # Log the deposit addition to draft history
            log_history_draft(
                report_draft_id=current_draft.id,
                company=entity_id,
                user_id=current_draft.uploaded_by,
                action="updated",
                field_changed="bank_deposit",
                old_value="previous_deposit",
                new_value=f"Bank Deposit: ${bank_deposit}",
            )

            # Check action type and redirect accordingly
            if action_type == "save_next":
                return redirect(
                    url_for(
                        "report.report_cash_count",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            elif action_type == "save_exit":
                return redirect(
                    url_for(
                        "entity.report_dashboard",
                        id=entity_id))
            else:
                # Default to save_next
                return redirect(
                    url_for(
                        "report.report_cash_count",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )

        except Exception as e:
            db.session.rollback()
            print(f"Error updating deposit: {str(e)}")
            flash(
                "Something went wrong saving your deposit. Mind trying again?",
                "danger")
            return redirect(url_for("report.report_deposit"))

    # Get entity for the template
    entity = Entity.query.filter(Entity.id == entity_id).first()
    entity_acronym, display_date = get_entity_badge_data(entity)

    # Ensure completed_sections is a list
    completed_sections = (
        current_draft.completed_sections if current_draft.completed_sections else [])

    # Don't reset current_section when viewing - it should only update when progressing forward
    # The stepper should always show the latest step reached, not the current
    # page

    # For new reports (no id parameter), always consider them as
    # latest/editable
    is_latest_report = True

    return render_template(
        "report/deposit.html",
        org=entity,
        current_draft=current_draft,
        header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
        transaction_date=transaction_date,
        current_section="deposit",  # Always set to current page
        completed_sections=completed_sections,
        draft_id=current_draft.id if current_draft else None,
        xero_bank_accounts=xero_bank_accounts,
        datenow=datetime.now(),
        is_latest_report=is_latest_report,
        entity_acronym=entity_acronym,
        display_date=display_date,
        is_edit_mode=is_edit_mode,
    )
