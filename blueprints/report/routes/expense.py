# Report expense routes; delegates to app implementation.
# Expense step: report_expense transferred from app.py (single function,
# no new functions).
import json
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (check_user_has_entities,
                                               get_cash_sales_from_detail,
                                               header_publishing_status_for,
                                               normalize_expense_files,
                                               resolve_report_entity_id,
                                               safe_float,
                                               update_draft_progress)
from models.db import (AccountInfo, Entity, EntityAccountXero, Report,
                       ReportDraft, ReportExpenseDetail, ReportV2, ShopExpense,
                       ShopExpenseDraft, XeroContactSync, db)
from services.authz import permission_denied
from services.helpers.xero_bridge import (account_info_to_xero_format,
                                          contact_sync_to_xero_format,
                                          get_xero_data_dynamic,
                                          resolve_contact_name)
from services.permission_policy import Permission, can_edit_report, has_permission
from utils import jsonify


def _trigger_xero_sync_background(entity_id, org):
    """Kick off background sync of accounts and contacts for a connected entity.

    Non-blocking: both syncs run in daemon threads so page load is not delayed.
    Only runs when the entity is connected and has a valid Xero token.
    """
    from services.auth.token_service import (
        ensure_valid_token,
        get_xero_token_user_for_entity,
    )
    from blueprints.entity.services.settings import (
        sync_chart_of_accounts_if_changed_background,
        sync_contacts_if_changed_background,
    )

    if not org or org.status != "connected" or not org.xero_org_id:
        return

    entity_id_str = str(entity_id)
    xero_org_id = str(org.xero_org_id)

    try:
        token_user = get_xero_token_user_for_entity(entity_id_str)
        if not token_user or not getattr(token_user, "access_token", None):
            logger.info(
                "expense sync skipped entity=%s: no token user", entity_id_str
            )
            return
        if not ensure_valid_token(token_user):
            logger.info(
                "expense sync skipped entity=%s: token invalid", entity_id_str
            )
            return

        access_token = token_user.access_token
        user_id = str(token_user.id)

        sync_chart_of_accounts_if_changed_background(
            entity_id_str, access_token, xero_org_id, user_id,
        )
        sync_contacts_if_changed_background(
            entity_id_str, access_token, xero_org_id,
        )
        logger.info(
            "expense page: triggered background account+contact sync entity=%s",
            entity_id_str,
        )
    except Exception as exc:
        logger.warning(
            "expense page: sync trigger failed entity=%s: %s", entity_id_str, exc
        )


