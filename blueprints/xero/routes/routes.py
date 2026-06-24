import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote, unquote

import requests
from dateutil import parser
from flask import current_app
from flask import current_app as app
from flask import (flash, g, get_flashed_messages, jsonify, redirect, request,
                   session, url_for)
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required, login_user
from loguru import logger
from sqlalchemy import desc

from blueprints.entity.services.settings import \
    sync_all_accounts_and_contacts_background
from blueprints.entity.services.shared import check_user_has_entities
from blueprints.xero import xero_bp
from blueprints.xero.services.integration import (
    _get_entity_xero_data_from_db, get_accounts_from_xero, get_auth_token,
    get_contacts_from_xero)
from blueprints.xero.services.settings import (get_entity_account_settings,
                                               sync_entity_xero_status)
from services.helpers.xero_bridge import get_entity_contact_settings
from models.db import Entity, Report, User, UserToken, XeroContactSync, db, tz
from services.authz import (permission_denied, require_entity_access,
                            require_permission)
from services.auth.token_service import (ensure_valid_token,
                                         get_xero_token_user_for_entity,
                                         upsert_user_token)
from services.auth.token_service import \
    refresh_access_token as refresh_access_token_service
from services.permission_policy import Permission, has_permission
from blueprints.auth.services.identity import normalize_email, resolve_user_by_email
from blueprints.invitation.models.invitation import Invitation
from blueprints.invitation.services.invite import accept_invitation
from utils import decode_jwt


@xero_bp.route("/xero_auth")
def xero_auth():
    next_url = request.args.get("next")
    if next_url:
        session["next_after_login"] = next_url
    scope = "openid profile email offline_access"
    # An invite token rides along in the OAuth state (the session does NOT
    # survive the Xero round-trip, but state does — same trick as the
    # entity_connect_onboarding flow). The callback parses "auth:invite:<token>"
    # to auto-create the user + accept the invitation, mirroring the OTP path.
    invite_token = (request.args.get("invite") or "").strip()
    state = f"auth:invite:{invite_token}" if invite_token else "auth"
    return redirect(
        "https://login.xero.com/identity/connect/authorize?response_type=code"
        f"&client_id={current_app.config['CLIENT_ID']}"
        f"&redirect_uri={current_app.config['REDIRECT_URI']}"
        f"&scope={scope}"
        f"&state={state}"
    )


# --- Onboarding Xero handoff helpers --------------------------------------

def _onboarding_app_url() -> str:
    return os.environ.get(
        "ONBOARDING_APP_URL", "http://localhost:3001"
    ).rstrip("/")


def _onboarding_xero_return(connected: bool, org_name: str = ""):
    """Redirect back into the onboarding app at the Accounting step (3).

    ``org_name`` is the Xero tenant/org name so onboarding can show the real
    Xero entity (not the local entity name).
    """
    from urllib.parse import urlencode

    flag = "connected" if connected else "cancelled"
    qs = {"xero": flag, "step": 3}
    if org_name:
        qs["org"] = org_name
    return redirect(f"{_onboarding_app_url()}/?{urlencode(qs)}")


def _create_user_from_xero(decoded: dict, xero_email: str) -> User | None:
    """Create a User row for a Xero-authenticating invitee with no account.

    Mirrors the OTP path's ``_create_passwordless_user``: reuse any row that
    already owns this address (avoids the unique-username/email constraints),
    otherwise create a passwordless row. Name comes from the Xero id_token
    claims; ``xero_email`` records the Xero-side identity. ``approved`` is set
    here, but the real gate is ``accept_invitation`` which validates the token.
    """
    import secrets

    from werkzeug.security import generate_password_hash

    try:
        existing = (
            resolve_user_by_email(xero_email)
            or User.query.filter_by(username=xero_email).first()
        )
        if existing:
            return existing  # race / pre-existing — reuse it.

        first_name = (decoded.get("given_name") or "").strip() or "Xero"
        last_name = (decoded.get("family_name") or "").strip() or "User"
        user = User(
            id=str(uuid.uuid4()),
            email=xero_email,
            xero_email=xero_email,
            username=xero_email,
            first_name=first_name,
            last_name=last_name,
            password=generate_password_hash(
                secrets.token_urlsafe(32), method="pbkdf2:sha256"
            ),
            system_role=User.SYSTEM_ROLE_DEFAULT,
            approved=True,
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"Created Xero-invite User {user.id} for {xero_email}")
        return user
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Failed to create Xero-invite User for {xero_email}: {exc}")
        return None


