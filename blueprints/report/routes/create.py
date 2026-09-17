# Report creation route; delegates to services.
# Report creation: DB, validation. Logic moved from app.create_report.
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.s3_storage import upload_file_to_s3
from blueprints.report.services.shared import (future_date_error,
                                               parse_nested_keys, safe_float,
                                               write_sales_detail_rows)
from models.db import Entity, Report, ShopExpense, db, tz
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@report_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_report():
    entity_id = request.args.get("entity_id") or request.form.get("entity_id")
    if not entity_id:
        flash("I need to know which entity we're working with first!", "danger")
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
            # No report may be created for a date after today, regardless of how
            # many prior reports exist.
            future_err = future_date_error(transaction_date)
            if future_err:
                logger.warning(
                    f"Transaction date {transaction_date} rejected: {future_err}"
                )
                raise ValueError(future_err)
            logger.info(
                f"Checking for existing report with transaction_date: {transaction_date} for company: {entity_id}"
            )

            # Submitted reports only: drafts live in `report` since Stage 4a,
            # so an unfiltered match would treat an in-progress draft as a
            # duplicate.
            existing_report = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
                db.or_(Report.status.is_(None), Report.status != "draft"),
            ).first()

            if existing_report and not hasattr(
                    existing_report, "_sa_instance_state"):
                logger.warning(
                    f"Duplicate report detected for date {transaction_date} - {existing_report}"
                )
                raise ValueError(
                    f"A report for {transaction_date} already exists. Please delete it first."
                )

            last_report = (
                # SUBMITTED only. The error this drives says "the day after your
                # last submitted report" — but since Stage 4a a draft also lives
                # in `report`, so unfiltered this treats the user's OWN
                # in-progress draft as the last submitted report and demands the
                # next day, bouncing them off their own report.
                Report.query.filter(
                    Report.company == entity_id,
                    db.or_(Report.status.is_(None), Report.status != "draft"),
                )
                .order_by(Report.transaction_date.desc())
                .first()
            )
            logger.info(f"last report is {last_report}")
            if last_report:
                # Hong Kong time so the "future" boundary is the users' local
                # midnight, not the server's (UTC) midnight.
                today = datetime.now(tz).date()
                expected_date = last_report.transaction_date + timedelta(days=1)
                if expected_date > today:
                    logger.warning(
                        f"Next report date {expected_date} is in the future (today {today})"
                    )
                    raise ValueError(
                        f"Transaction date cannot be in the future. You can only create reports for dates up to {today}."
                    )
                if transaction_date != expected_date:
                    logger.warning(
                        f"Transaction date {transaction_date} is not the day after the last submitted report date {last_report.transaction_date}"
                    )
                    raise ValueError(
                        f"Transaction date must be {expected_date}, the day after your last submitted report ({last_report.transaction_date})."
                    )
                next_transaction_date = transaction_date + timedelta(days=1)
            else:
                logger.info(
                    "No previous reports found; this is the first report.")
                # The floor for the first report is the onboarding date — the
                # transaction_date of the opening draft seeded during onboarding
                # (Step 4). The future-date guard above already rejected any date
                # after today; the onboarding date is the lower bound when one
                # exists.
                # Draft-only, same reasoning as _onboarding_floor_date in
                # opening.py: unfiltered, this resolves to the oldest SUBMITTED
                # report and moves the floor date. The status filter is now
                # load-bearing rather than implied by the table (Step 4a-6).
                opening_draft = (
                    Report.query.filter(
                        Report.company == entity_id,
                        Report.status == "draft",
                    )
                    .order_by(Report.transaction_date.asc())
                    .first()
                )
                onboarding_date = (
                    opening_draft.transaction_date if opening_draft else None
                )
                if onboarding_date and transaction_date < onboarding_date:
                    logger.warning(
                        f"Transaction date {transaction_date} is before onboarding date {onboarding_date}"
                    )
                    raise ValueError(
                        f"Transaction date must be on or after your onboarding date ({onboarding_date})."
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
                # the stored aggregates: cash, everything-but-cash, and their sum;
                # shop/delivery come from the report_sale rows written below
                cashsale_total=shop_sales_data.get("cash", 0),
                nocashsale_total=total_sales - shop_sales_data.get("cash", 0),
                total_sales=total_sales,
                expense_total=total_expenses,
                bank_deposit=bank_deposit,
                closing_balance=closing_balance,
                created_by=current_user.id,
                entity_id=entity_id,
            )

            db.session.add(report)
            db.session.flush()  # need report.id before writing detail rows

            # Per-method amounts go to report_sale_detail, not to one column
            # each. The form keys are the entity's sale_info rows, so a method
            # added to the catalog flows through without touching this code.
            write_sales_detail_rows(
                report_id=report.id,
                entity_id=entity_id,
                shop_sales_data=shop_sales_data,
                delivery_sales_data=delivery_sales_data,
            )

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
            flash("Report submitted!", "success")
            return redirect(url_for("auth.index", entity_id=entity_id))

        except ValueError as ve:
            logger.warning(f"Validation error: {ve}")
            return jsonify({"status": "error", "message": str(ve)}), 400

        except Exception:
            db.session.rollback()
            logger.exception("Error during report creation")
            return jsonify(
                {"status": "error", "message": "Something went wrong on my end. Mind trying again?"}), 500

    # Balance chaining: includes drafts on purpose, since the next report
    # opens from the previous one's closing balance whatever its status. The
    # date-SEQUENCE guard earlier in this file is submitted-only instead.
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
            # actual_cash_total lives on `report` since r1a01 hoisted it. The
            # report_cashcount_draft fallback went in Step 4a-5: r7a07
            # backfilled every historical value onto `report`, and
            # cash_count.py has written it there since Step 3.5.
            fallback_total = last_report.actual_cash_total
            if fallback_total is not None:
                opening_balance = fallback_total
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
        # Blank new-report form: no amounts yet, so every method renders empty.
        sales_amounts={},
        opening_balance=opening_balance,
        report=default_report,
        next_transaction_date=next_transaction_date,
        is_first_report=is_first_report,
        entity_id=entity_id,
        entity_name=entity.name if entity else entity_id,
    )
