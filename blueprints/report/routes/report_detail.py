# Report detail, edit, delete, download, resume; delegates to services.

from datetime import datetime
from io import BytesIO
from typing import Any, cast

import pandas as pd
from flask import (flash, jsonify, make_response, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.report import report_bp
from blueprints.report.services.shared import split_receipt_keys
from blueprints.report.services.history import log_history
from blueprints.report.services.report_detail import has_route
from blueprints.report.services.s3_storage import (delete_expense_with_receipts,
                                                   delete_files_from_s3,
                                                   get_s3_bucket,
                                                   get_s3_client,
                                                   upload_file_to_s3)
from blueprints.report.services.shared import (get_cash_sales_from_detail,
                                               get_next_section_for_user,
                                               parse_nested_keys,
                                               resolve_report_entity_id,
                                               safe_float,
                                               sales_amounts_by_short_name,
                                               write_sales_detail_rows)
from models.db import Report, ReportHistory, ReportSaleDetail, ShopExpense, db
from services.authz import permission_denied
from services.helpers.xero_bridge import get_entity_account_settings
from services.permission_policy import (Permission, can_delete_report,
                                        can_view_report, has_permission)


@report_bp.route("/report/<string:id>")
@login_required
def report_detail(id):
    try:
        s3_client = get_s3_client()
        bucket = get_s3_bucket()

        report = Report.query.get_or_404(id)
        if not can_view_report(current_user, report):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view this report.",
                    }
                ),
                403,
            )
        logger.debug(f"Report data: {report.__dict__}")

        history_log = (
            ReportHistory.query.filter_by(report_id=id)
            .order_by(ReportHistory.timestamp.desc())
            .all()
        )

        report.adjusted_opening_balance = report.opening_balance + (
            report.cash_addition or 0.0
        )

        sales_display_names = {
            "cash_sales": "Cash",
            "visa_sales": "Visa",
            "alipay_sales": "Alipay",
            "wechat_sales": "WeChat",
            "master_sales": "MasterCard",
            "unionpay_sales": "UnionPay",
            "amex_sales": "Amex",
            "octopus_sales": "Octopus",
            "foodpanda_sales": "Foodpanda",
            "keeta_sales": "Keeta",
            "openrice_sales": "OpenRice",
        }

        # Built from report_sale_detail rather than one column per method, so
        # a method added to the sales_method catalog appears without a change
        # here. Cash keeps its column and is merged back in.
        shop_sales_data, delivery_sales_data = sales_amounts_by_short_name(
            report.id, report.company
        )
        shop_sales_data["cash"] = report.cash_sales

        total_shop_sales = report.shop_sales or 0.0
        total_delivery_sales = report.delivery_sales or 0.0
        total_sales = total_shop_sales + total_delivery_sales
        total_expenses = report.expenses or 0.0
        bank_deposit = report.bank_deposit or 0.0
        cash_sales = get_cash_sales_from_detail(
            report.id, fallback_value=report.cash_sales or 0.0
        )
        closing_balance = (
            report.opening_balance
            + (report.cash_addition or 0)
            + cash_sales
            - total_expenses
            - bank_deposit
        )

        # receipts hang off the expense lines now (attachment rows), not the report
        files = [key for expense in report.shop_expenses for key in expense.receipt_keys]
        file_urls = []
        for file in files:
            if file:
                try:
                    file_url = s3_client.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": bucket, "Key": file},
                        ExpiresIn=3600,
                    )
                    file_urls.append(file_url)
                except Exception as e:
                    logger.warning(f"Failed to generate URL for file {file}: {e}")

        logger.debug(f"Shop Sales Breakdown: {shop_sales_data}")
        logger.debug(f"Delivery Sales Breakdown: {delivery_sales_data}")

        return render_template(
            "report_detail.html",
            report=report,
            cash_addition=report.cash_addition,
            total_shop_sales=total_shop_sales,
            total_expenses=total_expenses,
            total_sales=total_sales,
            bank_deposit=bank_deposit,
            files=file_urls,
            sales_display_names=sales_display_names,
            closing_balance=closing_balance,
            shop_sales_data=shop_sales_data,
            delivery_sales_data=delivery_sales_data,
            history_log=history_log,
        )

    except Exception as e:
        logger.error(f"Error fetching report with id {id}: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Hmm, I couldn't find that report.",
                }
            ),
            404,
        )


