# Opening step: report_opening transferred from app.py (single function,
# no new functions).
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from blueprints.report import report_bp
from blueprints.report.services.history import log_history_draft
from blueprints.report.services.shared import (check_user_has_entities,
                                               ensure_report_row_for_draft,
                                               future_date_error,
                                               header_publishing_status_for,
                                               recalculate_report,
                                               resolve_report_entity_id,
                                               safe_float,
                                               update_draft_progress)
from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity, Report, ReportCashCountDraft, ReportDraft, db, tz
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.authz import permission_denied
from services.helpers.xero_bridge import (get_accounts_from_xero,
                                          get_entity_account_settings)
from services.permission_policy import Permission, has_permission
from utils import jsonify


def _onboarding_floor_date(entity_id):
    """The earliest date a first report may use: the onboarding opening date.

    Onboarding seeds an opening ReportDraft whose ``transaction_date`` is the
    date the user chose to start reporting from. That date is the floor for the
    first report (replaces the legacy "within 7 days from today" window).
    Returns a date, or None if no onboarding draft exists.
    """
    # Draft-only: this is the onboarding seed draft (seed_opening_draft).
    # Unfiltered, once drafts live in `report`, "earliest row for the entity"
    # would resolve to the oldest SUBMITTED report and move the floor date.
    opening_draft = (
        ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.status == "draft",
        )
        .order_by(ReportDraft.transaction_date.asc())
        .first()
    )
    return opening_draft.transaction_date if opening_draft else None


def _first_report_date_error(selected_date, today, entity_id):
    """Validate a first report's date.

    Floor is the onboarding date (the opening draft's transaction_date) so the
    rule is the same whether or not the user arrived straight from the
    onboarding wizard. Future dates are always rejected; the onboarding date is
    enforced as the lower bound when one exists. Returns an error message if out
    of range, else None.
    """
    future_err = future_date_error(selected_date, today)
    if future_err:
        return future_err

    onboarding_date = _onboarding_floor_date(entity_id)
    if onboarding_date and selected_date < onboarding_date:
        return (
            f"Transaction date must be on or after your onboarding date "
            f"({onboarding_date})."
        )
    return None


