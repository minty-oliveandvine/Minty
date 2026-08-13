from __future__ import annotations

from flask import Response, jsonify
from flask_login import current_user

from models.db import UserEntity
from models.user_management import Roles
from services.permission_policy import (Role, can_manage_role_assignment_for_entity,
                                        role_at_least)


def get_all_roles():
    return Roles.query.all()


def find_membership_or_error(
    user_id: str, entity_id: str, *, model: type[UserEntity] | None = None
) -> tuple[UserEntity | None, tuple[Response, int] | None]:
    """Look up a user's membership on an entity.

    Returns ``(membership, None)`` on success, or ``(None, error_response)``
    with a 404 JSON body when no membership exists.

    ``model`` lets callers pass their own module-level ``UserEntity`` binding so
    it stays the object tests patch on the calling module.
    """
    membership_model = model if model is not None else UserEntity
    membership = membership_model.query.filter_by(
        user_id=user_id, entity_id=entity_id
    ).first()
    if not membership:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't find that person on this entity.",
                }
            ),
            404,
        )
    return membership, None


def check_role_assignment_or_error(
    role: str, entity_id: str, *, user=None, policy=None
) -> tuple[Response, int] | None:
    """Ensure the current user may assign ``role`` on ``entity_id``.

    Returns ``None`` when allowed, otherwise a 403 JSON error response.
    """
    actor = user if user is not None else current_user
    check = policy if policy is not None else can_manage_role_assignment_for_entity
    if not check(actor, role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I can't let you give someone a role above your own.",
                }
            ),
            403,
        )
    return None


def check_not_subscription_payer_or_error(
    user_id: str, entity_id: str, *, payer_lookup=None
) -> tuple[Response, int] | None:
    """Refuse to remove the person whose card pays for this entity.

    The payer is recorded on the SUBSCRIPTION rows (``EntityModuleSubscription``), not on
    the membership, so deleting a ``user_entity`` row does not move it — it strands it.
    What that leaves is unrecoverable from inside the app: ``may_manage_subscription``
    refuses every remaining admin, because a payer exists and is not them; and the payer
    themselves can no longer reach the page, because ``has_entity_access`` needs the
    membership that was just deleted. Nobody can cancel, renew or fix billing, and the
    renewals keep charging the card.

    So the subscription has to be moved FIRST. This is the same invariant the module
    settings page states when it names the payer — here it is enforced on the way out.

    ``payer_lookup`` is injectable so this stays testable without the subscription model
    graph; the import is lazy for the same reason ``require_subscription_payer`` defers
    it — user_management is imported early.
    """
    if payer_lookup is None:
        from blueprints.subscription.services import store as sub_store

        payer_lookup = sub_store.payer_for_entity

    payer = payer_lookup(entity_id)
    if payer is None or str(payer) != str(user_id):
        return None
    return (
        jsonify(
            {
                "status": "error",
                "message": (
                    "I can't remove the person who pays for this company. "
                    "Move the subscription to someone else first."
                ),
            }
        ),
        409,
    )


def check_role_change_or_error(
    membership_role: str,
    new_role: str,
    user_id: str,
    entity_id: str,
    *,
    model=None,
    payer_lookup=None,
) -> tuple[Response, int] | None:
    """Both invariants a DEMOTION out of admin can break — the same two that removal can.

    A role change reaches every state a removal does, so guarding only the DELETE left the
    guards trivially bypassable: demote yourself to cashier, then delete the cashier. Both
    checks below are the delete's, asked of the role someone is about to stop having.

    Only fires on the way DOWN out of admin. A promotion is how both states are repaired,
    and a payer who is already below admin is in the broken state — refusing to change
    their role would freeze it rather than fix it.
    """
    leaving_admin = role_at_least(membership_role, Role.ADMIN.value) and not role_at_least(
        new_role, Role.ADMIN.value
    )
    if not leaving_admin:
        return None

    # The payer must keep the rank that lets them spend their own money. Demoting them
    # produces the deadlock the module settings page cannot express: MODULE_MANAGE now
    # fails for the payer, may_manage_subscription fails for every other admin, and the
    # subscription can no longer be changed by anyone.
    if payer_lookup is None:
        from blueprints.subscription.services import store as sub_store

        payer_lookup = sub_store.payer_for_entity

    payer = payer_lookup(entity_id)
    if payer is not None and str(payer) == str(user_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "I can't take admin away from the person who pays for this "
                        "company. Move the subscription to someone else first."
                    ),
                }
            ),
            409,
        )

    return check_not_last_admin_or_error(
        membership_role, user_id, entity_id, model=model, action="demote"
    )


def check_not_last_admin_or_error(
    membership_role: str, user_id: str, entity_id: str, *, model=None,
    action: str = "remove",
) -> tuple[Response, int] | None:
    """Refuse to remove an entity's only admin.

    ``ENTITY_RENAME``, ``ENTITY_DELETE`` and ``MODULE_MANAGE`` all require admin rank, so
    an entity with no admin cannot be administered, renamed, deleted, or have its modules
    changed — and no one inside the entity can grant the role back, because assigning it
    needs someone who already outranks it. Only a superuser could unstick it.

    Guarded on the TARGET's rank first, and that ordering matters: on an entity that has
    somehow already lost its admins, counting alone would refuse to remove a cashier too
    — turning one broken invariant into a frozen user list.

    Counts APPROVED memberships only, matching every other read of this table: an
    unapproved row is not yet somebody who can act.

    ``action`` is the verb in the message — "remove" for a deletion, "demote" when the
    same last admin is about to lose the rank instead.
    """
    if not role_at_least(membership_role, Role.ADMIN.value):
        return None

    membership_model = model if model is not None else UserEntity
    remaining = [
        row
        for row in membership_model.query.filter_by(entity_id=entity_id).all()
        if str(getattr(row, "user_id", "")) != str(user_id)
        and getattr(row, "approved", True)
        and role_at_least(getattr(row, "role", None), Role.ADMIN.value)
    ]
    if remaining:
        return None
    return (
        jsonify(
            {
                "status": "error",
                "message": (
                    f"I can't {action} the only admin — this company would have nobody "
                    "who can manage it. Make someone else an admin first."
                ),
            }
        ),
        409,
    )


def check_can_manage_membership_or_error(
    membership_role: str, entity_id: str, *, user=None, policy=None
) -> tuple[Response, int] | None:
    """Ensure the current user outranks ``membership_role`` on ``entity_id``.

    Returns ``None`` when allowed, otherwise a 403 JSON error response.
    """
    actor = user if user is not None else current_user
    check = policy if policy is not None else can_manage_role_assignment_for_entity
    if not check(actor, membership_role, entity_id):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "I can't let you manage someone whose role matches "
                        "or outranks your own."
                    ),
                }
            ),
            403,
        )
    return None
