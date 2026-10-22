# Report sales routes; delegates to app implementation.


from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from services.app_runtime.log import logger

from blueprints.report import report_bp
from blueprints.report.services.sales import sales_methods as get_unique_sale_info_for_entity
from blueprints.report.services.shared import (
    check_user_has_entities, header_publishing_status_for, parse_nested_keys,
    resolve_report_entity_id, safe_float)
from blueprints.shared.entity_display import entity_badge_data
from models.db import Entity, Report, ReportSaleDetail, SaleInfo, db
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




@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/new/sale", methods=["GET", "POST"])
@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/<string:id>/sale", methods=["GET"])
@report_bp.route("/report/sale", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/sale", methods=["GET"])
@login_required
def report_sale(id=None, entity_id=None):
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
        # Step 4a-6: collapsed off the ReportDraft coalesce — drafts live in
        # `report` since Stage 4a. Any status, as before.
        latest_report_date = (
            db.session.query(db.func.max(Report.transaction_date))
            .filter(Report.company == entity_id)
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
            completed_sections=(report.completed_sections or ["opening"]) if report else ["opening"],
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
        from blueprints.report.services.sales import save_sales

        try:
            action_type = request.form.get("action_type", "save_next")
            transaction_date_str = request.form.get("transaction_date")
            if transaction_date_str:
                transaction_date = datetime.strptime(transaction_date_str, "%Y-%m-%d").date()
            else:
                transaction_date = datetime.now().date()

            # The day's draft (Opening makes it). POST has no id in its URL, so (entity, date).
            report_draft = Report.query.filter_by(
                company=entity_id,
                transaction_date=transaction_date,
                status="draft",
            ).first()
            if report_draft is None:
                logger.error(f"Sales form - No draft for entity {entity_id} on {transaction_date}")
                flash("I don't see a draft yet - let's start with the opening entry.", "danger")
                return redirect(url_for("report.report_opening"))

            shop_sales_data = parse_nested_keys(request.form, "sales[shop_sales]")
            delivery_sales_data = parse_nested_keys(request.form, "sales[delivery_sales]")
            amounts = {
                m.value_name: resolve_posted_sale_amount(m.value_name, shop_sales_data, delivery_sales_data)
                for m in get_unique_sale_info_for_entity(entity_id)
                if m.value_name
            }
            amounts["cash_sales"] = resolve_posted_sale_amount("cash_sales", shop_sales_data, delivery_sales_data)
            save_sales(entity_id, current_user, report_draft, amounts, action_type)

            if action_type == "save_exit":
                return redirect(url_for("entity.report_dashboard", id=entity_id))
            return redirect(
                url_for(
                    "report.report_expense",
                    entity_id=entity_id,
                    transaction_date=transaction_date.strftime("%Y-%m-%d"),
                )
            )

        except Exception:
            db.session.rollback()
            logger.exception("Error updating sales draft data")
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
                db.or_(Report.status.is_(None), Report.status != "draft"),
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
                    SaleInfo.sale_name,
                    SaleInfo.value_name,
                )
                .join(SaleInfo, SaleInfo.id == ReportSaleDetail.sale_id, isouter=True)
                .filter(ReportSaleDetail.report_id == existing_draft.id)
                .order_by(ReportSaleDetail.created_at.desc())
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
                (existing_draft.completed_sections or ["opening"]) if existing_draft else ["opening"]
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
