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
from sqlalchemy import bindparam, text

from blueprints.shared.schema import SCHEMA
from blueprints.subscription.constants import (PHASE_ACTIVE, PHASE_PAST_DUE,
                                               PHASE_SCHEDULED_CANCEL, PHASE_TRIAL,
                                               TRANSFER_OPEN_STATUSES)
from blueprints.subscription.models.billing_policy import BillingPolicy
from blueprints.subscription.models.entity_billing_group import EntityBillingGroup
from blueprints.subscription.models.entity_module_subscription import \
    EntityModuleSubscription
from blueprints.subscription.models.payer_billing_group import PayerBillingGroup
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


#: minty-subscription-api's shipped dunning schedule (``policy.DEFAULT_*``), which the
#: ``billing_policy`` row overrides only when it holds together (``policy._dunning_pair``).
DEFAULT_PAST_DUE_WINDOW_DAYS = 15
MIN_SETTLE_GAP_DAYS = 2


def _aware(value: datetime | None) -> datetime | None:
    """A stored time as an aware one (some drivers hand back naive UTC)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _past_due_window_days() -> int:
    """``policy.current().past_due_window_days``: the row's window when it and the retry
    schedule cohere (``policy._dunning_pair``), else the shipped 15 days."""
    row = BillingPolicy.query.filter_by(id=1).first()
    if row is None:
        return DEFAULT_PAST_DUE_WINDOW_DAYS
    try:
        window = int(row.past_due_window_days)
        offsets = [int(part) for part in str(row.retry_offsets_days or "").split(",") if part.strip()]
    except (TypeError, ValueError):
        logger.error("subscription reads: billing_policy's dunning settings are not numbers")
        return DEFAULT_PAST_DUE_WINDOW_DAYS
    if (
        not offsets
        or window < 1
        or any(offset <= 0 for offset in offsets)
        or offsets != sorted(set(offsets))
        or window - max(offsets) < MIN_SETTLE_GAP_DAYS
    ):
        logger.error("subscription reads: billing_policy's dunning settings are incoherent")
        return DEFAULT_PAST_DUE_WINDOW_DAYS
    return window


def _payment_failed(rows_by_entity: dict[str, list], now: datetime) -> set[str]:
    """The entities among ``rows_by_entity`` with a module whose card reads ``past_due``.

    minty-subscription-api's ``cards.get_module_cards`` - what the dashboard notice, the
    module cards and the subscriptions list all read - says ``past_due`` for a module that
    is past due, STILL GRANTS ACCESS (``access.grants_access``: until ``app_access_until``
    when one was promised, else until the company's paid-through plus the past-due window)
    and whose customer was TOLD (``dunning.told_of_failure``: the card is in dunning, or
    collection is over; a company with no card counts as told). Past due while the payment
    PROCESSOR failed was never a failed payment.

    The company's paid-through is its card's (``store.paid_through_for_entity``), moved
    later by a handover whose first charge is parked (``collect_at``). Three reads for the
    whole list, and only when something on it is past due.
    """
    past_due = {
        eid: rows for eid, rows in rows_by_entity.items()
        if any(r.phase == PHASE_PAST_DUE for r in rows)
    }
    if not past_due:
        return set()
    ids = list(past_due)
    groups = {
        (str(nomination.entity_id), str(nomination.payer_user_id)): group
        for nomination, group in EntityBillingGroup.query
        .join(PayerBillingGroup, PayerBillingGroup.id == EntityBillingGroup.billing_group_id)
        .add_entity(PayerBillingGroup)
        .filter(EntityBillingGroup.entity_id.in_(ids))
        .all()
    }
    # ``collect_at`` is in the schema but not on Flask's model: read bound and qualified.
    parked = {
        (str(entity_id), str(to_user_id)): _aware(collect_at)
        for entity_id, to_user_id, collect_at in db.session.execute(
            text(
                f"SELECT entity_id, to_user_id, MAX(collect_at) FROM {SCHEMA}.subscription_transfer"
                " WHERE entity_id IN :ids AND collect_at IS NOT NULL GROUP BY entity_id, to_user_id"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
    }
    window = timedelta(days=_past_due_window_days())

    failed = set()
    for eid, rows in past_due.items():
        # One payer per entity, from any row that names one (``payer_for_entity``).
        payer = next((str(r.payer_user_id) for r in rows if r.payer_user_id), None)
        group = groups.get((eid, payer)) if payer else None
        card_paid_through = _aware(group.paid_through) if group is not None else None
        paid_through = card_paid_through
        held = parked.get((eid, payer)) if group is not None else None
        if held is not None and (paid_through is None or held > paid_through):
            paid_through = held

        told = group is None or group.dunning_started_at is not None or (
            card_paid_through is not None and now >= card_paid_through + window
        )
        if not told:
            continue
        for row in rows:
            if row.phase != PHASE_PAST_DUE:
                continue
            promised = _aware(row.app_access_until)
            ends_at = promised if promised is not None else (
                paid_through + window if paid_through is not None else None
            )
            if ends_at is not None and ends_at > now:
                failed.add(eid)
                break
    return failed


def subscription_attention_for_entities(entity_ids: list[str]) -> dict[str, dict]:
    """What the entity list flags about each company's subscription, for the whole list in
    one read of the module rows: ``{entity_id: {"trials": {module code: when its free trial
    ends}, "payment_failed": bool}}``. A company with no module rows is absent.

    On a free trial: never billed (``first_billed_at`` is null - what separates a trial
    from a paid module winding down), running or cancelled (a cancelled trial keeps its
    free days), and not past its end - with ``TRIAL_CLOSING_WINDOW`` of slack for a running
    trial the daily pass has not closed out yet, so the badge does not blink off first. It
    ends at ``app_access_until`` (a cancelled trial's promise) before ``trial_end``.

    ``payment_failed``: see ``_payment_failed``.

    Fail-soft: any error yields no flags rather than an exception (logged). A missing flag
    costs a hint; a raise here would cost the user the whole entity list.
    """
    if not entity_ids:
        return {}
    try:
        now = _database_now()
        rows_by_entity: dict[str, list] = {}
        for row in EntityModuleSubscription.query.filter(
            EntityModuleSubscription.entity_id.in_(entity_ids)
        ).all():
            rows_by_entity.setdefault(str(row.entity_id), []).append(row)
        failed = _payment_failed(rows_by_entity, now)
    except Exception:
        # The rollback is not optional: on Postgres a failed statement aborts the whole
        # transaction, and the rest of the request would 500 several queries later.
        db.session.rollback()
        logger.exception("subscription reads: could not read subscription state for the entity list")
        return {}

    attention: dict[str, dict] = {}
    for eid, rows in rows_by_entity.items():
        trials: dict[str, datetime] = {}
        for row in rows:
            if (
                row.first_billed_at is not None
                or row.trial_end is None
                or row.phase not in (PHASE_TRIAL, PHASE_SCHEDULED_CANCEL)
            ):
                continue
            # The app's own promise (a cancelled trial's remaining days) outranks the term.
            ends_at = _aware(row.app_access_until or row.trial_end)
            if ends_at <= now and not (
                row.phase == PHASE_TRIAL and (now - ends_at) <= TRIAL_CLOSING_WINDOW
            ):
                continue
            trials[(row.function_code or "").upper()] = ends_at
        attention[eid] = {"trials": trials, "payment_failed": eid in failed}
    return attention


def trial_modules_for_entities(entity_ids: list[str]) -> dict[str, set[str]]:
    """Each entity id to the module codes currently on a FREE TRIAL, by
    ``subscription_attention_for_entities``'s rule. One read for the whole list; fail-soft."""
    return {
        eid: set(flags["trials"])
        for eid, flags in subscription_attention_for_entities(entity_ids).items()
        if flags["trials"]
    }
