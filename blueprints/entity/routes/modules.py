"""Module selector + JWT handover to Module 2 (Billing).

Flow when a user clicks an entity in the entity list:
  1. Browser hits ``/entity/<entity_id>/modules`` (``module_selector`` below).
  2. If billing isn't enabled for the entity, redirect to the petty cash
     dashboard (existing behaviour).
  3. If only billing is enabled, issue a short-lived HS256 JWT signed with
     Flask ``SECRET_KEY`` and hand off to the Module 2 Next.js frontend with
     the JWT in the query string, straight into the app itself.
  4. Both enabled: minty-web's module choice (``/entities/<shortid>/<name>``, phase 2 -
     2026-10-05; it was Module 2's ``/module-selection`` page), with a token scoped to the
     company. The picker only appears when there is actually something to pick.

Module 2 (the payment-request app) consumes the JWT, stores it in a cookie,
and uses ``Authorization: Bearer <jwt>`` + ``X-Entity-Id`` for all calls to
the billing backend. The backend verifies with the same shared ``SECRET_KEY``.

Return path: when its token expires, Module 2 sends the browser to ``/`` — this
app's landing page, which forwards to ``/entity`` for a live session and to the
login form otherwise. Picking a company there mints a fresh token through the
handoff above. Module 2 does not ask to be returned to the page it was on: that
path belongs to Module 2's origin, and replaying it here is what used to 404.
"""
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from flask import (current_app, flash, has_request_context, jsonify, make_response,
                   redirect, request, session, url_for)
from flask_login import current_user, login_required, login_user

from blueprints.entity import entity_bp
from blueprints.shared import bearer_api
from blueprints.shared.safe_redirect import safe_next
from blueprints.entity.services.modules import LOGIN_SID_SESSION_KEY, MODULE_BILL
from models.db import (Entity, EntityFunction, EntityFunctionMap, User,
                       UserEntity, db)
from services.permission_policy import Role, is_superuser
from services.user_presence import resume_presence
from blueprints.shared.enums import ModuleCode

#: How long every module token this app mints lives (``_generate_module_token``).
MODULE_TOKEN_MINUTES = 30
#: The ``module`` claim every module token carries; ``/entity/<id>/enter`` accepts no other token.
MODULE_TOKEN_CLAIM = "billing"

#: Where the Module 2 handoffs land inside minty-payment-request-web, under the company's
#: address (``/entity/<shortid>/<name>``, 2026-10-05): its list, and its settings page
#: (``billing_app_home_url`` / ``billing_settings_app_url``).
PAYMENT_REQUEST_APP_HOME_PATH = "payment-request"
PAYMENT_REQUEST_SETTINGS_PATH = "settings/payment-request"


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
                # AN AWARE UTC INSTANT, because the column is ``TIMESTAMPTZ``
                # (01_schema_rebased.sql). A timestamptz stores the instant an aware value
                # names, whatever the session ``TimeZone`` says; a NAIVE value it reads IN
                # the session's zone. This used to write naive UTC - right for the old
                # ``timestamp without time zone`` column, wrong since the rebase: on a
                # session that is not UTC (a local Postgres set to UTC+8, for one) every
                # stamp landed 8 hours early and the card said so. Correct in production
                # only while its sessions happened to run in UTC.
                "last_accessed_at": datetime.now(timezone.utc),
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


@entity_bp.route("/entity/<entity:entity_id>/modules")
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
    resume_presence(current_user, entity_id)

    # No access resync here any more. It re-read live Stripe on every page view to
    # catch a webhook that never arrived; the gate is now written by the app itself
    # whenever access changes, and the daily sweep closes it when a grace window
    # lapses (modules.sweep_expired_module_access).
    current_app.logger.info(f"Checking enabled modules for entity {entity_id}")
    billing_enabled = _is_module_enabled(entity_id, MODULE_BILL)
    petty_cash_enabled = _is_module_enabled(entity_id, "PETTY_CASH")
    current_app.logger.info(
        f"Modules for {entity_id}: BILL={billing_enabled} PETTY_CASH={petty_cash_enabled}"
    )

    if not billing_enabled:
        current_app.logger.info(
            f"Only petty cash enabled - redirecting directly to dashboard for entity {entity_id}"
        )
        return redirect(url_for("entity.report_dashboard", id=entity_id))

    if not petty_cash_enabled:
        # Mirror image of the branch above: with only one module switched on there
        # is nothing to choose between, so the picker is a dead click. Send the
        # user straight into Module 2's app instead of the module choice.
        current_app.logger.info(
            f"Only billing enabled - redirecting directly to Module 2 for entity {entity_id}"
        )
        return redirect(billing_app_home_url(entity_id, org, current_user.id))

    # Both modules enabled — minty-web's module choice, with a token scoped to the company
    # (the same token the module settings page gets; a superuser outside it is view-only there
    # as everywhere). Never log the URL itself: it carries the token.
    current_app.logger.info(f"Handing over to minty-web's module choice for entity {entity_id}")
    return redirect(
        minty_web_landing_url(minty_web_company_path(entity_id), org, current_user.id)
    )


