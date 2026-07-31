# Report sales routes; delegates to app implementation.


from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (
    check_user_has_entities, get_cash_sales_from_detail,
    header_publishing_status_for, parse_nested_keys, resolve_report_entity_id,
    safe_float, sum_sales_by_type, update_draft_progress,
    update_report_draft_sales_from_detail)
from blueprints.shared.entity_display import entity_badge_data
from models.db import (Entity, Report, ReportDraft, ReportSaleDetail,
                       EntitySaleSetting, db, tz)
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


def resolve_posted_sale_amount(field, shop_sales_data, delivery_sales_data):
    """Amount to store on a method's report_sale_detail row for this POST.

    The submitted form is authoritative. The sales form renders an input for
    every enabled method, so a method missing from the parsed data was cleared
    by the user — ``parse_nested_keys`` drops empty and "0" inputs — and means
    zero for this report, not "unchanged".

    Deliberately not an ``or`` chain and deliberately no fallback to the draft's
    legacy column. An ``or`` chain treats a real 0.0 as absent and resurrects
    the previous value, writing a detail row that disagrees with the column.
    Cash is the one method still stored in both places
    (``report_draft.cash_sales`` and its detail row), and that drift is what
    desynchronises the cash balance the deposit and cash-count steps compute:
    the deposit page totals the detail rows while cash count reads the column.
    """
    field_base = field.replace("_sales", "")

    if field_base in shop_sales_data:
        return safe_float(shop_sales_data[field_base])
    if field_base in delivery_sales_data:
        return safe_float(delivery_sales_data[field_base])
    return 0.0


def get_unique_sale_info_for_entity(entity_id):
    """
    Get unique payment methods for an entity, preventing duplicates.
    Returns: list of EntitySaleSetting objects ordered by display_order (matches Settings page).
    """
    payment_methods_subquery = (
        db.session.query(
            EntitySaleSetting.value_name,
            db.func.max(EntitySaleSetting.sale_id).label('max_sale_id')
        )
        .filter(
            EntitySaleSetting.entity_id == entity_id,
            EntitySaleSetting.value_name != "deliveroo_sales",
            EntitySaleSetting.enabled == True
        )
        .group_by(EntitySaleSetting.value_name)
        .subquery()
    )
    
    payment_methods = (
        db.session.query(EntitySaleSetting)
        .join(
            payment_methods_subquery,
            EntitySaleSetting.sale_id == payment_methods_subquery.c.max_sale_id
        )
        .order_by(EntitySaleSetting.display_order.asc(), EntitySaleSetting.create_date.asc())
        .all()
    )
    
    return payment_methods


