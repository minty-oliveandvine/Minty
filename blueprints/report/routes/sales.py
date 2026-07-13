# Report sales routes; delegates to app implementation.


from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (
    check_user_has_entities, get_cash_sales_from_detail,
    header_publishing_status_for, parse_nested_keys,
    resolve_report_entity_id, safe_float, update_draft_progress,
    update_report_draft_sales_from_detail)
from models.db import (Entity, Report, ReportDraft, ReportSaleDetail, ReportV2,
                       SaleInfo, db, tz)
from services.authz import permission_denied
from services.permission_policy import Permission, can_edit_report, has_permission


def get_unique_sale_info_for_entity(entity_id):
    """
    Get unique payment methods for an entity, preventing duplicates.
    Returns: list of SaleInfo objects ordered by display_order (matches Settings page).
    """
    payment_methods_subquery = (
        db.session.query(
            SaleInfo.value_name,
            db.func.max(SaleInfo.sale_id).label('max_sale_id')
        )
        .filter(
            SaleInfo.entity_id == entity_id,
            SaleInfo.value_name != "deliveroo_sales",
            SaleInfo.enabled == True
        )
        .group_by(SaleInfo.value_name)
        .subquery()
    )
    
    payment_methods = (
        db.session.query(SaleInfo)
        .join(
            payment_methods_subquery,
            SaleInfo.sale_id == payment_methods_subquery.c.max_sale_id
        )
        .order_by(SaleInfo.display_order.asc(), SaleInfo.create_date.asc())
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
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access:
            report_for_access = ReportDraft.query.filter_by(id=id).first()
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

    def get_entity_badge_data(entity):
        acronym = ""
        if entity and entity.name:
            words = entity.name.split()
            acronym = "".join([word[0].upper() for word in words if word])

        badge_date = None
        if entity and entity.created_at:
            if isinstance(entity.created_at, datetime):
                badge_date = entity.created_at.date()
            else:
                badge_date = entity.created_at
        return acronym, badge_date

    entity_acronym = ""
    display_date = None

    if id:
        report = (
            Report.query.join(ReportDraft, ReportDraft.id == Report.id, full=True)
            .filter(Report.id == id, ReportDraft.id == id)
            .with_entities(
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
            )
            .first()
        )
        entity = Entity.query.get_or_404(entity_id)
        entity_acronym, display_date = get_entity_badge_data(entity)

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

    if id:
        report = (
            Report.query.join(ReportDraft, ReportDraft.id == Report.id, full=True)
            .filter(Report.id == id, ReportDraft.id == id)
            .with_entities(
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
            )
            .first()
        )
        entity = Entity.query.get_or_404(entity_id)
        entity_acronym, display_date = get_entity_badge_data(entity)

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
            org=entity,
            current_draft=report,
            header_publishing_status=header_publishing_status_for(report_id=(report.id if report else None)),
            report=report,
            current_section="sales",
            completed_sections=report.completed_sections if report else ["opening"],
            is_draft=True,
            draft_id=report.id if report else None,
            current_user=current_user,
            sale_info=sale_info,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
        )
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

            # Also check what drafts exist for this user
            all_user_drafts = ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.uploaded_by == current_user.username,
            ).all()
            logger.info(
                f"Sales form - All drafts for user {current_user.username}: {[(d.id, d.transaction_date, d.status) for d in all_user_drafts]}"
            )

            nocashsale_fields = [
                "visa_sales",
                "master_sales",
                "alipay_sales",
                "wechat_sales",
                "unionpay_sales",
                "amex_sales",
                "octopus_sales",
            ]

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

                # Extract cash sales from shop sales
                cash_sales = safe_float(shop_sales_data.get("cash", 0))

                # Update draft fields from parsed data
                report_draft.cash_sales = cash_sales
                report_draft.visa_sales = safe_float(shop_sales_data.get("visa", 0))
                report_draft.master_sales = safe_float(shop_sales_data.get("master", 0))
                report_draft.unionpay_sales = safe_float(
                    shop_sales_data.get("unionpay", 0)
                )
                report_draft.alipay_sales = safe_float(shop_sales_data.get("alipay", 0))
                report_draft.wechat_sales = safe_float(shop_sales_data.get("wechat", 0))
                report_draft.amex_sales = safe_float(shop_sales_data.get("amex", 0))
                report_draft.octopus_sales = safe_float(
                    shop_sales_data.get("octopus", 0)
                )

                report_draft.deliveroo_sales = 0.0
                report_draft.foodpanda_sales = safe_float(
                    delivery_sales_data.get("foodpanda", 0)
                )
                report_draft.keeta_sales = safe_float(
                    delivery_sales_data.get("keeta", 0)
                )
                report_draft.openrice_sales = safe_float(
                    delivery_sales_data.get("openrice", 0)
                )

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
                        existing_report.cash_sales = report_draft.cash_sales
                        existing_report.visa_sales = report_draft.visa_sales
                        existing_report.master_sales = report_draft.master_sales
                        existing_report.unionpay_sales = report_draft.unionpay_sales
                        existing_report.alipay_sales = report_draft.alipay_sales
                        existing_report.wechat_sales = report_draft.wechat_sales
                        existing_report.amex_sales = report_draft.amex_sales
                        existing_report.octopus_sales = report_draft.octopus_sales
                        existing_report.foodpanda_sales = report_draft.foodpanda_sales
                        existing_report.keeta_sales = report_draft.keeta_sales
                        existing_report.openrice_sales = report_draft.openrice_sales
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

                # Update ReportSaleDetail for drafts so amounts are preserved
                # Ensure ReportV2 exists for this draft
                report_v2 = ReportV2.query.filter_by(report_id=report_draft.id).first()
                if not report_v2:
                    # Create ReportV2 if it doesn't exist
                    report_v2 = ReportV2(
                        report_id=report_draft.id,
                        entity_id=entity_id,
                        report_date=report_draft.transaction_date,
                        status="draft",
                        starting_balance=report_draft.opening_balance or 0,
                        opening_balance=report_draft.opening_balance or 0,
                        adjusted_opening_balance=report_draft.adjusted_opening_balance
                        or report_draft.opening_balance
                        or 0,
                        add_cash_amount=report_draft.cash_addition or 0,
                        cash_from_type="shop",
                        cashsale_total=report_draft.cash_sales or 0,
                        expense_total=report_draft.expenses or 0,
                        cash_deposit=report_draft.bank_deposit or 0,
                    )
                    db.session.add(report_v2)
                    db.session.commit()

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

                    amount = 0
                    if field not in default_saletypes.values():
                        # For dynamic fields, extract the base name (e.g.,
                        # "kakaopay" from "kakaopay_sales")
                        field_base = field.replace("_sales", "")
                        amount = (
                            shop_sales_data.get(field_base)
                            or delivery_sales_data.get(field_base)
                            or 0
                        )
                        logger.info(
                            f"Draft update - Dynamic field: {field} (base: {field_base}), amount: {amount}"
                        )
                    else:
                        # For default fields, get amount from
                        # shop_sales_data/delivery_sales_data first, then
                        # fallback to report_draft
                        field_base = field.replace("_sales", "")
                        amount = (
                            shop_sales_data.get(field_base)
                            or delivery_sales_data.get(field_base)
                            or getattr(report_draft, field, 0)
                            or 0
                        )

                    # Check if ReportSaleDetail exists
                    report_sale_detail = ReportSaleDetail.query.filter_by(
                        sale_id=sale.sale_id, report_id=report_v2.report_id
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
                            report_id=report_v2.report_id,
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
                # No existing draft found - this should not happen if user came from opening form
                # Try to find any draft for this user and date, regardless of
                # status
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

                    # Extract cash sales from shop sales
                    cash_sales = safe_float(shop_sales_data.get("cash", 0))

                    # Update draft fields from parsed data
                    report_draft.cash_sales = cash_sales
                    report_draft.visa_sales = safe_float(shop_sales_data.get("visa", 0))
                    report_draft.master_sales = safe_float(
                        shop_sales_data.get("master", 0)
                    )
                    report_draft.unionpay_sales = safe_float(
                        shop_sales_data.get("unionpay", 0)
                    )
                    report_draft.alipay_sales = safe_float(
                        shop_sales_data.get("alipay", 0)
                    )
                    report_draft.wechat_sales = safe_float(
                        shop_sales_data.get("wechat", 0)
                    )
                    report_draft.amex_sales = safe_float(shop_sales_data.get("amex", 0))
                    report_draft.octopus_sales = safe_float(
                        shop_sales_data.get("octopus", 0)
                    )

                    report_draft.deliveroo_sales = 0.0
                    report_draft.foodpanda_sales = safe_float(
                        delivery_sales_data.get("foodpanda", 0)
                    )
                    report_draft.keeta_sales = safe_float(
                        delivery_sales_data.get("keeta", 0)
                    )
                    report_draft.openrice_sales = safe_float(
                        delivery_sales_data.get("openrice", 0)
                    )

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

                    # Update ReportSaleDetail for drafts so amounts are preserved
                    # Ensure ReportV2 exists for this draft
                    report_v2 = ReportV2.query.filter_by(
                        report_id=report_draft.id
                    ).first()
                    if not report_v2:
                        # Create ReportV2 if it doesn't exist
                        report_v2 = ReportV2(
                            report_id=report_draft.id,
                            entity_id=entity_id,
                            report_date=report_draft.transaction_date,
                            status="draft",
                            starting_balance=report_draft.opening_balance or 0,
                            opening_balance=report_draft.opening_balance or 0,
                            adjusted_opening_balance=report_draft.adjusted_opening_balance
                            or report_draft.opening_balance
                            or 0,
                            add_cash_amount=report_draft.cash_addition or 0,
                            cash_from_type="shop",
                            cashsale_total=report_draft.cash_sales or 0,
                            expense_total=report_draft.expenses or 0,
                            cash_deposit=report_draft.bank_deposit or 0,
                        )
                        db.session.add(report_v2)
                        db.session.commit()

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

                        amount = 0
                        if field not in default_saletypes.values():
                            # For dynamic fields, extract the base name (e.g.,
                            # "kakaopay" from "kakaopay_sales")
                            field_base = field.replace("_sales", "")
                            amount = (
                                shop_sales_data.get(field_base)
                                or delivery_sales_data.get(field_base)
                                or 0
                            )
                            logger.info(
                                f"Draft update - Dynamic field: {field} (base: {field_base}), amount: {amount}"
                            )
                        else:
                            # For default fields, get amount from
                            # shop_sales_data/delivery_sales_data first, then
                            # fallback to report_draft
                            field_base = field.replace("_sales", "")
                            amount = (
                                shop_sales_data.get(field_base)
                                or delivery_sales_data.get(field_base)
                                or getattr(report_draft, field, 0)
                                or 0
                            )

                        # Check if ReportSaleDetail exists
                        report_sale_detail = ReportSaleDetail.query.filter_by(
                            sale_id=sale.sale_id, report_id=report_v2.report_id
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
                                report_id=report_v2.report_id,
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

            nocashsale_total = 0
            for field in nocashsale_fields:
                value = getattr(report_draft, field, 0)
                nocashsale_total += value if value else 0

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

            # Update report_v2
            report_v2 = ReportV2.query.filter_by(
                entity_id=entity_id, report_date=transaction_date
            ).first()

            # Check if the report is posted or draft status
            report_status = getattr(report_draft, "status", "draft")

            status = "draft" if report_status == "draft" else "posted"
            if report_v2:
                report_v2.cashsale_total = report_draft.cash_sales
                report_v2.nocashsale_total = nocashsale_total
                report_v2.expense_total = report_draft.expenses
            else:
                report_v2 = ReportV2(
                    report_id=report_draft.id,
                    entity_id=entity_id,
                    report_date=transaction_date,
                    status=status,
                    starting_balance=report_draft.opening_balance,
                    opening_balance=report_draft.opening_balance,
                    adjusted_opening_balance=report_draft.opening_balance,
                    add_cash_amount=report_draft.cash_addition,
                    cash_from_type="shop",
                    xero_organiztion_id=current_user.xero_entity_id,
                    cashsale_total=report_draft.cash_sales,
                    nocashsale_total=nocashsale_total,
                    cash_deposit=report_draft.bank_deposit,
                    expense_total=report_draft.expenses,
                )
                db.session.add(report_v2)
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
                    amount = 0
                    logger.info(f"Shop sales data: {shop_sales_data}")
                    logger.info(f"Delivery sales data: {delivery_sales_data}")
                    if field not in default_saletypes.values():
                        logger.warning(f"Unknown sale field: {field}, adding to query")
                        # For dynamic fields, extract the base name (e.g.,
                        # "kakaopay" from "kakaopay_sales")
                        field_base = field.replace("_sales", "")
                        amount = (
                            shop_sales_data.get(field_base)
                            or delivery_sales_data.get(field_base)
                            or 0
                        )
                        logger.info(
                            f"Sale name is: {sale.sale_name} sale value is: {field_base}, amount is {amount}"
                        )
                    else:
                        # For default fields, get amount from report_draft
                        amount = getattr(report_draft, field, 0) or 0

                    # Check if a detail already exists for this sale_id and
                    # report_id
                    report_sale_detail = ReportSaleDetail.query.filter_by(
                        sale_id=sale.sale_id, report_id=report_v2.report_id
                    ).first()
                    if report_sale_detail:
                        # Update the amount and update timestamp
                        report_sale_detail.amount = amount
                        report_sale_detail.create_at = datetime.now()
                    else:
                        # Insert new detail
                        report_sale_detail = ReportSaleDetail(
                            sale_id=sale.sale_id,
                            report_id=report_v2.report_id,
                            type=sale.type,
                            amount=amount,
                            create_at=datetime.now(),
                        )
                        db.session.add(report_sale_detail)
                        logger.info(
                            f"New sale detail record created: sale_id={sale.sale_id}, report_id={report_v2.report_id}, type={sale.type}, amount={amount}"
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
            existing_draft = ReportDraft.query.filter(
                ReportDraft.id == id,
                ReportDraft.company == entity_id,
                ReportDraft.status == "draft",
            ).first()
        else:
            existing_draft = ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.transaction_date == transaction_date,
                ReportDraft.status == "draft",
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
            draft_report = {
                "cash_sales": existing_draft.cash_sales or 0.0,
                "visa_sales": existing_draft.visa_sales or 0.0,
                "master_sales": existing_draft.master_sales or 0.0,
                "unionpay_sales": existing_draft.unionpay_sales or 0.0,
                "alipay_sales": existing_draft.alipay_sales or 0.0,
                "wechat_sales": existing_draft.wechat_sales or 0.0,
                "amex_sales": existing_draft.amex_sales or 0.0,
                "octopus_sales": existing_draft.octopus_sales or 0.0,
                "deliveroo_sales": 0.0,
                "foodpanda_sales": existing_draft.foodpanda_sales or 0.0,
                "keeta_sales": existing_draft.keeta_sales or 0.0,
                "openrice_sales": existing_draft.openrice_sales or 0.0,
            }

            report_sale_detail = (
                db.session.query(
                    ReportSaleDetail.sale_id,
                    ReportSaleDetail.amount,
                    ReportSaleDetail.type,
                    SaleInfo.sale_name,
                    SaleInfo.value_name,
                )
                .join(
                    SaleInfo, SaleInfo.sale_id == ReportSaleDetail.sale_id, isouter=True
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

        entity_acronym, display_date = get_entity_badge_data(org)
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
