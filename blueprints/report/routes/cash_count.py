from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services.cash_denominations import (
    build_denomination_rows, form_field_for, resolve_denominations_for_entity)
from blueprints.report.services.shared import (check_user_has_entities,
                                               header_publishing_status_for,
                                               resolve_report_entity_id,
                                               safe_float)
from blueprints.shared.entity_display import entity_badge_data
from models.db import Entity, Report, db
from services.authz import permission_denied
from services.permission_policy import Permission, has_permission


@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/new/cash-count", methods=["GET", "POST"])
@report_bp.route("/entity/<entity:entity_id>/petty-cash/reports/<string:id>/cash-count", methods=["GET"])
@report_bp.route("/report/cash_count", methods=["GET", "POST"])
@report_bp.route("/report/<string:id>/cash_count", methods=["GET"])
@login_required
def report_cash_count(id=None, entity_id=None):
    entity_id = entity_id or request.args.get("entity_id") or request.form.get("entity_id")
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
        # The ReportDraft fallback that used to sit here is gone: since Stage 4a
        # every draft has a paired `report` row with the same id, so the first
        # lookup already covers drafts. Kept as one query, not two.
        report_for_access = Report.query.filter_by(id=id).first()
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

    if id:
        report = (
            # The ReportDraft join is gone: it filtered BOTH ids to `id`, which
            # collapsed the "full outer" join back to an inner one, so `report`
            # was None whenever either side was missing and report.company below
            # raised. Its two columns live on `report` since r1a01.
            #
            # The cash-count join is gone too (Step 3.5). The nine denomination
            # columns it supplied were never rendered — the template iterates
            # `denomination_rows`, built from report_cash_count — and the four
            # scalars below now come from `report`, where cash_count.py writes
            # them. Selecting them off ReportCashCountDraft shadowed Report's
            # own identically-named columns in the result Row.
            Report.query .filter(
                Report.id == id,
                Report.company == entity_id,
            ) .with_entities(
                Report.id,
                Report.transaction_date,
                Report.next_transaction_date,
                Report.date,
                Report.opening_balance,
                Report.cash_addition,
                Report.adjusted_opening_balance,
                Report.cash_sales,
                Report.shop_sales,
                Report.delivery_sales,
                Report.total_sales,
                Report.expenses,
                Report.bank_deposit,
                Report.closing_balance,
                Report.uploaded_by,
                Report.company,
                Report.xero_integrated_yes,
                Report.completed_sections,
                Report.current_section,
                Report.safe_box_balance,
                Report.discrepancy_amount,
                Report.discrepancy_type,
                Report.discrepancy_reason,
                # NOTE: Report.status is deliberately NOT selected, matching
                # what this query returned before Step 3.5. The template does
                # `current_draft.status != 'draft'` to decide readonly, and an
                # absent attribute makes that true — so this branch has always
                # rendered read-only. Adding it here would silently make the
                # form editable; that is a behaviour change, not scaffolding
                # removal, so it belongs in its own commit.
            ) .first())
        user_entity = Entity.query.get_or_404(report.company)
        entity_acronym, display_date = entity_badge_data(user_entity)
        completed_sections = (
            report.completed_sections if report.completed_sections else []
        )
        # Determine if this is the latest report (most recent transaction_date)
        # or old report
        # Step 4a-6: was max(coalesce(Report.transaction_date,
        # ReportDraft.transaction_date)) over a full outer join. Drafts live in
        # `report` since Stage 4a, so one table answers it. No status filter —
        # balance chaining and "is this the latest" both mean ANY status; a
        # draft's date is still the latest date.
        latest_report_date = (
            db.session.query(db.func.max(Report.transaction_date))
            .filter(Report.company == entity_id)
            .scalar())

        is_latest_report = report.transaction_date == latest_report_date

        return render_template(
            "report/cash_count.html",
            org=user_entity,
            completed_sections=completed_sections,
            current_section="cash_count",
            current_draft=report,
            header_publishing_status=header_publishing_status_for(report_id=(report.id if report else None)),
            safe_box_balance=report.safe_box_balance or 0.00,
            closing_balance=report.closing_balance if report.closing_balance else 0.00,
            datenow=datetime.now(),
            transaction_date=report.transaction_date,
            is_latest_report=is_latest_report,
            entity_acronym=entity_acronym,
            display_date=display_date,
            is_edit_mode=is_edit_mode,
            denomination_rows=build_denomination_rows(
                entity_id, report_id=report.id
            ),
        )

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
                f"Cash count form - Using selected date from URL/form: {transaction_date}"
            )
        except ValueError:
            logger.warning(
                f"Cash count form - Invalid date format: {selected_date}, using today"
            )
            transaction_date = datetime.now().date()
    else:
        transaction_date = datetime.now().date()
        logger.info(
            f"Cash count form - No date provided, using today: {transaction_date}"
        )

    # If edit mode is enabled and no id provided, try to load any existing
    # report for this date
    if is_edit_mode and not id:
        # Edit mode targets a SUBMITTED report — see the note in sales.py.
        existing_report = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
            db.or_(Report.status.is_(None), Report.status != "draft"),
        ).first()
        if existing_report:
            # Redirect to cash_count page with report id
            return redirect(
                url_for(
                    "report.report_cash_count",
                    id=existing_report.id,
                    entity_id=entity_id,
                    edit="true",
                )
            )

    # Check for existing draft: by id when in URL, else by (entity,
    # transaction_date)
    if id:
        # WRITE FLIP (Step 2): current_draft is mutated below, so it must
        # read the table the writes land on.
        current_draft = Report.query.filter(
            Report.id == id,
            Report.company == entity_id,
            Report.status == "draft",
        ).first()
    else:
        current_draft = Report.query.filter(
            Report.company == entity_id,
            Report.transaction_date == transaction_date,
            Report.status == "draft",
        ).first()

    logger.info("Cash count form - Looking for existing draft:")
    logger.info(f"  Company: {entity_id}")
    logger.info(f"  Transaction date: {transaction_date}")
    logger.info(f"  Username: {current_user.username}")
    logger.info(
        f"  Found existing draft: {current_draft.id if current_draft else 'None'}"
    )

    # Denominations this entity logs, in display order. Drives both the form
    # and the POST parsing, so the two can never drift apart.
    denominations = resolve_denominations_for_entity(entity_id)

    if request.method == "POST":
        if not current_draft:
            flash(
                "I don't see a draft for today yet - let's start with the opening entry.",
                "warning",
            )
            return redirect(url_for("report.report_opening"))

        from blueprints.report.services.cash import CashRefused, save_cash_count

        here = url_for("report.report_cash_count", entity_id=entity_id,
                       transaction_date=transaction_date.strftime("%Y-%m-%d"))
        action_type = request.form.get("action_type", "save_next")
        # One count per denomination the company logs (the form's actual_cash[<field>]); the
        # discrepancy the page posts is the browser's - the service works it out again.
        counts = {}
        for denomination in denominations:
            raw = (request.form.get(f"actual_cash[{form_field_for(denomination)}]") or "").replace(",", "").strip()
            try:
                quantity = float(raw) if raw else 0.0
            except ValueError:
                quantity = -1.0
            counts[denomination.cash_id] = int(quantity) if quantity.is_integer() else -1
        try:
            save_cash_count(
                current_draft,
                current_user,
                counts,
                safe_float(request.form.get("safe_box_balance", 0)),
                request.form.get("discrepancy_reason", ""),
                action_type,
            )
        except CashRefused as refused:
            flash(refused.message, "danger")
            return redirect(here)
        except Exception:
            db.session.rollback()
            logger.exception(f"Error saving the cash count for entity {entity_id} on {transaction_date}")
            flash("Something went wrong saving your cash count. Mind trying again?", "danger")
            return redirect(here)

        if action_type == "save_exit":
            return redirect(url_for("entity.report_dashboard", id=entity_id))
        return redirect(
            url_for(
                "report.report_ending",
                entity_id=entity_id,
                transaction_date=transaction_date.strftime("%Y-%m-%d"),
            )
        )

    # Handle case where no draft exists
    if not current_draft:
        flash(
            "I don't see a draft for today yet - let's start with the opening entry.",
            "warning",
        )
        return redirect(url_for("report.report_opening"))

    # Get entity for the template
    entity = Entity.query.filter(Entity.id == entity_id).first()
    entity_acronym, display_date = entity_badge_data(entity)

    # Ensure completed_sections is a list
    completed_sections = (
        current_draft.completed_sections if current_draft.completed_sections else [])

    # Don't reset current_section when viewing - it should only update when progressing forward
    # The stepper should always show the latest step reached, not the current
    # page

    # For new reports (no id parameter), always consider them as
    # latest/editable
    is_latest_report = True

    return render_template(
        "report/cash_count.html",
        org=entity,
        completed_sections=completed_sections,
        current_section="cash_count",
        current_draft=current_draft,
        header_publishing_status=header_publishing_status_for(report_id=(current_draft.id if current_draft else None)),
        transaction_date=transaction_date,
        safe_box_balance=(
            current_draft.safe_box_balance if current_draft else 0.00) or 0.00,
        closing_balance=(
            current_draft.closing_balance if current_draft.closing_balance else 0.00),
        datenow=datetime.now(),
        is_latest_report=is_latest_report,
        entity_acronym=entity_acronym,
        display_date=display_date,
        is_edit_mode=is_edit_mode,
        denomination_rows=build_denomination_rows(
            entity_id,
            report_id=current_draft.id if current_draft else None,
        ),
    )
