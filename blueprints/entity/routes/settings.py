"""Entity settings and contact routes."""

from typing import Protocol
from urllib.parse import urlencode

from flask import (current_app, flash, get_flashed_messages, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from services.app_runtime.log import logger
from sqlalchemy.exc import IntegrityError

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import (billing_settings_app_url,
                                              minty_web_module_page_url)
from blueprints.entity.services.settings import (
    saveable_account_codes,
    sync_entity_account_xero_active)
from blueprints.entity.services.xero_account_mapping_post import (
    apply_country_currency_selection, process_xero_account_mapping_post)
from blueprints.entity.services.country_currency import country_currency_choices
from models.db import (Entity,
                       EntityPettycashSettings, db)
from services.auth.token_service import (ensure_valid_token)
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
    """Whether the entity was connected to a Xero org but is no longer live
    (``entity/services/xero_mapping.py::disconnected``, which checks Xero's /connections live)."""
    from blueprints.entity.services import xero_mapping

    return xero_mapping.disconnected(org, current_user)


def _xero_live(org) -> bool:
    """Whether the entity has a live Xero connection (``xero_mapping.is_live``)."""
    from blueprints.entity.services import xero_mapping

    return xero_mapping.is_live(org, current_user)


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
    the tab's read hands back as ``notices``.

    ``?xero_conflict=`` rides along the same way when a Xero connect was refused because
    another company already holds the organisation (``_refuse_conflict``): a notice says what
    happened, and this says enough for the tab to offer the move. It is forwarded rather than
    built here, because only the callback knows which company holds it."""
    from blueprints.entity.routes.modules import minty_web_company_path, minty_web_landing_url
    from blueprints.entity.services.entity_list import sign_notices

    org = Entity.query.get_or_404(entity_id)
    notices = sign_notices(get_flashed_messages(with_categories=True))
    carried = {}
    if notices:
        carried["flash"] = notices
    conflict = (request.args.get("xero_conflict") or "").strip()
    if conflict:
        carried["xero_conflict"] = conflict
    path = minty_web_company_path(entity_id, f"/settings/{tab}") + (
        f"?{urlencode(carried)}" if carried else ""
    )
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


#: The Petty Cash Settings cards that save on their own -> what a save says (None = all of them).
SETTINGS_SECTIONS = {
    None: "Entity settings saved!",
    "country": "Country and currency saved.",
    "mapping": "Xero account mapping saved.",
    "codes": "Account codes saved.",
}


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
            #
            # One Save per card (Part 15.20b; the user, 2026-10-14): the card names itself in
            # ``section`` and only that part is written - every card's fields ride along in the
            # post. No ``section`` (an older client) saves everything, as before. Sales methods
            # save through their own JSON API, never here.
            section = request.form.get("section") or None
            if section not in SETTINGS_SECTIONS:
                # returned, not abort(): the page's catch-all below would turn an HTTPException
                # into a "something got tangled" redirect
                logger.warning("entity_settings_entity POST: unknown section %r entity=%s", section, org_id)
                return "That part of the settings can't be saved here.", 400

            def saving(part):
                return section is None or section == part

            saveable = saveable_account_codes(org_id) if (xero_live and saving("codes")) else set()
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
                if saving("mapping") and xero_live and request.form.get("main_bank") and has_permission(
                    current_user, Permission.COA_UPDATE, org_id
                ):
                    _xr = process_xero_account_mapping_post(
                        org_id,
                        return_view="entity_settings_entity",
                        defer_success_redirect=True,
                        with_country=saving("country"),
                    )
                    if _xr is not None:
                        return _xr

                if saving("country"):
                    apply_country_currency_selection(org, request.form)

                db.session.commit()
                # The ticks live on entity_account_xero.is_active only; account_info.status is
                # Xero's own "still active" and is never touched by a tick (2026-10-01).
                if xero_live and saving("codes"):
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

                flash(SETTINGS_SECTIONS[section], "success")
                if saving("mapping") and first_save and EntityPettycashSettings.query.filter_by(
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

        # Handle GET request (display form): a live company's lists are refreshed from Xero first
        # (entity/services/xero_mapping.py, shared with the Petty Cash API).
        from blueprints.entity.services import xero_mapping

        if xero_live:
            xero_mapping.refresh_from_xero(org, current_user, current_app._get_current_object())

        # Country / currency registries: the dropdowns list the active rows
        # and preselect via the entity's country_code / currency_id FKs.
        (
            country_code,
            currencies,
            selected_country,
            selected_currency,
        ) = country_currency_choices(org)

        # The Petty Cash Account Code list, in code order: {code, name, selected} per row. The
        # page script draws it as text and posts the ticks (static/js/petty_cash_settings.js).
        petty_cash_codes = xero_mapping.account_codes(org_id) if xero_live else []

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

        from blueprints.entity.services.suppliers import SupplierRefused, create_supplier

        try:
            row = create_supplier(entity_id, name)
        except SupplierRefused as refused:
            return jsonify({"status": "error", "message": refused.message}), refused.status
        xero_contact_id, contact_name = row.xero_contact_id, row.name

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
