# Report-related API routes: expense create_contact, submit_all, delete;
# get_draft_totals; publish_to_xero; publishing_status;
# multi-file upload (upload_files, draft detail CRUD, validate_drafts).
import io
import json
import os
import uuid
from datetime import datetime

from flask import jsonify, request, url_for
from flask_login import current_user, login_required
from loguru import logger
from werkzeug.utils import secure_filename

from blueprints.report import report_bp
from blueprints.report.services.file_downsize import downsize_bytes
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.s3_storage import get_s3_bucket, get_s3_client
from blueprints.report.services.share import create_share_link_for_report
from blueprints.report.services.shared import get_cash_sales_from_detail
from blueprints.xero.services.publish_errors import latest_publish_reason_items
from blueprints.xero.services.publish_resolution import annotate_resolution
from models.db import (Entity, Report, ReportDraft, ReportHistory, ShopExpense,
                       ShopExpenseDraft, UserEntity, db)
from services.auth.token_service import (auto_refresh_token,
                                         ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.permission_policy import Permission, has_permission


def _can_view_report_draft(draft) -> bool:
    if not draft:
        return False
    entity_id = draft.company
    if (
        draft.uploaded_by == current_user.username
        and has_permission(current_user, Permission.REPORT_VIEW_OWN, entity_id)
    ):
        return True
    return has_permission(current_user, Permission.REPORT_VIEW_ENTITY, entity_id)


@report_bp.route("/report/expense/create_contact", methods=["POST"])
@login_required
def report_expense_create_contact():
    logger.info("=== CREATE CONTACT ENDPOINT REACHED ===")
    try:
        logger.info("Request method: %s", request.method)
        logger.info("Request content type: %s", request.content_type)
        logger.info("Request headers: %s", dict(request.headers))

        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify(
                {"status": "error", "message": "Request must be JSON"}), 400

        data = request.json
        logger.info("Creating contact with data: %s", data)

        if not data:
            logger.error("No data received in request")
            return jsonify(
                {"status": "error", "message": "No data received"}), 400

        entity_id = (
            data.get("entity_id")
            or request.args.get("entity_id")
            or request.form.get("entity_id")
        )
        if not entity_id:
            return (
                jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}),
                400,
            )
        if not has_permission(current_user, Permission.CONTACT_CREATE, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to create contacts for this entity.",
                    }
                ),
                403,
            )

        entity = Entity.query.get(entity_id)
        if not entity or not entity.xero_org_id:
            logger.error("No Xero org ID found for entity %s", entity_id)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "I can't add contacts yet — this entity isn't connected to Xero. Could an admin reconnect it?",
                    }),
                400,
            )

        xero_user = get_xero_token_user_for_entity(entity_id)
        logger.info("Xero token user: %s", xero_user.id if xero_user else None)
        if not xero_user or not xero_user.access_token:
            logger.error("No Xero access token found for entity")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "I can't add contacts yet — this entity isn't connected to Xero. Could an admin reconnect it?",
                    }),
                400,
            )

        if not ensure_valid_token(xero_user):
            logger.error("Failed to ensure valid token for entity xero user")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Xero wouldn't let me in. Could you ask an admin to reconnect it?",
                    }),
                400,
            )

        endpoint = "https://api.xero.com/api.xro/2.0/Contacts"

        logger.info("Making request to Xero for entity: %s", entity_id)
        logger.info("Request data: %s", data)

        import requests as _requests

        def _make_xero_request():
            return _requests.post(endpoint, headers={
                "Authorization": "Bearer " + xero_user.access_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Xero-Tenant-Id": str(entity.xero_org_id),
            }, json=data)

        xero_response = _make_xero_request()
        logger.info("Xero response status: %s", xero_response.status_code)
        logger.info("Xero response text: %s", xero_response.text)

        if xero_response.status_code in (401, 403):
            logger.warning("Xero returned %s, forcing token refresh and retrying",
                           xero_response.status_code)
            if auto_refresh_token(xero_user):
                xero_response = _make_xero_request()
                logger.info("Retry Xero response status: %s", xero_response.status_code)
                logger.info("Retry Xero response text: %s", xero_response.text)

        if xero_response.status_code not in (200, 201):
            # Xero's raw response body is diagnostic detail — log it, but never
            # hand it to the browser: this message renders straight into a toast.
            logger.error(
                "Failed to create contact in Xero. Status: %s, Response: %s",
                xero_response.status_code,
                xero_response.text,
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "I couldn't add that contact to Xero. Mind trying again?",
                    }
                ),
                400,
            )

        xero_contact = xero_response.json()
        logger.info("Successfully created contact: %s", xero_contact)
        return xero_contact
    except Exception as e:
        logger.error(f"Error creating contact: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't add that contact. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/report/expense/submit_all", methods=["POST"])
