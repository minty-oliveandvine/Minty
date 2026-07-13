from io import BytesIO
from typing import Any, cast

import pandas as pd
from flask import flash, jsonify, make_response, redirect, url_for
from flask_login import current_user
from loguru import logger

from models.db import AccountInfo, EntityAccountXero, Report, ShopExpense, db
from services.helpers.xero_bridge import get_entity_account_settings


def download_report(id):
    try:
        if not current_user.is_authenticated:
            flash("Your session ran out. Mind logging back in?", "warning")
            return redirect(url_for("auth.login"))

        report = (
            Report.query.join(ShopExpense, isouter=True).filter(Report.id == id).first()
        )
        if not report:
            return jsonify({"status": "error", "message": "Report not found."}), 404

        entity_id = report.company
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
                    {"status": "error", "message": "Failed to generate Excel file"}
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
                        "message": "Failed to generate download response",
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
                    "message": f"Error generating the Excel report: {str(e)}",
                }
            ),
            500,
        )
