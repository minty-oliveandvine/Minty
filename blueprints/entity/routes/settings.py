"""Entity settings and contact routes."""

import html
from typing import Protocol

import requests
from flask import (current_app, flash, get_flashed_messages, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from loguru import logger
from sqlalchemy.exc import IntegrityError

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import (billing_settings_app_url,
                                              minty_web_module_page_url)
from blueprints.entity.services.settings import (
    COA_INCLUDED_TYPES, saveable_account_codes,
    sync_chart_of_accounts_if_changed, sync_contacts_if_changed_background,
    sync_entity_account_xero_active, sync_xero_accounts_to_db_background,
    sync_xero_coa_pettycash)
from blueprints.entity.services.xero_account_mapping_post import (
    apply_country_currency_selection, process_xero_account_mapping_post)
from blueprints.entity.services.country_currency import country_currency_choices
from blueprints.xero.services.settings import sync_entity_xero_status
from models.db import (AccountInfo, Entity,
                       EntityAccountXero, EntityPettycashSettings, db)
from services.app_runtime.legacy.xero_service import (
    account_info_to_xero_format)
from services.auth.token_service import (auto_refresh_token,
                                         ensure_valid_token,
                                         get_xero_token_user_for_entity,
                                         resolve_xero_token)
from services.authz import (permission_denied, require_entity_access,
                            require_module, require_permission)
from services.permission_policy import Permission, has_permission


class _PyCountryCountry(Protocol):
    alpha_2: str
    name: str


def _redirect_xero_mapping(entity_id: str, *, return_view: str):
    """Redirect after Xero mapping POST; return_view selects integration vs petty cash page."""
    if return_view == "entity_settings_entity":
        return redirect(url_for("entity_settings_entity", org_id=entity_id))
    return redirect(url_for("entity_settings", entity_id=entity_id))


def _xero_disconnected(org) -> bool:
    """Whether the entity was connected to a Xero org but is no longer live.

    Only entities that are SUPPOSED to be connected (``org.xero_org_id`` is set)
    count, so entities that never connected don't nag the user.

    Runs the authoritative LIVE check first: ``sync_entity_xero_status`` hits
    Xero's /connections endpoint and reconciles ``org.status`` to reality. This
    matters because a connection revoked on the Xero website can leave the
    connector token still valid — so a token-only check (``resolve_xero_token``)
    would wrongly report "connected". So: disconnected when EITHER no token
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

    return not (token_resolved and getattr(org, "status", None) != "disconnected")


def _xero_live(org) -> bool:
    """Whether the entity has a live Xero connection: an org that was never connected, or one
    disconnected inside Minty (which nulls ``xero_org_id``), is not live either - unlike
    ``_xero_disconnected``, which only nags entities that are supposed to be connected."""
    return bool(org is not None and getattr(org, "xero_org_id", None)) and not _xero_disconnected(org)


def _flash_if_xero_disconnected(org) -> bool:
    """Flash a "Xero disconnected — please reconnect" error when
    ``_xero_disconnected(org)``. Returns True if the entity is disconnected.
    (Petty Cash Settings says it inside its mapping card instead.)"""
    if not _xero_disconnected(org):
        return False
    flash(
        "This entity has been disconnected from Xero. Please reconnect it to "
        "keep your data in sync.",
        "danger",
    )
    return True


def _to_hub_tab(entity_id, tab: str):
    """Users and Entity & Integration are minty-web's tabs since phase 2 (2026-10-05):
    ``/entity/<shortid>/<name>/settings/{users,integration}``, reached with a token scoped to
    the company. These Flask addresses stay as the way there - the sidebar, old links, the
    payments app's pills and every ``url_for`` here (the Xero callback lands on the
    integration tab) - and whatever was flashed on the way travels signed in ``?flash=``, which
    the tab's read hands back as ``notices``."""
    from blueprints.entity.routes.modules import minty_web_company_path, minty_web_landing_url
    from blueprints.entity.services.entity_list import sign_notices

    org = Entity.query.get_or_404(entity_id)
    notices = sign_notices(get_flashed_messages(with_categories=True))
    path = minty_web_company_path(entity_id, f"/settings/{tab}") + (f"?flash={notices}" if notices else "")
    return redirect(minty_web_landing_url(path, org, current_user.id))