@login_required
def report_expense_submit_all():
    try:
        entity_id = request.args.get(
            "entity_id") or request.form.get("entity_id")

        if not entity_id:
            return (
                jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}),
                400,
            )
        if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to edit reports for this entity.",
                    }
                ),
                403,
            )

        # Get transaction_date from request parameters (form data or URL)
        selected_date = request.form.get(
            "transaction_date") or request.args.get("transaction_date")
        if selected_date:
            try:
                transaction_date = datetime.strptime(
                    selected_date, "%Y-%m-%d").date()
                logger.info(
                    f"Submit all expenses - Using transaction date from form/URL: {transaction_date}"
                )
            except ValueError:
                logger.warning(
                    f"Submit all expenses - Invalid date format: {selected_date}, using today"
                )
                transaction_date = datetime.now().date()
        else:
            transaction_date = datetime.now().date()
            logger.info(
                f"Submit all expenses - No date provided, using today: {transaction_date}"
            )

        # Get the current draft for this user with the specific
        # transaction_date
        current_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.transaction_date == transaction_date,
            ReportDraft.status == "draft",
        ).first()

        if not current_draft:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No draft found. Please start with the opening entry first.",
                    }),
                400,
            )

        # Parse expenses data from JSON
        expenses_json = request.form.get("expenses")
        if not expenses_json:
            return (
                jsonify({"status": "error", "message": "No expenses data provided."}),
                400,
            )

        expenses_data = json.loads(expenses_json)

        # Get existing expenses total from database
        existing_expenses = ShopExpenseDraft.query.filter_by(
            report_draft_id=current_draft.id
        ).all()
        existing_total = sum(expense.amount for expense in existing_expenses)

        # Initialize total expenses with existing total
        total_expenses = existing_total
        expenses = []

        # Track file upload statistics
        total_files = 0
        successful_uploads = 0
        failed_files = []

        from blueprints.report.services.s3_storage import upload_file_to_s3
        from blueprints.report.services.shared import (safe_float,
                                                       update_draft_progress)
        from models.db import ReportExpenseDetail, ReportV2, db
        from services.helpers.xero_bridge import (get_xero_data_dynamic,
                                                  resolve_contact_name)

        # Process each expense
        for index, expense_data in enumerate(expenses_data):

            item = expense_data.get("item")
            contact_id = expense_data.get("contactId")
            contact_name = expense_data.get("contactName")
            # Ensure the name is stored even if the client only sent an id.
            if contact_id and not contact_name:
                contact_name = resolve_contact_name(
                    current_draft.company, contact_id
                )
            account_id = expense_data.get("accountId")
            amount = safe_float(expense_data.get("amount", 0))
            remarks = expense_data.get("remarks", "")
            account_code = expense_data.get("account_code")
            item_code = expense_data.get("item_code")

            # Debug: Log what files are available
            logger.info(f"Processing expense {index + 1}: {item}")
            logger.info(f"Available files keys: {list(request.files.keys())}")

            # Process files for this expense
            # The frontend sends files as files[{index}][{fileIndex}]
            files = []
            file_index = 0
            while True:
                file_key = f"files[{index}][{file_index}]"
                if file_key in request.files:
                    file = request.files[file_key]
                    if file and file.filename.strip():
                        files.append(file)
                    file_index += 1
                else:
                    break

            if not files:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Expense {index + 1} must have at least one valid file attached.",
                        }),
                    400,
                )

            # Use item as description, fallback to remarks if item is empty
            description = item if item else (remarks if remarks else "EXPENSE")

            # Upload files to S3 and store file paths
            total_files += len(files)
            file_paths = []
            for file_idx, file in enumerate(files):
                try:
                    file_path = upload_file_to_s3(
                        file,
                        str(current_draft.id),
                        transaction_date=current_draft.transaction_date,
                        description=description,
                        amount=amount,
                        file_index=file_idx if len(files) > 1 else None,
                    )
                    file_paths.append(file_path)
                    successful_uploads += 1
                except Exception as upload_error:
                    failed_files.append(file.filename)
                    logger.error(
                        f"Failed to upload file {file.filename}: {str(upload_error)}"
                    )
                    raise

            # Use account_code and item_code from frontend, or get them from
            # Xero if not provided
            if not account_code and account_id:
                # Get the account code from Xero accounts data (use entity
                # owner's token)
                try:
                    xero_accounts = get_xero_data_dynamic(
                        "Accounts",
                        params={"where": 'Type="EXPENSE"||Type="DIRECTCOSTS"'},
                        entity_id=current_draft.company,
                    )
                    if isinstance(
                            xero_accounts,
                            dict) and "Accounts" in xero_accounts:
                        for acc in xero_accounts["Accounts"]:
                            if acc.get("AccountID") == account_id:
                                account_code = acc.get("Code")
                                break
                except Exception as xero_error:
                    logger.warning(
                        f"Failed to fetch account_code from Xero for expense {index + 1}: {str(xero_error)}"
                    )
                    # Continue without account_code - it's optional

            # Use item_code from frontend, or get it from Xero if not provided
            if not item_code and account_id:
                try:
                    xero_accounts = get_xero_data_dynamic(
                        "Accounts",
                        params={"where": 'Type="EXPENSE"||Type="DIRECTCOSTS"'},
                        entity_id=current_draft.company,
                    )
                    if isinstance(
                            xero_accounts,
                            dict) and "Accounts" in xero_accounts:
                        for acc in xero_accounts["Accounts"]:
                            if acc.get("AccountID") == account_id:
                                # Xero item code field
                                item_code = acc.get("ItemCode")
                                break
                except Exception as xero_error:
                    logger.warning(
                        f"Failed to fetch item_code from Xero for expense {index + 1}: {str(xero_error)}"
                    )
                    # Continue without item_code - it's optional

            # Create expense object
            expense = ShopExpenseDraft(
                report_draft_id=current_draft.id,
                item=item,
                amount=amount,
                remarks=remarks,
                files=",".join(file_paths),
                contact_id=contact_id,
                contact_name=contact_name,
                account_id=account_id,
                account_code=account_code,
                item_code=item_code,
            )
            expenses.append(expense)
            total_expenses += amount

        # Add all expenses to database
        for expense in expenses:
            db.session.add(expense)
        db.session.flush()  # Flush to ensure expense IDs are generated

        # Update draft expenses total (replace, don't add)
        current_draft.expenses = total_expenses

        # Recalculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
        # Get cash sales from ReportSaleDetail with fallback to
        # current_draft.cash_sales
        from blueprints.report.services.shared import \
            get_cash_sales_from_detail

        cash_sales = get_cash_sales_from_detail(
            current_draft.id, fallback_value=current_draft.cash_sales or 0.0
        )
        current_draft.closing_balance = (
            current_draft.opening_balance
            + (current_draft.cash_addition or 0)
            + cash_sales
            - current_draft.expenses
            - (current_draft.bank_deposit or 0)
        )

        # Update report expense total
        report_v2 = ReportV2.query.filter_by(
            entity_id=current_draft.company, report_date=transaction_date
        ).first()

        if report_v2:
            report_v2.expense_total = total_expenses
        elif not report_v2:
            report_v2 = ReportV2(
                report_id=current_draft.id,
                entity_id=entity_id,
                report_date=transaction_date,
                status=current_draft.status,
                starting_balance=current_draft.opening_balance,
                opening_balance=current_draft.opening_balance,
                adjusted_opening_balance=current_draft.adjusted_opening_balance,
                add_cash_amount=current_draft.cash_addition,
                cash_from_type="shop",
                add_cash_bank_account_id=current_draft.withdrawal_bank_account,
                xero_organiztion_id=current_user.xero_entity_id,
                cashsale_total=current_draft.cash_sales,
                nocashsale_total=current_draft.delivery_sales,
                expense_total=total_expenses,
            )
            db.session.add(report_v2)
            db.session.flush()  # Flush to get the generated report_i

        for expense in expenses:
            report_expense_detail = ReportExpenseDetail(
                expense_id=expense.id,
                report_id=report_v2.report_id,
                account_id=getattr(expense, "account_id", None),
                amount=expense.amount,
                info_filepath=getattr(expense, "files", None),
                description=getattr(expense, "remarks", None),
                create_at=datetime.now(),
            )
            db.session.add(report_expense_detail)
        db.session.commit()

        # Get action_type from form data
        action_type = request.form.get("action_type", "save_next")

        # Update progress tracking (only for save_next)
        if action_type == "save_next":
            try:
                update_draft_progress(
                    current_draft, action_type, "expenses", "deposit")
            except Exception as progress_error:
                logger.warning(
                    f"Failed to update draft progress: {str(progress_error)}"
                )
                # Continue - progress update failure shouldn't break submission

        db.session.commit()

        # Log the expense addition to draft history (non-blocking)
        try:
            log_history_draft(
                report_draft_id=current_draft.id,
                company=entity_id,
                user_id=current_user.id,
                action="added",
                field_changed="expense",
                old_value="previous_expenses",
                new_value=f"Added {len(expenses)} expenses totaling: ${total_expenses}",
            )
        except Exception as history_error:
            logger.warning(f"Failed to log history: {str(history_error)}")
            # Continue - history logging failure shouldn't break submission

        # Determine redirect URL based on action_type
        if action_type == "save_exit":
            redirect_url = url_for(
                "report.report_expense",
                entity_id=entity_id,
                transaction_date=transaction_date.strftime("%Y-%m-%d"),
            )
        else:
            redirect_url = url_for(
                "report.report_deposit",
                entity_id=entity_id,
                transaction_date=transaction_date.strftime("%Y-%m-%d"),
            )

        # Log file upload statistics
        error_info = f" Failed files: {', '.join(failed_files)}" if failed_files else ""
        logger.info(
            "Submit all expenses - Total files: "
            f"{total_files}, Successfully uploaded: {successful_uploads}{error_info}")

        return jsonify(
            {
                "status": "success",
                "message": f"All expenses submitted successfully. Total: ${total_expenses}",
                "redirect_url": redirect_url,
            })

    except Exception as e:
        import traceback

        try:
            from models.db import db

            db.session.rollback()
        except Exception as rollback_error:
            logger.error(
                f"Failed to rollback database session: {str(rollback_error)}")

        logger.error(f"Error submitting all expenses: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while submitting your expenses. Mind trying again?",
                }),
            500,
        )