def minty_web_landing_url(next_path: str, org: Entity | None, user_id) -> str:
    """The way into minty-web: its ``/landing`` with a module token this app mints.

    Scoped to ``org`` when given (the company's module settings page - the token names the
    company and its enabled modules, as the payments-app tokens do), unscoped otherwise (the
    payer portal). ``next_path`` is a path on minty-web's origin and travels URL-encoded, so a
    query string of its own survives.
    """
    if org is not None:
        role = _resolve_user_entity_role(user_id, org.id)
        token = _generate_module_token(
            user_id,
            org.id,
            org.xero_org_id,
            role,
            billing_enabled=_is_module_enabled(org.id, MODULE_BILL),
            petty_cash_enabled=_is_module_enabled(org.id, "PETTY_CASH"),
        )
        entity_id, entity_name = org.id, org.name or ""
    else:
        token = _generate_module_token(user_id, "", "", "")
        entity_id, entity_name = "", ""
    return (
        f"{bearer_api.minty_web_origin()}/landing"
        f"?next={quote(next_path, safe='')}"
        f"&entity_id={entity_id}&entity_name={quote(entity_name, safe='')}&token={token}"
    )


def minty_web_company_path(entity_id, sub: str = "") -> str:
    """One company's pages on minty-web's origin: ``/entities/<shortid>/<name><sub>`` (phase 2,
    2026-10-05 - minty-web's ``lib/hubPaths.ts::companyPath``). An id that names no company
    keeps its full form with the placeholder name ``company``; minty-web puts the company's
    own name in the address bar once it knows it."""
    from blueprints.shared.entity_ref import canonical_ref

    ref = canonical_ref(entity_id)
    if "/" not in ref:
        ref = f"{ref}/company"
    return f"/entities/{ref}{sub}"


def minty_web_module_page_path(entity_id) -> str:
    """minty-web's module settings page of one company - the Module tab among its settings,
    ``/entities/<shortid>/<name>/settings/modules`` since phase 2 (it was
    ``/subscription/entities/<shortid>/<name>/modules``; minty-web 307s the old address)."""
    return minty_web_company_path(entity_id, "/settings/modules")


def minty_web_module_page_url(org: Entity, user_id) -> str:
    """minty-web's module settings page of ``org`` (Part 2 step 4a), through the landing."""
    return minty_web_landing_url(minty_web_module_page_path(org.id), org, user_id)


def minty_web_module_page_handoff(entity_id) -> str:
    """The module page as a link Flask authenticates at the CLICK, not when it is drawn:
    ``/handoff/minty-web?next=<module page>&entity_id=``. For links that wait on a page or a
    dialog (the subscription notice) - a token minted at render time lapses after
    ``MODULE_TOKEN_MINUTES``. A path on this app's origin, so the payments app can hand it
    to ``buildMintyEnterUrl`` like any other Minty path."""
    return url_for(
        "entity.handoff_minty_web",
        next=minty_web_module_page_path(entity_id),
        entity_id=str(entity_id),
    )


#: minty-web's hub pages: the entity list and My Profile.
MINTY_WEB_ENTITIES_PATH = "/entities"
MINTY_WEB_PROFILE_PATH = "/profile"


def minty_web_entity_list_url(user_id, *, notices: str | None = None) -> str:
    """minty-web's entity list, with an unscoped token - a person choosing a company is in
    none yet. ``notices`` is a signed flash hand-over (``services.entity_list.sign_notices``)
    for the list to show, so a message flashed on the way here is not lost."""
    path = MINTY_WEB_ENTITIES_PATH + (f"?flash={notices}" if notices else "")
    return minty_web_landing_url(path, None, user_id)


