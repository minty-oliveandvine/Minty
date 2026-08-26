"""Entity settings and contact routes."""

import html
import uuid
from typing import Protocol
from urllib.parse import quote

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
                            require_module, require_permission,
                            require_subscription_payer)
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


def _entity_members(org_id):
    """(members, signed_in) for an entity's Users tab — two answers, one query base.

    The tab asks two different questions and shows them one above the other.
    ``members`` is everyone approved, which is the roster you manage: it carries the
    roles, the subscriber tag and the edit/remove buttons. ``signed_in`` is who is
    here right now, which changes by the minute and is a read-only view.

    Built from the same base query so the second can never contain someone the first
    does not — "signed in but not a member" would be a contradiction the page had no
    way to explain.
    """
    from services.user_presence import is_signed_in_clause

    member_query = (
        db.session.query(User, UserEntity.role)
        .join(UserEntity, User.id == UserEntity.user_id)
        .filter(UserEntity.entity_id == org_id, UserEntity.approved)
    )
    return member_query.all(), member_query.filter(
        is_signed_in_clause(org_id)
    ).all()


@entity_bp.route("/entity/settings/users/<string:org_id>/presence", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.USER_VIEW_ALL,
    entity_arg="org_id",
    message="You do not have permission to view all users for this entity.",
)
def entity_settings_users_presence(org_id):
    """Just the SIGNED-IN rows, for the Users tab to poll.

    Only the lower section. The member roster above it changes when an admin invites,
    edits or removes someone — all of which reload the page — so re-sending it every
    twenty seconds would be traffic that never carries news, and it would fight the
    filter and any half-open row menu.

    Same permission gate as the page itself: the fragment shows what the page shows,
    so anything less would be a way around it.

    Returns rendered HTML rather than JSON rows on purpose — the markup stays defined
    once, in the partial, instead of being duplicated in JavaScript where the two
    copies would drift apart.

    Listed in pettycash/core/hooks.py as an endpoint that does NOT count as user
    activity. A tab left open here polls all night, and treating that as presence
    would keep whoever left it open on the list forever — the exact thing
    last_seen_at exists to prevent.
    """
    _members, signed_in = _entity_members(org_id)
    return jsonify(
        {
            "count": len(signed_in),
            "html": render_template(
                "entity/settings_users_signed_in.html", signed_in=signed_in
            ),
        }
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

        users, signed_in = _entity_members(org_id)

        # Who pays for this entity. NOT a role and not derivable from one — it is one
        # person's financial relationship, recorded per entity — so it cannot be read off
        # the ``role`` column beside it and has to be looked up separately.
        #
        # It is on this page because "who can change our modules" is answered by BOTH
        # columns at once: MODULE_MANAGE needs admin rank, and may_manage_subscription
        # needs the payer, so the one person who can is the admin carrying this tag. With
        # only the role shown, every admin here looked equally able to, and the ones who
        # are not the payer found the buttons missing with nothing on the page to explain
        # why. Compared as a string because the id may arrive as a UUID.
        from blueprints.subscription.services import store as sub_store

        payer_id = sub_store.payer_for_entity(org_id)
        subscriber_id = str(payer_id) if payer_id else None

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
            signed_in=signed_in,
            entity_acronym=entity_acronym,
            subscriber_id=subscriber_id,
            roles=roles,
            entity_user_role_options=entity_user_role_options,
            bills_settings_query=bills_settings_query,
            # THREE flags, because this page offers three actions behind three different
            # permissions — and it used to gate all of them on one.
            #
            # ``is_view_only`` is about INVITING, which is what it has always meant: it
            # drives the floating add-user button and the page's read-only styling.
            #
            # The per-row buttons are the ones that were wrong. Remove posts to
            # ``delete_user_role``, which requires USER_ROLE_DELETE (min ACCOUNTANT),
            # while this flag asks about USER_INVITE (min SHOP_MANAGER) — so a shop
            # manager was shown a remove button that the API answers with a 403. Each
            # button now asks about the permission its own endpoint enforces, and edit
            # gets the same treatment even though its floor happens to match today,
            # because "happens to match" is not a reason to ask the wrong question.
            is_view_only=not has_permission(
                current_user, Permission.USER_INVITE, org_id
            ),
            can_edit_users=has_permission(
                current_user, Permission.USER_ROLE_ASSIGN, org_id
            ),
            can_remove_users=has_permission(
                current_user, Permission.USER_ROLE_DELETE, org_id
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
    from blueprints.entity.services.modules import (build_subscription_panel,
                                                    get_billing_anchor,
                                                    get_module_cards,
                                                    get_next_payment_date,
                                                    get_subscription_summary,
                                                    next_payment_from_panel)

    org = Entity.query.get_or_404(org_id)

    entity_acronym = build_entity_acronym(org.name) if org else ""

    module_cards = get_module_cards(org_id)
    subscription_summary = get_subscription_summary(org_id)
    # Never shown. The anchor only answers "has this payer ever been billed", which is
    # what puts the panel in its paid rather than its trial mode.
    billing_anchor = get_billing_anchor(org_id)
    subscription_panel = build_subscription_panel(
        module_cards, subscription_summary, billing_anchor
    )
    # The date on the card at the top of the page, and it is READ OFF THE PANEL rather
    # than computed beside it — the card and the list below it were two answers to one
    # question, and they disagreed whenever anything other than the renewal came first.
    # The payer's projected cycle is only the fallback, for an entity with nothing
    # scheduled at all.
    next_payment_date = (
        next_payment_from_panel(subscription_panel) or get_next_payment_date(org_id)
    )

    # Only admins may change modules; everyone else views read-only.
    #
    # AND the payer. Permission says who may administer the entity; the payer is whose
    # card every one of these buttons spends. A co-admin pressing Cancel, Pay now or
    # Subscribe would move money belonging to someone who never saw the screen, so the
    # actions are hidden for anyone else — and refused server-side by
    # @require_subscription_payer, because hiding a button is not a permission.
    from blueprints.subscription.services import store as sub_store

    can_manage_modules = has_permission(
        current_user, Permission.MODULE_MANAGE, org_id
    ) and sub_store.may_manage_subscription(org_id, current_user.id)

    # Who to name when the actions are hidden. None while the entity has no payer, which
    # is the case any admin is allowed to act on.
    payer_id = sub_store.payer_for_entity(org_id)
    subscription_payer = (
        User.query.get(str(payer_id)) if payer_id and str(payer_id) != str(current_user.id)
        else None
    )

    # The lapsed-trial restart screen. None on an ordinary page, which is the single
    # falsy check the template branches on. Computed AFTER ``can_manage_modules``,
    # because a co-admin gets the naming fields and none of the Stripe reads behind them.
    from blueprints.entity.services.modules import build_consent_takeover

    consent_takeover = build_consent_takeover(
        org_id, current_user.id, can_manage=can_manage_modules
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
        subscription_panel=subscription_panel,
        next_payment_date=next_payment_date,
        can_manage_modules=can_manage_modules,
        consent_takeover=consent_takeover,
        subscription_payer=subscription_payer,
        # TEMPORARY, DEV ONLY. Gates the "add a payment method / confirm billing"
        # banner, which exists to reach those two flows directly while the trial
        # decision modal is being built — that modal is the customer-facing route to
        # both. Same debug gate as the dashboard's ``?notice=1`` re-show, so it is off
        # in production. Delete the banner and this flag once the modal is signed off.
        dev_tools=bool(current_app.debug),
        bill_settings_url=billing_settings_app_url(
            org_id, org, current_user.id, from_bills=from_param == "bills"
        ),
    )




@entity_bp.route("/entity/settings/module/<string:org_id>/checkout", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_checkout(org_id):
    """Subscribe the entity to one or more modules — one paid subscription each.

    Body: ``{"codes": ["BILL", ...]}`` (empty → auto-resolve the single unsubscribed
    module). When the entity already has a saved card the subscriptions are created
    immediately and the response is ``{"created": [codes]}`` (client reloads). When
    no card is on file the response is ``{"url": <setup checkout url>}`` to capture
    one first; the subscriptions are created on return (see ...checkout_complete).
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        start_modules_checkout,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes") or []
    return_url = url_for("entity.entity_settings_module", org_id=org_id, _external=True)
    # Setup checkout returns here so the subscriptions can be created once the card
    # is saved; Stripe substitutes the real id for {CHECKOUT_SESSION_ID}.
    complete_url = url_for(
        "entity.entity_settings_module_checkout_complete", org_id=org_id, _external=True
    ) + "?session_id={CHECKOUT_SESSION_ID}"
    try:
        result = start_modules_checkout(
            org,
            current_user,
            success_url=complete_url,
            cancel_url=return_url,
            requested_codes=codes,
        )
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("module checkout failed for %s", org_id)
        return (
            jsonify({"error": "Could not start checkout. Please try again."}),
            500,
        )
    if result.get("url"):
        return jsonify({"url": result["url"]}), 200
    if result.get("needs_confirmation"):
        return jsonify({"needs_confirmation": result["needs_confirmation"]}), 200
    return jsonify({"created": result.get("created", [])}), 200


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/authorize-billing", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_authorize_billing(org_id):
    """Authorise billing for this entity WITHOUT subscribing or charging.

    Used by the trial banner. The module still has trial time left, so the outcome
    should be "convert at term end" — not "charge now", which is what the subscribe
    path would do (an app-level trial has no Stripe object, so it doesn't read as an
    active subscription and paid checkout would happily bill it immediately).

    Idempotent: consent is once per entity.

    Body: ``{"payment_method": "pm_..."}``, OPTIONAL. Absent leaves whatever card this
    company is already on, which is what onboarding sends — it has just captured one, and
    the capture nominated it.

    When present it is nominated BEFORE consent is recorded: authorising a charge while
    the company still points at a different card authorises one the payer was never shown.

    NOMINATION IS PER COMPANY. It puts THIS company on that card and moves nothing else
    the payer owns — a change from when the engine read only
    ``invoice_settings.default_payment_method`` and every such choice was account-wide.
    Consent and the card stay two separate records: consenting says the payer may be
    billed for this company, the nomination says on what.
    """
    from blueprints.subscription.services import payment_methods
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        authorize_entity_billing,
    )

    org = Entity.query.get_or_404(org_id)
    pm_id = str((request.get_json(silent=True) or {}).get("payment_method") or "").strip()
    try:
        if pm_id:
            # Routed through ``set_for_entity``, which proves both halves: the method
            # belongs to this caller, and this caller is the company's payer. Another
            # payer's ``pm_...`` answers "not found" rather than being nominated.
            payment_methods.set_for_entity(current_user.id, org_id, pm_id)
    except payment_methods.PaymentMethodError as exc:
        return jsonify({"error": exc.message}), exc.status

    try:
        authorize_entity_billing(org, current_user)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("module billing authorization failed for %s", org_id)
        return (
            jsonify({"error": "Could not confirm billing. Please try again."}),
            500,
        )
    return jsonify({"ok": True}), 200


# --- The lapsed-trial restart screen -----------------------------------------
#
# Six routes serving ONE screen: four that manage the payer's cards from inside the page
# (Minty had no card UI at all — the payer portal owns that, over bearer auth on another
# origin), a quote, and the one that charges.
#
# ALL SIX carry the same guard stack as the money routes above, for the same reason:
# ``MODULE_MANAGE`` says who may administer the entity, ``require_subscription_payer``
# says whose card is about to be spent. ``org_id`` is unused by the four card handlers —
# a card belongs to the PERSON, not the company — and is there purely so the guards have
# an entity to scope to. Do not "tidy" it away.
#
# NOT csrf-exempt, unlike their bearer twins in ``subscription.routes.portal``. These are
# cookie-authenticated, so they want CSRF; the page sends ``X-CSRFToken`` from the
# ``csrf_token`` meta tag both settings templates carry.


def _session_payment_methods(handler):
    """Run one payment-method action for the signed-in user. Session auth, no CORS.

    The third transport over ``payment_methods.run`` — the bearer one in
    ``subscription.routes.portal`` and the onboarding one in ``entity.routes.create`` are
    the other two, and all three now share the failure handling rather than each keeping
    its own copy of it.
    """
    from blueprints.subscription.services import payment_methods

    payload, status = payment_methods.run(handler, current_user.id)
    return jsonify(payload), status


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/payment-methods", methods=["GET"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_payment_methods(org_id):
    """Every card saved on the payer's own account, plus which one bills THIS company.

    ``nominated_id`` is what the pickers on this page preselect, falling back to
    ``default_id`` when the company has none yet — the account default is offered, never
    assumed. Reading the list without it would preselect the account's main card for a
    company billed to a different one, and the payer would confirm a charge against a card
    that is not theirs to expect.
    """
    from blueprints.subscription.services import payment_methods

    return _session_payment_methods(
        lambda user_id: payment_methods.for_entity(user_id, org_id)
    )


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/payment-methods/setup-intent",
    methods=["POST"],
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_payment_methods_setup_intent(org_id):
    """Open a SetupIntent so the in-page card form can mount.

    Creates no Stripe customer: an abandoned form must not leave one behind, so the
    customer is made in ``confirm`` once Stripe says a card actually exists.
    """
    from blueprints.subscription.services import payment_methods

    return _session_payment_methods(payment_methods.start_setup)


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/payment-methods/confirm", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_payment_methods_confirm(org_id):
    """Adopt the card the browser just confirmed. Body: ``{setup_intent, make_default?}``.

    Nothing in the body is trusted — the intent is re-read from Stripe and refused unless
    it carries this caller's own ``metadata.user_id`` stamp.
    """
    from blueprints.subscription.services import payment_methods

    body = request.get_json(silent=True) or {}
    setup_intent = str(body.get("setup_intent") or "").strip()
    make_default = bool(body.get("make_default"))

    return _session_payment_methods(
        lambda user_id: payment_methods.confirm_setup(
            user_id, setup_intent, make_default=make_default
        )
    )


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/payment-methods/default", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_payment_methods_default(org_id):
    """Nominate the card every future invoice is charged against.

    Body: ``{payment_method}``. Account-wide, not per entity — renewals bill the payer.
    """
    from blueprints.subscription.services import payment_methods

    pm_id = str(
        (request.get_json(silent=True) or {}).get("payment_method") or ""
    ).strip()
    return _session_payment_methods(
        lambda user_id: payment_methods.set_default(user_id, pm_id)
    )


def _restart_state_and_codes(org_id, requested):
    """``(state, codes, error)`` for the two restart routes — their shared front half.

    The quote and the charge MUST resolve the submitted codes identically, or the payer
    is shown one number and billed against another set. So it is resolved once, here, and
    both routes call it.
    """
    from blueprints.subscription.services import consent

    state = consent.lapsed_trial_for_entity(org_id, current_user.id)
    if not state.get("mode"):
        return (
            state,
            [],
            (jsonify({"error": "There is nothing to restart for this company."}), 409),
        )

    codes = consent.codes_for_restart(state, requested)
    if not codes:
        return (
            state,
            [],
            (jsonify({"error": "Choose at least one module to restart."}), 422),
        )
    return state, codes, None


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/restart-quote", methods=["GET"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_restart_quote(org_id):
    """What restarting ``?codes=A,B`` would cost. READS ONLY.

    The screen re-prices on every tick and this is what it asks. It runs the same
    resolution as the charge, so the two can never name a different set of modules, and
    quotes through ``preview_subscribe_modules`` — the same figure the charge itself
    uses, rather than a price list that could disagree with it.
    """
    requested = [
        part for part in (request.args.get("codes") or "").split(",") if part.strip()
    ]
    _state, codes, error = _restart_state_and_codes(org_id, requested)
    if error:
        return error

    from blueprints.subscription.services.checkout import (CheckoutError,
                                                           preview_subscribe_modules)

    org = Entity.query.get_or_404(org_id)
    try:
        return jsonify(preview_subscribe_modules(org, current_user, codes)), 200
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("restart quote failed for %s", org_id)
        return jsonify({"error": "Could not price that. Please try again."}), 500


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/restart-billing", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_restart_billing(org_id):
    """Buy back a lapsed trial's modules. THIS CHARGES.

    Body: ``{codes: [...], payment_method?}``.

    The trial is over, so there is nothing to defer to. Unlike ``authorize-billing``,
    which records consent and lets the term end on its own, this subscribes and takes the
    payment now.

    Order matters and each step has its own answer:

    1. the entity must genuinely have a lapsed trial (409) — without it this URL would
       charge a company that is running perfectly well;
    2. the codes must be ones that actually lapsed (422) — the list comes from the
       browser, so a module the entity never had must never become a charge;
    3. the card is nominated for THIS COMPANY before the charge (402 when there is none)
       — charging while it still points at a different card bills one the payer was never
       shown, and there is no account default to fall back on;
    4. only then the subscribe, priced server-side from the resolved codes rather than
       from any amount the client sent.

    Consent lands through ``confirm_modules_checkout``, the same function every other
    paid purchase writes it from — this screen adds no new consent site.
    """
    from blueprints.subscription.services import payment_methods
    from blueprints.subscription.services.checkout import (CheckoutError,
                                                           confirm_modules_checkout)

    body = request.get_json(silent=True) or {}
    _state, codes, error = _restart_state_and_codes(org_id, body.get("codes"))
    if error:
        return error

    org = Entity.query.get_or_404(org_id)

    pm_id = str(body.get("payment_method") or "").strip()
    try:
        if pm_id:
            # Routed through ``set_for_entity``, which proves the method belongs to this
            # caller AND that this caller pays for the company before acting on it:
            # another payer's ``pm_...`` answers "not found" rather than being nominated.
            payment_methods.set_for_entity(current_user.id, org_id, pm_id)
        if not _entity_has_card(org_id):
            return jsonify({"error": "Choose a card before restarting billing."}), 402
    except payment_methods.PaymentMethodError as exc:
        return jsonify({"error": exc.message}), exc.status

    return_url = url_for("entity.entity_settings_module", org_id=org_id, _external=True)
    complete_url = url_for(
        "entity.entity_settings_module_checkout_complete", org_id=org_id, _external=True
    ) + "?session_id={CHECKOUT_SESSION_ID}"
    try:
        result = confirm_modules_checkout(
            org,
            current_user,
            success_url=complete_url,
            cancel_url=return_url,
            requested_codes=codes,
        )
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("restart billing failed for %s", org_id)
        return (
            jsonify({"error": "Could not restart billing. Please try again."}),
            500,
        )
    if result.get("url"):
        # The saved card could not be used after all, so Stripe collects a new one. Same
        # answer the confirm-billing route gives, and the page follows it.
        return jsonify({"url": result["url"]}), 200
    return jsonify({"ok": True, "restarted": result.get("created", codes)}), 200


def _entity_has_card(entity_id) -> bool:
    """Whether THIS company has a card nominated for it.

    Read AFTER any nomination above, so it sees the card just chosen rather than the state
    before it.

    Asks about the company, not the payer, because that is what will be charged. A payer
    with three cards saved and none of them put on this company cannot be billed for it —
    there is deliberately no account default to fall back on, so "has a card somewhere"
    is not the question.
    """
    from blueprints.subscription.services import store as sub_store

    return bool(sub_store.card_for_entity(entity_id))


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/confirm-billing", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_confirm_billing(org_id):
    """Record the payer's consent to bill THIS entity, then subscribe.

    Body: ``{"codes": [...]}`` — the same codes the checkout call returned
    ``needs_confirmation`` for. The payer has been shown the amount and the card and
    accepted; consent is per entity and permanent, so later purchases on this entity go
    straight through.

    The codes are re-validated downstream (they came back from the client), so this
    can still answer ``{"url": …}`` if the card disappeared in between.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        confirm_modules_checkout,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes") or []
    return_url = url_for("entity.entity_settings_module", org_id=org_id, _external=True)
    complete_url = url_for(
        "entity.entity_settings_module_checkout_complete", org_id=org_id, _external=True
    ) + "?session_id={CHECKOUT_SESSION_ID}"
    try:
        result = confirm_modules_checkout(
            org,
            current_user,
            success_url=complete_url,
            cancel_url=return_url,
            requested_codes=codes,
        )
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("module billing confirmation failed for %s", org_id)
        return (
            jsonify({"error": "Could not complete the subscription. Please try again."}),
            500,
        )
    if result.get("url"):
        return jsonify({"url": result["url"]}), 200
    return jsonify({"created": result.get("created", [])}), 200


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/checkout-complete", methods=["GET"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
def entity_settings_module_checkout_complete(org_id):
    """Return target for the setup-mode checkout: create the paid subscriptions from
    the saved card, then redirect back to the module settings page.

    On failure the reason is carried back as a ``checkout_error`` query param so the
    page can show it (instead of silently landing on an unchanged page)."""
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        complete_setup_checkout,
    )

    org = Entity.query.get_or_404(org_id)
    session_id = (request.args.get("session_id") or "").strip()
    # A card-only session (the "Add payment method" button with no customer yet) comes
    # back here too, because saving the card is the same operation. It carries no
    # modules_to_subscribe, so completing it correctly creates NOTHING — and reporting
    # "the subscription wasn't created" for that would call a success a failure.
    card_only = request.args.get("purpose") == "payment_method"
    module_url = url_for("entity.entity_settings_module", org_id=org_id)
    error_message = None
    if session_id:
        try:
            created = complete_setup_checkout(org, current_user, session_id)
            if not created and not card_only:
                error_message = (
                    "The subscription wasn't created. Please try again or check your "
                    "payment method."
                )
        except CheckoutError as exc:
            logger.exception(
                "checkout-complete: failed to create subscriptions for %s", org_id
            )
            error_message = exc.message
        except Exception:
            logger.exception(
                "checkout-complete: unexpected failure for %s", org_id
            )
            error_message = "Something went wrong finishing your subscription."
    else:
        error_message = "Checkout could not be completed (missing session)."
    if error_message:
        return redirect(f"{module_url}?checkout_error={quote(error_message)}")
    return redirect(module_url)


@entity_bp.route("/entity/settings/module/<string:org_id>/start-trial", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_start_trial(org_id):
    """Start a card-free trial for one or more never-subscribed modules.

    Body: ``{"codes": ["BILL", ...]}``. Each module must be trial-eligible (no
    Stripe subscription history in any status); a module that already used its
    trial is rejected (the UI offers paid checkout for those instead). Access is
    granted immediately by enabling the module in entity_function_map; the
    subscription webhook later reaffirms the same state. Returns the resulting
    ``{"modules": {code: bool}}`` so the client can re-render.
    """
    from blueprints.entity.services.modules import set_entity_module
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        start_module_trials,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes") or []
    try:
        started = start_module_trials(org, current_user, codes)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status

    data, status = {"modules": {}}, 200
    for code in started:
        data, status = set_entity_module(org_id, code, True, actor="subscription")
        if status != 200:
            return jsonify(data), status
    return jsonify(data), status


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/resume-preview", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_resume_preview(org_id):
    """What resuming cancelled modules would charge — for the dialog. Writes nothing.

    Body: ``{"codes": [...]}``. Resuming COLLECTS money up front when the cancellation's
    extension was already invoiced, so this is the disclosure that action needs: it was
    charging with no dialog at all before.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        preview_reinstate_modules,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    codes = [str(c).strip().upper() for c in (payload.get("codes") or []) if str(c).strip()]
    if not codes:
        return jsonify({"error": "codes are required"}), 400

    try:
        p = preview_reinstate_modules(org, current_user, codes)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("module resume preview failed for %s", org_id)
        return jsonify({"error": "Could not price that."}), 500

    fmt = lambda d: d.strftime("%d %b %Y") if d else None  # noqa: E731
    return (
        jsonify(
            {
                **{
                    k: v for k, v in p.items()
                    if k not in ("covers_from", "covers_to", "trial_end")
                },
                "trial_end": fmt(p.get("trial_end")),
                "covers_from": fmt(p.get("covers_from")),
                "covers_to": fmt(p.get("covers_to")),
                "covers_days": (
                    round((p["covers_to"] - p["covers_from"]).total_seconds() / 86400)
                    if p.get("covers_from") and p.get("covers_to")
                    else None
                ),
            }
        ),
        200,
    )


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/subscribe-preview", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_subscribe_preview(org_id):
    """What subscribing would charge — for the confirmation dialog. Writes nothing.

    Body: ``{"codes": ["PETTY_CASH", ...]}``. The figure is the one the purchase itself
    will bill (``changes.build_change``), not a price list: an entity joining mid-period
    pays for the days left in it, and a second module costs the difference to the bundle.

    Same permission as the purchase it describes — it states what the payer would be
    charged, so it is not more public than the charge.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        preview_subscribe_modules,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    codes = [str(c).strip().upper() for c in (payload.get("codes") or []) if str(c).strip()]
    if not codes:
        return jsonify({"error": "codes are required"}), 400

    try:
        return jsonify(preview_subscribe_modules(org, current_user, codes)), 200
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("module subscribe preview failed for %s", org_id)
        return jsonify({"error": "Could not price that subscription."}), 500


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/cancel-preview", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_cancel_preview(org_id):
    """What cancelling this module would do — for the confirmation dialog. Writes nothing.

    Body: ``{"code": "PETTY_CASH"}``. Returns the same shape ``preview_cancel_module``
    produces, with dates pre-formatted for display::

        {"kind": "paid", "access_until": "February 04, 2027",
         "amount_formatted": "120.00", "currency": "HKD", "charged_now": false,
         "remaining": ["BILL"], "remaining_amount": "280.00"}

    Same permission as the cancel itself: it discloses what the payer would be billed,
    so it is not more public than the action it describes.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        preview_cancel_module,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400
    # The OTHER modules going in the same click. An extension is priced against everything
    # leaving together, so a preview that doesn't know about its companions quotes each
    # module as if it were leaving alone — more than twice what the invoice then collects.
    also = [
        str(c).strip().upper()
        for c in (payload.get("also") or [])
        if str(c).strip()
    ]

    try:
        preview = preview_cancel_module(org, current_user, code, also)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status

    access_end = preview.get("access_end")
    return (
        jsonify(
            {
                "kind": preview.get("kind"),
                "access_until": access_end.strftime("%B %d, %Y") if access_end else None,
                "access_days": preview.get("access_days"),
                "amount_formatted": preview.get("amount_formatted"),
                "currency": preview.get("currency"),
                "charged_now": preview.get("charged_now", False),
                "remaining": preview.get("remaining") or [],
                "remaining_amount": preview.get("remaining_amount"),
                # The whole cancellation as the invoice will state it: every module
                # leaving together, under the name of the plan covering them, with the
                # total. What the dialog quotes when more than one module is going.
                "leaving_label": preview.get("leaving_label"),
                "leaving_total_formatted": preview.get("leaving_total_formatted"),
                "leaving_count": preview.get("leaving_count") or 0,
                "error": preview.get("error"),
            }
        ),
        200,
    )


@entity_bp.route("/entity/settings/module/<string:org_id>/retry-payment", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_retry_payment(org_id):
    """Collect a past-due payer's outstanding invoice right now.

    No body. Returns ``{"ok": bool, "status": ..., "message": ...}``.

    Exists because saving a card does not itself settle anything: automatic retries run
    on a 1/4/7/10/13-day schedule, so without this a customer fixes their card and then
    sits locked out for up to three days with nothing to press.

    Charges against the SAME budget and the same deadline as the scheduled run — see
    ``dunning.retry_now``. Scoped to the entity's payer, so an admin of one company can
    only ever settle the account that pays for it.
    """
    from blueprints.subscription.services import store as sub_store
    from blueprints.subscription.services.dunning import retry_now

    Entity.query.get_or_404(org_id)
    payer_id = sub_store.payer_for_entity(org_id)
    if not payer_id:
        return jsonify({"error": "This entity has no billing account."}), 409

    try:
        # The entity goes with it: a payer may hold several cards, and the debt to settle
        # is the one on the card THIS company is billed to — not their oldest.
        result = retry_now(payer_id, org_id)
    except Exception:
        logger.exception("retry-payment: collection failed for entity %s", org_id)
        return jsonify({"error": "We couldn't reach the card processor. Try again shortly."}), 502

    status = result["status"]
    messages = {
        "paid": "Payment received — your subscription is active again.",
        "no_card": "There's no card on file to charge. Add a payment method, then try again.",
        "gave_up": "This subscription is past its payment deadline and has been closed.",
        "nothing_owed": "Nothing is outstanding — your subscription is up to date.",
        # Deliberately not "nothing is outstanding": something is, and the customer can
        # see it sitting Unpaid on the Invoices tab. It is simply not this period's, so
        # paying it would take money and restore nothing — which is a conversation, not
        # a button press. See ``dunning.retry_now``.
        "older_debt_only": (
            "There's nothing due for the current period. An earlier unpaid invoice is "
            "still outstanding — contact us and we'll sort it out with you."
        ),
    }
    if status == "failed":
        # The processor's own words when there are any: "insufficient funds" and "card
        # expired" need different things from the customer, and collapsing both into
        # "declined" tells them to do the same thing twice.
        reason = (result.get("reason") or "").strip()
        message = (
            f"That card was declined: {reason}" if reason
            else "That card was declined. Try a different payment method."
        )
    else:
        message = messages.get(status, "Payment could not be completed.")

    return (
        jsonify(
            {
                "ok": status in ("paid", "nothing_owed"),
                "status": status,
                "message": message,
            }
        ),
        200,
    )


@entity_bp.route("/entity/settings/module/<string:org_id>/cancel", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_cancel(org_id):
    """Cancel ONE module.

    Body: ``{"code": "PETTY_CASH", "reason": "too expensive"}``.

    ``reason`` is the free text from the cancellation dialog and is entirely optional —
    it is recorded, never required, and never changes the outcome.

    Cancellation is per MODULE, not per subscription: the payer has one subscription and
    the entity one line on it, so a subscription id no longer identifies a module.

    * An **active paid** module cancels under the prorated rule — access until
      max(period end, now + 30 days), the extra days billed at the module's marginal
      price on the payer's next invoice. Returns ``{"ok": true, "access_until": "..."}``.
    * An **app-level trial** simply stops (no Stripe object, no charge).
    """
    from blueprints.subscription.services.checkout import CheckoutError, cancel_module

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400

    try:
        result = cancel_module(org, current_user, code, reason=payload.get("reason"))
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status

    access_end = result.get("access_end")
    access_until = access_end.strftime("%B %d, %Y") if access_end else None
    return jsonify({"ok": True, "access_until": access_until}), 200


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/payment-method", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_payment_method(org_id):
    """Add or update the payer's card. Returns ``{"url": …}`` for the client to open.

    TWO flows, because Stripe's portal cannot serve the first card:

    * an existing customer goes to the billing PORTAL, deep-linked to the
      payment-method form (``open_payment_method_update``);
    * a payer with no Stripe customer yet goes to setup-mode CHECKOUT
      (``start_payment_method_setup``), which passes ``customer_creation="always"``
      so Stripe mints the customer when the card is actually saved.

    Without the second branch this route answered "This entity has no billing account
    yet" to exactly the people trying to open one — the portal needs a customer, and a
    customer is only created by saving a card, which is what the button is for. The
    same dead end left their trials unable to convert, since conversion resolves a
    customer or expires the trial.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        open_payment_method_update,
        start_payment_method_setup,
    )

    org = Entity.query.get_or_404(org_id)
    return_url = url_for("entity.entity_settings_module", org_id=org_id, _external=True)
    try:
        session = open_payment_method_update(org, return_url)
    except CheckoutError:
        # No customer to open a portal against — capture the first card instead.
        # Completion runs through the SAME return route as a subscribe checkout; that
        # handler saves the card and creates nothing when the session carries no
        # modules_to_subscribe, which is exactly what a card-only session looks like.
        complete_url = url_for(
            "entity.entity_settings_module_checkout_complete",
            org_id=org_id,
            _external=True,
        ) + "?purpose=payment_method&session_id={CHECKOUT_SESSION_ID}"
        try:
            session = start_payment_method_setup(
                org, current_user, success_url=complete_url, cancel_url=return_url
            )
        except CheckoutError as exc:
            return jsonify({"error": exc.message}), exc.status
    return jsonify({"url": session.get("url")}), 200


@entity_bp.route("/entity/settings/module/<string:org_id>/renew", methods=["POST"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_renew(org_id):
    """Reactivate a module scheduled to cancel — in-app, no portal.

    Body: ``{"code": "PETTY_CASH"}``. Puts the module back on the entity's line and
    reverses the extension charge (deleted if it never billed, credited if it did),
    then the client refreshes. Returns ``{"ok": True}``.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        reactivate_module,
    )

    org = Entity.query.get_or_404(org_id)
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400
    try:
        reactivate_module(org, current_user, code)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    return jsonify({"ok": True}), 200


@entity_bp.route(
    "/entity/settings/module/<string:org_id>/manage-billing", methods=["POST"]
)
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_MANAGE,
    entity_arg="org_id",
    message="You do not have permission to manage subscriptions for this entity.",
)
@require_subscription_payer(entity_arg="org_id")
def entity_settings_module_manage_billing(org_id):
    """Open the Stripe portal for invoice history + payment-method management,
    WITHOUT Stripe's own cancellation (cancellation uses the in-app prorated flow).

    Returns ``{"url": <portal url>}`` for the client to redirect to.
    """
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        open_billing_management_portal,
    )

    org = Entity.query.get_or_404(org_id)
    return_url = url_for("entity.entity_settings_module", org_id=org_id, _external=True)
    try:
        session = open_billing_management_portal(org, return_url)
    except CheckoutError as exc:
        return jsonify({"error": exc.message}), exc.status
    return jsonify({"url": session.get("url")}), 200


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