@report_bp.route("/report/expense/add", methods=["POST"])
@login_required
def report_expense_add():
    """Persist a single expense immediately when the user clicks "Add".

    Uploads the expense's file(s) to S3 and commits one ShopExpenseDraft row
    (plus its ReportExpenseDetail), then recomputes the draft total / closing
    balance. This is one iteration of ``report_expense_submit_all`` returning
    JSON instead of a redirect — it does NOT advance draft progress, so the
    user stays on the expense page and can keep adding. Uploading one expense
    at a time avoids the single large multipart request that caused the
    many-files upload error.

    Multipart form payload mirrors the per-expense fields of the create flow
    (item, contactId, accountId, amount, remarks, account_code, item_code)
    with files under files[0][n].
    """
    from blueprints.report.services.s3_storage import upload_file_to_s3
    from blueprints.report.services.shared import (normalize_expense_files,
                                                   safe_float)
    from models.db import ReportExpenseDetail, ReportV2, db
    from services.helpers.xero_bridge import (get_xero_data_dynamic,
                                              resolve_contact_name)

    try:
        entity_id = request.args.get(
            "entity_id") or request.form.get("entity_id")

        if not entity_id:
            return (
                jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}),
                400,
            )
        if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to edit reports for this entity.",
                    }
                ),
                403,
            )

        # Resolve the transaction date (form/URL), defaulting to today.
        selected_date = request.form.get(
            "transaction_date") or request.args.get("transaction_date")
        if selected_date:
            try:
                transaction_date = datetime.strptime(
                    selected_date, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(
                    f"Add expense - Invalid date format: {selected_date}, using today"
                )
                transaction_date = datetime.now().date()
        else:
            transaction_date = datetime.now().date()

        current_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.transaction_date == transaction_date,
            ReportDraft.status == "draft",
        ).first()

        if not current_draft:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No draft found. Please start with the opening entry first.",
                    }),
                400,
            )

        item = request.form.get("item")
        contact_id = request.form.get("contactId")
        contact_name = request.form.get("contactName")
        # Ensure the name is stored even if the client only sent an id.
        if contact_id and not contact_name:
            contact_name = resolve_contact_name(entity_id, contact_id)
        account_id = request.form.get("accountId")
        amount = safe_float(request.form.get("amount", 0))
        remarks = request.form.get("remarks", "")
        account_code = request.form.get("account_code")
        item_code = request.form.get("item_code")

        # Collect this expense's files (files[0][n]).
        files = []
        file_index = 0
        while True:
            file_key = f"files[0][{file_index}]"
            if file_key in request.files:
                f = request.files[file_key]
                if f and f.filename.strip():
                    files.append(f)
                file_index += 1
            else:
                break

        if not files:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Expense must have at least one valid file attached.",
                    }),
                400,
            )

        description = item if item else (remarks if remarks else "EXPENSE")

        # Upload files to S3.
        file_paths = []
        for file_idx, f in enumerate(files):
            file_path = upload_file_to_s3(
                f,
                str(current_draft.id),
                transaction_date=current_draft.transaction_date,
                description=description,
                amount=amount,
                file_index=file_idx if len(files) > 1 else None,
            )
            file_paths.append(file_path)

        # Backfill account_code / item_code from Xero when not provided.
        if (not account_code or not item_code) and account_id:
            try:
                xero_accounts = get_xero_data_dynamic(
                    "Accounts",
                    params={"where": 'Type="EXPENSE"||Type="DIRECTCOSTS"'},
                    entity_id=current_draft.company,
                )
                if isinstance(xero_accounts, dict) and "Accounts" in xero_accounts:
                    for acc in xero_accounts["Accounts"]:
                        if acc.get("AccountID") == account_id:
                            if not account_code:
                                account_code = acc.get("Code")
                            if not item_code:
                                item_code = acc.get("ItemCode")
                            break
            except Exception as xero_error:
                logger.warning(
                    f"Add expense - Failed to fetch account/item code from Xero: {str(xero_error)}"
                )
                # Continue without them - they're optional.

        expense = ShopExpenseDraft(
            report_draft_id=current_draft.id,
            item=item,
            amount=amount,
            remarks=remarks,
            files=",".join(file_paths),
            contact_id=contact_id,
            contact_name=contact_name,
            account_id=account_id,
            account_code=account_code,
            item_code=item_code,
        )
        db.session.add(expense)
        db.session.flush()  # Generate expense.id

        # Recompute the draft expense total from all DB rows (idempotent).
        all_expenses = ShopExpenseDraft.query.filter_by(
            report_draft_id=current_draft.id
        ).all()
        total_expenses = sum(exp.amount for exp in all_expenses)
        current_draft.expenses = total_expenses

        cash_sales = get_cash_sales_from_detail(
            current_draft.id, fallback_value=current_draft.cash_sales or 0.0
        )
        current_draft.closing_balance = (
            current_draft.opening_balance
            + (current_draft.cash_addition or 0)
            + cash_sales
            - current_draft.expenses
            - (current_draft.bank_deposit or 0)
        )

        # Mirror the expense total on ReportV2 and add a detail row.
        report_v2 = ReportV2.query.filter_by(
            entity_id=current_draft.company, report_date=transaction_date
        ).first()

        if report_v2:
            report_v2.expense_total = total_expenses
        else:
            report_v2 = ReportV2(
                report_id=current_draft.id,
                entity_id=entity_id,
                report_date=transaction_date,
                status=current_draft.status,
                starting_balance=current_draft.opening_balance,
                opening_balance=current_draft.opening_balance,
                adjusted_opening_balance=current_draft.adjusted_opening_balance,
                add_cash_amount=current_draft.cash_addition,
                cash_from_type="shop",
                add_cash_bank_account_id=current_draft.withdrawal_bank_account,
                xero_organiztion_id=current_user.xero_entity_id,
                cashsale_total=current_draft.cash_sales,
                nocashsale_total=current_draft.delivery_sales,
                expense_total=total_expenses,
            )
            db.session.add(report_v2)
            db.session.flush()  # Generate report_v2.report_id

        report_expense_detail = ReportExpenseDetail(
            expense_id=expense.id,
            report_id=report_v2.report_id,
            account_id=account_id,
            amount=expense.amount,
            info_filepath=expense.files,
            description=remarks,
            create_at=datetime.now(),
        )
        db.session.add(report_expense_detail)

        db.session.commit()

        # Log to draft history (non-blocking).
        try:
            log_history_draft(
                report_draft_id=current_draft.id,
                company=entity_id,
                user_id=current_user.id,
                action="added",
                field_changed="expense",
                old_value="previous_expenses",
                new_value=f"Added expense: {item} (${amount})",
            )
        except Exception as history_error:
            logger.warning(f"Failed to log history: {str(history_error)}")

        return jsonify(
            {
                "status": "success",
                "message": "Expense added successfully.",
                "expense": {
                    "id": expense.id,
                    "item": expense.item or "",
                    "amount": expense.amount or 0,
                    "remarks": expense.remarks or "",
                    "account_code": expense.account_code or "",
                    "item_code": expense.item_code or "",
                    "account_id": expense.account_id or "",
                    "contact_id": expense.contact_id or "",
                    "contact_name": expense.contact_name or "",
                    "files": normalize_expense_files(
                        expense.files, getattr(expense, "s3_key", None)
                    ),
                },
                "totals": {
                    "total_expenses": total_expenses,
                    "closing_balance": current_draft.closing_balance,
                },
            }
        )

    except Exception as e:
        import traceback

        try:
            from models.db import db

            db.session.rollback()
        except Exception as rollback_error:
            logger.error(
                f"Failed to rollback database session: {str(rollback_error)}")

        logger.error(f"Error adding expense: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while adding that expense. Mind trying again?",
                }),
            500,
        )