def minty_web_profile_url(org: Entity | None, user_id) -> str:
    """minty-web's My Profile: scoped to ``org`` when opened from inside a company (the
    profile names it and the person's role there), unscoped from the entity list. Its back
    arrow returns to the page the person came from (minty-web lib/backLink.ts)."""
    return minty_web_landing_url(MINTY_WEB_PROFILE_PATH, org, user_id)


@entity_bp.route("/handoff/minty-web")
@login_required
def handoff_minty_web():
    """Re-entry into minty-web: ``?next=<path on minty-web>&entity_id=<optional>``.

    minty-web has no login and no refresh of its own - its 30-minute token comes from here, and
    when it lapses the app sends the browser back to this route for another (lib/handoff.ts).
    Login-gated, so a person whose Flask session also ran out logs in first and then lands
    where they were going. ``next`` is a path only (``safe_next``): this route hands out a
    token, and must never be an open redirect.
    """
    destination = safe_next(request.args.get("next"), "/subscription")
    entity_id = (request.args.get("entity_id") or "").strip()
    org = None
    if entity_id:
        from services.permission_policy import has_entity_access

        org = Entity.query.filter(Entity.id == entity_id).first()
        if org is None or not (is_superuser(current_user) or has_entity_access(current_user, entity_id)):
            flash("Hmm, it looks like you don't have permission to look there.", "danger")
            return redirect(url_for("entity.entity_list"))
    return redirect(minty_web_landing_url(destination, org, current_user.id))