@report_bp.route("/report/sale", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/sale", methods=["GET"])
@login_required
def report_sale(id=None):
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
        # The ReportDraft fallback that used to sit here is gone: since Stage 4a
        # every draft has a paired `report` row with the same id, so the first
        # lookup already covers drafts. Kept as one query, not two.
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
    # Check if user has any entities before allowing access to reports
    if not check_user_has_entities(current_user.id):
        flash("You'll need to create an entity before I can show you any reports.", "warning")
        return redirect(url_for("entity.entity_list"))

    # Check if edit mode is enabled
    is_edit_mode = (
        request.args.get("edit") == "true" or request.form.get("edit") == "true"
    )

    entity_acronym = ""
    display_date = None

    if id:
        report = (
            # Was a full outer join to ReportDraft that filtered BOTH ids to
            # `id`, collapsing it back to an inner join: `report` came back None
            # whenever either side was missing. completed_sections /
            # current_section live on `report` since r1a01.
            Report.query
            .filter(Report.id == id)
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
                Report.completed_sections,
                Report.current_section,
            )
            .first()
        )
        entity = Entity.query.get_or_404(entity_id)
        entity_acronym, display_date = entity_badge_data(entity)

        # Determine if this is the latest report (most recent transaction_date)
        # or old report
        latest_report_date = (
            db.session.query(
                db.func.max(
                    db.func.coalesce(
                        Report.transaction_date, ReportDraft.transaction_date
                    )
                )
            )
            .filter(
                db.or_(Report.company == entity_id, ReportDraft.company == entity_id),
            )
            .scalar()
        )

        is_latest_report = report.transaction_date == latest_report_date

        # Get sale_info for the entity (unique, no duplicates, proper order)
        sale_info_list = get_unique_sale_info_for_entity(entity_id)
        
        # Attach amounts from ReportSaleDetail for this report
        sale_info = []
        for sale_obj in sale_info_list:
            sale_detail = ReportSaleDetail.query.filter_by(
                report_id=report.id,
                sale_id=sale_obj.sale_id
            ).first()
            sale_obj.amount = sale_detail.amount if sale_detail else None
            sale_info.append(sale_obj)

        return render_template(
            "report/sales.html",
            datenow=datetime.now(),
            # Per-method amounts keyed by legacy value_name, sourced from
            # report_sale_detail via the sale_info rows attached above.
            sales_amounts={
                s.value_name: (s.amount or 0)
                for s in sale_info if s.value_name
            },
            org=entity,
            current_draft=report,
            header_publishing_status=header_publishing_status_for(report_id=(report.id if report else None)),
            report=report,
            current_section="sales",
            completed_sections=report.completed_sections if report else ["opening"],
            is_draft=True,
            draft_id=report.id if report else None,
            current_user=current_user,
            transaction_date=report.transaction_date,
            is_latest_report=is_latest_report,
            sale_info=sale_info,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
        )

    # NOTE: a second, byte-identical `if id:` block used to sit here. It was
    # unreachable — the block above ends in `return render_template(...)` — so
    # it was deleted rather than migrated off the ReportDraft join.

    if request.method == "POST":
        try:
            # Get action type from form
            action_type = request.form.get("action_type", "save_next")

            # Get transaction date from form
            transaction_date_str = request.form.get("transaction_date")

            if transaction_date_str:
                transaction_date = datetime.strptime(
                    transaction_date_str, "%Y-%m-%d"
                ).date()
            else:
                transaction_date = datetime.now().date()

            # If edit mode is enabled, check for any existing report for this
            # date
            if is_edit_mode:
                existing_report = Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date == transaction_date,
                ).first()
                if existing_report:
                    # Update existing report sales data
                    logger.info(
                        f"Edit mode - updating sales for report {existing_report.id}"
                    )
                    # The sales update logic will handle updating the report
                    # We'll update both Report and ReportDraft

            # Check for existing draft: by id when in URL, else by (entity,
            # transaction_date)
            logger.info("Sales form - Looking for existing draft:")
            logger.info(f"  Company: {entity_id}")
            logger.info(f"  Transaction date: {transaction_date}")
            if id:
                existing_draft = ReportDraft.query.filter_by(
                    id=id,
                    company=entity_id,
                    status="draft",
                ).first()
            else:
                existing_draft = ReportDraft.query.filter_by(
                    company=entity_id,
                    transaction_date=transaction_date,
                    status="draft",
                ).first()

            logger.info(
                f"Sales form - Found existing draft: {existing_draft.id if existing_draft else 'None'}"
            )

            # Debug logging only — deliberately unfiltered so the log shows
            # every row and its status. Nothing branches on this result.
            all_user_drafts = ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.uploaded_by == current_user.username,
            ).all()
            logger.info(
                f"Sales form - All drafts for user {current_user.username}: {[(d.id, d.transaction_date, d.status) for d in all_user_drafts]}"
            )

            report_draft: ReportDraft | None = existing_draft

            if existing_draft:
                # Update existing draft - preserve all existing data, only update sales fields; track last editor
                # Keep a tracked reference with a narrow type for downstream
                # typing.
                report_draft = existing_draft
                assert report_draft is not None
                report_draft.uploaded_by = current_user.username
                logger.info(f"Updating existing draft {report_draft.id} for sales data")
                # Parse nested sales data (same structure as main form)
                shop_sales_data = parse_nested_keys(request.form, "sales[shop_sales]")
                delivery_sales_data = parse_nested_keys(
                    request.form, "sales[delivery_sales]"
                )

                # Extract cash sales from shop sales. Resolved the same way as
                # the cash detail row written below, so the column and the row
                # cannot disagree — the deposit step totals the rows while cash
                # count reads this column.
                cash_sales = resolve_posted_sale_amount(
                    "cash_sales", shop_sales_data, delivery_sales_data
                )

                # Update draft fields from parsed data
                # cash_sales stays a column; per-method amounts are written as
                # report_sale_detail rows below, so a method added to the
                # sales_method catalog needs no change here.
                report_draft.cash_sales = cash_sales

                # Calculate aggregates from form data (will be recalculated
                # from report_sale_detail after records are created)
                total_shop_sales = sum(
                    safe_float(v) for k, v in shop_sales_data.items()
                )
                total_delivery_sales = sum(
                    safe_float(v) for k, v in delivery_sales_data.items()
                )
                total_sales = total_shop_sales + total_delivery_sales

                report_draft.shop_sales = total_shop_sales
                report_draft.delivery_sales = total_delivery_sales
                report_draft.total_sales = total_sales

                # Recalculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
                # Get cash sales from ReportSaleDetail with fallback to
                # report_draft.cash_sales
                cash_sales = get_cash_sales_from_detail(
                    report_draft.id, fallback_value=report_draft.cash_sales or 0.0
                )
                report_draft.closing_balance = (
                    report_draft.opening_balance
                    + (report_draft.cash_addition or 0)
                    + cash_sales
                    - (report_draft.expenses or 0)
                    - (report_draft.bank_deposit or 0)
                )

                logger.info(f"Closing balance calculation for draft {report_draft.id}:")
                logger.info(f"  Opening Balance: {report_draft.opening_balance}")
                logger.info(f"  Cash Addition: {report_draft.cash_addition}")
                logger.info(
                    f"  Adjusted Opening: {report_draft.adjusted_opening_balance}"
                )
                logger.info(f"  Total Sales: {report_draft.total_sales}")
                logger.info(f"  Expenses: {report_draft.expenses}")
                logger.info(f"  Bank Deposit: {report_draft.bank_deposit}")
                logger.info(f"  Closing Balance: {report_draft.closing_balance}")

                # If edit mode is enabled, also update the Report table
                if is_edit_mode:
                    existing_report = Report.query.filter(
                        Report.id == report_draft.id
                    ).first()
                    if existing_report:
                        logger.info(
                            f"Edit mode - updating Report {existing_report.id} with sales data"
                        )
                        # Per-method amounts are NOT copied: the draft and the
                        # report share an id (ending.py creates the revert draft
                        # with id=full_report.id), so both already resolve the
                        # same report_sale_detail rows. Only cash and the
                        # aggregate caches are stored per-row.
                        existing_report.cash_sales = report_draft.cash_sales
                        existing_report.shop_sales = report_draft.shop_sales
                        existing_report.delivery_sales = report_draft.delivery_sales
                        existing_report.total_sales = report_draft.total_sales
                        existing_report.date = datetime.now(
                            tz
                        )  # Update date to current timestamp
                        # Recalculate closing balance
                        cash_sales_for_report = get_cash_sales_from_detail(
                            existing_report.id,
                            fallback_value=existing_report.cash_sales or 0.0,
                        )
                        existing_report.closing_balance = (
                            existing_report.opening_balance
                            + (existing_report.cash_addition or 0)
                            + cash_sales_for_report
                            - (existing_report.expenses or 0)
                            - (existing_report.bank_deposit or 0)
                        )

                # Save the draft
                db.session.commit()
                logger.info(f"Updated existing draft {report_draft.id} with sales data")

                # Update ReportSaleDetail for drafts so amounts are preserved.
                # The ReportV2 row that used to be manufactured here existed
                # only to satisfy report_sale_detail's FK, dropped in r2a02.

                # Get all sale_info for this entity (only enabled ones, no duplicates, proper order)
                sale_info = get_unique_sale_info_for_entity(entity_id)
                default_saletypes = {
                    "cash": "cash_sales",
                    "visa": "visa_sales",
                    "master": "master_sales",
                    "alipay": "alipay_sales",
                    "wechat": "wechat_sales",
                    "unionpay": "unionpay_sales",
                    "amex": "amex_sales",
                    "octopus": "octopus_sales",
                    "foodpanda": "foodpanda_sales",
                    "keeta": "keeta_sales",
                    "openrice": "openrice_sales",
                }

                # Update or create ReportSaleDetail for each sale type
                for sale in sale_info:
                    field = sale.value_name
                    if not field or field == "deliveroo_sales":
                        continue

                    amount = resolve_posted_sale_amount(
                        field, shop_sales_data, delivery_sales_data
                    )

                    # Check if ReportSaleDetail exists
                    report_sale_detail = ReportSaleDetail.query.filter_by(
                        sale_id=sale.sale_id, report_id=report_draft.id
                    ).first()

                    if report_sale_detail:
                        # Update existing record
                        report_sale_detail.amount = amount
                        report_sale_detail.create_at = datetime.now()
                        logger.info(
                            f"Updated ReportSaleDetail for draft: sale_id={sale.sale_id}, field={field}, amount={amount}"
                        )
                    else:
                        # Create new record
                        report_sale_detail = ReportSaleDetail(
                            sale_id=sale.sale_id,
                            report_id=report_draft.id,
                            # Catalog link, so the row stays self-describing
                            # even if this sale_info row is later removed.
                            sale_info_id=sale.sale_info_id,
                            type=sale.type,
                            amount=amount,
                            create_at=datetime.now(),
                        )
                        db.session.add(report_sale_detail)
                        logger.info(
                            f"Created ReportSaleDetail for draft: sale_id={sale.sale_id}, field={field}, amount={amount}"
                        )

                db.session.commit()

            else:
                # No existing draft found - this should not happen if user came
                # from opening form. Deliberately status-AGNOSTIC: the recovery
                # path forces status="draft" below, so it must be able to find a
                # row the "draft" filter would have excluded.
                any_draft = ReportDraft.query.filter(
                    ReportDraft.company == entity_id,
                    ReportDraft.transaction_date == transaction_date,
                ).first()

                if any_draft:
                    logger.info(
                        f"Found existing draft {any_draft.id} for date {transaction_date}, updating it"
                    )
                    # Update the existing draft
                    report_draft = any_draft
                    assert report_draft is not None
                    report_draft.status = "draft"  # Ensure it's marked as draft

                    # Validate the draft record integrity
                    if not report_draft.id:
                        logger.error(
                            f"Draft record {report_draft.id} has no valid ID, creating new draft"
                        )
                        flash(
                            "Something's off with this draft - could you reopen it from the opening step?", "danger",
                        )
                        return redirect(url_for("report.report_opening"))

                    # Process sales data for the found draft
                    # Parse nested sales data (same structure as main form)
                    shop_sales_data = parse_nested_keys(
                        request.form, "sales[shop_sales]"
                    )
                    delivery_sales_data = parse_nested_keys(
                        request.form, "sales[delivery_sales]"
                    )

                    # Extract cash sales from shop sales. Same resolution as the
                    # cash detail row written below, so the two agree.
                    cash_sales = resolve_posted_sale_amount(
                        "cash_sales", shop_sales_data, delivery_sales_data
                    )

                    # Update draft fields from parsed data
                    # cash_sales stays a column; per-method amounts become
                    # report_sale_detail rows below.
                    report_draft.cash_sales = cash_sales

                    # Calculate aggregates from form data (will be recalculated
                    # from report_sale_detail after records are created)
                    total_shop_sales = sum(
                        safe_float(v) for k, v in shop_sales_data.items()
                    )
                    total_delivery_sales = sum(
                        safe_float(v) for k, v in delivery_sales_data.items()
                    )
                    total_sales = total_shop_sales + total_delivery_sales

                    report_draft.shop_sales = total_shop_sales
                    report_draft.delivery_sales = total_delivery_sales
                    report_draft.total_sales = total_sales

                    # Recalculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
                    # Get cash sales from ReportSaleDetail with fallback to
                    # report_draft.cash_sales
                    cash_sales = get_cash_sales_from_detail(
                        report_draft.id, fallback_value=report_draft.cash_sales or 0.0
                    )
                    report_draft.closing_balance = (
                        report_draft.opening_balance
                        + (report_draft.cash_addition or 0)
                        + cash_sales
                        - (report_draft.expenses or 0)
                        - (report_draft.bank_deposit or 0)
                    )

                    logger.info(
                        f"Updated existing draft {report_draft.id} with sales data"
                    )

                    # Update ReportSaleDetail for drafts so amounts are
                    # preserved. See the note above: the ReportV2 row formerly
                    # created here was FK scaffolding only (r2a02).

                    # Get all sale_info for this entity (only enabled ones, no duplicates, proper order)
                    sale_info = get_unique_sale_info_for_entity(entity_id)
                    default_saletypes = {
                        "cash": "cash_sales",
                        "visa": "visa_sales",
                        "master": "master_sales",
                        "alipay": "alipay_sales",
                        "wechat": "wechat_sales",
                        "unionpay": "unionpay_sales",
                        "amex": "amex_sales",
                        "octopus": "octopus_sales",
                        "foodpanda": "foodpanda_sales",
                        "keeta": "keeta_sales",
                        "openrice": "openrice_sales",
                    }

                    # Update or create ReportSaleDetail for each sale type
                    for sale in sale_info:
                        field = sale.value_name
                        if not field or field == "deliveroo_sales":
                            continue

                        amount = resolve_posted_sale_amount(
                            field, shop_sales_data, delivery_sales_data
                        )

                        # Check if ReportSaleDetail exists
                        report_sale_detail = ReportSaleDetail.query.filter_by(
                            sale_id=sale.sale_id, report_id=report_draft.id
                        ).first()

                        if report_sale_detail:
                            # Update existing record
                            report_sale_detail.amount = amount
                            report_sale_detail.create_at = datetime.now()
                            logger.info(
                                f"Updated ReportSaleDetail for draft: sale_id={sale.sale_id}, field={field}, amount={amount}"
                            )
                        else:
                            # Create new record
                            report_sale_detail = ReportSaleDetail(
                                sale_id=sale.sale_id,
                                report_id=report_draft.id,
                                # Catalog link, so the row stays self-describing
                                # even if this sale_info row is later removed.
                                sale_info_id=sale.sale_info_id,
                                type=sale.type,
                                amount=amount,
                                create_at=datetime.now(),
                            )
                            db.session.add(report_sale_detail)
                            logger.info(
                                f"Created ReportSaleDetail for draft: sale_id={sale.sale_id}, field={field}, amount={amount}"
                            )

                    db.session.commit()
                else:
                    logger.error(
                        f"Sales form - No draft found for user {current_user.username} on date {transaction_date}"
                    )
                    logger.error(
                        "Sales form - This should not happen if user came from opening form"
                    )
                    flash(
                        "I don't see a draft yet - let's start with the opening entry.", "danger",
                    )
                    return redirect(url_for("report.report_opening"))

            assert report_draft is not None

            # The non-cash total computed here fed report_v2.nocashsale_total
            # and nothing else; both went with the ReportV2 write (r2a02).

            # Update progress tracking
            try:
                update_draft_progress(report_draft, action_type, "sales", "expenses")

                # Commit progress updates
                db.session.commit()
                logger.info(
                    f"Successfully committed sales data and progress for draft {report_draft.id}"
                )
            except Exception as progress_error:
                logger.error(f"Error updating draft progress: {progress_error}")
                db.session.rollback()
                # Don't fail the entire operation for progress tracking issues
                flash(
                    "Your sales data is saved! I lost track of where you were in the report, though - please pick the next step yourself.",
                    "warning",
                )

            # Debug: Check what was actually saved to database
            db.session.refresh(report_draft)
            print(
                f"DEBUG SALES: After commit - current_section: {report_draft.current_section}"
            )
            print(
                f"DEBUG SALES: After commit - completed_sections: {report_draft.completed_sections}"
            )
            print(
                f"DEBUG SALES: After commit - completed_sections type: {type(report_draft.completed_sections)}"
            )
            print(
                f"DEBUG SALES: After commit - completed_sections length: {len(report_draft.completed_sections) if report_draft.completed_sections else 0}"
            )

            # Log the sales entry to draft history
            log_history_draft(
                report_draft_id=report_draft.id,
                company=entity_id,
                user_id=current_user.id,
                action="created" if not existing_draft else "updated",
                field_changed="sales_entry",
                old_value="None" if not existing_draft else "previous_sales_state",
                new_value=f"Sales: Shop={total_shop_sales}, Delivery={total_delivery_sales}, Total={total_sales}, Closing Balance={report_draft.closing_balance}",
            )

            # report_v2 used to be created/updated here, keyed on the draft id,
            # purely so report_sale_detail's FK resolved. r2a02 dropped that FK
            # and nothing ever read the columns back, so the whole block went.
            db.session.commit()

            # Insert to report_sale_detail (only enabled sale types, no duplicates, proper order)
            sale_info = get_unique_sale_info_for_entity(entity_id)
            # Map sale_name to report field
            default_saletypes = {
                "cash": "cash_sales",
                "visa": "visa_sales",
                "master": "master_sales",
                "alipay": "alipay_sales",
                "wechat": "wechat_sales",
                "unionpay": "unionpay_sales",
                "amex": "amex_sales",
                "octopus": "octopus_sales",
                "foodpanda": "foodpanda_sales",
                "keeta": "keeta_sales",
                "openrice": "openrice_sales",
            }

            # Insert or update ReportSaleDetail for each sale type for this
            # report
            for sale in sale_info:
                # Use value_name directly as the field name
                field = sale.value_name

                if field:
                    # Skip deliveroo_sales
                    if field == "deliveroo_sales":
                        continue
                    logger.info(f"Shop sales data: {shop_sales_data}")
                    logger.info(f"Delivery sales data: {delivery_sales_data}")
                    if field not in default_saletypes.values():
                        logger.warning(f"Unknown sale field: {field}, adding to query")
                    amount = resolve_posted_sale_amount(
                        field, shop_sales_data, delivery_sales_data
                    )

                    # Check if a detail already exists for this sale_id and
                    # report_id
                    report_sale_detail = ReportSaleDetail.query.filter_by(
                        sale_id=sale.sale_id, report_id=report_draft.id
                    ).first()
                    if report_sale_detail:
                        # Update the amount and update timestamp
                        report_sale_detail.amount = amount
                        report_sale_detail.create_at = datetime.now()
                    else:
                        # Insert new detail
                        report_sale_detail = ReportSaleDetail(
                            sale_id=sale.sale_id,
                            report_id=report_draft.id,
                            # Catalog link, so the row stays self-describing
                            # even if this sale_info row is later removed.
                            sale_info_id=sale.sale_info_id,
                            type=sale.type,
                            amount=amount,
                            create_at=datetime.now(),
                        )
                        db.session.add(report_sale_detail)
                        logger.info(
                            f"New sale detail record created: sale_id={sale.sale_id}, report_id={report_draft.id}, type={sale.type}, amount={amount}"
                        )

            logger.info(f"Committing {len(sale_info)} sale detail records to database")
            db.session.commit()

            # Recalculate sales from report_sale_detail now that records are
            # created/updated
            update_report_draft_sales_from_detail(report_draft)
            db.session.commit()

            # Update totals for logging
            total_shop_sales = report_draft.shop_sales or 0.0
            total_delivery_sales = report_draft.delivery_sales or 0.0
            total_sales = report_draft.total_sales or 0.0

            # Check action type and redirect accordingly
            logger.info(
                f"Sales form - Processing redirect for action_type: {action_type}"
            )
            if action_type == "save_next":
                logger.info(
                    f"Sales form - Redirecting to expenses form with transaction_date: {transaction_date}"
                )
                return redirect(
                    url_for(
                        "report.report_expense",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            elif action_type == "save_exit":
                logger.info("Sales form - Redirecting to dashboard")
                return redirect(url_for("entity.report_dashboard", id=entity_id))
            else:
                # Default to save_next
                logger.info(
                    f"Sales form - Default redirect to expenses form with transaction_date: {transaction_date}"
                )
                return redirect(
                    url_for(
                        "report.report_expense",
                        entity_id=entity_id,
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating sales draft data: {str(e)}")

            # Try to preserve the draft record even after error
            try:
                # Check if the draft still exists after rollback
                draft_obj = locals().get("report_draft")
                if isinstance(draft_obj, ReportDraft):
                    draft_id = draft_obj.id
                    draft_check = ReportDraft.query.filter_by(id=draft_id).first()
                    if draft_id is not None and not draft_check:
                        logger.warning(
                            f"Draft record {draft_id} may have been lost due to rollback"
                        )
            except Exception as check_error:
                logger.error(
                    f"Error checking draft status after rollback: {check_error}"
                )

            flash("Oops, that didn't go as planned. Please try refreshing or saving your sales data again.", "danger")
            return redirect(url_for("report.report_sale"))

    # For GET request, check for existing draft and load data
    try:
        # Get transaction date from URL parameter or form data if provided,
        # otherwise use today
        selected_date = request.args.get("transaction_date") or request.form.get(
            "transaction_date"
        )
        if selected_date:
            try:
                transaction_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
                logger.info(
                    f"Sales form - Using selected date from URL/form: {transaction_date}"
                )
            except ValueError:
                logger.warning(
                    f"Sales form - Invalid date format: {selected_date}, using today"
                )
                transaction_date = datetime.now().date()
        else:
            transaction_date = datetime.now().date()
            logger.info(
                f"Sales form - No date provided, using today: {transaction_date}"
            )

        # If edit mode is enabled and no id provided, try to load any existing
        # report for this date
        if is_edit_mode and not id:
            existing_report = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
            ).first()
            if existing_report:
                # Redirect to sales page with report id
                return redirect(
                    url_for(
                        "report.report_sale",
                        id=existing_report.id,
                        entity_id=entity_id,
                        edit="true",
                    )
                )

        # Check for existing draft: by id when in URL, else by (entity,
        # transaction_date)
        if id:
            # GET-path read, migrated to `report` (mirror keeps it current).
            # Read-only: nothing writes through existing_draft on this path.
            existing_draft = Report.query.filter(
                Report.id == id,
                Report.company == entity_id,
                Report.status == "draft",
            ).first()
        else:
            existing_draft = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
                Report.status == "draft",
            ).first()

        if existing_draft:
            # Load draft data
            logger.info(f"Loading existing draft {existing_draft.id} for sales form")
            is_draft = True
            draft_id = existing_draft.id
            next_transaction_date = existing_draft.transaction_date
            datenow = datetime.now()

            default_saletypes = {
                "cash": "cash_sales",
                "visa": "visa_sales",
                "master": "master_sales",
                "alipay": "alipay_sales",
                "wechat": "wechat_sales",
                "unionpay": "unionpay_sales",
                "amex": "amex_sales",
                "octopus": "octopus_sales",
                "foodpanda": "foodpanda_sales",
                "keeta": "keeta_sales",
                "openrice": "openrice_sales",
            }

            # Create draft report data for template
            # Per-method amounts come from report_sale_detail, keyed by the
            # legacy value_name so the template contract is unchanged. Adding a
            # method to the catalog surfaces it here automatically.
            draft_report = {"cash_sales": existing_draft.cash_sales or 0.0}
            for _sale in get_unique_sale_info_for_entity(entity_id):
                if not _sale.value_name or _sale.value_name == "cash_sales":
                    continue
                _detail = ReportSaleDetail.query.filter_by(
                    report_id=existing_draft.id, sale_id=_sale.sale_id
                ).first()
                draft_report[_sale.value_name] = (
                    _detail.amount if _detail and _detail.amount else 0.0
                )

            report_sale_detail = (
                db.session.query(
                    ReportSaleDetail.sale_id,
                    ReportSaleDetail.amount,
                    ReportSaleDetail.type,
                    EntitySaleSetting.sale_name,
                    EntitySaleSetting.value_name,
                )
                .join(
                    EntitySaleSetting, EntitySaleSetting.sale_id == ReportSaleDetail.sale_id, isouter=True
                )
                .filter(ReportSaleDetail.report_id == existing_draft.id)
                .order_by(ReportSaleDetail.create_at.desc())
                .all()
            )

            for sale in report_sale_detail:
                field = sale.value_name
                # Skip deliveroo_sales
                if field == "deliveroo_sales":
                    continue
                if field not in default_saletypes.values():
                    logger.warning(
                        f"Unknown sale field: {field}, adding to draft_report"
                    )
                    amount = sale.amount
                    draft_report[field] = amount or 0.0
        else:
            # No draft found, use default values
            logger.info("No existing draft found for sales form")
            is_draft = False
            draft_id = None
            next_transaction_date = datetime.now().date()
            datenow = datetime.now()
            draft_report = {
                "cash_sales": 0.0,
                "visa_sales": 0.0,
                "master_sales": 0.0,
                "unionpay_sales": 0.0,
                "alipay_sales": 0.0,
                "wechat_sales": 0.0,
                "amex_sales": 0.0,
                "octopus_sales": 0.0,
                "deliveroo_sales": 0.0,
                "foodpanda_sales": 0.0,
                "keeta_sales": 0.0,
                "openrice_sales": 0.0,
            }

            # Keep numeric zero defaults for server-side calculations; the
            # template renders zero-valued sale inputs as empty fields.
            # This prevents loading old data from other reports/entities.

        # Get organization info for template - validate entity_id first
        if not entity_id:
            logger.error("Entity ID is None or empty when loading sales form")
            flash("Hmm, that entity ID doesn't look quite right. Could you double-check it?", "danger")
            return redirect(url_for("entity.entity_list"))

        org = Entity.query.get(entity_id)
        if not org:
            logger.error(f"Entity with ID {entity_id} not found in database")
            flash("Hmm, that organization doesn't seem to be in our system.", "danger")
            return redirect(url_for("entity.entity_list"))

        entity_acronym, display_date = entity_badge_data(org)
        sale_info_query = get_unique_sale_info_for_entity(org.id)

        # Attach amounts from ReportSaleDetail if draft exists
        sale_info = []
        if existing_draft:
            # Attach amounts from ReportSaleDetail for this draft
            for sale_obj in sale_info_query:
                sale_detail = ReportSaleDetail.query.filter_by(
                    report_id=existing_draft.id,
                    sale_id=sale_obj.sale_id
                ).first()
                sale_obj.amount = sale_detail.amount if sale_detail else None
                sale_info.append(sale_obj)
        else:
            # No draft, just set amount to None for all
            for sale_obj in sale_info_query:
                sale_obj.amount = None
                sale_info.append(sale_obj)

        # Don't reset current_section when viewing - it should only update when progressing forward
        # The stepper should always show the latest step reached, not the
        # current page

        # For new reports (no id parameter), always consider them as
        # latest/editable
        is_latest_report = True

        return render_template(
            "report/sales.html",
            sales_amounts=draft_report,
            org=org,
            is_draft=is_draft,
            draft_id=draft_id,
            next_transaction_date=transaction_date,  # Use the actual transaction date
            datenow=datenow,
            current_draft=existing_draft,
            header_publishing_status=header_publishing_status_for(report_id=(existing_draft.id if existing_draft else None)),
            report=draft_report,
            sale_info=sale_info,
            # Add stepper data for dynamic progress display
            current_section="sales",  # Always set to current page
            completed_sections=(
                existing_draft.completed_sections if existing_draft else ["opening"]
            ),
            is_latest_report=is_latest_report,
            transaction_date=transaction_date,
            # Pass transaction_date to template for date display
            selected_date=transaction_date,  # Also pass as selected_date for consistency
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
        )

    except Exception as e:
        logger.error(f"Error loading sales form: {str(e)}")
        flash("Something got tangled up while loading the sales form. Please try again!", "danger")
        return redirect(url_for("report.report_opening"))


# Sales step: report_sale transferred from app.py (single function, no new
# functions).