@report_bp.route("/report/expense/update/<string:expense_id>",
                 methods=["POST"])
@login_required
def report_expense_update(expense_id):
    """Update an existing draft expense in place.

    Multipart form payload mirrors the create flow's per-expense fields
    (item, contactId, accountId, amount, remarks, account_code, item_code).
    Files under files[0][n] are optional: when present they replace the
    existing files; when omitted, existing files are preserved so the user
    can edit text/amount/account without re-uploading receipts.
    """
    from blueprints.report.services.s3_storage import upload_file_to_s3
    from blueprints.report.services.shared import safe_float
    from models.db import ReportExpenseDetail, db
    from services.helpers.xero_bridge import resolve_contact_name

    try:
        expense = ShopExpenseDraft.query.get(expense_id)
        if not expense:
            return jsonify(
                {"status": "error", "message": "Hmm, I couldn't find that expense."}), 404

        draft = expense.report_draft
        if not draft:
            return jsonify(
                {"status": "error", "message": "I don't see a draft for that yet."}), 404

        if draft.status != "draft":
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "This report isn't a draft anymore, so I can't change its expenses.",
                    }
                ),
                400,
            )

        entity_id = draft.company
        if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "It looks like you don't have permission to edit this expense.",
                    }
                ),
                403,
            )

        item = request.form.get("item") or expense.item
        contact_id = request.form.get("contactId") or expense.contact_id
        contact_name = request.form.get("contactName") or expense.contact_name
        # Ensure the name is stored even if it was never captured from the form.
        if contact_id and not contact_name:
            contact_name = resolve_contact_name(entity_id, contact_id)
        account_id = request.form.get("accountId") or expense.account_id
        account_code = request.form.get("account_code") or expense.account_code
        item_code = request.form.get("item_code") or expense.item_code
        remarks = request.form.get("remarks", expense.remarks or "")
        amount_raw = request.form.get("amount")
        amount = (
            safe_float(amount_raw) if amount_raw is not None else expense.amount
        )

        # Optional file replacement: only when the client uploads at least one
        # new file under files[0][n]. Otherwise keep the existing files.
        new_files = []
        file_index = 0
        while True:
            file_key = f"files[0][{file_index}]"
            if file_key in request.files:
                f = request.files[file_key]
                if f and f.filename.strip():
                    new_files.append(f)
                file_index += 1
            else:
                break

        if new_files:
            description = item if item else (remarks if remarks else "EXPENSE")
            file_paths = []
            for idx, f in enumerate(new_files):
                file_path = upload_file_to_s3(
                    f,
                    str(draft.id),
                    transaction_date=draft.transaction_date,
                    description=description,
                    amount=amount,
                    file_index=idx if len(new_files) > 1 else None,
                )
                file_paths.append(file_path)
            expense.files = ",".join(file_paths)

        expense.item = item
        expense.amount = amount
        expense.remarks = remarks
        expense.contact_id = contact_id
        expense.contact_name = contact_name
        expense.account_id = account_id
        expense.account_code = account_code
        expense.item_code = item_code

        # Mirror the change on ReportExpenseDetail if a row exists for this
        # expense; the create flow inserts one per expense, so most drafts will.
        detail = ReportExpenseDetail.query.filter_by(
            expense_id=expense.id
        ).first()
        if detail:
            detail.account_id = account_id
            detail.amount = amount
            detail.info_filepath = expense.files
            detail.description = remarks

        # Recalculate draft total + closing balance using same formula as
        # create/delete handlers.
        remaining_expenses = ShopExpenseDraft.query.filter_by(
            report_draft_id=draft.id
        ).all()
        new_total = sum(exp.amount for exp in remaining_expenses)
        draft.expenses = new_total
        cash_sales = get_cash_sales_from_detail(
            draft.id,
            fallback_value=draft.cash_sales or 0.0,
        )
        draft.closing_balance = (
            draft.opening_balance
            + (draft.cash_addition or 0)
            + cash_sales
            - draft.expenses
            - (draft.bank_deposit or 0)
        )

        db.session.commit()

        try:
            log_history_draft(
                report_draft_id=draft.id,
                company=draft.company,
                user_id=current_user.id,
                action="updated",
                field_changed="expense",
                old_value=f"expense_{expense_id}",
                new_value=f"updated to amount: ${amount}",
            )
        except Exception as history_error:
            logger.warning(f"Failed to log history: {str(history_error)}")

        return jsonify(
            {"status": "success", "message": "Expense updated successfully."}
        )
    except Exception as e:
        try:
            from models.db import db
            db.session.rollback()
        except Exception:
            pass
        logger.error(f"Error updating expense: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while updating that expense. Mind trying again?",
                }
            ),
            500,
        )