@entity_bp.route("/me/sidebar-token")
def sidebar_token():
    """The bearer token Flask's own pages hand their sidebar (``static/js/minty_sidebar.js``).

    The sidebar's My Profile and its Subscriptions Overview are drawn in the browser over the
    SAME reads minty-web makes - this app's ``/api/me/profile`` and minty-billing-api's
    ``/api/me/subscriptions`` - and both take a bearer token, not this app's session. So the
    page asks for one here: unscoped (the profile names its company as ``?entity=``; the
    subscriptions are the person's), ``MODULE_TOKEN_MINUTES`` like every other one.

    Not ``@login_required``: that answers with a redirect to the sign-in page, which a fetch
    follows and then fails on as HTML - a signed-out caller gets a 401 it can read instead.
    ``no-store`` so no cache keeps the token. The app-wide ``CORS(app)`` stamps ``*`` here as
    everywhere, which exposes nothing: this route reads the session cookie, and a browser
    never shows another origin a credentialed answer that does not name it and allow
    credentials - without the cookie the answer is the 401.
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    resp = make_response(
        jsonify(
            {
                "token": _generate_module_token(current_user.id, "", "", ""),
                "valid_for_seconds": MODULE_TOKEN_MINUTES * 60,
            }
        )
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@entity_bp.route("/profile")
@login_required
def open_profile():
    """Every "open my profile" link in Minty and the payments app comes here:
    ``?entity_id=<company it was opened from>``.

    Always minty-web's My Profile: billing-frontend's profile page was deleted on 2026-10-01
    (that app holds only Payment Request now), and its old ``/profile`` address forwards
    here. Minted here, at the click, rather than when the page that carries the link
    renders - a link minted at render time held a 30-minute token, and a page left open
    longer than that sent its avatar to an expired landing.
    """
    entity_id = (request.args.get("entity_id") or "").strip()
    org = None
    if entity_id:
        from services.permission_policy import has_entity_access

        org = Entity.query.filter(Entity.id == entity_id).first()
        if org is None or not (is_superuser(current_user) or has_entity_access(current_user, entity_id)):
            flash("Hmm, it looks like you don't have permission to look there.", "danger")
            return redirect(url_for("entity.entity_list"))

    return redirect(minty_web_profile_url(org, current_user.id))


@entity_bp.route("/entity/<entity:entity_id>/enter")
def module_reenter(entity_id):
    """Re-entry from Module 2. Validates the JWT, re-establishes the Flask
    session, then redirects to ``next`` (if safe) or the petty cash dashboard.

    ``next`` here is a path on THIS origin — the payer portal's ``buildEnterUrl``
    sends users to entity settings. Module 2 paths go through ``billing_relogin``
    instead, which hands them back to Module 2's own origin.

    The token turns into a full session, so only a MODULE token (``module`` claim, minted
    by ``_generate_module_token``) is accepted - not the onboarding token, which is meant
    for the onboarding API alone - and only for a company the person belongs to.
    """
    destination = safe_next(
        request.args.get("next"), url_for("entity.report_dashboard", id=entity_id)
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
        if decoded.get("module") != MODULE_TOKEN_CLAIM:
            current_app.logger.warning(
                f"/enter refused a non-module token (scope={decoded.get('scope')!r}) for entity {entity_id}"
            )
            flash("Something's off with your session. Mind logging back in?", "warning")
            return redirect(url_for("auth.home"))
        user = User.query.get(decoded["user_id"])
        if not user:
            flash("Hmm, that name doesn't seem to be in my list.", "danger")
            return redirect(url_for("auth.home"))

        from services.permission_policy import has_entity_access

        if not (is_superuser(user) or has_entity_access(user, entity_id)):
            current_app.logger.warning(f"/enter refused user {user.id}: not a member of entity {entity_id}")
            flash("Hmm, it looks like you don't have permission to look there.", "danger")
            return redirect(url_for("auth.home"))

        login_user(user)
        return redirect(destination)

    except jwt.ExpiredSignatureError:
        flash("Your session ran out. Mind logging back in?", "warning")
        return redirect(url_for("auth.home"))
    except (jwt.DecodeError, jwt.InvalidTokenError):
        flash("Something's off with your session. Mind logging back in?", "warning")
        return redirect(url_for("auth.home"))


@entity_bp.route("/entity/<entity:entity_id>/billing-relogin")
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


@entity_bp.route("/entity/<entity:entity_id>/payment-request")
@login_required
def go_to_bills(entity_id):
    """Direct handoff to Module 2 Bills (skips the module picker).

    ``?request=<uuid>`` lands on that payment request instead of the list: the payments app
    sends a page of another company here (its cookie holds one company at a time). Anything
    that is not a uuid is ignored; the payments API decides whether the request is this
    company's.
    """
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

    if not _is_module_enabled(entity_id, MODULE_BILL):
        flash("The Payment module isn't switched on for this entity yet - an admin can turn it on in the entity's module settings.", "warning")
        return redirect(url_for("entity.report_dashboard", id=entity_id))

    try:
        request_id = str(uuid.UUID(request.args.get("request", "")))
    except ValueError:
        request_id = None
    return redirect(billing_app_home_url(entity_id, org, current_user.id, request_id))


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
        "module": MODULE_TOKEN_CLAIM,
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
        "exp": datetime.now(timezone.utc) + timedelta(minutes=MODULE_TOKEN_MINUTES),
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
    # function_code is the closed module_code enum: a word outside it is not a module, and
    # asking the database would be an error, not a miss
    if function_code not in ModuleCode.values():
        current_app.logger.warning(
            f"Function {function_code} not found - denying access"
        )
        return False

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
    return bearer_api.frontend_origin()


def _billing_app_landing_url(entity_id: str, org: Entity, user_id, page: str) -> str:
    """The payments app's ``/landing`` with a module token for ``org``, going on to ``page``
    under the company's address (``/entity/<shortid>/<name>/<page>``, the address the app's
    middleware also builds - it re-checks the company against the token's)."""
    from blueprints.shared.entity_ref import canonical_ref

    role = _resolve_user_entity_role(user_id, entity_id)
    token = _generate_module_token(
        user_id,
        entity_id,
        org.xero_org_id,
        role,
        billing_enabled=_is_module_enabled(entity_id, MODULE_BILL),
        petty_cash_enabled=_is_module_enabled(entity_id, "PETTY_CASH"),
    )
    next_path = f"/entity/{canonical_ref(entity_id)}/{page}"
    return (
        f"{_frontend_origin()}/landing"
        f"?next={quote(next_path, safe='')}"
        f"&entity_id={entity_id}&entity_name={quote(org.name or '', safe='')}&token={token}"
    )


def billing_app_home_url(entity_id: str, org: Entity, user_id, request_id: str | None = None) -> str:
    """Handoff URL for Module 2 main app with entity pre-selected - its list, or one payment
    request when ``request_id`` (a uuid, checked by the caller) is given."""
    page = PAYMENT_REQUEST_APP_HOME_PATH
    if request_id:
        page = f"{page}/{request_id}"
    return _billing_app_landing_url(entity_id, org, user_id, page)


def billing_settings_app_url(entity_id: str, org: Entity, user_id) -> str:
    """Handoff URL for Module 2 settings page."""
    return _billing_app_landing_url(entity_id, org, user_id, PAYMENT_REQUEST_SETTINGS_PATH)

