import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import current_app as app
from flask import flash, jsonify, redirect, request, url_for
from flask.typing import ResponseReturnValue
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.shared import safe_float
from blueprints.xero.services.publish import (update_after_deposit_change,
                                              update_xero_deposit_after_change)
from models.db import Entity, Report, ShareLink, db, tz
from services.helpers.xero_bridge import get_entity_account_settings
from utils import verify_share_token


@report_bp.route("/Minty_Report/<path:entity_and_date>/", methods=["GET"])
def minty_report_share(entity_and_date: str) -> ResponseReturnValue:
    """Handle shared links with clean format: Minty_Report/EntityName/09_Jan_2026/."""
    try:
        from blueprints.report.services.ending import \
            report_ending as render_report_ending

        # Look up token from database using path segment
        share_link = ShareLink.query.filter_by(
            path_segment=entity_and_date).first()

        if not share_link:
            flash("Hmm, I couldn't find that share link.", "danger")
            return redirect(url_for("entity.entity_list"))

        # Check if expired
        if datetime.now() > share_link.expires_at:
            flash("This link has expired. Could you ask for a fresh one?", "warning")
            db.session.delete(share_link)
            db.session.commit()
            return redirect(url_for("entity.entity_list"))

        # Verify token
        secret_key = app.config.get("SECRET_KEY")
        if not secret_key:
            flash("Something's not set up right on my end. Could you let us know?", "danger")
            return redirect(url_for("entity.entity_list"))

        is_valid, params = verify_share_token(share_link.token, secret_key)
        if not is_valid or not params:
            flash("This link doesn't work anymore. Could you ask for a fresh one?", "danger")
            db.session.delete(share_link)
            db.session.commit()
            return redirect(url_for("entity.entity_list"))

        # Extract params from token
        token_entity_id = params.get("entity_id")
        token_transaction_date = params.get("transaction_date")
        if not token_entity_id or not token_transaction_date:
            flash("This link doesn't look right to me.", "danger")
            return redirect(url_for("entity.entity_list"))

        # Verify entity_id matches
        if token_entity_id != share_link.entity_id:
            flash("This link doesn't look right to me.", "danger")
            return redirect(url_for("entity.entity_list"))

        # Get the entity
        org = Entity.query.get(token_entity_id)
        if not org:
            flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
            return redirect(url_for("entity.entity_list"))

        # Find the report for the transaction_date from token
        report_date = datetime.strptime(
            token_transaction_date, "%Y-%m-%d").date()
        specific_report = Report.query.filter(
            # Share-link target: SUBMITTED reports only, never a draft.
            db.or_(Report.status.is_(None), Report.status != "draft"),
            Report.company == str(token_entity_id),
            Report.transaction_date == report_date,
        ).first()

        if specific_report:
            # Render ending page without login requirement
            return render_report_ending(
                id=specific_report.id,
                entity_id=token_entity_id,
                skip_auth=True)
        else:
            flash(f"I couldn't find a report for {token_transaction_date}.", "warning")
            return redirect(url_for("entity.entity_list"))

    except Exception as e:
        logger.error(f"Error processing share link: {str(e)}")
        flash("This link doesn't look right to me.", "danger")
        return redirect(url_for("entity.entity_list"))
    return redirect(url_for("entity.entity_list"))


@report_bp.route("/Minty_Report_<path:entity_and_date>/ending",
                 methods=["GET"])
