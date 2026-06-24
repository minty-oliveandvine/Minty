# Report creation route; delegates to services.
# Report creation: DB, validation. Logic moved from app.create_report.
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.s3_storage import upload_file_to_s3
from blueprints.report.services.shared import parse_nested_keys, safe_float
from models.db import Entity, Report, ReportCashCountDraft, ShopExpense, db
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@report_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_report():
    entity_id = request.args.get("entity_id") or request.form.get("entity_id")
    if not entity_id:
        flash("Entity context is required.", "danger")
        return redirect(url_for("entity.entity_list"))
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You do not have permission to create reports for this entity.",
            entity_id=entity_id,
        )

    if request.method == "POST":
        try:
            logger.info(f"Raw form data: {request.form.to_dict(flat=False)}")
            logger.info(f"Raw file data: {request.files.to_dict(flat=False)}")

            cleaned_form = {key: request.form.getlist(
                key)[0] for key in request.form.keys()}
            logger.info(f"Cleaned form data: {cleaned_form}")

            shop_sales_data = parse_nested_keys(
                request.form, "sales[shop_sales]")
            delivery_sales_data = parse_nested_keys(
                request.form, "sales[delivery_sales]"
            )

            transaction_date = datetime.strptime(
                request.form["transaction_date"], "%Y-%m-%d"
            ).date()

            # Reject dates that fall within a Xero-locked period (uses the
            # cached lock date; publishing re-validates against fresh Xero data).
            from blueprints.xero.services.integration import (
                get_effective_lock_date, lock_date_violation_message)
            entity = Entity.query.get(entity_id)
            lock_msg = lock_date_violation_message(
                transaction_date, get_effective_lock_date(entity)
            )
            if lock_msg:
                logger.warning(
                    f"Transaction date {transaction_date} is within Xero lock period for entity {entity_id}"
                )
                raise ValueError(lock_msg)

            logger.info(
                f"Checking for existing report with transaction_date: {transaction_date} for company: {entity_id}"
            )

            existing_report = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
            ).first()

            if existing_report and not hasattr(
                    existing_report, "_sa_instance_state"):
                logger.warning(
                    f"Duplicate report detected for date {transaction_date} - {existing_report}"
                )
                raise ValueError(
                    f"A report for {transaction_date} already exists. Please delete it first. ?´ë¹ ? ì§??ë¦¬í¬?¸ê? ?´ë? ?ìµ?ë¤, ?? ?ê³  ?¤ì ?ì¶ ?ìê¸?ë°ë?ë¤."
                )

            last_report = (
                Report.query.filter_by(company=entity_id)
                .order_by(Report.transaction_date.desc())
                .first()
            )
            logger.info(f"last report is {last_report}")
            if last_report:
                if transaction_date <= last_report.transaction_date:
                    logger.warning(
                        f"Transaction date {transaction_date} is before or equal to last submitted report date {last_report.transaction_date}"
                    )
                    raise ValueError(
                        f"Transaction date must be after {last_report.transaction_date}. You can only start reports after your last submitted report date."
                    )
                next_transaction_date = transaction_date + timedelta(days=1)
            else:
                logger.info(
                    "No previous reports found; this is the first report.")
                today = datetime.now().date()
                seven_days_ago = today - timedelta(days=7)
                if transaction_date < seven_days_ago or transaction_date > today:
                    logger.warning(
                        f"Transaction date {transaction_date} is outside the 7-day window from today {today}"
                    )
                    raise ValueError(
                        f"Transaction date must be within 7 days from today. You can only create reports for dates between {seven_days_ago} and {today}."
                    )
                next_transaction_date = transaction_date + timedelta(days=1)

            opening_balance = safe_float(request.form["opening_balance"])
            cash_addition = safe_float(request.form.get("cash_addition", 0))
            bank_deposit = safe_float(request.form.get("bank_deposit", 0))
            total_shop_sales = sum(shop_sales_data.values())
            total_delivery_sales = sum(delivery_sales_data.values())
            total_sales = total_shop_sales + total_delivery_sales
            cash_sales = safe_float(
                request.form.get(
                    "sales[shop_sales][cash]", 0))

            no_expense = request.form.get("no_expense") == "true"
            total_expenses = 0

            closing_balance = (
                opening_balance
                + cash_addition
                + cash_sales
                - total_expenses
                - bank_deposit
            )

            report = Report(
                transaction_date=transaction_date,
                next_transaction_date=next_transaction_date,
                opening_balance=opening_balance,
                cash_addition=cash_addition,
                cash_sales=shop_sales_data.get("cash", 0),
                visa_sales=shop_sales_data.get("visa", 0),
                alipay_sales=shop_sales_data.get("alipay", 0),
                wechat_sales=shop_sales_data.get("wechat", 0),
                master_sales=shop_sales_data.get("master", 0),
                unionpay_sales=shop_sales_data.get("unionpay", 0),
                amex_sales=shop_sales_data.get("amex", 0),
                octopus_sales=shop_sales_data.get("octopus", 0),
                deliveroo_sales=0.0,
                foodpanda_sales=delivery_sales_data.get("foodpanda", 0),
                keeta_sales=delivery_sales_data.get("keeta", 0),
                openrice_sales=delivery_sales_data.get("openrice", 0),
                shop_sales=total_shop_sales,
                delivery_sales=total_delivery_sales,
                total_sales=total_sales,
                expenses=total_expenses,
                bank_deposit=bank_deposit,
                closing_balance=closing_balance,
                uploaded_by=current_user.username,
                company=entity_id,
            )

            db.session.add(report)
            db.session.commit()

            expenses = []
            if not no_expense:
                index = 0
                while f"shopExpenses[{index}][item]" in request.form:
                    item = request.form.get(f"shopExpenses[{index}][item]")
                    amount = safe_float(
                        request.form.get(f"shopExpenses[{index}][amount]", 0)
                    )
                    remarks = request.form.get(
                        f"shopExpenses[{index}][remarks]", "")
                    contact_id = request.form.get(
                        f"shopExpenses[{index}][contactId]")
                    contact_name = request.form.get(
                        f"shopExpenses[{index}][contactName]")
                    account_id = request.form.get(
                        f"shopExpenses[{index}][accountId]")
                    # Ensure the name is stored even if only an id was submitted.
                    if contact_id and not contact_name:
                        from services.helpers.xero_bridge import \
                            resolve_contact_name
                        contact_name = resolve_contact_name(
                            entity_id, contact_id)

                    files = request.files.getlist(f"files[{index}][]")
                    files = [
                        file for file in files if file and file.filename.strip()]

                    if not files:
                        raise ValueError(
                            f"Expense {index + 1} must have at least one valid file attached."
                        )

                    description = item if item else (
                        remarks if remarks else "EXPENSE")
                    file_paths = []
                    for file_index, file in enumerate(files):
                        file_path = upload_file_to_s3(
                            file,
                            str(report.id),
                            transaction_date=report.transaction_date,
                            description=description,
                            amount=amount,
                            file_index=file_index if len(files) > 1 else None,
                        )
                        file_paths.append(file_path)

                    expense = ShopExpense(
                        report_id=report.id,
                        item=item,
                        amount=amount,
                        remarks=remarks,
                        files=",".join(file_paths),
                        contact_id=contact_id,
                        contact_name=contact_name,
                        account_id=account_id,
                    )
                    expenses.append(expense)
                    total_expenses += amount
                    index += 1

                for expense in expenses:
                    db.session.add(expense)
                db.session.commit()

            report.closing_balance = closing_balance
            db.session.commit()
            logger.info(
                f"Report updated with total expenses: {total_expenses}")

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(
                    {
                        "status": "success",
                        "message": "Report submitted successfully.",
                        "redirect_url": url_for("auth.index", entity_id=entity_id),
                    }
                )
            flash("Report submitted successfully.", "success")
            return redirect(url_for("auth.index", entity_id=entity_id))

        except ValueError as ve:
            logger.warning(f"Validation error: {ve}")
            return jsonify({"status": "error", "message": str(ve)}), 400

        except Exception:
            db.session.rollback()
            logger.exception("Error during report creation")
            return jsonify(
                {"status": "error", "message": "An error occurred."}), 500

    last_report = (
        Report.query.filter_by(company=entity_id)
        .order_by(Report.transaction_date.desc())
        .first()
    )
    if last_report:
        if last_report.closing_balance is not None:
            opening_balance = last_report.closing_balance
            logger.info(
                f"Using previous day's closing balance as opening balance: {opening_balance} (from report {last_report.id})"
            )
        else:
            last_cashcount = ReportCashCountDraft.query.filter(
                ReportCashCountDraft.report_id == last_report.id
            ).first()
            if last_cashcount and last_cashcount.actual_cash_total is not None:
                opening_balance = last_cashcount.actual_cash_total
                logger.info(
                    f"Using previous day's cash count balance as opening balance (fallback): {opening_balance} (from report {last_report.id})"
                )
            else:
                opening_balance = 0
                logger.info(
                    f"No closing balance or cash count data found, defaulting opening balance to 0 (from report {last_report.id})"
                )
    else:
        opening_balance = 0
    next_transaction_date = (
        (last_report.transaction_date +
         timedelta(
             days=1)) if last_report else None)
    is_first_report = last_report is None
    entity = Entity.query.get(entity_id)

    default_report = {
        "cash_sales": "",
        "visa_sales": "",
        "alipay_sales": "",
        "wechat_sales": "",
        "master_sales": "",
        "unionpay_sales": "",
        "amex_sales": "",
        "octopus_sales": "",
        "foodpanda_sales": "",
        "keeta_sales": "",
        "openrice_sales": "",
        "shop_sales": "",
        "delivery_sales": "",
        "total_sales": "",
        "expenses": "",
        "bank_deposit": "",
        "closing_balance": opening_balance,
        "cash_addition": "",
        "adjusted_opening_balance": opening_balance,
    }

    return render_template(
        "index.html",
        current_user=current_user,
        opening_balance=opening_balance,
        report=default_report,
        next_transaction_date=next_transaction_date,
        is_first_report=is_first_report,
        entity_id=entity_id,
        entity_name=entity.name if entity else entity_id,
    )
