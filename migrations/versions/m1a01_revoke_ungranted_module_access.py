"""Revoke module access that no subscription row ever granted.

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

import os

from alembic import op
from sqlalchemy import text

revision = "m1a01_revoke_ungranted"
down_revision = "t1a01_terms_consent"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Mirrors blueprints.entity.services.modules.MODULE_CODES. Spelled out rather than
# imported: a migration must keep describing the database as it was when written, and
# an import would silently change this statement's meaning the day a third module ships.
MODULE_CODES = ("PETTY_CASH", "BILL")


def upgrade():
    # SUBSCRIPTIONS DARK (2026-09-18, docs/modernisation/modernisation_plan.md Phase E):
    # production cuts over to the redesigned schema with the subscription feature switched
    # off, and this revocation is the one step of the upgrade that would change what a
    # customer can do - 47 live companies would lose Petty Cash for a feature nobody can
    # see. So it runs only when the feature is on. With it off the grants come through as
    # they are, the revision is still recorded, and the same UPDATE is available on launch
    # day as ``flask subscriptions revoke-ungranted`` - a deliberate command, not a side
    # effect of a deploy. The switch's default is off (blueprints/shared/feature_flags.py).
    if (os.environ.get("SUBSCRIPTION_ENABLED") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        print("m1a01: skipped - subscriptions are dark (SUBSCRIPTION_ENABLED unset/0); "
              "nothing revoked. Launch day: flask subscriptions revoke-ungranted.")
        return

    bind = op.get_bind()

    result = bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_function_map AS m
            SET is_enabled  = FALSE,
                disabled_at = NOW(),
                updated_at  = NOW()
            FROM {SCHEMA}.entity_function AS f
            WHERE f.id = m.entity_function_id
              AND UPPER(f.function_code) IN :codes
              AND m.is_enabled
              -- The whole test: nothing in the record of truth grants this module.
              AND NOT EXISTS (
                  SELECT 1
                  FROM {SCHEMA}.entity_module_subscription AS s
                  WHERE s.entity_id = m.entity_id
                    AND UPPER(s.function_code) = UPPER(f.function_code)
              )
              -- Mid-wizard entities keep their selection (see docstring). Written as
              -- NOT EXISTS on purpose rather than a join to entities: a map row whose
              -- entity is gone matches nothing here and so stays in scope for revoking.
              AND NOT EXISTS (
                  SELECT 1
                  FROM {SCHEMA}.entities AS e
                  WHERE e.id = m.entity_id
                    AND e.status = 'onboarding'
              )
            """
        ).bindparams(codes=tuple(MODULE_CODES))
    )

    # Printed rather than logged: alembic's output is the only record anyone reads when
    # deciding whether a deploy did what it claimed, and "0 rows" is a meaningful and
    # expected result here (already swept), not a sign the statement failed to match.
    print(f"m1a01: revoked {result.rowcount} module grant(s) with no subscription row.")


def downgrade():
    # Intentional no-op. There is no correct inverse: re-enabling these rows would hand
    # back modules that nothing ever granted, which is precisely the state this exists to
    # erase. The rows carry disabled_at if a specific case ever needs auditing by hand.
    pass
