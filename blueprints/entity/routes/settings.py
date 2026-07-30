"""Entity settings and contact routes."""

import html
import uuid
from typing import Protocol

import requests
from flask import (current_app, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import billing_settings_app_url
from blueprints.entity.services.settings import (
    COA_INCLUDED_TYPES, backfill_lock_dates_if_needed_background,
    sync_chart_of_accounts_if_changed, sync_contacts_if_changed_background,
    sync_expense_account_info_from_xero, sync_xero_accounts_to_db_background,
    sync_xero_coa_pettycash)
from blueprints.entity.services.shared import check_user_has_entities
from blueprints.entity.services.xero_account_mapping_post import (
    apply_country_currency_selection, process_xero_account_mapping_post)
from blueprints.shared.entity_display import build_entity_acronym
from blueprints.xero.services.settings import sync_entity_xero_status
from models.db import (AccountInfo, CountryInfo, CurrencyInfo, Entity,
                       EntityAccountXero, EntityPettycashSettings, User,
                       UserEntity, XeroContactSync, db)
from services.app_runtime.legacy.xero_service import (
    account_info_to_xero_format, contact_sync_to_xero_format)
from services.auth.token_service import (auto_refresh_token,
                                         ensure_valid_token,
                                         get_xero_token_user_for_entity,
                                         resolve_xero_token)
from services.authz import (permission_denied, require_entity_access,
                            require_module, require_permission)
from services.helpers.xero_bridge import get_xero_data_dynamic
from services.permission_policy import Permission, has_permission


class _PyCountryCountry(Protocol):
    alpha_2: str
    name: str


def _country_currency_choices(org):
    """Build the country / currency dropdown lists and the entity's current
    selection in each.

    Returns ``(country_code, currencies, selected_country, selected_currency)``.
    Keys mirror the old pycountry shape so the existing suggestion JS keeps
    working.

    Only ``is_active`` registry rows are listed: country_info and
    currency_info are seeded with the full ISO lists (~250 countries, ~170
    currencies) and the flag narrows them to what this deployment operates in.

    The entity's CURRENT row is always included even when it has since been
    deactivated. Without that, ``selected_*`` would fall to None and the
    template renders the hidden country_code / currency_id inputs as
    ``value=""`` (settings_entity.html:336-337), so the form shows a blank
    country for an entity that has one. The save path skips empty values
    (xero_account_mapping_post.py:44) so nothing is overwritten, but a blank
    field reads as "unset" and invites someone to change it. Deactivating a
    currency must not silently rewrite the entities already using it.

    Countries order by display_order then name, so common ones can be floated
    above the alphabetical tail; currency_info has no display_order column.
    """
    countries_q = (
        CountryInfo.query.filter(
            db.or_(
                CountryInfo.is_active.is_(True),
                CountryInfo.country_code == org.country_code,
            )
        )
        .order_by(CountryInfo.display_order, CountryInfo.country_name_en)
    )
    country_code = [
        {
            "country_code": c.country_code,
            "country_name": c.country_name_en,
        }
        for c in countries_q.all()
    ]

    currencies_q = (
        CurrencyInfo.query.filter(
            db.or_(
                CurrencyInfo.is_active.is_(True),
                CurrencyInfo.id == org.currency_id,
            )
        )
        .order_by(CurrencyInfo.currency_name)
    )
    currencies = [
        {"currency_id": c.id, "currency_name": c.currency_name}
        for c in currencies_q.all()
    ]

    selected_country = next(
        (c for c in country_code if c["country_code"] == org.country_code), None
    )
    selected_currency = next(
        (c for c in currencies if c["currency_id"] == org.currency_id), None
    )
    return country_code, currencies, selected_country, selected_currency


def _redirect_xero_mapping(entity_id: str, _from: str | None, *, return_view: str):
    """Redirect after Xero mapping POST; return_view selects integration vs petty cash page."""
    bills_kw = {"from": _from} if _from == "bills" else {}
    if return_view == "entity_settings_entity":
        return redirect(url_for("entity_settings_entity", org_id=entity_id, **bills_kw))
    return redirect(url_for("entity_settings", entity_id=entity_id, **bills_kw))


def _flash_if_xero_disconnected(org) -> bool:
    """Flash a "Xero disconnected — please reconnect" error when the entity was
    connected to a Xero org but is no longer live. Returns True if the entity is
    disconnected.

    Only flashes for entities that are SUPPOSED to be connected
    (``org.xero_org_id`` is set) so entities that never connected don't nag the
    user.

    Runs the authoritative LIVE check first: ``sync_entity_xero_status`` hits
    Xero's /connections endpoint and reconciles ``org.status`` to reality. This
    matters because a connection revoked on the Xero website can leave the
    connector token still valid — so a token-only check (``resolve_xero_token``)
    would wrongly report "connected". We therefore flash when EITHER no token
    resolves OR the live sync flipped status to "disconnected".
    """
    if org is None or not getattr(org, "xero_org_id", None):
        return False

    token_resolved = resolve_xero_token(org.id, current_user) is not None

    # Authoritative live reconcile (best-effort; gate on a resolvable connector
    # token since the sync needs one to call Xero).
    if token_resolved:
        try:
            sync_entity_xero_status(org.id)
            refreshed = Entity.query.get(org.id)
            if refreshed is not None:
                org = refreshed
        except Exception as sync_error:
            logger.warning(
                "Xero live status sync failed for entity %s: %s",
                org.id, sync_error,
            )

    if token_resolved and getattr(org, "status", None) != "disconnected":
        return False

    flash(
        "This entity has been disconnected from Xero. Please reconnect it to "
        "keep your data in sync.",
        "danger",
    )
    return True


def _integration_minimal_entity_settings_post(entity_id: str, _from: str | None):
    """Save country/currency and (admin only) the entity name from the classic
    Xero integration page. No Xero mapping fields are handled here."""
    try:
        entity = Entity.query.get_or_404(entity_id)

        # Entity rename is admin-only and shares the "Save Changes" button with
        # the country/currency save. The field is disabled in the UI for
        # non-admins (so the browser omits it); re-check the permission here so
        # a crafted POST can't bypass the gate.
        if (
            "entity_name" in request.form
            and has_permission(current_user, Permission.ENTITY_RENAME, entity_id)
        ):
            name_form = (request.form.get("entity_name") or "").strip()
            if name_form != (entity.name or ""):
                if not name_form:
                    flash("I need a name for this entity before I can save it.", "danger")
                    return _redirect_xero_mapping(
                        entity_id, _from, return_view="entity_settings"
                    )
                if len(name_form) > 100:
                    flash("That name goes on a bit! Please keep it to 100 characters or fewer.", "danger")
                    return _redirect_xero_mapping(
                        entity_id, _from, return_view="entity_settings"
                    )
                if Entity.query.filter(
                    Entity.name == name_form, Entity.id != entity_id
                ).first():
                    flash("Oh, someone got there first! Do you have another name in mind?", "danger")
                    return _redirect_xero_mapping(
                        entity_id, _from, return_view="entity_settings"
                    )
                entity.name = name_form

        apply_country_currency_selection(entity, request.form)
        db.session.commit()
        flash("Settings saved!", "success")
    except IntegrityError as exc:
        db.session.rollback()
        logger.error(
            "integration_minimal_entity_settings_post integrity error entity=%s: %s",
            entity_id,
            exc,
        )
        flash(
            "I couldn't save these settings — one of the values needs to be "
            "unique and it's already in use. Could you check your entries and try again?",
            "danger",
        )
    except Exception as exc:
        db.session.rollback()
        logger.error(
            "integration_minimal_entity_settings_post failed entity=%s: %s",
            entity_id,
            exc,
        )
        flash(
            "I couldn't save your settings. Could you check your entries and try again?",
            "danger",
        )
    return _redirect_xero_mapping(entity_id, _from, return_view="entity_settings")
@entity_bp.route("/entity/<string:entity_id>/settings/xero",
                 methods=["GET", "POST"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero settings for this entity.",
)
def entity_settings(entity_id=None):

    # Check if user has any entities before allowing access to report history
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you any entity settings.",
            "info",
        )
        return redirect(url_for("entity.entity_list"))

    # Best-effort: sync connection status before proceeding so UI reflects
    # reality
    try:
        if entity_id:
            sync_entity_xero_status(entity_id)
    except Exception:
        logger.warning(f"Entity settings: status sync skipped for {entity_id}")

    if request.method == "POST":
        _from = request.form.get("_from") or request.args.get("from")
        if request.form.get("_integration_minimal_save") == "1":
            if not has_permission(
                current_user, Permission.XERO_SETTINGS_UPDATE, entity_id
            ):
                return permission_denied(
                    "You do not have permission to update Xero settings.",
                    entity_id=entity_id,
                )
            return _integration_minimal_entity_settings_post(entity_id, _from)

        if not has_permission(current_user, Permission.XERO_SETTINGS_UPDATE, entity_id):
            return permission_denied(
                "You do not have permission to update Xero settings.",
                entity_id=entity_id,
            )
        return_view = request.form.get("_xero_mapping_return_view") or "entity_settings"
        if return_view not in ("entity_settings", "entity_settings_entity"):
            return_view = "entity_settings"
        _xero_resp = process_xero_account_mapping_post(
            entity_id,
            return_view=return_view,
            defer_success_redirect=False,
        )
        if _xero_resp is not None:
            return _xero_resp
        if not request.form.get("main_bank"):
            flash(
                "Please enter all default settings for this entity", "danger",
            )
            return _redirect_xero_mapping(entity_id, _from, return_view=return_view)
    try:
        org = Entity.query.get_or_404(entity_id)

        logger.info(f"Starting entity settings load for {entity_id}")

        # Try to validate token (but don't fail if it doesn't work)
        token_valid = False
        try:
            token_valid = ensure_valid_token(current_user)
        except Exception as token_error:
            logger.warning(
                f"Token validation failed, will use database data: {str(token_error)}"
            )

        xero_token_resolved = (
            resolve_xero_token(entity_id, current_user) is not None
        )

        # Authoritative LIVE check FIRST: hit Xero's /connections and reconcile
        # org.status (connected/disconnected) to match reality. This must run
        # BEFORE the reconnect flash below, otherwise a connection revoked on the
        # Xero website — where the token can still be valid — would leave
        # org.status stale and the flash would wrongly say "connected". Gate on a
        # resolvable connector token; sync validates that token itself.
        if xero_token_resolved:
            try:
                sync_entity_xero_status(entity_id)
                org = Entity.query.get(entity_id) or org  # re-read fresh status
            except Exception as sync_error:
                logger.warning(
                    f"Status sync failed, continuing with database data: {str(sync_error)}"
                )

        # Live check: flash "reconnect" when the entity was meant to be connected
        # to Xero but is no longer live — either no token resolves, OR the live
        # sync above flipped status to "disconnected" (revoked on Xero's side).
        if org.xero_org_id and (
            not xero_token_resolved or org.status == "disconnected"
        ):
            flash(
                "This entity has been disconnected from Xero. Please reconnect "
                "it to keep your data in sync.",
                "danger",
            )

        if (
            xero_token_resolved
            and org.xero_org_id
            and not getattr(org, "xero_tenant_name", None)
        ):
            try:
                org_data = get_xero_data_dynamic(
                    "Organisation", entity_id=entity_id
                )
                if org_data and not org_data.get("error"):
                    organisations = org_data.get("Organisations") or []
                    if organisations:
                        name = organisations[0].get("Name")
                        if name:
                            org.xero_tenant_name = name
                            db.session.commit()
            except Exception as exc:
                logger.warning(
                    f"Failed to backfill xero_tenant_name for {entity_id}: {exc}"
                )

        # (Live status sync already ran above, before the reconnect flash, so
        # org.status reflects Xero's real connection state here.)

        # Sync chart of accounts from Xero in the background (non-blocking).
        # Fetches ALL Xero accounts, upserts new ones, and sets status=ACTIVE /
        # status=ARCHIVED on existing DB rows to match Xero's live state.
        # Skipped gracefully if Xero tokens are missing or the entity is not connected.
        if org.status == "connected" and org.xero_org_id:
            try:
                token_user_for_sync = get_xero_token_user_for_entity(entity_id)
                if token_user_for_sync and ensure_valid_token(token_user_for_sync):
                    _app = current_app._get_current_object()
                    sync_xero_accounts_to_db_background(
                        entity_id,
                        token_user_for_sync.access_token,
                        org.xero_org_id,
                        flask_app=_app,
                    )
            except Exception as _coa_sync_err:
                logger.warning(
                    "entity_settings GET: chart-of-accounts sync skipped entity=%s: %s",
                    entity_id,
                    _coa_sync_err,
                )

        # Fetch Xero tenant name (optional, don't fail if it doesn't work)
        xero_tenant_name = None

        # Only fetch tenant name if entity is connected
        if org.status == "connected":
            # First, try to use current user's token if they have access
            if token_valid:
                try:
                    headers = {
                        "Authorization": f"Bearer {current_user.access_token}",
                        "Content-Type": "application/json",
                    }
                    connections_response = requests.get(
                        "https://api.xero.com/connections",
                        headers=headers,
                    )
                    if connections_response.status_code == 200:
                        connections = connections_response.json()
                        for conn in connections:
                            if conn.get("tenantId") == str(org.xero_org_id):
                                xero_tenant_name = conn.get("tenantName")
                                break
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch Xero tenant name with current user token: {str(e)}"
                    )

            # If current user doesn't have access, try to find a user who does
            if not xero_tenant_name and org.xero_org_id:
                try:
                    # Find a user whose xero_entity_id matches the entity's
                    # xero_org_id
                    owner_user = User.query.filter(
                        User.xero_entity_id == str(org.xero_org_id),
                        User.access_token.isnot(None),
                    ).first()

                    if owner_user:
                        # Try to validate and use the owner's token
                        if ensure_valid_token(owner_user):
                            try:
                                headers = {
                                    "Authorization": f"Bearer {owner_user.access_token}",
                                    "Content-Type": "application/json",
                                }
                                connections_response = requests.get(
                                    "https://api.xero.com/connections",
                                    headers=headers,
                                )
                                if connections_response.status_code == 200:
                                    connections = connections_response.json()
                                    for conn in connections:
                                        if conn.get("tenantId") == str(
                                                org.xero_org_id):
                                            xero_tenant_name = conn.get(
                                                "tenantName")
                                            break
                            except Exception as e:
                                logger.warning(
                                    f"Failed to fetch Xero tenant name with owner user token: {str(e)}"
                                )
                except Exception as e:
                    logger.warning(
                        f"Failed to find owner user for entity {entity_id}: {str(e)}"
                    )

        integration_bills_shell = request.args.get("from") == "bills"
        if integration_bills_shell:
            bank_accounts = []
            cashsale_account = []
            owners_account = []
            discrepancy_account = []
            contacts = []
            main_bank_account_default = None
            deposit_bank_account_default = None
            cashsale_account_default = None
            cashsale_contact_default = None
            owners_account_default = None
            owners_contact_default = None
            discrepancy_bank_default = None
            discrepancy_account_default = None
            discrepancy_contact_default = None
            current_setting_contact = []
        else:
            # Petty Cash settings dropdowns are always populated from the
            # database, regardless of connection state. The background Xero ->
            # DB sync above keeps account_info / xero_contact_sync current.
            if not hasattr(g, "_xero_data_cache"):
                g._xero_data_cache = {}

            cache_key = f"{entity_id}_{org.xero_org_id}"

            if cache_key not in g._xero_data_cache:
                db_accounts = AccountInfo.query.filter(
                    AccountInfo.entity_id == entity_id,
                    AccountInfo.status == "ACTIVE",
                ).all()
                db_contacts = XeroContactSync.query.filter_by(
                    entity_id=entity_id).all()

                all_accounts = [
                    account_info_to_xero_format(acc) for acc in db_accounts]
                contacts = [
                    contact_sync_to_xero_format(c) for c in db_contacts]

                bank_accounts = [
                    acc for acc in all_accounts if acc.get("Type") == "BANK"]
                cashsale_account = [
                    acc
                    for acc in all_accounts
                    if acc.get("Type") in ["SALES", "REVENUE", "INCOME"]
                ]
                owners_account = [
                    acc
                    for acc in all_accounts
                    if acc.get("Type") in [
                        "NONCURRENT",
                        "CURRLIAB",
                        "TERMLIAB",
                        "FIXED",
                        "INVENTORY",
                        "DIRECTCOSTS",
                        "EXPENSE",
                    ]
                    and not (
                        isinstance(acc.get("SystemAccount"), str)
                        and acc.get("SystemAccount", "").strip() != ""
                    )
                ]
                discrepancy_account = [
                    acc for acc in all_accounts
                    if acc.get("Type") in ("EXPENSE", "DIRECTCOSTS")
                ]

                g._xero_data_cache[cache_key] = {
                    "bank_accounts": bank_accounts,
                    "cashsale_account": cashsale_account,
                    "owners_account": owners_account,
                    "discrepancy_account": discrepancy_account,
                    "contacts": contacts,
                }
            else:
                cached_data = g._xero_data_cache[cache_key]
                bank_accounts = cached_data["bank_accounts"]
                cashsale_account = cached_data["cashsale_account"]
                owners_account = cached_data["owners_account"]
                discrepancy_account = cached_data["discrepancy_account"]
                contacts = cached_data["contacts"]

            current_setting_contact = (
                db.session.query(XeroContactSync)
                .filter(XeroContactSync.entity_id == entity_id)
                .all()
            )

            _settings_row = EntityPettycashSettings.query.filter_by(
                entity_id=entity_id
            ).first()

            def _account_default(account_id):
                if not account_id:
                    return None
                acc = AccountInfo.query.get(account_id)
                return account_info_to_xero_format(acc) if acc else None

            def _contact_default(contact_id):
                if not contact_id:
                    return None
                c = XeroContactSync.query.get(contact_id)
                return contact_sync_to_xero_format(c) if c else None

            if _settings_row is None:
                main_bank_account_default = None
                deposit_bank_account_default = None
                cashsale_account_default = None
                owners_account_default = None
                discrepancy_bank_default = None
                discrepancy_account_default = None
                cashsale_contact_default = None
                discrepancy_contact_default = None
                owners_contact_default = None
            else:
                main_bank_account_default = _account_default(
                    _settings_row.pettycash_account_id
                )
                deposit_bank_account_default = _account_default(
                    _settings_row.bank_account_id
                )
                cashsale_account_default = _account_default(
                    _settings_row.cash_sale_account_id
                )
                owners_account_default = _account_default(
                    _settings_row.director_account_id
                )
                discrepancy_bank_default = _account_default(
                    _settings_row.discrepancy_bank_account_id
                )
                discrepancy_account_default = _account_default(
                    _settings_row.discrepancy_account_id
                )
                cashsale_contact_default = _contact_default(
                    _settings_row.cash_sale_contact_id
                )
                discrepancy_contact_default = _contact_default(
                    _settings_row.discrepancy_contact_id
                )
                owners_contact_default = _contact_default(
                    _settings_row.director_contact_id
                )

        if entity_id:
            logger.info(
                f"Fetched current entity settings for entity ID: {entity_id}")
        logger.info(
            f"Fetched current entity settings contact for entity ID: {current_setting_contact}"
        )
    except Exception as e:
        logger.error(f"Error getting entity settings: {str(e)}")
        return redirect(url_for("entity.entity_list"))

    entity_acronym = build_entity_acronym(org.name) if org else ""

    from blueprints.user_management.services.roles import get_all_roles

    roles = get_all_roles()
    roles = [role.name for role in roles]

    # Country / currency registries: the dropdowns list the active rows and
    # preselect via the entity's country_code / currency_id FKs.
    (
        country_code,
        currencies,
        selected_country,
        selected_currency,
    ) = _country_currency_choices(org)

    can_edit_xero_settings = has_permission(
        current_user, Permission.XERO_SETTINGS_UPDATE, entity_id
    )
    can_rename_entity = has_permission(
        current_user, Permission.ENTITY_RENAME, entity_id
    )

    from_param = request.args.get("from")
    template = (
        "entity/settings_xero_bills_ui.html"
        if from_param == "bills"
        else "entity/settings.html"
    )
    if from_param == "bills":
        logger.info(
            "entity_settings: rendering bills UI template for entity_id=%s",
            entity_id,
        )

    return render_template(
        template,
        bill_settings_url=billing_settings_app_url(
            entity_id, org, current_user.id, from_bills=from_param == "bills"
        ),
        roles=roles,
        can_edit_xero_settings=can_edit_xero_settings,
        can_rename_entity=can_rename_entity,
        country_code=country_code,
        currencies=currencies,
        selected_country=selected_country,
        selected_currency=selected_currency,
        cashsale_account_default=cashsale_account_default,
        cashsale_contact_default=cashsale_contact_default,
        deposit_bank_account_default=deposit_bank_account_default,
        discrepancy_bank_default=discrepancy_bank_default,
        discrepancy_account_default=discrepancy_account_default,
        discrepancy_contact_default=discrepancy_contact_default,
        main_bank_account_default=main_bank_account_default,
        owners_account_default=owners_account_default,
        owners_contact_default=owners_contact_default,
        cashsale_account=cashsale_account,
        owners_account=owners_account,
        discrepancy_account=discrepancy_account,
        org=org,
        bank_accounts=bank_accounts,
        contacts=contacts,
        last_connected_at=(
            org.last_connected_at if org.last_connected_at else org.created_at
        ),
        xero_tenant_name=xero_tenant_name,
        xero_token_resolved=xero_token_resolved,
        entity_acronym=entity_acronym,
    )