# ---------------------------------------------------------------------------
# Submitted-report editing of NON-balance fields only.
#
# These endpoints back the constrained "Edit Report" mode (?report_edit=true)
# for already-submitted reports. They intentionally never touch any value that
# feeds the cash balance (amounts, sales, opening, deposit, cash count), so a
# submitted report's closing balance — and the next day's opening balance —
# can never shift through this path.
# ---------------------------------------------------------------------------


def _report_for_edit(report):
    """Authorize the current user to edit `report`; return entity_id or None.

    Returns the entity_id on success, or None when unauthorized (caller turns
    that into a 403). Only submitted Report rows are valid here.
    """
    if not report:
        return None
    entity_id = report.company
    if not entity_id or not has_permission(
        current_user, Permission.REPORT_EDIT_OWN, entity_id
    ):
        return None
    return entity_id


@report_bp.route("/report/expense/edit/<string:expense_id>", methods=["POST"])
@login_required
def report_expense_edit_submitted(expense_id):
    """Edit non-balance fields of a SUBMITTED report's expense.

    Editable here: description/remarks, supplier/contact, account code, and the
    attached receipt file(s). The amount is intentionally immutable so the
    report's cash balance is never affected; replacing the receipt photo does
    not feed the balance, so it is permitted.
    """
    from blueprints.report.services.s3_storage import upload_file_to_s3
    from services.helpers.xero_bridge import resolve_contact_name

    try:
        expense = ShopExpense.query.get(expense_id)
        if not expense:
            return jsonify(
                {"status": "error", "message": "Hmm, I couldn't find that expense."}), 404

        report = Report.query.filter_by(id=expense.report_id).first()
        entity_id = _report_for_edit(report)
        if not entity_id:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "It looks like you don't have permission to edit this expense.",
                    }
                ),
                403,
            )

        contact_id = request.form.get("contactId") or expense.contact_id
        contact_name = request.form.get("contactName") or expense.contact_name
        if contact_id and not contact_name:
            contact_name = resolve_contact_name(entity_id, contact_id)
        account_id = request.form.get("accountId") or expense.account_id
        account_code = request.form.get("account_code") or expense.account_code
        item_code = request.form.get("item_code") or expense.item_code
        remarks = request.form.get("remarks", expense.remarks or "")

        # Optional receipt replacement: only when the client uploads at least
        # one new file under files[0][n]. The amount is left untouched, so the
        # cash balance is unaffected; when omitted, existing files are kept.
        new_files = []
        file_index = 0
        while True:
            file_key = f"files[0][{file_index}]"
            if file_key in request.files:
                f = request.files[file_key]
                if f and f.filename.strip():
                    new_files.append(f)
                file_index += 1
            else:
                break

        if new_files:
            description = expense.item or remarks or "EXPENSE"
            file_paths = []
            for idx, f in enumerate(new_files):
                file_path = upload_file_to_s3(
                    f,
                    str(report.id),
                    transaction_date=report.transaction_date,
                    description=description,
                    amount=expense.amount,
                    file_index=idx if len(new_files) > 1 else None,
                )
                file_paths.append(file_path)
            # Store as Format A (comma-separated S3 keys) and clear any stale
            # Format B metadata in the separate s3_key column.
            expense.files = ",".join(file_paths)
            if hasattr(expense, "s3_key"):
                expense.s3_key = None

        # Non-balance fields only — the amount is never touched.
        expense.remarks = remarks
        expense.contact_id = contact_id
        expense.contact_name = contact_name
        expense.account_id = account_id
        expense.account_code = account_code
        expense.item_code = item_code

        # Editing a submitted report makes its data diverge from what was pushed
        # to Xero, so clear the integrated flag — it shows as "Submitted" in
        # report history again and can be published afresh. publishing_status is
        # left intact so the publish flow still knows it was previously published
        # and can warn about Xero duplicates.
        if report:
            report.xero_integrated_yes = False

        db.session.commit()
        return jsonify(
            {
                "status": "success",
                "message": "Expense updated successfully.",
                "expense": {
                    "id": expense.id,
                    "item": expense.item or "",
                    "amount": expense.amount or 0,
                    "remarks": expense.remarks or "",
                    "account_code": expense.account_code or "",
                    "item_code": expense.item_code or "",
                    "account_id": expense.account_id or "",
                    "contact_id": expense.contact_id or "",
                    "contact_name": expense.contact_name or "",
                },
            }
        )
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error(f"Error editing submitted expense: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while updating that expense. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/report/<string:id>/edit/discrepancy-reason",
                 methods=["POST"])
@login_required
def report_edit_discrepancy_reason(id):
    """Edit only the free-text discrepancy reason of a SUBMITTED report.

    The discrepancy amount and type are derived from the cash count and stay
    locked; only the explanation text is editable.
    """
    try:
        report = Report.query.filter_by(id=id).first()
        entity_id = _report_for_edit(report)
        if not entity_id:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "It looks like you don't have permission to edit this report.",
                    }
                ),
                403,
            )

        # Column is String(300); trim to fit.
        reason = (request.form.get("discrepancy_reason") or "").strip()[:300]
        report.discrepancy_reason = reason

        # The cash count page reads the discrepancy reason from the linked
        # ReportCashCountDraft / ReportDraft (and Xero/exports read ReportDetail),
        # so keep all of them in sync — otherwise the saved value won't show on
        # reload and downstream consumers see the stale text.
        from models.db import ReportCashCountDraft, ReportDetail

        cashcount_draft = ReportCashCountDraft.query.filter(
            ReportCashCountDraft.report_id == report.id
        ).first()
        if cashcount_draft:
            cashcount_draft.discrepancy_reason = reason

        draft = ReportDraft.query.filter_by(id=report.id).first()
        if not draft:
            draft = ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.transaction_date == report.transaction_date,
            ).first()
        if draft:
            draft.discrepancy_reason = reason
        report_detail = ReportDetail.query.filter(
            ReportDetail.report_id == report.id
        ).first()
        if report_detail:
            report_detail.discrepancy_description = reason

        # Editing diverges the report from Xero — revert it to "Submitted" while
        # keeping publishing_status as the "was previously published" marker.
        report.xero_integrated_yes = False

        db.session.commit()
        return jsonify(
            {
                "status": "success",
                "message": "Discrepancy reason updated successfully.",
                "discrepancy_reason": report.discrepancy_reason or "",
            }
        )
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error(f"Error editing discrepancy reason: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while updating that report. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/report/<string:id>/edit/withdrawal", methods=["POST"])
@login_required
def report_edit_withdrawal(id):
    """Edit only the "withdrawal from" source of a SUBMITTED report.

    The cash amount (cash_addition) is locked; this changes only where the
    cash came from (withdrawal_type + bank account), which feeds Xero mapping,
    not the cash balance. Persisted on the linked ReportDraft — the submitted
    Report has no withdrawal columns and Xero reads them from the draft
    (matched by company + transaction_date).
    """
    try:
        report = Report.query.filter_by(id=id).first()
        entity_id = _report_for_edit(report)
        if not entity_id:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "It looks like you don't have permission to edit this report.",
                    }
                ),
                403,
            )

        withdrawal_type = (request.form.get("withdrawal_type") or "").strip()
        if withdrawal_type not in ("personal", "company"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "That withdrawal type doesn't look quite right to me.",
                    }
                ),
                400,
            )
        bank_account = (request.form.get("withdrawal_bank_account") or "").strip()

        # The submitted Report and its ReportDraft share the same id; fall back
        # to the company+date match Xero uses if the id link is ever missing.
        draft = ReportDraft.query.filter_by(id=report.id).first()
        if not draft:
            draft = ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.transaction_date == report.transaction_date,
            ).first()
        if not draft:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "I couldn't find the draft behind this report, so I can't change the withdrawal source.",
                    }
                ),
                404,
            )

        draft.withdrawal_type = withdrawal_type
        draft.withdrawal_bank_account = bank_account if withdrawal_type == "company" else ""

        # Editing diverges the report from Xero — revert it to "Submitted" while
        # keeping publishing_status as the "was previously published" marker.
        report.xero_integrated_yes = False

        db.session.commit()
        return jsonify(
            {
                "status": "success",
                "message": "Withdrawal source updated successfully.",
                "withdrawal_type": draft.withdrawal_type,
                "withdrawal_bank_account": draft.withdrawal_bank_account or "",
            }
        )
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error(f"Error editing withdrawal source: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while updating that report. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/report/expense/delete/<string:expense_id>",
                 methods=["DELETE"])
