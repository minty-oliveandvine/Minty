# Report detail, edit, delete, download, resume; delegates to services.
import os
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Any, cast

import pandas as pd
from flask import current_app as app
from flask import (jsonify, make_response, redirect, render_template, request,
                   send_file)
from flask_login import current_user
from loguru import logger

from blueprints.report.services.s3_storage import get_s3_bucket, get_s3_client
from models.db import (AccountInfo, EntityAccountXero, Report, ReportDraft,
                       ShopExpense, ShopExpenseDraft, db)
from services.helpers.xero_bridge import get_entity_account_settings


def download_file(filename):
    try:
        bucket = get_s3_bucket()
        s3_client = get_s3_client()

        logger.info(f"Attempting to download file: {filename} from S3 bucket {bucket}")
        s3_key = filename
        download_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": s3_key}, ExpiresIn=3600
        )
        return redirect(download_url)
    except Exception as e:
        print(f"Error generating pre-signed URL: {e}")
        return jsonify({"status": "error", "message": str(e)}), 404


def download_statements():
    if request.method == "GET":
        companies = db.session.query(Report.company).distinct().all()
        return render_template(
            "download_statements.html", companies=[c[0] for c in companies]
        )

    elif request.method == "POST":
        try:
            start_date = request.form.get("start_date")
            end_date = request.form.get("end_date")
            company = request.form.get("company")

            if not start_date or not end_date:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "I need both a start and an end date to do that.",
                        }
                    ),
                    400,
                )

            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "That date doesn't look quite right — could you use YYYY-MM-DD?",
                        }
                    ),
                    400,
                )

            query = Report.query
            if company:
                query = query.filter(Report.company == company)
            query = query.filter(Report.transaction_date >= start_date)
            query = query.filter(Report.transaction_date <= end_date)

            reports = query.order_by(Report.transaction_date.asc()).all()
            if not reports:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "No reports found for the selected criteria.",
                        }
                    ),
                    404,
                )

            data_rows = []
            for report in reports:
                data_rows.append(
                    {
                        "Transaction Date": report.transaction_date.strftime(
                            "%Y-%m-%d"
                        ),
                        "Company": report.company,
                        "Description": "Cash Sales",
                        "Amount": report.cash_sales,
                    }
                )
                for expense in report.shop_expenses:
                    data_rows.append(
                        {
                            "Transaction Date": report.transaction_date.strftime(
                                "%Y-%m-%d"
                            ),
                            "Company": report.company,
                            "Description": f"Expense: {expense.item}",
                            "Amount": -expense.amount,
                        }
                    )
                if report.cash_addition != 0:
                    data_rows.append(
                        {
                            "Transaction Date": report.transaction_date.strftime(
                                "%Y-%m-%d"
                            ),
                            "Company": report.company,
                            "Description": "Cash Addition",
                            "Amount": report.cash_addition,
                        }
                    )
                if report.bank_deposit != 0:
                    data_rows.append(
                        {
                            "Transaction Date": report.transaction_date.strftime(
                                "%Y-%m-%d"
                            ),
                            "Company": report.company,
                            "Description": "Bank Deposit",
                            "Amount": -report.bank_deposit,
                        }
                    )

            output = BytesIO()
            with pd.ExcelWriter(cast(Any, output), engine="openpyxl") as writer:
                pd.DataFrame(data_rows).to_excel(
                    writer, index=False, sheet_name="Detailed Reports"
                )
            output.seek(0)

            response = make_response(output.read())
            response.headers["Content-Disposition"] = (
                f'attachment; filename=statements_{datetime.now().strftime("%Y%m%d%H%M%S")}.xlsx'
            )
            response.headers["Content-type"] = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            return response

        except Exception as e:
            print(f"Error generating statements: {e}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Something went wrong on my end while building those statements. Mind trying again?",
                    }
                ),
                500,
            )


