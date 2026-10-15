# Entity list and report dashboard routes.

from datetime import datetime

from flask import (current_app, flash, get_flashed_messages, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_required
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import minty_web_module_page_handoff
from blueprints.entity.services.entity_list import sign_notices
from blueprints.entity.services.launch import greeting, launch_state
from blueprints.entity.services.modules import claim_subscription_notice
from blueprints.entity.services.shared import check_user_has_entities
from blueprints.report.services.daily_closing import stage_hrefs
from blueprints.xero.services.settings import (
    check_entity_xero_settings_complete, get_entity_account_settings,
    get_missing_xero_settings_fields)
from models.db import Entity, UserEntity, tz
from services.authz import (permission_denied, require_module)
from services.permission_policy import (Permission, has_permission, is_superuser,
                                        is_superuser_readonly)
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

    # The launch page (Part 15.6a): the open draft, the next day and its gate, the latest reports
    # - decided in blueprints/entity/services/launch.py, not in the browser.
    launch = launch_state(id)

    # "Before You Start" and "Correct deposit" rewrite the latest submitted report's deposit
    # (POST /api/check-dept-bank-yest), which needs the entity's deposit-bank and petty-cash
    # mappings when there was a deposit to reverse. Same rule the endpoint enforces (409).
    deposit_bank = None
    deposit_missing_settings = []
    if launch.latest and launch.latest.bank_deposit > 0:
        deposit_bank = get_entity_account_settings(str(id), "bank")
        deposit_missing_settings = [
            label
            for label, present in (
                ("Deposit Bank Account", bool(deposit_bank)),
                ("Petty Cash Account", bool(get_entity_account_settings(str(id), "pettycash"))),
            )
            if not present
        ]
    readonly = is_superuser_readonly(current_user, id)
    can_correct_deposit = (
        not readonly
        and launch.state in ("not_started", "done")
        and launch.latest is not None
        and launch.latest.bank_deposit > 0
        and has_permission(current_user, Permission.REPORT_EDIT_ENTITY, id)
    )

    has_complete_xero_settings = check_entity_xero_settings_complete(id)
    missing_settings_fields = []
    if not has_complete_xero_settings:
        missing_settings_fields = get_missing_xero_settings_fields(id)

    # Money amounts on the dashboard render with the ISO code of the entity's
    # selected currency (entities.currency_id -> currency_info.currency_code).
    from models.db import CurrencyInfo

    currency_symbol = "$"
    if org and org.currency_id:
        _currency = CurrencyInfo.query.get(org.currency_id)
        if _currency and _currency.currency_code:
            currency_symbol = _currency.currency_code

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
        "petty_cash/launch.html",
        org=org,
        launch=launch,
        greeting=greeting(datetime.now(tz)),
        # done and current stages open their page (Part 14 Step progress)
        stage_hrefs=(
            stage_hrefs(id, launch.work_date)
            if launch.state == "in_progress"
            else None
        ),
        readonly=readonly,
        can_correct_deposit=can_correct_deposit,
        deposit_bank=deposit_bank,
        deposit_missing_settings=deposit_missing_settings,
        subscription_notice=subscription_notice,
        # minty-web's Module page, through this app's hand-over at the click
        subscription_settings_url=minty_web_module_page_handoff(id),
        currency_symbol=currency_symbol,
        has_complete_xero_settings=has_complete_xero_settings,
        missing_settings_fields=missing_settings_fields,
        xero_connected=request.args.get("success") == "true",
    )


# Entity list and report dashboard. Logic moved from app.
