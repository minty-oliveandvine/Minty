"""Entity settings and contact routes."""

from urllib.parse import urlencode

from flask import (get_flashed_messages, redirect,
                   request, url_for)
from flask_login import current_user, login_required

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import (billing_settings_app_url,
                                              minty_web_module_page_url)
from models.db import (Entity)
from services.authz import (require_entity_access,
                            require_module, require_permission)
from services.permission_policy import Permission


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


@entity_bp.route("/entity/<entity:org_id>/settings/petty-cash", methods=["GET"])
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
    """Petty Cash Settings - minty-petty-cash-web's page (Flask's was deleted 2026-10-20), through
    the hand-off that mints that app's token. Old links and the older front ends still land here."""
    from blueprints.entity.routes.modules import minty_web_company_path

    return redirect(url_for(
        "entity.handoff_petty_cash_web",
        entity_id=org_id,
        next=minty_web_company_path(org_id, "/settings/petty-cash"),
    ))


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
