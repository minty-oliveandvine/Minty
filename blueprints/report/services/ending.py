# Report ending services; extracted from report routes.

# Report ending routes; delegates to app implementation.
# Ending step: report_ending transferred from app.py (single function, no
# new functions).
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from services.app_runtime.log import logger
from sqlalchemy.orm.attributes import flag_modified

from blueprints.report.services.cash_denominations import (
    cash_summary, get_cash_count_details)
from blueprints.report.services.report_page import expense_bars, sales_mix
from blueprints.report.services.shared import (check_user_has_entities,
                                               resolve_report_entity_id)
from blueprints.shared.entity_display import entity_badge_data
from blueprints.shared.enums import SaleType
from blueprints.shared.enums import ReportStatus
from models.db import (Entity, Report, ReportSaleDetail, EntitySaleSetting, SaleInfo, ShopExpense, UserEntity, db)
from services.permission_policy import (Permission, can_view_report,
                                        has_permission, is_superuser)


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




def convert_report_to_draft(report_id):
    """JSON endpoint for the Daily Report's Edit report: services/report_actions.py::reopen_report,
    shared with the Petty Cash API."""
    from blueprints.report.services.report_actions import ReportActionRefused, reopen_report

    report = Report.query.filter(Report.id == report_id).first()
    if report is None:
        return jsonify({"status": "error", "message": "Report not found"}), 404
    try:
        reopened = reopen_report(report, current_user)
    except ReportActionRefused as refused:
        return jsonify({"status": "error", "message": refused.message}), refused.status
    except Exception as e:
        logger.exception(f"Error converting report to draft: {str(e)}")
        return (
            jsonify({"status": "error", "message": "I couldn't convert that report to a draft. Mind trying again?"}),
            500,
        )
    return jsonify(
        {
            "status": "success",
            "message": "Report converted to draft",
            "draft_id": reopened.id,
            "transaction_date": reopened.transaction_date.strftime("%Y-%m-%d") if reopened.transaction_date else None,
        }
    )


def entity_ending(entity_id):
    from datetime import datetime

    # Signed-in only. The old ?token= public branch is gone (2026-10-05): it took a
    # 30-day HMAC token that ignored the ShareLink row, so revoking a link did nothing.
    # Public sharing is /Minty_Report/<initials>/<date>/<secret>/ alone.
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
        # Share-link target: SUBMITTED reports only, never a draft.
        db.or_(Report.status.is_(None), Report.status != "draft"),
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


def _submit_step_url(step, entity_id, day, report_id):
    """Where a refused submit sends the person: the step that fixes it, for the same day."""
    if step == "submitted":
        return url_for("report.report_submitted", entity_id=entity_id, id=report_id)
    if step == "dashboard":
        return url_for("entity.report_dashboard", id=entity_id)
    endpoint = {"opening": "report.report_opening", "sales": "report.report_sale",
                "expenses": "report.report_expense"}.get(step, "report.report_cash_count")
    return url_for(endpoint, entity_id=entity_id, transaction_date=day)


