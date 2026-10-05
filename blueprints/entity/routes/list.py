# Entity list and report dashboard routes.


from datetime import datetime, timezone

from flask import (current_app, flash, get_flashed_messages, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy import func, or_

from blueprints.entity import entity_bp
from blueprints.shared.feature_flags import minty_web_hub
from blueprints.entity.routes.modules import minty_web_module_page_handoff
from blueprints.entity.services.entity_list import build_entity_list, sign_notices
from blueprints.entity.services.modules import (build_subscription_notices,
                                                claim_subscription_notice)
from blueprints.entity.services.shared import (check_user_has_entities,
                                               get_main_bank_account)
from blueprints.legal.services.gate import outstanding_terms_context
from blueprints.shared.entity_display import build_entity_acronym
from blueprints.xero.services.integration import get_accounts_from_xero
from blueprints.xero.services.settings import (
    check_entity_xero_settings_complete, get_entity_account_settings,
    get_missing_xero_settings_fields)
from models.db import Entity, Report, User, UserEntity, db, tz
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity)
from services.authz import (permission_denied, require_entity_access,
                            require_module, require_permission)
from services.permission_policy import Permission, has_permission, is_superuser


def _format_last_accessed(dt):
    """Render a last-login timestamp like "9 Jun 5:42 PM", in Hong Kong time.

    AN INSTANT, CONVERTED HERE. ``last_accessed_at`` is a ``TIMESTAMPTZ``
    (``record_entity_access`` writes an aware UTC instant) and arrives here as the aware,
    UTC value ``services.entity_list`` normalises it to; this converts it to Hong Kong once.
    A naive value is still read as UTC, so a caller holding one gets the same answer.

    Built without strftime's %-d / %-I, which are glibc extensions and raise on
    Windows, so this renders identically on a dev box and on the server.
    """
    if not dt:
        return None
    # Naive values are UTC by the convention above. An aware one is honoured as it stands,
    # so this stays correct if the column is ever migrated to ``timestamptz``.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)
    return (
        f"{local.day} {local.strftime('%b')} "
        f"{local.strftime('%I:%M %p').lstrip('0')}"
    )


