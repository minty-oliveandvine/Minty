"""Revoke module access that no subscription row ever granted - NOW A NO-OP.

A NO-OP SINCE 2026-10-01. While subscriptions were dark (2026-09-18) this revocation ran
only with ``SUBSCRIPTION_ENABLED`` on, because it is the one step of an upgrade that would
change what a customer can do. The switch was removed on 2026-10-01 (the stack is deployed
to a test site), and its standing rule outlives it: turning subscriptions on writes nothing.
So the revision is still recorded and revokes nothing; the same UPDATE is the deliberate
``flask subscriptions revoke-ungranted`` (dry by default, ``--apply`` writes -
``blueprints.subscription.services.access_sweep.revoke_ungranted_module_access``). What
follows is the original rationale, kept because the command still follows it.

Companion to ``b8f3a2c1d4e5``, which seeded the catalog and backfilled the missing
``entity_function_map`` rows. That one is INSERT-ONLY by design — it targets entities
with ``NOT EXISTS`` a map row — so it could create a correct row where none existed but
could never correct one that was already there and wrong. This is the other half: the
UPDATE that turns off the rows the backfill had to skip.

-----------------------------------------------------------------------------
WHAT WENT WRONG THAT THIS REPAIRS

Access is a PROJECTION of ``entity_module_subscription``, which is the record of truth;
``entity_function_map.is_enabled`` only caches it so the request gate costs one indexed
lookup. A module switches on when its trial or subscription starts, and that is what
writes the subscription row and then flips the flag.

Onboarding wrote map rows at ``is_enabled = TRUE`` with actor ``entity_create`` before
any of that existed. Those rows are switched on with NOTHING behind them. The visible
symptom is the one ``b8f3a2c1d4e5`` describes: a card offering "Start free trial" on a
module the user is already working inside, because the gate reads this table while the
button reads the subscription rows.

``b8f3a2c1d4e5`` assumed the only stale TRUE rows would be ones IT had written (its
original version backfilled PETTY_CASH TRUE) and left them to the access sweep. On a
database whose TRUE rows came from onboarding instead, the migration ran, reported
success, and changed nothing — every entity already had a row, so every entity was
skipped.

-----------------------------------------------------------------------------
SCOPE — DELIBERATELY THE NARROW CASE ONLY

This revokes a module ONLY when there is no ``entity_module_subscription`` row for that
(entity, module) AT ALL. It does not read ``phase``, ``trial_end``, ``app_access_until``
or any grace window.

That boundary is the point. "Has a row, and the row says access ended" is a date
comparison against tunable policy windows, and it belongs to
``sweep_expired_module_access`` (``flask subscriptions sweep-access``), which re-derives
it every pass. Reimplementing that here would freeze today's policy constants into a
migration and then disagree with the sweep the first time they are tuned. "Has no row at
all" needs no policy to decide — it is unambiguous at any point in time, which is what
makes it safe to write down once.

So this closes the gap the backfill left, and nothing else. Anything with a subscription
row behind it is the sweep's business, both before this runs and after.

-----------------------------------------------------------------------------
ONBOARDING ENTITIES ARE EXEMPT

Entities at ``status = 'onboarding'`` keep their enabled rows. The wizard records its
Step 2 module selection in the map and only starts the trials at finalize, so between
those two calls an enabled module with no subscription row is the expected state, not a
broken one. Revoking it would empty the user's own selection out from under them
mid-wizard. Same rule, and the same reason, as the sweep's exemption.

Map rows whose ``entity_id`` no longer matches any row in ``entities`` are NOT exempt —
they are revoked. A row belonging to no entity cannot be mid-onboarding, and it cannot
be entitled to anything either.

-----------------------------------------------------------------------------
IDEMPOTENT, AND SAFE TO RUN BEFORE OR AFTER THE SWEEP

Re-running matches nothing: the predicate requires ``is_enabled`` to still be true, so a
second pass updates zero rows. It commutes with ``sweep-access`` for the same reason —
whichever runs first, the other finds its work already done. A database where the sweep
has already been run by hand gets a clean no-op here, and the alembic history still
records that the repair happened.

Revision ID: m1a01_revoke_ungranted
Revises: t1a01_terms_consent
Create Date: 2026-08-07

Parented on ``t1a01_terms_consent`` — the current head — rather than on
``b8f3a2c1d4e5``, whose gap this actually closes. Hanging it off b8f3a2c1d4e5 would read
better as history but would fork the graph: t1a01 is already a child of that revision, so
this would become a second head and every later ``flask db upgrade`` would need a merge
node or an explicit target. The repo's standing choice on this is to reparent and keep
one line. Nothing is lost by the later slot — this is a pure data UPDATE over tables that
existed long before either neighbour, and no revision between them reads what it writes.

"""

revision = "m1a01_revoke_ungranted"
down_revision = "t1a01_terms_consent"
branch_labels = None
depends_on = None



def upgrade():
    # A no-op on purpose (see the docstring): the revocation is the deliberate
    # ``flask subscriptions revoke-ungranted``, never a side effect of a deploy.
    print("m1a01: no-op - nothing revoked; the revocation is "
          "`flask subscriptions revoke-ungranted` (dry unless --apply).")


def downgrade():
    # Intentional no-op. There is no correct inverse: re-enabling these rows would hand
    # back modules that nothing ever granted, which is precisely the state this exists to
    # erase. The rows carry disabled_at if a specific case ever needs auditing by hand.
    pass
