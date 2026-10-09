"""A company's Users and Entity & Integration tabs as minty-web draws them (phase 2, 2026-10-05):
the bearer routes behind ``/entity/<shortid>/<name>/settings/{users,integration}``. They replace
the session pages ``settings_users_bills_ui.html`` / ``settings_xero_bills_ui.html`` and the session
JSON routes those pages called (``/minty/api/invitation/*``, ``/minty/api/users/<id>[/role]``,
``POST /entity/settings/xero/disconnect``), which are deleted with them.

THE COMPANY comes from ``?entity=`` and nowhere else - never the body, never the token - and must
be one the person belongs to (or any, for a superuser): ``profile.entity_context``, the test the
profile and ``/handoff/minty-web`` apply. (The session ``PATCH /minty/api/users/<id>`` read the
company from the query for its permission check and from the body for its write, so a check on
one company let a rename land in another.)

Each action asks for its own permission (``services.permission_policy``) and then the rank rule -
``can_manage_role_assignment_for_entity``: a role at or below your own. Roles are the four
assignable ones only (``enums.ASSIGNABLE_ENTITY_ROLES``); an address to invite is an address and
nothing else (``email_rules.invite_address_error``). Names are never changed here: a person
edits their own in My Profile (``PATCH /api/me/profile``).

Everything refuses through ``hub_api`` (``{"error": <sentence>}`` with CORS), the guard services'
own ``(response, status)`` answers re-worded into that shape by ``_refusal``. ``?flash=`` is the
signed hand-over Flask's redirects to these tabs carry (the Xero reconnect's outcome); the GETs
answer it as ``notices``.
"""

from __future__ import annotations

import uuid

from flask import request
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.entity.services.entity_list import read_notices
from blueprints.shared import hub_api
from blueprints.shared.email_rules import invite_address_error
from blueprints.shared.enums import ASSIGNABLE_ENTITY_ROLES, entity_role_label
from blueprints.user_management.services import profile
from services.permission_policy import (Permission, can_manage_role_assignment_for_entity,
                                        has_permission)

_SAVE_FAILED = "That didn't quite save. Mind trying again?"
_NO_COMPANY = "You don't have access to that company."
_ROLE_VALUES = tuple(role.value for role in ASSIGNABLE_ENTITY_ROLES)


def _value(role) -> str:
    """A stored role as its string (the column hands back the enum or the string)."""
    return str(getattr(role, "value", role) or "")


def _refusal(answer):
    """A guard service's ``(jsonify({status, message}), code)`` as the hub's refusal."""
    response, status = answer
    body = response.get_json(silent=True) or {}
    return hub_api.refuse(body.get("message") or _SAVE_FAILED, status)


def _open(permission: Permission, denied: str):
    """``(early, user, entity_id)``: the bearer, the company from ``?entity=`` and the
    permission this route asks for. Return ``early`` when it is not None."""
    early, user = hub_api.guard()
    if early is not None:
        return early, None, None
    entity_id = (request.args.get("entity") or "").strip()
    company = profile.entity_context(user, entity_id) if entity_id else None
    if company is None:
        return hub_api.refuse(_NO_COMPANY, 403), None, None
    if not has_permission(user, permission, company["id"]):
        return hub_api.refuse(denied, 403), None, None
    return None, user, company["id"]


def _modules(entity_id) -> list[str]:
    """The company's modules switched on - which settings pills the tab shows."""
    from blueprints.entity.services.modules import get_enabled_modules_for_entities

    return sorted(get_enabled_modules_for_entities([entity_id]).get(entity_id, set()))


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# --- Users ---------------------------------------------------------------------------------------


def _roles_for(user, entity_id) -> list[dict]:
    """The roles this person may give: the assignable four, at or below their own rank."""
    return [
        {"value": role.value, "label": entity_role_label(role.value)}
        for role in ASSIGNABLE_ENTITY_ROLES
        if can_manage_role_assignment_for_entity(user, role.value, entity_id)
    ]


