"""Seed two logins and one entity, set up so "Change subscriber" can be clicked through.

    python scripts/subscription/seed_transfer_demo.py
    python scripts/subscription/seed_transfer_demo.py --teardown

WHY A SEPARATE SCRIPT FROM replay_scenarios.py
``replay_scenarios`` simulates a lifecycle against a Stripe TEST CLOCK, which is the right
tool for "does the renewal bill the right amount in four months" and the wrong one here.
This seeds a single resting state — a paid-up entity with a second admin who can take it
on — and then gets out of the way so the handover is exercised by clicking it.

WHAT IT BUILDS, and why each piece has to be there. ``transfers.transfer_blockers`` refuses
a handover for six reasons, so a demo that trips any of them shows a greyed button and
proves nothing:

  * TWO USERS, both ``approved``, both APPROVED ADMINS of the entity. The bill can only be
    offered to an admin, and only an admin whose account can actually sign in.
  * A STRIPE TEST CUSTOMER AND SAVED CARD FOR EACH. The incoming payer's card is checked
    before the offer is even allowed: without one ``start_billing_cycle`` silently no-ops
    and the accept would fail at the charge having promised to succeed.
  * MODULE ROWS IN ``active``. ``--with-trial`` adds a second module on a free trial,
    which is now allowed and is worth exercising separately: the free days carry over
    untouched, the trial is NOT charged for at accept, and the accept screen has to
    disclose the charge that lands when it converts.
  * NO past-due row, no dunning, no pending cancel-extension.
  * ANCHORS ON DIFFERENT DAYS OF THE MONTH. This is the part worth setting up deliberately:
    the outgoing payer is paid up to a date, the incoming payer's cycle turns over on
    another, and the charge at accept is the window BETWEEN them. Give both the same
    anchor and the interesting arithmetic disappears.

THE MONEY IS REAL, in Stripe's test mode. Accepting raises and pays an actual test invoice,
so the amount on the accept screen can be checked against the invoice it produced.

LOCAL ONLY. ``DATABASE_URL`` may well be real Supabase in a given checkout — so this
refuses to run unless the resolved database is localhost. Seeding demo users into production is not a mistake worth leaving available.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# Dev-only. These two exist to be signed in as.
PASSWORD = "ChangeSubscriber!2026"
OUTGOING_EMAIL = "handover.from@example.com"
INCOMING_EMAIL = "handover.to@example.com"
ENTITY_NAME = "Handover Demo Ltd"
MODULE_CODES = ("PETTY_CASH",)
#: Added by ``--with-trial``. A second module still on free days, so the handover has
#: something to carry over and something to disclose.
TRIAL_CODE = "PAYMENT_REQUEST"
TRIAL_DAYS = 14
# Stripe's always-succeeds test method. A real card number never appears here.
CARD_GOOD = "pm_card_visa"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _require_local_and_test_mode(app) -> None:
    """Refuse to touch anything that is not a local database in Stripe test mode."""
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if not ("localhost" in uri or "127.0.0.1" in uri):
        sys.exit(
            "Refusing to run: the resolved database is not local.\n"
            f"  {uri.split('@')[-1] or uri}\n"
            "Re-run with DATABASE_URL pointing at a local database."
        )
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if "_test_" not in key:
        sys.exit(
            "Refusing to run: STRIPE_SECRET_KEY is not a test key. This script creates "
            "customers and pays invoices."
        )


def _user(email: str, first: str, last: str):
    from werkzeug.security import generate_password_hash

    from models.db import User, db

    user = User.query.filter_by(username=email).first()
    if user is not None:
        print(f"  user exists      {email}")
        return user
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        username=email,
        first_name=first,
        last_name=last,
        # pbkdf2, not werkzeug's scrypt default: scrypt produces ~162 chars and the
        # password column is varchar(150), so the default silently truncates.
        password=generate_password_hash(PASSWORD, method="pbkdf2:sha256"),
        system_role="normal",
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    print(f"  created user     {email}")
    return user


def _customer_with_card(user, label: str) -> str:
    """A Stripe test customer with a default card, mirrored into user_stripe_customer."""
    from blueprints.subscription.services import store
    from blueprints.subscription.services.stripe_client import get_stripe

    stripe = get_stripe()
    mapping = store.customer_mapping_for_user(user.id)
    customer_id = mapping.stripe_customer_id if mapping else None

    if customer_id:
        try:
            stripe.Customer.retrieve(customer_id)
        except Exception:
            customer_id = None

    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email, name=f"{label} (handover demo)"
        )
        customer_id = customer["id"]
        store.upsert_customer_mapping(user.id, customer_id)
        print(f"  created customer {customer_id} for {user.username}")

    # No test clock, deliberately: this is a resting state to click through, not a
    # timeline to replay, and a clock would freeze the charge at a date nobody chose.
    settings = stripe.Customer.retrieve(customer_id).get("invoice_settings") or {}
    if not settings.get("default_payment_method"):
        method = stripe.PaymentMethod.attach(CARD_GOOD, customer=customer_id)
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": method["id"]},
        )
        print(f"  attached card    {method['id']} to {customer_id}")
    return customer_id


def seed(with_trial: bool = False) -> None:
    from main import app

    with app.app_context():
        _require_local_and_test_mode(app)

        from blueprints.subscription.constants import PHASE_ACTIVE, PHASE_TRIAL
        from blueprints.subscription.services import store
        from models.db import Entity, UserEntity, db

        now = datetime.now(UTC)

        print("users")
        outgoing = _user(OUTGOING_EMAIL, "Olive", "Outgoing")
        incoming = _user(INCOMING_EMAIL, "Ivan", "Incoming")

        print("stripe")
        _customer_with_card(outgoing, "Olive Outgoing")
        _customer_with_card(incoming, "Ivan Incoming")

        print("entity")
        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        if entity is None:
            entity = Entity(
                id=str(uuid.uuid4()), name=ENTITY_NAME,
                country_code="HK", status="disconnected",
            )
            db.session.add(entity)
            db.session.commit()
            print(f"  created entity   {entity.name} ({entity.id})")
        else:
            print(f"  entity exists    {entity.name} ({entity.id})")

        # BOTH admins. The offer is only allowed to an admin, and the accept re-checks it.
        for user in (outgoing, incoming):
            if not UserEntity.query.filter_by(
                user_id=user.id, entity_id=entity.id
            ).first():
                db.session.add(UserEntity(
                    user_id=user.id, entity_id=entity.id, role="admin",
                    approved=True, joined_at=now, created_at=now,
                ))
                print(f"  admin membership {user.username}")
        db.session.commit()

        print("billing cycles")
        plan = store.billing_plan_for_codes(set(MODULE_CODES))
        currency = (plan.currency if plan else "HKD") or "HKD"

        # ANCHORS ON DIFFERENT DAYS, so the handover window is a real proration rather
        # than a whole period. Olive is paid ~18 days out; Ivan's cycle turns over ~6 days
        # after that, so accepting charges Ivan for the gap between the two.
        olive_paid_through = now + timedelta(days=18)
        olive_anchor = olive_paid_through - timedelta(days=30)
        ivan_anchor = now + timedelta(days=24) - timedelta(days=30)

        store.start_billing_cycle(outgoing.id, olive_anchor, currency)
        # ``paid_through`` lives on the CARD now, not the account: the payer-level
        # ``store.set_paid_through`` was removed with the per-entity-card cutover. This
        # script predates billing groups and does not create one, so say so loudly
        # rather than seeding a demo whose handover window is silently wrong.
        olive_groups = store.billing_groups_for_payer(outgoing.id)
        if not olive_groups:
            print("  WARNING: no billing group for Olive; paid_through not set. "
                  "Nominate a card for Olive in the app first.")
        for group in olive_groups:
            store.set_group_paid_through(group.id, olive_paid_through)
        store.start_billing_cycle(incoming.id, ivan_anchor, currency)
        print(f"  Olive paid through {olive_paid_through:%d %b %Y} (anchor {olive_anchor:%d %b})")
        print(f"  Ivan  anchor       {ivan_anchor:%d %b} -> next turnover ~{now + timedelta(days=24):%d %b %Y}")

        print("subscription")
        for code in MODULE_CODES:
            store.upsert_module_row(
                entity.id, code, outgoing.id,
                phase=PHASE_ACTIVE,
                # Set, so nothing reads this as a trial — a trial blocks the handover.
                first_billed_at=olive_anchor,
                app_access_until=None,
                trial_end=None,
                extension_state=None,
                extension_amount=None,
            )
            print(f"  {code} active, payer = {OUTGOING_EMAIL}")

        if with_trial:
            # A trial the handover carries over. Deliberately a DIFFERENT module from the
            # paid one, so the accept charges for the active module only and the trial
            # shows up purely as a disclosure — which is the distinction worth seeing.
            trial_end = now + timedelta(days=TRIAL_DAYS)
            store.upsert_module_row(
                entity.id, TRIAL_CODE, outgoing.id,
                phase=PHASE_TRIAL,
                trial_end=trial_end,
                # A trial's access runs to its own end date; it has never been billed.
                app_access_until=trial_end,
                first_billed_at=None,
            )
            print(f"  {TRIAL_CODE} on free trial until {trial_end:%d %b %Y}")

        # Olive's own consent. Ivan's is recorded by the accept — that is the point of
        # consent being per (entity, payer) rather than per entity.
        store.record_billing_consent(entity.id, outgoing.id, "confirmed")

        # Switch the module on so the entity looks live in Minty, not just in billing.
        # Through ``set_entity_module`` rather than by writing entity_function_map here:
        # that function owns the enabled/disabled bookkeeping (timestamps, the paid-
        # subscription guard, the actor trail), and ``actor="subscription"`` is the same
        # value checkout uses when a purchase grants access. Hand-writing the row would
        # reproduce a subset of it and drift.
        from blueprints.entity.services.modules import set_entity_module

        for code in MODULE_CODES:
            body, status = set_entity_module(
                entity.id, code, True, actor="subscription"
            )
            print(
                f"  module access    {code} enabled"
                if status == 200
                else f"  module access    {code} NOT enabled: {body}"
            )

        from blueprints.subscription.services import transfers

        blockers = transfers.transfer_blockers(
            entity.id, from_user_id=outgoing.id, to_user_id=incoming.id
        )
        quote = transfers.quote_transfer(entity.id, to_user_id=incoming.id)
        trials = transfers.trial_disclosure(entity.id, incoming.id)

        print()
        print("=" * 72)
        if blockers:
            # Printed rather than hidden: a demo that silently seeds an unusable state is
            # worse than one that says which rule it tripped.
            print("NOT READY — the handover would be refused:")
            for reason in blockers:
                print(f"  - {reason}")
        else:
            print("READY. The handover will be allowed.")
            if quote:
                # covers_from, NOT period_start: the period is Ivan's whole cycle,
                # and he only pays the part of it after Olive's money runs out.
                print(
                    f"  Accepting charges Ivan {quote['currency']} "
                    f"{quote['amount'] / 100:,.2f} for "
                    f"{quote['covers_from']:%d %b} to {quote['covers_to']:%d %b %Y}"
                )
                print(
                    f"  (Ivan's own cycle runs {quote['period_start']:%d %b} to "
                    f"{quote['period_end']:%d %b %Y}; he is not billed for the earlier part)"
                )
            for trial in trials:
                amount = (
                    f"{trial['currency']} {trial['amount'] / 100:,.2f}"
                    if trial["amount"] is not None else "an amount we couldn't price"
                )
                print(
                    f"  Inherits {'+'.join(trial['codes'])} on free trial until "
                    f"{trial['trial_end']:%d %b %Y} — {amount} charged then, not now"
                )
        print("=" * 72)
        print(f"Entity     {ENTITY_NAME}  ({entity.id})")
        print(f"Password   {PASSWORD}   (both accounts)")
        print()
        print(f"  1. Sign in to Minty as {OUTGOING_EMAIL} — the current subscriber.")
        print("  2. Open the payer portal, Manage Subscriptions, row menu ->")
        print("     Change subscriber. Pick Ivan Incoming and send the request.")
        print(f"  3. Sign in as {INCOMING_EMAIL}. The request is on My Profile,")
        print("     or at /profile/subscriptions/incoming.")
        print("  4. Accept and pay. The subscription moves and Olive stops being billed.")
        print()
        print("To retry from the start: --teardown, then run again.")


def teardown() -> None:
    from main import app

    with app.app_context():
        _require_local_and_test_mode(app)

        from models.db import (Entity, EntityBillingConsent, EntityFunctionMap,
                               EntityModuleSubscription, SubscriptionTransfer, User,
                               UserEntity, UserStripeCustomer, db)

        entity = Entity.query.filter_by(name=ENTITY_NAME).first()
        users = User.query.filter(
            User.username.in_([OUTGOING_EMAIL, INCOMING_EMAIL])
        ).all()

        if entity is not None:
            for model in (
                SubscriptionTransfer, EntityModuleSubscription,
                EntityBillingConsent, EntityFunctionMap, UserEntity,
            ):
                model.query.filter_by(entity_id=entity.id).delete(
                    synchronize_session=False
                )
            db.session.delete(entity)

        for user in users:
            UserStripeCustomer.query.filter_by(user_id=user.id).delete(
                synchronize_session=False
            )
            UserEntity.query.filter_by(user_id=user.id).delete(
                synchronize_session=False
            )
            db.session.delete(user)

        db.session.commit()
        # The Stripe test customers are LEFT. They cost nothing, hold no real card, and
        # deleting them would take their invoice history — which is the evidence of what
        # the last run actually charged.
        print(f"removed the demo entity and {len(users)} user(s).")
        print("Stripe test customers were left in place (they hold the invoice history).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teardown", action="store_true",
                        help="remove the demo users and entity")
    parser.add_argument("--with-trial", action="store_true", dest="with_trial",
                        help="add a module on a free trial, so the handover has free "
                             "days to carry over and a future charge to disclose")
    args = parser.parse_args()
    teardown() if args.teardown else seed(with_trial=args.with_trial)
