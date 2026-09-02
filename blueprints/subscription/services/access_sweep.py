"""The daily access reconciler: close windows that simply elapsed.

Moved here from ``entity.services.modules``, where it sat among 2,600 lines of module-card
rendering despite being neither about the entity blueprint nor about rendering. It is
subscription work: it reads ``paid_through``, ``app_access_until`` and the phase, and it
is driven by ``daily.run_daily``, ``dunning`` and the transfer accept -- all of which live
here.

WHAT STAYED BEHIND, AND WHY IT MATTERS: ``entity.services.modules`` still exports both
names, so every importer and every ``monkeypatch.setattr`` that names that module keeps
working. The three entity-side dependencies -- ``_enabled_state``, ``set_entity_module``
and ``_notify_access_revoked`` -- are reached through the MODULE OBJECT and read at call
time, not bound at import. That is deliberate and load-bearing: the suite patches those
names on ``entity.services.modules``, and a ``from ... import`` here would capture the
real ones at import and silently ignore the patch (see CODE_CLEANSE_NOTES.md, "dependency
injection is required in this repo").

The lazy imports inside the functions are the existing house pattern and are what keeps
this module importable from ``modules`` without a cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from models.db import EntityFunction, EntityFunctionMap


def sweep_expired_module_access(payer_user_id=None) -> dict:
    """Disable modules whose access has lapsed past its grace, and END the ones that are
    over.

    ``payer_user_id`` narrows the whole pass to one billing account. The daily job runs
    unscoped; a caller that has just changed one account's entitlement — dunning, on the
    payment that clears an episode — passes its payer so the customer's access comes back
    with the payment rather than at the next nightly run.

    Nothing fires at a grace boundary — not the past-due window measured from
    ``paid_through``, and not ``app_access_until`` (a cancelled module's paid
    extension). So the access map goes stale the moment a window simply elapses, and
    this reconciles it.

    Two things go stale at that boundary, not one. Access is the obvious one. The other
    is the PHASE: ``scheduled_cancel`` and ``past_due`` describe a subscription on its
    way out, and once the date they hang on has passed it is out — so they are moved to
    ``cancelled``, which is terminal and, unlike either of them, lets the customer buy
    the module again. Without that the row reads as mid-cancellation or in-arrears
    forever and the panel keeps offering Renew or Pay now for something already ended.
    See ``checkout.terminate_lapsed_module``; trials are excluded there, because the
    trial-end job owns that transition.

    Runs the SAME sync the webhooks do, per entity, rather than reimplementing "who should
    have access" — the copy that used to live here had drifted into three bugs: it read
    the payer's views without filtering to this entity (granting siblings' modules), it
    iterated only codes that HAD a Stripe view (so a module cancelled out of a bundle —
    whose line is gone, which is the exact case this exists for — was never evaluated),
    and it ignored app-granted access (revoking live trials).

    A module with NO subscription row is revoked, not skipped. The subscription row is
    the record of truth and ``is_enabled`` only projects it, so "switched on with no row
    behind it" is precisely the state this job exists to erase — it is how an entity ends
    up inside a module whose card still offers "Start free trial". This used to `continue`
    on the grounds that a hand-enabled module was nobody's business, which meant the one
    inconsistency nothing else could repair was the one thing deliberately left alone.

    Entities still mid-onboarding are exempt: the wizard records its Step 2 selection in
    the map and only starts the trials at finalize, so between those two calls an enabled
    module with no row is expected rather than broken.

    Reconciles in BOTH directions. A module whose entitlement has come BACK — a past-due
    account that paid, a dunning episode that recovered — is switched on again, because
    nothing else does it either. Revocation used to be one-way: the sweep only looked at
    modules that were currently on, so one it turned off left its candidate set for good
    and the customer stayed locked out of a subscription still being charged for. See the
    restore branch for why that direction is deliberately narrower than this one.

    Intended to run daily (``flask subscriptions sweep-access``). Returns
    ``{"disabled": [{"entity_id", "code"}, ...], "restored": [...]}``.
    """
    from blueprints.entity.services import modules as entity_modules
    from blueprints.subscription.services import access, checkout, clock, policy
    from blueprints.subscription.services import store as sub_store

    code_set = set(entity_modules.MODULE_CODES)
    disabled: list[dict] = []
    restored: list[dict] = []
    now = clock.now()
    # One window for the whole sweep. Reading it per entity would let a mid-run edit
    # revoke access for the tail of the batch under a rule the head never saw.
    grace_days = policy.current().past_due_window_days

    entity_ids, onboarding_ids = _sweep_scope(payer_user_id, sub_store)

    for entity_id in entity_ids:
        if entity_id in onboarding_ids:
            continue
        try:
            rows = {
                row.function_code.upper(): row
                for row in sub_store.module_rows_for_entity(entity_id)
            }
            # The date access is measured against lives on the CARD this company is
            # billed on — not on the rows, which drift apart between entities, and no
            # longer on the account, which cannot answer for two cards at once.
            payer_id = next(
                (r.payer_user_id for r in rows.values() if r.payer_user_id), None
            )
            paid_through = (
                sub_store.paid_through_for_entity(entity_id) if payer_id else None
            )
            enabled = entity_modules._enabled_state(entity_id)
            for code in code_set:
                row = rows.get(code)
                if not enabled.get(code):
                    # Switched off while the subscription still entitles it. Restoring
                    # is deliberately narrower than revoking: only a BILLED module, and
                    # only on the same ``grants_access`` predicate that took it away.
                    #
                    # Requiring a row keeps the guarantee that access is a projection of
                    # a subscription — a flag with nothing behind it is still revoked
                    # above and is never invented here. Requiring the module to be BILLED
                    # is what keeps this from fighting the customer: a paid module cannot
                    # be switched off by hand at all (``set_entity_module`` refuses it),
                    # so an off flag on one can only have come from this sweep. A trial
                    # IS freely toggleable, so re-enabling one would silently overturn a
                    # deliberate choice — and a live trial never loses access this way in
                    # the first place, since its date does not depend on the billing
                    # cycle. Terminal phases grant nothing and so are never restored.
                    if row is not None and access.is_paid_module(
                        phase=row.phase,
                        has_been_billed=row.first_billed_at is not None,
                    ) and access.grants_access(
                        now,
                        phase=row.phase,
                        trial_end=row.trial_end,
                        app_access_until=row.app_access_until,
                        period_end=paid_through,
                        past_due_grace_days=grace_days,
                    ):
                        entity_modules.set_entity_module(
                            entity_id, code, True, actor="subscription"
                        )
                        restored.append({"entity_id": entity_id, "code": code})
                    continue
                # Switched on with nothing behind it — never subscribed, or a row
                # deleted out from under the flag. Access is a projection; with no
                # row to project, it comes off.
                if row is None:
                    entity_modules.set_entity_module(
                        entity_id, code, False, actor="subscription"
                    )
                    disabled.append(
                        {"entity_id": entity_id, "code": code, "payer_user_id": payer_id}
                    )
                    continue
                if access.grants_access(
                    now,
                    phase=row.phase,
                    trial_end=row.trial_end,
                    app_access_until=row.app_access_until,
                    period_end=paid_through,
                    past_due_grace_days=grace_days,
                ):
                    continue
                # Access has lapsed — a trial that ended, a cancellation past its
                # extension, or a past-due account past its grace. Nothing else closes
                # the gate: the boundary is a DATE, and no event fires when a date passes.
                entity_modules.set_entity_module(
                    entity_id, code, False, actor="subscription"
                )
                # The same date ENDS the subscription, so the phase has to say so too.
                # Revoking access while leaving the row on scheduled_cancel / past_due
                # left a module nobody could use still offering Renew or Pay now for
                # something already over. A trial is left alone — the trial-end job owns
                # that transition (see checkout.terminate_lapsed_module).
                checkout.terminate_lapsed_module(row)
                disabled.append(
                    {"entity_id": entity_id, "code": code, "payer_user_id": payer_id}
                )
        except Exception:
            logger.exception("modules: access sweep failed for entity {}", entity_id)
            continue

    # After the whole sweep. A revocation the customer is not told about is how someone
    # discovers their subscription lapsed by being bounced to an Access Denied page.
    entity_modules._notify_access_revoked(disabled)
    # ``payer_user_id`` is scaffolding for addressing the email, not part of what this
    # reports. Dropped so the documented return shape is unchanged by notification
    # having been bolted on.
    for item in disabled:
        item.pop("payer_user_id", None)
    # Restorations are deliberately NOT mailed. The customer is told by the thing that
    # caused them — the dunning "you're all settled" notice, the receipt for the payment
    # that cleared the balance — and a second "your access is back" for the same event
    # reads as a system talking to itself. A revocation has no such owner, which is why
    # that one does send.
    return {"disabled": disabled, "restored": restored}


def _notify_access_revoked(disabled: list[dict]) -> None:
    """Tell each payer which modules were switched off. Never raises — see ``notify``.

    One email per entity, listing every module it lost, rather than one per module: the
    customer lost access to a company, not to two rows.

    A trial that ended has ALREADY been mailed by ``convert_or_expire_due_trials``, which
    revokes access itself — so by the time this sweep runs those modules are no longer
    enabled and never reach this list. That ordering is what keeps the two jobs from
    double-notifying, and is why ``close-trials`` is documented to run first.
    """
    if not disabled:
        return
    from blueprints.entity.services import modules as entity_modules
    from blueprints.subscription.services import notify

    now = datetime.now(timezone.utc)
    by_entity: dict[str, dict] = {}
    for item in disabled:
        payer = item.get("payer_user_id")
        if not payer:
            # Nothing was ever subscribed for this entity, so there is no payer to tell.
            continue
        bucket = by_entity.setdefault(
            str(item["entity_id"]), {"payer": payer, "codes": []}
        )
        bucket["codes"].append(item["code"])

    names = entity_modules._entity_names_for_sweep(set(by_entity))
    events = [
        (
            bucket["payer"],
            notify.ACCESS_REVOKED,
            # Date-stamped so an entity that resubscribes and lapses again months later
            # is notified again rather than deduping against the first lapse.
            f"{entity_id}:{','.join(sorted(bucket['codes']))}:{now:%Y-%m-%d}",
            {
                "entity_id": entity_id,
                "entity_name": names.get(entity_id),
                "codes": sorted(bucket["codes"]),
            },
        )
        for entity_id, bucket in by_entity.items()
    ]
    notify.notify_many(events)


def _sweep_scope(payer_user_id, sub_store):
    """Which entities this sweep looks at: ``(entity_ids, onboarding_ids)``.

    Kept together because the two populations only make sense as a pair -- see the
    comment below for why a one-way candidate set turned the sweep into a ratchet that
    could revoke access and never give it back.

    Imports at call time like the caller does: the suite patches ``MODULE_CODES`` on
    ``entity.services.modules``, and binding it at import would ignore that.
    """
    from blueprints.entity.services import modules as entity_modules
    from models.db import Entity

    # Two populations, because this reconciles in BOTH directions.
    #
    # Entities with a module switched on are the only ones that could need switching
    # off. On its own that set made the sweep a one-way ratchet: a module revoked here
    # left the candidate set permanently, so nothing could ever switch it back on — and
    # nothing else does. An account that went past due, then paid, stayed locked out of
    # a subscription it was being charged for, which is precisely the recovery dunning
    # exists to deliver. So entities holding a BILLED module are candidates too, however
    # their access flag currently reads.
    module_fn_ids = [
        fn.id
        for fn in EntityFunction.query.filter(
            EntityFunction.function_code.in_(entity_modules.MODULE_CODES)
        ).all()
    ]
    entity_ids = (
        {
            row.entity_id
            for row in EntityFunctionMap.query.filter(
                EntityFunctionMap.entity_function_id.in_(module_fn_ids),
                EntityFunctionMap.is_enabled.is_(True),
            ).all()
        }
        if module_fn_ids
        else set()
    )
    if payer_user_id is None:
        entity_ids |= sub_store.entity_ids_with_billed_modules()
    else:
        mine = {
            str(row.entity_id)
            for row in sub_store.module_rows_for_payer(payer_user_id)
        }
        entity_ids = (entity_ids & mine) | sub_store.entity_ids_with_billed_modules(
            payer_user_id
        )

    # Mid-onboarding entities are exempt (see docstring). Resolved in ONE query up
    # front rather than per entity, so a long sweep can't straddle a finalize and
    # judge the head of the batch by a different rule than the tail. Unfiltered by
    # entity_ids on purpose: the set of in-flight onboardings is small, and an IN
    # clause over every enabled entity is the part that would not scale.
    onboarding_ids = {
        row.id
        for row in Entity.query.filter(Entity.status == "onboarding")
        .with_entities(Entity.id)
        .all()
    }
    return entity_ids, onboarding_ids
