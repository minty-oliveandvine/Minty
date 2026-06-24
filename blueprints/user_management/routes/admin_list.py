# Admin report list and client logs. Delegate to app.


import json
from datetime import datetime
from typing import Any, cast

from flask import jsonify, redirect, render_template, request
from flask_login import current_user, login_required
from loguru import logger

from blueprints.user_management import user_management_bp
from models.db import Report


@user_management_bp.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    user = cast(Any, current_user)
    if getattr(user, "system_role", None) != "superuser":
        logger.warning(
            "Unauthorized admin access attempt by user_id=%s",
            getattr(user, "id", None),
        )
        from flask import flash, url_for

        flash("Not authorized", "danger")
        return redirect(url_for("auth.index"))

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    company = request.args.get("company")
    uploaded_by = request.args.get("uploaded_by")
    expenses = request.args.get("expenses")
    sales = request.args.get("sales")

    query = Report.query

    if start_date:
        query = query.filter(
            Report.transaction_date >= datetime.strptime(
                start_date, "%Y-%m-%d").date())
    if end_date:
        query = query.filter(
            Report.transaction_date <= datetime.strptime(
                end_date, "%Y-%m-%d").date())
    if company:
        query = query.filter(Report.company == company)
    if uploaded_by:
        query = query.filter(Report.uploaded_by == uploaded_by)

    if expenses:
        try:
            expenses_val = float(expenses)
            query = query.filter(
                Report.expenses.between(expenses_val * 0.9, expenses_val * 1.1)
            )
        except ValueError:
            pass

    if sales:
        try:
            sales_val = float(sales)
            query = query.filter(
                Report.total_sales.between(sales_val * 0.9, sales_val * 1.1)
            )
        except ValueError:
            pass

    reports = query.order_by(Report.date.desc()).all()

    cumulative_shop_sales_by_company = {}
    cumulative_delivery_sales_by_company = {}
    cumulative_total_sales_by_company = {}
    cumulative_expenses_by_company = {}

    for report in reports:
        company_id = report.company
        cumulative_shop_sales_by_company[company_id] = (
            cumulative_shop_sales_by_company.get(company_id, 0)
            + (report.shop_sales or 0)
        )
        cumulative_delivery_sales_by_company[company_id] = (
            cumulative_delivery_sales_by_company.get(company_id, 0)
            + (report.delivery_sales or 0)
        )
        cumulative_total_sales_by_company[company_id] = (
            cumulative_total_sales_by_company.get(company_id, 0)
            + (report.total_sales or 0)
        )
        cumulative_expenses_by_company[company_id] = cumulative_expenses_by_company.get(
            company_id, 0) + (report.expenses or 0)

    from flask import flash

    return render_template(
        "admin.html",
        reports=reports,
        cumulative_shop_sales_by_company=cumulative_shop_sales_by_company,
        cumulative_delivery_sales_by_company=cumulative_delivery_sales_by_company,
        cumulative_total_sales_by_company=cumulative_total_sales_by_company,
        cumulative_expenses_by_company=cumulative_expenses_by_company,
        super_admin=(getattr(user, "system_role", None) == "superuser"),
    )


@user_management_bp.route("/api/client-logs", methods=["POST"])
@login_required
def client_logs():
    """Receive frontend log payload and persist to server log."""
    try:
        data = request.json or {}
        level = data.get("level", "info").upper()
        message = data.get("message", "")
        extra = data.get("extra", {})
        url = data.get("url", "")
        user_agent = data.get("userAgent", "")
        timestamp = data.get("timestamp", "")
        user = cast(Any, current_user)
        user_id = user.id if user.is_authenticated else None
        username = (
            user.username if user.is_authenticated else "anonymous")

        log_message = f"FRONTEND [{level}] {message}"
        if url:
            log_message += f" | URL: {url}"
        if username:
            log_message += f" | User: {username} (ID: {user_id})"
        if user_agent:
            log_message += f" | UA: {user_agent[:100]}"
        if timestamp:
            log_message += f" | Time: {timestamp}"
        if extra:
            log_message += f" | Extra: {json.dumps(extra)}"

        if level == "ERROR":
            logger.error(log_message)
        elif level == "WARN":
            logger.warning(log_message)
        else:
            logger.info(log_message)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error("Failed to process client log: %s", str(e))
        return jsonify({"status": "error"}), 500
