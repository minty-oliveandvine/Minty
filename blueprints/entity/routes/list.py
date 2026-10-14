# Entity list and report dashboard routes.


from datetime import datetime

from flask import (current_app, flash, get_flashed_messages, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_required
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import minty_web_module_page_handoff
from blueprints.entity.services.dashboard import dashboard_state
from blueprints.entity.services.entity_list import sign_notices
from blueprints.entity.services.modules import claim_subscription_notice
from blueprints.entity.services.shared import (check_user_has_entities,
                                               get_main_bank_account)
from blueprints.shared.entity_display import build_entity_acronym
from blueprints.xero.services.integration import get_accounts_from_xero
from models.db import Entity, Report, UserEntity
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.authz import (permission_denied, require_module)
from services.permission_policy import Permission, has_permission, is_superuser
from services.subscription_api import fetch_notice


@entity_bp.route("/entity")
@login_required
def entity_list():
    """The entity list is minty-web's ``/entities`` (the ``MINTY_WEB_HUB`` switch went in phase
    2, 2026-10-05, with Flask's Jinja list) - Terms owed or not: minty-web draws the acceptance
    panel itself, over every page (its TermsGate, over legal/routes/hub.py), so the gate's
    redirect to here carries on to it."""
    return _to_minty_web_list()


def _to_minty_web_list():
    """On to minty-web's list, carrying what the redirect that brought the person here
    flashed. Seventy-odd routes flash a message ("couldn't find that one", "no permission to
    look there") and redirect to /entity; minty-web cannot read this session, so the
    messages are drained here and signed into the URL, and minty-web's list shows them."""
    from blueprints.entity.routes.modules import minty_web_entity_list_url

    notices = sign_notices(get_flashed_messages(with_categories=True))
    return redirect(minty_web_entity_list_url(current_user.id, notices=notices))


@entity_bp.route("/entity/<entity:id>/petty-cash")
@login_required
@require_module(
    "PETTY_CASH",
    entity_arg="id",
    message="Petty Cash is not activated for this entity.",
)
def report_dashboard(id):
    id = (id or "").strip()
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you the report dashboard.",
            "info",
        )
        return redirect(url_for("entity.entity_list"))
    # entities.id is a uuid: no trim() on the column (Postgres has no btrim(uuid)); the
    # URL value is stripped before the compare instead.
    org = Entity.query.filter(Entity.id == id.strip()).first()
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    user_entity = UserEntity.query.filter(
        UserEntity.user_id == current_user.id, UserEntity.entity_id == id
    ).first()
    # Superusers can enter any entity even without a user_entity row.
    # has_permission will gate writes via the readonly path.
    if not user_entity and not is_superuser(current_user):
        return permission_denied("You don't have access to this entity", entity_id=id)
    if not has_permission(current_user, Permission.ENTITY_VIEW, id):
        return permission_denied(
            "You do not have permission to view this entity.", entity_id=id
        )

    # Entity still mid-onboarding → bounce the member back into the wizard to
    # finish setup. Gated on user_entity so a superuser inspecting an entity
    # they don't belong to can still view it read-only instead of being sent
    # into an onboarding flow that isn't theirs.
    #
    # Pass entity_id (not just entity_name) so the wizard binds THIS entity and
    # rehydrates its saved progress via GET /api/onboarding/state. Without it the
    # wizard boots fresh and only Step 1 (entity name) shows — so an invitee, or
    # the owner re-entering, would lose all progress made past Basic Information.
    if org.status == "onboarding" and user_entity:
        from blueprints.entity.routes.create import onboarding_launch_url

        return redirect(
            onboarding_launch_url(
                current_user, entity_name=org.name or "", entity_id=id
            )
        )

    # Everything the page computes about the company's reports - shared with the Petty Cash
    # API's GET /home (blueprints/entity/services/dashboard.py), copied onto ``org`` as before.
    state = dashboard_state(id)
    latest, draft = state["latest"], state["draft"]
    org.transaction_date = latest["date"]
    org.closing_balance = latest["closing_balance"]
    org.latest_deposit = latest["deposit"]
    org.latest_date = latest["date"]
    org.latest_deposit_bank_name = latest["deposit_bank_name"]
    org.latest_deposit_bank_number = latest["deposit_bank_number"]
    org.deposit_correction_missing_settings = latest["deposit_correction_missing_settings"]
    org.can_correct_latest_deposit = latest["can_correct_deposit"]
    org.has_existing_draft = draft is not None
    org.draft_id = draft["id"] if draft else None
    org.draft_current_section = draft["current_section"] if draft else None
    org.draft_completed_sections = draft["completed_sections"] if draft else []
    org.draft_progress_completed = len(draft["completed_sections"]) if draft else 0
    org.draft_date = state["draft_date"]
    org.draft_last_edit_seconds = draft["last_edit_seconds"] if draft else 0
    org.is_new_user = state["is_new_user"]
    latest_report_submitter_first_name = state["latest_submitter_first_name"]
    published_reports_dict = state["published"]
    published_dates = list(published_reports_dict)
    today_has_report = state["today_has_report"]
    today_is_latest_report = state["today_is_latest_report"]
    today_report_id = state["today_report_id"]

    try:
        token_user = get_xero_token_user_for_entity(id)
        if ensure_valid_token(token_user):
            bank_accounts = get_accounts_from_xero(
                token_user.access_token,
                org.xero_org_id,
                where='Type="BANK"',
                order="Code ASC, Name ASC",
                token_validated=True,
            )
        else:
            bank_accounts = []
    except Exception as e:
        logger.error(f"Error fetching bank accounts: {str(e)}")
        bank_accounts = []

    has_complete_xero_settings = state["has_complete_xero_settings"]
    missing_settings_fields = state["missing_settings_fields"]
    main_bank_account = get_main_bank_account(id)
    # Includes drafts on purpose: a deposit entered on a draft is a real
    # deposit for the "has this entity ever deposited" question.
    has_deposit = (
        Report.query.filter(Report.company == str(id), Report.bank_deposit > 0)
        .order_by(Report.transaction_date.desc())
        .first()
    )
    entity_acronym = build_entity_acronym(org.name) if org else ""
    display_date = None
    if org and org.created_at:
        display_date = (
            org.created_at.date()
            if isinstance(org.created_at, datetime)
            else org.created_at
        )

    # Hong Kong "today" for the calendar's create-time validation; amounts render with the
    # company's ISO currency code ("$" when it has none).
    server_today_hk = state["server_today_hk"]
    currency_symbol = state["currency_code"] or "$"

    # Subscription notice — once per entity per login. claim_* is checked FIRST so the
    # subscription API is only asked on a page view that would show the modal; the
    # dashboard is a hot path.
    #
    # ``?notice=1`` re-shows it without a fresh login. Debug-gated, because the whole
    # point of the claim is that a customer sees this once — but testing it otherwise
    # means logging out between every attempt, and the claim is spent even on a visit
    # that had nothing to show.
    force_notice = bool(current_app.debug) and request.args.get("notice") == "1"
    claimed = force_notice or claim_subscription_notice(session, id)
    subscription_notice = None
    if claimed:
        # Never breaks the dashboard: a failure is logged there and answers None.
        subscription_notice = fetch_notice(id, current_user)
    # One line per dashboard load. "Not showing" has several indistinguishable
    # causes — claim already spent, nothing to report, a failed fetch — and
    # without this the only way to tell them apart is to guess.
    logger.info(
        f"NOTICE {id}: forced={force_notice} claimed={claimed} "
        f"items={len(subscription_notice['items']) if subscription_notice else 0} "
        f"user={current_user.id}"
    )

    return render_template(
        "entity/entity_dashboard_v2.html",
        org=org,
        subscription_notice=subscription_notice,
        # minty-web's Module page, through this app's hand-over at the click
        subscription_settings_url=minty_web_module_page_handoff(id),
        currency_symbol=currency_symbol,
        server_today_hk=server_today_hk,
        main_bank_account=main_bank_account,
        bank_accounts=bank_accounts,
        published_dates=published_dates,
        published_reports_dict=published_reports_dict,
        today_has_report=today_has_report,
        today_report_id=today_report_id,
        today_is_latest_report=today_is_latest_report,
        has_complete_xero_settings=has_complete_xero_settings,
        missing_settings_fields=missing_settings_fields,
        has_deposit=has_deposit,
        entity_acronym=entity_acronym,
        display_date=display_date,
        latest_report_submitter_first_name=latest_report_submitter_first_name,
    )


# Entity list and report dashboard. Logic moved from app.