def _users_page(user, entity_id) -> dict:
    from blueprints.invitation.services.invite import (get_pending_invitations,
                                                       resend_cooldown_remaining)
    from blueprints.subscription.services import store_ro as sub_store
    from models.db import Entity, User, UserEntity, db

    org = db.session.get(Entity, entity_id)
    members = (
        db.session.query(User, UserEntity.role)
        .join(UserEntity, User.id == UserEntity.user_id)
        .filter(UserEntity.entity_id == entity_id, UserEntity.approved)
        .order_by(User.first_name, User.last_name, User.email)
        .all()
    )
    payer_id = sub_store.payer_for_entity(entity_id)
    can_assign = has_permission(user, Permission.USER_ROLE_ASSIGN, entity_id)
    can_delete = has_permission(user, Permission.USER_ROLE_DELETE, entity_id)
    can_invite = has_permission(user, Permission.USER_INVITE, entity_id)

    def member(row, role) -> dict:
        role = _value(role)
        may_touch = can_manage_role_assignment_for_entity(user, role, entity_id)
        return {
            "id": str(row.id),
            "first_name": row.first_name or "",
            "last_name": row.last_name or "",
            "email": row.email or row.username or "",
            "initials": profile.initials(row),
            "role": role,
            "role_label": entity_role_label(role),
            "subscriber": payer_id is not None and str(payer_id) == str(row.id),
            "is_you": str(row.id) == str(user.id),
            "can_change_role": can_assign and may_touch,
            "can_remove": can_delete and may_touch,
        }

    def invitation(inv) -> dict:
        role = _value(inv.role)
        return {
            "id": str(inv.id),
            "email": inv.email,
            "first_name": inv.first_name or "",
            "last_name": inv.last_name or "",
            "role": role,
            "role_label": entity_role_label(role),
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "resend_cooldown": resend_cooldown_remaining(inv),
            "can_manage": can_invite and can_manage_role_assignment_for_entity(user, role, entity_id),
        }

    return {
        "company": {"id": str(org.id), "name": org.name},
        "modules": _modules(entity_id),
        "members": [member(row, role) for row, role in members],
        "invitations": [invitation(inv) for inv in get_pending_invitations(entity_id)],
        "roles": _roles_for(user, entity_id),
        "can_invite": can_invite,
    }


@entity_bp.route("/api/me/company/users", methods=["GET", "OPTIONS"])
def hub_company_users():
    early, user, entity_id = _open(Permission.USER_VIEW_ALL, "You don't have permission to see this company's users.")
    if early is not None:
        return early
    return hub_api.respond({**_users_page(user, entity_id), "notices": read_notices(request.args.get("flash"))})


@entity_bp.route("/api/me/company/invitations", methods=["POST", "OPTIONS"])
def hub_company_invite():
    early, user, entity_id = _open(Permission.USER_INVITE, "You don't have permission to invite people to this company.")
    if early is not None:
        return early
    from blueprints.invitation.services.invite import create_invitation, send_invitation_email

    data = _body()
    email = str(data.get("email") or "").strip().lower()
    role = str(data.get("role") or "").strip().lower()
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()

    address_error = invite_address_error(email) if email else "I need an email address to send the invitation to."
    if address_error:
        return hub_api.refuse(address_error, 400)
    if role not in _ROLE_VALUES:
        return hub_api.refuse("Pick one of the roles offered.", 400)
    # A new invitee's account is made from these names when they sign in by code.
    if not first_name or not last_name:
        return hub_api.refuse("I need their first and last name.", 400)
    if len(first_name) > 100 or len(last_name) > 100:
        return hub_api.refuse("Please keep each name to 100 characters or fewer.", 400)
    if not can_manage_role_assignment_for_entity(user, role, entity_id):
        return hub_api.refuse("I can't let you give someone a role above your own.", 403)

    invitation, error = create_invitation(
        entity_id=entity_id,
        email=email,
        role=role,
        invited_by=user.id,
        first_name=first_name,
        last_name=last_name,
    )
    if error:
        logger.info(f"hub invitation refused actor={user.id} entity={entity_id} reason={error!r}")
        return hub_api.refuse(error, 409)
    email_sent = send_invitation_email(invitation, first_name=first_name, last_name=last_name)
    logger.info(f"hub invitation sent actor={user.id} entity={entity_id} invitation={invitation.id} email_sent={email_sent}")
    return hub_api.respond(
        {
            "invitation_id": str(invitation.id),
            "email_sent": email_sent,
            "message": "Invitation sent." if email_sent else "The invitation is saved, but its email didn't go out - try Resend.",
        },
        201,
    )