@entity_bp.route("/entity/settings/users/<string:org_id>", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.USER_VIEW_ALL,
    entity_arg="org_id",
    message="You do not have permission to view all users for this entity.",
)
def entity_settings_users(org_id):
    from_origin = request.args.get("from")
    try:
        # Get the entity by ID
        org = Entity.query.get_or_404(org_id)

        # Mirror the Entity & Integration / Petty Cash Settings pages: any
        # landing under Settings (including the Users tab opened directly
        # from the sidebar) refreshes account_info from Xero in the
        # background so the CoA stays in sync regardless of which sub-tab
        # the user opens first.
        if org.status == "connected" and org.xero_org_id:
            try:
                token_user_for_sync = get_xero_token_user_for_entity(org_id)
                if token_user_for_sync and ensure_valid_token(token_user_for_sync):
                    sync_xero_accounts_to_db_background(
                        org_id,
                        token_user_for_sync.access_token,
                        org.xero_org_id,
                        flask_app=current_app._get_current_object(),
                    )
            except Exception as _sync_err:
                logger.warning(
                    "entity_settings_users: chart-of-accounts sync skipped entity=%s: %s",
                    org_id,
                    _sync_err,
                )

        # Get users associated with this entity
        users = (
            db.session.query(User, UserEntity.role)
            .join(UserEntity, User.id == UserEntity.user_id)
            .filter(UserEntity.entity_id == org_id, UserEntity.approved)
            .all()
        )

        entity_acronym = ""
        if org and org.name:
            words = org.name.split()
            entity_acronym = "".join([word[0].upper()
                                     for word in words if word])

        # Assignable roles, mirroring the onboarding invite step
        # (onboarding/components/OnboardingSteps.jsx ROLES). Hardcoded to the
        # canonical four so the dropdown never shows redundant/near-duplicate
        # rows from the roles table.
        entity_user_role_options = [
            {"value": "admin", "name": "Admin"},
            {"value": "accountant", "name": "Accountant"},
            {"value": "shop_manager", "name": "Shop Manager"},
            {"value": "cashier", "name": "Cashier"},
        ]
        roles = entity_user_role_options

        bills_settings_query = "?from=bills" if from_origin == "bills" else ""

        template = (
            "entity/settings_users_bills_ui.html"
            if from_origin == "bills"
            else "entity/settings_users.html"
        )
        if from_origin == "bills":
            logger.info(
                "entity_settings_users: rendering bills UI template for org_id=%s",
                org_id,
            )

        return render_template(
            template,
            org=org,
            bill_settings_url=billing_settings_app_url(
                org_id, org, current_user.id, from_bills=from_origin == "bills"
            ),
            users=users,
            entity_acronym=entity_acronym,
            roles=roles,
            entity_user_role_options=entity_user_role_options,
            bills_settings_query=bills_settings_query,
            is_view_only=not has_permission(
                current_user, Permission.USER_INVITE, org_id
            ),
        )
    except Exception as e:
        logger.error(f"Error accessing entity settings users: {str(e)}")
        flash(
            "I couldn't load the user settings for this entity. "
            "Could you go back to your entities and try again?",
            "danger",
        )
        # Redirect to the entity list rather than back to this same page: if the
        # failure persists, self-redirecting here would loop indefinitely.
        return redirect(url_for("entity.entity_list"))