@xero_bp.route("/xero_connect")
@login_required
def xero_connect_entity():
    if not has_permission(current_user, Permission.ENTITY_CREATE):
        return permission_denied(
            "You do not have permission to connect a new entity to Xero."
        )
    scope = (
        "openid profile email offline_access accounting.settings accounting.contacts"
    )
    # When launched from the onboarding app, tag the OAuth state so the
    # callback returns to onboarding (step 3) instead of the entity list.
    # The state param survives the Xero round-trip; the session does not.
    from_onboarding = request.args.get("from") == "onboarding"
    entity_id = (request.args.get("entity_id") or "").strip()
    # Carry the entity name too, so the callback can resolve the connecting
    # user's entity by name when no entity_id is present (a frontend that passes
    # only the name). The session does NOT survive the Xero round-trip, so both
    # id and name ride along in the state param. The name is URL-encoded because
    # it may contain ":" / spaces, which would otherwise break the partition.
    entity_name = (request.args.get("entity_name") or "").strip()
    base_state = "entity_connect_onboarding" if from_onboarding else "entity_connect"
    # state shape: "<base>" | "<base>:<entity_id>" | "<base>:<entity_id>:<name>"
    # entity_id may be empty while name is present (id-less resume).
    state = base_state
    if entity_id or entity_name:
        state = f"{base_state}:{entity_id}:{quote(entity_name, safe='')}"
    return redirect(
        "https://login.xero.com/identity/connect/authorize?response_type=code"
        f"&client_id={current_app.config['CLIENT_ID']}"
        f"&redirect_uri={current_app.config['REDIRECT_URI']}"
        f"&scope={scope}"
        f"&state={state}"
    )


@xero_bp.route("/xero_reconnect")
@login_required
@require_entity_access(entity_keys=("entity_id",))
@require_permission(
    Permission.XERO_SETTINGS_UPDATE,
    entity_keys=("entity_id",),
    message="You do not have permission to reconnect Xero for this entity.",
)
def xero_reconnect():
    entity_id = request.args.get("entity_id")
    session["reconnect_entity_id"] = entity_id
    scope = "email profile openid accounting.contacts accounting.contacts.read accounting.settings accounting.settings.read accounting.reports.read accounting.attachments.read files payroll.employees payroll.payruns payroll.payslip payroll.timesheets projects.read projects accounting.attachments files.read accounting.journals.read assets.read assets accounting.transactions payroll.settings accounting.budgets.read offline_access"
    state = "entity_reconnect"
    return redirect(
        "https://login.xero.com/identity/connect/authorize?response_type=code"
        f"&client_id={current_app.config['CLIENT_ID']}"
        f"&redirect_uri={current_app.config['REDIRECT_URI']}"
        f"&scope={scope}"
        f"&state={state}"
        f"&entity_id={entity_id}"
    )


def _resolve_connect_entity(entity_id, user, from_onboarding, entity_name=""):
    """Resolve which entity the Xero connection attaches to.

    Priority (most reliable first):

    1. Exact ``entity_id`` embedded in the OAuth state. ``entity_id`` is the
       primary key — unique and unambiguous — so it always wins.
    2. Onboarding with no id but a name carried through the state: the
       *connecting user's own* entity with that name (still in status
       "onboarding"). Scoped to the user's entities so a name another user
       happens to share can't be hijacked — the fix for the swap race.
    3. Onboarding with neither id nor a name match: the user's own
       most-recently-created "onboarding" entity.
    4. Non-onboarding legacy: the global latest-created entity.

    Resolving by the user's own entities (never the global latest) under cases
    2–3 is what closes the concurrency race where User A's callback could pick
    up User B's just-created entity.

    Returns the Entity or None.
    """
    if entity_id:
        return Entity.query.get(entity_id)

    if from_onboarding and user is not None:
        from models.db import UserEntity

        owned_onboarding = Entity.query.join(
            UserEntity, UserEntity.entity_id == Entity.id
        ).filter(
            UserEntity.user_id == user.id,
            Entity.status == "onboarding",
        )

        name = (entity_name or "").strip()
        if name:
            by_name = (
                owned_onboarding.filter(Entity.name == name)
                .order_by(desc(Entity.created_at))
                .first()
            )
            if by_name is not None:
                return by_name

        return owned_onboarding.order_by(desc(Entity.created_at)).first()

    return Entity.query.order_by(desc(Entity.created_at)).first()