@report_bp.route("/report/expense", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/expense", methods=["GET"])
@login_required
def report_expense(id=None):
    from blueprints.report.services.s3_storage import upload_file_to_s3

    DD_CLIENT_TOKEN = "pub8127bb0367f2b74cbba93dad6f012b90"
    entity_id = request.args.get("entity_id") or request.form.get("entity_id")
    if not entity_id:
        entity_id = resolve_report_entity_id(id)
    if not entity_id:
        flash("I need to know which entity we're working with first!", "danger")
        return redirect(url_for("entity.entity_list"))
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You do not have permission to edit reports for this entity.",
            entity_id=entity_id,
        )
    if id:
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access:
            report_for_access = ReportDraft.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
    # Check if user has any entities before allowing access to reports
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you any reports.",
            "warning")
        return redirect(url_for("entity.entity_list"))

    # Check if edit mode is enabled
    is_edit_mode = (request.args.get("edit") ==
                    "true" or request.form.get("edit") == "true")

    def get_entity_badge_data(entity):
        acronym = ""
        if entity and entity.name:
            words = entity.name.split()
            acronym = "".join([word[0].upper() for word in words if word])

        badge_date = None
        if entity and entity.created_at:
            if isinstance(entity.created_at, datetime):
                badge_date = entity.created_at.date()
            else:
                badge_date = entity.created_at
        return acronym, badge_date

    entity_acronym = ""
    display_date = None

    # Get entity to access its xero_org_id
    org = None
    xero_org_id = None
    if entity_id:
        org = Entity.query.filter(Entity.id == entity_id).first()
        if org and org.xero_org_id:
            xero_org_id = org.xero_org_id
            logger.info(
                f"Using entity-specific xero_org_id: {xero_org_id} for entity: {entity_id}"
            )
        else:
            logger.warning(
                f"Entity {entity_id} not found or missing xero_org_id, falling back to user's default"
            )

    # Get Xero data with error handling
    # Check if entity is connected - if not, use database data
    is_connected = org and org.status == "connected"

    # Trigger background sync of Xero accounts and contacts before fetching
    # page data so the DB is as fresh as possible. Non-blocking — runs in
    # daemon threads and does NOT delay the page load.
    if is_connected and request.method == "GET":
        _trigger_xero_sync_background(entity_id, org)

    if is_connected:
        # Contacts come from Xero live when connected. The account dropdown is
        # NOT fetched here — it is sourced from entity_account_xero below.
        logger.info(
            f"Entity {entity_id} is connected, fetching contacts from Xero API")
        xero_contacts = get_xero_data_dynamic(
            "Contacts", xero_org_id=xero_org_id, entity_id=entity_id,
            paginate=True, page_size=100,
        )
    else:
        # Disconnected: contacts from DB. Accounts still come from
        # entity_account_xero below (single source of truth).
        logger.info(
            f"Entity {entity_id} is disconnected, fetching contacts from database")
        db_contacts = XeroContactSync.query.filter_by(
            entity_id=entity_id).all()
        logger.info(
            f"Found {len(db_contacts)} contacts in database for entity {entity_id}"
        )
        contacts_list = [
            contact_sync_to_xero_format(contact) for contact in db_contacts
        ]
        xero_contacts = {"Contacts": contacts_list}

    # Check if Xero API calls failed (only when connected)
    if is_connected:
        if isinstance(xero_contacts, dict) and (
            "error" in xero_contacts or "Detail" in xero_contacts
        ):
            error_msg = xero_contacts.get(
                "error", xero_contacts.get("Detail", "Unknown error")
            )
            logger.warning(f"Failed to fetch Xero contacts: {error_msg}")
            xero_contacts = {"Contacts": []}  # Provide empty fallback

    # When connected but contacts failed or empty, fall back to DB so expense
    # Suppliers dropdown has data
    if is_connected and entity_id:
        contacts_list = (
            xero_contacts.get("Contacts") if isinstance(
                xero_contacts, dict) else [])
        if not contacts_list or (
            isinstance(xero_contacts, dict)
            and ("error" in xero_contacts or "Detail" in xero_contacts)
        ):
            db_contacts = XeroContactSync.query.filter_by(
                entity_id=entity_id).all()
            contacts_list = [
                contact_sync_to_xero_format(c) for c in db_contacts]
            xero_contacts = {"Contacts": contacts_list}
            if contacts_list:
                logger.info(
                    f"Using {len(contacts_list)} contacts from DB for entity {entity_id} (Xero fetch failed or empty)"
                )

    # Account dropdown source of truth: entity_account_xero (is_active=true),
    # joined to account_info for code/name/type/status. The petty cash CoA tick
    # selection drives this list. No fallback — if the sync pipeline has not
    # populated entity_account_xero yet, the dropdown is empty (it fills on the
    # next Xero connect, settings-page visit, or nightly sync).
    xero_accounts = []
    if entity_id:
        active_rows = (
            db.session.query(AccountInfo)
            .join(
                EntityAccountXero,
                EntityAccountXero.account_id == AccountInfo.id,
            )
            .filter(
                AccountInfo.entity_id == entity_id,
                EntityAccountXero.is_active.is_(True),
            )
            .all()
        )
        # entity_account_xero.is_active is the single source of truth — show
        # every active account as-is (no SystemAccount / code-497 filtering),
        # mirroring the petty cash CoA settings list.
        for acc in active_rows:
            xero_accounts.append(account_info_to_xero_format(acc))
        logger.info(
            "expense: %s active entity_account_xero accounts for entity %s",
            len(xero_accounts), entity_id,
        )

    if id:
        current_draft = (
            ReportDraft.query.join(
                Report,
                ReportDraft.id == Report.id,
                full=True) .filter_by(
                id=id) .first())
        if not org:
            org = Entity.query.get_or_404(entity_id)
        entity_acronym, display_date = get_entity_badge_data(org)
        existing_expenses = (
            ShopExpense.query.join(
                ShopExpenseDraft,
                ShopExpenseDraft.id == ShopExpense.id,
                full=True) .filter(
                ShopExpense.report_id == id,
                ShopExpenseDraft.report_draft_id == id) .all())

        # Determine if this is the latest report (most recent transaction_date)
        # or old report
        latest_report_date = (
            db.session.query(
                db.func.max(
                    db.func.coalesce(
                        Report.transaction_date,
                        ReportDraft.transaction_date))) .filter(
                db.or_(
                    Report.company == entity_id,
                    ReportDraft.company == entity_id),
            ) .scalar())

        is_latest_report = current_draft.transaction_date == latest_report_date

        # Publish sets xero_integrated_yes on Report, not always synced on ReportDraft;
        # header badge reads this for Published vs Submitted.
        _report_for_xero = Report.query.filter_by(id=id).first()
        header_xero_integrated_yes = bool(
            _report_for_xero and _report_for_xero.xero_integrated_yes
        )

        # Normalize expense file metadata so the template emits a clean JSON
        # array for each expense's data-expense-files attribute.
        expense_files_map = {
            expense.id: json.dumps(
                normalize_expense_files(expense.files, getattr(expense, "s3_key", None))
            )
            for expense in existing_expenses
        }

        return render_template(
            "report/expense.html",
            xero_contacts=xero_contacts,
            xero_accounts=xero_accounts,
            existing_expenses=existing_expenses,
            expense_files_map=expense_files_map,
            current_report=current_draft,
            current_draft=current_draft,
            header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
            org=org,
            current_section="expenses",  # Always set to current page
            completed_sections=(
                current_draft.completed_sections if current_draft else [
                    "opening"]
            ),
            is_draft=True,
            draft_id=current_draft.id if current_draft else None,
            current_user=current_user,
            datenow=datetime.now(),
            transaction_date=current_draft.transaction_date,
            is_latest_report=is_latest_report,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
            DD_CLIENT_TOKEN=DD_CLIENT_TOKEN,
            header_xero_integrated_yes=header_xero_integrated_yes,
        )
    if request.method == "POST":
        # Debug logging
        logger.info("Expense form POST request received")
        logger.info(f"Form data keys: {list(request.form.keys())}")
        logger.info(f"Files data keys: {list(request.files.keys())}")

        action_type = request.form.get("action_type", "save_next")
        logger.info(f"Action type: {action_type}")
        try:
            # Get the current draft for this user instead of production report
            # We should get the transaction_date from the current session or
            # use today
            selected_date = request.form.get("transaction_date")
            if selected_date:
                try:
                    transaction_date = datetime.strptime(
                        selected_date, "%Y-%m-%d"
                    ).date()
                    logger.info(
                        f"Expenses form - Using transaction date from form: {transaction_date}"
                    )
                except ValueError:
                    logger.warning(
                        f"Expenses form - Invalid date format in form: {selected_date}, using today"
                    )
                    transaction_date = datetime.now().date()
            else:
                transaction_date = datetime.now().date()
                logger.info(
                    f"Expenses form - No transaction date in form, using today: {transaction_date}"
                )

            current_draft = (
                ReportDraft.query.filter(
                    ReportDraft.company == entity_id,
                    ReportDraft.transaction_date == transaction_date,
                    ReportDraft.status == "draft",
                )
                .order_by(ReportDraft.transaction_date.desc())
                .first()
            )

            if not current_draft:
                flash(
                    "I don't see a draft yet - let's start with the opening entry.",
                    "danger",
                )
                return redirect(url_for("report.report_opening", entity_id=entity_id))

            # Get existing expenses total from database
            existing_expenses = ShopExpenseDraft.query.filter_by(
                report_draft_id=current_draft.id
            ).all()
            existing_total = sum(
                expense.amount for expense in existing_expenses)

            # Initialize total expenses with existing total
            total_expenses = existing_total
            expenses = []

            # Process expenses if applicable
            index = 0
            while f"shopExpenses[{index}][item]" in request.form:
                item_value = request.form.get(f"shopExpenses[{index}][item]")
                item = item_value.split("_")[1]
                item_value.split("_")[0]

                amount = safe_float(
                    request.form.get(f"shopExpenses[{index}][amount]", 0)
                )
                remarks = request.form.get(
                    f"shopExpenses[{index}][remarks]", "")
                contact_id = request.form.get(
                    f"shopExpenses[{index}][contactId]")
                contact_name = request.form.get(
                    f"shopExpenses[{index}][contactName]")
                account_id = request.form.get(
                    f"shopExpenses[{index}][accountId]")
                # Ensure the name is stored even if only an id was submitted.
                if contact_id and not contact_name:
                    contact_name = resolve_contact_name(entity_id, contact_id)

                # Process files for each expense
                files = request.files.getlist(f"files[{index}][]")
                files = [
                    file for file in files if file and file.filename.strip()]

                if not files:
                    raise ValueError(
                        f"Expense {index + 1} must have at least one valid file attached."
                    )

                # Use item as description, fallback to remarks if item is empty
                description = item if item else (
                    remarks if remarks else "EXPENSE")

                # Upload files to S3 with proper naming format
                file_paths = []
                for file_index, file in enumerate(files):
                    file_path = upload_file_to_s3(
                        file,
                        str(current_draft.id),
                        transaction_date=current_draft.transaction_date,
                        description=description,
                        amount=amount,
                        file_index=file_index if len(files) > 1 else None,
                    )
                    file_paths.append(file_path)

                # Create expense object with the draft ID
                expense = ShopExpenseDraft(
                    report_draft_id=current_draft.id,
                    item=item,
                    amount=amount,
                    remarks=remarks,
                    files=",".join(file_paths),
                    contact_id=contact_id,
                    contact_name=contact_name,
                    account_id=account_id,
                )
                expenses.append(expense)
                total_expenses += amount
                index += 1

            # If no expenses were submitted, still update draft progress
            if len(expenses) == 0:
                logger.info(
                    "No new expenses submitted, proceeding to next section")
                logger.info(
                    f"Existing expenses count: {len(existing_expenses)}")
                logger.info(f"Total expenses: {total_expenses}")

                # Update draft progress to mark expenses section as complete
                # (even with no expenses, only for save_next)
                if action_type == "save_next":
                    update_draft_progress(
                        current_draft, action_type, "expenses", "deposit"
                    )

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    logger.info("AJAX request - returning JSON response")
                    return jsonify(
                        {
                            "status": "success",
                            "message": "No expenses to add. Proceeding to next section.",
                            "redirect_url": url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ),
                        })
                else:
                    logger.info(
                        "Regular form submission - redirecting to deposit")

                    # Check action type and redirect accordingly
                    if action_type == "save_next":
                        logger.info(
                            f"Redirecting to deposit page with date: {transaction_date}"
                        )
                        return redirect(
                            url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))
                    elif action_type == "save_exit":
                        return redirect(
                            url_for(
                                "report.report_expense",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))
                    else:
                        # Default to save_next
                        return redirect(
                            url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))
            else:
                # Add all expenses to database
                for expense in expenses:
                    db.session.add(expense)

                # Update draft expenses total (replace, don't add); track last
                # editor
                current_draft.uploaded_by = current_user.username
                current_draft.expenses = total_expenses

                # Check if there is an existing report_v2 based on report_id
                # (draft_id)
                report_v2 = ReportV2.query.filter_by(
                    report_id=current_draft.id).first()

                nocashsale_fields = [
                    "visa_sales",
                    "master_sales",
                    "alipay_sales",
                    "wechat_sales",
                    "unionpay_sales",
                    "amex_sales",
                    "octopus_sales",
                ]
                nocashsale_total = 0
                for field in nocashsale_fields:
                    value = getattr(current_draft, field, 0)
                    nocashsale_total += value if value else 0

                if report_v2:
                    # Update existing report_v2 with new expense_total
                    report_v2.nocashsale_total = nocashsale_total
                    report_v2.expense_total = total_expenses
                    logger.info(
                        f"Updated existing ReportV2 {report_v2.report_id} with expense_total: {total_expenses}"
                    )
                else:
                    # Create new report_v2 if it doesn't exist
                    report_v2 = ReportV2(
                        report_id=current_draft.id,
                        entity_id=entity_id,
                        report_date=current_draft.transaction_date,
                        status=current_draft.status or "draft",
                        starting_balance=current_draft.opening_balance,
                        opening_balance=current_draft.opening_balance,
                        adjusted_opening_balance=current_draft.adjusted_opening_balance,
                        add_cash_amount=current_draft.cash_addition,
                        cash_from_type="shop",
                        add_cash_bank_account_id=current_draft.withdrawal_bank_account,
                        xero_organiztion_id=current_user.xero_entity_id,
                        cashsale_total=current_draft.cash_sales or 0,
                        nocashsale_total=nocashsale_total or 0,
                        expense_total=total_expenses,
                    )
                    db.session.add(report_v2)
                    logger.info(
                        f"Created new ReportV2 {report_v2.report_id} with expense_total: {total_expenses}"
                    )

                # Insert report_expense_detail records for each expense
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
                    logger.info(
                        f"Added ReportExpenseDetail: {expense.id} -> {report_v2.report_id} = {expense.amount}"
                    )

                # Recalculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
                # Get cash sales from ReportSaleDetail with fallback to
                # current_draft.cash_sales
                cash_sales = get_cash_sales_from_detail(
                    current_draft.id, fallback_value=current_draft.cash_sales or 0.0)
                current_draft.closing_balance = (
                    current_draft.opening_balance
                    + (current_draft.cash_addition or 0)
                    + cash_sales
                    - current_draft.expenses
                    - (current_draft.bank_deposit or 0)
                )

                db.session.commit()

                # Log the expense addition to draft history
                log_history_draft(
                    report_draft_id=current_draft.id,
                    company=entity_id,
                    user_id=current_user.id,
                    action="added",
                    field_changed="expense",
                    old_value="previous_expenses",
                    new_value=f"Added {len(expenses)} expenses totaling: ${total_expenses}",
                )

                # Update draft progress to mark expenses section as complete
                # (only for save_next)
                if action_type == "save_next":
                    update_draft_progress(
                        current_draft, action_type, "expenses", "deposit"
                    )

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(
                        {
                            "status": "success",
                            "message": f"Expenses added successfully. Total: ${total_expenses}",
                            "redirect_url": url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ),
                        })
                else:
                    # Check action type and redirect accordingly
                    if action_type == "save_next":
                        return redirect(
                            url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))
                    elif action_type == "save_exit":
                        return redirect(
                            url_for(
                                "report.report_expense",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))
                    else:
                        # Default to save_next
                        return redirect(
                            url_for(
                                "report.report_deposit",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ))

        except ValueError as ve:
            print(f"Validation error: {ve}")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"status": "error", "message": str(ve)}), 400
            else:
                flash(str(ve), "danger")
                return redirect(url_for("report.report_expense"))

        except Exception as e:
            db.session.rollback()
            print(f"Error adding expenses: {str(e)}")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "An error occurred adding expenses.",
                        }
                    ),
                    500,
                )
            else:
                flash(
                    "Something went wrong adding those expenses. Mind trying again?",
                    "danger")
                return redirect(url_for("report.report_expense"))

    # Get transaction date from URL parameter or form data if provided,
    # otherwise use today
    selected_date = request.args.get("transaction_date") or request.form.get(
        "transaction_date"
    )

    if selected_date:
        try:
            transaction_date = datetime.strptime(
                selected_date, "%Y-%m-%d").date()
            logger.info(
                f"Expenses form - Using selected date from URL/form: {transaction_date}"
            )
        except ValueError:
            logger.warning(
                f"Expenses form - Invalid date format: {selected_date}, using today"
            )
            transaction_date = datetime.now().date()
    else:
        transaction_date = datetime.now().date()
        logger.info(
            f"Expenses form - No date provided, using today: {transaction_date}"
        )

    # If edit mode is enabled and no id provided, try to load existing report
    if is_edit_mode and not id:
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
        ).first()
        if existing_report:
            # Redirect to expense page with report id
            return redirect(
                url_for(
                    "report.report_expense",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )

    # Check for existing draft: by id when in URL, else by (entity,
    # transaction_date)
    if id:
        current_draft = ReportDraft.query.filter(
            ReportDraft.id == id,
            ReportDraft.company == entity_id,
            ReportDraft.status == "draft",
        ).first()
    else:
        current_draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.transaction_date == transaction_date,
            ReportDraft.status == "draft",
        ).first()

    logger.info("Expenses form - Looking for existing draft:")
    logger.info(f"  Company: {entity_id}")
    logger.info(f"  Transaction date: {transaction_date}")
    logger.info(f"  Username: {current_user.username}")
    logger.info(
        f"  Found existing draft: {current_draft.id if current_draft else 'None'}"
    )

    # Handle case where no draft exists
    if not current_draft and not is_edit_mode:
        flash(
            "I don't see a draft for today yet - let's start with the opening entry.",
            "warning",
        )
        return redirect(url_for("report.report_opening", entity_id=entity_id))

    # Get existing expenses for this draft
    existing_expenses = []
    if current_draft:
        existing_expenses = ShopExpenseDraft.query.filter_by(
            report_draft_id=current_draft.id
        ).all()

    # Get organization info for the template (if not already fetched)
    if not org:
        org = Entity.query.filter(Entity.id == entity_id).first()
    entity_acronym, display_date = get_entity_badge_data(org)

    # Don't reset current_section when viewing - it should only update when progressing forward
    # The stepper should always show the latest step reached, not the current
    # page

    # For new reports (no id parameter), always consider them as
    # latest/editable
    is_latest_report = True

    # Normalize expense file metadata so the template emits a clean JSON
    # array for each expense's data-expense-files attribute.
    expense_files_map = {
        expense.id: json.dumps(
            normalize_expense_files(expense.files, getattr(expense, "s3_key", None))
        )
        for expense in existing_expenses
    }

    return render_template(
        "report/expense.html",
        xero_contacts=xero_contacts,
        xero_accounts=xero_accounts,
        existing_expenses=existing_expenses,
        expense_files_map=expense_files_map,
        current_report=current_draft,
        current_draft=current_draft,
        header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
        org=org,
        transaction_date=transaction_date,
        current_section="expenses",  # Always set to current page
        completed_sections=(
            current_draft.completed_sections if current_draft else ["opening"]
        ),
        is_draft=True,
        draft_id=current_draft.id if current_draft else None,
        current_user=current_user,
        datenow=datetime.now(),
        is_latest_report=is_latest_report,
        entity_acronym=entity_acronym,
        display_date=display_date,
        is_edit_mode=is_edit_mode,
        DD_CLIENT_TOKEN=DD_CLIENT_TOKEN,
    )
