import uuid
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.cash_denominations import (
    build_denomination_rows, counts_to_legacy_columns, form_field_for,
    resolve_denominations_for_entity, save_cash_count_details)
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (check_user_has_entities,
                                               header_publishing_status_for,
                                               resolve_report_entity_id,
                                               safe_float,
                                               update_draft_progress)
from blueprints.shared.entity_display import entity_badge_data
from models.db import (Entity, Report, ReportCashCountDraft, ReportDetail,
                       ReportDraft, db)
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@report_bp.route("/report/cash_count", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/cash_count", methods=["GET"])
@login_required
def report_cash_count(id=None):
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

    if id:
        report = (
            Report.query.join(
                ReportDraft,
                ReportDraft.id == Report.id,
                full=True) .join(
                ReportCashCountDraft,
                ReportCashCountDraft.report_id == ReportDraft.id,
                full=True,
            ) .filter(
                Report.id == id,
                ReportDraft.id == id,
                Report.company == entity_id,
                ReportDraft.company == entity_id,
            ) .with_entities(
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
        user_entity = Entity.query.get_or_404(report.company)
        entity_acronym, display_date = entity_badge_data(user_entity)
        completed_sections = (
            report.completed_sections if report.completed_sections else []
        )
        cashcount_draft = ReportCashCountDraft.query.filter(
            ReportCashCountDraft.report_id == report.id
        ).first()

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
            "report/cash_count.html",
            org=user_entity,
            completed_sections=completed_sections,
            current_section="cash_count",
            current_draft=report,
            header_publishing_status=header_publishing_status_for(report_id=(report.id if report else None)),
            cashcount_draft=cashcount_draft,
            safe_box_balance=(
                cashcount_draft.safe_box_balance if cashcount_draft else 0.00),
            closing_balance=report.closing_balance if report.closing_balance else 0.00,
            datenow=datetime.now(),
            transaction_date=report.transaction_date,
            is_latest_report=is_latest_report,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
            denomination_rows=build_denomination_rows(
                entity_id,
                report_id=report.id,
                fallback_draft=cashcount_draft,
            ),
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
                f"Cash count form - Using selected date from URL/form: {transaction_date}"
            )
        except ValueError:
            logger.warning(
                f"Cash count form - Invalid date format: {selected_date}, using today"
            )
            transaction_date = datetime.now().date()
    else:
        transaction_date = datetime.now().date()
        logger.info(
            f"Cash count form - No date provided, using today: {transaction_date}"
        )

    # If edit mode is enabled and no id provided, try to load any existing
    # report for this date
    if is_edit_mode and not id:
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
        ).first()
        if existing_report:
            # Redirect to cash_count page with report id
            return redirect(
                url_for(
                    "report.report_cash_count",
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

    logger.info("Cash count form - Looking for existing draft:")
    logger.info(f"  Company: {entity_id}")
    logger.info(f"  Transaction date: {transaction_date}")
    logger.info(f"  Username: {current_user.username}")
    logger.info(
        f"  Found existing draft: {current_draft.id if current_draft else 'None'}"
    )

    if current_draft:
        cashcount_draft = ReportCashCountDraft.query.filter(
            ReportCashCountDraft.report_id == current_draft.id
        ).first()
    else:
        cashcount_draft = None

    # Denominations this entity logs, in display order. Drives both the form
    # and the POST parsing, so the two can never drift apart.
    denominations = resolve_denominations_for_entity(entity_id)

    if request.method == "POST":
        # Check if current_draft exists
        if not current_draft:
            flash(
                "I don't see a draft for today yet - let's start with the opening entry.",
                "warning",
            )
            return redirect(url_for("report.report_opening"))

        expected_balance = (
            (current_draft.opening_balance or 0)
            + (current_draft.cash_addition or 0)
            + (current_draft.cash_sales or 0)
            - (current_draft.expenses or 0)
            - (current_draft.bank_deposit or 0)
        )
        if expected_balance < 0:
            flash("Hmm, it looks like your cash balance is negative. Could you fix that first?", "danger")
            return redirect(
                url_for(
                    "report.report_cash_count",
                    entity_id=entity_id,
                    transaction_date=transaction_date.strftime("%Y-%m-%d"),
                )
            )

        try:
            # Get form data for cash count
            safe_box_balance = safe_float(
                request.form.get("safe_box_balance", 0))
            discrepancy_amount = safe_float(
                request.form.get("discrepancy_amount", 0))
            discrepancy_type = request.form.get("discrepancy_type", "none")
            discrepancy_reason = request.form.get("discrepancy_reason", "")

            # Read one quantity per denomination the entity logs. Face values
            # come from cash_info, so adding a denomination is an INSERT
            # there — no change here.
            if not denominations:
                logger.error(
                    f"No cash denominations resolved for entity {entity_id} "
                    "— cannot record a cash count"
                )
                flash(
                    "I don't have any cash denominations set up for this entity yet. "
                    "Please check the entity's country settings.",
                    "danger",
                )
                return redirect(
                    url_for(
                        "report.report_cash_count",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )

            counts_by_cash_id = {}
            total_cash_count = 0.0
            for denomination in denominations:
                quantity = safe_float(
                    request.form.get(
                        f"actual_cash[{form_field_for(denomination)}]", 0
                    )
                )
                counts_by_cash_id[denomination.cash_id] = int(quantity or 0)
                total_cash_count += (denomination.cash_value or 0) * quantity

            # Log cash count data for debugging
            logger.info(f"Cash count data for draft {current_draft.id}:")
            logger.info(f"  Safe box balance: {safe_box_balance}")
            logger.info(
                "  Counted: "
                + ", ".join(
                    f"{d.cash_value:g}x{counts_by_cash_id[d.cash_id]}"
                    for d in denominations
                )
            )

            # Calculate expected cash count balance: opening_balance +
            # cash_sales - expenses - deposit
            opening_balance = current_draft.opening_balance or 0
            cash_addition = current_draft.cash_addition or 0
            cash_sales = current_draft.cash_sales or 0
            expenses = current_draft.expenses or 0
            deposit_cash = current_draft.bank_deposit or 0
            expected_cash_count_balance = (
                opening_balance +
                cash_addition +
                cash_sales -
                expenses -
                deposit_cash)

            # Calculate discrepancy: expected cash count balance - cash count
            # balance - safe box balance
            discrepancy = (
                total_cash_count - expected_cash_count_balance
            ) + safe_box_balance
            actual_cash_total = total_cash_count
            # Determine discrepancy type and amount
            if (
                discrepancy < -0.01 or discrepancy > 0.01
            ):  # Use small threshold to avoid floating point issues
                discrepancy_type = "shortage" if discrepancy < 0 else "surplus"
                discrepancy_amount = discrepancy
            else:
                discrepancy_type = "none"
                discrepancy_amount = 0.0
            logger.info(f"  Calculated actual cash total: {actual_cash_total}")
            logger.info(
                f"  Total cash count (actual + safe box): {actual_cash_total + safe_box_balance}"
            )
            logger.info(f"  Calculated discrepancy: {discrepancy}")
            logger.info(f"  Discrepancy type: {discrepancy_type}")
            logger.info(f"  Discrepancy amount: {discrepancy_amount}")
            logger.info(f"  Discrepancy reason: {discrepancy_reason}")

            # Track last editor
            current_draft.uploaded_by = current_user.username

            # The nine note/coin columns still have five readers (ending.py,
            # export_screenshot.py, deposit.py, the template, and the
            # next-day opening balance), so keep them in sync with the detail
            # rows until those are converted. Denominations without a legacy
            # column — the HK$200 note, and anything an entity adds — live
            # only in report_cashcount_detail.
            legacy_columns = counts_to_legacy_columns(counts_by_cash_id)

            if not cashcount_draft:
                cashcount_draft = ReportCashCountDraft(
                    id=str(uuid.uuid4()),
                    report_id=current_draft.id,
                    safe_box_balance=safe_box_balance,
                    discrepancy_amount=discrepancy_amount,
                    discrepancy_type=discrepancy_type,
                    discrepancy_reason=discrepancy_reason,
                    actual_cash_total=total_cash_count,
                    **legacy_columns,
                )

                # Update current_draft with discrepancy information
                current_draft.discrepancy_amount = discrepancy_amount
                current_draft.discrepancy_reason = discrepancy_reason
                current_draft.discrepancy_type = discrepancy_type
                current_draft.safe_box_balance = safe_box_balance

                logger.info(
                    f"  Updated current_draft.discrepancy_amount: {current_draft.discrepancy_amount}"
                )
                logger.info(
                    f"  Updated current_draft.discrepancy_reason: {current_draft.discrepancy_reason}"
                )
                logger.info(
                    f"  Updated current_draft.discrepancy_type: {current_draft.discrepancy_type}"
                )

                db.session.add(cashcount_draft)

                # Create ReportDetail with discrepancy information
                report_detail = ReportDetail(
                    report_id=current_draft.id,
                    entity_id=entity_id,
                    opening_balance=opening_balance,
                    adjusted_opening_balance=current_draft.adjusted_opening_balance,
                    nocashsale_total=current_draft.total_sales -
                    cash_sales,
                    cashsale_total=cash_sales,
                    expense_total=expenses,
                    discrepancy_amount=discrepancy_amount,
                    discrepancy_description=discrepancy_reason,
                )
                db.session.add(report_detail)
            else:
                for column, count in legacy_columns.items():
                    setattr(cashcount_draft, column, count)
                cashcount_draft.safe_box_balance = safe_box_balance
                cashcount_draft.discrepancy_amount = discrepancy_amount
                cashcount_draft.discrepancy_type = discrepancy_type
                cashcount_draft.discrepancy_reason = discrepancy_reason
                cashcount_draft.actual_cash_total = total_cash_count

                # Update current_draft with discrepancy information
                current_draft.discrepancy_amount = discrepancy_amount
                current_draft.discrepancy_reason = discrepancy_reason
                current_draft.discrepancy_type = discrepancy_type
                current_draft.safe_box_balance = safe_box_balance

                logger.info(
                    f"  Updated current_draft.discrepancy_amount: {current_draft.discrepancy_amount}"
                )
                logger.info(
                    f"  Updated current_draft.discrepancy_reason: {current_draft.discrepancy_reason}"
                )
                logger.info(
                    f"  Updated current_draft.discrepancy_type: {current_draft.discrepancy_type}"
                )

                # Update or create ReportDetail with discrepancy information
                report_detail = ReportDetail.query.filter(
                    ReportDetail.report_id == current_draft.id,
                    ReportDetail.entity_id == entity_id,
                ).first()

                if not report_detail:
                    report_detail = ReportDetail(
                        report_id=current_draft.id,
                        entity_id=entity_id,
                        opening_balance=opening_balance,
                        adjusted_opening_balance=current_draft.adjusted_opening_balance,
                        nocashsale_total=current_draft.total_sales -
                        cash_sales,
                        cashsale_total=cash_sales,
                        expense_total=expenses,
                    )
                    db.session.add(report_detail)

                # Update discrepancy fields in ReportDetail
                report_detail.discrepancy_amount = discrepancy_amount
                report_detail.discrepancy_description = discrepancy_reason
                cashcount_draft.actual_cash_total = actual_cash_total

            # Per-denomination counts — the source of truth. Written in the
            # same transaction as the discrepancy it drives, so the two can
            # never be committed out of step.
            save_cash_count_details(current_draft.id, counts_by_cash_id)

            db.session.commit()

            # Verify the update was saved
            logger.info(
                f"  Verifying saved discrepancy data for draft {current_draft.id}"
            )
            saved_draft = ReportDraft.query.filter(
                ReportDraft.id == current_draft.id
            ).first()
            if saved_draft:
                logger.info(
                    f"  Saved discrepancy_amount: {saved_draft.discrepancy_amount}"
                )
                logger.info(
                    f"  Saved discrepancy_reason: {saved_draft.discrepancy_reason}"
                )
                logger.info(
                    f"  Saved discrepancy_type: {saved_draft.discrepancy_type}")
            else:
                logger.error(
                    f"  ERROR: Could not retrieve saved draft {current_draft.id}"
                )

            # Log the cash count addition to draft history
            log_history_draft(
                report_draft_id=current_draft.id,
                company=entity_id,
                user_id=current_draft.uploaded_by,
                action="added",
                field_changed="cash_count",
                old_value="previous_cash_count",
                new_value=f"Cash Count: ${actual_cash_total + safe_box_balance}",
            )

            # Update progress tracking
            action_type = request.form.get("action_type", "save_next")
            if action_type == "save_next":
                update_draft_progress(
                    current_draft, action_type, "cash_count", "ending"
                )
            else:
                # save_exit: keep current_section at cash_count but do NOT add cash_count to completed_sections,
                # so user cannot access ending page until they complete cash
                # count with Save & Next
                current_draft.current_section = "cash_count"

            db.session.commit()

            # Check action type and redirect accordingly
            action_type = request.form.get("action_type", "save_next")
            if action_type == "save_next":
                return redirect(
                    url_for(
                        "report.report_ending",
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
                        "report.report_ending",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
        except Exception as e:
            db.session.rollback()
            print(f"Error updating cash count: {str(e)}")
            flash(
                "Something went wrong saving your cash count. Mind trying again?",
                "danger")
            return redirect(
                url_for(
                    "report.report_cash_count",
                    entity_id=entity_id,
                    transaction_date=transaction_date.strftime("%Y-%m-%d"),
                )
            )

    # Handle case where no draft exists
    if not current_draft:
        flash(
            "I don't see a draft for today yet - let's start with the opening entry.",
            "warning",
        )
        return redirect(url_for("report.report_opening"))

    # Get entity for the template
    entity = Entity.query.filter(Entity.id == entity_id).first()
    entity_acronym, display_date = entity_badge_data(entity)

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
        "report/cash_count.html",
        org=entity,
        completed_sections=completed_sections,
        current_section="cash_count",
        current_draft=current_draft,
        header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
        transaction_date=transaction_date,
        cashcount_draft=cashcount_draft,
        safe_box_balance=cashcount_draft.safe_box_balance if cashcount_draft else 0.00,
        closing_balance=(
            current_draft.closing_balance if current_draft.closing_balance else 0.00),
        datenow=datetime.now(),
        is_latest_report=is_latest_report,
        entity_acronym=entity_acronym,
        display_date=display_date,
        is_edit_mode=is_edit_mode,
        denomination_rows=build_denomination_rows(
            entity_id,
            report_id=current_draft.id if current_draft else None,
            fallback_draft=cashcount_draft,
        ),
    )