@report_bp.route("/report/edit/<string:id>", methods=["GET", "POST"])
@login_required
def edit_report(id):
    report = db.session.query(Report).filter_by(id=id).first()

    if not report:
        flash("Hmm, I couldn't find that report.", "danger")
        return redirect(url_for("auth.index" if has_route("auth.index") else "index"))

    entity_id = report.company
    if not entity_id or not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You are not authorized to edit this report.",
            entity_id=entity_id,
        )

    most_recent_report = (
        db.session.query(Report)
        .filter_by(company=report.company)
        .order_by(Report.transaction_date.desc())
        .first()
    )
    if report.id != most_recent_report.id:
        flash(
            "I can only let you edit the most recent report.",
            "warning",
        )
        return redirect(url_for("report.report_detail", id=report.id))

    if request.method == "POST":
        try:
            logger.info(f"Received Edit Report Data: {request.form}")

            submitted_transaction_date_str = request.form.get("transaction_date")
            if submitted_transaction_date_str is None:
                flash("That field can't be empty! Please let me know your transaction date.", "danger")
                return redirect(url_for("report.edit_report", id=report.id))
            submitted_transaction_date = datetime.strptime(
                submitted_transaction_date_str, "%Y-%m-%d"
            ).date()
            if submitted_transaction_date != report.transaction_date:
                flash("The transaction date is locked in once a report is saved - I can't change it now.", "danger")
                return redirect(url_for("report.edit_report", id=report.id))

            report.opening_balance = safe_float(request.form.get("opening_balance", 0))
            report.cash_addition = safe_float(request.form.get("cash_addition", 0))
            report.bank_deposit = safe_float(request.form.get("bank_deposit", 0))

            # Existing amounts come from report_sale_detail, so a field the
            # form omits keeps its stored value exactly as before — the
            # per-method columns are no longer consulted.
            existing_shop, existing_delivery = sales_amounts_by_short_name(
                report.id, report.company
            )
            existing_shop["cash"] = report.cash_sales

            shop_sales_data = parse_nested_keys(
                request.form, "sales[shop_sales]", existing_values=existing_shop
            )
            delivery_sales_data = parse_nested_keys(
                request.form,
                "sales[delivery_sales]",
                existing_values=existing_delivery,
            )

            report.cash_sales = shop_sales_data.get("cash", report.cash_sales)
            # Per-method amounts are rewritten as detail rows (replace=True
            # clears this report's rows first, so an edit is idempotent).
            write_sales_detail_rows(
                report_id=report.id,
                entity_id=report.company,
                shop_sales_data=shop_sales_data,
                delivery_sales_data=delivery_sales_data,
            )

            # The form re-posts every line; the ones it keeps name their receipts in
            # existing_files[n], and those objects must survive the rewrite.
            kept_keys = set()
            index = 0
            while f"shopExpenses[{index}][item]" in request.form:
                kept_keys.update(
                    key for key in split_receipt_keys(request.form.get(f"existing_files[{index}]", ""))
                )
                index += 1
            for expense in ShopExpense.query.filter_by(report_id=report.id).all():
                delete_expense_with_receipts(expense, keep_keys=kept_keys)

            total_expenses = 0
            index = 0

            if request.form.get("no_expense") != "true":
                index = 0
                while f"shopExpenses[{index}][item]" in request.form:
                    item = request.form.get(f"shopExpenses[{index}][item]")
                    amount = safe_float(
                        request.form.get(f"shopExpenses[{index}][amount]", 0)
                    )
                    remarks = request.form.get(f"shopExpenses[{index}][remarks]", "")

                    existing_files = request.form.get(f"existing_files[{index}]", "")
                    files = request.files.getlist(f"files[{index}][]")

                    file_paths = split_receipt_keys(existing_files) if existing_files else []

                    if files and any(file.filename for file in files):
                        if existing_files:
                            delete_files_from_s3(split_receipt_keys(existing_files))

                        description = (
                            item if item else (remarks if remarks else "EXPENSE")
                        )
                        file_paths = []
                        for file_index, file in enumerate(files):
                            if file:
                                file_path = upload_file_to_s3(
                                    file,
                                    str(report.id),
                                    transaction_date=report.transaction_date,
                                    description=description,
                                    amount=amount,
                                    file_index=file_index if len(files) > 1 else None,
                                )
                                file_paths.append(file_path)

                    rewritten = ShopExpense(
                        report_id=report.id,
                        item=item,
                        amount=amount,
                        remarks=remarks,
                    )
                    uploaded_by_name = {
                        path: (uploaded.filename, uploaded.mimetype)
                        for uploaded, path in zip([f for f in files if f], file_paths)
                    } if files and any(file.filename for file in files) else {}
                    rewritten.set_receipts(
                        [(path, *uploaded_by_name.get(path, (None, None))) for path in file_paths],
                        uploaded_by=current_user.id,
                    )
                    db.session.add(rewritten)

                    total_expenses += amount
                    index += 1

            report.expenses = total_expenses
            cash_sales = get_cash_sales_from_detail(
                report.id, fallback_value=report.cash_sales or 0.0
            )
            report.closing_balance = (
                report.opening_balance
                + (report.cash_addition or 0)
                + cash_sales
                - (report.bank_deposit or 0)
                - report.expenses
            )

            db.session.commit()
            logger.info(f"Updated report: {report.__dict__}")

            log_history(
                report_id=report.id,
                company=report.company,
                user_id=current_user.id,
                action="edited",
                field_changed="multiple_fields",
                old_value="Previous State",
                new_value="Updated State",
            )

            flash(
                "Report updated!",
                "success",
            )
            return redirect(url_for("report.report_detail", id=report.id))

        except ValueError as ve:
            logger.warning(f"Validation error: {str(ve)}")
            flash(str(ve), "danger")
            return redirect(url_for("report.edit_report", id=report.id))

        except Exception:
            logger.exception("Unexpected error editing report")
            db.session.rollback()
            flash("Something went wrong saving your changes to this report. Mind trying again?", "danger")

    sales_data = {
        "shop_sales": {
            field.replace("_sales", ""): getattr(report, field, 0.0)
            for field in [
                "cash_sales",
                "visa_sales",
                "alipay_sales",
                "wechat_sales",
                "master_sales",
                "unionpay_sales",
                "amex_sales",
                "octopus_sales",
            ]
        },
        "delivery_sales": {
            field.replace("_sales", ""): getattr(report, field, 0.0)
            for field in [
                "foodpanda_sales",
                "keeta_sales",
                "openrice_sales",
            ]
        },
    }

    # Per-method amounts for the form, keyed by the legacy value_name the
    # template still uses. Sourced from report_sale_detail, so a method added
    # to the catalog appears here with no template change.
    _shop, _delivery = sales_amounts_by_short_name(report.id, report.company)
    sales_amounts = {
        f"{short}_sales": amount
        for short, amount in list(_shop.items()) + list(_delivery.items())
    }
    sales_amounts["cash_sales"] = report.cash_sales or 0.0

    return render_template(
        "edit_report.html",
        report=report,
        sales_data=sales_data,
        sales_amounts=sales_amounts,
        expenses=report.expenses,
    )