@login_required
def report_expense_delete(expense_id):
    try:
        logger.info("Delete expense request for ID: %s", expense_id)

        expense = ShopExpenseDraft.query.get(expense_id)
        if not expense:
            logger.warning("Expense not found: %s", expense_id)
            return jsonify(
                {"status": "error", "message": "Hmm, I couldn't find that expense."}), 404

        draft = expense.report_draft
        if not draft:
            return jsonify({"status": "error", "message": "I don't see a draft for that yet."}), 404
        entity_id = draft.company
        is_owner = draft.uploaded_by == current_user.username
        can_delete = False
        if is_owner and has_permission(current_user, Permission.REPORT_DELETE_OWN, entity_id):
            can_delete = True
        elif has_permission(current_user, Permission.REPORT_DELETE_ENTITY, entity_id):
            can_delete = True
        if not can_delete:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "It looks like you don't have permission to delete this expense.",
                    }
                ),
                403,
            )

        deleted_amount = expense.amount
        from models.db import db

        db.session.delete(expense)

        remaining_expenses = ShopExpenseDraft.query.filter_by(
            report_draft_id=draft.id
        ).all()
        new_total = sum(exp.amount for exp in remaining_expenses)
        logger.info(
            "Deleted expense amount: %s, remaining: %s, new_total: %s",
            deleted_amount,
            len(remaining_expenses),
            new_total,
        )

        draft.expenses = new_total
        cash_sales = get_cash_sales_from_detail(
            draft.id,
            fallback_value=draft.cash_sales or 0.0,
        )
        draft.closing_balance = (
            draft.opening_balance
            + (draft.cash_addition or 0)
            + cash_sales
            - draft.expenses
            - (draft.bank_deposit or 0)
        )
        logger.info("New closing balance: %s", draft.closing_balance)
        db.session.commit()

        log_history_draft(
            report_draft_id=draft.id,
            company=draft.company,
            user_id=current_user.id,
            action="deleted",
            field_changed="expense",
            old_value=f"expense_{expense_id}",
            new_value="deleted",
        )

        return jsonify(
            {"status": "success", "message": "Expense deleted successfully."}
        )
    except Exception as e:
        from models.db import db

        db.session.rollback()
        logger.error("Error deleting expense: %s", str(e))
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while deleting that expense. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/api/get_draft_totals", methods=["GET"])
@login_required
def get_draft_totals():
    try:
        transaction_date_str = request.args.get(
            "transaction_date") or request.form.get("transaction_date")
        if not transaction_date_str:
            return (
                jsonify({"status": "error", "message": "That field can't be empty! Please let me know your transaction date."}),
                400,
            )

        from datetime import datetime

        try:
            transaction_date = datetime.strptime(
                transaction_date_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            return jsonify(
                {"status": "error", "message": "That date doesn't look quite right to me."}), 400

        entity_id_param = (
            request.args.get("entity_id")
            or request.form.get("entity_id")
        )
        if not entity_id_param:
            return (
                jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}),
                400,
            )
        if not has_permission(current_user, Permission.REPORT_VIEW_OWN, entity_id_param):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view report totals for this entity.",
                    }
                ),
                403,
            )
        current_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id_param,
            ReportDraft.transaction_date == transaction_date,
            ReportDraft.status == "draft",
        ).first()

        if not current_draft:
            return jsonify(
                {"status": "error", "message": "I don't see a draft for that yet."}), 404
        if not _can_view_report_draft(current_draft):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view this draft.",
                    }
                ),
                403,
            )

        from models.db import db

        db.session.refresh(current_draft)

        calculated_total = current_draft.total_expenses or 0
        stored_total = current_draft.expenses or 0

        expenses_count = ShopExpenseDraft.query.filter_by(
            report_draft_id=current_draft.id
        ).count()

        opening_bal = float(current_draft.opening_balance or 0)
        cash_addition_val = float(current_draft.cash_addition or 0)
        bank_dep = float(current_draft.bank_deposit or 0)
        cash_sales_val = float(
            get_cash_sales_from_detail(
                current_draft.id,
                fallback_value=float(current_draft.cash_sales or 0),
            )
        )
        exp_total = float(calculated_total or 0)
        # Same as expense save: opening + cash_addition + cash_sales − expenses − bank_deposit
        computed_closing = (
            opening_bal
            + cash_addition_val
            + cash_sales_val
            - exp_total
            - bank_dep
        )
        currency_balance = computed_closing

        logger.info(
            "API get_draft_totals - Calculated total: %s, Stored total: %s, Count: %s",
            calculated_total,
            stored_total,
            expenses_count,
        )

        return jsonify({"status": "success",
                        "total_expenses": calculated_total,
                        "expenses_count": expenses_count,
                        "opening_balance": opening_bal,
                        "cash_sales": cash_sales_val,
                        "currency_balance": currency_balance,
                        "cash_addition": cash_addition_val,
                        "adjusted_opening_balance": current_draft.adjusted_opening_balance or 0,
                        "total_sales": current_draft.total_sales or 0,
                        "bank_deposit": bank_dep,
                        "closing_balance": computed_closing,
                        })

    except Exception as e:
        logger.error("Error getting draft totals: %s", str(e))
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong on my end while adding up your totals. Mind trying again?",
                }
            ),
            500,
        )