def report_ending(id=None, entity_id=None, skip_auth=False):
    # Lazy imports from app to avoid circular import
    # Diagnostic: the bounce below is a flash + 302, which logs nothing on its
    # own. Record what actually arrived so a lost query string, a stripped form
    # body and an expired session can be told apart from one another.
    logger.info(
        # The endpoint, not the path or the Referer: on a share link both carry its secret.
        "ENTITY-TRACE report_ending entry - method=%s endpoint=%s id=%s passed=%r "
        "args=%r form=%r xhr=%s auth=%s",
        request.method,
        request.endpoint,
        id,
        entity_id,
        request.args.get("entity_id"),
        request.form.get("entity_id"),
        request.headers.get("X-Requested-With"),
        getattr(current_user, "is_authenticated", False),
    )
    if entity_id is None:
        entity_id = request.args.get("entity_id") or request.form.get("entity_id")
    if not skip_auth and not entity_id:
        entity_id = resolve_report_entity_id(id)
    if not skip_auth and not entity_id:
        logger.error(
            "ENTITY-TRACE report_ending BOUNCE - method=%s arg_keys=%r form_keys=%r",
            request.method,
            list(request.args.keys()),
            list(request.form.keys()),
        )
        flash("I need to know which entity we're working with first!", "danger")
        return redirect(url_for("entity.entity_list"))
    if not skip_auth and not has_permission(
        current_user, Permission.REPORT_VIEW_OWN, entity_id
    ):
        flash("It looks like you don't have permission to view this entity's reports.", "danger")
        return redirect(url_for("entity.entity_list"))
    if not skip_auth and id:
        # ReportDraft fallback removed: since Stage 4a every draft has a paired
        # `report` row with the same id, so one lookup covers both.
        report_for_access = Report.query.filter_by(id=id).first()
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

        # Both joins are gone (Step 3.5). This used to outerjoin ReportDraft
        # and then chain the cash-count join off ReportDraft.id — the same
        # value as Report.id, but Step 2 stopped creating draft rows, so the
        # intermediate join yielded NULL and every column it fed came back
        # empty for any report created after the flip.
        #
        # Nothing needs either table now: completed_sections / current_section
        # / status live on Report since Stage 4a, safe_box_balance and the
        # discrepancy trio are written to Report by cash_count.py, and the nine
        # denomination columns were never read here at all.
        report = (
            Report.query
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
                Report.uploaded_by,
                Report.company,
                Report.xero_integrated_yes,
                # the column is jsonb (json on SQLite); casting to the column's own
                # type keeps COALESCE happy on both
                db.func.coalesce(
                    Report.completed_sections, db.cast("[]", Report.completed_sections.type)
                ).label("completed_sections"),
                db.func.coalesce(Report.current_section, db.null()).label(
                    "current_section"
                ),
                # Report.status is authoritative since Stage 4a and is set for
                # drafts too. The "posted" literal only answers for legacy rows
                # that predate the consolidation — line 637 branches on this to
                # choose ShopExpenseDraft vs ShopExpense, so defaulting an
                # in-progress report to "posted" would pick the wrong table.
                db.func.coalesce(Report.status, "submitted").label("status"),
                # The nine denomination columns that used to be selected here
                # were never read — ending.html renders no cash-count grid.
                # They went with Step 3.5 along with the join that fed them.
                #
                # These four DO get read (line ~658) and now come from `report`
                # itself, where cash_count.py has been writing them all along.
                # Selecting them off ReportCashCountDraft shadowed Report's own
                # identically-named columns in the result Row.
                Report.safe_box_balance,
                Report.discrepancy_amount,
                Report.discrepancy_type,
                Report.discrepancy_reason,
                # Step 4a-5 reads this below to decide whether the report was
                # counted at all (an all-zero count stores no rows). A Row from
                # with_entities only carries the columns named here, so leaving
                # it out raised AttributeError on the ending page.
                Report.actual_cash_total,
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

        # WRITE FLIP (Step 2): the self-heal block that used to sit here
        # created a ReportDraft when a Report had none. That state is no
        # longer reachable — the Report IS the draft — so the ~50 lines of
        # reconstruction went with it.
        report_draft = report

        # Ensure report has status attribute
        if not hasattr(report, "status") or not report.status:
            # Only reached when BOTH sides lack a status. Report.status is set
            # at draft creation since Stage 4a, so this is a legacy-row path;
            # "posted" is the right default there because a report row with no
            # draft and no status predates the consolidation.
            if report_draft and report_draft.status:
                report.status = report_draft.status
            else:
                report.status = ReportStatus.SUBMITTED

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
        # joined to the CATALOGUE (never deleted, only switched off per company), so a
        # method the company later removed still names its amount
        report_sale_details = (
            db.session.query(ReportSaleDetail, SaleInfo)
            .outerjoin(SaleInfo, ReportSaleDetail.sale_id == SaleInfo.id)
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
            # For drafts, calculate from the report's ShopExpense records
            # Read-only: migrated to ShopExpense (Stage 4b). The paired row now
            # exists from draft creation via ensure_shop_expense_for_draft, and
            # report_id holds the same value report_draft_id did.
            expense_drafts = ShopExpense.query.filter_by(
                report_id=report.id
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

        # The Daily Report's bar rows: the expenses summed per account (one joined read each).
        expense_chart = expense_bars(
            (e.account.name if e.account is not None else None, e.amount) for e in existing_expenses
        )

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
            sale_type = SaleType.normalize(
                sale_info_item.type if sale_info_item and sale_info_item.type else sale_detail.type
            )

            if sale_info_item is not None and sale_info_item.is_cash:
                cash_sales += amount
            elif sale_type == SaleType.DELIVERY:
                delivery_sales += amount
            elif sale_type is not None:  # electronic, and any other non-cash method
                electronic_sales += amount

        # Fallback to report.cash_sales if no cash sales found in ReportSaleDetail
        if cash_sales == 0:
            cash_sales = report.cash_sales if report.cash_sales else 0

        total_sales = report.total_sales if report.total_sales else 0
        # The Daily Report's proportion bar: the same methods as its "Sales by method" list
        # (electronic, then delivery without Deliveroo, then Cash).
        listed = [s for s in sale_info if SaleType.normalize(s.type) == SaleType.ELECTRONIC] + [
            s for s in sale_info
            if SaleType.normalize(s.type) == SaleType.DELIVERY and s.value_name != "deliveroo_sales"
        ]
        sales_chart = sales_mix(
            [(s, None, sales_amounts.get(s.value_name, 0)) for s in listed] + [(None, "Cash", cash_sales)]
        )
        # Calculate actual cash balance from cash count data - one
        # report_cash_summary row: NULL means never counted (show the closing
        # balance instead), 0 means counted with every denomination zero.
        total_actual_cash, cash_balance = cash_summary(report.id)
        if total_actual_cash is None:
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
        safe_box_balance = report.safe_box_balance or 0
        total_expense = (
            cash_expense + bank_deposit + safe_box_balance
        )  # Total expenses = cash expenses + bank deposits + safe box balance

        # Determine if this is the latest report (most recent transaction_date) or old report
        # Find the latest report ID for this entity (same logic as report_history)
        # Step 4a-6: was a full outer join to ReportDraft with a coalesce on
        # every column. Drafts live in `report` since Stage 4a, so the join,
        # the coalesces and the or_ all collapse to one table. No status filter
        # — "latest report" means any status here, which is what the full outer
        # join was expressing.
        latest_report = (
            Report.query
            .with_entities(Report.id, Report.transaction_date)
            .filter(Report.company == entity_id)
            .order_by(Report.transaction_date.desc())
            .first()
        )

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
            safe_box_balance=safe_box_balance,
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
            sales_chart=sales_chart,
            expense_chart=expense_chart,
            is_edit_mode=is_edit_mode,
        )

    # Get transaction date from the form or the URL — the finish form posts to
    # an action URL carrying both, so reading only one source per method lost
    # the date whenever the hidden field submitted empty. That silently fell
    # back to today below, so the draft lookup asked for the wrong day and
    # reported "no draft" for a date the user never requested.
    if request.method == "POST":
        entity_id = (
            entity_id
            or request.form.get("entity_id")
            or request.args.get("entity_id")
        )
        selected_date = (
            request.form.get("transaction_date")
            or request.args.get("transaction_date")
        )
    else:
        selected_date = request.args.get("transaction_date")
        entity_id = entity_id or request.args.get("entity_id")

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
            "Ending form - no transaction_date in form or URL, falling back to "
            f"today: {transaction_date} (method={request.method})"
        )

    # Get user entity
    user_entity = Entity.query.get(entity_id)
    entity_acronym, display_date = (
        entity_badge_data(user_entity) if user_entity else ("", None)
    )

    # If edit mode is enabled and no id provided, try to load any existing report for this date
    if is_edit_mode and not id:
        # Edit mode targets a SUBMITTED report; a draft is edited through the
        # wizard, not here.
        existing_report = Report.query.filter(
            db.or_(Report.status.is_(None), Report.status != "draft"),
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
    # WRITE FLIP (Step 2): current_draft drives the submit path. Reading
    # Report means submit flips the real row's status rather than copying a
    # draft across.
    if id:
        current_draft = Report.query.filter(
            Report.id == id,
            Report.company == entity_id,
            Report.status == "draft",
        ).first()
    else:
        current_draft = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
            Report.status == "draft",
        ).first()

    # Check if entity and draft exist
    if not user_entity:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    # If edit mode is enabled and no draft exists, try to load any existing report for this date
    if is_edit_mode and not current_draft:
        # Submitted only — see the note above.
        existing_report = Report.query.filter(
            db.or_(Report.status.is_(None), Report.status != "draft"),
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
        # Name the date actually queried. This said "today" regardless of which
        # date was looked up, so a miss on a back-dated report read as "no
        # draft for today" while a perfectly good draft for today existed.
        logger.warning(
            "Ending page - no draft found: entity=%s transaction_date=%s "
            "(id=%s, method=%s)",
            entity_id,
            transaction_date,
            id,
            request.method,
        )
        flash(
            "I don't see a draft for "
            f"{transaction_date.strftime('%d %b %Y')} yet - "
            "let's start with the opening entry.",
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
        db.session.query(ReportSaleDetail, SaleInfo)
        .outerjoin(SaleInfo, ReportSaleDetail.sale_id == SaleInfo.id)
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
    # Use ONLY amounts from ReportSaleDetail - no fallback to the report row
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
        sale_type = SaleType.normalize(
            sale_info_item.type if sale_info_item and sale_info_item.type else sale_detail.type
        )

        if sale_info_item is not None and sale_info_item.is_cash:
            cash_sales += amount
        elif sale_type == SaleType.DELIVERY:
            delivery_sales += amount
        elif sale_type is not None:  # electronic, and any other non-cash method
            electronic_sales += amount

    # Fallback to current_draft.cash_sales if no cash sales found in ReportSaleDetail
    if cash_sales == 0:
        cash_sales = current_draft.cash_sales if current_draft.cash_sales else 0

    # Calculate total expenses from individual expense records for drafts
    existing_expenses = []
    if current_draft.status == "draft":
        # For drafts, calculate from the report's ShopExpense records
        # Read-only: migrated to ShopExpense (Stage 4b). The paired row now
        # exists from draft creation via ensure_shop_expense_for_draft, and
        # report_id holds the same value report_draft_id did.
        expense_drafts = ShopExpense.query.filter_by(
            report_id=current_draft.id
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

    # Calculate actual cash balance from cash count data: one report_cash_summary
    # row (NULL = never counted, so the closing balance shows instead).
    total_actual_cash, cash_balance = cash_summary(current_draft.id)
    if total_actual_cash is not None:
        logger.info(f"Retrieved cash count data for draft {current_draft.id}:")
        # Enumerate what was actually counted rather than the nine fixed
        # columns, so custom denominations show up here too.
        counted = get_cash_count_details(current_draft.id)
        if counted:
            # Diagnostic only - never let it break the page. cash_value is
            # Numeric, so float() it before formatting, and the row's count
            # field is `quantity` (`.count` is SQLAlchemy's own attribute).
            try:
                logger.info(
                    "  Counted: "
                    + ", ".join(
                        f"{float(row.cash_value):g}x{row.quantity}"
                        for row in sorted(
                            counted.values(),
                            key=lambda r: -float(r.cash_value),
                        )
                    )
                )
            except Exception:
                logger.exception("  Counted: failed to format cash count rows")
        logger.info(f"  Safe box balance: {current_draft.safe_box_balance}")
        logger.info(f"  Calculated total_actual_cash: {total_actual_cash}")
        logger.info(f"  Final cash_balance: {cash_balance}")
    else:
        total_actual_cash = 0
        cash_balance = (
            current_draft.closing_balance if current_draft.closing_balance else 0
        )

    # Read off `report` (current_draft), where cash_count.py writes them. These
    # three used to dereference cashcount_draft with no None-guard, so a report
    # whose cash count was never saved raised AttributeError here.
    discrepancy_amount = current_draft.discrepancy_amount or 0
    discrepancy_type = current_draft.discrepancy_type or "none"
    discrepancy_reason = current_draft.discrepancy_reason or ""
    if request.method == "POST":
        # The submit's rules and writes: services/submit.py, shared with the Petty Cash API.
        from blueprints.report.services.submit import SubmitRefused, submit_report

        day = transaction_date.strftime("%Y-%m-%d")
        try:
            posted = submit_report(current_draft, current_user)
        except SubmitRefused as refused:
            flash(refused.message, "warning")
            return redirect(_submit_step_url(refused.to, entity_id, day, current_draft.id))
        except Exception:
            logger.exception(f"Submitting report {current_draft.id} failed; the draft is left as it was")
            flash("Something went wrong on my end while submitting your report. Nothing was submitted - "
                  "mind trying again?", "danger")
            return redirect(url_for("report.report_ending", entity_id=entity_id, transaction_date=day))
        return redirect(url_for("report.report_submitted", entity_id=entity_id, id=posted.id))

    bank_deposit = current_draft.bank_deposit if current_draft.bank_deposit else 0
    cash_expense = total_expense  # Total of all individual expenses added
    safe_box_balance = current_draft.safe_box_balance or 0
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
    # show "Partially Published" (set on Report by the publish flow).
    posted_report_row = Report.query.filter(
        db.or_(Report.status.is_(None), Report.status != "draft"),
        Report.company == entity_id,
        Report.transaction_date == transaction_date,
    ).first()
    header_publishing_status = (
        posted_report_row.publishing_status if posted_report_row else None
    )

    # The draft's Close stage (Part 15.15e, the work verification); a saved report by id renders
    # the Daily Report (report/ending.html) above.
    return render_template(
        "report/close.html",
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
        safe_box_balance=safe_box_balance,
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