@entity_bp.route("/entity")
@login_required
def entity_list():
    # With the hub on, the list is minty-web's (its /entities) - Terms owed or not: minty-web
    # draws the acceptance panel itself, over every page (its TermsGate, over
    # legal/routes/hub.py), so the gate's redirect to here carries on to it.
    if minty_web_hub():
        return _to_minty_web_list()

    # The Terms panel renders as a modal over this page — it is where the gate
    # sends anyone who has not agreed. None means nothing is outstanding.
    # Resolved before the empty-list branch on purpose: a brand-new user with
    # no companies is exactly the person most likely to owe an acceptance, and
    # they never reach index.html.
    terms = outstanding_terms_context()

    # The list itself (services/entity_list.py) - the same builder minty-web's list reads,
    # so the two can never disagree about which companies there are or what badges they carry.
    entries = build_entity_list(current_user)
    if not entries:
        logger.info("Entity list is empty")
        return render_template("entity/entity_list_empty.html", terms=terms)

    organizations = [
        {**entry, "last_accessed_display": _format_last_accessed(entry["last_accessed_at"])}
        for entry in entries
    ]
    return render_template(
        "entity/index.html", organizations=organizations, terms=terms
    )


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

    # Deliberately INCLUDES drafts: this drives the "latest report" summary
    # (transaction_date / closing_balance / latest_deposit), and a draft
    # genuinely is the most recent report for those purposes. Anything that
    # means "last SUBMITTED report" must filter status separately — see the
    # date-sequence guards in opening.py and create.py.
    latest_report = (
        Report.query.filter(Report.company == str(id))
        .order_by(Report.transaction_date.desc())
        .first()
    )

    if latest_report:
        org.transaction_date = latest_report.transaction_date
        org.closing_balance = latest_report.closing_balance
        org.latest_deposit = latest_report.bank_deposit
        org.latest_date = latest_report.transaction_date
        if latest_report.bank_deposit > 0:
            deposit_bank_account = get_entity_account_settings(str(id), "bank")
            pettycash_account_for_deposit = get_entity_account_settings(
                str(id), "pettycash"
            )
            if deposit_bank_account:
                org.latest_deposit_bank_name = deposit_bank_account["name"]
                org.latest_deposit_bank_number = deposit_bank_account.get(
                    "bank_account_number", "****"
                )
            else:
                org.latest_deposit_bank_name = "Unknown Bank"
                org.latest_deposit_bank_number = "****"
            # Used by the Before You Start modal to block "change" / "no" when
            # the entity is missing the settings needed to reconcile a deposit
            # correction (locally or in Xero).
            org.deposit_correction_missing_settings = [
                label
                for label, present in (
                    ("Deposit Bank Account", bool(deposit_bank_account)),
                    ("Petty Cash Account", bool(pettycash_account_for_deposit)),
                )
                if not present
            ]
            org.can_correct_latest_deposit = not org.deposit_correction_missing_settings
        else:
            org.latest_deposit_bank_name = "No deposit"
            org.latest_deposit_bank_number = ""
            org.deposit_correction_missing_settings = []
            org.can_correct_latest_deposit = True
    else:
        org.transaction_date = None
        org.closing_balance = 0
        org.latest_deposit = 0
        org.latest_date = None
        org.latest_deposit_bank_name = "No deposit"
        org.latest_deposit_bank_number = ""
        org.deposit_correction_missing_settings = []
        org.can_correct_latest_deposit = True

    # Dashboard "Continue Report" card — read-only. Migrated to `report`; the
    # draft->report mirror keeps current_section/completed_sections current.
    current_draft = (
        Report.query.filter(
            Report.company == str(id),
            Report.status == "draft",
        )
        .order_by(Report.transaction_date.desc())
        .first()
    )
    org.has_existing_draft = current_draft is not None
    org.draft_id = current_draft.id if current_draft else None
    org.draft_current_section = current_draft.current_section if current_draft else None
    # NULL on legacy drafts (6 of 25 in production): the template iterates it
    org.draft_completed_sections = (
        (current_draft.completed_sections or []) if current_draft else []
    )
    org.draft_progress_completed = (
        len(current_draft.completed_sections)
        if current_draft and current_draft.completed_sections
        else 0
    )
    # The calendar uses draft_date as its onboarding FLOOR (the earliest date a
    # first report may use), so it must be the EARLIEST draft — the onboarding
    # seed — not the newest. With .desc() above, an entity holding drafts for
    # both 29 and 30 July got a floor of the 30th, which made the 29th
    # unclickable even though that was its own opening date.
    earliest_draft_date = (
        db.session.query(db.func.min(Report.transaction_date))
        .filter(Report.company == str(id), Report.status == "draft")
        .scalar()
    )
    org.draft_date = earliest_draft_date or (
        current_draft.transaction_date if current_draft else None
    )
    # "last edited" is updated_at (timestamptz since C4; SQLite hands it back naive)
    last_edit = current_draft.updated_at or current_draft.created_at if current_draft else None
    if last_edit is not None and last_edit.tzinfo is None:
        last_edit = last_edit.replace(tzinfo=timezone.utc)
    org.draft_last_edit_seconds = (
        int((datetime.now(timezone.utc) - last_edit).total_seconds()) if last_edit is not None else 0
    )
    org.is_new_user = latest_report is None

    latest_report_submitter_first_name = None
    if latest_report and latest_report.uploaded_by:
        _lr_user = User.query.filter_by(username=latest_report.uploaded_by).first()
        if _lr_user and _lr_user.first_name:
            latest_report_submitter_first_name = _lr_user.first_name.strip()

    # PUBLISHED means submitted. Since Stage 4a `report` also holds
    # draft-shaped rows (status='draft'), so without this filter the dashboard
    # counts an in-progress draft as a finished report — published_dates below
    # drives today_has_report and the "already done" state.
    published_reports = (
        Report.query.filter(
            Report.company == str(id),
            db.or_(Report.status.is_(None), Report.status != "draft"),
        )
        .with_entities(
            Report.transaction_date,
            Report.id,
            Report.closing_balance,
            Report.bank_deposit,
            Report.xero_integrated_yes,
            Report.uploaded_by,
        )
        .all()
    )
    _uploaders = {r.uploaded_by for r in published_reports if r.uploaded_by}
    _first_by_username = {}
    if _uploaders:
        for _u in User.query.filter(User.username.in_(_uploaders)).all():
            _first_by_username[_u.username] = (
                (_u.first_name or "").strip() or None
            )
    published_dates = [report.transaction_date.strftime(
        "%Y-%m-%d") for report in published_reports]
    published_reports_dict = {
        report.transaction_date.strftime("%Y-%m-%d"): {
            "id": report.id,
            "closing_balance": report.closing_balance,
            "bank_deposit": report.bank_deposit or 0.0,
            "xero_integrated_yes": report.xero_integrated_yes,
            "submitter_first_name": _first_by_username.get(report.uploaded_by),
        }
        for report in published_reports
    }
    today = datetime.now().strftime("%Y-%m-%d")
    today_has_report = today in published_dates
    latest_report_date_str = (latest_report.transaction_date.strftime(
        "%Y-%m-%d") if latest_report else None)
    today_is_latest_report = today == latest_report_date_str
    today_report_id = None
    if today_has_report:
        # Unfiltered is safe here: today_has_report is derived from
        # published_dates, which already excludes drafts, so this only runs
        # when a SUBMITTED report exists for today.
        today_report = Report.query.filter(
            Report.company == str(id),
            Report.transaction_date == datetime.now().date()).first()
        if today_report:
            today_report_id = today_report.id

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

    has_complete_xero_settings = check_entity_xero_settings_complete(id)
    missing_settings_fields = []
    if not has_complete_xero_settings:
        missing_settings_fields = get_missing_xero_settings_fields(id)
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

    # Server-authoritative "today" in Hong Kong time. The calendar's create-time
    # validation uses this (not the browser clock) so the future-date boundary
    # matches the users' local midnight regardless of the device timezone.
    server_today_hk = datetime.now(tz).date().isoformat()

    # Money amounts on the dashboard render with the ISO code of the entity's
    # selected currency (entities.currency_id -> currency_info.currency_code).
    from models.db import CurrencyInfo

    currency_symbol = "$"
    if org and org.currency_id:
        _currency = CurrencyInfo.query.get(org.currency_id)
        if _currency and _currency.currency_code:
            currency_symbol = _currency.currency_code

    # Subscription notice — once per entity per login. claim_* is checked FIRST so
    # the billing queries behind build_* never run on a page view that wouldn't show
    # the modal anyway; the dashboard is a hot path.
    #
    # ``?notice=1`` re-shows it without a fresh login. Debug-gated, because the whole
    # point of the claim is that a customer sees this once — but testing it otherwise
    # means logging out between every attempt, and the claim is spent even on a visit
    # that had nothing to show.
    force_notice = bool(current_app.debug) and request.args.get("notice") == "1"
    claimed = force_notice or claim_subscription_notice(session, id)
    subscription_notice = None
    if claimed:
        try:
            notice = build_subscription_notices(id, current_user.id)
            subscription_notice = notice if notice["items"] else None
        except Exception as exc:  # never break the dashboard over a notice
            logger.error(f"Subscription notice build failed for {id}: {exc}")
    # One line per dashboard load. "Not showing" has several indistinguishable
    # causes — claim already spent, nothing to report, a build that threw — and
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