@report_bp.route("/report/delete/<string:id>", methods=["POST"])
@login_required
def delete_report(id):
    s3_client = get_s3_client()
    bucket = get_s3_bucket()

    def _delete_report_children(report_id):
        """Delete the child rows that must go before a report row can.

        Renamed from _delete_report_v2_cascade in Step 4a-2: ReportV2 had no
        writers since r2a02, its delete went with that edit, and the table
        itself was dropped in r10a10.

        The report_expense_detail delete went in Step 3.5.

        The Xero sync rows (xero_report_sync, xero_bank_transaction,
        xero_bank_transfer) go WITH the report: the schema's FKs are ON DELETE
        CASCADE (C5 reversed r9a09's SET NULL - a publish record for a report
        that no longer exists has nothing to protect). Deleted here explicitly
        so SQLite, which enforces no FK, behaves like Postgres.
        """
        from models.db import XeroBankTransaction, XeroBankTransfer, XeroReportSync

        ReportSaleDetail.query.filter_by(report_id=report_id).delete()
        XeroReportSync.query.filter_by(report_id=report_id).delete()
        XeroBankTransfer.query.filter_by(sync_report_id=report_id).delete()
        XeroBankTransaction.query.filter_by(sync_report_id=report_id).delete()

    def _delete_expenses_with_receipts(report_id):
        """Delete a report's expense lines and their receipts (F2)."""
        expenses = ShopExpense.query.filter_by(report_id=report_id).all()
        logger.info(
            f"Deleting {len(expenses)} expense lines and "
            f"{sum(len(e.attachments) for e in expenses)} receipts of report {report_id}"
        )
        for expense in expenses:
            delete_expense_with_receipts(expense)

    try:
        # Step 4a-6: the whole "no Report row, fall back to a ReportDraft"
        # branch that used to sit here is gone. It existed for drafts predating
        # Stage 4a, which is when every draft gained a paired `report` row with
        # the same id. With report_draft dropped there is nothing to fall back
        # to — no row means the report genuinely does not exist.
        report = Report.query.get_or_404(id)

        entity_id = report.company
        if not can_delete_report(current_user, report):
            return permission_denied(
                "You are not authorized to delete this report.",
                entity_id=entity_id,
            )

        # Deliberately INCLUDES drafts. Deleting a report whose successor
        # exists — draft or submitted — would leave that successor's opening
        # balance dangling, since it chains off this report's closing balance.
        newer_report = (
            Report.query.filter(
                Report.company == report.company,
                Report.transaction_date > report.transaction_date,
            )
            .order_by(Report.transaction_date.asc())
            .first()
        )

        if newer_report:
            flash(
                "I can only delete the most recent report, and there's a newer one after this.", "danger",
            )
            return redirect(url_for("entity.report_dashboard", id=entity_id))

        prev_report = (
            Report.query.filter(
                Report.company == report.company,
                Report.transaction_date < report.transaction_date,
            )
            .order_by(Report.transaction_date.desc())
            .first()
        )

        next_report = (
            Report.query.filter(
                Report.company == report.company,
                Report.transaction_date > report.transaction_date,
            )
            .order_by(Report.transaction_date.asc())
            .first()
        )

        if prev_report:
            prev_report.next_transaction_date = (
                next_report.transaction_date if next_report else None
            )
            db.session.add(prev_report)

        # The receipts go with the report: every expense line's attachments are
        # removed from S3 and their rows deleted with the line (F2).
        _delete_expenses_with_receipts(report.id)
        _delete_report_children(report.id)

        # The paired-ReportDraft delete that sat here went with Step 4a-6 —
        # report and draft are one row, already being deleted below.

        # Sibling rows for the same (company, transaction_date); duplicates per
        # date do occur. The status filter is LOAD-BEARING and now the only
        # thing scoping this to drafts — the table used to imply it. Without
        # it this deletes submitted reports for the same entity and date.
        other_drafts = (
            Report.query.filter(
                Report.company == report.company,
                Report.transaction_date == report.transaction_date,
                Report.id != report.id,
                Report.status == "draft",
            ).all()
        )

        for draft in other_drafts:
            _delete_expenses_with_receipts(draft.id)
            _delete_report_children(draft.id)
            # One row per sibling now (Step 4a-6) — delete it directly.
            paired_sibling = Report.query.filter_by(id=draft.id).first()
            if paired_sibling:
                db.session.delete(paired_sibling)
            db.session.delete(draft)

        db.session.delete(report)
        db.session.commit()

        flash("That report's deleted.", "success")
        return redirect(url_for("entity.report_dashboard", id=entity_id))

    except IntegrityError:
        logger.exception(f"Integrity error deleting report {id}")
        db.session.rollback()
        flash(
            "I can't delete this report — other records still depend on it. "
            "Could you remove or update those first, then try again?",
            "danger",
        )
        entity_id = id
        r = Report.query.get(id)
        if r:
            entity_id = r.company
        return redirect(url_for("entity.report_dashboard", id=entity_id))
    except Exception:
        logger.exception(f"Error deleting report {id}")
        db.session.rollback()
        flash("Something went wrong deleting that report. Mind trying again?", "danger")
        entity_id = id
        r = Report.query.get(id)
        if r:
            entity_id = r.company
        return redirect(url_for("entity.report_dashboard", id=entity_id))