@entity_bp.route("/entity/settings/entity/<string:org_id>",
                 methods=["GET", "POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.COA_VIEW,
    entity_arg="org_id",
    message="You do not have permission to view CoA settings for this entity.",
)
@require_module(
    "PETTY_CASH",
    entity_arg="org_id",
    message="Petty Cash is not activated for this entity.",
)
def entity_settings_entity(org_id):
    try:
        # Get the entity by ID
        org = Entity.query.get_or_404(org_id)

        # Handle POST request (save country selection)
        if request.method == "POST":
            if not has_permission(current_user, Permission.ENTITY_UPDATE, org_id):
                return permission_denied(
                    "You do not have permission to update this entity.",
                    entity_id=org_id,
                )
            if not has_permission(current_user, Permission.COA_UPDATE, org_id):
                return permission_denied(
                    "You do not have permission to update CoA settings.",
                    entity_id=org_id,
                )
            if not has_permission(current_user, Permission.COA_CREATE, org_id):
                return permission_denied(
                    "You do not have permission to create CoA settings.",
                    entity_id=org_id,
                )
            if not has_permission(current_user, Permission.COA_DELETE, org_id):
                return permission_denied(
                    "You do not have permission to delete CoA settings.",
                    entity_id=org_id,
                )
            try:
                if request.form.get("main_bank") and has_permission(
                    current_user, Permission.COA_UPDATE, org_id
                ):
                    _xr = process_xero_account_mapping_post(
                        org_id,
                        return_view="entity_settings_entity",
                        defer_success_redirect=True,
                    )
                    if _xr is not None:
                        return _xr

                apply_country_currency_selection(org, request.form)

                selected_account_codes = request.form.getlist(
                    "account_codes[]")
                logger.info(
                    f"Saving selected account codes for entity {org_id}: {selected_account_codes}"
                )
                if org.xero_org_id:
                    try:
                        token_user = get_xero_token_user_for_entity(org_id)
                        if ensure_valid_token(token_user):
                            sync_expense_account_info_from_xero(
                                org_id,
                                token_user.access_token,
                                org.xero_org_id,
                                selected_account_codes=selected_account_codes,
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to update expense account codes: {str(e)}"
                        )

                db.session.commit()

                # Sync entity_account_xero to reflect the petty cash CoA tick
                # state (shared with the onboarding Step 5 save).
                try:
                    eligible_accounts = AccountInfo.query.filter(
                        AccountInfo.entity_id == org_id,
                        AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
                    ).all()
                    # Drive is_active straight from the ticked checkboxes
                    # (account_codes[]), NOT from account_info.status. The
                    # status path filters out Xero system accounts (497/498/499)
                    # and is also overwritten by the background Xero sync, so it
                    # could not honor a tick on those accounts.
                    selected_code_set = {
                        str(c).strip()
                        for c in selected_account_codes
                        if c and str(c).strip()
                    }
                    selected_ids = {
                        acc.id for acc in eligible_accounts
                        if acc.xero_code
                        and str(acc.xero_code).strip() in selected_code_set
                    }

                    existing_eax = (
                        db.session.query(EntityAccountXero)
                        .join(
                            AccountInfo,
                            EntityAccountXero.account_id == AccountInfo.id,
                        )
                        .filter(AccountInfo.entity_id == org_id)
                        .all()
                    )
                    existing_by_account_id = {
                        eax.account_id: eax for eax in existing_eax
                    }

                    for eax in existing_eax:
                        eax.is_active = eax.account_id in selected_ids
                        # Refresh denormalized fields so the table can answer
                        # questions without joining account_info.
                        info = next(
                            (a for a in eligible_accounts if a.id == eax.account_id),
                            None,
                        )
                        if info is not None:
                            eax.name = info.name
                            eax.type = info.type
                            eax.xero_org_id = org.xero_org_id
                            eax.xero_account_id = info.xero_account_id

                    for acc in eligible_accounts:
                        if acc.id in existing_by_account_id:
                            continue
                        db.session.add(
                            EntityAccountXero(
                                id=str(uuid.uuid4()),
                                account_id=acc.id,
                                name=acc.name,
                                type=acc.type,
                                xero_org_id=org.xero_org_id,
                                xero_account_id=acc.xero_account_id,
                                is_active=(acc.id in selected_ids),
                            )
                        )

                    db.session.commit()
                    logger.info(
                        "entity_settings_entity POST: synced entity_account_xero "
                        "for entity=%s active=%s total=%s",
                        org_id, len(selected_ids), len(eligible_accounts),
                    )
                except Exception as eax_err:
                    db.session.rollback()
                    logger.warning(
                        "entity_settings_entity POST: failed to sync "
                        "entity_account_xero entity=%s: %s",
                        org_id, eax_err,
                    )

                flash("Entity settings saved!", "success")
                _from = request.form.get("_from") or request.args.get("from")
                return redirect(
                    url_for(
                        "entity_settings_entity",
                        org_id=org_id,
                        **{"from": _from} if _from == "bills" else {},
                    )
                )
            except IntegrityError as e:
                db.session.rollback()
                logger.error(f"Entity settings integrity error: {str(e)}")
                flash(
                    "I couldn't save these entity settings — one of the values "
                    "needs to be unique and it's already in use. Could you check "
                    "your entries and try again?",
                    "danger",
                )
                _from = request.form.get("_from") or request.args.get("from")
                return redirect(
                    url_for(
                        "entity_settings_entity",
                        org_id=org_id,
                        **{"from": _from} if _from == "bills" else {},
                    )
                )
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating entity settings: {str(e)}")
                flash(
                    "I couldn't save your entity settings. Could you check your "
                    "entries and try again?",
                    "danger",
                )
                _from = request.form.get("_from") or request.args.get("from")
                return redirect(
                    url_for(
                        "entity_settings_entity",
                        org_id=org_id,
                        **{"from": _from} if _from == "bills" else {},
                    )
                )

        # Handle GET request (display form)
        # Compare Xero live vs DB and sync both modules if changes detected
        if org.xero_org_id:
            try:
                token_user = get_xero_token_user_for_entity(org_id)
                if token_user and ensure_valid_token(token_user):
                    # Full sync inserts BANK / EQUITY / etc rows that the
                    # CoA-only sync skips, so visiting this page also catches
                    # new accounts of every type (e.g. a newly-added Bank in
                    # Xero appearing in the Petty Cash Account dropdown).
                    sync_xero_accounts_to_db_background(
                        org_id,
                        token_user.access_token,
                        org.xero_org_id,
                        flask_app=current_app._get_current_object(),
                    )
                    # Also sync contacts → xero_contact_sync so the Cash Sales /
                    # Director / Discrepancy contact dropdowns are seeded on page
                    # load. Without this the contact table only filled in after a
                    # user manually created a contact.
                    sync_contacts_if_changed_background(
                        org_id,
                        token_user.access_token,
                        org.xero_org_id,
                        flask_app=current_app._get_current_object(),
                    )
                    sync_chart_of_accounts_if_changed(
                        org_id, token_user.access_token, org.xero_org_id,
                        user_id=str(current_user.id),
                    )
            except Exception as rec_err:
                logger.warning(
                    "entity_settings_entity: chart sync skipped for %s: %s",
                    org_id, rec_err,
                )

            if org.xero_org_id and (org.period_lock_date is None or org.end_of_year_lock_date is None):
                backfill_lock_dates_if_needed_background(org.id, current_user.access_token, org.xero_org_id)

        # Country / currency registries: the dropdowns list the active rows
        # and preselect via the entity's country_code / currency_id FKs.
        (
            country_code,
            currencies,
            selected_country,
            selected_currency,
        ) = _country_currency_choices(org)

        # Petty cash CoA list is sourced from entity_account_xero (joined to
        # account_info) — the single source of truth — instead of a live Xero
        # API call. EntityAccountXero.is_active drives the checkbox state. No
        # SystemAccount / code-497 / Status filtering is applied here: whatever
        # the sync placed in entity_account_xero is shown as-is.
        # Backfill entity_account_xero from account_info SYNCHRONOUSLY before
        # building the list below. The heavier Xero refresh runs in the
        # background (above) and the inner join below only returns accounts that
        # already have an entity_account_xero row — so on first load the list
        # would be partial until the background thread caught up. This backfill
        # reads account_info only (no Xero API call), so it's fast and safe to
        # run inline. Wrapped so a failure can't break the page.
        try:
            sync_xero_coa_pettycash(org_id, org.xero_org_id)
        except Exception as _coa_backfill_err:
            logger.warning(
                "entity_settings_entity: petty cash CoA backfill skipped "
                "entity={}: {}",
                org_id,
                _coa_backfill_err,
            )

        expense_account_code = []
        if org_id:
            coa_rows = (
                db.session.query(AccountInfo, EntityAccountXero.is_active)
                .join(
                    EntityAccountXero,
                    EntityAccountXero.account_id == AccountInfo.id,
                )
                .filter(
                    AccountInfo.entity_id == org_id,
                    AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
                )
                .order_by(AccountInfo.xero_code)
                .all()
            )
            for acc, is_active in coa_rows:
                entry = account_info_to_xero_format(acc)
                entry["Name"] = html.unescape(entry.get("Name", "") or "")
                entry["_is_selected"] = bool(is_active)
                expense_account_code.append(entry)
            logger.info(
                "entity_settings_entity: loaded {} petty cash CoA accounts "
                "from entity_account_xero for entity {}",
                len(expense_account_code), org_id,
            )

        entity_acronym = ""
        if org and org.name:
            words = org.name.split()
            entity_acronym = "".join([word[0].upper()
                                     for word in words if word])

        from_param = request.args.get("from")
        token_valid = False
        try:
            token_valid = ensure_valid_token(current_user)
        except Exception as tok_err:
            logger.warning(
                "entity_settings_entity: token check skipped entity=%s: %s",
                org_id,
                tok_err,
            )
        can_edit_xero_settings = has_permission(
            current_user, Permission.COA_UPDATE, org_id
        )
        from blueprints.entity.services.xero_mapping_form_context import \
            build_xero_mapping_form_context

        _mapping = build_xero_mapping_form_context(org_id, org, token_valid)

        template = (
            "entity/settings_entity_bills_ui.html"
            if from_param == "bills"
            else "entity/settings_entity.html"
        )
        _can_edit_coa = has_permission(current_user, Permission.COA_UPDATE, org_id)
        # Live check (hits Xero /connections): warn if the entity was connected
        # to Xero but is no longer live, so the user knows to reconnect.
        _flash_if_xero_disconnected(org)
        return render_template(
            template,
            org=org,
            bill_settings_url=billing_settings_app_url(
                org_id, org, current_user.id, from_bills=from_param == "bills"
            ),
            country_code=country_code,
            currencies=currencies,
            selected_country=selected_country,
            selected_currency=selected_currency,
            expense_account_code=expense_account_code,
            entity_acronym=entity_acronym,
            is_view_only=not _can_edit_coa,
            can_edit_xero_settings=can_edit_xero_settings,
            **_mapping,
        )
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error accessing entity settings: {str(e)}")
        flash(
            "Something got tangled up while loading these settings. Mind trying again?",
            "danger",
        )
        return redirect(url_for("entity_settings", entity_id=org_id))


@entity_bp.route("/entity/settings/module/<string:org_id>", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_VIEW,
    entity_arg="org_id",
    message="You do not have permission to view module settings for this entity.",
)
def entity_settings_module(org_id):
    """Module settings tab. Shows the entity's module entitlements as cards
    with on/off toggles (PETTY_CASH, BILL)."""
    from blueprints.entity.services.modules import (get_module_cards,
                                                    get_subscription_summary)

    org = Entity.query.get_or_404(org_id)

    entity_acronym = build_entity_acronym(org.name) if org else ""

    module_cards = get_module_cards(org_id)
    subscription_summary = get_subscription_summary(org_id)

    # Only admins may change modules; everyone else views read-only.
    can_manage_modules = has_permission(
        current_user, Permission.MODULE_MANAGE, org_id
    )

    from_param = request.args.get("from")
    template = (
        "entity/settings_module_bills_ui.html"
        if from_param == "bills"
        else "entity/settings_module.html"
    )

    return render_template(
        template,
        org=org,
        entity_acronym=entity_acronym,
        module_cards=module_cards,
        subscription_summary=subscription_summary,
        can_manage_modules=can_manage_modules,
        bill_settings_url=billing_settings_app_url(
            org_id, org, current_user.id, from_bills=from_param == "bills"
        ),
    )


@entity_bp.route("/entity/settings/module/<string:org_id>/toggle", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to change modules for this entity.",
)
def entity_settings_module_toggle(org_id):
    """Flip one module on/off for the entity. JSON in/out for the toggle UI."""
    from blueprints.entity.services.modules import set_entity_module

    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    enabled = bool(payload.get("enabled"))

    # Returns {"modules": {PETTY_CASH: bool, BILL: bool}}; the client uses the
    # full state to navigate to the correct shell, which re-renders the
    # subscription summary server-side.
    data, status = set_entity_module(org_id, code, enabled, actor="settings_ui")
    return jsonify(data), status


@entity_bp.route("/entity/settings/module/<string:org_id>/save", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to change modules for this entity.",
)
def entity_settings_module_save(org_id):
    """Apply the staged module on/off selections in one shot (the Save button).

    Body: ``{"modules": {"PETTY_CASH": bool, "BILL": bool}}``. Each canonical
    module is set to its requested state; returns the full resulting state so
    the client can navigate to the correct shell.
    """
    from blueprints.entity.services.modules import (MODULE_CODES,
                                                    _enabled_state,
                                                    set_entity_module)

    payload = request.get_json(silent=True) or {}
    desired = payload.get("modules")
    if not isinstance(desired, dict):
        return jsonify({"error": "A 'modules' object is required."}), 400

    # At least one module must stay active. Evaluate the resulting state
    # (requested values overlaid on the current ones) so even a partial save
    # can't leave the entity with no modules.
    current = _enabled_state(org_id)
    resulting = {
        code
        for code in MODULE_CODES
        if (bool(desired[code]) if code in desired else current.get(code, False))
    }
    if not resulting:
        return jsonify({"error": "At least one module must be active."}), 400

    data, status = {"modules": {}}, 200
    for code in MODULE_CODES:
        if code in desired:
            data, status = set_entity_module(
                org_id, code, bool(desired[code]), actor="settings_ui"
            )
            if status != 200:
                return jsonify(data), status
    return jsonify(data), status


@entity_bp.route("/entity/contact/create", methods=["POST"])
@login_required
@require_entity_access(entity_keys=("entity_id",))
@require_permission(
    Permission.CONTACT_CREATE,
    entity_keys=("entity_id",),
    message="You do not have permission to create contacts for this entity.",
)
def entity_contact_create():
    try:

        data = request.form.to_dict()
        logger.info(f"Creating contact with data: {data}")

        if not data:
            logger.error("No data received in request")
            return jsonify(
                {"status": "error", "message": "No data received"}), 400

        name = data.get("name")
        entity_id = data.get("entity_id")

        if not entity_id:
            logger.error("No 'entity_id' field in request data")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Missing 'entity_id' field in request",
                    }
                ),
                400,
            )

        if not name:
            logger.error("No 'name' field in request data")
            return (
                jsonify(
                    {"status": "error", "message": "Missing 'name' field in request"}
                ),
                400,
            )

        entity = Entity.query.get(entity_id)
        if not entity or not entity.xero_org_id:
            logger.error("No Xero org ID found for entity %s", entity_id)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "This entity isn't connected to Xero yet. Could you ask an admin to connect it?",
                    }),
                400,
            )

        xero_user = get_xero_token_user_for_entity(entity_id)
        if not xero_user or not xero_user.access_token:
            logger.error("No Xero access token found for entity")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "This entity isn't connected to Xero yet. Could you ask an admin to connect it?",
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
        contact_data = {"Contacts": [
            {"Name": name, "IsCustomer": True, "IsSupplier": False}]}

        logger.info(f"Creating contact in Xero: {contact_data}")

        def _make_xero_request():
            return requests.post(endpoint, headers={
                "Authorization": "Bearer " + xero_user.access_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Xero-Tenant-Id": str(entity.xero_org_id),
            }, json=contact_data)

        xero_response = _make_xero_request()

        logger.info(f"Xero response status: {xero_response.status_code}")
        logger.info(f"Xero response: {xero_response.text}")

        if xero_response.status_code in (401, 403):
            logger.warning("Xero returned %s, forcing token refresh and retrying", xero_response.status_code)
            if auto_refresh_token(xero_user):
                xero_response = _make_xero_request()
                logger.info(f"Retry Xero response status: {xero_response.status_code}")
                logger.info(f"Retry Xero response: {xero_response.text}")

        if xero_response.status_code not in (200, 201):
            # Log Xero's raw body; show the user plain language. This message is
            # rendered directly into a toast.
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

        xero_contact_data = xero_response.json()
        contacts = xero_contact_data.get("Contacts", [])

        if not contacts:
            logger.error("No contacts returned from Xero")
            return (
                jsonify(
                    {"status": "error", "message": "I couldn't add that contact to Xero. Mind trying again?"}
                ),
                400,
            )

        created_contact = contacts[0]
        xero_contact_id = created_contact.get("ContactID")
        contact_name = created_contact.get("Name")

        if not xero_contact_id:
            logger.error("No ContactID returned from Xero")
            return (
                jsonify(
                    {"status": "error", "message": "Xero didn't tell me which contact it created. Mind trying again?"}
                ),
                400,
            )

        # The contact is created in Xero and its name is returned to the
        # frontend below. The name is persisted on the expense itself
        # (shop_expense_draft.contact_name) when the expense is saved, so we do
        # NOT store a XeroContactSync record here.

        logger.info(
            f"Successfully created contact: {contact_name} with ID: {xero_contact_id}"
        )

        return (jsonify({"status": "success",
                         "message": f"Contact '{contact_name}' created successfully.",
                         "contact_id": xero_contact_id,
                         "name": contact_name,
                         }),
                201,
                )

    except Exception as e:
        logger.error(f"Error creating contact: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't add that contact. Mind trying again?",
                }),
            500,
        )


"""Entity settings service handlers extracted from legacy route implementations."""




# Restored implementation from legacy history: def
# debug_xero_settings(entity_id):
