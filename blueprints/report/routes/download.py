# Report download routes: file (S3), statements, attachments ZIP, CSV export.
# Report download: file (S3 presigned), report Excel, statements,
# attachments ZIP, CSV export. Logic moved from app.
import mimetypes
import os
import uuid
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Any, cast

import pandas as pd
from flask import (jsonify, make_response, redirect, render_template, request,
                   send_file)
from flask_login import current_user, login_required
from services.app_runtime.log import logger

from blueprints.report import report_bp
from blueprints.report.services import report_csv
from blueprints.report.services.shared import split_receipt_keys
from blueprints.report.services.s3_storage import get_s3_bucket, get_s3_client
from blueprints.shared.enums import ReportStatus
from blueprints.report.models.shop_expense import (Attachment, ReportExpense,
                                                    ReportExpenseAttachment)
from models.db import Report, db
from services.permission_policy import can_view_report, is_superuser


def _superuser_only() -> Any:
    """None for a superuser, else a logged 403. The statement and attachment exports
    span EVERY company, so only a superuser may run them."""
    if is_superuser(current_user):
        return None
    logger.warning(f"all-company export refused for user {current_user.id}")
    return jsonify({"status": "error", "message": "Hmm, I can't let you in there."}), 403


def _report_owning_key(s3_key: str) -> Report | None:
    """The report a receipt key belongs to, or None.

    An expense line's attachment row says it directly. A file uploaded but not yet on a
    line has no row, but every key Minty writes is ``expenses/<report_id>/...``
    (``s3_storage.upload_file_to_s3`` and ``api.expense_upload_files``).
    """
    report_id = (
        db.session.query(ReportExpense.report_id)
        .join(ReportExpenseAttachment, ReportExpenseAttachment.report_expense_id == ReportExpense.id)
        .join(Attachment, Attachment.id == ReportExpenseAttachment.attachment_id)
        .filter(Attachment.file_path == s3_key)
        .limit(1)
        .scalar()
    )
    if report_id is None:
        parts = s3_key.split("/")
        if len(parts) < 3 or parts[0] != "expenses":
            return None
        try:
            report_id = str(uuid.UUID(parts[1]))
        except ValueError:
            return None
    return db.session.get(Report, report_id)


def _receipt_refusal(filename: str, what: str) -> Any:
    """None when ``filename`` is a receipt of a report this user may see, else the logged
    404 / 403. Every receipt route asks this first: ``/download`` used to sign ANY key for any
    signed-in user (other companies' receipts)."""
    report = _report_owning_key(filename)
    if report is None:
        logger.warning(f"{what} refused: no report owns key {filename!r} (user {current_user.id})")
        return jsonify({"status": "error", "message": "I couldn't find that file."}), 404
    if not can_view_report(current_user, report):
        logger.warning(f"{what} refused: user {current_user.id} may not view report {report.id}")
        return jsonify({"status": "error", "message": "Hmm, it looks like you don't have permission to look there."}), 403
    return None


@report_bp.route("/download/<path:filename>", methods=["GET"])
@login_required
def download_file(filename):
    # Hands out a presigned S3 link, so it must be a receipt of a report this user may see.
    refusal = _receipt_refusal(filename, "download")
    if refusal is not None:
        return refusal
    try:
        bucket = get_s3_bucket()
        s3_client = get_s3_client()

        logger.info(f"Attempting to download file: {filename} from S3 bucket {bucket}")
        s3_key = filename
        download_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": s3_key}, ExpiresIn=3600
        )
        return redirect(download_url)
    except Exception:
        # A failure here is a server-side fault (S3 unreachable, bad creds), not
        # a missing file — 404 misreported it as "not found".
        logger.exception(f"Error generating pre-signed URL for {filename}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't open that report. Mind trying again?",
                }
            ),
            500,
        )


#: The upload limit (expense.html, ``api.expense_upload_files``): nothing larger is a receipt.
RECEIPT_PREVIEW_MAX_BYTES = 10 * 1024 * 1024