@xero_bp.route("/callback", methods=["GET"])
def xero_callback():
    code = request.args.get("code")
    state = request.args.get("state") or ""
    error = request.args.get("error")

    # State may carry an embedded entity_id and (for onboarding) a URL-encoded
    # entity name: "entity_connect:<uuid>" or
    # "entity_connect_onboarding:<uuid>:<url-encoded-name>". Split them out so
    # downstream logic can resolve the exact entity (by id, then by the user's
    # own entity name) rather than falling back to latest-created.
    base_state, _, state_suffix = state.partition(":")
    state_suffix = state_suffix.strip()

    # The login flow can additionally carry an invitation: "auth:invite:<token>".
    # Pull the token out so the auth branch can accept the invite after OAuth.
    invite_token = ""
    if base_state == "auth" and state_suffix.startswith("invite:"):
        invite_token = state_suffix[len("invite:"):].strip()
        state_suffix = ""

    # For the entity-connect branches the suffix is "<entity_id>:<name>" (name
    # url-encoded, either part possibly empty). For other branches it's just the
    # raw suffix.
    state_entity_id, _, state_entity_name_raw = state_suffix.partition(":")
    state_entity_id = state_entity_id.strip()
    state_entity_name = unquote(state_entity_name_raw).strip()

    # Legacy: entity_id could also arrive as a query param (reconnect flow).
    entity_id = state_entity_id or (request.args.get("entity_id") or "").strip()
    if entity_id:
        logger.info(f"Entity ID: {entity_id}")
    if state_entity_name:
        logger.info(f"Entity name (fallback resolver): {state_entity_name}")

    if base_state == "auth":
        response = get_auth_token(code, state)
        decoded = decode_jwt(response.get("id_token"))
        decode_jwt(response.get("access_token"))
        access_token = response.get("access_token")
        id_token = response.get("id_token")
        expires_in = response.get("expires_in")
        refresh_token = response.get("refresh_token")

        # The Xero id_token carries an `email` claim (the `email` scope is
        # requested); `preferred_username` is the Xero login email as a fallback.
        xero_email = normalize_email(
            decoded.get("email") or decoded.get("preferred_username"))

        # Resolve by email/xero_email so a personal/OTP row with the same address
        # is reused (one user) instead of creating a duplicate.
        user = resolve_user_by_email(xero_email)

        if not user and invite_token:
            # No account + an invite, but if Xero returned no email claim we
            # can't match the invite or build a valid (non-null) username.
            if not xero_email:
                logger.warning(
                    "Xero invite login: id_token carried no email claim"
                )
                flash(
                    "Your Xero account didn't share an email address. "
                    "Please use the email login link instead.",
                    "error",
                )
                return redirect(url_for("auth.home"))

            # Invitee with no account yet. Validate the invite addresses THIS
            # Xero email BEFORE creating anything — accept_invitation enforces
            # the same rule, but doing it first avoids leaving an orphan User
            # row when the Xero login email differs from the invited address.
            invitation = Invitation.query.filter_by(
                token=invite_token, status="pending"
            ).first()
            if not invitation:
                flash(
                    "This invitation is invalid or has already been used.",
                    "error",
                )
                return redirect(url_for("auth.home"))
            if normalize_email(invitation.email) != xero_email:
                flash(
                    "This invitation was sent to a different email address. "
                    "Log in with the Xero account matching the invite.",
                    "error",
                )
                return redirect(url_for("auth.home"))

            # Mirror the OTP path's _create_passwordless_user: auto-create a
            # User row from the Xero id_token (email + name claims) so
            # accept_invitation has someone to attach the membership to. The
            # invite IS the approval.
            user = _create_user_from_xero(decoded, xero_email)
            if user is None:
                flash(
                    "Could not create your account. Please contact your inviter.",
                    "error",
                )
                return redirect(url_for("auth.home"))

        # No "sign up first" gate: if the Xero account isn't in the DB yet,
        # auto-create it from the id_token so they can log in and use the app.
        if not user:
            if not xero_email:
                # Xero gave us no email — we can't build a valid (non-null)
                # username, so this is the one case we can't let through.
                logger.warning("Xero login: id_token carried no email claim")
                flash(
                    "Your Xero account didn't share an email address.",
                    "error",
                )
                return redirect(url_for("auth.home"))
            user = _create_user_from_xero(decoded, xero_email)
            if user is None:
                flash("Could not log you in. Please try again.", "error")
                return redirect(url_for("auth.home"))
            logger.info(f"Xero login: auto-created account for {xero_email}")

        if user:
            # Existing row (personal/OTP or prior Xero) — link Xero identity if
            # not yet stored, then refresh tokens.
            if not user.xero_email:
                user.xero_email = xero_email
            user.access_token = access_token
            user.id_token = id_token
            user.expires_in = expires_in
            user.refresh_token = refresh_token
            user.token_created_at = datetime.now(tz)
            db.session.commit()
            upsert_user_token(user, response)

            # If this Xero login is accepting an invite, attach the entity
            # membership BEFORE logging in — exactly like the OTP handoff.
            # accept_invitation enforces user_email == invitation.email, so a
            # mismatched Xero address is rejected here, not silently accepted.
            if invite_token:
                entity_id_accepted, accept_error, _hint = accept_invitation(
                    invite_token, user.id
                )
                if accept_error:
                    logger.warning(
                        f"Xero invite acceptance failed for user {user.id}: "
                        f"{accept_error}"
                    )
                    flash(accept_error, "error")
                    return redirect(url_for("auth.home"))
                login_user(user)
                logger.info(
                    f"Xero login: user {user.id} accepted invite to entity "
                    f"{entity_id_accepted}."
                )
                flash("Invitation accepted. Welcome!", "success")
                return redirect(
                    url_for("entity.report_dashboard", id=entity_id_accepted)
                )

            login_user(user)
            # Drain any flashes left queued in the session from a pre-login
            # request (e.g. a stale deep link that flashed "Entity not found"
            # then redirected). Flashes survive redirects, and the dashboard
            # is the one page that renders the `danger` category, so without
            # this the old error pops up next to the login-success toast.
            # Same defensive pattern used in auth/logout.py and register.py.
            get_flashed_messages()
            flash("Xero Authentication: Logged in successfully", "success")
            next_url = session.pop("next_after_login", None)
            return redirect(next_url or url_for("entity.entity_list"))
        else:
            db.session.rollback()
            logger.error(f"Error in xero auth with user: {user}")
            flash("Xero Connect: Authentication Error", "error")
            return redirect(url_for("auth.home"))
    elif base_state in ("entity_connect", "entity_connect_onboarding"):
        from_onboarding = base_state == "entity_connect_onboarding"

        error = request.args.get("error")
        if not error:
            response = get_auth_token(code, state)
            decoded = decode_jwt(response.get("id_token"))
            xero_email = normalize_email(
                decoded.get("email") or decoded.get("preferred_username"))
            user = resolve_user_by_email(xero_email)

            if user:
                dec_acc_token = decode_jwt(response.get("access_token"))
                auth_id = dec_acc_token["authentication_event_id"]
                logger.info(f"Entity Connect Auth Id: {auth_id}")
                headers = {
                    "Authorization": f"Bearer {response.get('access_token')}",
                    "Content-Type": "application/json",
                }
                curr_conn = requests.get(
                    f"https://api.xero.com/connections?authEventId={auth_id}",
                    headers=headers,
                )
                try:
                    curr_conn = curr_conn.json()
                    if not curr_conn:
                        flash(
                            "Entity Created, but not connected to Xero.",
                            "warning",
                        )
                        logger.error(
                            "User did not select an entity in the dropdown in allow in xero's allow access page"
                        )
                        if from_onboarding:
                            return _onboarding_xero_return(False)
                        return redirect(url_for("entity.entity_list"))
                    elif curr_conn:
                        try:
                            tenant_id = curr_conn[0]["tenantId"]
                            if tenant_id is None:
                                flash(
                                    "Xero Connect: Please select an entity to connect.", "error", )
                                if from_onboarding:
                                    return _onboarding_xero_return(False)
                                return redirect(
                                    url_for("entity.entity_create_success"))
                            else:
                                entity = _resolve_connect_entity(
                                    entity_id,
                                    user,
                                    from_onboarding,
                                    entity_name=state_entity_name,
                                )
                                if entity is None:
                                    logger.error(f"Entity Connect: entity '{entity_id}' not found")
                                    flash("Xero Connect: Entity not found.", "error")
                                    if from_onboarding:
                                        return _onboarding_xero_return(False)
                                    return redirect(url_for("entity.entity_list"))
                                # ``user`` is already the user resolved from the
                                # Xero id_token email above. Do NOT re-fetch via
                                # current_user: /callback has no @login_required
                                # and login_user runs later, so during the
                                # onboarding redirect-back current_user is
                                # anonymous — current_user.username would be None
                                # and clobber ``user`` with the wrong / no row.
                                entity.xero_org_id = tenant_id
                                entity.xero_tenant_name = curr_conn[0].get(
                                    "tenantName"
                                )
                                # Mid-onboarding, leave status == "onboarding" so
                                # the resume flow (entity list badge, modules.py
                                # resume, /api/onboarding/state step derivation)
                                # keeps working. Only /api/onboarding/finalize
                                # clears it. Outside onboarding, mark connected.
                                if not from_onboarding:
                                    entity.status = "connected"
                                entity.last_connected_at = datetime.now()
                                entity.connected_by_user_id = user.id
                                user.xero_entity_id = tenant_id
                                db.session.commit()
                                # Persist the fresh token bundle to user_token
                                # so the entity-connector lookup can read it.
                                upsert_user_token(user, response)

                                try:
                                    _app = current_app._get_current_object()
                                    sync_thread = threading.Thread(
                                        target=sync_all_accounts_and_contacts_background,
                                        args=(
                                            str(entity.id),
                                            response.get("access_token"),
                                            tenant_id,
                                            user.id,
                                            _app,
                                        ),
                                        daemon=True,
                                    )
                                    sync_thread.start()
                                    time.sleep(0.2)
                                    if sync_thread.is_alive():
                                        logger.info(
                                            f"Background sync thread started successfully for entity {entity.id}"
                                        )
                                    else:
                                        logger.warning(
                                            f"Background sync thread may not have started for entity {entity.id}"
                                        )
                                except Exception as sync_error:
                                    logger.warning(
                                        f"Entity Connect: failed to start background sync: {sync_error}"
                                    )

                                login_user(user)
                                flash(
                                    "Xero connect: Successfully connected. Syncing accounts and contacts in background...",
                                    "success",
                                )
                                if from_onboarding:
                                    return _onboarding_xero_return(
                                        True, entity.xero_tenant_name or ""
                                    )
                                return redirect(url_for("entity.entity_list"))
                        except Exception as err:
                            flash(
                                "Xero Connect: There is an error connecting to xero", "error", )
                            logger.error(
                                f"There is an error connecting to xero: {err}")
                            if from_onboarding:
                                return _onboarding_xero_return(False)
                            return redirect(
                                url_for("entity.entity_create_success"))
                except Exception as error:
                    flash(
                        "Xero Connect: There is no entity selected to connect",
                        "error")
                    logger.error(
                        f"There is an error connecting to xero: {error}")
                    if from_onboarding:
                        return _onboarding_xero_return(False)
                    return redirect(url_for("entity.entity_create_success"))
        else:
            if from_onboarding:
                # Mid-onboarding the user may cancel/deny and retry or skip;
                # leave the entity intact and return to the Accounting step.
                logger.info("Onboarding Xero connect cancelled/denied by user")
                return _onboarding_xero_return(False)
            entity = (
                Entity.query.get(entity_id)
                if entity_id
                else Entity.query.order_by(desc(Entity.created_at)).first()
            )
            if entity is None:
                logger.error(f"Entity Connect cancel: entity '{entity_id}' not found")
                return redirect(url_for("entity.entity_list"))
            entity.status = "cancelled"
            db.session.commit()
            logger.info(
                "Newly created petty cash entity status set to cancelled")
            logger.error(f"Error in xero auth {error}")
            flash("New Petty Cash Entity has been created", "success")
            return redirect(url_for("entity.entity_list"))
    elif base_state == "entity_reconnect":
        entity_id = (
            session.get("reconnect_entity_id")
            or entity_id
            or request.args.get("entity_id")
        )

        if not entity_id:
            logger.error("Entity Reconnect: Missing entity_id after callback")
            flash("Xero Reconnect: Missing entity to reconnect.", "error")
            return redirect(url_for("entity.entity_list"))

        if not error:
            response = get_auth_token(code, state)
            decoded = decode_jwt(response.get("id_token"))
            xero_email = normalize_email(
                decoded.get("email") or decoded.get("preferred_username"))
            user = resolve_user_by_email(xero_email)

            if user:
                dec_acc_token = decode_jwt(response.get("access_token"))
                auth_id = dec_acc_token["authentication_event_id"]
                logger.info(f"Entity Reconnect Auth Id {auth_id}")
                try:
                    user.access_token = response.get("access_token")
                    user.id_token = response.get("id_token")
                    user.expires_in = response.get("expires_in")
                    user.refresh_token = response.get("refresh_token")
                    user.token_created_at = datetime.now(tz)
                    db.session.commit()
                    try:
                        login_user(user)
                    except Exception:
                        logger.warning(
                            "Entity Reconnect: login_user refresh skipped")
                except Exception:
                    logger.warning(
                        "Entity Reconnect: failed to update user tokens")

                headers = {
                    "Authorization": f"Bearer {response.get('access_token')}",
                    "Content-Type": "application/json",
                }
                curr_conn = requests.get(
                    f"https://api.xero.com/connections?authEventId={auth_id}",
                    headers=headers,
                )

                try:
                    curr_conn = curr_conn.json()
                    if not curr_conn:
                        flash(
                            "Xero Reconnect: Please select a xero entity to connect", "error", )
                        logger.error(
                            "User did not select an entity in the dropdown in allow in xero's allow access page"
                        )
                    else:
                        try:
                            tenant_id = curr_conn[0]["tenantId"]
                            if tenant_id is None:
                                flash(
                                    "Xero Reconnect: Please select an entity to connect.", "error", )
                                return redirect(
                                    url_for(
                                        "entity_settings",
                                        entity_id=entity_id))
                            else:
                                entity = Entity.query.filter(
                                    Entity.id == entity_id
                                ).first()
                                if entity:
                                    if not entity.xero_org_id or str(
                                        entity.xero_org_id
                                    ) != str(tenant_id):
                                        logger.info(
                                            f"Entity {entity_id} xero_org_id update: {entity.xero_org_id} -> {tenant_id}"
                                        )
                                    entity.xero_org_id = tenant_id
                                    entity.xero_tenant_name = curr_conn[0].get(
                                        "tenantName"
                                    )
                                entity.status = "connected"
                                entity.last_connected_at = datetime.now()
                                entity.connected_by_user_id = user.id
                                if not user.xero_entity_id or str(
                                    user.xero_entity_id
                                ) != str(tenant_id):
                                    user.xero_entity_id = tenant_id
                                db.session.commit()
                                # Persist the fresh token bundle to user_token
                                # so the entity-connector lookup can read it.
                                upsert_user_token(user, response)

                                try:
                                    _app = current_app._get_current_object()
                                    sync_thread = threading.Thread(
                                        target=sync_all_accounts_and_contacts_background, args=(
                                            entity_id, response.get("access_token"), tenant_id, user.id, _app, ), daemon=True, )
                                    sync_thread.start()
                                    time.sleep(0.2)
                                    if sync_thread.is_alive():
                                        logger.info(
                                            f"Background sync thread started successfully for entity {entity_id}"
                                        )
                                    else:
                                        logger.warning(
                                            f"Background sync thread may not have started for entity {entity_id}"
                                        )
                                except Exception as sync_error:
                                    logger.warning(
                                        f"Entity Reconnect: failed to start background sync: {sync_error}"
                                    )

                                try:
                                    sync_entity_xero_status(entity_id)
                                except Exception:
                                    logger.warning(
                                        "Entity Reconnect: status sync skipped"
                                    )
                                flash(
                                    "Xero Reconnect: Successfully reconnected. Syncing accounts and contacts in background...",
                                    "success",
                                )
                                logger.info(
                                    "Xero Reconnect: Successfully reconnected")
                                return redirect(
                                    url_for(
                                        "entity_settings",
                                        entity_id=entity_id))
                        except Exception as err:
                            flash(
                                "Xero Reconnect: There is an error connecting to xero", "error", )
                            logger.error(
                                f"There is an error connecting to xero: {err}")
                except Exception as err:
                    flash(
                        "Xero Reconnect: There is no entity selected to connect",
                        "error",
                    )
                    logger.error(
                        f"There is an error connecting to xero: {err}")
                    return redirect(
                        url_for(
                            "entity_settings",
                            entity_id=entity_id))
        else:
            logger.error(f"Error in xero auth {error}")
            flash("Xero Reconnect: There is an error reconnecting to xero", "error")
            return redirect(url_for("entity_settings", entity_id=entity_id))
    return redirect(url_for("entity_settings", entity_id=entity_id))


