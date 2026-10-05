from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app as app
from flask import flash, jsonify, redirect, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.shared import safe_float
from blueprints.xero.services.publish import (update_after_deposit_change,
                                              update_xero_deposit_after_change)
from models.db import Entity, Report, ShareLink, db
from services.authz import require_entity_access, require_permission
from services.helpers.xero_bridge import get_entity_account_settings
from services.permission_policy import Permission
from utils import verify_share_token


@report_bp.route("/Minty_Report/<path:entity_and_date>/", methods=["GET"])
def minty_report_share(entity_and_date: str) -> ResponseReturnValue:
    """Public share link: Minty_Report/{initials}/{date}/{secret}/.

    Only the full path, secret included, finds a link. The old two-part form had no
    secret and could be guessed, so it is refused even while its row still exists.
    """
    try:
        from blueprints.report.services.ending import \
            report_ending as render_report_ending
        from blueprints.report.services.share import is_share_path

        if not is_share_path(entity_and_date):
            logger.warning(
                f"share link refused: malformed or old-form path, from {request.remote_addr}")
            flash("This link doesn't work anymore. Could you ask for a fresh one?", "danger")
            return redirect(url_for("entity.entity_list"))

        share_link = ShareLink.query.filter_by(
            path_segment=entity_and_date.strip("/")).first()

        if not share_link:
            logger.warning(f"share link refused: unknown secret, from {request.remote_addr}")
            flash("Hmm, I couldn't find that share link.", "danger")
            return redirect(url_for("entity.entity_list"))

        # expires_at is TIMESTAMPTZ; a naive value (a hand-made row) is local time.
        expires_at = share_link.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.astimezone()
        if datetime.now(timezone.utc) > expires_at:
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

        # The signed token must name the same company and day as the row.
        if (str(token_entity_id) != str(share_link.entity_id)
                or str(token_transaction_date) != str(share_link.transaction_date)):
            logger.warning(f"share link refused: token does not match link {share_link.id}")
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
            logger.info(
                f"share link opened: link={share_link.id} entity={token_entity_id} "
                f"date={token_transaction_date} from {request.remote_addr}")
            # Render ending page without login requirement
            return render_report_ending(
                id=specific_report.id,
                entity_id=token_entity_id,
                skip_auth=True)
        else:
            flash(f"I couldn't find a report for {token_transaction_date}.", "warning")
            return redirect(url_for("entity.entity_list"))

    except Exception:
        # logger.exception keeps the traceback: a crash here once hid that every
        # link failed on Postgres (naive vs aware expires_at).
        logger.exception("Error processing share link")
        flash("This link doesn't look right to me.", "danger")
        return redirect(url_for("entity.entity_list"))
    return redirect(url_for("entity.entity_list"))


@report_bp.route("/api/check-dept-bank-yest/<string:entity_id>", methods=["POST"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(Permission.REPORT_EDIT_ENTITY, entity_arg="entity_id")
def report_check_dept_bank_yest(entity_id: str) -> Any:
    # Rewrites a report's bank deposit and pushes the change to Xero, so it needs a
    # signed-in member allowed to edit this company's reports. It used to take GET
    # and no login at all.
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
