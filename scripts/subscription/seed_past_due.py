"""Seed one entity sitting in PAST DUE, so the critical dashboard notice is visible.

WHY THIS EXISTS
---------------
``past_due`` is the only ``critical`` item ``build_subscription_notices`` can produce, and
no seeded scenario holds it: on 2026-08-18 the dev database had 24 trial / 22 active /
13 expired / 12 scheduled_cancel / 9 cancelled module rows and not one past_due. The
dashboard's red "Action needed" modal therefore could not be seen anywhere.

WHAT THIS IS NOT
----------------
This writes the END STATE only — no Stripe customer, no card, no open invoice, no test
clock. That is a deliberate, and LIMITED, choice:

  * ``dunning.collect_due`` keys on the payer's OPEN INVOICE. A past-due phase with no
    invoice behind it reads as "settled elsewhere", so a daily run will silently RECOVER
    this account and the scenario evaporates. That has happened before. Treat this entity
    as a screenshot of a state, not as a dunning fixture — do not run the daily jobs
    against this payer and expect it to survive.
  * The payer has no ``user_stripe_customer`` row at all, so ``paid_through`` and the
    anchor are absent. ``app_access_until`` is therefore written EXPLICITLY here: it is
    what the notice's deadline is read from, and nothing else would derive it.

For a faithful arrears account with real invoices and retry history, add a shape to
``replay_scenarios.py`` anchored so its failing renewal falls a few days back.

ITS OWN PAYER, NOT YOURS
------------------------
``paid_through``, ``dunning_started_at`` and the anchor all live on
``user_stripe_customer`` — the PAYER, not the entity. Arrears are account-level: one bad
card revokes every entity on the account. Hanging this off an existing payer would drag
that payer's other entities into the same state, which is why the older P5 scenario was
given an isolated payer too.

Both modules are past_due for the same reason: dunning is account-level, so a real
declined renewal fails the whole account, not one module of it.

Usage:
    python scripts/subscription/seed_past_due.py            # create/refresh
    python scripts/subscription/seed_past_due.py --remove   # drop the subscription rows + membership
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from main import app  # noqa: E402

# Isolated payer. Fixed id so re-runs update rather than duplicate.
PAYER_ID = "d5d5d5d5-0000-1111-2222-333333333333"
PAYER_EMAIL = "angelika.tardaguela+pastdue@oliveandvinehk.com"
PAYER_NAME = ("Angelika", "PastDue")
PASSWORD = "ReplayScenarios!2026"  # the replay harness password, same everywhere

# Also given membership, so the entity shows up in the normal entity list without
# switching accounts. As a NON-payer this login gets the "Billing for this company is
# managed by ..." variant of the modal, with no action button — the payer login above is
# the one that sees the button.
#
# These two ids are PER DATABASE (a rebuild reseeds the catalogue with fresh uuids) and a
# stale ALSO_MEMBER fails the membership insert on user_entity's FK. Last refreshed
# 2026-09-22 for the rebuilt pettycashv3: the +catalogue payer, and its Scenario 8.
ALSO_MEMBER = "88888888-9999-0000-1111-222222222222"  # angelika.tardaguela+catalogue

ENTITY_NAME = "Scenario 13 - Past Due (Payment Failed)"
CLONE_FROM = "4a42a915-94af-49b1-bd56-5cf9665e3638"  # Ang - Scenario 8 - Both Active

# Renewal failed this many days ago. Access ends at the end of the past-due window, read
# from billing_policy rather than hard-coded: that window is tunable, and a fixture that
# disagrees with the policy is a fixture that lies.
DAYS_IN_ARREARS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed() -> None:
    from werkzeug.security import generate_password_hash

    from blueprints.subscription.constants import PHASE_PAST_DUE
    from blueprints.subscription.services import policy, store
    from blueprints.subscription.services.checkout import _set_module_access
    from models.db import Entity, User, UserEntity, db

    with app.app_context():
        user = User.query.get(PAYER_ID)
        if user is None:
            first, last = PAYER_NAME
            user = User(
                id=PAYER_ID, email=PAYER_EMAIL, username=PAYER_EMAIL,
                first_name=first, last_name=last,
                # pbkdf2, not the werkzeug default scrypt: that produces ~162 chars and
                # the password column is varchar(150).
                password=generate_password_hash(PASSWORD, method="pbkdf2:sha256"),
                system_role="normal", approved=True,
            )
            db.session.add(user)
            db.session.commit()
            print("created payer %s / %s" % (PAYER_EMAIL, PASSWORD))
        else:
            print("payer exists %s" % PAYER_EMAIL)

        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            template = Entity.query.get(CLONE_FROM)
            entity = Entity(
                id=str(uuid.uuid4()), name=ENTITY_NAME, status="disconnected",
                # Cloned, not invented: the dashboard formats money from
                # entities.currency_id and several settings read country_code.
                country_code=template.country_code if template else "HK",
                currency_id=template.currency_id if template else None,
            )
            db.session.add(entity)
            db.session.commit()
            print("created entity %s" % entity.id)
        else:
            print("entity exists %s" % entity.id)

        for user_id, role in ((PAYER_ID, "admin"), (ALSO_MEMBER, "admin")):
            if not UserEntity.query.filter_by(
                user_id=user_id, entity_id=entity.id
            ).first():
                db.session.add(UserEntity(
                    user_id=user_id, entity_id=entity.id, role=role,
                    approved=True, joined_at=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                ))
                print("  +membership %s (%s)" % (user_id[:8], role))
        db.session.commit()

        grace = policy.current().past_due_window_days
        now = _now()
        access_until = now + timedelta(days=grace - DAYS_IN_ARREARS)

        for code in ("PETTY_CASH", "PAYMENT_REQUEST"):
            store.upsert_module_row(
                entity.id, code, PAYER_ID,
                phase=PHASE_PAST_DUE,
                app_access_until=access_until,
                # It billed successfully once, a month before the failed renewal — a
                # past_due row with no first_billed_at would be a module that fell into
                # arrears without ever having been charged.
                first_billed_at=now - timedelta(days=33),
            )
            # Access stays OPEN through the past-due window; that window is the whole
            # point of the state, and of the deadline the notice prints.
            _set_module_access(entity.id, code, True)
        db.session.commit()
        print("both modules past_due, access until %s (%s-day window, %s days in arrears)"
              % (access_until.strftime("%d %b %Y"), grace, DAYS_IN_ARREARS))

        _report(entity.id)


def _report(entity_id: str) -> None:
    from blueprints.entity.services.modules import (build_subscription_notices,
                                                    get_module_cards)

    for card in get_module_cards(entity_id):
        print("  card %-11s status=%s access_end=%s" % (
            card.get("code"), card.get("subscription_status"),
            card.get("access_end_long")))
    for viewer, label in ((PAYER_ID, "payer"), (ALSO_MEMBER, "other admin")):
        notice = build_subscription_notices(entity_id, viewer)
        print("  modal as %s: can_manage=%s severity=%s"
              % (label, notice["can_manage"], notice["severity"]))
        for item in notice["items"]:
            print("    [%s] %s :: %s"
                  % (item["severity"], item["title"], item["detail"]))


def remove() -> None:
    """Drop what this script wrote. The ENTITY is kept: deleting one cascades into
    ``invitations``, a table that cannot even be loaded here."""
    from blueprints.subscription.models.entity_module_subscription import \
        EntityModuleSubscription
    from models.db import Entity, UserEntity, db

    with app.app_context():
        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            print("nothing to remove")
            return
        subs = EntityModuleSubscription.query.filter_by(entity_id=entity.id).delete()
        members = UserEntity.query.filter_by(entity_id=entity.id).delete()
        db.session.commit()
        print("removed %s subscription row(s), %s membership(s); entity %s kept"
              % (subs, members, entity.id))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    remove() if args.remove else seed()