@xero_bp.route("/api/refresh_xero_token", methods=["GET"])
@login_required
def refresh_access_token() -> ResponseReturnValue:
    token_response = refresh_access_token_service()
    if token_response:
        return jsonify(token_response), 200
    return (
        jsonify({"status": "error", "message": "Failed to refresh access token"}),
        500,
    )


@xero_bp.route("/api/xero/bank-transactions/latest/<entity_id>",
               methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero bank transactions.",
)
def get_latest_xero_bank_transactions(entity_id: str) -> ResponseReturnValue:
    try:
        entity = Entity.query.get_or_404(entity_id)
        access_token = current_user.access_token
        xero_org_id = entity.xero_org_id

        url = f"{current_app.config['XERO_API_BASE_URL']}/BankTransactions"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": str(xero_org_id),
            "Accept": "application/json",
        }
        date = request.args.get("date")
        _ = request.args.get("bankAccount")
        response = requests.get(url, headers=headers)
        if response.status_code in (200, 201):
            bank_transactions = response.json().get("BankTransactions", [])
            for transaction in bank_transactions:
                date_xero = str(
                    parser.parse(transaction.get("DateString"))
                    .date()
                    .strftime("%Y-%m-%d")
                )
                if date_xero == date:
                    logger.info(
                        f"Latest Xero bank transactions: {transaction}")
                    return jsonify(
                        {"status": "success", "data": transaction}), 200
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Failed to fetch bank transactions: {response.text}",
                    }),
                response.status_code,
            )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "not_found", "message": "No transaction found"}), 404


