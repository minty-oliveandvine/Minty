"""The subscription reads Flask still makes - read-only, and nothing else.

The subscription engine is minty-subscription-api: it is the one writer of the
subscription tables and the only service that talks to Stripe. Flask kept its copy of
the engine until 2026-10-06; what is left here are the questions the REST of Flask asks
about a company's subscription before it lets someone leave, be demoted, or switch a
module off - answered from the SQLAlchemy models, which stay for Alembic.

Nothing in this module writes, commits or calls out. A new read belongs here; a new
write belongs in minty-subscription-api.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text

from blueprints.subscription.constants import (PHASE_ACTIVE, PHASE_PAST_DUE,
                                               PHASE_SCHEDULED_CANCEL, PHASE_TRIAL,
                                               TRANSFER_OPEN_STATUSES)
from blueprints.subscription.models.entity_module_subscription import \
    EntityModuleSubscription
from blueprints.subscription.models.subscription_transfer import SubscriptionTransfer
from models.db import Entity, db

# How long after ``trial_end`` a trial the daily pass has not closed out yet still shows as
# a trial. Six hours against an hourly pass: wide enough for a missed run or a deploy, far
# too narrow to cover an environment where nothing runs at all (unbounded, every stale
# trial there would match forever).
TRIAL_CLOSING_WINDOW = timedelta(hours=6)


def payer_for_entity(entity_id) -> str | None:
    """The payer user id for an entity, from any of its rows that HAS one.

    None before the entity has a subscription or trial at all, and equally while its
    trials have no SUBSCRIBER: ``payer_user_id`` is NULL until billing is confirmed on a
    billing account, because starting a free trial commits nobody.

    One payer per entity is enforced on the engine's write, so any row that has one
    answers — but a NULL row answers nothing, and an unordered ``.first()`` would let a
    subscriber-less row speak for an entity that IS being billed.
    """
    if not entity_id:
        return None
    rows = EntityModuleSubscription.query.filter_by(entity_id=str(entity_id)).all()
    return next((r.payer_user_id for r in rows if r.payer_user_id), None)


def rows_for_entity(entity_id) -> list[EntityModuleSubscription]:
    """Every module row of one entity, whatever its phase or payer."""
    if not entity_id:
        return []
    return EntityModuleSubscription.query.filter_by(entity_id=str(entity_id)).all()


def entities_paid_for_by(user_id) -> list[tuple[str, str]]:
    """``(entity_id, name)`` for every entity whose bill this user currently carries.

    Answers "may this person leave / be deactivated?". Phase-blind on purpose: a
    cancelled or past-due row still names a payer, and a payer with an unsettled row is
    exactly the one who must not vanish. Named rather than counted, so a refusal can list
    the companies.
    """
    if not user_id:
        return []
    rows = EntityModuleSubscription.query.filter_by(
        payer_user_id=str(user_id)
    ).with_entities(EntityModuleSubscription.entity_id).all()
    ids = {str(entity_id) for (entity_id,) in rows}
    if not ids:
        return []
    named = {
        str(e.id): (e.name or "").strip() or str(e.id)
        for e in Entity.query.filter(Entity.id.in_(list(ids))).all()
    }
    # An entity row that has gone missing still counts - it is the SUBSCRIPTION that
    # strands, and dropping it here would let the payer slip out through a broken FK.
    return sorted((eid, named.get(eid, eid)) for eid in ids)


def pending_transfer_for_entity(entity_id) -> SubscriptionTransfer | None:
    """The open handover offer on this entity, if any (at most one - a partial unique
    index guarantees it)."""
    if not entity_id:
        return None
    return (
        SubscriptionTransfer.query.filter(
            SubscriptionTransfer.entity_id == str(entity_id),
            SubscriptionTransfer.status.in_(TRANSFER_OPEN_STATUSES),
        )
        .order_by(SubscriptionTransfer.created_at.desc())
        .first()
    )


def module_is_paid(entity_id, function_code) -> bool:
    """Whether this module is BILLED - which locks the manual module switch.

    Active and past-due modules are billed. ``scheduled_cancel`` is shared by a paid
    module winding down (billed: ``first_billed_at`` is set) and a cancelled trial (never
    billed, so freely switchable). Trials, cancelled and expired modules are not billed.
    """
    if not entity_id or not function_code:
        return False
    row = EntityModuleSubscription.query.filter_by(
        entity_id=str(entity_id), function_code=str(function_code).strip().upper()
    ).one_or_none()
    if row is None:
        return False
    if row.phase in (PHASE_ACTIVE, PHASE_PAST_DUE):
        return True
    return row.phase == PHASE_SCHEDULED_CANCEL and row.first_billed_at is not None


def _database_now() -> datetime:
    """The database's clock: shared by every instance, unlike the host's."""
    value = db.session.execute(text("SELECT now()")).scalar()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def trial_modules_for_entities(entity_ids: list[str]) -> dict[str, set[str]]:
    """Map each entity id to the module codes currently on a FREE TRIAL - the entity
    list's badge. One query for the whole list.

    On a free trial: never billed (``first_billed_at`` is null - what separates a trial
    from a paid module winding down), running or cancelled (a cancelled trial keeps its
    free days), and not past its end - with ``TRIAL_CLOSING_WINDOW`` of slack for a running
    trial the daily pass has not closed out yet, so the badge does not blink off first.

    Fail-soft: any error yields no badges rather than an exception (logged). A missing
    badge costs a hint; a raise here would cost the user the whole entity list.
    """
    if not entity_ids:
        return {}
    try:
        now = _database_now()
        rows = EntityModuleSubscription.query.filter(
            EntityModuleSubscription.entity_id.in_(entity_ids),
            EntityModuleSubscription.first_billed_at.is_(None),
            EntityModuleSubscription.trial_end.isnot(None),
            EntityModuleSubscription.phase.in_((PHASE_TRIAL, PHASE_SCHEDULED_CANCEL)),
        ).all()
    except Exception:
        # The rollback is not optional: on Postgres a failed statement aborts the whole
        # transaction, and the rest of the request would 500 several queries later.
        db.session.rollback()
        logger.exception("subscription reads: could not read trial state for the entity list")
        return {}

    trials: dict[str, set[str]] = {}
    for row in rows:
        # The app's own promise (a cancelled trial's remaining days) outranks the term.
        ends_at = row.app_access_until or row.trial_end
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ends_at <= now and not (
            row.phase == PHASE_TRIAL and (now - ends_at) <= TRIAL_CLOSING_WINDOW
        ):
            continue
        trials.setdefault(row.entity_id, set()).add((row.function_code or "").upper())
    return trials