@entity_bp.route("/entity/<entity:entity_id>/settings/integration", methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero settings for this entity.",
)
def entity_settings(entity_id=None):
    """The Entity & Integration tab - minty-web's (``_to_hub_tab``)."""
    return _to_hub_tab(entity_id, "integration")


@entity_bp.route("/entity/<entity:org_id>/settings/users", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.USER_VIEW_ALL,
    entity_arg="org_id",
    message="You do not have permission to view all users for this entity.",
)
def entity_settings_users(org_id):
    """The Users tab - minty-web's (``_to_hub_tab``)."""
    return _to_hub_tab(org_id, "users")


@entity_bp.route("/entity/<entity:org_id>/settings/petty-cash",
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
        # Live check (hits Xero /connections). Without a live connection the page hides the
        # Xero-fed cards (the mapping and the account codes), so a save must not touch them:
        # it would refuse over cached codes nobody can see, or switch every code off.
        xero_live = _xero_live(org)

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
            # At least one account code stays ticked: a save with none switches every code off
            # (entity_account_xero.is_active below), and a petty cash expense can only use the
            # codes ticked here. Refused
            # BEFORE anything is written - the mapping save commits on its own. A company with
            # no codes at all saves as before; the page greys Save in the same case.
            saveable = saveable_account_codes(org_id) if xero_live else set()
            if saveable:
                posted = {
                    str(c).strip()
                    for c in request.form.getlist("account_codes[]")
                    if c and str(c).strip()
                }
                if not posted & saveable:
                    flash("Pick at least one account code.", "danger")
                    return _redirect_xero_mapping(org_id, return_view="entity_settings_entity"
                    )
            # The first mapping save sends the company to its dashboard (as it always has),
            # but only AFTER the ticks and country/currency below are saved.
            first_save = (
                EntityPettycashSettings.query.filter_by(entity_id=org_id).first() is None
            )
            try:
                if xero_live and request.form.get("main_bank") and has_permission(
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

                db.session.commit()
                # The ticks live on entity_account_xero.is_active only; account_info.status is
                # Xero's own "still active" and is never touched by a tick (2026-10-01).
                if xero_live:
                    selected_account_codes = request.form.getlist("account_codes[]")
                    logger.info(
                        f"Saving selected account codes for entity {org_id}: {selected_account_codes}"
                    )
                    try:
                        sync_entity_account_xero_active(
                            org_id, org.xero_org_id, selected_account_codes
                        )
                    except Exception:
                        db.session.rollback()
                        logger.exception(
                            "entity_settings_entity POST: the account code ticks were not saved "
                            "entity=%s", org_id,
                        )
                        flash(
                            "I couldn't save your account code ticks. Mind trying again?",
                            "danger",
                        )
                        return _redirect_xero_mapping(org_id, return_view="entity_settings_entity"
                        )

                flash("Entity settings saved!", "success")
                if first_save and EntityPettycashSettings.query.filter_by(
                    entity_id=org_id
                ).first() is not None:
                    return redirect(
                        url_for("entity.report_dashboard", id=org_id, success="true")
                    )
                return _redirect_xero_mapping(org_id, return_view="entity_settings_entity"
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
                return _redirect_xero_mapping(org_id, return_view="entity_settings_entity"
                )
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating entity settings: {str(e)}")
                flash(
                    "I couldn't save your entity settings. Could you check your "
                    "entries and try again?",
                    "danger",
                )
                return _redirect_xero_mapping(org_id, return_view="entity_settings_entity"
                )

        # Handle GET request (display form)
        # Compare Xero live vs DB and sync both modules if changes detected
        if xero_live:
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

        # Country / currency registries: the dropdowns list the active rows
        # and preselect via the entity's country_code / currency_id FKs.
        (
            country_code,
            currencies,
            selected_country,
            selected_currency,
        ) = country_currency_choices(org)

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
        # run inline. Wrapped so a failure can't break the page. Not live: the card is hidden.
        if xero_live:
            try:
                sync_xero_coa_pettycash(org_id, org.xero_org_id)
            except Exception as _coa_backfill_err:
                logger.warning(
                    "entity_settings_entity: petty cash CoA backfill skipped "
                    "entity={}: {}",
                    org_id,
                    _coa_backfill_err,
                )

        # The Petty Cash Account Code list, in code order: {code, name, selected} per row. The
        # page script draws it as text and posts the ticks (static/js/petty_cash_settings.js).
        petty_cash_codes = []
        if xero_live:
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
                petty_cash_codes.append(
                    {
                        "code": entry.get("Code") or "",
                        "name": html.unescape(entry.get("Name", "") or ""),
                        "selected": bool(is_active),
                    }
                )
            logger.info(
                "entity_settings_entity: loaded {} petty cash CoA accounts "
                "from entity_account_xero for entity {}",
                len(petty_cash_codes), org_id,
            )

        _can_edit_coa = has_permission(current_user, Permission.COA_UPDATE, org_id)
        _mapping = {}
        if xero_live:
            token_valid = False
            try:
                token_valid = ensure_valid_token(current_user)
            except Exception as tok_err:
                logger.warning(
                    "entity_settings_entity: token check skipped entity=%s: %s",
                    org_id,
                    tok_err,
                )
            from blueprints.entity.services.xero_mapping_form_context import \
                build_xero_mapping_form_context

            _mapping = build_xero_mapping_form_context(org_id, org, token_valid)

        # The Electronic/Delivery cards are the only controls on this page whose
        # APIs enforce SALES_METHOD_* rather than COA_*. Same minimum role today,
        # but gate the UI on the permission its own endpoints check.
        _can_edit_sales_methods = has_permission(
            current_user, Permission.SALES_METHOD_UPDATE, org_id
        )
        return render_template(
            "entity/settings_entity.html",
            org=org,
            country_code=country_code,
            currencies=currencies,
            selected_country=selected_country,
            selected_currency=selected_currency,
            petty_cash_codes=petty_cash_codes,
            is_view_only=not _can_edit_coa,
            can_edit_coa_mappings=_can_edit_coa,
            can_edit_sales_methods=_can_edit_sales_methods,
            xero_live=xero_live,
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


@entity_bp.route("/entity/<entity:org_id>/settings/modules", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
@require_permission(
    Permission.MODULE_VIEW,
    entity_arg="org_id",
    message="You do not have permission to view module settings for this entity.",
)
def entity_settings_module(org_id):
    """The Module tab: a hand-over to minty-web's Module page, with a token for this company.

    The page itself is minty-web's (Part 2 step 4a, built to its design). Flask's Jinja version
    and the session routes behind it were deleted on 2026-10-01; this address stays so the
    Petty Cash tab, the payments app's links (``SettingsPills``, ``ModuleGate``), the in-app
    notice and old bookmarks still land.
    """
    org = Entity.query.get_or_404(org_id)
    return redirect(minty_web_module_page_url(org, current_user.id))


@entity_bp.route("/entity/<entity:org_id>/settings/payment-request", methods=["GET"])
@login_required
@require_entity_access(entity_arg="org_id")
def entity_settings_payments(org_id):
    """The Payment Settings tab as a plain URL.

    The tab's target is the payments app's settings page behind a module token that only
    Flask mints (``billing_settings_app_url``). Flask's own settings pages compute that URL
    into the template; a page that is not Flask's - the module settings page in minty-web
    (Part 2 step 4) - links here instead and is sent on.
    """
    org = Entity.query.get_or_404(org_id)
    return redirect(billing_settings_app_url(org_id, org, current_user.id))


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