def _invitation_to_manage(user, entity_id, invitation_id, verb: str):
    """``(early, invitation)``: a pending invitation OF THIS COMPANY that this person may manage."""
    from blueprints.invitation.models.invitation import Invitation
    from models.db import db

    try:
        uuid.UUID(str(invitation_id))
    except ValueError:
        return hub_api.refuse("Hmm, I couldn't find that invitation.", 404), None
    inv = db.session.get(Invitation, invitation_id)
    if inv is None or str(inv.entity_id) != entity_id:
        return hub_api.refuse("Hmm, I couldn't find that invitation.", 404), None
    if not can_manage_role_assignment_for_entity(user, _value(inv.role), entity_id):
        return hub_api.refuse(f"I can't let you {verb} an invitation for a role above your own.", 403), None
    return None, inv


@entity_bp.route("/api/me/company/invitations/<invitation_id>/cancel", methods=["POST", "OPTIONS"])
def hub_company_invitation_cancel(invitation_id):
    early, user, entity_id = _open(Permission.USER_INVITE, "You don't have permission to manage this company's invitations.")
    if early is not None:
        return early
    early, inv = _invitation_to_manage(user, entity_id, invitation_id, "cancel")
    if early is not None:
        return early
    from blueprints.invitation.services.invite import cancel_invitation

    ok, error = cancel_invitation(inv.id)
    if not ok:
        return hub_api.refuse(error or _SAVE_FAILED, 400)
    logger.info(f"hub invitation cancelled actor={user.id} entity={entity_id} invitation={inv.id}")
    return hub_api.respond({"message": "Invitation cancelled."})


@entity_bp.route("/api/me/company/invitations/<invitation_id>/resend", methods=["POST", "OPTIONS"])
def hub_company_invitation_resend(invitation_id):
    early, user, entity_id = _open(Permission.USER_INVITE, "You don't have permission to manage this company's invitations.")
    if early is not None:
        return early
    early, inv = _invitation_to_manage(user, entity_id, invitation_id, "resend")
    if early is not None:
        return early
    from blueprints.invitation.services.invite import (resend_cooldown_remaining, resend_invitation,
                                                       send_invitation_email)

    inv, error, retry_after = resend_invitation(inv.id, actor_id=user.id)
    if error:
        # A live cooldown is a rate limit, not a bad request; the page counts it down.
        status = 429 if retry_after > 0 else 400
        return hub_api.respond({"error": error, "retry_after": retry_after}, status)
    email_sent = send_invitation_email(inv)
    if not email_sent:
        # The token rotated already: the old link is dead and the new one did not go out.
        logger.error(f"hub invitation resend: email failed invitation={inv.id} entity={entity_id}")
        return hub_api.respond(
            {"error": "I couldn't send that email just now. Mind trying again in a moment?",
             "retry_after": resend_cooldown_remaining(inv)},
            502,
        )
    return hub_api.respond({"message": "Invitation sent again.", "resend_cooldown": resend_cooldown_remaining(inv)})


