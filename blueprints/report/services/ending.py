# Report ending services; extracted from report routes.

# Report ending routes; delegates to app implementation.
# Ending step: report_ending transferred from app.py (single function, no
# new functions).
from datetime import datetime, timedelta

from flask import current_app as app
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from blueprints.report.services.cash_denominations import (
    get_cash_count_details, get_cash_count_total)
from blueprints.report.services.shared import (check_user_has_entities,
                                               cleanup_partial_submission_data,
                                               future_date_error,
                                               get_cash_sales_from_detail,
                                               resolve_report_entity_id)
from blueprints.shared.entity_display import entity_badge_data
from models.db import (Entity, Report, ReportCashCountDraft, ReportDraft,
                       ReportSaleDetail, EntitySaleSetting, ShopExpense,
                       ShopExpenseDraft, UserEntity, db, tz)
from services.helpers.xero_bridge import resolve_contact_name
from services.permission_policy import (Permission, can_view_report,
                                        has_permission, is_superuser)
from utils import verify_share_token


def entity_ending_with_report(entity_id, report_id):
    # Check if user has access to this entity.
    # Superusers without a user_entity row enter in read-only mode and may
    # still view past reports; can_view_report below enforces the per-report
    # check, and writes are gated by has_permission elsewhere.
    user_entity = UserEntity.query.filter(
        UserEntity.user_id == current_user.id,
        UserEntity.entity_id == entity_id).first()

    if not user_entity and not is_superuser(current_user):
        flash("Hmm, it looks like you don't have permission to look there.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Get the entity
    Entity.query.get_or_404(entity_id)

    # Get the specific report by ID - removed uploaded_by filter since access
    # is controlled by UserEntity
    report = Report.query.filter(
        Report.id == report_id,
        Report.company == entity_id,
    ).first()

    if not report:
        flash("Hmm, I couldn't find that report.", "danger")
        return redirect(url_for("report.entity_report_history", entity_id=entity_id))
    if not can_view_report(current_user, report):
        flash("Hmm, it looks like you don't have permission to open this report.", "danger")
        return redirect(url_for("report.entity_report_history", entity_id=entity_id))

    # Get the report data and render the ending page
    return report_ending(id=report_id, entity_id=entity_id)




class RevertError(Exception):
    """A revert-to-draft attempt that failed a guard, with an HTTP status."""

    def __init__(self, message, status_code):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def revert_report_to_draft(report_id):
    """Revert a submitted report to an editable draft.

    Deletes the posted Report (and its ShopExpense rows) and rewinds the
    ReportDraft to the opening step, so the whole report — balances included —
    can be re-entered through the normal flow and re-submitted.

    Two things are deliberately preserved on the draft before the Report row
    goes away:

    * ``publishing_status`` — the only record that this report was already
      pushed to Xero. Publishing does not store Xero object IDs, so a second
      publish re-POSTs everything and duplicates it. Submitting the draft again
      restores this marker onto the new Report so the publish flow can warn.
    * ``xero_integrated_yes`` — whether that push fully succeeded.

    Raises RevertError on a failed guard. Commits on success and returns the
    ReportDraft.
    """
    report = Report.query.filter(Report.id == report_id).first()
    if not report:
        raise RevertError("Report not found", 404)

    entity_id = report.company
    if not entity_id or not has_permission(
        current_user, Permission.REPORT_EDIT_OWN, entity_id
    ):
        raise RevertError("You do not have permission to edit this report.", 403)

    # Reports chain: each one's opening balance comes from the previous one's
    # closing balance. Reverting an older report deletes a link mid-chain and
    # leaves the newer reports' opening balances dangling, so only the latest
    # may be reverted -- matching edit_report and delete_report.
    newer_report = (
        Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date > report.transaction_date,
        )
        .order_by(Report.transaction_date.desc())
        .first()
    )
    if newer_report:
        raise RevertError(
            "You can only edit the most recent report. Delete or edit the newer "
            "reports first.",
            400,
        )

    report_draft = ReportDraft.query.filter(ReportDraft.id == report_id).first()
    if not report_draft:
        raise RevertError("Report draft not found", 404)

    was_published = bool(report.xero_integrated_yes)
    prior_publishing_status = report.publishing_status

    try:
        # ShopExpense.report_id is non-nullable, so these go before the Report.
        ShopExpense.query.filter(ShopExpense.report_id == report_id).delete()
        db.session.delete(report)

        report_draft.status = "draft"
        report_draft.current_section = "opening"
        report_draft.completed_sections = []
        report_draft.xero_integrated_yes = was_published
        report_draft.publishing_status = prior_publishing_status

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    logger.info(
        f"Report {report_id} reverted to draft "
        f"(was_published={was_published}, publishing_status={prior_publishing_status})"
    )
    return report_draft


def convert_report_to_draft(report_id):
    """JSON endpoint wrapper around revert_report_to_draft."""
    try:
        report_draft = revert_report_to_draft(report_id)
    except RevertError as e:
        return jsonify({"status": "error", "message": e.message}), e.status_code
    except Exception as e:
        logger.exception(f"Error converting report to draft: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't convert that report to a draft. Mind trying again?",
                }
            ),
            500,
        )

    return jsonify(
        {
            "status": "success",
            "message": "Report converted to draft",
            "draft_id": report_draft.id,
            "transaction_date": (
                report_draft.transaction_date.strftime("%Y-%m-%d")
                if report_draft.transaction_date
                else None
            ),
        }
    )