@report_bp.route("/report/download/<string:id>", methods=["GET"])
@login_required
def download_report(id):
    try:
        if not current_user.is_authenticated:
            flash("Your session ran out. Mind logging back in?", "warning")
            return redirect(url_for("auth.login"))

        report = (
            Report.query.join(ShopExpense, isouter=True).filter(Report.id == id).first()
        )
        if not report:
            return jsonify({"status": "error", "message": "Hmm, I couldn't find that report."}), 404

        entity_id = report.company
        # can_view_report, not "uploader OR permission": an uploader whose
        # membership was removed must lose access too.
        if not can_view_report(current_user, report):
            return jsonify({"status": "error", "message": "Not authorized."}), 403
        expenses = ShopExpense.query.filter_by(report_id=report.id).all()
        rows = []
        for exp in expenses:
            rows.append(
                {
                    "Date": (
                        report.transaction_date.strftime("%Y-%m-%d")
                        if report.transaction_date
                        else "N/A"
                    ),
                    "Account Code": exp.account_code or "N/A",
                    "Amount": -(exp.amount or 0),
                    "Description": (
                        "Expense"
                        if exp.remarks in ("No description", "-")
                        else exp.remarks or "Expense"
                    ),
                    "Reference": " ",
                    "Check Number": " ",
                }
            )

        cash_sale_settings = get_entity_account_settings(entity_id, "cash_sale")
        logger.info(f"Cash sale settings for entity {entity_id}: {cash_sale_settings}")
        cash_sale_account_code = (
            cash_sale_settings["account_code"]
            if cash_sale_settings and "account_code" in cash_sale_settings
            else ""
        )
        rows.append(
            {
                "Date": (
                    report.transaction_date.strftime("%Y-%m-%d")
                    if report.transaction_date
                    else "N/A"
                ),
                "Account Code": cash_sale_account_code or "",
                "Amount": report.cash_sales or 0,
                "Description": "Cash Sale (Pettycash)",
                "Reference": " ",
                "Check Number": " ",
            }
        )

        df = pd.DataFrame(
            rows,
            columns=pd.Index(
                [
                    "Date",
                    "Account Code",
                    "Amount",
                    "Description",
                    "Reference",
                    "Check Number",
                ]
            ),
        )

        output = BytesIO()
        try:
            with pd.ExcelWriter(cast(Any, output), engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Report")
                ws = writer.sheets["Report"]
                for index, col in enumerate(df.columns, 1):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    ws.column_dimensions[
                        ws.cell(row=1, column=index).column_letter
                    ].width = max_len
        except Exception as excel_error:
            print(f"Excel generation error: {excel_error}")
            return (
                jsonify(
                    {"status": "error", "message": "Something went wrong on my end while building that Excel file. Mind trying again?"}
                ),
                500,
            )

        output.seek(0)
        try:
            response = make_response(output.read())
        except Exception as response_error:
            print(f"Response generation error: {response_error}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Something went wrong on my end while preparing that download. Mind trying again?",
                    }
                ),
                500,
            )
        response.headers["Content-Disposition"] = (
            f"attachment; filename=report_{id}.xlsx"
        )
        response.headers["Content-type"] = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return response

    except Exception as e:
        print(f"Error downloading report with id {id}: {e}")
        import traceback

        traceback.print_exc()
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while building that Excel report. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/entity/<entity:entity_id>/reports/resume", methods=["GET"])
@report_bp.route("/report/resume", methods=["GET"])
@login_required
def resume_report(entity_id=None):
    try:
        entity_id = entity_id or request.args.get("entity_id")
        transaction_date_param = request.args.get("transaction_date")
        report_or_draft_id = request.args.get("report_id") or request.args.get(
            "draft_id"
        )

        logger.info(
            f"Resume report - entity_id: {entity_id}, transaction_date: {transaction_date_param}, report_or_draft_id: {report_or_draft_id}"
        )

        company_or_entity = entity_id or resolve_report_entity_id(report_or_draft_id)
        if not company_or_entity:
            flash("I need to know which entity we're working with first!", "danger")
            return redirect(url_for("entity.entity_list"))

        next_section, draft_id, is_draft = get_next_section_for_user(
            current_user,
            company_or_entity,
            transaction_date_param,
            draft_id=report_or_draft_id,
        )

        logger.info(
            f"User {current_user.username} resuming report at section: {next_section}"
        )

        transaction_date = None
        if transaction_date_param:
            try:
                transaction_date = datetime.strptime(
                    transaction_date_param, "%Y-%m-%d"
                ).date()
                logger.info(
                    f"Resuming report for transaction_date from parameter: {transaction_date}"
                )
            except ValueError:
                logger.warning(
                    f"Invalid transaction_date parameter: {transaction_date_param}"
                )
                if draft_id:
                    draft = Report.query.get(draft_id)
                    if draft:
                        transaction_date = draft.transaction_date
                        logger.info(
                            f"Using draft transaction_date as fallback: {transaction_date}"
                        )
        elif draft_id:
            draft = Report.query.get(draft_id)
            if draft:
                transaction_date = draft.transaction_date
                logger.info(
                    f"Resuming report for transaction_date from draft: {transaction_date}"
                )

        def build_url(route_name, **kwargs):
            if company_or_entity:
                url = url_for(route_name, **kwargs)
                separator = "&" if "?" in url else "?"
                return f"{url}{separator}entity_id={company_or_entity}"
            return url_for(route_name, **kwargs)

        if next_section == "opening":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_opening",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_opening"))
        elif next_section == "sales":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_sale",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_sale"))
        elif next_section == "expenses":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_expense",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_expense"))
        elif next_section == "deposit":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_deposit",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_deposit"))
        elif next_section == "cash_count":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_cash_count",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_cash_count"))
        elif next_section == "ending":
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_ending",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_ending"))
        else:
            if transaction_date:
                return redirect(
                    build_url(
                        "report.report_opening",
                        transaction_date=transaction_date.strftime("%Y-%m-%d"),
                    )
                )
            return redirect(build_url("report.report_opening"))

    except Exception as e:
        logger.error(f"Error determining resume section: {str(e)}")
        flash("Something went wrong picking up where you left off, so I've taken us back to the first step.", "warning")
        entity_id = request.args.get("entity_id")
        if entity_id:
            return redirect(
                url_for("report.report_opening") + f"?entity_id={entity_id}"
            )
        return redirect(url_for("report.report_opening"))
