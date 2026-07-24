"""Module selector + JWT handover to Module 2 (Billing).

Flow when a user clicks an entity in the entity list:
  1. Browser hits ``/entity/<entity_id>/modules`` (``module_selector`` below).
  2. If billing isn't enabled for the entity, redirect to the petty cash
     dashboard (existing behaviour).
  3. If billing IS enabled, issue a short-lived HS256 JWT signed with
     Flask ``SECRET_KEY`` and redirect to the Module 2 Next.js frontend's
     ``/module-selection`` page with the JWT in the query string.

Module 2 (the payment-request app) consumes the JWT, stores it in a cookie,
and uses ``Authorization: Bearer <jwt>`` + ``X-Entity-Id`` for all calls to
the billing backend. The backend verifies with the same shared ``SECRET_KEY``.

Return path: Module 2 calls ``/entity/<entity_id>/billing-relogin?next=…``
when the cookie expires; ``module_reenter`` re-establishes the Flask session
from the JWT.
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required, login_user

from blueprints.entity import entity_bp
from models.db import Entity, EntityFunction, EntityFunctionMap, User, UserEntity
from services.permission_policy import Role, is_superuser


@entity_bp.route("/entity/<string:entity_id>/modules")
@login_required
def module_selector(entity_id):
    org = Entity.query.filter(Entity.id == entity_id).first()
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Resume-on-return: an entity left mid-onboarding (Save & Exit, which does
    # not call /api/onboarding/finalize) keeps status == "onboarding". Clicking
    # it from the entity list must drop the user back into the onboarding flow,
    # not the dashboard of a half-configured entity. The flag is cleared only by
    # /api/onboarding/finalize.
    #
    # We hand the wizard both entity_id and a freshly minted onboarding token
    # (via onboarding_launch_url) so resume works even with no browser
    # localStorage: the wizard binds the existing entity, fetches its saved
    # state from GET /api/onboarding/state, and the token authorizes those
    # calls. The entities row — not the browser — is the source of truth.
    if org.status == "onboarding":
        from blueprints.entity.routes.create import onboarding_launch_url

        current_app.logger.info(
            f"Entity {entity_id} is mid-onboarding; resuming onboarding flow"
        )
        return redirect(
            onboarding_launch_url(
                current_user, entity_name=org.name or "", entity_id=entity_id
            )
        )

    _user_is_superuser = is_superuser(current_user)

    user_entity = UserEntity.query.filter(
        UserEntity.user_id == current_user.id,
        UserEntity.entity_id == entity_id,
    ).first()
    if not user_entity and not _user_is_superuser:
        flash("Hmm, it looks like you don't have permission to look there.", "danger")
        return redirect(url_for("entity.entity_list"))

    # Superusers viewing an entity they aren't a member of get a view-only
    # super_admin role in the JWT so Module 2 can identify them.
    effective_role = user_entity.role if user_entity else Role.SUPER_ADMIN.value

    current_app.logger.info(f"Checking enabled modules for entity {entity_id}")
    billing_enabled = _is_module_enabled(entity_id, "BILL")
    petty_cash_enabled = _is_module_enabled(entity_id, "PETTY_CASH")
    current_app.logger.info(
        f"Modules for {entity_id}: BILL={billing_enabled} PETTY_CASH={petty_cash_enabled}"
    )

    if not billing_enabled:
        current_app.logger.info(
            f"Only petty cash enabled - redirecting directly to dashboard for entity {entity_id}"
        )
        return redirect(url_for("entity.report_dashboard", id=entity_id))

    # Both modules enabled — hand off to Module 2's /module-selection page.
    frontend_app_url = os.environ.get("FRONTEND_APP_URL", "http://localhost:3000").rstrip("/")
    token = _generate_module_token(
        current_user.id,
        entity_id,
        org.xero_org_id,
        effective_role,
        billing_enabled=billing_enabled,
        petty_cash_enabled=petty_cash_enabled,
    )
    entity_name = quote(org.name or "", safe="")
    frontend_url = (
        f"{frontend_app_url}/module-selection"
        f"?entity_id={entity_id}&entity_name={entity_name}&token={token}"
    )

    current_app.logger.info(f"Redirecting to Module 2 module selection: {frontend_url}")
    return redirect(frontend_url)


@entity_bp.route("/entity/<string:entity_id>/enter")
def module_reenter(entity_id):
    """Re-entry from Module 2. Validates the JWT, re-establishes the Flask
    session, then redirects to ``next`` (if safe) or the petty cash dashboard."""
    default_dest = url_for("entity.report_dashboard", id=entity_id)
    next_url = request.args.get("next", "").strip()
    destination = next_url if next_url.startswith("/") else default_dest

    if current_user.is_authenticated:
        return redirect(destination)

    token = request.args.get("token", "")
    if not token:
        flash("Your session ran out. Mind logging back in?", "warning")
        return redirect(url_for("auth.home"))

    try:
        secret = current_app.config.get("SECRET_KEY")
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        user = User.query.get(decoded["user_id"])
        if not user:
            flash("Hmm, that name doesn't seem to be in my list.", "danger")
            return redirect(url_for("auth.home"))

        login_user(user)
        return redirect(destination)

    except jwt.ExpiredSignatureError:
        flash("Your session ran out. Mind logging back in?", "warning")
        return redirect(url_for("auth.home"))
    except (jwt.DecodeError, jwt.InvalidTokenError):
        flash("Something's off with your session. Mind logging back in?", "warning")
        return redirect(url_for("auth.home"))


# Alias the re-entry endpoint at the path the payment-request frontend
# actually calls (see payment-request/lib/auth.ts redirectToLogin).
@entity_bp.route("/entity/<string:entity_id>/billing-relogin")
def billing_relogin(entity_id):
    return module_reenter(entity_id)


@entity_bp.route("/entity/<string:entity_id>/bills")
@login_required
def go_to_bills(entity_id):
    """Direct handoff to Module 2 Bills (skips the module picker)."""
    org = Entity.query.filter(Entity.id == entity_id).first()
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    if not is_superuser(current_user):
        ue = UserEntity.query.filter(
            UserEntity.user_id == current_user.id,
            UserEntity.entity_id == entity_id,
        ).first()
        if not ue:
            flash("Hmm, it looks like you don't have permission to look there.", "danger")
            return redirect(url_for("entity.entity_list"))

    if not _is_module_enabled(entity_id, "BILL"):
        flash("The Bill module isn't switched on for this entity yet - an admin can turn it on in the entity's module settings.", "warning")
        return redirect(url_for("entity.report_dashboard", id=entity_id))

    return redirect(billing_app_home_url(entity_id, org, current_user.id))


def _generate_module_token(
    user_id,
    entity_id,
    xero_org_id,
    role: str = "",
    billing_enabled: bool = True,
    petty_cash_enabled: bool = True,
):
    secret = current_app.config.get("SECRET_KEY")
    user_obj = User.query.get(str(user_id)) if user_id else None
    system_role = (getattr(user_obj, "system_role", None) or "") if user_obj else ""
    payload = {
        "user_id": str(user_id),
        "entity_id": str(entity_id) if entity_id else "",
        "xero_org_id": str(xero_org_id or ""),
        "role": role or "",
        "system_role": system_role,
        "module": "billing",
        "billing_enabled": billing_enabled,
        # Mirror of billing_enabled for the petty-cash module — drives the
        # Module 2 nav's Petty Cash section visibility. Defaults True so old
        # call sites (e.g. unscoped profile handoff) don't silently hide nav.
        "petty_cash_enabled": petty_cash_enabled,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _is_module_enabled(entity_id: str, function_code: str) -> bool:
    """Check pettycashv2.entity_function / entity_function_map. Defaults to
    enabled when the function row doesn't exist (backward-compatible for
    entities that predate the gating table)."""
    entity_function = EntityFunction.query.filter(
        EntityFunction.function_code == function_code
    ).first()

    if not entity_function:
        current_app.logger.info(
            f"Function {function_code} not found - defaulting to ENABLED"
        )
        return True

    function_map = EntityFunctionMap.query.filter(
        EntityFunctionMap.entity_id == entity_id,
        EntityFunctionMap.entity_function_id == entity_function.id,
    ).first()

    if function_map:
        return function_map.is_enabled

    return entity_function.is_active


def _resolve_user_entity_role(user_id, entity_id) -> str:
    """Effective role string for JWT generation. Falls back to super_admin
    for system superusers with no UserEntity row."""
    from flask_login import current_user as _cu

    if entity_id:
        ue = UserEntity.query.filter(
            UserEntity.user_id == str(user_id),
            UserEntity.entity_id == str(entity_id),
        ).first()
        if ue:
            return ue.role or ""
    if is_superuser(_cu):
        return Role.SUPER_ADMIN.value
    return ""


def _frontend_origin() -> str:
    return os.environ.get("FRONTEND_APP_URL", "http://localhost:3000").rstrip("/")


def billing_app_home_url(entity_id: str, org: Entity, user_id, *, from_bills: bool = False) -> str:
    """Handoff URL for Module 2 main app with entity pre-selected."""
    home_seg = (
        os.environ.get("PAYMENT_REQUEST_APP_HOME_PATH")
        or os.environ.get("BILLING_APP_HOME_PATH")
        or ""
    ).strip("/")
    next_arg = f"/{home_seg}" if home_seg else "/"
    role = _resolve_user_entity_role(user_id, entity_id)
    billing_enabled = _is_module_enabled(entity_id, "BILL")
    petty_cash_enabled = _is_module_enabled(entity_id, "PETTY_CASH")
    token = _generate_module_token(
        user_id,
        entity_id,
        org.xero_org_id,
        role,
        billing_enabled=billing_enabled,
        petty_cash_enabled=petty_cash_enabled,
    )
    entity_name = quote(org.name or "", safe="")
    url = (
        f"{_frontend_origin()}/landing"
        f"?next={next_arg}"
        f"&entity_id={entity_id}&entity_name={entity_name}&token={token}"
    )
    if from_bills:
        url += "&from=bills"
    return url


def billing_settings_app_url(entity_id: str, org: Entity, user_id, *, from_bills: bool = False) -> str:
    """Handoff URL for Module 2 settings page."""
    settings_path = (
        os.environ.get("PAYMENT_REQUEST_SETTINGS_PATH")
        or os.environ.get("BILLING_SETTINGS_PATH")
        or "settings"
    ).strip("/") or "settings"
    role = _resolve_user_entity_role(user_id, entity_id)
    billing_enabled = _is_module_enabled(entity_id, "BILL")
    petty_cash_enabled = _is_module_enabled(entity_id, "PETTY_CASH")
    token = _generate_module_token(
        user_id,
        entity_id,
        org.xero_org_id,
        role,
        billing_enabled=billing_enabled,
        petty_cash_enabled=petty_cash_enabled,
    )
    entity_name = quote(org.name or "", safe="")
    url = (
        f"{_frontend_origin()}/landing"
        f"?next=/{settings_path}"
        f"&entity_id={entity_id}&entity_name={entity_name}&token={token}"
    )
    if from_bills:
        url += "&from=bills"
    return url


def billing_app_profile_url(entity_id: str, org: Entity, user_id, *, from_bills: bool = False) -> str:
    """Handoff URL for Module 2 profile page."""
    profile_seg = (
        os.environ.get("PAYMENT_REQUEST_PROFILE_PATH")
        or os.environ.get("BILLING_PROFILE_PATH")
        or "profile"
    ).strip("/")
    next_arg = f"/{profile_seg}" if profile_seg else "/profile"
    role = _resolve_user_entity_role(user_id, entity_id)
    billing_enabled = _is_module_enabled(entity_id, "BILL")
    petty_cash_enabled = _is_module_enabled(entity_id, "PETTY_CASH")
    token = _generate_module_token(
        user_id,
        entity_id,
        org.xero_org_id,
        role,
        billing_enabled=billing_enabled,
        petty_cash_enabled=petty_cash_enabled,
    )
    entity_name = quote(org.name or "", safe="")
    url = (
        f"{_frontend_origin()}/landing"
        f"?next={next_arg}"
        f"&entity_id={entity_id}&entity_name={entity_name}&token={token}"
    )
    if from_bills:
        url += "&from=bills"
    return url


def billing_app_profile_unscoped_url(user_id, *, from_bills: bool = False) -> str:
    """Handoff URL for Module 2 profile with no entity context (Select Company)."""
    profile_seg = (
        os.environ.get("PAYMENT_REQUEST_PROFILE_PATH")
        or os.environ.get("BILLING_PROFILE_PATH")
        or "profile"
    ).strip("/")
    next_arg = f"/{profile_seg}" if profile_seg else "/profile"
    role = _resolve_user_entity_role(user_id, "")
    token = _generate_module_token(user_id, "", None, role)
    url = (
        f"{_frontend_origin()}/landing"
        f"?next={next_arg}"
        f"&token={token}"
    )
    if from_bills:
        url += "&from=bills"
    return url