def entity_ending(entity_id):
    from datetime import datetime

    # Check if token is provided for public access
    token = request.args.get("token")
    if token:
        # Verify token
        secret_key = app.config.get("SECRET_KEY")
        if not secret_key:
            flash("Something's not set up right on my end. Could you let us know?", "danger")
            return redirect(url_for("entity.entity_list"))

        is_valid, params = verify_share_token(token, secret_key)
        if not is_valid or not params:
            flash("This link doesn't work anymore. Could you ask for a fresh one?", "danger")
            return redirect(url_for("entity.entity_list"))

        # Extract params from token (use token params, not URL params for
        # security)
        token_entity_id = params.get("entity_id")
        token_transaction_date = params.get("transaction_date")

        # Verify entity_id matches
        if token_entity_id != entity_id:
            flash("This link doesn't look right to me.", "danger")
            return redirect(url_for("entity.entity_list"))

        # Get the entity
        Entity.query.get_or_404(entity_id)

        # Find the report for the transaction_date from token
        try:
            report_date = datetime.strptime(
                token_transaction_date, "%Y-%m-%d").date()
            specific_report = Report.query.filter(
                Report.company == str(entity_id),
                Report.transaction_date == report_date).first()

            if specific_report:
                # Render ending page without login requirement
                return report_ending(
                    id=specific_report.id,
                    entity_id=entity_id,
                    skip_auth=True,
                )
            else:
                flash(
                    f"I couldn't find a report for {token_transaction_date}.",
                    "warning",
                )
                return redirect(url_for("entity.entity_list"))
        except ValueError:
            flash("There's something wrong with the date in this link.", "warning")
            return redirect(url_for("entity.entity_list"))

    # No token provided, require login
    try:
        if not current_user.is_authenticated:
            flash("You'll need to sign in to view this report.", "info")
            return redirect(url_for("auth.login"))
    except AttributeError:
        flash("You'll need to sign in to view this report.", "info")
        return redirect(url_for("auth.login"))

    # Check if user has access to this entity. Superusers without a
    # user_entity row are allowed in (read-only).
    user_entity = UserEntity.query.filter(
        UserEntity.user_id == current_user.id,
        UserEntity.entity_id == entity_id).first()

    if not user_entity and not is_superuser(current_user):
        flash("Hmm, it looks like you don't have permission to look there.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Get transaction_date from request or use today's date
    transaction_date = request.args.get("transaction_date")
    if transaction_date:
        try:
            report_date = datetime.strptime(
                transaction_date, "%Y-%m-%d").date()
        except ValueError:
            flash("That date doesn't look quite right to me.", "warning")
            return redirect(url_for("entity.entity_list"))
    else:
        # Use today's date if no transaction_date provided
        report_date = datetime.now().date()

    # Find the report for the transaction_date
    specific_report = Report.query.filter(
        Report.company == str(entity_id),
        Report.transaction_date == report_date).first()

    if specific_report:
        # Render ending page
        return report_ending(
            id=specific_report.id,
            entity_id=entity_id,
            skip_auth=False,
        )
    else:
        flash(
            f"I couldn't find a report for {report_date.strftime('%Y-%m-%d')}.",
            "warning",
        )
        return redirect(url_for("entity.entity_list"))


def report_ending(id=None, entity_id=None, skip_auth=False):
    # Lazy imports from app to avoid circular import
    # Diagnostic: the bounce below is a flash + 302, which logs nothing on its
    # own. Record what actually arrived so a lost query string, a stripped form
    # body and an expired session can be told apart from one another.
    logger.info(
        "ENTITY-TRACE report_ending entry - method=%s path=%s id=%s passed=%r "
        "args=%r form=%r referrer=%r xhr=%s auth=%s",
        request.method,
        request.path,
        id,
        entity_id,
        request.args.get("entity_id"),
        request.form.get("entity_id"),
        request.referrer,
        request.headers.get("X-Requested-With"),
        getattr(current_user, "is_authenticated", False),
    )
    if entity_id is None:
        entity_id = request.args.get("entity_id") or request.form.get("entity_id")
    if not skip_auth and not entity_id:
        entity_id = resolve_report_entity_id(id)
    if not skip_auth and not entity_id:
        logger.error(
            "ENTITY-TRACE report_ending BOUNCE - method=%s args=%r form_keys=%r referrer=%r",
            request.method,
            dict(request.args),
            list(request.form.keys()),
            request.referrer,
        )
        flash("I need to know which entity we're working with first!", "danger")
        return redirect(url_for("entity.entity_list"))
    if not skip_auth and not has_permission(
        current_user, Permission.REPORT_VIEW_OWN, entity_id
    ):
        flash("It looks like you don't have permission to view this entity's reports.", "danger")
        return redirect(url_for("entity.entity_list"))
    if not skip_auth and id:
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access:
            report_for_access = ReportDraft.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
        if not can_view_report(current_user, report_for_access):
            flash("Hmm, it looks like you don't have permission to open this report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))

    # Check if edit mode is enabled
    is_edit_mode = (
        request.args.get("edit") == "true" or request.form.get("edit") == "true"
    )

    # Check if user has any entities before allowing access to reports (skip if token-based access)
    if not skip_auth:
        try:
            if not current_user.is_authenticated or not check_user_has_entities(
                current_user.id
            ):
                flash(
                    "You'll need to create an entity before I can show you any reports.",
                    "warning",
                )
                return redirect(url_for("entity.entity_list"))
        except AttributeError:
            flash(
                "You'll need to create an entity before I can show you any reports.",
                "warning",
            )
            return redirect(url_for("entity.entity_list"))

    entity_acronym = ""
    display_date = None

    if id:
        # First verify the report exists
        report_exists = Report.query.filter(
            Report.id == id,
            Report.company == entity_id,
        ).first()

        if not report_exists:
            logger.error(f"Report not found: id={id}, entity_id={entity_id}")
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity_report_history", entity_id=entity_id))

        logger.info(
            f"Report found: id={id}, company={report_exists.company}, entity_id={entity_id}"
        )

        # Now query with outerjoins for draft data
        report = (
            Report.query.outerjoin(ReportDraft, ReportDraft.id == Report.id)
            .outerjoin(
                ReportCashCountDraft,
                ReportCashCountDraft.report_id == ReportDraft.id,
            )
            .filter(
                Report.id == id,
                Report.company == entity_id,
            )
            .with_entities(
                Report.id,
                Report.transaction_date,
                Report.next_transaction_date,
                Report.date,
                Report.opening_balance,
                Report.cash_addition,
                Report.adjusted_opening_balance,
                Report.cash_sales,
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
                db.func.coalesce(
                    ReportDraft.completed_sections, db.cast("[]", db.JSON)
                ).label("completed_sections"),
                db.func.coalesce(ReportDraft.current_section, db.null()).label(
                    "current_section"
                ),
                db.func.coalesce(ReportDraft.status, "posted").label("status"),
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
            )
            .first()
        )

        # If report query failed (shouldn't happen since we checked above, but just in case)
        if not report:
            logger.error(
                f"Report query failed after existence check: id={id}, entity_id={entity_id}"
            )
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity_report_history", entity_id=entity_id))

        # Check if ReportDraft exists, create it if missing
        report_draft = ReportDraft.query.filter(ReportDraft.id == id).first()
        if not report_draft:
            logger.info(f"ReportDraft missing for report {id}, creating it now")
            try:
                # Get full Report object to access all fields
                full_report = Report.query.filter(Report.id == id).first()
                if not full_report:
                    logger.error(
                        f"Full Report not found for {id}, cannot create ReportDraft"
                    )
                else:
                    report_draft = ReportDraft(
                        id=full_report.id,
                        transaction_date=full_report.transaction_date,
                        next_transaction_date=full_report.next_transaction_date,
                        date=full_report.date,
                        opening_balance=full_report.opening_balance,
                        cash_addition=full_report.cash_addition or 0.0,
                        adjusted_opening_balance=full_report.adjusted_opening_balance,
                        cash_sales=full_report.cash_sales or 0.0,
                        shop_sales=full_report.shop_sales or 0.0,
                        delivery_sales=full_report.delivery_sales or 0.0,
                        total_sales=full_report.total_sales or 0.0,
                        expenses=full_report.expenses or 0.0,
                        bank_deposit=full_report.bank_deposit or 0.0,
                        closing_balance=full_report.closing_balance or 0.0,
                        receipt_files=full_report.receipt_files,
                        uploaded_by=full_report.uploaded_by,
                        company=full_report.company,
                        completed_sections=[],
                        current_section=None,
                        status="posted",  # Set to 'posted' since Report already exists
                        xero_integrated_yes=getattr(
                            full_report, "xero_integrated_yes", False
                        )
                        or False,
                        safe_box_balance=getattr(full_report, "safe_box_balance", None),
                        discrepancy_amount=getattr(
                            full_report, "discrepancy_amount", None
                        ),
                        discrepancy_type=getattr(full_report, "discrepancy_type", None),
                        discrepancy_reason=getattr(
                            full_report, "discrepancy_reason", None
                        ),
                    )
                    db.session.add(report_draft)
                    db.session.commit()
                    logger.info(
                        f"Successfully created ReportDraft for report {id} with status 'posted'"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to create ReportDraft for report {id}: {str(e)}"
                )
                db.session.rollback()
                # Continue anyway - we'll handle missing draft fields gracefully

        # Ensure report has status attribute
        if not hasattr(report, "status") or not report.status:
            if report_draft:
                report.status = report_draft.status
            else:
                report.status = "posted"

        user_entity = Entity.query.get_or_404(entity_id)
        entity_acronym, display_date = entity_badge_data(user_entity)
        completed_sections = (
            report.completed_sections if report.completed_sections else []
        )

        # Query enabled sale settings for the entity
        enabled_sale_info = (
            EntitySaleSetting.query.filter_by(entity_id=entity_id, enabled=True)
            .order_by(EntitySaleSetting.display_order)
            .all()
        )

        # Query ReportSaleDetail with outer join to EntitySaleSetting to include deleted/disabled sale types
        # This ensures we get all sale details even if EntitySaleSetting was deleted/disabled
        report_sale_details = (
            db.session.query(ReportSaleDetail, EntitySaleSetting)
            .outerjoin(EntitySaleSetting, ReportSaleDetail.sale_id == EntitySaleSetting.sale_id)
            .filter(ReportSaleDetail.report_id == id)
            .all()
        )

        # Create mapping of sale_id to enabled EntitySaleSetting for quick lookup
        enabled_sale_info_dict = {sale.sale_id: sale for sale in enabled_sale_info}

        # Create mapping of value_name to amount from ReportSaleDetail
        sale_detail_amounts = {}
        deleted_sale_info_list = []
        processed_sale_ids = set()

        for sale_detail, sale_info_item in report_sale_details:
            # If EntitySaleSetting exists (even if disabled), use it
            if sale_info_item:
                value_name = sale_info_item.value_name
                if value_name and value_name != "deliveroo_sales":
                    sale_detail_amounts[value_name] = sale_detail.amount or 0
                    # If this sale is not in enabled list, add it to deleted list
                    if (
                        sale_info_item.sale_id not in enabled_sale_info_dict
                        and sale_info_item.sale_id not in processed_sale_ids
                    ):
                        deleted_sale_info_list.append(sale_info_item)
                        processed_sale_ids.add(sale_info_item.sale_id)
            else:
                # EntitySaleSetting was completely deleted from database, but we have a transaction
                # Try to find it by sale_id (in case it still exists but join failed)
                deleted_sale_info = EntitySaleSetting.query.filter_by(
                    sale_id=sale_detail.sale_id
                ).first()
                if deleted_sale_info:
                    # EntitySaleSetting exists but join failed (shouldn't happen, but handle it)
                    value_name = deleted_sale_info.value_name
                    if value_name and value_name != "deliveroo_sales":
                        sale_detail_amounts[value_name] = sale_detail.amount or 0
                        if (
                            deleted_sale_info.sale_id not in enabled_sale_info_dict
                            and deleted_sale_info.sale_id not in processed_sale_ids
                        ):
                            deleted_sale_info_list.append(deleted_sale_info)
                            processed_sale_ids.add(deleted_sale_info.sale_id)

        # Combine enabled sale_info with deleted/disabled sale types that have transactions
        # Deduplicate by value_name to prevent duplicates (e.g., when a sale type is re-enabled)
        # Track value_names that have been added (enabled ones take priority)
        added_value_names = {
            sale.value_name
            for sale in enabled_sale_info
            if sale.value_name and sale.value_name != "deliveroo_sales"
        }
        # Add enabled sale types first
        sale_info = list(enabled_sale_info)
        # Add deleted/disabled sale types only if their value_name hasn't been added yet
        for sale in sorted(
            deleted_sale_info_list, key=lambda x: getattr(x, "display_order", 9999)
        ):
            if (
                sale.value_name
                and sale.value_name != "deliveroo_sales"
                and sale.value_name not in added_value_names
            ):
                sale_info.append(sale)
                added_value_names.add(sale.value_name)

        # Build sales amounts dictionary for template
        # Use ONLY amounts from ReportSaleDetail - no fallback to Report model
        sales_amounts = {}
        for sale in sale_info:
            if sale.value_name and sale.value_name != "deliveroo_sales":
                # Get amount ONLY from ReportSaleDetail
                amount = sale_detail_amounts.get(sale.value_name, 0) or 0
                sales_amounts[sale.value_name] = amount
        # Calculate total expenses - check if it's a draft or completed report
        existing_expenses = []
        if hasattr(report, "status") and report.status == "draft":
            # For drafts, calculate from ShopExpenseDraft records
            expense_drafts = ShopExpenseDraft.query.filter_by(
                report_draft_id=report.id
            ).all()
            existing_expenses = expense_drafts
            total_expense = (
                sum(expense.amount for expense in expense_drafts)
                if expense_drafts
                else 0
            )
        else:
            # For completed reports, use the stored expenses field
            total_expense = report.expenses if report.expenses else 0
            # Get expenses from ShopExpense table for completed reports
            existing_expenses = ShopExpense.query.filter_by(report_id=report.id).all()

        # Group expenses by account_code
        grouped_expenses = {}
        for expense in existing_expenses:
            account_code = expense.account_code or "NO_CODE"
            if account_code not in grouped_expenses:
                grouped_expenses[account_code] = {
                    "item": expense.item or account_code,
                    "amount": 0,
                    "account_code": account_code,
                }
            grouped_expenses[account_code]["amount"] += expense.amount or 0

        # Convert to list and sort by amount (descending)
        existing_expenses = sorted(
            grouped_expenses.values(), key=lambda x: x["amount"], reverse=True
        )

        # Calculate electronic_sales, delivery_sales, and cash_sales from ReportSaleDetail
        electronic_sales = 0.0
        delivery_sales = 0.0
        cash_sales = 0.0

        for sale_detail, sale_info_item in report_sale_details:
            amount = sale_detail.amount or 0
            sale_type = (
                sale_info_item.type
                if sale_info_item and sale_info_item.type
                else sale_detail.type
            )

            if sale_type == "Electronic":
                electronic_sales += amount
            elif sale_type == "Delivery":
                delivery_sales += amount
            elif sale_type == "Cash":
                cash_sales += amount

        # Fallback to report.cash_sales if no cash sales found in ReportSaleDetail
        if cash_sales == 0:
            cash_sales = report.cash_sales if report.cash_sales else 0

        total_sales = report.total_sales if report.total_sales else 0
        # Calculate actual cash balance from cash count data
        cashcount_draft = ReportCashCountDraft.query.filter(
            ReportCashCountDraft.report_id == report.id
        ).first()
        if cashcount_draft:
            # Total from report_cashcount_detail, falling back to the legacy
            # note/coin columns for reports predating the backfill.
            total_actual_cash = get_cash_count_total(
                report.id, fallback_draft=cashcount_draft
            )
            safe_box_balance = cashcount_draft.safe_box_balance or 0
            cash_balance = total_actual_cash + safe_box_balance
        else:
            total_actual_cash = 0
            cash_balance = report.closing_balance if report.closing_balance else 0

        expected_cash_count_balance = (
            report.opening_balance
            + (report.cash_addition or 0)
            + report.cash_sales
            - report.expenses
            - report.bank_deposit
        )

        discrepancy_amount = (
            report.discrepancy_amount if report.discrepancy_amount else 0
        )
        discrepancy_type = (
            report.discrepancy_type if report.discrepancy_type else "none"
        )
        discrepancy_reason = (
            report.discrepancy_reason if report.discrepancy_reason else ""
        )

        bank_deposit = report.bank_deposit if report.bank_deposit else 0
        cash_expense = total_expense  # Total of all individual expenses added
        safe_box_balance = (
            cashcount_draft.safe_box_balance
            if cashcount_draft and cashcount_draft.safe_box_balance
            else 0
        )
        total_expense = (
            cash_expense + bank_deposit + safe_box_balance
        )  # Total expenses = cash expenses + bank deposits + safe box balance

        # Determine if this is the latest report (most recent transaction_date) or old report
        # Find the latest report ID for this entity (same logic as report_history)
        latest_report_query = (
            Report.query.join(ReportDraft, ReportDraft.id == Report.id, full=True)
            .with_entities(
                db.func.coalesce(Report.id, ReportDraft.id).label("id"),
                db.func.coalesce(
                    Report.transaction_date, ReportDraft.transaction_date
                ).label("transaction_date"),
            )
            .filter(
                db.or_(Report.company == entity_id, ReportDraft.company == entity_id),
            )
        )

        latest_report = latest_report_query.order_by(
            db.func.coalesce(
                Report.transaction_date, ReportDraft.transaction_date
            ).desc()
        ).first()

        # Check if this report is the latest by comparing IDs
        is_latest_report = latest_report and report.id == latest_report.id

        # Calculate yesterday's sales for comparison
        yesterday_date = (
            report.transaction_date - timedelta(days=1)
            if report.transaction_date
            else None
        )
        yesterday_sales = 0
        sales_difference = 0
        sales_percentage = 0
        sales_percentage_abs = 0
        is_sales_increase = False

        if yesterday_date:
            yesterday_report = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == yesterday_date,
            ).first()

            if yesterday_report and yesterday_report.total_sales:
                yesterday_sales = yesterday_report.total_sales
                sales_difference = total_sales - yesterday_sales
                if yesterday_sales > 0:
                    sales_percentage = (sales_difference / yesterday_sales) * 100
                is_sales_increase = sales_difference > 0
                sales_percentage_abs = abs(sales_percentage)

        # Get sales history for last 30 days
        sales_history = []
        if report.transaction_date:
            today_date = report.transaction_date
            for i in range(29, -1, -1):  # 29 days ago to today (30 days total)
                date = today_date - timedelta(days=i)
                is_today = i == 0  # Today is the last day (i == 0)

                # If it's today, use current report's sales (even if not submitted yet)
                if is_today:
                    sales_value = total_sales if total_sales else 0
                else:
                    day_report = Report.query.filter(
                        Report.company == entity_id, Report.transaction_date == date
                    ).first()
                    sales_value = (
                        day_report.total_sales
                        if day_report and day_report.total_sales
                        else 0
                    )

                month_abbr = date.strftime("%b").upper()
                day_num = date.strftime("%d").lstrip("0") or "0"
                day_name = date.strftime("%a").upper()
                date_label = f"{day_num} {month_abbr} {day_name}"

                sales_history.append(
                    {"date": date_label, "value": sales_value, "is_today": is_today}
                )

        # Surface the posted report's Xero publish state so the header badge can
        # show "Partially Published" (the Row above carries xero_integrated_yes
        # but not publishing_status).
        posted_report_row = Report.query.filter(Report.id == id).first()
        header_publishing_status = (
            posted_report_row.publishing_status if posted_report_row else None
        )

        return render_template(
            "report/ending.html",
            org=user_entity,
            completed_sections=completed_sections,
            current_section="ending",
            current_draft=report,
            report_draft=report,
            header_publishing_status=header_publishing_status,
            total_expense=total_expense,
            electronic_sales=electronic_sales,
            delivery_sales=delivery_sales,
            cash_sales=cash_sales,
            total_sales=total_sales,
            cash_balance=cash_balance,
            total_actual_cash=total_actual_cash,
            expected_cash_count_balance=expected_cash_count_balance,
            discrepancy_amount=discrepancy_amount,
            discrepancy_type=discrepancy_type,
            discrepancy_reason=discrepancy_reason,
            bank_deposit=bank_deposit,
            cash_expense=cash_expense,
            transaction_date=report.transaction_date,
            is_latest_report=is_latest_report,
            today_date=datetime.now().date(),
            cashcount_draft=cashcount_draft,
            closing_balance=report.closing_balance if report.closing_balance else 0,
            existing_expenses=existing_expenses,
            entity_acronym=entity_acronym,
            display_date=display_date,
            yesterday_sales=yesterday_sales,
            sales_percentage_abs=sales_percentage_abs,
            is_sales_increase=is_sales_increase,
            sales_history=sales_history,
            is_shared_link=skip_auth,
            sale_info=sale_info,
            sales_amounts=sales_amounts,
            is_edit_mode=is_edit_mode,
        )

    # Get transaction date from URL parameter if provided, otherwise use today
    if request.method == "POST":
        entity_id = request.form.get("entity_id")
        selected_date = request.form.get("transaction_date")
    else:
        selected_date = request.args.get("transaction_date")
        entity_id = request.args.get("entity_id")

    if selected_date:
        try:
            transaction_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            logger.info(
                f"Ending form - Using selected date from URL: {transaction_date}"
            )
        except ValueError:
            logger.warning(
                f"Ending form - Invalid date format in URL: {selected_date}, using today"
            )
            transaction_date = datetime.now().date()
    else:
        transaction_date = datetime.now().date()
        logger.info(
            f"Ending form - No date in URL, using today: {transaction_date}"
        )

    # Get user entity
    user_entity = Entity.query.get(entity_id)
    entity_acronym, display_date = (
        entity_badge_data(user_entity) if user_entity else ("", None)
    )

    # If edit mode is enabled and no id provided, try to load any existing report for this date
    if is_edit_mode and not id:
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
        ).first()
        if existing_report:
            # Redirect to ending page with report id
            return redirect(
                url_for(
                    "report.report_ending",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )

    # Check for existing draft: by id when in URL, else by (entity, transaction_date)
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

    cashcount_draft = None
    if current_draft:
        cashcount_draft = ReportCashCountDraft.query.filter(
            ReportCashCountDraft.report_id == current_draft.id
        ).first()

    # Check if entity and draft exist
    if not user_entity:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    # If edit mode is enabled and no draft exists, try to load any existing report for this date
    if is_edit_mode and not current_draft:
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
        ).first()
        if existing_report:
            # Redirect to ending page with report id to load it properly
            return redirect(
                url_for(
                    "report.report_ending",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )
        else:
            flash("I couldn't find a report to edit for that date.", "warning")
            return redirect(url_for("entity.report_dashboard", id=entity_id))

    if not current_draft and not is_edit_mode:
        flash(
            "I don't see a draft for today yet - let's start with the opening entry.",
            "warning",
        )
        # Carry the entity through: report_opening can't resolve one on its
        # own, so without it this lands on "I need to know which entity we're
        # working with first!" and a bounce to the entity list instead of the
        # opening page. Every other redirect on this page passes it too.
        return redirect(url_for("report.report_opening", entity_id=entity_id))

    completed_sections = (
        current_draft.completed_sections if current_draft.completed_sections else []
    )

    # Block access to ending if cash_count not completed, UNLESS balance is
    # negative — in that case let the page load so the Fix Negative Balance
    # modal can guide the user back to the right step.
    expected_balance = (
        (current_draft.opening_balance or 0)
        + (current_draft.cash_addition or 0)
        + (current_draft.cash_sales or 0)
        - (current_draft.expenses or 0)
        - (current_draft.bank_deposit or 0)
    )
    if not is_edit_mode and "cash_count" not in completed_sections and expected_balance >= 0:
        flash(
            "The Cash Count step needs finishing before I can show you the Ending page - shall we do that first?",
            "warning",
        )
        return redirect(
            url_for(
                "report.report_cash_count",
                entity_id=entity_id,
                transaction_date=transaction_date.strftime("%Y-%m-%d"),
            )
        )

    # Query enabled sale settings for the entity
    enabled_sale_info = (
        EntitySaleSetting.query.filter_by(entity_id=entity_id, enabled=True)
        .order_by(EntitySaleSetting.display_order)
        .all()
    )

    # Query ReportSaleDetail with outer join to EntitySaleSetting to include deleted/disabled sale types
    # This ensures we get all sale details even if EntitySaleSetting was deleted/disabled
    report_sale_details = (
        db.session.query(ReportSaleDetail, EntitySaleSetting)
        .outerjoin(EntitySaleSetting, ReportSaleDetail.sale_id == EntitySaleSetting.sale_id)
        .filter(ReportSaleDetail.report_id == current_draft.id)
        .all()
    )

    # Create mapping of sale_id to enabled EntitySaleSetting for quick lookup
    enabled_sale_info_dict = {sale.sale_id: sale for sale in enabled_sale_info}

    # Create mapping of value_name to amount from ReportSaleDetail
    sale_detail_amounts = {}
    deleted_sale_info_list = []
    processed_sale_ids = set()

    for sale_detail, sale_info_item in report_sale_details:
        # If EntitySaleSetting exists (even if disabled), use it
        if sale_info_item:
            value_name = sale_info_item.value_name
            if value_name and value_name != "deliveroo_sales":
                sale_detail_amounts[value_name] = sale_detail.amount or 0
                # If this sale is not in enabled list, add it to deleted list
                if (
                    sale_info_item.sale_id not in enabled_sale_info_dict
                    and sale_info_item.sale_id not in processed_sale_ids
                ):
                    deleted_sale_info_list.append(sale_info_item)
                    processed_sale_ids.add(sale_info_item.sale_id)
        else:
            # EntitySaleSetting was completely deleted from database, but we have a transaction
            # Try to find it by sale_id (in case it still exists but join failed)
            deleted_sale_info = EntitySaleSetting.query.filter_by(
                sale_id=sale_detail.sale_id
            ).first()
            if deleted_sale_info:
                # EntitySaleSetting exists but join failed (shouldn't happen, but handle it)
                value_name = deleted_sale_info.value_name
                if value_name and value_name != "deliveroo_sales":
                    sale_detail_amounts[value_name] = sale_detail.amount or 0
                    if (
                        deleted_sale_info.sale_id not in enabled_sale_info_dict
                        and deleted_sale_info.sale_id not in processed_sale_ids
                    ):
                        deleted_sale_info_list.append(deleted_sale_info)
                        processed_sale_ids.add(deleted_sale_info.sale_id)

    # Combine enabled sale_info with deleted/disabled sale types that have transactions
    # Deduplicate by value_name to prevent duplicates (e.g., when a sale type is re-enabled)
    # Track value_names that have been added (enabled ones take priority)
    added_value_names = {
        sale.value_name
        for sale in enabled_sale_info
        if sale.value_name and sale.value_name != "deliveroo_sales"
    }
    # Add enabled sale types first
    sale_info = list(enabled_sale_info)
    # Add deleted/disabled sale types only if their value_name hasn't been added yet
    for sale in sorted(
        deleted_sale_info_list, key=lambda x: getattr(x, "display_order", 9999)
    ):
        if (
            sale.value_name
            and sale.value_name != "deliveroo_sales"
            and sale.value_name not in added_value_names
        ):
            sale_info.append(sale)
            added_value_names.add(sale.value_name)

    # Build sales amounts dictionary for template
    # Use ONLY amounts from ReportSaleDetail - no fallback to ReportDraft model
    sales_amounts = {}
    for sale in sale_info:
        if sale.value_name and sale.value_name != "deliveroo_sales":
            # Get amount ONLY from ReportSaleDetail
            amount = sale_detail_amounts.get(sale.value_name, 0) or 0
            sales_amounts[sale.value_name] = amount

    # Don't reset current_section when viewing ending page - it should only update when progressing forward
    # The stepper should always show the latest step reached, not reset when viewing pages
    # Ending can still be marked as completed separately if needed
    if "ending" not in completed_sections:
        completed_sections.append("ending")
        current_draft.completed_sections = completed_sections
        flag_modified(current_draft, "completed_sections")
        # Don't reset current_section here - it should reflect the latest step reached
        db.session.commit()

    total_sales = current_draft.total_sales if current_draft.total_sales else 0

    # Calculate electronic_sales, delivery_sales, and cash_sales from ReportSaleDetail
    electronic_sales = 0.0
    delivery_sales = 0.0
    cash_sales = 0.0

    for sale_detail, sale_info_item in report_sale_details:
        amount = sale_detail.amount or 0
        sale_type = (
            sale_info_item.type
            if sale_info_item and sale_info_item.type
            else sale_detail.type
        )

        if sale_type == "Electronic":
            electronic_sales += amount
        elif sale_type == "Delivery":
            delivery_sales += amount
        elif sale_type == "Cash":
            cash_sales += amount

    # Fallback to current_draft.cash_sales if no cash sales found in ReportSaleDetail
    if cash_sales == 0:
        cash_sales = current_draft.cash_sales if current_draft.cash_sales else 0

    # Calculate total expenses from individual expense records for drafts
    existing_expenses = []
    if current_draft.status == "draft":
        # For drafts, calculate from ShopExpenseDraft records
        expense_drafts = ShopExpenseDraft.query.filter_by(
            report_draft_id=current_draft.id
        ).all()
        existing_expenses = expense_drafts

        # Group expenses by account_code
        grouped_expenses = {}
        for expense in existing_expenses:
            account_code = expense.account_code or "NO_CODE"
            if account_code not in grouped_expenses:
                grouped_expenses[account_code] = {
                    "item": expense.item or account_code,
                    "amount": 0,
                    "account_code": account_code,
                }
            grouped_expenses[account_code]["amount"] += expense.amount or 0

        # Convert to list and sort by amount (descending)
        existing_expenses = sorted(
            grouped_expenses.values(), key=lambda x: x["amount"], reverse=True
        )

        total_expense = (
            sum(exp["amount"] for exp in existing_expenses) if existing_expenses else 0
        )
    else:
        # For completed reports, use the stored expenses field
        total_expense = current_draft.expenses if current_draft.expenses else 0
        # Get expenses from ShopExpense table for completed reports
        existing_expenses = ShopExpense.query.filter_by(
            report_id=current_draft.id
        ).all()

        # Group expenses by account_code
        grouped_expenses = {}
        for expense in existing_expenses:
            account_code = expense.account_code or "NO_CODE"
            if account_code not in grouped_expenses:
                grouped_expenses[account_code] = {
                    "item": expense.item or account_code,
                    "amount": 0,
                    "account_code": account_code,
                }
            grouped_expenses[account_code]["amount"] += expense.amount or 0

        # Convert to list and sort by amount (descending)
        existing_expenses = sorted(
            grouped_expenses.values(), key=lambda x: x["amount"], reverse=True
        )

    # Calculate actual cash balance from cash count data
    if cashcount_draft:
        logger.info(f"Retrieved cash count data for draft {current_draft.id}:")
        # Enumerate what was actually counted rather than the nine fixed
        # columns, so custom denominations show up here too.
        counted = get_cash_count_details(current_draft.id)
        if counted:
            logger.info(
                "  Counted: "
                + ", ".join(
                    f"{row.cash_value:g}x{row.count}"
                    for row in sorted(
                        counted.values(), key=lambda r: -r.cash_value
                    )
                )
            )
        logger.info(f"  Safe box balance: {cashcount_draft.safe_box_balance}")
        logger.info(
            f"  Stored actual_cash_total: {cashcount_draft.actual_cash_total}"
        )

        # Total from report_cashcount_detail, falling back to the legacy
        # note/coin columns for reports predating the backfill.
        total_actual_cash = get_cash_count_total(
            current_draft.id, fallback_draft=cashcount_draft
        )
        safe_box_balance = cashcount_draft.safe_box_balance or 0
        cash_balance = total_actual_cash + safe_box_balance

        logger.info(f"  Calculated total_actual_cash: {total_actual_cash}")
        logger.info(f"  Final cash_balance: {cash_balance}")
    else:
        total_actual_cash = 0
        cash_balance = (
            current_draft.closing_balance if current_draft.closing_balance else 0
        )

    discrepancy_amount = (
        cashcount_draft.discrepancy_amount if cashcount_draft.discrepancy_amount else 0
    )
    discrepancy_type = (
        cashcount_draft.discrepancy_type if cashcount_draft.discrepancy_type else "none"
    )
    discrepancy_reason = (
        cashcount_draft.discrepancy_reason if cashcount_draft.discrepancy_reason else ""
    )
    if request.method == "POST":
        expected_balance = (
            (current_draft.opening_balance or 0)
            + (current_draft.cash_addition or 0)
            + (current_draft.cash_sales or 0)
            - (current_draft.expenses or 0)
            - (current_draft.bank_deposit or 0)
        )
        if expected_balance < 0:
            flash("Hmm, it looks like your cash balance is negative. Could you fix that first?", "warning")
            return redirect(
                url_for(
                    "report.report_deposit",
                    entity_id=entity_id,
                    transaction_date=transaction_date.strftime("%Y-%m-%d"),
                )
            )

        try:
            logger.info("=== STARTING REPORT ENDING SUBMISSION ===")
            logger.info(
                f"Draft ID: {current_draft.id if current_draft else 'None'}"
            )
            logger.info(f"Entity ID: {entity_id}")
            logger.info(
                f"User: {current_user.username if current_user else 'None'}"
            )
            logger.info(
                f"Company: {entity_id if entity_id else 'None'}"
            )
            logger.info(
                f"Transaction Date: {current_draft.transaction_date if current_draft else 'None'}"
            )
            logger.info(f"Completed Sections: {completed_sections}")
            logger.info(
                f"Current Section: {current_draft.current_section if current_draft else 'None'}"
            )
            logger.info(
                f"Xero Integrated: {current_draft.xero_integrated_yes if current_draft else 'None'}"
            )

            # Comprehensive validation checks before processing
            validation_errors = []

            # 1. Validate draft exists and is valid
            if not current_draft:
                validation_errors.append("No draft found for submission")
            else:
                # 2. Validate required sections are completed
                required_sections = [
                    "opening",
                    "sales",
                    "expenses",
                    "deposit",
                    "cash_count",
                ]
                missing_sections = [
                    section
                    for section in required_sections
                    if section not in completed_sections
                ]
                if missing_sections:
                    validation_errors.append(
                        f"Missing required sections: {', '.join(missing_sections)}"
                    )

                # 3. Validate essential data fields
                if not current_draft.transaction_date:
                    validation_errors.append("Transaction date is required")
                else:
                    # No report may be posted for a date after today. This is the
                    # definitive guard: the wizard bypasses create.py, so this is
                    # the last gate before a Report row is written.
                    future_err = future_date_error(current_draft.transaction_date)
                    if future_err:
                        validation_errors.append(future_err)

                if current_draft.opening_balance is None:
                    validation_errors.append("Opening balance is required")

                if current_draft.closing_balance is None:
                    validation_errors.append("Closing balance is required")

                # 4. Validate cash count data if cash count section is completed
                if "cash_count" in completed_sections:
                    if not cashcount_draft:
                        validation_errors.append("Cash count data is missing")
                    else:
                        # Validate cash count - allow zero cash count
                        # Cash balance (cash count + safe box) can be <= 0
                        # Discrepancy validation will handle description requirements
                        total_cash_count = get_cash_count_total(
                            current_draft.id, fallback_draft=cashcount_draft
                        )
                        # No validation needed - allow zero cash count
                        # The discrepancy validation will ensure description is provided when needed

                # 5. Validate sales data
                if "sales" in completed_sections:
                    if (
                        current_draft.total_sales is None
                        or current_draft.total_sales < 0
                    ):
                        validation_errors.append(
                            "Total sales must be a valid positive number"
                        )

                # 6. Validate expenses
                if "expenses" in completed_sections:
                    if current_draft.expenses is None or current_draft.expenses < 0:
                        validation_errors.append(
                            "Total expenses must be a valid positive number"
                        )

                # 7. Validate deposit data
                if "deposit" in completed_sections:
                    if (
                        current_draft.bank_deposit is None
                        or current_draft.bank_deposit < 0
                    ):
                        validation_errors.append(
                            "Bank deposit must be a valid positive number"
                        )

                # 8. Validate Xero integration requirements if applicable
                if current_draft.xero_integrated_yes:
                    if not current_draft.withdrawal_type:
                        validation_errors.append(
                            "Withdrawal type is required for Xero integration"
                        )
                    if not current_draft.withdrawal_bank_account:
                        validation_errors.append(
                            "Withdrawal bank account is required for Xero integration"
                        )

            # If validation errors exist, return error response
            if validation_errors:
                logger.error("=== VALIDATION FAILED ===")
                logger.error(
                    f"Draft ID: {current_draft.id if current_draft else 'unknown'}"
                )
                logger.error(f"Validation Errors: {validation_errors}")
                logger.error("=== END VALIDATION FAILURE ===")
                flash(f"Hmm, a few things need fixing before I can submit: {'; '.join(validation_errors)}", "danger")
                return redirect(url_for("report.report_ending", entity_id=entity_id))

            logger.info("=== VALIDATION PASSED ===")
            logger.info(
                f"All validation checks passed for draft {current_draft.id}"
            )
            logger.info("=== PROCEEDING TO SUBMISSION ===")

            if "submitted" not in completed_sections:
                # Check if report already exists
                existing_report = Report.query.filter(
                    Report.id == current_draft.id
                ).first()
                logger.info("=== REPORT CREATION PHASE ===")
                logger.info(f"Existing report found: {existing_report is not None}")

                if not existing_report:
                    logger.info(
                        f"Creating new Report record for draft {current_draft.id}"
                    )
                    logger.info(
                        f"Report data - Opening Balance: {current_draft.opening_balance}"
                    )
                    logger.info(
                        f"Report data - Cash Addition: {current_draft.cash_addition}"
                    )
                    logger.info(
                        f"Report data - Total Sales: {current_draft.total_sales}"
                    )
                    logger.info(f"Report data - Expenses: {current_draft.expenses}")
                    logger.info(
                        f"Report data - Bank Deposit: {current_draft.bank_deposit}"
                    )
                    logger.info(
                        f"Report data - Closing Balance: {current_draft.closing_balance}"
                    )

                    # Calculate closing balance with discrepancy (discrepancy_amount is already signed)
                    # Get cash sales from ReportSaleDetail with fallback to current_draft.cash_sales
                    cash_sales = get_cash_sales_from_detail(
                        current_draft.id, fallback_value=current_draft.cash_sales or 0.0
                    )
                    base_closing_balance = (
                        (current_draft.opening_balance or 0)
                        + (current_draft.cash_addition or 0)
                        + cash_sales
                        - (current_draft.expenses or 0)
                        - (current_draft.bank_deposit or 0)
                    )
                    final_closing_balance = base_closing_balance + (
                        current_draft.discrepancy_amount or 0
                    )

                    posted_report = Report(
                        id=current_draft.id,
                        transaction_date=current_draft.transaction_date,
                        next_transaction_date=current_draft.next_transaction_date,
                        date=datetime.now(tz),
                        opening_balance=current_draft.opening_balance,
                        cash_addition=current_draft.cash_addition,
                        adjusted_opening_balance=current_draft.adjusted_opening_balance,
                        # Per-method amounts live in report_sale_detail and
                        # are shared via the id above — not copied per column.
                        cash_sales=current_draft.cash_sales,
                        shop_sales=current_draft.shop_sales,
                        delivery_sales=current_draft.delivery_sales,
                        total_sales=current_draft.total_sales,
                        expenses=current_draft.expenses,
                        bank_deposit=current_draft.bank_deposit,
                        closing_balance=final_closing_balance,
                        receipt_files=current_draft.receipt_files,
                        uploaded_by=current_user.username,
                        company=current_draft.company,
                        safe_box_balance=current_draft.safe_box_balance,
                        discrepancy_amount=current_draft.discrepancy_amount,
                        discrepancy_type=current_draft.discrepancy_type,
                        discrepancy_reason=current_draft.discrepancy_reason,
                        # Restore the Xero publish markers carried on the draft by
                        # revert_report_to_draft. Publishing stores no Xero object
                        # IDs, so a re-publish duplicates every transaction; these
                        # are what let the publish flow warn about that. Normal
                        # first-time drafts carry None/False and are unaffected.
                        publishing_status=current_draft.publishing_status,
                        xero_integrated_yes=bool(current_draft.xero_integrated_yes),
                    )
                    db.session.add(posted_report)
                    logger.info(
                        f"Added new Report record to session for draft {current_draft.id}"
                    )
                else:
                    # If report already exists, use the existing one
                    posted_report = existing_report
                    logger.info(
                        f"Using existing Report record for draft {current_draft.id}"
                    )
                    # Last submitter is the name shown
                    posted_report.uploaded_by = current_user.username

                    # Update all fields from draft when in edit mode
                    posted_report.date = datetime.now(
                        tz
                    )  # Update date to current timestamp
                    posted_report.opening_balance = current_draft.opening_balance
                    posted_report.cash_addition = current_draft.cash_addition
                    posted_report.adjusted_opening_balance = (
                        current_draft.adjusted_opening_balance
                    )
                    posted_report.cash_sales = current_draft.cash_sales
                    posted_report.shop_sales = current_draft.shop_sales
                    posted_report.delivery_sales = current_draft.delivery_sales
                    posted_report.total_sales = current_draft.total_sales
                    posted_report.expenses = current_draft.expenses
                    posted_report.bank_deposit = current_draft.bank_deposit
                    posted_report.safe_box_balance = current_draft.safe_box_balance

                    # Recalculate closing balance with discrepancy (discrepancy_amount is already signed)
                    # Get cash sales from ReportSaleDetail with fallback to current_draft.cash_sales
                    cash_sales = get_cash_sales_from_detail(
                        current_draft.id, fallback_value=current_draft.cash_sales or 0.0
                    )
                    base_closing_balance = (
                        (current_draft.opening_balance or 0)
                        + (current_draft.cash_addition or 0)
                        + cash_sales
                        - (current_draft.expenses or 0)
                        - (current_draft.bank_deposit or 0)
                    )
                    posted_report.closing_balance = base_closing_balance + (
                        current_draft.discrepancy_amount or 0
                    )
                    posted_report.discrepancy_amount = current_draft.discrepancy_amount
                    posted_report.discrepancy_type = current_draft.discrepancy_type
                    posted_report.discrepancy_reason = current_draft.discrepancy_reason

                # Process expense drafts with rollback protection
                try:
                    logger.info("=== EXPENSE PROCESSING PHASE ===")
                    logger.info(
                        f"Processing expense drafts for draft {current_draft.id}"
                    )
                    shop_expense_drafts = ShopExpenseDraft.query.filter(
                        ShopExpenseDraft.report_draft_id == current_draft.id
                    ).all()
                    logger.info(f"Found {len(shop_expense_drafts)} expense drafts")

                    # Log each expense draft
                    for i, expense_draft in enumerate(shop_expense_drafts):
                        logger.info(
                            f"Expense {i+1}: {expense_draft.item} - ${expense_draft.amount}"
                        )
                        if expense_draft.remarks:
                            logger.info(f"  Remarks: {expense_draft.remarks}")
                        if expense_draft.contact_id:
                            logger.info(f"  Contact ID: {expense_draft.contact_id}")
                        if expense_draft.account_id:
                            logger.info(f"  Account ID: {expense_draft.account_id}")

                    # Validate expense drafts data
                    for expense_draft in shop_expense_drafts:
                        if not expense_draft.item or expense_draft.item.strip() == "":
                            logger.error(
                                f"Expense draft {expense_draft.id} has empty item name"
                            )
                            raise ValueError("Expense item cannot be empty")
                        if not expense_draft.amount or expense_draft.amount <= 0:
                            logger.error(
                                f"Expense draft {expense_draft.id} has invalid amount: {expense_draft.amount}"
                            )
                            raise ValueError(
                                "Expense amount must be greater than zero"
                            )

                    shop_expenses = ShopExpense.query.filter(
                        ShopExpense.report_id == current_draft.id
                    ).all()
                    logger.info(
                        f"Found {len(shop_expenses)} existing shop expenses"
                    )

                    # Resolve contact_name once per contact_id for this report so a
                    # missing name on the draft still lands on the final expense.
                    entity_id = current_draft.company
                    contact_name_cache = {}

                    def _contact_name_for(draft):
                        name = draft.contact_name
                        if name or not draft.contact_id:
                            return name
                        if draft.contact_id not in contact_name_cache:
                            contact_name_cache[draft.contact_id] = resolve_contact_name(
                                entity_id, draft.contact_id
                            )
                        return contact_name_cache[draft.contact_id]

                    expense_drafts = []
                    for shop_expense_draft in shop_expense_drafts:
                        # Check if this expense draft already exists in shop expenses
                        existing_expense = next(
                            (
                                exp
                                for exp in shop_expenses
                                if exp.id == shop_expense_draft.id
                            ),
                            None,
                        )

                        if not existing_expense:
                            # If the expense draft is not in the shop expenses, add it to the database
                            expense_drafts.append(
                                ShopExpense(
                                    id=shop_expense_draft.id,
                                    report_id=shop_expense_draft.report_draft_id,
                                    item=shop_expense_draft.item,
                                    amount=shop_expense_draft.amount,
                                    remarks=shop_expense_draft.remarks,
                                    files=shop_expense_draft.files,
                                    account_code=shop_expense_draft.account_code,
                                    item_code=shop_expense_draft.item_code,
                                    account_id=shop_expense_draft.account_id,
                                    contact_id=shop_expense_draft.contact_id,
                                    contact_name=shop_expense_draft.contact_name,
                                )
                            )
                            logger.info(
                                f"Added new expense draft: {shop_expense_draft.item}"
                            )
                        else:
                            # If the expense draft is in the shop expenses, update the expense
                            existing_expense.item = shop_expense_draft.item
                            existing_expense.amount = shop_expense_draft.amount
                            existing_expense.remarks = shop_expense_draft.remarks
                            existing_expense.files = shop_expense_draft.files
                            existing_expense.account_code = (
                                shop_expense_draft.account_code
                            )
                            existing_expense.item_code = shop_expense_draft.item_code
                            existing_expense.account_id = shop_expense_draft.account_id
                            existing_expense.contact_id = shop_expense_draft.contact_id
                            existing_expense.contact_name = (
                                shop_expense_draft.contact_name
                            )
                            logger.info(
                                f"Updated existing expense: {shop_expense_draft.item}"
                            )

                    db.session.add_all(expense_drafts)
                    logger.info(
                        f"Added {len(expense_drafts)} expense drafts to session"
                    )

                    db.session.commit()
                    logger.info("Database session flushed successfully")

                except Exception as expense_error:
                    logger.error(
                        f"Error processing expense drafts: {str(expense_error)}"
                    )
                    db.session.rollback()
                    raise expense_error

                # Final commit and status update with rollback protection
                if "submitted" not in completed_sections:
                    try:
                        logger.info("=== FINAL COMMIT PHASE ===")
                        # Final validation before commit
                        logger.info(
                            f"Performing final validation before commit for {current_draft.id}"
                        )
                        logger.info(
                            f"Current completed sections: {completed_sections}"
                        )
                        logger.info(f"Current draft status: {current_draft.status}")
                        logger.info(
                            f"Current draft section: {current_draft.current_section}"
                        )

                        # Validate that all required data is present
                        if not posted_report:
                            raise ValueError("Report record not created properly")

                        # Validate that expense drafts were processed correctly
                        final_expenses = ShopExpense.query.filter(
                            ShopExpense.report_id == current_draft.id
                        ).all()
                        if (
                            "expenses" in completed_sections
                            and len(final_expenses) == 0
                        ):
                            logger.warning(
                                f"No expenses found for report {current_draft.id} despite expenses section being completed"
                            )

                        # Validate cash count data if applicable
                        if "cash_count" in completed_sections and cashcount_draft:
                            if (
                                not cashcount_draft.actual_cash_total
                                or cashcount_draft.actual_cash_total <= 0
                            ):
                                logger.warning(
                                    f"Cash count total is zero or negative for report {current_draft.id}"
                                )

                        logger.info(
                            f"Final validation passed for {current_draft.id}"
                        )

                        logger.info(
                            f"Updating draft status to submitted for {current_draft.id}"
                        )
                        logger.info("Adding 'submitted' to completed sections")
                        completed_sections.append("submitted")
                        current_draft.completed_sections = completed_sections
                        current_draft.current_section = "submitted"
                        current_draft.status = "posted"

                        logger.info("Committing database changes...")
                        db.session.commit()

                        logger.info("=== SUBMISSION SUCCESSFUL ===")
                        logger.info(
                            f"Report {current_draft.id} submitted successfully"
                        )
                        logger.info(
                            f"Final completed sections: {completed_sections}"
                        )
                        logger.info(f"Final draft status: {current_draft.status}")
                        logger.info(
                            f"Final draft section: {current_draft.current_section}"
                        )
                        logger.info(f"Posted report ID: {posted_report.id}")
                        logger.info("=== END SUBMISSION SUCCESS ===")

                        return redirect(
                            url_for(
                                "report.report_submitted",
                                entity_id=entity_id,
                                id=posted_report.id,
                            )
                        )
                    except Exception as commit_error:
                        logger.error("=== FINAL COMMIT ERROR ===")
                        logger.error(
                            f"Error during final commit for draft {current_draft.id}: {str(commit_error)}"
                        )
                        logger.error(f"Error type: {type(commit_error).__name__}")
                        logger.error("Rolling back database session...")
                        db.session.rollback()
                        logger.error("=== END FINAL COMMIT ERROR ===")
                        raise commit_error
                else:
                    logger.warning(f"Report {current_draft.id} already submitted")
                    flash("This one's already been submitted!", "warning")
                    return redirect(
                        url_for("entity.report_dashboard", id=entity_id)
                    )
            else:
                # Report already submitted, redirect to dashboard
                logger.warning(
                    f"Report {current_draft.id} already submitted, redirecting to dashboard"
                )
                flash("This one's already been submitted!", "warning")
                return redirect(
                    url_for("entity.report_dashboard", id=entity_id)
                )

        except Exception as e:
            # Comprehensive rollback on error
            logger.error("=== SUBMISSION FAILURE ===")
            logger.error(
                f"Unexpected error during report ending submission for draft {current_draft.id if current_draft else 'unknown'}"
            )
            logger.error(f"Error: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            if entity_id:
                logger.error(f"Entity ID: {entity_id}")
            logger.error(
                f"User: {current_user.username if current_user else 'None'}"
            )
            logger.error(
                f"Company: {entity_id if entity_id else 'None'}"
            )
            logger.error(
                f"Transaction Date: {current_draft.transaction_date if current_draft else 'None'}"
            )
            logger.error(
                f"Completed Sections: {completed_sections if 'completed_sections' in locals() else 'Unknown'}"
            )
            logger.error("=== ROLLING BACK DATABASE ===")

            # Perform comprehensive rollback
            try:
                db.session.rollback()
                logger.info(
                    f"Database rollback completed for draft {current_draft.id}"
                )
            except Exception as rollback_error:
                logger.error(f"Error during database rollback: {rollback_error}")
                logger.error(
                    f"Rollback error type: {type(rollback_error).__name__}"
                )

            # Check and restore draft state after rollback
            try:
                logger.info("Checking draft state after rollback...")
                draft_check = ReportDraft.query.filter_by(id=current_draft.id).first()
                if not draft_check:
                    logger.error(
                        f"Draft record {current_draft.id} was lost due to rollback - this is a critical error"
                    )
                    flash(
                        "I'm so sorry - your draft was lost and I couldn't recover it. You'll need to start this report over.",
                        "danger",
                    )
                    return redirect(
                        url_for("report.report_opening", entity_id=entity_id)
                    )
                else:
                    logger.info(
                        f"Draft record {current_draft.id} preserved after rollback"
                    )

                    # Check if any partial data was created and needs cleanup
                    existing_report = Report.query.filter(
                        Report.id == current_draft.id
                    ).first()
                    existing_expenses = ShopExpense.query.filter(
                        ShopExpense.report_id == current_draft.id
                    ).all()

                    if existing_report or existing_expenses:
                        logger.warning("=== PARTIAL DATA CLEANUP ===")
                        logger.warning(
                            f"Partial data exists for {current_draft.id} - attempting cleanup"
                        )
                        logger.warning(
                            f"Existing report: {existing_report is not None}"
                        )
                        logger.warning(
                            f"Existing expenses count: {len(existing_expenses)}"
                        )
                        cleanup_success = cleanup_partial_submission_data(
                            current_draft.id
                        )
                        if cleanup_success:
                            logger.info(
                                f"Successfully cleaned up partial data for {current_draft.id}"
                            )
                        else:
                            logger.error(
                                f"Failed to clean up partial data for {current_draft.id} - manual cleanup may be required"
                            )
                        logger.warning("=== END PARTIAL DATA CLEANUP ===")

            except Exception as check_error:
                logger.error(
                    f"Error checking draft status after rollback: {check_error}"
                )

            # Determine error type and provide appropriate user message
            logger.info("=== ERROR TYPE DETERMINATION ===")
            error_type = "database"
            if "connection" in str(e).lower() or "timeout" in str(e).lower():
                error_type = "connection"
                logger.info("Error classified as connection issue")
            elif "constraint" in str(e).lower() or "foreign key" in str(e).lower():
                error_type = "constraint"
                logger.info("Error classified as constraint violation")
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_type = "permission"
                logger.info("Error classified as permission issue")
            else:
                logger.info("Error classified as general database issue")
            logger.info("=== END ERROR TYPE DETERMINATION ===")

            if error_type == "connection":
                logger.info("Showing connection error message to user")
                flash(
                    "Something went wrong reaching the server. Could you check your connection and try again?",
                    "warning",
                )
            elif error_type == "constraint":
                logger.info("Showing constraint error message to user")
                flash(
                    "Something in the report data doesn't look right to me. Could you check your entries and try again?",
                    "warning",
                )
            elif error_type == "permission":
                logger.info("Showing permission error message to user")
                flash(
                    "I couldn't save your report - something on our end blocked it. Nothing was submitted, so please contact your administrator before trying again.",
                    "danger",
                )
            else:
                logger.info("Showing general error message to user")
                flash(
                    "Something went wrong on my end while submitting your report. Mind trying again?",
                    "danger",
                )

            logger.info("=== REDIRECTING TO REPORT ENDING ===")
            logger.info(f"Redirecting to report_ending with entity_id: {entity_id}")
            logger.error("=== END SUBMISSION FAILURE ===")
            return redirect(url_for("report.report_ending", entity_id=entity_id))

    bank_deposit = current_draft.bank_deposit if current_draft.bank_deposit else 0
    cash_expense = total_expense  # Total of all individual expenses added
    safe_box_balance = (
        cashcount_draft.safe_box_balance
        if cashcount_draft and cashcount_draft.safe_box_balance
        else 0
    )
    total_expense = (
        cash_expense + bank_deposit + safe_box_balance
    )  # Total expenses = cash expenses + bank deposits + safe box balance

    # For new reports (no id parameter), always consider them as latest/editable
    is_latest_report = True

    # Calculate yesterday's sales for comparison
    yesterday_date = transaction_date - timedelta(days=1) if transaction_date else None
    yesterday_sales = 0
    sales_difference = 0
    sales_percentage = 0
    sales_percentage_abs = 0
    is_sales_increase = False

    if yesterday_date:
        yesterday_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == yesterday_date,
        ).first()

        if yesterday_report and yesterday_report.total_sales:
            yesterday_sales = yesterday_report.total_sales
            sales_difference = total_sales - yesterday_sales
            if yesterday_sales > 0:
                sales_percentage = (sales_difference / yesterday_sales) * 100
            is_sales_increase = sales_difference > 0
            sales_percentage_abs = abs(sales_percentage)

    # Get sales history for last 30 days
    sales_history = []
    if transaction_date:
        today_date = transaction_date
        for i in range(29, -1, -1):  # 29 days ago to today (30 days total)
            date = today_date - timedelta(days=i)
            is_today = i == 0  # Today is the last day (i == 0)

            # If it's today, use current draft's sales (even if not submitted yet)
            if is_today:
                sales_value = total_sales if total_sales else 0
            else:
                day_report = Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date == date,
                ).first()
                sales_value = (
                    day_report.total_sales
                    if day_report and day_report.total_sales
                    else 0
                )

            month_abbr = date.strftime("%b").upper()
            day_num = date.strftime("%d").lstrip("0") or "0"
            day_name = date.strftime("%a").upper()
            date_label = f"{day_num} {month_abbr} {day_name}"

            sales_history.append(
                {"date": date_label, "value": sales_value, "is_today": is_today}
            )

    # Surface the posted report's Xero publish state so the header badge can
    # show "Partially Published" (set on Report, not on the ReportDraft above).
    posted_report_row = Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == transaction_date,
    ).first()
    header_publishing_status = (
        posted_report_row.publishing_status if posted_report_row else None
    )

    return render_template(
        "report/ending.html",
        org=user_entity,
        completed_sections=completed_sections,
        current_section="ending",
        current_draft=current_draft,
        report_draft=current_draft,
        header_publishing_status=header_publishing_status,
        total_expense=total_expense,
        electronic_sales=electronic_sales,
        delivery_sales=delivery_sales,
        cash_sales=cash_sales,
        total_sales=total_sales,
        cash_balance=cash_balance,
        total_actual_cash=total_actual_cash,
        expected_cash_count_balance=(
            current_draft.opening_balance
            + (current_draft.cash_addition or 0)
            + (current_draft.cash_sales or 0)
            - (current_draft.expenses or 0)
            - (current_draft.bank_deposit or 0)
            if current_draft
            else 0
        ),
        discrepancy_amount=discrepancy_amount,
        discrepancy_type=discrepancy_type,
        discrepancy_reason=discrepancy_reason,
        bank_deposit=bank_deposit,
        cash_expense=cash_expense,
        transaction_date=transaction_date,
        is_latest_report=is_latest_report,
        today_date=datetime.now().date(),
        cashcount_draft=cashcount_draft,
        closing_balance=current_draft.closing_balance if current_draft else 0,
        existing_expenses=existing_expenses,
        entity_acronym=entity_acronym,
        display_date=display_date,
        yesterday_sales=yesterday_sales,
        sales_difference=sales_difference,
        sales_percentage=sales_percentage,
        sales_percentage_abs=sales_percentage_abs,
        is_sales_increase=is_sales_increase,
        sales_history=sales_history,
        is_shared_link=skip_auth,
        sale_info=sale_info,
        sales_amounts=sales_amounts,
        is_edit_mode=is_edit_mode,
    )