@report_bp.route("/api/generate_share_link", methods=["POST"])
@login_required
def generate_share_link():
    try:
        data = request.get_json(silent=True) or {}
        response, status = create_share_link_for_report(current_user.id, data)
        return jsonify(response), status
    except Exception as exc:
        logger.error(f"Error generating share link: {str(exc)}")
        return jsonify({"error": "Failed to generate share link"}), 500


@report_bp.route("/api/report/<report_id>/publishing_status", methods=["GET"])
@login_required
def report_publishing_status(report_id):
    """Get the current publishing status of a report."""
    try:
        report = Report.query.get_or_404(report_id)
        entity_id = report.company
        user_entity = UserEntity.query.filter(
            UserEntity.user_id == current_user.id,
            UserEntity.entity_id == entity_id,
        ).first()
        if not user_entity:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have access to this report",
                    }
                ),
                403,
            )
        if not has_permission(current_user, Permission.REPORT_VIEW_ENTITY, entity_id):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view publishing status.",
                    }
                ),
                403,
            )

        failure_reason = None
        failure_reasons = []
        failure_reason_items = []
        if report.publishing_status in ("failed", "partially_published"):
            # Pull the most recent ``publish_failed`` history row so the
            # frontend can show the user *why* it failed / was only partially
            # published (archived contact, inactive account, etc.) instead of a
            # generic toast.
            recent_history = (
                ReportHistory.query.filter(
                    ReportHistory.report_id == report.id,
                )
                .order_by(ReportHistory.timestamp.desc())
                .limit(5)
                .all()
            )
            items = latest_publish_reason_items(recent_history)
            failure_reason_items = annotate_resolution(
                report.company, items, report_id=report.id
            )
            failure_reasons = [it["text"] for it in failure_reason_items]
            if failure_reasons:
                failure_reason = "; ".join(failure_reasons)

        return (
            jsonify(
                {
                    "status": "success",
                    "publishing_status": report.publishing_status,
                    "xero_integrated_yes": report.xero_integrated_yes or False,
                    "failure_reason": failure_reason,
                    "failure_reasons": failure_reasons,
                    "failure_reason_items": failure_reason_items,
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(
            "Error getting publishing status for report %s: %s",
            report_id,
            str(e),
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Something went wrong checking that report's publishing status. Mind trying again?",
                }
            ),
            500,
        )


# ---------------------------------------------------------------------------
# Multi-file expense upload  (Step 1: upload files, create skeleton drafts)
# ---------------------------------------------------------------------------

_ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


@report_bp.route("/report/expense/upload_files", methods=["POST"])
@login_required
def expense_upload_files():
    """Upload multiple receipt files to S3 and create a ShopExpenseDraft skeleton
    record for each one.  Details (amount, contact, account_code, etc.) are
    intentionally left null — they are filled in later via PATCH.

    Accepts multipart/form-data with:
      - report_draft_id  (required)
      - entity_id        (required)
      - files[]          (one or more files)

    Returns JSON list of created draft records.
    """
    try:
        entity_id = request.form.get("entity_id")
        report_draft_id = request.form.get("report_draft_id")

        if not entity_id:
            return jsonify({"status": "error", "message": "I need to know which entity we're working with first!"}), 400
        if not report_draft_id:
            return jsonify({"status": "error", "message": "I need to know which draft we're working with first!"}), 400

        if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
            return (
                jsonify({"status": "error", "message": "Hmm, it looks like you don't have permission to do that."}),
                403,
            )

        draft = ReportDraft.query.filter_by(id=report_draft_id).first()
        if not draft or str(draft.company) != str(entity_id):
            return jsonify({"status": "error", "message": "I don't see a draft for that yet."}), 404

        files = request.files.getlist("files[]")
        files = [f for f in files if f and f.filename.strip()]
        if not files:
            return jsonify({"status": "error", "message": "No files provided."}), 400

        created = []
        for file in files:
            # Validate mime type
            if file.mimetype not in _ALLOWED_MIME:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Unsupported file type '{file.mimetype}' for {file.filename}. "
                            "Allowed: PDF, JPEG, PNG.",
                        }
                    ),
                    400,
                )

            # Validate size
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > _MAX_FILE_BYTES:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"File '{file.filename}' exceeds the 10 MB limit.",
                        }
                    ),
                    400,
                )

            original_filename = secure_filename(file.filename)
            _, ext = os.path.splitext(original_filename)
            if not ext:
                ext = ".jpg"

            # Use a UUID-based key so names don't collide and we don't need
            # expense details (description / amount) at upload time.
            s3_key = f"expenses/{report_draft_id}/upload_{uuid.uuid4().hex[:12]}{ext}"

            file.seek(0)
            raw = file.read()
            downsized, out_mime = downsize_bytes(raw, file.mimetype or "")
            # A PNG re-encoded to JPEG must land under a .jpg key so the stored
            # bytes match the extension that download/preview relies on.
            if out_mime == "image/jpeg" and not s3_key.lower().endswith((".jpg", ".jpeg")):
                s3_key = os.path.splitext(s3_key)[0] + ".jpg"
            if len(downsized) < len(raw):
                logger.info(
                    "Downsized %s: %d -> %d bytes",
                    file.filename, len(raw), len(downsized),
                )

            try:
                get_s3_client().upload_fileobj(
                    io.BytesIO(downsized), get_s3_bucket(), s3_key
                )
            except Exception as upload_err:
                logger.error("S3 upload failed for %s: %s", file.filename, upload_err)
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Failed to upload '{file.filename}'. Please try again.",
                        }
                    ),
                    500,
                )

            # Build files metadata JSON (mirrors the pattern used by submit_all).
            # mime_type reflects the stored bytes (PNG may have been re-encoded
            # to JPEG), not the original upload.
            files_meta = json.dumps(
                {"original_filename": original_filename, "mime_type": out_mime or file.mimetype}
            )

            expense_draft = ShopExpenseDraft(
                report_draft_id=report_draft_id,
                # Required DB NOT NULL field — use a placeholder until filled in
                item="",
                amount=0.0,
                files=files_meta,
                s3_key=s3_key,
                # Detail fields intentionally null until PATCH
                remarks=None,
                contact_id=None,
                contact_name=None,
                account_id=None,
                account_code=None,
                item_code=None,
            )
            db.session.add(expense_draft)
            db.session.flush()  # get the generated id before commit

            # Build a short-lived (15-min) presigned URL for preview
            try:
                preview_url = get_s3_client().generate_presigned_url(
                    "get_object",
                    Params={"Bucket": get_s3_bucket(), "Key": s3_key},
                    ExpiresIn=900,
                )
            except Exception:
                preview_url = None

            created.append(
                {
                    "id": expense_draft.id,
                    "original_filename": original_filename,
                    "mime_type": file.mimetype,
                    "s3_key": s3_key,
                    "preview_url": preview_url,
                }
            )

        db.session.commit()
        logger.info(
            "expense_upload_files: created %d draft records for report_draft %s",
            len(created),
            report_draft_id,
        )
        return jsonify({"status": "success", "drafts": created}), 200

    except Exception as exc:
        db.session.rollback()
        logger.error("expense_upload_files error: %s", exc)
        return jsonify({"status": "error", "message": "That upload didn't go through. Mind trying again?"}), 500