@report_bp.route("/preview/<path:filename>", methods=["GET"])
@login_required
def preview_file(filename):
    """A receipt's bytes from this origin, for the Expenses step's preview (2026-10-05).

    ``/download`` redirects to a presigned Backblaze link: fine for ``<img>``, but pdf.js
    ``fetch``es a PDF, and the bucket's CORS rules are not ours to rely on. Same checks as
    ``/download``; shown inline, never larger than an upload may be.
    """
    refusal = _receipt_refusal(filename, "preview")
    if refusal is not None:
        return refusal
    try:
        obj = get_s3_client().get_object(Bucket=get_s3_bucket(), Key=filename)
        size = obj.get("ContentLength")
        if size is not None and size > RECEIPT_PREVIEW_MAX_BYTES:
            logger.warning(f"preview refused: {filename!r} is {size} bytes")
            return jsonify({"status": "error", "message": "That file is too big to preview here."}), 413
        body = obj["Body"].read(RECEIPT_PREVIEW_MAX_BYTES + 1)
    except Exception:
        logger.exception(f"Error reading {filename} for preview")
        return jsonify({"status": "error", "message": "I couldn't open that file. Mind trying again?"}), 500
    if len(body) > RECEIPT_PREVIEW_MAX_BYTES:
        logger.warning(f"preview refused: {filename!r} is over {RECEIPT_PREVIEW_MAX_BYTES} bytes")
        return jsonify({"status": "error", "message": "That file is too big to preview here."}), 413
    content_type = obj.get("ContentType") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    resp = make_response(body)
    resp.headers["Content-Type"] = content_type
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@report_bp.route("/admin/download_statements", methods=["GET", "POST"])
@login_required
def download_statements():
    denied = _superuser_only()
    if denied:
        return denied
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

            # Exports cover SUBMITTED reports. Since Stage 4a `report` also
            # holds draft-shaped rows (status='draft'), so without this an
            # in-progress draft lands in the downloaded file.
            query = Report.query.filter(db.or_(Report.status.is_(None), Report.status != "draft"))
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

    return jsonify({"status": "error", "message": "Invalid request method"}), 405


@report_bp.route("/download_attachments", methods=["POST"])
@login_required
def download_attachments():
    denied = _superuser_only()
    if denied:
        return denied
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

        # Submitted reports only — see the note on the single-report export.
        query = Report.query.filter(
            Report.transaction_date >= start_date,
            Report.transaction_date <= end_date,
            db.or_(Report.status.is_(None), Report.status != "draft"),
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
                        for file_path in split_receipt_keys(expense.files):
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


#: The Jinja export's sentence for each refused range (report_csv.parse_range's reasons).
_RANGE_REFUSALS = {
    "missing": "I need both a start and an end date to do that.",
    "format": "That date doesn't look quite right — could you use YYYY-MM-DD?",
    "order": "Your start date lands after your end date — could you flip them around?",
    "too_long": f"That range is longer than a year — could you choose {report_csv.MAX_DAYS} days or fewer?",
}


def _csv_error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


def _csv_file(body: bytes, filename: str):
    response = make_response(body)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/download-csv", methods=["GET"])
@login_required
def download_reports_csv(entity_id):
    """History's Export CSV (``report/services/report_csv.py``): a date range, or one report by
    ``report_id``. Submitted and published reports only."""
    from blueprints.report.services.shared import check_user_has_entities

    if not check_user_has_entities(current_user.id):
        return _csv_error("You need to create an entity first before accessing reports.", 403)
    if not report_csv.may_export(current_user, entity_id):
        return _csv_error("You do not have access to this entity.", 403)

    report_id = request.args.get("report_id")
    if report_id:
        try:
            report = db.session.get(Report, str(uuid.UUID(report_id)))
        except ValueError:
            report = None
        # this company's submitted report, and one this person may see
        if report is None or str(report.company) != str(entity_id) or report.status == ReportStatus.DRAFT:
            return _csv_error("I can only download submitted or published reports as CSV.", 404)
        if not can_view_report(current_user, report):
            return _csv_error("You do not have access to this report.", 403)
        rows = report_csv.movements(entity_id, [report])
        if not rows:
            return _csv_error("No data to export for this report.", 404)
        return _csv_file(report_csv.to_csv(rows), f"report_{report.id}.csv")

    try:
        first, last = report_csv.parse_range(request.args.get("start_date"), request.args.get("end_date"))
    except report_csv.RangeRefused as refused:
        return _csv_error(_RANGE_REFUSALS[refused.reason], 400)
    reports = report_csv.submitted_reports(entity_id, first, last)
    if not reports:
        return _csv_error("No reports found in the specified date range.", 404)
    rows = report_csv.movements(entity_id, reports)
    if not rows:
        return _csv_error("No data to export in the specified date range.", 404)
    return _csv_file(report_csv.to_csv(rows), report_csv.range_filename(first, last))
