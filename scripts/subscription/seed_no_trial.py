"""Seed one entity that has NEVER started a trial, so the "nothing yet" state is visible.

WHY THIS EXISTS
---------------
Every entity in the catalogue (Scenarios 2-13) already holds at least one module row, so
the state a brand-new company is actually in — both cards offering a free trial, nothing
subscribed, no billing group, no consent — could not be seen anywhere. The onboarding
wizard cannot produce it either: merely ARRIVING on step 9 finalizes the entity and opens
the trials, so a wizard-made entity is never in this state by the time you can log in.

WHAT THIS WRITES
----------------
Two rows, and deliberately nothing else:

  * ``entities`` — cloned country/currency from a catalogue entity (the dashboard formats
    money from ``currency_id`` and several settings read ``country_code``);
  * ``user_entity`` — the +catalogue payer as an approved admin, so it appears in the
    normal entity switcher.

NO ``entity_module_subscription``, NO ``entity_function_map``, NO
``entity_billing_group``, NO ``entity_billing_consent``. That absence IS the scenario:
the module gate is closed because nothing was ever granted, not because something was
revoked, and the payer is unnominated because no card has been put against this company
yet. Starting a trial from the UI is what creates all four.

It is also safe from the replay harness: ``replay_scenarios.py`` only touches entities
whose NAME appears in a run's scenario list, and this name is in no run.

RESETTING IT
------------
Testing the page STARTS trials, and there is no route back: nothing in the product
un-starts a module, and a cancelled or expired trial is a different scenario (7 and 11
already hold those). ``--reset`` therefore deletes rather than rewrites — the four tables
above, plus any e-mail-log rows keyed to this entity. Those last ones matter: the log
exists so a send happens once and the row is claimed BEFORE the mail goes out, so a row
left behind SILENTLY suppresses the next run's trial notice.

Usage:
    python scripts/subscription/seed_no_trial.py            # create (idempotent)
    python scripts/subscription/seed_no_trial.py --reset    # back to nothing-started
    python scripts/subscription/seed_no_trial.py --remove   # drop the membership
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from main import app  # noqa: E402

# The existing catalogue payer — this scenario has no money in it at all, so unlike
# Scenario 13 it needs no isolated payer: there is no paid_through, anchor or dunning
# state on the account that a shared login could disturb.
OWNER_ID = "88888888-9999-0000-1111-222222222222"  # angelika.tardaguela+catalogue
OWNER_EMAIL = "angelika.tardaguela+catalogue@oliveandvinehk.com"

ENTITY_NAME = "Scenario 14 - No Trial Started"

# PER DATABASE — a rebuild reseeds the catalogue with fresh uuids. Falls back to HK/NULL
# (what every catalogue entity carries today) when the id is stale.
CLONE_FROM = "4a42a915-94af-49b1-bd56-5cf9665e3638"  # Ang - Scenario 8 - Both Active


def seed() -> None:
    from models.db import Entity, User, UserEntity, db

    with app.app_context():
        owner = User.query.get(OWNER_ID)
        if owner is None:
            raise SystemExit(
                "payer %s (%s) is not in this database — refresh OWNER_ID"
                % (OWNER_ID, OWNER_EMAIL)
            )

        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            template = Entity.query.get(CLONE_FROM)
            entity = Entity(
                id=str(uuid.uuid4()), name=ENTITY_NAME, status="disconnected",
                country_code=template.country_code if template else "HK",
                currency_id=template.currency_id if template else None,
            )
            db.session.add(entity)
            db.session.commit()
            print("created entity %s" % entity.id)
        else:
            print("entity exists %s" % entity.id)

        if not UserEntity.query.filter_by(
            user_id=OWNER_ID, entity_id=entity.id
        ).first():
            db.session.add(UserEntity(
                user_id=OWNER_ID, entity_id=entity.id, role="admin",
                approved=True, joined_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
            ))
            db.session.commit()
            print("  +membership %s (admin)" % OWNER_ID[:8])

        _report(entity.id)


def _report(entity_id: str) -> None:
    """Prove the state rather than assume it: every card must be unsubscribed, and the
    four tables that a started trial writes must be empty for this entity."""
    from blueprints.entity.services.modules import (build_subscription_notices,
                                                    get_module_cards)
    from blueprints.subscription.models.entity_billing_consent import \
        EntityBillingConsent
    from blueprints.subscription.models.entity_billing_group import \
        EntityBillingGroup
    from blueprints.subscription.models.entity_module_subscription import \
        EntityModuleSubscription
    from models.db import EntityFunctionMap

    for card in get_module_cards(entity_id):
        print("  card %-15s status=%s trial_eligible=%s access_end=%s" % (
            card.get("code"), card.get("subscription_status"),
            card.get("trial_eligible"), card.get("access_end_long")))

    for label, model in (
        ("module rows", EntityModuleSubscription),
        ("function map", EntityFunctionMap),
        ("billing group", EntityBillingGroup),
        ("billing consent", EntityBillingConsent),
    ):
        print("  %-15s rows=%s"
              % (label, model.query.filter_by(entity_id=entity_id).count()))

    notice = build_subscription_notices(entity_id, OWNER_ID)
    print("  modal: can_manage=%s severity=%s items=%s"
          % (notice["can_manage"], notice["severity"], len(notice["items"])))
    for item in notice["items"]:
        print("    [%s] %s :: %s"
              % (item["severity"], item["title"], item["detail"]))


def reset() -> None:
    """Rewind a tested entity to nothing-started. Keeps the entity and its membership.

    Deletes, and does not rewrite, for one reason: this scenario IS the absence of rows.
    A module row set back to some "none" phase is still a module that was once held, and
    ``get_module_cards`` reads the ROW, not the phase, to decide whether the card has
    history to show.

    The payer's ``payer_billing_group`` is deliberately left alone — it is the card and
    the cycle, shared with every other entity on that account. Only this entity's
    nomination goes.
    """
    from blueprints.subscription.models.entity_billing_consent import \
        EntityBillingConsent
    from blueprints.subscription.models.entity_billing_group import \
        EntityBillingGroup
    from blueprints.subscription.models.entity_module_subscription import \
        EntityModuleSubscription
    from blueprints.subscription.models.subscription_audit_log import \
        SubscriptionAuditLog
    from blueprints.subscription.models.subscription_email_log import \
        SubscriptionEmailLog
    from models.db import Entity, EntityFunctionMap, db

    with app.app_context():
        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            print("nothing to reset — entity %r is not here" % ENTITY_NAME)
            return

        for label, model in (
            ("module rows", EntityModuleSubscription),
            ("function map", EntityFunctionMap),
            ("billing group", EntityBillingGroup),
            ("billing consent", EntityBillingConsent),
            ("audit log", SubscriptionAuditLog),
        ):
            gone = model.query.filter_by(entity_id=entity.id).delete()
            if gone:
                print("  -%s %s" % (gone, label))

        # The log has no entity_id: the dedupe key carries it. LIKE on the key is the
        # only handle, and it is safe here because the key is built from the uuid.
        mail = SubscriptionEmailLog.query.filter(
            SubscriptionEmailLog.dedupe_key.like("%%%s%%" % entity.id)
        ).delete(synchronize_session=False)
        if mail:
            print("  -%s e-mail log row(s)" % mail)

        db.session.commit()
        print("reset entity %s" % entity.id)
        _report(entity.id)


def remove() -> None:
    """Drop the membership. The ENTITY is kept: deleting one cascades into
    ``invitations``, a table that cannot even be loaded here."""
    from models.db import Entity, UserEntity, db

    with app.app_context():
        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            print("nothing to remove")
            return
        members = UserEntity.query.filter_by(entity_id=entity.id).delete()
        db.session.commit()
        print("removed %s membership(s); entity %s kept" % (members, entity.id))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.remove:
        remove()
    elif args.reset:
        reset()
    else:
        seed()