@entity_bp.route("/api/me/company/users/<member_id>", methods=["PATCH", "DELETE", "OPTIONS"])
def hub_company_member(member_id):
    from blueprints.user_management.services.roles import (check_can_manage_membership_or_error,
                                                           check_not_last_admin_or_error,
                                                           check_not_pending_subscriber_or_error,
                                                           check_not_subscription_payer_or_error,
                                                           check_role_assignment_or_error,
                                                           check_role_change_or_error,
                                                           find_membership_or_error)
    from models.db import UserEntity, db

    removing = request.method == "DELETE"
    early, user, entity_id = _open(
        Permission.USER_ROLE_DELETE if removing else Permission.USER_ROLE_ASSIGN,
        "You don't have permission to remove people from this company."
        if removing
        else "You don't have permission to change roles in this company.",
    )
    if early is not None:
        return early
    try:
        uuid.UUID(str(member_id))
    except ValueError:
        return hub_api.refuse("I couldn't find that person on this entity.", 404)
    membership, error = find_membership_or_error(member_id, entity_id, model=UserEntity)
    if error is not None:
        return _refusal(error)
    current_role = _value(membership.role)

    if removing:
        # In this order: may you touch this person at all, then what deleting would break -
        # the payer's card, the last admin, a handover offered to them.
        for check in (
            lambda: check_can_manage_membership_or_error(
                current_role, entity_id, user=user, policy=can_manage_role_assignment_for_entity
            ),
            lambda: check_not_subscription_payer_or_error(member_id, entity_id),
            lambda: check_not_last_admin_or_error(current_role, member_id, entity_id, model=UserEntity),
            lambda: check_not_pending_subscriber_or_error(member_id, entity_id),
        ):
            error = check()
            if error is not None:
                return _refusal(error)
        db.session.delete(membership)
        db.session.commit()
        logger.info(f"hub member removed actor={user.id} entity={entity_id} member={member_id}")
        return hub_api.respond({"message": "Removed from the company."})

    new_role = str(_body().get("role") or "").strip().lower()
    if new_role not in _ROLE_VALUES:
        return hub_api.refuse("Pick one of the roles offered.", 400)
    for check in (
        lambda: check_role_assignment_or_error(new_role, entity_id, user=user, policy=can_manage_role_assignment_for_entity),
        lambda: check_can_manage_membership_or_error(
            current_role, entity_id, user=user, policy=can_manage_role_assignment_for_entity
        ),
        # Losing admin breaks what removal breaks: the payer and the last admin stay admins.
        lambda: check_role_change_or_error(current_role, new_role, member_id, entity_id, model=UserEntity),
    ):
        error = check()
        if error is not None:
            return _refusal(error)
    membership.role = new_role
    db.session.commit()
    logger.info(f"hub member role changed actor={user.id} entity={entity_id} member={member_id} role={new_role}")
    return hub_api.respond({"message": "Role saved.", "role": new_role, "role_label": entity_role_label(new_role)})


# --- Entity & Integration -------------------------------------------------------------------------


def _integration_page(user, entity_id) -> dict:
    from blueprints.entity.services.country_currency import country_currency_choices
    from blueprints.xero.services.settings import sync_entity_xero_status
    from services.helpers.xero_bridge import get_xero_data_dynamic
    from models.db import Entity, db
    from services.auth.token_service import resolve_xero_token

    org = db.session.get(Entity, entity_id)
    token_resolved = bool(org.xero_org_id) and resolve_xero_token(entity_id, user) is not None
    if token_resolved:
        # The live check: a grant revoked on Xero's site can leave the token valid, so the
        # stored status is reconciled with Xero's /connections before it is shown.
        try:
            sync_entity_xero_status(entity_id)
            db.session.refresh(org)
        except Exception as exc:  # noqa: BLE001 - the stored status is shown, and this is logged
            logger.warning(f"Entity & Integration: Xero status sync failed for {entity_id}: {exc}")
        if not org.xero_tenant_name:
            try:
                found = get_xero_data_dynamic("Organisation", entity_id=entity_id) or {}
                name = ((found.get("Organisations") or [{}])[0] or {}).get("Name") if not found.get("error") else None
                if name:
                    org.xero_tenant_name = name
                    db.session.commit()
            except Exception as exc:  # noqa: BLE001 - the name is a nicety; logged
                logger.warning(f"Entity & Integration: Xero organisation name not read for {entity_id}: {exc}")

    countries, currencies, _country, _currency = country_currency_choices(org)
    connected_at = org.last_connected_at or org.created_at
    return {
        "company": {
            "id": str(org.id),
            "name": org.name,
            "country_code": org.country_code,
            "currency_id": str(org.currency_id) if org.currency_id else None,
        },
        "modules": _modules(entity_id),
        "countries": [{"code": c["country_code"], "name": c["country_name"]} for c in countries],
        "currencies": [{"id": str(c["currency_id"]), "name": c["currency_name"]} for c in currencies],
        "xero": {
            "status": org.status,
            "connected": bool(org.xero_org_id) and token_resolved and org.status == "connected",
            # Meant to be connected but no longer live: no token resolves, or Xero says revoked.
            "needs_reconnect": bool(org.xero_org_id) and (not token_resolved or org.status == "disconnected"),
            "organisation": org.xero_tenant_name if org.xero_org_id else None,
            "last_connected_at": connected_at.isoformat() if connected_at else None,
        },
        "can_edit": has_permission(user, Permission.XERO_SETTINGS_UPDATE, entity_id),
        "can_rename": has_permission(user, Permission.ENTITY_RENAME, entity_id),
    }


