from datetime import datetime

from flask import redirect
from flask.typing import ResponseReturnValue
from services.app_runtime.log import logger

from blueprints.report import report_bp
from blueprints.report.services.shared import safe_float
from blueprints.xero.services.publish import (update_after_deposit_change,
                                              update_xero_deposit_after_change)
from models.db import Entity, Report, ShareLink, db  # noqa: F401  (tests patch these here)
from services.helpers.xero_bridge import get_entity_account_settings


@report_bp.route("/Minty_Report/<path:entity_and_date>/", methods=["GET"])
def minty_report_share(entity_and_date: str) -> ResponseReturnValue:
    """An old share link, ``Minty_Report/{initials}/{date}/{secret}/``: the page is
    minty-petty-cash-web's ``/share/{path}`` (Flask's went 2026-10-20), which reads the link
    through the public share API and refuses an unknown or expired one itself."""
    from blueprints.shared import bearer_api

    return redirect(f"{bearer_api.petty_cash_web_origin()}/share/{entity_and_date.strip('/')}", code=308)


def correct_previous_deposit(entity_id: str, form_data: dict) -> tuple[dict, int]:
    """The dashboard's "Before You Start" correction of the previous day's bank deposit:
    ``(payload, status)``. Called by the internal route ``/api/internal/xero/deposit-correction``
    (blueprints/petty_cash_api's ``correct_deposit``); the caller has already checked
    ``REPORT_EDIT_ENTITY``. Kept in this module so the names its tests patch here still apply."""
    try:
        logger.info(
            f"check_dept_bank_yest_module - Received data: {form_data}")
        amount = safe_float(form_data.get("amount", 0))
        bank_account = form_data.get("bankAccount")
        date = form_data.get("date")
        kind = (form_data.get("kind") or "").strip().lower()
        logger.info(
            f"check_dept_bank_yest_module - Parsed: amount={amount}, bank_account={bank_account}, date={date}, kind={kind}"
        )
        report_date = datetime.strptime(date, "%Y-%m-%d").date()

        report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == report_date,
        ).first()
        if report is None:
            update_after_deposit_change(entity_id, date, amount)
            return (
                {
                    "status": "warning",
                    "message": "No previous report found to update.",
                },
                200,
            )

        previous_deposit = report.bank_deposit or 0.0
        is_published = report.publishing_status == "completed"

        # Hard-stop: cannot reconcile a deposit correction (local or Xero) when
        # the entity's deposit-bank / petty-cash mappings are missing. Same
        # condition that surfaces "Unknown Bank (****)" in the dashboard modal.
        if previous_deposit > 0:
            bank_settings = get_entity_account_settings(entity_id, "bank")
            pettycash_settings = get_entity_account_settings(entity_id, "pettycash")
            missing = []
            if not bank_settings:
                missing.append("Deposit Bank Account")
            if not pettycash_settings:
                missing.append("Petty Cash Account")
            if missing:
                return (
                    {
                        "status": "error",
                        "message": (
                            "Cannot change or remove this deposit because the "
                            f"following entity setting(s) are not configured: "
                            f"{', '.join(missing)}. Configure them in "
                            "Settings → Petty Cash before correcting this deposit."
                        ),
                        "missing_settings": missing,
                    },
                    409,
                )

        if amount > previous_deposit:
            return (
                {
                    "status": "error",
                    "message": "That deposit is larger than the previous one — could you double-check the amount?",
                },
                400,
            )

        updated_report = update_after_deposit_change(entity_id, date, amount) or report

        logger.info(
            f"Updated report {updated_report.id} bank deposit from {previous_deposit} to {amount}"
        )

        xero_status = "skipped"
        xero_message = None
        if is_published and previous_deposit > 0:
            try:
                xero_ok, xero_detail = update_xero_deposit_after_change(
                    entity_id,
                    date,
                    previous_deposit,
                    amount,
                    report_id=updated_report.id,
                )
                xero_status = "success" if xero_ok else "failed"
                if not xero_ok:
                    xero_message = xero_detail or (
                        "Database updated but Xero deposit could not be "
                        "reversed/updated. Please verify in Xero."
                    )
            except Exception as xero_exc:
                logger.error(
                    f"Xero deposit reconciliation failed: {str(xero_exc)}"
                )
                xero_status = "failed"
                xero_message = (
                    f"Database updated but Xero update raised an error: {xero_exc}"
                )

        response_status = "success"
        response_message = "Previous day's deposit updated successfully."
        if xero_status == "failed":
            response_status = "warning"
            response_message = (
                f"Local report updated, but Xero sync failed: {xero_message}"
                if xero_message
                else "Local report updated, but Xero sync failed."
            )

        return (
            {
                "status": response_status,
                "message": response_message,
                "id": updated_report.id,
                "previous_deposit": previous_deposit,
                "bank_deposit": amount,
                "closing_balance": updated_report.closing_balance,
                "is_published": is_published,
                "xero_status": xero_status,
            },
            200,
        )
    except Exception:
        # Fail-safe fallback: keep behavior from legacy implementation
        logger.exception("Error processing check_dept_bank_yest_module")
        return (
            {
                "status": "error",
                "message": "Something went wrong on my end while checking that deposit. Mind trying again?",
            },
            500,
        )
