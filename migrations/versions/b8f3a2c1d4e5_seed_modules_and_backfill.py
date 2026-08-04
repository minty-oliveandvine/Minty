"""Seed entity_function catalog and backfill entity_function_map for existing entities.

Access is a PROJECTION of a module's ``entity_module_subscription`` row, which is the
record of truth. ``entity_function_map.is_enabled`` only caches it so the request gate
costs one indexed lookup instead of a join. Nothing here may GRANT a module: a module
switches on when its trial or subscription starts, which is what writes the row and
then flips the flag (``checkout._set_module_access``).

Catalog defaults:
  - PETTY_CASH → is_active = FALSE
  - BILL       → is_active = FALSE

``is_active`` says whether a module is OFFERED, never who may use it. It used to double
as the "no map row" fallback in ``_is_module_enabled``, and with PETTY_CASH active that
fallback granted the module to every entity that had never subscribed to it. The
resolver no longer reads it at all — both ``_is_module_enabled`` and ``_enabled_state``
now deny when there is no map row — so seeding both FALSE is belt-and-braces against
anything reintroducing the read.

Backfill posture (the long-term "explicit row per entity per module" pattern):
  For every entity in the table (including soft-deleted ones — so if any are
  ever restored they already have correct entitlements), insert BOTH rows in
  entity_function_map, both OFF:
    - PETTY_CASH → is_enabled = FALSE (disabled_at = NOW())
    - BILL       → is_enabled = FALSE (disabled_at = NOW())

Both rows are written explicitly (rather than relying on the catalog fallback) so an
entity's entitlements are always an unambiguous DB record — the same shape onboarding
writes for new entities.

PETTY_CASH used to be backfilled TRUE here, on the reasoning that existing entities
should not lose a module they were already using. That handed every entity in the table
a free module with no subscription row behind it — and because the daily sweep skipped
modules with no row, nothing ever took it back. The visible symptom was a card offering
"Start free trial" on a module the user was already working inside, because the gate read
this table while the button read the subscription rows.

Writing FALSE costs those entities nothing they still had: with the resolver now denying
on a missing row, an unmigrated database already refuses these modules. This only makes
the refusal an explicit record. Databases that ran the ORIGINAL version of this migration
keep their TRUE rows — alembic will not re-run it — and are repaired by the access sweep
(``flask subscriptions sweep-access``), which now revokes a module with no subscription
row instead of skipping it.

UUIDs are generated in Python rather than via ``gen_random_uuid()`` so the
migration runs on any DB role / search_path / Postgres version. The earlier
``CREATE EXTENSION IF NOT EXISTS "pgcrypto"`` call failed on roles that don't
have CREATE on a schema in their search_path — modern Postgres has
``gen_random_uuid`` in core anyway, but the safest path is to bypass the
extension entirely and not depend on PG version either.

Idempotent — re-running is a no-op:
  * catalog rows use ON CONFLICT (function_code) so re-runs just refresh the
    name / is_active / updated_at without creating duplicates;
  * map-row inserts target only entities that don't already have a row for
    the function (NOT EXISTS), so entities set by hand pre-backfill are left
    untouched.

Downgrade is a no-op. Removing these rows would silently flip behaviour from
the explicit record back to the catalog fallback, which is the surprise this
migration is designed to eliminate.

Revision ID: b8f3a2c1d4e5
Revises: a1b2c3d4e5f7
Create Date: 2026-05-29 00:00:00.000000

Ordering note: this is a pure, idempotent DATA seed — it only INSERTs into
entity_function / entity_function_map, both of which exist from the base schema, and no
other migration reads what it writes. So it is placed LAST, after the subscription
schema, rather than at its original 2026-05 slot. The create-date is left as written for
provenance; alembic orders by the graph, not date.

Kept SEPARATE from the squashed schema revision on purpose: that one is DDL for tables
it creates itself, this one writes rows into tables it does not own. Folding a data
backfill into a schema migration hides the fact that re-running them has completely
different consequences.

"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "b8f3a2c1d4e5"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Sentinel stored in entity_function_map.created_by so audit queries can tell
# "this row came from the one-shot backfill" apart from "a human/onboarding
# turned this on/off later". Fits the column's 36-char cap.
BACKFILL_ACTOR = "system_backfill"


def upgrade():
    bind = op.get_bind()

    # 1. Catalog seed — upsert by function_code (the model-declared unique key).
    #    UUIDs are bound from Python; the ON CONFLICT branch ignores the
    #    supplied :pc_id/:bill_id when the row already exists, so re-runs
    #    don't churn the PKs.
    bind.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.entity_function
                (id, function_code, function_name, description, is_active, created_at, updated_at)
            VALUES
                (:pc_id, 'PETTY_CASH', 'Petty Cash',
                 'Petty cash module — track and reimburse small office expenses.',
                 FALSE, NOW(), NOW()),
                (:bill_id, 'BILL', 'Payment Request',
                 'Payment request module — capture vendor bills and reconcile with the ledger.',
                 FALSE, NOW(), NOW())
            ON CONFLICT (function_code) DO UPDATE
            SET function_name = EXCLUDED.function_name,
                description   = EXCLUDED.description,
                is_active     = EXCLUDED.is_active,
                updated_at    = NOW()
            """
        ),
        {"pc_id": str(uuid.uuid4()), "bill_id": str(uuid.uuid4())},
    )

    # 2. Resolve the canonical function ids post-upsert. Pre-existing rows
    #    keep their original PKs; freshly inserted rows take the bound UUIDs.
    pc_function_id = bind.execute(
        text(f"SELECT id FROM {SCHEMA}.entity_function WHERE function_code = 'PETTY_CASH'")
    ).fetchone()[0]
    bill_function_id = bind.execute(
        text(f"SELECT id FROM {SCHEMA}.entity_function WHERE function_code = 'BILL'")
    ).fetchone()[0]

    # 3. Backfill BOTH modules OFF for every entity that doesn't yet have a map row
    #    for them. One loop rather than a block per module: the two used to differ
    #    (PETTY_CASH TRUE, BILL FALSE) and now say the same thing, because nothing
    #    outside the subscription lifecycle may grant a module.
    #
    #    Per-row INSERT (rather than a single INSERT…SELECT) so each PK is a
    #    Python-generated UUID — see the note above on avoiding gen_random_uuid().
    targets_sql = text(
        f"""
        SELECT e.id
        FROM {SCHEMA}.entities e
        WHERE NOT EXISTS (
            SELECT 1
            FROM {SCHEMA}.entity_function_map m
            WHERE m.entity_id = e.id
              AND m.entity_function_id = :fn_id
        )
        """
    )
    insert_sql = text(
        f"""
        INSERT INTO {SCHEMA}.entity_function_map
            (id, entity_id, entity_function_id, is_enabled,
             enabled_at, disabled_at, created_by, created_at, updated_at)
        VALUES (:id, :entity_id, :fn_id, FALSE,
                NULL, NOW(), :actor, NOW(), NOW())
        """
    )

    for function_id in (pc_function_id, bill_function_id):
        targets = bind.execute(targets_sql, {"fn_id": function_id}).fetchall()
        for row in targets:
            bind.execute(
                insert_sql,
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": row[0],
                    "fn_id": function_id,
                    "actor": BACKFILL_ACTOR,
                },
            )


def downgrade():
    # Intentional no-op — reverting would silently restore the catalog-fallback
    # ambiguity this migration replaces with explicit rows, and setting is_active
    # back to TRUE would re-grant a module to every entity with no map row.
    pass