@report_bp.route("/report/opening", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/opening", methods=["GET"])
@report_bp.route("/entity/<string:entity_id>/report/opening",
                 methods=["GET", "POST"])
@login_required
def report_opening(id=None, entity_id=None):
    # Get entity_id from route parameter or query parameter
    if not entity_id:
        entity_id = request.args.get("entity_id")
    if not entity_id:
        entity_id = request.form.get("entity_id")
    if not entity_id:
        entity_id = resolve_report_entity_id(id)
    if not entity_id:
        # Diagnostic: pairs with the ENTITY-TRACE lines in ending.py. The
        # referrer tells us which page redirected here without an entity.
        logger.error(
            "ENTITY-TRACE report_opening BOUNCE - method=%s path=%s id=%s "
            "args=%r form_keys=%r referrer=%r",
            request.method,
            request.path,
            id,
            dict(request.args),
            list(request.form.keys()),
            request.referrer,
        )
        flash("I need to know which entity we're working with first!", "danger")
        return redirect(url_for("entity.entity_list"))
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return permission_denied(
            "You do not have permission to edit reports for this entity.",
            entity_id=entity_id,
        )
    if id:
        # The ReportDraft fallback that used to sit here is gone: since Stage 4a
        # every draft has a paired `report` row with the same id, so the first
        # lookup already covers drafts. Kept as one query, not two.
        report_for_access = Report.query.filter_by(id=id).first()
        if not report_for_access or str(report_for_access.company) != str(entity_id):
            flash("Hmm, I couldn't find that report.", "danger")
            return redirect(url_for("entity.report_dashboard", id=entity_id))
    is_latest_report = False

    # Check if edit mode is enabled
    is_edit_mode = (request.args.get("edit") ==
                    "true" or request.form.get("edit") == "true")

    # Users arriving straight from onboarding are setting the date they want to
    # start reporting from, so the usual "within 7 days from today" guard for a
    # first report must not block their chosen opening date.
    #
    # Onboarding flags this on the inbound GET; we record it in the server
    # session (scoped to this entity) and immediately redirect to a clean URL,
    # so the internal flag never lingers in the address bar or the form. The
    # flag survives the Save & Next POST via the session and is cleared once the
    # opening entry is saved.
    if request.method == "GET" and request.args.get("from_onboarding") == "1":
        session["onboarding_opening_entity"] = str(entity_id)
        clean_args = {k: v for k, v in request.args.items()
                      if k != "from_onboarding"}
        return redirect(url_for("report.report_opening", **clean_args))

    from_onboarding = (
        session.get("onboarding_opening_entity") == str(entity_id)
    )

    toast = {
        "message": request.args.get("toast_message"),
        "type": request.args.get("toast_type"),
    }

    deposit_type = request.args.get("deposit_type") or ""

    request.form.get("withdrawal")
    request.form.get("bank_account")
    _pettycash_settings = (
        get_entity_account_settings(entity_id, "pettycash") or {}
    )
    main_bank_account = _pettycash_settings.get("xero_account_id")

    _bank_settings = get_entity_account_settings(entity_id, "bank") or {}
    company_bank = _bank_settings.get("xero_account_id")

    logger.info(f"Toast: {toast}")

    # Check if user has any entities before allowing access to reports
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you any reports.",
            "warning")
        return redirect(url_for("entity.entity_list"))

    # Get selected date from query parameter or form data if provided
    selected_date = request.args.get("transaction_date") or request.form.get(
        "transaction_date"
    )
    if selected_date and not id:
        try:
            selected_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            if not id and request.method == "POST":
                # Use Hong Kong time so the date boundary matches the users'
                # local midnight, not the server's (UTC) midnight.
                today = datetime.now(tz).date()

                # Fetch the last submitted report to validate date
                last_report = (
                    Report.query.filter_by(company=entity_id)
                    .order_by(Report.transaction_date.desc())
                    .first()
                )

                # No report may start on a date after today, regardless of how
                # many prior reports exist.
                future_err = future_date_error(selected_date, today)
                if future_err:
                    logger.warning(
                        f"Transaction date {selected_date} rejected: {future_err}"
                    )
                    flash(future_err, "error")
                    if entity_id:
                        return redirect(
                            url_for("entity.report_dashboard", id=entity_id))
                    return redirect(url_for("entity.entity_list"))

                # Validate based on business rules
                if last_report:
                    # If reports exist: only the day after the last submitted
                    # report is allowed (consecutive days, no gaps).
                    expected_date = last_report.transaction_date + timedelta(days=1)
                    if expected_date > today:
                        logger.warning(
                            f"Next report date {expected_date} is in the future (today {today})"
                        )
                        flash(
                            "Transaction date cannot be in the future. "
                            f"You can only create reports for dates up to {today}.", "danger",
                        )
                        if entity_id:
                            return redirect(
                                url_for(
                                    "entity.report_dashboard",
                                    id=entity_id))
                        else:
                            return redirect(url_for("entity.entity_list"))
                    if selected_date != expected_date:
                        logger.warning(
                            f"Transaction date {selected_date} is not the day after the last submitted report date {last_report.transaction_date}"
                        )
                        flash(
                            f"Reports go one day at a time - this one needs to be {expected_date}, the day after your last submitted report ({last_report.transaction_date}).", "danger",
                        )
                        if entity_id:
                            return redirect(
                                url_for(
                                    "entity.report_dashboard",
                                    id=entity_id))
                        else:
                            return redirect(url_for("entity.entity_list"))
                else:
                    # No reports exist: the first report may start on or after
                    # the onboarding date (no 7-day floor), up to today. Same
                    # rule whether or not the user came straight from onboarding.
                    first_err = _first_report_date_error(
                        selected_date, today, entity_id
                    )
                    if first_err:
                        logger.warning(
                            f"First report date {selected_date} rejected: {first_err}"
                        )
                        flash(first_err, "danger")
                        if entity_id:
                            return redirect(
                                url_for(
                                    "entity.report_dashboard",
                                    id=entity_id))
                        else:
                            return redirect(url_for("entity.entity_list"))
        except ValueError:
            flash("That date doesn't look quite right! Please check the format and try again.", "danger")
            selected_date = None
    elif selected_date and id:
        try:
            selected_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None

    # Get entity and bank accounts for the template
    entity = Entity.query.filter(Entity.id == entity_id).first()

    # Prepare display metadata for headers
    entity_acronym = build_entity_acronym(entity.name) if entity else ""

    display_date = None
    if entity and entity.created_at:
        if isinstance(entity.created_at, datetime):
            display_date = entity.created_at.date()
        else:
            display_date = entity.created_at

    # Check if entity exists
    if not entity:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Use entity owner's Xero token so any user can load report opening
    token_user = get_xero_token_user_for_entity(entity_id)
    if ensure_valid_token(token_user):
        bank_accounts = get_accounts_from_xero(
            token_user.access_token,
            entity.xero_org_id,
            where='Type="BANK"',
            order="Code ASC, Name ASC",
            token_validated=True,
        )
    else:
        bank_accounts = []

    # Ensure bank_accounts is never None BEFORE using it
    if bank_accounts is None:
        logger.warning("bank_accounts is None, defaulting to empty list")
        bank_accounts = []

    pettycash_bank_account = (
        get_entity_account_settings(entity_id, "pettycash") or {}
    ).get("xero_account_id")
    # Remove pettycashaccount from bank_accounts
    bank_accounts = [
        account
        for account in bank_accounts
        if account.get("AccountID") != pettycash_bank_account
    ]

    # If edit mode is enabled and no id provided, try to load existing report
    # (any report for this date)
    if is_edit_mode and not id and selected_date:
        # Edit mode targets a SUBMITTED report — drafts live in `report` too
        # since Stage 4a.
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == selected_date,
            Report.status != "draft",
        ).first()
        if existing_report:
            # Redirect to opening page with report id
            return redirect(
                url_for(
                    "report.report_opening",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )

    # When a specific report/draft id is provided, load that draft by id first
    existing_draft = None
    if id:
        # Reads `report` rather than report_draft: the draft->report mirror
        # keeps the paired row current, and every field consumed below
        # (opening_balance, withdrawal_*, completed_sections) lives on both.
        # status == "draft" is what still makes this a DRAFT lookup.
        draft_by_id = Report.query.filter(
            Report.id == id,
            Report.company == entity_id,
            Report.status == "draft",
        ).first()
        if draft_by_id:
            existing_draft = draft_by_id
    if existing_draft is None and selected_date:
        # No id or no draft for that id: find any draft for (entity,
        # transaction_date)
        existing_draft = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == selected_date,
            Report.status == "draft",
        ).first()

    if id and not existing_draft:
        # Was a two-entity full outer join filtering BOTH ids to `id`, which
        # collapsed to an inner join and returned nothing whenever either row
        # was missing. withdrawal_type and withdrawal_bank_account live on
        # `report` since r1a01, so one table answers the whole question.
        report = Report.query.filter(Report.id == id).first()
        if report:
            default_report = {
                "adjusted_opening_balance": report.opening_balance,
                "cash_addition": 0,
                "withdrawal": report.withdrawal_type or "personal",
                "bank_account": report.withdrawal_bank_account or "",
            }
            # Determine if this is the latest report (most recent
            # transaction_date) or old report
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

            is_latest_report = report.transaction_date == latest_report_date

            yesterday_report = (
                Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date < report.transaction_date,
                )
                .order_by(Report.transaction_date.desc())
                .first()
            )

            yesterday_closing_balance = (
                yesterday_report.closing_balance
                if yesterday_report and yesterday_report.closing_balance is not None
                else 0
            )
            safebox_balance = (
                yesterday_report.safe_box_balance
                if yesterday_report and yesterday_report.safe_box_balance is not None
                else 0
            )

            template_data = {
                "opening_balance": report.opening_balance,
                "report": default_report,
                "next_transaction_date": report.next_transaction_date,
                "is_first_report": False,
                "is_draft": False,
                "draft_id": report_draft.id,
                # For new reports, start with opening as current and no
                # completed sections
                "current_section": "opening",  # Always set to current page
                "completed_sections": report_draft.completed_sections,
                "bank_accounts": bank_accounts,
                "withdrawal_type": (
                    report_draft.withdrawal_type
                    if report_draft.withdrawal_type
                    else "personal"
                ),
                "withdrawal_bank_account": (
                    report_draft.withdrawal_bank_account
                    if report_draft.withdrawal_bank_account
                    else ""
                ),
            }

            return render_template(
                "report/opening.html",
                current_user=current_user,
                opening_balance=template_data["opening_balance"],
                report=template_data["report"],
                next_transaction_date=template_data["next_transaction_date"],
                selected_date=selected_date,  # Pass the selected date from URL parameter
                is_first_report=template_data["is_first_report"],
                current_draft=report,
                header_publishing_status=header_publishing_status_for(report_id=(report.id if report else None)),
                org=entity,
                datenow=datetime.now(),
                is_draft=template_data["is_draft"],
                draft_id=template_data["draft_id"],
                # Add stepper data for dynamic progress display
                current_section=template_data["current_section"],
                completed_sections=template_data["completed_sections"],
                bank_accounts=template_data["bank_accounts"],
                transaction_date=report.transaction_date,
                is_latest_report=is_latest_report,
                withdrawal_type=template_data["withdrawal_type"],
                withdrawal_bank_account=template_data["withdrawal_bank_account"],
                entity_acronym=entity_acronym,
                display_date=display_date,
                is_edit_mode=is_edit_mode,
                yesterday_closing_balance=yesterday_closing_balance,
                safebox_balance=safebox_balance,
            )
        # If join_result was None (e.g. id is draft-only), fall through to use
        # existing_draft

    if request.method == "POST":
        try:
            # Debugging logs
            logger.info(
                f"Opening form submission started for user: {current_user.username}, entity_id: {entity_id}"
            )
            logger.info(
                f"Opening form data: {request.form.to_dict(flat=False)}")

            if not entity_id:
                flash(
                    "I need to know which entity we're working with first!",
                    "danger",
                )
                return redirect(url_for("entity.entity_list"))

            # Get form data for opening portion
            opening_balance = safe_float(
                request.form.get("opening_balance", 0))
            cash_addition = safe_float(request.form.get("cash_addition", 0))

            # Parse transaction date with logging
            transaction_date_str = request.form.get("transaction_date")
            logger.info(
                f"Opening form - Transaction date string from form: {transaction_date_str}"
            )
            if not transaction_date_str:
                raise ValueError("Missing transaction date")
            try:
                transaction_date = datetime.strptime(
                    transaction_date_str, "%Y-%m-%d"
                ).date()
                logger.info(
                    f"Opening form - Successfully parsed transaction date: {transaction_date}"
                )
            except ValueError as e:
                logger.error(
                    f"Opening form - Failed to parse transaction date '{transaction_date_str}': {e}"
                )
                raise ValueError(
                    f"Invalid transaction date format: {transaction_date_str}"
                )

            if (opening_balance + cash_addition) < 0:
                flash(
                    "Hmm, it looks like your cash balance is negative. Could you fix that first?",
                    "danger",
                )
                return redirect(
                    url_for(
                        "report.report_opening",
                        entity_id=entity_id,
                        transaction_date=transaction_date_str,
                    )
                )

            withdrawal = request.form.get("withdrawal")
            bank_account = request.form.get("bank_account")
            action_type = request.form.get("action_type", "save_next")

            logger.info(
                f"Form data parsed - opening_balance: {opening_balance}, cash_addition: {cash_addition}, withdrawal: {withdrawal}, bank_account: {bank_account}, action_type: {action_type}"
            )

            # Check if any report already exists for this (entity, date) ??one
            # report per date
            logger.info(
                f"Checking for existing report on date {transaction_date} for company {entity_id}"
            )
            # status != 'draft' is load-bearing. This guard means "has a report
            # already been SUBMITTED for this date". Since drafts now live in
            # `report` too (Stage 4a), an unfiltered match also finds the
            # user's own in-progress draft and refuses to let them continue it.
            existing_report = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
                Report.status != "draft",
            ).first()

            if existing_report and not is_edit_mode:
                logger.warning(
                    f"Report already exists for date {transaction_date}: {existing_report.id}"
                )
                raise ValueError(
                    f"A report for {transaction_date} already exists. Please delete it first."
                )

            # If edit mode is enabled and report exists, update it
            if is_edit_mode and existing_report:
                logger.info(
                    f"Edit mode enabled - updating existing report {existing_report.id} for date {transaction_date}"
                )
                # Update the existing report
                existing_report.opening_balance = opening_balance
                existing_report.cash_addition = cash_addition
                existing_report.adjusted_opening_balance = (
                    opening_balance + cash_addition
                )
                existing_report.date = datetime.now(tz)

                # Update or create draft
                report_draft = ReportDraft.query.filter(
                    ReportDraft.id == existing_report.id
                ).first()
                if not report_draft:
                    report_draft = ReportDraft(
                        id=existing_report.id,
                        transaction_date=existing_report.transaction_date,
                        next_transaction_date=existing_report.next_transaction_date,
                        opening_balance=opening_balance,
                        cash_addition=cash_addition,
                        adjusted_opening_balance=opening_balance +
                        cash_addition,
                        uploaded_by=existing_report.uploaded_by,
                        company=existing_report.company,
                        status="draft",
                    )
                    db.session.add(report_draft)
                else:
                    report_draft.opening_balance = opening_balance
                    report_draft.cash_addition = cash_addition
                    report_draft.adjusted_opening_balance = (
                        opening_balance + cash_addition
                    )

                report_draft.withdrawal_type = withdrawal
                report_draft.withdrawal_bank_account = bank_account

                # Ensure opening is in completed sections
                if not report_draft.completed_sections:
                    report_draft.completed_sections = []
                if "opening" not in report_draft.completed_sections:
                    report_draft.completed_sections.append("opening")
                flag_modified(report_draft, "completed_sections")

                db.session.commit()
                logger.info(
                    f"Updated report {existing_report.id} in edit mode")
            else:
                # When id is provided (e.g. from URL), load that specific
                # draft; else find any draft for (entity, date)
                draft_id_param = id or request.form.get("draft_id")
                if draft_id_param:
                    existing_draft = ReportDraft.query.filter(
                        ReportDraft.id == draft_id_param,
                        ReportDraft.company == entity_id,
                        ReportDraft.status == "draft",
                    ).first()
                else:
                    existing_draft = ReportDraft.query.filter(
                        ReportDraft.company == entity_id,
                        ReportDraft.transaction_date == transaction_date,
                        ReportDraft.status == "draft",
                    ).first()

            if existing_draft and not (is_edit_mode and existing_report):
                logger.info(
                    f"Found existing draft {existing_draft.id} for date {transaction_date}, updating it"
                )
                # Update existing draft - preserve all existing data, only
                # update opening fields; track last editor
                report_draft = existing_draft
                report_draft.uploaded_by = current_user.username
                report_draft.opening_balance = opening_balance
                report_draft.cash_addition = cash_addition
                report_draft.adjusted_opening_balance = opening_balance + cash_addition
                report_draft.next_transaction_date = transaction_date + \
                    timedelta(days=1)
                logger.info(
                    f"Updating existing draft {report_draft.id} for opening data"
                )
            else:
                # Before creating a new draft: ensure no report and no other
                # draft for this (entity, date)
                # Submitted reports only — see the note above. Without the
                # status filter this finds the draft-shaped report row that
                # ensure_report_row_for_draft created moments earlier.
                any_report_for_date = Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date == transaction_date,
                    Report.status != "draft",
                ).first()
                if any_report_for_date:
                    logger.warning(
                        f"Report already submitted for date {transaction_date}, not creating draft"
                    )
                    raise ValueError(
                        f"A report for {transaction_date} already exists."
                    )
                any_draft_for_date = ReportDraft.query.filter(
                    ReportDraft.company == entity_id,
                    ReportDraft.transaction_date == transaction_date,
                    ReportDraft.status == "draft",
                ).first()
                if any_draft_for_date:
                    report_draft = any_draft_for_date
                    report_draft.uploaded_by = current_user.username
                    report_draft.opening_balance = opening_balance
                    report_draft.cash_addition = cash_addition
                    report_draft.adjusted_opening_balance = (
                        opening_balance + cash_addition
                    )
                    report_draft.next_transaction_date = transaction_date + \
                        timedelta(days=1)
                    report_draft.withdrawal_type = withdrawal
                    report_draft.withdrawal_bank_account = bank_account
                    if not report_draft.completed_sections:
                        report_draft.completed_sections = []
                    if "opening" not in report_draft.completed_sections:
                        report_draft.completed_sections.append("opening")
                    flag_modified(report_draft, "completed_sections")
                    logger.info(
                        f"Reusing existing draft {report_draft.id} for date {transaction_date}"
                    )
                else:
                    logger.info(
                        f"No existing draft found, creating new draft for date {transaction_date}"
                    )
                    # Fetch the last report to determine next transaction date
                    last_report = (
                        Report.query.filter_by(company=entity_id)
                        .order_by(Report.transaction_date.desc())
                        .first()
                    )
                    logger.info(
                        f"Last report found: {last_report.id if last_report else 'None'} on date {last_report.transaction_date if last_report else 'N/A'}"
                    )

                    # Determine the expected date and validate transaction_date.
                    # Hong Kong time so the "future" boundary is the users' local
                    # midnight, not the server's (UTC) midnight.
                    today = datetime.now(tz).date()
                    if last_report:
                        # If a report has been submitted, only the day after the
                        # submitted date is allowed (consecutive days, no gaps).
                        expected_date = last_report.transaction_date + timedelta(days=1)
                        if expected_date > today:
                            logger.warning(
                                f"Next report date {expected_date} is in the future (today {today})"
                            )
                            flash(
                                "Transaction date cannot be in the future. "
                                f"You can only create reports for dates up to {today}.",
                                "danger",
                            )
                            if entity_id:
                                return redirect(
                                    url_for(
                                        "entity.report_dashboard",
                                        id=entity_id))
                            else:
                                return redirect(url_for("entity.entity_list"))
                        if transaction_date != expected_date:
                            logger.warning(
                                f"Transaction date {transaction_date} is not the day after the last submitted report date {last_report.transaction_date}"
                            )
                            flash(
                                f"Reports go one day at a time - this one needs to be {expected_date}, the day after your last submitted report ({last_report.transaction_date}).",
                                "danger",
                            )
                            if entity_id:
                                return redirect(
                                    url_for(
                                        "entity.report_dashboard",
                                        id=entity_id))
                            else:
                                return redirect(url_for("entity.entity_list"))

                        next_transaction_date = transaction_date + \
                            timedelta(days=1)
                    else:
                        logger.info(
                            "No previous reports found; this is the first report."
                        )
                        today = datetime.now(tz).date()

                        # First report: may start on or after the onboarding
                        # date (no 7-day floor), up to today. Same rule whether
                        # or not the user arrived straight from onboarding.
                        first_err = _first_report_date_error(
                            transaction_date, today, entity_id
                        )
                        if first_err:
                            logger.warning(
                                f"First report date {transaction_date} rejected: {first_err}"
                            )
                            flash(first_err, "danger")
                            if entity_id:
                                return redirect(
                                    url_for(
                                        "entity.report_dashboard",
                                        id=entity_id))
                            else:
                                return redirect(url_for("entity.entity_list"))

                        next_transaction_date = transaction_date + \
                            timedelta(days=1)

                    # Calculate adjusted opening balance
                    adjusted_opening_balance = opening_balance + cash_addition

                    # Create new draft
                    report_draft = ReportDraft(
                        transaction_date=transaction_date,
                        next_transaction_date=next_transaction_date,
                        opening_balance=opening_balance,
                        cash_addition=cash_addition,
                        adjusted_opening_balance=adjusted_opening_balance,
                        # Set all sales to 0 for opening entry
                        cash_sales=0.0,
                        shop_sales=0.0,
                        delivery_sales=0.0,
                        total_sales=0.0,
                        expenses=0.0,
                        bank_deposit=0.0,
                        closing_balance=adjusted_opening_balance,
                        # Initialize progress tracking
                        current_section="opening",
                        completed_sections=[],
                        uploaded_by=current_user.username,
                        withdrawal_type=withdrawal,
                        withdrawal_bank_account=bank_account,
                        company=entity_id,
                        status="draft",
                    )
                db.session.add(report_draft)
                # Pair the draft with a report row (Stage 4a) so the sales and
                # expense steps write detail rows under an id that already
                # exists in `report`. flush() first: the draft on the new-draft
                # branch has no id until then.
                db.session.flush()
                ensure_report_row_for_draft(report_draft)
                logger.info(
                    f"Creating new draft {report_draft.id} with opening data and all sections initialized to 0.0"
                )

            # Save the draft
            db.session.commit()

            logger.info(
                f"Successfully saved draft {report_draft.id} for date {transaction_date}"
            )
            logger.info("Opening form - Draft details:")
            logger.info(f"  ID: {report_draft.id}")
            logger.info(f"  Company: {report_draft.company}")
            logger.info(f"  Transaction date: {report_draft.transaction_date}")
            logger.info(f"  Username: {report_draft.uploaded_by}")
            logger.info(f"  Status: {report_draft.status}")

            # Store withdrawal information for later use when publishing to
            # Xero
            if withdrawal and bank_account:
                report_draft.withdrawal_type = withdrawal
                report_draft.withdrawal_bank_account = bank_account
                logger.info(
                    f"Set withdrawal info: type={withdrawal}, bank_account={bank_account}"
                )

            # Update progress tracking
            update_draft_progress(
                report_draft, action_type, "opening", "sales")
            logger.info(
                f"Updated progress tracking for draft {report_draft.id}")

            # Commit progress updates
            db.session.commit()

            # Onboarding hand-off is done once the opening entry is saved —
            # drop the session flag so later reports use the normal date rules.
            if from_onboarding:
                session.pop("onboarding_opening_entity", None)

            # Debug: Check what was actually saved to database
            db.session.refresh(report_draft)
            print(
                f"DEBUG: After commit - current_section: {report_draft.current_section}"
            )
            print(
                f"DEBUG: After commit - completed_sections: {report_draft.completed_sections}"
            )
            print(
                f"DEBUG: After commit - completed_sections type: {type(report_draft.completed_sections)}"
            )
            print(
                f"DEBUG: After commit - completed_sections length: {len(report_draft.completed_sections) if report_draft.completed_sections else 0}"
            )

            # Additional debug: Check if the field is actually in the session
            print(
                f"DEBUG: Session dirty objects: {[obj for obj in db.session.dirty]}")
            print(
                f"DEBUG: Session new objects: {[obj for obj in db.session.new]}")

            # Log the opening entry to draft history
            log_history_draft(
                report_draft_id=report_draft.id,
                company=entity_id,
                user_id=current_user.id,
                action="created" if not existing_draft else "updated",
                field_changed="opening_entry",
                old_value="None" if not existing_draft else "previous_opening_state",
                new_value=f"Opening: {opening_balance}, Addition: {cash_addition}, Adjusted: {opening_balance + cash_addition}",
            )

            # Check if the request is AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                if action_type == "save_next":
                    return jsonify(
                        {
                            "status": "success",
                            "redirect_url": url_for(
                                "report.report_sale",
                                entity_id=entity_id,
                                transaction_date=transaction_date.strftime("%Y-%m-%d"),
                            ),
                        })
                else:  # save_exit
                    return jsonify(
                        {
                            "status": "success",
                            "redirect_url": url_for(
                                "entity.report_dashboard", id=entity_id
                            ),
                        }
                    )
            else:
                if action_type == "save_next":
                    return redirect(
                        url_for(
                            "report.report_sale",
                            entity_id=entity_id,
                            transaction_date=transaction_date.strftime("%Y-%m-%d"),
                        ))
                else:  # save_exit
                    return redirect(
                        url_for(
                            "entity.report_dashboard",
                            id=entity_id))

        except ValueError as ve:
            logger.error(f"Validation error in opening form: {ve}")
            print(f"Validation error: {ve}")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"status": "error", "message": str(ve)}), 400
            else:
                flash(str(ve), "danger")
                return redirect(url_for("report.report_opening"))

        except Exception as e:
            # Rollback on error
            db.session.rollback()
            logger.error(
                f"Unexpected error during opening entry creation: {str(e)}",
                exc_info=True,
            )
            print(f"Error during opening entry creation: {str(e)}")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return (
                    jsonify({"status": "error", "message": "Something went wrong on my end. Mind trying again?"}),
                    500,
                )
            else:
                flash("Something went wrong on my end. Mind trying again?", "danger")
                return redirect(url_for("report.report_opening"))

    # For GET request, check for existing drafts first
    # If we have a selected date and found an existing draft for it, use that
    # Otherwise, check for existing drafts for today or recent dates
    if not existing_draft:
        if selected_date:
            # If user selected a specific date but no draft exists for that date,
            # we need to create a new draft for that date
            logger.info(
                f"No existing draft found for selected date {selected_date}, will create new one"
            )
            # Don't look for other drafts, we want to create one for the
            # selected date
        else:
            today = datetime.now(tz).date()

            # Try to find an existing draft for this entity (any user) in the
            # last 7 days
            existing_draft = (
                # GET-path read, migrated to `report` (mirror keeps it current).
                Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date
                    # Look back 7 days for recent drafts
                    >= today - timedelta(days=7),
                    Report.status == "draft",
                )
                .order_by(Report.transaction_date.desc())
                .first()
            )
    if existing_draft:
        # User has an existing draft, use that data
        opening_balance = existing_draft.opening_balance or 0
        next_transaction_date = existing_draft.next_transaction_date
        is_first_report = False

        # For existing drafts, always consider them as latest/editable (KISS
        # approach)
        is_latest_report = True

        yesterday_report = (
            Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date < existing_draft.transaction_date,
            )
            .order_by(Report.transaction_date.desc())
            .first()
        )

        yesterday_closing_balance = (
            yesterday_report.closing_balance
            if yesterday_report and yesterday_report.closing_balance is not None
            else 0
        )
        safebox_balance = (
            yesterday_report.safe_box_balance
            if yesterday_report and yesterday_report.safe_box_balance is not None
            else 0
        )

        # Prepare draft data for the template
        draft_report = {
            "adjusted_opening_balance": existing_draft.adjusted_opening_balance or 0,
            "cash_addition": existing_draft.cash_addition or 0,
            "withdrawal": (
                existing_draft.withdrawal_type
                if existing_draft.withdrawal_type
                else "personal"
            ),
            "bank_account": (
                existing_draft.withdrawal_bank_account
                if existing_draft.withdrawal_bank_account
                else ""
            ),
        }

        # Use draft data - ensure we get the most current completed_sections
        template_data = {
            "opening_balance": opening_balance,
            "report": draft_report,
            # Use draft's transaction date
            "next_transaction_date": existing_draft.transaction_date,
            "is_first_report": False,
            "is_draft": True,
            "draft_id": existing_draft.id,
            # Always use the current draft data for stepper
            "current_section": "opening",  # Always set to current page
            "completed_sections": existing_draft.completed_sections or [],
            "bank_accounts": bank_accounts,
            "withdrawal_type": (
                existing_draft.withdrawal_type
                if existing_draft.withdrawal_type
                else "personal"
            ),
            "withdrawal_bank_account": (
                existing_draft.withdrawal_bank_account
                if existing_draft.withdrawal_bank_account
                else ""
            ),
        }

    else:
        # No existing draft, find the latest report before the selected date
        if selected_date:
            # Find the latest report before the selected date
            last_report = (
                Report.query.filter(
                    Report.company == entity_id,
                    Report.transaction_date < selected_date) .order_by(
                    Report.transaction_date.desc()) .first())

            # Draft-only: the paired `last_report` query above is already the
            # Report side of this pair, so leaving it unfiltered would make the
            # two resolve to the same row once the tables merge, and the
            # bank_deposit adjustment below would be applied twice.
            last_draft_report = (
                ReportDraft.query.filter(
                    ReportDraft.company == entity_id,
                    ReportDraft.transaction_date < selected_date,
                    ReportDraft.status == "draft",
                )
                .order_by(ReportDraft.transaction_date.desc())
                .first()
            )

            if deposit_type and deposit_type == "no change":
                if last_report:
                    last_report.bank_deposit -= last_report.bank_deposit
                    recalculate_report(last_report)
                if last_draft_report:
                    last_draft_report.bank_deposit -= last_draft_report.bank_deposit
                    recalculate_report(last_draft_report)
                if last_report or last_draft_report:
                    db.session.commit()

            # Get opening balance from previous day's closing balance (calculated value)
            # Fallback to cash count balance for backward compatibility with
            # old data
            if last_report:
                # Prioritize closing_balance (calculated value) over
                # actual_cash_total (physical count)
                if last_report.closing_balance is not None:
                    opening_balance = last_report.closing_balance
                    logger.info(
                        f"Using previous day's closing balance as opening balance: {opening_balance} (from report {last_report.id})"
                    )
                else:
                    # Fallback to cash count for backward compatibility with
                    # old data
                    last_cashcount = ReportCashCountDraft.query.filter(
                        ReportCashCountDraft.report_id == last_report.id
                    ).first()
                    if last_cashcount and last_cashcount.actual_cash_total is not None:
                        opening_balance = last_cashcount.actual_cash_total
                        logger.info(
                            f"Using previous day's cash count balance as opening balance (fallback): {opening_balance} (from report {last_report.id})"
                        )
                    else:
                        opening_balance = 0
                        logger.info(
                            f"No closing balance or cash count data found, defaulting opening balance to 0 (from report {last_report.id})"
                        )
            else:
                opening_balance = 0
        else:
            # No selected date, use the latest report overall
            last_report = (
                Report.query.filter_by(company=entity_id)
                .order_by(Report.transaction_date.desc())
                .first()
            )
            # Get opening balance from previous day's closing balance (calculated value)
            # Fallback to cash count balance for backward compatibility with
            # old data
            if last_report:
                # Prioritize closing_balance (calculated value) over
                # actual_cash_total (physical count)
                if last_report.closing_balance is not None:
                    opening_balance = last_report.closing_balance
                    logger.info(
                        f"Using previous day's closing balance as opening balance: {opening_balance} (from report {last_report.id})"
                    )
                else:
                    # Fallback to cash count for backward compatibility with
                    # old data
                    last_cashcount = ReportCashCountDraft.query.filter(
                        ReportCashCountDraft.report_id == last_report.id
                    ).first()
                    if last_cashcount and last_cashcount.actual_cash_total is not None:
                        opening_balance = last_cashcount.actual_cash_total
                        logger.info(
                            f"Using previous day's cash count balance as opening balance (fallback): {opening_balance} (from report {last_report.id})"
                        )
                    else:
                        opening_balance = 0
                        logger.info(
                            f"No closing balance or cash count data found, defaulting opening balance to 0 (from report {last_report.id})"
                        )
            else:
                opening_balance = 0

        # Use selected date if provided, otherwise calculate next transaction
        # date
        if selected_date:
            next_transaction_date = selected_date
        else:
            next_transaction_date = (
                (last_report.transaction_date + timedelta(days=1))
                if last_report
                else None
            )

        is_first_report = last_report is None

        # For new reports (no id parameter), always consider them as
        # latest/editable
        is_latest_report = True

        # Prepare production data for the template
        default_report = {
            "adjusted_opening_balance": opening_balance,
            "cash_addition": 0,
            "withdrawal": "personal",
            "bank_account": "",
        }

        yesterday_closing_balance = (
            last_report.closing_balance
            if last_report and last_report.closing_balance is not None
            else 0
        )
        safebox_balance = (
            last_report.safe_box_balance
            if last_report and last_report.safe_box_balance is not None
            else 0
        )

        # Use production data
        template_data = {
            "opening_balance": opening_balance,
            "report": default_report,
            "next_transaction_date": next_transaction_date,
            "is_first_report": is_first_report,
            "is_draft": False,
            "draft_id": None,
            # For new reports, start with opening as current and no completed
            # sections
            "current_section": "opening",
            "completed_sections": [],
            "withdrawal_type": "personal",
            "withdrawal_bank_account": "",
        }

    personal_bank_account = get_entity_account_settings(
        str(entity_id), "pettycash")

    # Don't reset current_section when viewing - it should only update when progressing forward
    # The stepper should always show the latest step reached, not the current
    # page

    return render_template(
        "report/opening.html",
        current_user=current_user,
        opening_balance=template_data["opening_balance"],
        report=template_data["report"],
        next_transaction_date=template_data["next_transaction_date"],
        is_first_report=template_data["is_first_report"],
        current_draft=existing_draft,
        header_publishing_status=header_publishing_status_for(report_id=(existing_draft.id if existing_draft else None)),
        org=entity,
        datenow=datetime.now(),
        is_draft=template_data["is_draft"],
        draft_id=template_data["draft_id"],
        main_bank_account=main_bank_account,
        company_bank=company_bank,
        # Add stepper data for dynamic progress display
        current_section="opening",  # Always set to current page regardless of database value
        completed_sections=existing_draft.completed_sections if existing_draft else [],
        bank_accounts=bank_accounts,
        personal_bank_account=personal_bank_account,
        is_latest_report=is_latest_report,
        selected_date=selected_date,  # Pass the selected date from URL parameter
        transaction_date=(
            selected_date
            if selected_date
            else (existing_draft.transaction_date if existing_draft else None)
        ),
        entity_acronym=entity_acronym,
        display_date=display_date,
        is_edit_mode=is_edit_mode,
        yesterday_closing_balance=yesterday_closing_balance,
        safebox_balance=safebox_balance,
    )