def minty_report_ending(entity_and_date: str) -> ResponseReturnValue:
    """Handle shared links with readable format: Minty_Report_EntityName_dd_mm_yyyy."""
    from blueprints.report.services.ending import \
        report_ending as render_report_ending

    token = request.args.get("token")
    if not token:
        flash("This link doesn't look right to me.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Verify token
    secret_key = app.config.get("SECRET_KEY")
    if not secret_key:
        flash("Something's not set up right on my end. Could you let us know?", "danger")
        return redirect(url_for("entity.entity_list"))

    is_valid, params = verify_share_token(token, secret_key)
    if not is_valid or not params:
        flash("This link doesn't work anymore. Could you ask for a fresh one?", "danger")
        return redirect(url_for("entity.entity_list"))

    # Extract params from token (use token data, not URL data for security)
    token_entity_id = params.get("entity_id")
    token_transaction_date = params.get("transaction_date")
    if not token_entity_id or not token_transaction_date:
        flash("This link doesn't look right to me.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Get the entity by ID from token (for security, we verify using token
    # data)
    org = Entity.query.get(token_entity_id)
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Find the report for the transaction_date from token
    try:
        report_date = datetime.strptime(
            token_transaction_date, "%Y-%m-%d").date()
        specific_report = Report.query.filter(
            # Share-link target: SUBMITTED reports only.
            db.or_(Report.status.is_(None), Report.status != "draft"),
            Report.company == str(token_entity_id),
            Report.transaction_date == report_date,
        ).first()

        if specific_report:
            # Render ending page without login requirement
            return render_report_ending(
                id=specific_report.id,
                entity_id=token_entity_id,
                skip_auth=True)
        else:
            flash(f"I couldn't find a report for {token_transaction_date}.", "warning")
            return redirect(url_for("entity.entity_list"))
    except ValueError:
        flash("There's something wrong with the date in this link.", "warning")
        return redirect(url_for("entity.entity_list"))
    return redirect(url_for("entity.entity_list"))


@report_bp.route("/insert_xero_transaction", methods=["GET"])
def report_insert_xero_transaction() -> Any:
    from models.db import XeroBankTransaction

    xero_bank_transaction = XeroBankTransaction(
        id=str(uuid.uuid4()),
        sync_report_id="11111111-1111-1111-1111-111111111111",
        type="Spend",
        xero_contact_id="22222222-2222-2222-2222-222222222222",
        xero_contact_name="ABC Supplies Co.",
        unit_amount=1500.0,
        quantity=1.0,
        xero_account_id="33333333-3333-3333-3333-333333333333",
        xero_account_code="200",
        description="Expense Report for 2025-11-14",
        xero_bank_account_id="44444444-4444-4444-4444-444444444444",
        xero_bank_transaction_id="55555555-5555-5555-5555-555555555555",
        subtotal=1500.0,
        total_tax=0.0,
        total=1500.0,
        status="AUTHORISED",
        created_at=datetime.now(tz),
    )

    # Insert into database
    db.session.add(xero_bank_transaction)
    db.session.commit()
    return jsonify({"status": "success",
                    "message": "Xero transaction inserted successfully."})


@report_bp.route(
    "/api/check-dept-bank-yest/<string:entity_id>", methods=["GET", "POST"]
)
def report_check_dept_bank_yest(entity_id: str) -> Any:
    try:
        form_data = request.get_json() or {}
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
        redirect_date = report_date + timedelta(days=1)
        redirect_date = redirect_date.strftime("%Y-%m-%d")

        report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == report_date,
        ).first()
        if report is None:
            update_after_deposit_change(entity_id, date, amount)
            response = jsonify(
                {
                    "status": "warning",
                    "message": "No previous report found to update.",
                    "redirect_url": f"/report/opening?entity_id={entity_id}&transaction_date={redirect_date}",
                }
            )
            response.status_code = 200
            return response

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
                response = jsonify(
                    {
                        "status": "error",
                        "message": (
                            "Cannot change or remove this deposit because the "
                            f"following entity setting(s) are not configured: "
                            f"{', '.join(missing)}. Configure them in "
                            "Settings → Petty Cash before correcting this deposit."
                        ),
                        "missing_settings": missing,
                    }
                )
                response.status_code = 409
                return response

        if amount > previous_deposit:
            response = jsonify(
                {
                    "status": "error",
                    "message": "That deposit is larger than the previous one — could you double-check the amount?",
                }
            )
            response.status_code = 400
            return response

        updated_report = update_after_deposit_change(entity_id, date, amount) or report

        logger.info(
            f"Updated report {updated_report.id} bank deposit from {previous_deposit} to {amount}"
        )
        logger.info(f"Redirect date: {redirect_date}")

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

        response = jsonify(
            {
                "status": response_status,
                "message": response_message,
                "id": updated_report.id,
                "previous_deposit": previous_deposit,
                "bank_deposit": amount,
                "closing_balance": updated_report.closing_balance,
                "is_published": is_published,
                "xero_status": xero_status,
                "redirect_url": f"/report/opening?entity_id={entity_id}&transaction_date={redirect_date}",
            }
        )
        response.status_code = 200
        return response
    except Exception:
        # Fail-safe fallback: keep behavior from legacy implementation
        logger.error("Error processing check_dept_bank_yest_module")
        response = jsonify(
            {
                "status": "error",
                "message": "Something went wrong on my end while checking that deposit. Mind trying again?",
            }
        )
        response.status_code = 500
        return response
