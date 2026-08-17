from __future__ import annotations

from flask import Response, jsonify
from flask_login import current_user
from loguru import logger

from models.db import User, UserEntity
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

        # "Does ANY module row of this entity name this user as payer", not
        # ``payer_for_entity``. That one answers from an unordered ``.first()``, which is
        # only unambiguous while one-payer-per-entity holds — and a transfer is the first
        # code that writes every row at once, so a half-applied flip would make the answer
        # depend on which row came back. Asking about any row makes a split state fail
        # CLOSED: the removal is refused rather than allowed on a coin toss.
        def payer_lookup(eid):
            rows = sub_store.rows_for_entity(eid)
            payers = {str(r.payer_user_id) for r in rows if r.payer_user_id}
            return str(user_id) if str(user_id) in payers else (
                next(iter(payers)) if payers else None
            )

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


def check_not_pending_subscriber_or_error(
    user_id: str, entity_id: str, *, pending_lookup=None
) -> tuple[Response, int] | None:
    """Refuse to remove or demote someone a handover is currently offered to.

    The two sides of a transfer can otherwise pass each other: the offer is validated when
    it is made and again when it is accepted, but nothing stops the nominee being taken
    off the entity in between. Accept then re-checks, refuses, and permanently cancels an
    offer the outgoing payer was relying on to get out — so the failure is silent from
    their side and only shows up as an exit that will not complete.

    Refusing the removal instead keeps the two in step: whoever wants the nominee gone
    withdraws the handover first, which is one click and says what it does.

    FAILS OPEN if the offer cannot be read. This guard is a courtesy that keeps two flows
    in step, not a safety property — accept re-validates everything regardless, so the
    worst case of not firing is the behaviour that existed before it. Blocking every
    membership change whenever the subscription tables are unreachable would be a far
    larger harm than the one it prevents.
    """
    if pending_lookup is None:
        from blueprints.subscription.services import transfers

        def pending_lookup(eid):
            offer = transfers.pending_transfer_for_entity(eid)
            return offer.to_user_id if offer is not None else None

    try:
        nominee = pending_lookup(entity_id)
    except Exception:  # noqa: BLE001 - see the docstring; open is the safe side here
        logger.warning(
            "roles: could not check for a pending handover on {}; allowing the change",
            entity_id,
        )
        return None
    if nominee is None or str(nominee) != str(user_id):
        return None
    return (
        jsonify(
            {
                "status": "error",
                "message": (
                    "This company's subscription is being handed over to them. "
                    "Cancel the handover first, then make the change."
                ),
            }
        ),
        409,
    )


def _deactivated_accounts(user_ids: list[str], *, user_model=None) -> set[str]:
    """Which of these user ids belong to accounts that can no longer sign in.

    Positive identification only: an id absent from the answer is one we could not prove
    is deactivated, NOT one we proved is live. Callers use this to discount cover, and
    discounting someone wrongly refuses an action that is fine — so the uncertain case
    has to fall on the permissive side.

    A lookup failure is therefore degraded, not raised. This runs inside guards that are
    already answering a different question, and the pure-function tests exercise them
    without a database bound at all; turning "I couldn't check" into a 500 would make the
    weaker answer unavailable rather than better.
    """
    if not user_ids:
        return set()
    account_model = user_model if user_model is not None else User
    try:
        return {
            str(found_id)
            for (found_id,) in account_model.query.filter(
                account_model.id.in_(list(user_ids)),
                account_model.approved.is_(False),
            )
            .with_entities(account_model.id)
            .all()
        }
    except Exception:  # noqa: BLE001 - see the docstring; the fallback is the safe answer
        logger.warning(
            "roles: could not check which of {} account(s) are deactivated; "
            "counting them all as live",
            len(user_ids),
        )
        return set()


def check_not_subscription_payer_anywhere_or_error(
    user_id: str, *, entities_lookup=None
) -> tuple[Response, int] | None:
    """Refuse to deactivate an account that still pays for a company.

    The account-level twin of ``check_not_subscription_payer_or_error``, and it exists
    because the membership-level guard was being walked around. ``DELETE /minty/api/users/me``
    sets ``User.approved = False`` and clears the tokens, but leaves every ``user_entity``
    row and every ``payer_user_id`` exactly where it was — so it produced precisely the
    state that guard refuses, through a different door: the payer can no longer sign in
    (``approved`` False blocks login), no remaining admin can act because
    ``may_manage_subscription`` answers only to the payer, and the renewals keep charging
    a card whose owner cannot reach the page to stop them.

    The remedy is the same one the other guard names — move the subscription first — so
    the message names the companies rather than stating a rule.

    ``entities_lookup`` is injectable, and the import is lazy, for the same reason its
    sibling does it: user_management is imported early and must not pull the subscription
    model graph in with it.
    """
    if entities_lookup is None:
        from blueprints.subscription.services import store as sub_store

        entities_lookup = sub_store.entities_paid_for_by

    entities = entities_lookup(user_id) or []
    if not entities:
        return None

    names = [name for _entity_id, name in entities]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
    return (
        jsonify(
            {
                "status": "error",
                "message": (
                    f"I can't close your account while you're paying for {listed}. "
                    "Hand the subscription to another admin first, then come back."
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
    pending_lookup=None,
) -> tuple[Response, int] | None:
    """Both invariants a DEMOTION out of admin can break — the same two that removal can.

    A role change reaches every state a removal does, so guarding only the DELETE left the
    guards trivially bypassable: demote yourself to cashier, then delete the cashier. Both
    checks below are the delete's, asked of the role someone is about to stop having.

    Only fires on the way DOWN out of admin. A promotion is how both states are repaired,
    and a payer who is already below admin is in the broken state — refusing to change
    their role would freeze it rather than fix it.

    A third check rides along for the same reason: someone a handover is offered TO must
    keep the admin rank the handover requires, or accept would refuse and cancel an offer
    the outgoing payer is relying on to get out.
    """
    leaving_admin = role_at_least(membership_role, Role.ADMIN.value) and not role_at_least(
        new_role, Role.ADMIN.value
    )
    if not leaving_admin:
        return None

    error = check_not_pending_subscriber_or_error(
        user_id, entity_id, pending_lookup=pending_lookup
    )
    if error is not None:
        return error

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
    action: str = "remove", user_model=None,
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

    Approved on BOTH levels. The membership flag says "this person has been let into
    this company"; ``User.approved`` says "this person can sign in at all", and a
    deactivated account fails the second while still passing the first. Counting only
    the membership let a deactivated admin stand as cover for a live one — so the last
    person who could actually administer the entity could be removed, and the entity
    was left with an admin who cannot reach it.

    Only accounts POSITIVELY known to be deactivated are discounted. A membership whose
    user row cannot be found is kept, because "no user row" means the question could not
    be answered here, and answering it wrongly would refuse a removal that is fine.

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
        deactivated = _deactivated_accounts(
            [str(getattr(row, "user_id", "")) for row in remaining],
            user_model=user_model,
        )
        if deactivated:
            remaining = [
                row
                for row in remaining
                if str(getattr(row, "user_id", "")) not in deactivated
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