@xero_bp.route("/api/xero/bank-transactions/update/<entity_id>",
               methods=["POST"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_UPDATE,
    entity_arg="entity_id",
    message="You do not have permission to update Xero bank transactions.",
)
def update_bank_transaction(entity_id):
    logger.info(f"Updating bank transaction for entity_id: {entity_id}")
    entity = Entity.query.get_or_404(entity_id)
    token = current_user.access_token

    data = request.get_json()
    transaction_id = data.get("BankTransactionId")
    new_amount = data.get("Amount")
    account_id = data.get("AccountID")
    date_str = data.get("Date")
    if not date_str:
        return jsonify({"status": "error", "message": "Missing date"}), 400
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    redirect_date = date + timedelta(days=1)

    report = Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == date,
    ).first()
    if report:
        previous_deposit = report.bank_deposit or 0.0
        if new_amount is not None and float(new_amount) > previous_deposit:
            return jsonify({
                "status": "error",
                "message": "Deposit cannot be higher than previous deposit amount",
            }), 400

    headers = {
        "Authorization": f"Bearer {token}",
        "Xero-Tenant-Id": str(entity.xero_org_id),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    director_contact = get_entity_contact_settings(
        entity_id, "director_contact"
    )
    director_contact_id = (
        director_contact.xero_contact_id if director_contact else None
    )
    contact_name = director_contact.name if director_contact else ""
    logger.info(f"Contact name: {contact_name}")

    account_settings = get_entity_account_settings(entity_id, "director")
    account_code = (
        account_settings["account_code"]
        if account_settings is not None and account_settings != {}
        else None
    )
    if account_code is None:
        raise RuntimeError("Director account code not configured")
    logger.info(f"Director account code: {account_code}")

    bank_transaction_payload = {
        "bankTransactions": [
            {
                "type": "RECEIVE",
                "contact": {"contactID": director_contact_id},
                "lineItems": [
                    {
                        "description": f"Amount due to {contact_name}",
                        "quantity": 1,
                        "unitAmount": new_amount,
                        "accountCode": account_code,
                        "taxType": "NONE",
                    }
                ],
                "bankAccount": {"accountID": account_id},
            }
        ]
    }
    url = f"{current_app.config['XERO_API_BASE_URL']}/BankTransactions/{transaction_id}"
    response = requests.post(
        url, data=json.dumps(bank_transaction_payload), headers=headers
    )

    return (
        jsonify(
            {
                "status": "success",
                "message": "Bank transaction updated successfully",
                "data": response.json(),
                "redirect_url": f"/report/opening?entity_id={entity_id}&transaction_date={redirect_date}",
            }),
        200,
    )


@xero_bp.route("/api/entity/<string:entity_id>/xero-sync-status",
               methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero sync status.",
)
def get_xero_sync_status(entity_id):
    """API endpoint to check the status of Xero sync for an entity."""
    from services.app_runtime.legacy import compat

    xero_sync_status = compat.xero_sync_status
    status = xero_sync_status.get(entity_id, {"status": "idle", "message": ""})
    return jsonify(status)


@xero_bp.route("/entity/settings/xero/disconnect", methods=["GET"])
@login_required
@require_entity_access(entity_keys=("entity_id",))
@require_permission(
    Permission.XERO_SETTINGS_UPDATE,
    entity_keys=("entity_id",),
    message="You do not have permission to disconnect Xero for this entity.",
)
def disconnect_from_xero():
    entity_id = request.args.get("entity_id")

    if not entity_id:
        flash("Entity ID is required.", "danger")
        return redirect(url_for("entity.entity_list"))

    try:
        org = Entity.query.get_or_404(entity_id)
        logger.info(f"Disconnecting entity: {org.name} (ID: {entity_id})")

        connector = None
        if org.connected_by_user_id:
            connector = User.query.get(org.connected_by_user_id)
            if connector is None:
                logger.warning(
                    f"connected_by_user_id {org.connected_by_user_id} on entity "
                    f"{entity_id} points to a missing user; skipping remote disconnect"
                )

        if connector is not None and org.xero_org_id:
            xero_connections_url = "https://api.xero.com/connections"
            try:
                if ensure_valid_token(connector):
                    get_conn_response = requests.get(
                        xero_connections_url,
                        headers={
                            "Authorization": f"Bearer {connector.access_token}"},
                        timeout=10,
                    )
                    if get_conn_response.status_code == 200:
                        for conn in get_conn_response.json():
                            if conn.get("tenantId") == str(org.xero_org_id):
                                auth_id_to_delete = conn.get("id")
                                delete_response = requests.delete(
                                    f"{xero_connections_url}/{auth_id_to_delete}",
                                    headers={
                                        "Authorization": f"Bearer {connector.access_token}"
                                    },
                                    timeout=10,
                                )
                                if delete_response.status_code in [200, 204]:
                                    logger.info(
                                        f"Disconnected user {connector.username} from entity {entity_id}"
                                    )
                                else:
                                    logger.warning(
                                        f"Xero DELETE /connections/{auth_id_to_delete} "
                                        f"returned {delete_response.status_code}"
                                    )
                                break
                    else:
                        logger.warning(
                            f"Xero GET /connections returned {get_conn_response.status_code} "
                            f"for user {connector.username}"
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to disconnect user {connector.username}: {str(e)}"
                )

        # Clear the connector's stored tokens (user columns + user_token row) —
        # but ONLY if this user has no OTHER entity still connected with the same
        # shared token bundle. Tokens are per-user (user_token.user_id is UNIQUE)
        # and one user can be connected_by_user_id for several entities, so a
        # blanket clear here would break those other entities' Xero access. Scope
        # the clear to "this was their last connection".
        if connector is not None:
            other_connected = (
                Entity.query.filter(
                    Entity.connected_by_user_id == connector.id,
                    Entity.xero_org_id.isnot(None),
                    Entity.id != entity_id,
                ).first()
                is not None
            )
            if other_connected:
                logger.info(
                    f"Keeping Xero tokens for user {connector.username} — "
                    f"still connected to other entities"
                )
            else:
                connector.access_token = None
                connector.refresh_token = None
                connector.xero_entity_id = None
                connector.id_token = None
                connector.expires_in = None
                connector.token_created_at = None

                token_row = UserToken.query.filter_by(
                    user_id=connector.id
                ).first()
                if token_row is not None:
                    token_row.access_token = None
                    token_row.refresh_token = None
                    token_row.id_token = None
                    token_row.access_token_expires_in = None
                    token_row.access_token_obtained_at = None
                logger.info(
                    f"Cleared Xero tokens for user {connector.username}"
                )

        org.status = "disconnected"
        org.xero_org_id = None
        org.connected_by_user_id = None
        db.session.commit()
        logger.info(f"Successfully disconnected entity: {entity_id}")
        flash("Disconnected from Xero successfully.", "success")
        return redirect(url_for("entity_settings", entity_id=entity_id))
    except Exception as e:
        logger.error(f"Error disconnecting from Xero: {str(e)}")
        db.session.rollback()
        flash("An error occurred while disconnecting from Xero.", "danger")
        return redirect(url_for("entity_settings", entity_id=entity_id))


@xero_bp.route("/api/entity/<string:entity_id>/xero-data", methods=["GET"])
@login_required
@require_entity_access(entity_arg="entity_id")
@require_permission(
    Permission.XERO_SETTINGS_VIEW,
    entity_arg="entity_id",
    message="You do not have permission to view Xero data for this entity.",
)
def get_entity_xero_data(entity_id):
    try:
        if not check_user_has_entities(current_user.id):
            return jsonify(
                {"status": "error", "message": "No entities found"}), 403

        org = Entity.query.filter(Entity.id == entity_id).first()
        if not org:
            return jsonify(
                {"status": "error", "message": "Entity not found"}), 404

        if not org.xero_org_id:
            return jsonify(
                {"status": "error", "message": "Xero not connected"}), 400

        token_user = get_xero_token_user_for_entity(entity_id)
        if not ensure_valid_token(token_user):
            db_data = _get_entity_xero_data_from_db(entity_id)
            if db_data and any(
                db_data.get(k)
                for k in (
                    "bank_accounts",
                    "cashsale_account",
                    "owners_account",
                    "discrepancy_account",
                    "contacts",
                )
            ):
                return jsonify({"status": "success", **db_data})
            return (
                jsonify({"status": "error", "message": "Xero authentication expired"}),
                401,
            )

        if not hasattr(g, "_xero_data_cache"):
            g._xero_data_cache = {}

        cache_key = f"{entity_id}_{org.xero_org_id}"
        if cache_key not in g._xero_data_cache:
            logger.info(f"Fetching fresh Xero data for entity {entity_id}")
            # Filter to ACTIVE accounts only so archived-in-Xero accounts
            # never repopulate the settings dropdowns.
            all_accounts = get_accounts_from_xero(
                token_user.access_token,
                org.xero_org_id,
                where='Status=="ACTIVE"',
                token_validated=True,
            )

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
                if acc.get("Type")
                in ["CURRENT", "CURRLIAB", "NONCURRENT", "TERMLIAB", "LIABILITY"]
            ]
            owners_account = [
                acc
                for acc in owners_account
                if not (
                    acc.get("SystemAccount")
                    and isinstance(acc.get("SystemAccount"), str)
                    and acc.get("SystemAccount").strip() != ""
                )
            ]
            discrepancy_account = [
                acc for acc in all_accounts if acc.get("Type") in ("EXPENSE", "DIRECTCOSTS")
            ]

            contacts = get_contacts_from_xero(
                token_user.access_token,
                org.xero_org_id,
                order="Name ASC",
                token_validated=True,
            )

            if not all_accounts and not contacts:
                db_data = _get_entity_xero_data_from_db(entity_id)
                if db_data:
                    bank_accounts = db_data["bank_accounts"]
                    cashsale_account = db_data["cashsale_account"]
                    owners_account = db_data["owners_account"]
                    discrepancy_account = db_data["discrepancy_account"]
                    contacts = db_data["contacts"]

            g._xero_data_cache[cache_key] = {
                "bank_accounts": bank_accounts,
                "cashsale_account": cashsale_account,
                "owners_account": owners_account,
                "discrepancy_account": discrepancy_account,
                "contacts": contacts,
            }
        else:
            logger.info(f"Using cached Xero data for entity {entity_id}")
            cached_data = g._xero_data_cache[cache_key]
            bank_accounts = cached_data["bank_accounts"]
            cashsale_account = cached_data["cashsale_account"]
            owners_account = cached_data["owners_account"]
            discrepancy_account = cached_data["discrepancy_account"]
            contacts = cached_data["contacts"]

        bank_accounts = bank_accounts or []
        cashsale_account = cashsale_account or []
        owners_account = owners_account or []
        discrepancy_account = discrepancy_account or []
        contacts = contacts or []

        return jsonify(
            {
                "status": "success",
                "bank_accounts": bank_accounts,
                "cashsale_account": cashsale_account,
                "owners_account": owners_account,
                "discrepancy_account": discrepancy_account,
                "contacts": contacts,
            }
        )
    except Exception as e:
        logger.error(
            f"Error fetching Xero data for entity {entity_id}: {str(e)}")
        return jsonify(
            {"status": "error", "message": "Failed to fetch Xero data"}), 500


"""Xero connection and integration route handlers extracted from legacy."""








