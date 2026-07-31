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
from blueprints.report.services.history import log_history
from blueprints.report.services.report_detail import has_route
from blueprints.report.services.s3_storage import (delete_files_from_s3,
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
from models.db import (Report, ReportCashCountDraft, ReportDraft,
                       ReportExpenseDetail, ReportHistory, ReportSaleDetail,
                       ReportV2, ShopExpense, ShopExpenseDraft, db)
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

        files = report.receipt_files.split(",") if report.receipt_files else []
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

            old_expenses = ShopExpense.query.filter_by(report_id=report.id).all()
            for expense in old_expenses:
                if expense.files:
                    delete_files_from_s3(expense.files.split(","))

            db.session.query(ShopExpense).filter_by(report_id=report.id).delete(
                synchronize_session=False
            )

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

                    file_paths = existing_files.split(",") if existing_files else []

                    if files and any(file.filename for file in files):
                        if existing_files:
                            delete_files_from_s3(existing_files.split(","))

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

                    db.session.add(
                        ShopExpense(
                            report_id=report.id,
                            item=item,
                            amount=amount,
                            remarks=remarks,
                            files=",".join(file_paths),
                        )
                    )

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

    def _delete_report_v2_cascade(report_id):
        """Delete ReportV2 and all records that reference it via FK."""
        ReportExpenseDetail.query.filter_by(report_id=report_id).delete()
        ReportSaleDetail.query.filter_by(report_id=report_id).delete()
        from models.db import XeroBankTransfer, XeroReportSync
        XeroReportSync.query.filter_by(report_id=report_id).delete()
        XeroBankTransfer.query.filter_by(sync_report_id=report_id).delete()
        ReportV2.query.filter_by(report_id=report_id).delete()

    try:
        report = Report.query.get(id)

        if not report:
            report_draft = ReportDraft.query.get_or_404(id)
            if not can_delete_report(current_user, report_draft):
                return permission_denied(
                    "You are not authorized to delete this report.",
                    entity_id=report_draft.company,
                )
            entity_id = report_draft.company

            ShopExpense.query.filter_by(report_id=report_draft.id).delete()
            ReportCashCountDraft.query.filter_by(report_id=report_draft.id).delete()
            _delete_report_v2_cascade(report_draft.id)
            # Since Stage 4a a draft has a paired `report` row with the same id.
            # This branch predates that and only deleted the draft, so the
            # report row survived and the "deleted" report kept showing up in
            # the dashboard and history, which read `report` now.
            paired = Report.query.filter_by(id=report_draft.id).first()
            if paired:
                db.session.delete(paired)
            db.session.delete(report_draft)

            # status filter is load-bearing: this deletes SIBLING rows matched
            # on (company, transaction_date), and duplicates per date do occur.
            # Without it, once drafts live in `report`, this would delete
            # submitted reports for the same entity and date.
            other_drafts = (
                ReportDraft.query.filter(
                    ReportDraft.company == report_draft.company,
                    ReportDraft.transaction_date == report_draft.transaction_date,
                    ReportDraft.id != report_draft.id,
                    ReportDraft.status == "draft",
                ).all()
            )
            for draft in other_drafts:
                ShopExpense.query.filter_by(report_id=draft.id).delete()
                ReportCashCountDraft.query.filter_by(report_id=draft.id).delete()
                _delete_report_v2_cascade(draft.id)
                paired_sibling = Report.query.filter_by(id=draft.id).first()
                if paired_sibling:
                    db.session.delete(paired_sibling)
                db.session.delete(draft)

            db.session.commit()

            flash("That report's deleted.", "success")
            return redirect(url_for("entity.report_dashboard", id=entity_id))

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

        if report.receipt_files:
            for file_key in report.receipt_files.split(","):
                try:
                    s3_client.delete_object(Bucket=bucket, Key=file_key)
                except Exception as e:
                    logger.warning(f"Failed to delete file {file_key} from S3: {e}")

        ShopExpense.query.filter_by(report_id=report.id).delete()
        _delete_report_v2_cascade(report.id)

        report_draft = ReportDraft.query.filter_by(id=report.id).first()
        if report_draft:
            ShopExpense.query.filter_by(report_id=report_draft.id).delete()
            ReportCashCountDraft.query.filter_by(report_id=report_draft.id).delete()
            db.session.delete(report_draft)

        # See the note on the draft-only branch: status keeps this from
        # deleting submitted reports once drafts move into `report`.
        other_drafts = (
            ReportDraft.query.filter(
                ReportDraft.company == report.company,
                ReportDraft.transaction_date == report.transaction_date,
                ReportDraft.id != report.id,
                ReportDraft.status == "draft",
            ).all()
        )

        for draft in other_drafts:
            ShopExpense.query.filter_by(report_id=draft.id).delete()
            ReportCashCountDraft.query.filter_by(report_id=draft.id).delete()
            _delete_report_v2_cascade(draft.id)
            # Sibling drafts have paired `report` rows too (Stage 4a) — delete
            # both or the sibling survives in the dashboard as a ghost draft.
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
        else:
            rd = ReportDraft.query.get(id)
            if rd:
                entity_id = rd.company
        return redirect(url_for("entity.report_dashboard", id=entity_id))
    except Exception:
        logger.exception(f"Error deleting report {id}")
        db.session.rollback()
        flash("Something went wrong deleting that report. Mind trying again?", "danger")
        entity_id = id
        r = Report.query.get(id)
        if r:
            entity_id = r.company
        else:
            rd = ReportDraft.query.get(id)
            if rd:
                entity_id = rd.company
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
        if (
            report.uploaded_by != current_user.username
            and not has_permission(current_user, Permission.REPORT_VIEW_ENTITY, entity_id)
        ):
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


@report_bp.route("/report/resume", methods=["GET"])
@login_required
def resume_report():
    try:
        entity_id = request.args.get("entity_id")
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
                    draft = ReportDraft.query.get(draft_id)
                    if draft:
                        transaction_date = draft.transaction_date
                        logger.info(
                            f"Using draft transaction_date as fallback: {transaction_date}"
                        )
        elif draft_id:
            draft = ReportDraft.query.get(draft_id)
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