@entity_bp.route("/api/me/company/integration", methods=["GET", "PATCH", "OPTIONS"])
def hub_company_integration():
    if request.method == "PATCH":
        early, user, entity_id = _open(Permission.XERO_SETTINGS_UPDATE, "You don't have permission to change this company's settings.")
        if early is not None:
            return early
        refusal = _save_integration(user, entity_id, _body())
        if refusal is not None:
            return refusal
        return hub_api.respond(
            {**_integration_page(user, entity_id), "notices": [], "xero_conflict": None, "message": "Settings saved!"}
        )

    early, user, entity_id = _open(Permission.XERO_SETTINGS_VIEW, "You don't have permission to see this company's settings.")
    if early is not None:
        return early
    return hub_api.respond(
        {
            **_integration_page(user, entity_id),
            "notices": read_notices(request.args.get("flash")),
            "xero_conflict": _conflict(user, entity_id, request.args.get("xero_conflict")),
        }
    )


def _conflict(user, entity_id, token: str | None) -> dict | None:
    """The company holding the Xero organisation this company's connect was refused for,
    for the tab's "move it here" dialog - or None when there is nothing to offer.

    ``read_conflict`` only proves the hand-over is ours and unexpired. Three things are
    settled HERE, against the database as it is now, because the token was signed before the
    round trip and a person can reload the tab, or edit the URL, long after:

    * the other company must still hold an organisation. Free it (here, or on its own tab)
      and a reload stops offering the move instead of failing on it.
    * it must not be this company. A token naming the company being viewed would offer to
      disconnect it from itself.
    * ``can_move`` is this person's permission on the OTHER company, re-read rather than
      trusted from the token. The release route checks it again; this only decides whether
      the button is drawn.
    """
    from blueprints.entity.services.entity_list import read_conflict
    from models.db import Entity, db

    held = read_conflict(token)
    if held is None or str(held["entity_id"]) == str(entity_id):
        return None
    other = db.session.get(Entity, held["entity_id"])
    if other is None or not other.xero_org_id:
        return None
    return {
        "entity_id": str(other.id),
        "entity_name": other.name,
        "organisation": other.xero_tenant_name or None,
        "can_move": has_permission(user, Permission.XERO_SETTINGS_UPDATE, other.id),
    }


def _save_integration(user, entity_id, data: dict):
    """The name (``ENTITY_RENAME``: admins), the country and the currency. An unknown country
    or currency is refused, not skipped; an explicit currency wins, and a country alone
    brings its own (``apply_country_currency_selection``)."""
    from blueprints.entity.services.xero_account_mapping_post import apply_country_currency_selection
    from models.db import CountryInfo, CurrencyInfo, Entity, db

    org = db.session.get(Entity, entity_id)
    fields = {}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if name != (org.name or ""):
            if not has_permission(user, Permission.ENTITY_RENAME, entity_id):
                return hub_api.refuse("Only an admin can rename the company.", 403)
            if not name:
                return hub_api.refuse("I need a name for this entity before I can save it.", 422)
            if len(name) > 100:
                return hub_api.refuse("That name goes on a bit! Please keep it to 100 characters or fewer.", 422)
            # The same rule the Jinja page kept, case and all: exact names are unique.
            if Entity.query.filter(Entity.name == name, Entity.id != entity_id).first():
                return hub_api.refuse("Oh, someone got there first! Do you have another name in mind?", 422)
            org.name = name
    country_code = str(data.get("country_code") or "").strip().upper()
    if country_code:
        if db.session.get(CountryInfo, country_code) is None:
            return hub_api.refuse("Pick one of the countries offered.", 422)
        fields["country_code"] = country_code
    currency_id = str(data.get("currency_id") or "").strip()
    if currency_id:
        try:
            uuid.UUID(currency_id)
        except ValueError:
            return hub_api.refuse("Pick one of the currencies offered.", 422)
        if db.session.get(CurrencyInfo, currency_id) is None:
            return hub_api.refuse("Pick one of the currencies offered.", 422)
        fields["currency_id"] = currency_id
    try:
        apply_country_currency_selection(org, fields)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(f"Entity & Integration save failed entity={entity_id} actor={user.id}")
        return hub_api.refuse(_SAVE_FAILED, 500)
    logger.info(f"Entity & Integration saved entity={entity_id} actor={user.id} fields={sorted(fields) + (['name'] if 'name' in data else [])}")
    return None


