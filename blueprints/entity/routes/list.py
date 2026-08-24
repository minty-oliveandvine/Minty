# Entity list and report dashboard routes.


from datetime import datetime, timezone

from flask import (current_app, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased

from blueprints.entity import entity_bp
from blueprints.entity.services.modules import (build_subscription_notices,
                                                claim_subscription_notice,
                                                get_enabled_modules_for_entities,
                                                get_trial_modules_for_entities,
                                                module_display_names)
from blueprints.entity.services.shared import (check_user_has_entities,
                                               get_main_bank_account)
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

    STORED AS UTC, CONVERTED HERE. ``last_accessed_at`` is a naive
    ``timestamp without time zone`` holding UTC — see ``record_entity_access``, which
    writes it that way deliberately. A naive column has no opinion about which zone its
    digits belong to, so the only thing that makes them meaningful is the pair of
    conventions at the two ends: write UTC, read UTC, convert once, here.

    It used to render the digits verbatim, which was correct only if they were already
    Hong Kong wall time. They were not: the write handed Postgres an aware +08:00 value,
    and a naive column CONVERTS an aware value using the session ``TimeZone`` (UTC on the
    server) rather than keeping its wall clock. So every card was 8 hours behind — a login
    at 5:36 PM read "9:36 AM" — which is exactly the failure the old comment on the write
    said it was avoiding.

    Rows written before this are already UTC for that same reason, so they read correctly
    now without being touched.

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
    # Who last opened each entity — outer-joined so entities that have never
    # been opened (last_accessed_by_user_id IS NULL) still come back.
    accessor = aliased(User)
    base_query = (
        db.session.query(
            Entity.id,
            Entity.name,
            Entity.status,
            Entity.last_accessed_at,
            accessor.first_name,
            accessor.last_name,
        )
        .outerjoin(accessor, Entity.last_accessed_by_user_id == accessor.id)
        .filter(or_(Entity.status.is_(None), Entity.status != "deleted"))
        # "Setup in progress" floats to the top so a half-finished entity is
        # the first thing seen, then most-recently-opened first. Never-opened
        # entities sort last rather than first, which is what NULLS LAST buys.
        .order_by(
            (Entity.status == "onboarding").desc(),
            Entity.last_accessed_at.desc().nulls_last(),
        )
    )
    if is_superuser(current_user):
        # Superusers see every non-deleted entity, even those they have no
        # user_entity row on (they enter read-only on those).
        rows = base_query.all()
    else:
        rows = (
            base_query.join(UserEntity, UserEntity.entity_id == Entity.id)
            .filter(UserEntity.user_id == current_user.id)
            .all()
        )
    if not rows:
        logger.info("Entity list is empty")
        return render_template("entity/entity_list_empty.html")

    # Which module icons each card shows. This resolver is fail-closed (no
    # entity_function_map row means OFF), which is what we want here — a module
    # icon is a claim that the module is paid for and usable.
    modules_by_entity = get_enabled_modules_for_entities([r.id for r in rows])

    # Which of those modules are running on a free trial — one query for the list.
    # Intersected with the enabled set below so the badge can never claim a trial on
    # a module whose icon isn't there: the two come from different tables, and the
    # entitlement resolver is the one the request gate actually obeys.
    trials_by_entity = get_trial_modules_for_entities([r.id for r in rows])
    trial_labels = module_display_names(
        {code for codes in trials_by_entity.values() for code in codes}
    )

    organizations = []
    for r in rows:
        modules = modules_by_entity.get(r.id, set())
        trial_modules = trials_by_entity.get(r.id, set()) & modules
        organizations.append(
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "modules": modules,
                "trial_modules": trial_modules,
                # Named in the badge tooltip so a card showing two module icons and
                # one badge says WHICH module the free trial belongs to.
                "trial_module_names": sorted(
                    trial_labels.get(code, code) for code in trial_modules
                ),
                "last_accessed_display": _format_last_accessed(r.last_accessed_at),
                "last_accessed_by": (
                    f"{r.first_name or ''} {r.last_name or ''}".strip() or None
                ),
            }
        )
    return render_template("entity/index.html", organizations=organizations)


@entity_bp.route("/entity/<string:id>")
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
    #prev code
    #org = Entity.query.filter(Entity.id == id).first()
    #new code fix
    org = Entity.query.filter(func.trim(Entity.id) == id.strip()).first()
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))
    if org.status == "deleted":
        flash("This one's gone — it was deleted.", "warning")
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
    org.draft_completed_sections = (
        current_draft.completed_sections if current_draft else []
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
    org.draft_last_edit_seconds = (
        int((datetime.now() - current_draft.date).total_seconds())
        if current_draft
        else 0
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
        subscription_settings_url=url_for(
            "entity.entity_settings_module", org_id=id
        ),
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


@entity_bp.route("/entity/<string:id>/delete", methods=["POST"])
@login_required
@require_entity_access(entity_arg="id")
@require_permission(
    Permission.ENTITY_DELETE,
    entity_arg="id",
    message="You do not have permission to delete this entity.",
)
def delete_entity(id):
    org = Entity.query.filter(Entity.id == id).first_or_404()
    if org.status == "deleted":
        flash("This one's already been deleted.", "info")
        return redirect(url_for("entity.entity_list"))
    org.status = "deleted"
    db.session.commit()
    flash("That entity's deleted.", "success")
    return redirect(url_for("entity.entity_list"))


# Entity list and report dashboard. Logic moved from app.
