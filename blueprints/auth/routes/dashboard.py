from flask import redirect, render_template, request
from flask_login import current_user, login_required

from blueprints.auth import auth_bp
from blueprints.report.services.shared import get_cash_sales_from_detail
from models.db import Report
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@auth_bp.route("/index")
@login_required
def index():
    entity_id = request.args.get("entity_id")
    if not entity_id:
        return redirect("/entity")

    if not has_permission(current_user, Permission.ENTITY_VIEW, entity_id):
        return permission_denied(
            "You do not have permission to view this entity.",
            entity_id=entity_id,
        )

    reports = (
        Report.query.filter_by(company=entity_id).order_by(Report.date.desc()).all()
    )

    cumulative_shop_sales = 0.0
    cumulative_delivery_sales = 0.0
    cumulative_expenses = 0.0

    for report in reports:
        try:
            total_shop_sales = report.shop_sales or 0.0
            total_delivery_sales = report.delivery_sales or 0.0
            total_expenses = sum(expense.amount for expense in report.shop_expenses)
            adjusted_opening_balance = report.opening_balance + (
                report.cash_addition or 0.0
            )
            cash_sales = get_cash_sales_from_detail(
                report.id,
                fallback_value=report.cash_sales or 0.0,
            )
            closing_balance = (
                report.opening_balance
                + (report.cash_addition or 0)
                + cash_sales
                - total_expenses
                - (report.bank_deposit or 0)
            )

            cumulative_shop_sales += total_shop_sales
            cumulative_delivery_sales += total_delivery_sales
            cumulative_expenses += total_expenses

            report.__dict__.update(
                {
                    "adjusted_opening_balance": adjusted_opening_balance,
                    "total_shop_sales": total_shop_sales,
                    "total_delivery_sales": total_delivery_sales,
                    "total_sales": total_shop_sales + total_delivery_sales,
                    "total_expenses": total_expenses,
                    "closing_balance": closing_balance,
                }
            )
        except Exception:
            report.__dict__.update(
                {
                    "adjusted_opening_balance": 0.0,
                    "total_shop_sales": 0.0,
                    "total_delivery_sales": 0.0,
                    "total_sales": 0.0,
                    "total_expenses": 0.0,
                }
            )

    most_recent_report = reports[0] if reports else None

    return render_template(
        "report_list.html",
        reports=reports,
        cumulative_shop_sales=cumulative_shop_sales,
        cumulative_delivery_sales=cumulative_delivery_sales,
        cumulative_expenses=cumulative_expenses,
        most_recent_report=most_recent_report,
        user=current_user,
        entity_id=entity_id,
    )
