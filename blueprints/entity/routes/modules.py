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

Return path: when its token expires, Module 2 sends the browser to ``/`` — this
app's landing page, which forwards to ``/entity`` for a live session and to the
login form otherwise. Picking a company there mints a fresh token through the
handoff above. Module 2 does not ask to be returned to the page it was on: that
path belongs to Module 2's origin, and replaying it here is what used to 404.
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from flask import (current_app, flash, has_request_context, redirect, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user

from blueprints.entity import entity_bp
from blueprints.entity.services.modules import LOGIN_SID_SESSION_KEY
from models.db import (Entity, EntityFunction, EntityFunctionMap, User,
                       UserEntity, db, tz)
from services.permission_policy import Role, is_superuser
from services.user_presence import resume_presence


def record_entity_access(entity_id: str, user_id: str) -> None:
    """Stamp who last opened this entity and when (team-wide last login).

    Drives the "last logged in" clock on the Select Company card. Best-effort by
    design: a failure here must never block entry into the entity, so it rolls
    back and logs rather than raising. Call only after the access check passes —
    a rejected visit is not an access.
    """
    try:
        updated = Entity.query.filter(Entity.id == entity_id).update(
            {
                # datetime.now(tz), not datetime.now(): the column is a naive
                # TIMESTAMP and every other timestamp in this app is stored as
                # Hong Kong wall time. A bare now() on a UTC host would render
                # the card 8 hours behind.
                "last_accessed_at": datetime.now(tz),
                "last_accessed_by_user_id": user_id,
            },
            synchronize_session=False,
        )
        if updated:
            db.session.commit()
    except Exception as exc:  # noqa: BLE001 - never block entity entry
        db.session.rollback()
        current_app.logger.warning(
            f"Failed to record entity access for {entity_id}: {exc}"
        )


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

    # Access granted — record this open as the entity's latest "last login".
    record_entity_access(entity_id, current_user.id)

    # ...and put the user back on this entity's signed-in list. Every route into
    # an entity comes through here (the entity list links each card to this page),
    # so this is the one place that reliably means "I am going in". Ordinary page
    # loads must NOT do this — see resume_presence for why.
    resume_presence(current_user)

    # Superusers viewing an entity they aren't a member of get a view-only
    # super_admin role in the JWT so Module 2 can identify them.
    effective_role = user_entity.role if user_entity else Role.SUPER_ADMIN.value

    # No access resync here any more. It re-read live Stripe on every page view to
    # catch a webhook that never arrived; the gate is now written by the app itself
    # whenever access changes, and the daily sweep closes it when a grace window
    # lapses (modules.sweep_expired_module_access).
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


def _safe_next(raw: str, default: str) -> str:
    """A single-slash absolute path, or ``default``.

    ``//evil.example`` is a protocol-relative URL, not a path. Letting one through
    would make these routes an open redirect that arrives carrying a token.
    """
    nxt = (raw or "").strip()
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default


@entity_bp.route("/entity/<string:entity_id>/enter")
def module_reenter(entity_id):
    """Re-entry from Module 2. Validates the JWT, re-establishes the Flask
    session, then redirects to ``next`` (if safe) or the petty cash dashboard.

    ``next`` here is a path on THIS origin — the payer portal's ``buildEnterUrl``
    sends users to entity settings. Module 2 paths go through ``billing_relogin``
    instead, which hands them back to Module 2's own origin.
    """
    destination = _safe_next(
        request.args.get("next", ""), url_for("entity.report_dashboard", id=entity_id)
    )

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


@entity_bp.route("/entity/<string:entity_id>/billing-relogin")
def billing_relogin(entity_id: str):
    """Legacy: Module 2 telling us its billing JWT ran out.

    Kept only for browsers running a Module 2 build from before the frontend
    stopped calling this. Current builds go straight to ``/`` — this route never
    did anything a plain redirect to the landing page couldn't, and being an
    extra hop it could 404 on its own, which is precisely what it did.

    It used to redirect to the ``next`` Module 2 sent: a path on Module 2's
    origin, replayed on this one. From the payer portal that was a 404 on
    ``/profile``, reached with the cookie already cleared, so every request on
    the stranded page then failed with "you're signed out". ``next`` is ignored
    now — nothing from the other origin decides where this goes.

    ``entity_id`` is unused; the destination is the same either way. Delete this
    once no deployed Module 2 build calls it.
    """
    if not current_user.is_authenticated:
        flash("Your session ran out. Mind logging back in?", "warning")
    else:
        flash("That session ran out - pick a company and I'll get you back in.", "warning")
    return redirect(url_for("auth.home"))


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
        flash("The Payment module isn't switched on for this entity yet - an admin can turn it on in the entity's module settings.", "warning")
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
        # Which sign-in this token belongs to. Module 2 cannot see the Flask session,
        # so this is how it honours "once per login" for the subscription notice: it
        # keys its own per-tab flag by this value, and a fresh login mints a new one.
        # Empty outside a request context (the CLI mints tokens too) — the frontend
        # falls back to a plain per-tab flag, which is what it did before.
        "sid": session.get(LOGIN_SID_SESSION_KEY, "") if has_request_context() else "",
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
    """Fast per-request access gate: reads ``entity_function_map``.

    ``is_enabled`` is not a fact — it is a PROJECTION of the module's
    ``entity_module_subscription`` row, which is the record of truth. Only the
    subscription lifecycle writes it (trial start, conversion, expiry, uncancel,
    renew, and the daily sweep that closes date boundaries no event fires on).
    This function just reads the projection, so a request costs one indexed
    lookup rather than a join across the billing tables.

    Every unknown answers NO. A missing catalog row, or an entity with no map row,
    used to fall through to ENABLED (via the catalog ``is_active``) — which granted
    a module to every entity that had never subscribed to it, and left the "Start
    free trial" button showing on a module the user was already inside.
    """
    entity_function = EntityFunction.query.filter(
        EntityFunction.function_code == function_code
    ).first()

    if not entity_function:
        current_app.logger.warning(
            f"Function {function_code} not found - denying access"
        )
        return False

    function_map = EntityFunctionMap.query.filter(
        EntityFunctionMap.entity_id == entity_id,
        EntityFunctionMap.entity_function_id == entity_function.id,
    ).first()

    if function_map:
        return function_map.is_enabled

    # No projection row means nothing has ever granted this module. The catalog's
    # ``is_active`` says whether a module is offered at all, never who may use it.
    return False


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


def _notice_cors(resp):
    """Let the Module 2 frontend call this cross-origin (bearer-token auth).

    Mirrors the ``/api/onboarding/*`` contract in ``routes.create._cors``. The app
    already installs flask-cors globally, but naming the origin explicitly keeps the
    allowance narrow and pins ``Vary: Origin`` so a cached response for one origin is
    never replayed to another.
    """
    resp.headers["Access-Control-Allow-Origin"] = _frontend_origin()
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return resp


@entity_bp.route(
    "/api/entity/<string:entity_id>/subscription-notice", methods=["GET", "OPTIONS"]
)
def subscription_notice_api(entity_id):
    """Subscription notice for the Module 2 (Payment) landing page.

    Same data the Petty Cash dashboard modal renders, over JSON. The billing frontend
    talks to its own backend for everything else; subscription state lives only here,
    so this is the one endpoint it calls on Minty's origin.

    Auth is the billing JWT — the same token Module 2 already holds, signed with this
    app's ``SECRET_KEY``. The token's ``entity_id`` claim must match the path, so a
    token minted for one company cannot read another's billing state, and membership
    is re-checked server-side rather than trusted from the claim.

    Stateless by design: it does NOT consume ``claim_subscription_notice``. The
    "show once per session" rule is the caller's, and the frontend keeps its own
    per-tab flag — a shared Flask session doesn't exist across the two origins.
    """
    from flask import jsonify, make_response

    if request.method == "OPTIONS":
        return _notice_cors(make_response("", 204))

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return _notice_cors(make_response(jsonify({"error": "unauthorized"}), 401))

    try:
        decoded = jwt.decode(
            header[len("Bearer "):].strip(),
            current_app.config.get("SECRET_KEY"),
            algorithms=["HS256"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.DecodeError):
        return _notice_cors(make_response(jsonify({"error": "unauthorized"}), 401))

    user_id = decoded.get("user_id")
    if not user_id:
        return _notice_cors(make_response(jsonify({"error": "no_user_claim"}), 403))

    # The claim scopes the token to one company. Enforced only when the token
    # carries one: the refresh path mints tokens through the Module 2 backend, and a
    # missing claim there would otherwise lock this endpoint out for every user whose
    # 30-minute token has rolled over. Authorisation does not rest on this — the
    # membership check below is what decides, and it reads the PATH entity.
    claimed = str(decoded.get("entity_id") or "")
    if claimed and claimed != str(entity_id):
        current_app.logger.info(
            f"Notice API: token scoped to {claimed}, asked for {entity_id}"
        )
        return _notice_cors(make_response(jsonify({"error": "entity_mismatch"}), 403))

    from services.permission_policy import has_entity_access

    user = User.query.get(str(user_id))
    if not user or not (
        is_superuser(user) or has_entity_access(user, entity_id)
    ):
        current_app.logger.info(
            f"Notice API: user {user_id} has no access to {entity_id}"
        )
        return _notice_cors(make_response(jsonify({"error": "not_a_member"}), 403))

    from blueprints.entity.services.modules import build_subscription_notices

    try:
        notice = build_subscription_notices(entity_id, user_id)
    except Exception as exc:  # a notice must never break the landing page
        current_app.logger.error(
            f"Subscription notice API failed for {entity_id}: {exc}"
        )
        return _notice_cors(make_response(jsonify({"items": []}), 200))

    # A Minty PATH, not a URL: subscription management lives on this side, and the
    # frontend's buildMintyEnterUrl() already knows how to hand its token back for a
    # session. Returning a bare origin here would skip that and land on the login form.
    notice["settings_path"] = url_for(
        "entity.entity_settings_module", org_id=entity_id
    )
    return _notice_cors(make_response(jsonify(notice), 200))


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