@entity_bp.route("/api/me/company/xero/disconnect", methods=["POST", "OPTIONS"])
def hub_company_xero_disconnect():
    early, user, entity_id = _open(Permission.XERO_SETTINGS_UPDATE, "You don't have permission to disconnect this company from Xero.")
    if early is not None:
        return early
    from blueprints.xero.services.disconnect import disconnect_entity_from_xero

    try:
        disconnect_entity_from_xero(entity_id)
    except Exception:
        logger.exception(f"Xero disconnect failed entity={entity_id} actor={user.id}")
        # The revoke at Xero may have gone through while the local save did not.
        return hub_api.refuse(
            "I couldn't finish disconnecting this company from Xero, so it may still show as "
            "connected. Mind checking again before trying once more?",
            502,
        )
    logger.info(f"Xero disconnected entity={entity_id} actor={user.id}")
    return hub_api.respond(
        {
            **_integration_page(user, entity_id),
            "notices": [],
            "xero_conflict": None,
            "message": "You're disconnected from Xero.",
        }
    )


@entity_bp.route("/api/me/company/xero/release", methods=["POST", "OPTIONS"])
def hub_company_xero_release():
    """Free the Xero organisation held by ANOTHER company, so it can be connected here.

    The first half of the move the Entity & Integration tab offers when a connect was
    refused ("this organisation is already connected to X"): this disconnects X, and the tab
    then sends the person back through Xero's consent screen for the company they were
    connecting. Two steps, not one, because the grant the refused attempt created was handed
    back to Xero - there is no token left to reuse, and keeping one would mean storing
    somebody's Xero tokens against a connect that was refused.

    THE COMPANY FREED IS THE ONE IN THE BODY, not the ``?entity=`` the tab is showing, so it
    is authorized on its own: ``XERO_SETTINGS_UPDATE`` on the company being disconnected,
    which is the permission its own Disconnect button asks for. ``?entity=`` still has to be
    a company this person belongs to (``_open``), and the two must differ - a company does
    not release itself.

    Disconnecting is the canonical ``disconnect_entity_from_xero``: it revokes at Xero,
    clears the cached Xero data and leaves that company ``disconnected``, which is exactly
    what its own tab would have done.
    """
    early, user, entity_id = _open(
        Permission.XERO_SETTINGS_UPDATE, "You don't have permission to change this company's settings."
    )
    if early is not None:
        return early

    from blueprints.xero.services.disconnect import disconnect_entity_from_xero
    from models.db import Entity, db

    release_id = str(_body().get("entity_id") or "").strip()
    if not release_id:
        return hub_api.refuse("I need to know which company to disconnect from Xero.", 422)
    if release_id == str(entity_id):
        return hub_api.refuse("That company is the one you're connecting.", 422)
    try:
        uuid.UUID(release_id)
    except ValueError:
        return hub_api.refuse(_NO_COMPANY, 403)
    other = db.session.get(Entity, release_id)
    if other is None:
        return hub_api.refuse(_NO_COMPANY, 403)
    # The permission that counts: on the company being freed, not the one being viewed.
    if not has_permission(user, Permission.XERO_SETTINGS_UPDATE, other.id):
        return hub_api.refuse(
            f"Only an accountant or admin of \"{other.name}\" can disconnect it from Xero.", 403
        )
    if not other.xero_org_id:
        # Already free - the move can go on, so this is an answer and not a refusal.
        logger.info(f"Xero release: entity={release_id} already free actor={user.id}")
        return hub_api.respond({"message": f"\"{other.name}\" is already disconnected from Xero."})

    try:
        disconnect_entity_from_xero(other.id)
    except Exception:
        logger.exception(f"Xero release failed entity={release_id} actor={user.id}")
        return hub_api.refuse(
            f"I couldn't disconnect \"{other.name}\" from Xero, so the organisation is still "
            "in use there. Mind trying again?",
            502,
        )
    logger.info(f"Xero released entity={release_id} for={entity_id} actor={user.id}")
    return hub_api.respond({"message": f"\"{other.name}\" is disconnected from Xero."})

