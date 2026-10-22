# Opening step: report_opening transferred from app.py (single function,
# no new functions).
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from services.app_runtime.log import logger
from sqlalchemy.orm.attributes import flag_modified

from blueprints.report import report_bp
from blueprints.report.services.opening import (OpeningRefused, find_draft,
                                                first_report_date_error,
                                                first_report_opening, onboarding_floor_date,
                                                opening_state, save_opening)
from blueprints.report.services.shared import (check_user_has_entities,
                                               future_date_error,
                                               header_publishing_status_for,
                                               recalculate_report,
                                               resolve_report_entity_id,
                                               safe_float)
from blueprints.shared.entity_display import build_entity_acronym
from models.db import Entity, Report, db, tz
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.authz import permission_denied
from services.helpers.xero_bridge import (get_accounts_from_xero,
                                          get_entity_account_settings)
from services.permission_policy import Permission, has_permission
from utils import jsonify


# The date rules, what the page shows and the save live in blueprints/report/services/opening.py,
# shared with the Petty Cash API (minty-petty-cash-web); these names are kept for the code below.
_onboarding_floor_date = onboarding_floor_date
_first_report_date_error = first_report_date_error


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/new/opening", methods=["GET", "POST"])
@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/<string:id>/opening", methods=["GET"])
@report_bp.route("/report/opening", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/opening", methods=["GET"])
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

    deposit_type = request.args.get("deposit_type") or ""

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
                    # SUBMITTED only. The error this drives says "the day after your
                    # last submitted report" — but since Stage 4a a draft also lives
                    # in `report`, so unfiltered this treats the user's OWN
                    # in-progress draft as the last submitted report and demands the
                    # next day, bouncing them off their own report.
                    Report.query.filter(
                        Report.company == entity_id,
                        db.or_(Report.status.is_(None), Report.status != "draft"),
                    )
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
            db.or_(Report.status.is_(None), Report.status != "draft"),
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
        # was missing. withdrawal_type lives on `report` (cash_addition_type), so
        # one table answers the whole question.
        report = Report.query.filter(Report.id == id).first()
        if report:
            default_report = {
                "adjusted_opening_balance": report.opening_balance,
                "cash_addition": 0,
                "withdrawal": report.withdrawal_type or "personal",
                "bank_account": "",  # the main bank account on the settings, not per report
            }
            # Determine if this is the latest report (most recent
            # transaction_date) or old report
            latest_report_date = (
                db.session.query(db.func.max(Report.transaction_date))
                .filter(Report.company == entity_id)
                .scalar())

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
                # These six read `report`, not `report_draft`.
                #
                # `report_draft` is never assigned in this branch — it is bound
                # much further down, inside the POST handler — so every one of
                # these raised UnboundLocalError. This branch is the
                # "view a SUBMITTED report's opening page" path, which is why
                # it went unnoticed: it needs a report id whose row is not a
                # draft. Pre-existing, not introduced by the consolidation.
                #
                # `report` is the right source regardless: draft and report are
                # one row, and all four fields live on it.
                "draft_id": report.id,
                # For new reports, start with opening as current and no
                # completed sections
                "current_section": "opening",  # Always set to current page
                "completed_sections": report.completed_sections or [],  # NULL on legacy drafts
                "bank_accounts": bank_accounts,
                "withdrawal_type": report.withdrawal_type or "personal",
                "withdrawal_bank_account": "",
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

            # The FIRST report opens at the onboarding balance - read on the server, never
            # trusted from the form's hidden field. Only for a company onboarding gave a start
            # date; edit mode re-saves a posted report and keeps the normal path.
            if not is_edit_mode:
                onboarding_opening = first_report_opening(entity_id, transaction_date)
                if onboarding_opening is not None:
                    opening_balance = onboarding_opening

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
            action_type = request.form.get("action_type", "save_next")

            logger.info(
                f"Form data parsed - opening_balance: {opening_balance}, cash_addition: {cash_addition}, withdrawal: {withdrawal}, action_type: {action_type}"
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
                db.or_(Report.status.is_(None), Report.status != "draft"),
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
                # WRITE FLIP: existing_report IS the row we want to update.
                report_draft = Report.query.filter(
                    Report.id == existing_report.id
                ).first()
                if not report_draft:
                    # Edit mode: the Report already exists, so this branch now
                    # only runs when something is badly out of sync. Keep it as
                    # a Report so the shapes match.
                    report_draft = Report(
                        id=existing_report.id,
                        transaction_date=existing_report.transaction_date,
                        next_transaction_date=existing_report.next_transaction_date,
                        opening_balance=opening_balance,
                        cash_addition=cash_addition,
                        adjusted_opening_balance=opening_balance +
                        cash_addition,
                        created_by=existing_report.created_by,
                        entity_id=existing_report.entity_id,
                        status="draft",
                    )
                    db.session.add(report_draft)
                else:
                    report_draft.opening_balance = opening_balance
                    report_draft.cash_addition = cash_addition
                    report_draft.adjusted_opening_balance = (
                        opening_balance + cash_addition
                    )

                report_draft.cash_addition_type = withdrawal
                # the bank account is the one on entity_pettycash_settings (schema item 13)

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
                # When id is provided (e.g. from URL), load that specific draft; else any draft for
                # (entity, date).
                existing_draft = find_draft(entity_id, transaction_date, id or request.form.get("draft_id"))

            try:
                report_draft = save_opening(
                    entity_id,
                    current_user,
                    transaction_date,
                    opening_balance,
                    cash_addition,
                    withdrawal,
                    action_type,
                    existing_draft=None if (is_edit_mode and existing_report) else existing_draft,
                )
            except OpeningRefused as refused:
                flash(refused.message, "danger")
                if entity_id:
                    return redirect(url_for("entity.report_dashboard", id=entity_id))
                return redirect(url_for("entity.entity_list"))

            # Onboarding hand-off is done once the opening entry is saved - drop the session flag so
            # later reports use the normal date rules.
            if from_onboarding:
                session.pop("onboarding_opening_entity", None)

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

    # A request to clear the previous day's deposit ("no change"). Nothing sends deposit_type any
    # more; kept as it was until it is retired with this page.
    if not existing_draft and selected_date and deposit_type and deposit_type == "no change":
        last_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date < selected_date,
            db.or_(Report.status.is_(None), Report.status != "draft"),
        ).order_by(Report.transaction_date.desc()).first()
        last_draft_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date < selected_date,
            Report.status == "draft",
        ).order_by(Report.transaction_date.desc()).first()
        if last_report:
            last_report.bank_deposit -= last_report.bank_deposit
            recalculate_report(last_report)
        if last_draft_report:
            last_draft_report.bank_deposit -= last_draft_report.bank_deposit
            recalculate_report(last_draft_report)
        if last_report or last_draft_report:
            db.session.commit()

    # What the page shows: the day's draft, else what the day opens from (the service).
    state = opening_state(entity_id, selected_date, draft=existing_draft)
    existing_draft = state["draft"]
    is_latest_report = True  # a new day's report is always the latest, and editable
    yesterday_closing_balance = state["yesterday_closing_balance"]
    safebox_balance = state["safebox_balance"]
    template_data = {
        "opening_balance": state["opening_balance"],
        "report": state["report"],
        "next_transaction_date": state["next_transaction_date"],
        "is_first_report": state["is_first_report"],
        "is_draft": existing_draft is not None,
        "draft_id": existing_draft.id if existing_draft else None,
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
        # Add stepper data for dynamic progress display
        current_section="opening",  # Always set to current page regardless of database value
        completed_sections=(existing_draft.completed_sections or []) if existing_draft else [],
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