def download_attachments():
    try:
        from blueprints.report.services.s3_storage import download_file_from_s3

        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        company = request.form.get("company")

        if not start_date or not end_date:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "I need both a start and an end date to do that.",
                    }
                ),
                400,
            )

        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "That date doesn't look quite right — could you use YYYY-MM-DD?",
                    }
                ),
                400,
            )

        query = Report.query.filter(
            Report.transaction_date >= start_date,
            Report.transaction_date <= end_date,
        )
        if company:
            query = query.filter(Report.company == company)

        reports = query.all()
        if not reports:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No reports found for the selected criteria.",
                    }
                ),
                404,
            )

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for report in reports:
                date_folder = report.transaction_date.strftime("%Y-%m-%d")
                for expense in report.shop_expenses:
                    if expense.files:
                        for file_path in expense.files.split(","):
                            file_path = file_path.strip()
                            file_data = download_file_from_s3(file_path)
                            if file_data:
                                zip_file.writestr(
                                    f"{date_folder}/{os.path.basename(file_path)}",
                                    file_data,
                                )

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"attachments_{start_date}_{end_date}.zip",
        )

    except Exception as e:
        print(f"Error generating attachments ZIP: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while packaging those attachments. Mind trying again?",
                }
            ),
            500,
        )


def download_reports_csv(entity_id):
    from blueprints.report.services.shared import check_user_has_entities

    try:
        if not check_user_has_entities(current_user.id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You need to create an entity first before accessing reports.",
                    }
                ),
                403,
            )

        report_id = request.args.get("report_id")

        if report_id:
            report = Report.query.filter_by(id=report_id).first()
            report_draft = None
            if not report:
                report_draft = ReportDraft.query.filter_by(id=report_id).first()

            current_report = report if report else report_draft
            if not current_report:
                return (
                    jsonify({"status": "error", "message": "Hmm, I couldn't find that report."}),
                    404,
                )

            if current_report.uploaded_by != current_user.username:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "You do not have access to this report.",
                        }
                    ),
                    403,
                )

            report_entity_id = (
                current_report.company
                if hasattr(current_report, "company")
                else entity_id
            )

            _pettycash_settings = (
                get_entity_account_settings(report_entity_id, "pettycash") or {}
            )
            main_bank_account = _pettycash_settings.get("account_code")

            _discrepancy_account_settings = (
                get_entity_account_settings(
                    report_entity_id, "discrepancy_account"
                ) or {}
            )
            discrepancy_account_code = _discrepancy_account_settings.get(
                "account_code"
            )

            transaction_date = (
                current_report.transaction_date
                if hasattr(current_report, "transaction_date")
                else None
            )
            all_rows = []

            cash_addition = (
                report.cash_addition
                if report
                else (report_draft.cash_addition if report_draft else 0)
            )
            cash_addition_account_code = main_bank_account
            withdrawal_type = getattr(current_report, "withdrawal_type", None)
            if withdrawal_type == "personal":
                director_settings = get_entity_account_settings(
                    report_entity_id, "director"
                )
                if director_settings and "account_code" in director_settings:
                    cash_addition_account_code = director_settings["account_code"]
            elif withdrawal_type == "company":
                pass

            if cash_addition and cash_addition != 0:
                all_rows.append(
                    {
                        "Date": (
                            transaction_date.strftime("%Y-%m-%d")
                            if transaction_date
                            else "N/A"
                        ),
                        "Account Code": cash_addition_account_code or "",
                        "Amount": cash_addition,
                        "Description": "Cash Addition/Withdrawal From (Start)",
                        "Reference": " ",
                        "Check Number": " ",
                    }
                )

            expenses = []
            if report:
                expenses = ShopExpense.query.filter_by(report_id=report_id).all()
            elif report_draft:
                expenses = ShopExpenseDraft.query.filter_by(
                    report_draft_id=report_id
                ).all()

            for exp in expenses:
                all_rows.append(
                    {
                        "Date": (
                            transaction_date.strftime("%Y-%m-%d")
                            if transaction_date
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

            cash_sales = (
                report.cash_sales
                if report
                else (report_draft.cash_sales if report_draft else 0)
            )
            cash_sale_settings = get_entity_account_settings(
                report_entity_id, "cash_sale"
            )
            cash_sale_account_code = (
                cash_sale_settings["account_code"]
                if cash_sale_settings and "account_code" in cash_sale_settings
                else ""
            )

            if cash_sales and cash_sales > 0:
                all_rows.append(
                    {
                        "Date": (
                            transaction_date.strftime("%Y-%m-%d")
                            if transaction_date
                            else "N/A"
                        ),
                        "Account Code": cash_sale_account_code or "",
                        "Amount": cash_sales,
                        "Description": "Cash Sale (Pettycash)",
                        "Reference": " ",
                        "Check Number": " ",
                    }
                )

            bank_deposit = (
                report.bank_deposit
                if report
                else (report_draft.bank_deposit if report_draft else 0)
            )
            if bank_deposit and bank_deposit > 0:
                all_rows.append(
                    {
                        "Date": (
                            transaction_date.strftime("%Y-%m-%d")
                            if transaction_date
                            else "N/A"
                        ),
                        "Account Code": main_bank_account or "",
                        "Amount": -bank_deposit,
                        "Description": "Bank Deposit",
                        "Reference": " ",
                        "Check Number": " ",
                    }
                )

            discrepancy_amount = (
                report.discrepancy_amount
                if report
                else (report_draft.discrepancy_amount if report_draft else 0)
            )
            discrepancy_type = (
                report.discrepancy_type
                if report
                else (report_draft.discrepancy_type if report_draft else "none")
            )

            if (
                discrepancy_type
                and discrepancy_type != "none"
                and discrepancy_amount
                and discrepancy_amount != 0
            ):
                discrepancy_value = (
                    -abs(discrepancy_amount)
                    if discrepancy_type == "shortage"
                    else abs(discrepancy_amount)
                )
                all_rows.append(
                    {
                        "Date": (
                            transaction_date.strftime("%Y-%m-%d")
                            if transaction_date
                            else "N/A"
                        ),
                        "Account Code": discrepancy_account_code or "",
                        "Amount": discrepancy_value,
                        "Description": f"Discrepancy ({discrepancy_type})",
                        "Reference": " ",
                        "Check Number": " ",
                    }
                )

            if not all_rows:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "No data to export for this report.",
                        }
                    ),
                    404,
                )

            df = pd.DataFrame(
                all_rows,
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
            df.to_csv(output, index=False)
            output.seek(0)
            response = make_response(output.read())
            response.headers["Content-Disposition"] = (
                f"attachment; filename=report_{report_id}.csv"
            )
            response.headers["Content-type"] = "text/csv"
            return response

        else:
            start_date = request.args.get("start_date")
            end_date = request.args.get("end_date")

            if not start_date or not end_date:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "I need both a start and an end date to do that.",
                        }
                    ),
                    400,
                )

            if start_date > end_date:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Your start date lands after your end date — could you flip them around?",
                        }
                    ),
                    400,
                )

            _pettycash_settings = (
                get_entity_account_settings(entity_id, "pettycash") or {}
            )
            main_bank_account = _pettycash_settings.get("account_code")

            _discrepancy_account_settings = (
                get_entity_account_settings(
                    entity_id, "discrepancy_account"
                ) or {}
            )
            discrepancy_account_code = _discrepancy_account_settings.get(
                "account_code"
            )

            report_ids_query = (
                Report.query.join(ReportDraft, ReportDraft.id == Report.id, full=True)
                .with_entities(
                    db.func.coalesce(Report.id, ReportDraft.id).label("id"),
                    db.func.coalesce(
                        Report.transaction_date, ReportDraft.transaction_date
                    ).label("transaction_date"),
                )
                .filter(
                    db.or_(
                        Report.company == entity_id, ReportDraft.company == entity_id
                    ),
                    db.and_(
                        db.or_(
                            Report.transaction_date >= start_date,
                            ReportDraft.transaction_date >= start_date,
                        ),
                        db.or_(
                            Report.transaction_date <= end_date,
                            ReportDraft.transaction_date <= end_date,
                        ),
                    ),
                )
                .order_by(
                    db.func.coalesce(
                        Report.transaction_date, ReportDraft.transaction_date
                    ).asc()
                )
                .all()
            )

            if not report_ids_query:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "No reports found in the specified date range.",
                        }
                    ),
                    404,
                )

            all_rows = []
            processed_report_ids = set()

            for report_row in report_ids_query:
                rid = report_row.id
                transaction_date = report_row.transaction_date

                if rid in processed_report_ids:
                    continue
                processed_report_ids.add(rid)

                report = Report.query.filter_by(id=rid).first()
                report_draft = None
                if not report:
                    report_draft = ReportDraft.query.filter_by(id=rid).first()

                current_report = report if report else report_draft
                if not current_report:
                    continue

                cash_addition = (
                    report.cash_addition
                    if report
                    else (report_draft.cash_addition if report_draft else 0)
                )
                cash_addition_account_code = main_bank_account
                withdrawal_type = getattr(current_report, "withdrawal_type", None)
                if withdrawal_type == "personal":
                    director_settings = get_entity_account_settings(
                        entity_id, "director"
                    )
                    if director_settings and "account_code" in director_settings:
                        cash_addition_account_code = director_settings["account_code"]
                elif withdrawal_type == "company":
                    pass

                if cash_addition and cash_addition != 0:
                    all_rows.append(
                        {
                            "Date": (
                                transaction_date.strftime("%Y-%m-%d")
                                if transaction_date
                                else "N/A"
                            ),
                            "Account Code": cash_addition_account_code or "",
                            "Amount": cash_addition,
                            "Description": "Cash Addition/Withdrawal From (Start)",
                            "Reference": " ",
                            "Check Number": " ",
                        }
                    )

                expenses = []
                if report:
                    expenses = ShopExpense.query.filter_by(report_id=rid).all()
                elif report_draft:
                    expenses = ShopExpenseDraft.query.filter_by(
                        report_draft_id=rid
                    ).all()

                for exp in expenses:
                    all_rows.append(
                        {
                            "Date": (
                                transaction_date.strftime("%Y-%m-%d")
                                if transaction_date
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

                cash_sales = (
                    report.cash_sales
                    if report
                    else (report_draft.cash_sales if report_draft else 0)
                )
                cash_sale_settings = get_entity_account_settings(entity_id, "cash_sale")
                cash_sale_account_code = (
                    cash_sale_settings["account_code"]
                    if cash_sale_settings and "account_code" in cash_sale_settings
                    else ""
                )

                if cash_sales and cash_sales > 0:
                    all_rows.append(
                        {
                            "Date": (
                                transaction_date.strftime("%Y-%m-%d")
                                if transaction_date
                                else "N/A"
                            ),
                            "Account Code": cash_sale_account_code or "",
                            "Amount": cash_sales,
                            "Description": "Cash Sale (Pettycash)",
                            "Reference": " ",
                            "Check Number": " ",
                        }
                    )

                bank_deposit = (
                    report.bank_deposit
                    if report
                    else (report_draft.bank_deposit if report_draft else 0)
                )
                if bank_deposit and bank_deposit > 0:
                    all_rows.append(
                        {
                            "Date": (
                                transaction_date.strftime("%Y-%m-%d")
                                if transaction_date
                                else "N/A"
                            ),
                            "Account Code": main_bank_account or "",
                            "Amount": -bank_deposit,
                            "Description": "Bank Deposit",
                            "Reference": " ",
                            "Check Number": " ",
                        }
                    )

                discrepancy_amount = (
                    report.discrepancy_amount
                    if report
                    else (report_draft.discrepancy_amount if report_draft else 0)
                )
                discrepancy_type = (
                    report.discrepancy_type
                    if report
                    else (report_draft.discrepancy_type if report_draft else "none")
                )

                if (
                    discrepancy_type
                    and discrepancy_type != "none"
                    and discrepancy_amount
                    and discrepancy_amount != 0
                ):
                    discrepancy_value = (
                        -abs(discrepancy_amount)
                        if discrepancy_type == "shortage"
                        else abs(discrepancy_amount)
                    )
                    all_rows.append(
                        {
                            "Date": (
                                transaction_date.strftime("%Y-%m-%d")
                                if transaction_date
                                else "N/A"
                            ),
                            "Account Code": discrepancy_account_code or "",
                            "Amount": discrepancy_value,
                            "Description": f"Discrepancy ({discrepancy_type})",
                            "Reference": " ",
                            "Check Number": " ",
                        }
                    )

            if not all_rows:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "No data to export in the specified date range.",
                        }
                    ),
                    404,
                )

            df = pd.DataFrame(
                all_rows,
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
            df.to_csv(output, index=False)
            output.seek(0)
            response = make_response(output.read())
            response.headers["Content-Disposition"] = (
                f"attachment; filename=reports_{start_date}_to_{end_date}.csv"
            )
            response.headers["Content-type"] = "text/csv"
            return response

    except Exception as e:
        logger.error(f"Error downloading CSV reports: {e}")
        import traceback

        traceback.print_exc()
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while building that CSV. Mind trying again?",
                }
            ),
            500,
        )


def has_route(route_name):
    return route_name in app.view_functions