# ---------------------------------------------------------------------------
# Get / update a single ShopExpenseDraft record (Steps 2 & 3)
# ---------------------------------------------------------------------------


@report_bp.route("/report/expense/draft/<string:draft_id>", methods=["GET"])
@login_required
def expense_draft_get(draft_id):
    """Return the detail fields of one ShopExpenseDraft record."""
    expense = ShopExpenseDraft.query.get(draft_id)
    if not expense:
        return jsonify({"status": "error", "message": "I don't see a draft for that yet."}), 404

    entity_id = expense.report_draft.company
    if not has_permission(current_user, Permission.REPORT_VIEW_OWN, entity_id):
        return jsonify({"status": "error", "message": "Hmm, it looks like you don't have permission to do that."}), 403

    # Determine which S3 key to use for the presigned preview URL.
    #
    # Rule 1 — files is a plain S3 path string (legacy submit_all format):
    #   use files directly as the S3 key.
    # Rule 2 — files is a JSON object {"original_filename": ..., "mime_type": ...}
    #   (new upload_files format): use expense.s3_key.
    _files_s3_key = None
    try:
        meta = json.loads(expense.files) if expense.files else {}
        if isinstance(meta, dict):
            # Rule 2: JSON format — use the dedicated s3_key column
            _files_s3_key = expense.s3_key
        else:
            # Unexpected JSON type — fall back to s3_key column
            _files_s3_key = expense.s3_key
            meta = {}
    except (ValueError, TypeError):
        # Rule 1: plain string path — use it directly as the S3 key
        meta = {}
        _files_s3_key = expense.files if expense.files else expense.s3_key

    # Infer mime_type from file extension when not stored in meta
    _mime_type = meta.get("mime_type", "")
    if not _mime_type and _files_s3_key:
        _ext = os.path.splitext(_files_s3_key)[1].lower()
        _ext_mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
        }
        _mime_type = _ext_mime_map.get(_ext, "")

    # Infer original_filename from S3 key when not stored in meta
    _original_filename = meta.get("original_filename", "")
    if not _original_filename and _files_s3_key:
        _original_filename = os.path.basename(_files_s3_key)

    # Re-generate presigned URL on demand so it stays fresh
    try:
        preview_url = get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": get_s3_bucket(), "Key": _files_s3_key},
            ExpiresIn=900,
        ) if _files_s3_key else None
    except Exception:
        preview_url = None

    return jsonify(
        {
            "status": "success",
            "draft": {
                "id": expense.id,
                "original_filename": _original_filename,
                "mime_type": _mime_type,
                "s3_key": expense.s3_key,
                "preview_url": preview_url,
                "item": expense.item or "",
                "amount": expense.amount or 0,
                "remarks": expense.remarks or "",
                "contact_id": expense.contact_id or "",
                "contact_name": expense.contact_name or "",
                "account_id": expense.account_id or "",
                "account_code": expense.account_code or "",
                "item_code": expense.item_code or "",
            },
        }
    )


@report_bp.route("/report/expense/draft/<string:draft_id>", methods=["PATCH"])
@login_required
def expense_draft_patch(draft_id):
    """Update the expense detail fields of a single ShopExpenseDraft.

    JSON body:
      amount, item, remarks, contact_id, contact_name, account_id,
      account_code, item_code  (all optional — only provided keys are updated)
    """
    expense = ShopExpenseDraft.query.get(draft_id)
    if not expense:
        return jsonify({"status": "error", "message": "I don't see a draft for that yet."}), 404

    entity_id = expense.report_draft.company
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return jsonify({"status": "error", "message": "Hmm, it looks like you don't have permission to do that."}), 403

    data = request.get_json(silent=True) or {}

    if "amount" in data:
        try:
            expense.amount = float(str(data["amount"]).replace(",", ""))
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "That amount doesn't look quite right to me."}), 400

    if "item" in data:
        expense.item = str(data["item"])[:150]
    if "remarks" in data:
        expense.remarks = str(data["remarks"])[:300] if data["remarks"] else None
    if "contact_id" in data:
        expense.contact_id = data["contact_id"] or None
    if "contact_name" in data:
        expense.contact_name = str(data["contact_name"])[:150] if data["contact_name"] else None
    # When the contact changes but no name was supplied, resolve it from Xero.
    if "contact_id" in data and "contact_name" not in data and expense.contact_id:
        from services.helpers.xero_bridge import resolve_contact_name
        resolved = resolve_contact_name(entity_id, expense.contact_id)
        if resolved:
            expense.contact_name = resolved[:150]
    if "account_id" in data:
        expense.account_id = data["account_id"] or None
    if "account_code" in data:
        expense.account_code = str(data["account_code"])[:20] if data["account_code"] else None
    if "item_code" in data:
        expense.item_code = str(data["item_code"])[:20] if data["item_code"] else None

    db.session.commit()
    logger.info("expense_draft_patch: updated draft %s", draft_id)
    return jsonify({"status": "success", "message": "Expense details saved."})


# ---------------------------------------------------------------------------
# Validate all drafts for a report are complete (Step 4)
# ---------------------------------------------------------------------------


@report_bp.route("/report/expense/validate_drafts", methods=["GET"])
@login_required
def expense_validate_drafts():
    """Check every ShopExpenseDraft for a given report_draft_id has required
    fields filled in (amount > 0, contact_id, account_id).

    Query params:
      - report_draft_id
      - entity_id

    Returns:
      { "status": "complete" }  if all records are complete
      { "status": "incomplete", "first_incomplete": { id, original_filename } }
    """
    report_draft_id = request.args.get("report_draft_id")
    entity_id = request.args.get("entity_id")

    if not report_draft_id or not entity_id:
        return (
            jsonify({"status": "error", "message": "I need to know which entity and draft we're working with first!"}),
            400,
        )

    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return jsonify({"status": "error", "message": "Hmm, it looks like you don't have permission to do that."}), 403

    drafts = ShopExpenseDraft.query.filter_by(report_draft_id=report_draft_id).all()

    if not drafts:
        # No uploaded files — nothing to validate, treat as complete
        return jsonify({"status": "complete"})

    for d in drafts:
        if not d.amount or d.amount <= 0 or not d.contact_id or not d.account_id:
            try:
                meta = json.loads(d.files) if d.files else {}
            except (ValueError, TypeError):
                meta = {"original_filename": d.files or "unknown"}
            filename = meta.get("original_filename", "unknown")
            return jsonify(
                {
                    "status": "incomplete",
                    "first_incomplete": {"id": d.id, "original_filename": filename},
                }
            )

    return jsonify({"status": "complete"})




