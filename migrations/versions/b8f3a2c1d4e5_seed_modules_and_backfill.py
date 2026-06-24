"""Seed entity_function catalog and backfill entity_function_map for existing entities.

Catalog defaults (driving the "no map row" fallback in ``_is_module_enabled``):
  - PETTY_CASH → is_active = TRUE   (every existing customer has it today)
  - BILL       → is_active = FALSE  (must be explicitly granted per entity)

Backfill posture (the long-term "explicit row per entity per module" pattern):
  For every entity in the table (including soft-deleted ones — so if any are
  ever restored they already have correct entitlements), insert BOTH rows in
  entity_function_map:
    - PETTY_CASH → is_enabled = TRUE  (enabled_at = NOW())
    - BILL       → is_enabled = FALSE (disabled_at = NOW())

The unselected-module row is written explicitly (rather than relying on the
catalog fallback) so an entity's entitlements are always an unambiguous DB
record — which is the same shape onboarding writes for new entities.

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
Revises: a3c5e7f9b1d4
Create Date: 2026-05-29 00:00:00.000000

"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "b8f3a2c1d4e5"
down_revision = "a3c5e7f9b1d4"
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
                 TRUE, NOW(), NOW()),
                (:bill_id, 'BILL', 'Bill Payment',
                 'Bill payment module — capture vendor bills and reconcile with the ledger.',
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

    # 3. Backfill PETTY_CASH = TRUE for every entity that doesn't yet have a
    #    map row for it. Per-row INSERT (rather than a single INSERT…SELECT)
    #    so each PK is a Python-generated UUID.
    pc_targets = bind.execute(
        text(
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
        ),
        {"fn_id": pc_function_id},
    ).fetchall()

    insert_pc = text(
        f"""
        INSERT INTO {SCHEMA}.entity_function_map
            (id, entity_id, entity_function_id, is_enabled,
             enabled_at, disabled_at, created_by, created_at, updated_at)
        VALUES (:id, :entity_id, :fn_id, TRUE,
                NOW(), NULL, :actor, NOW(), NOW())
        """
    )
    for row in pc_targets:
        bind.execute(
            insert_pc,
            {
                "id": str(uuid.uuid4()),
                "entity_id": row[0],
                "fn_id": pc_function_id,
                "actor": BACKFILL_ACTOR,
            },
        )

    # 4. Backfill BILL = FALSE for every entity that doesn't yet have a map
    #    row for it. Same idempotency guard, opposite is_enabled value.
    bill_targets = bind.execute(
        text(
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
        ),
        {"fn_id": bill_function_id},
    ).fetchall()

    insert_bill = text(
        f"""
        INSERT INTO {SCHEMA}.entity_function_map
            (id, entity_id, entity_function_id, is_enabled,
             enabled_at, disabled_at, created_by, created_at, updated_at)
        VALUES (:id, :entity_id, :fn_id, FALSE,
                NULL, NOW(), :actor, NOW(), NOW())
        """
    )
    for row in bill_targets:
        bind.execute(
            insert_bill,
            {
                "id": str(uuid.uuid4()),
                "entity_id": row[0],
                "fn_id": bill_function_id,
                "actor": BACKFILL_ACTOR,
            },
        )


def downgrade():
    # Intentional no-op — reverting would silently restore the catalog-fallback
    # ambiguity this migration replaces with explicit rows.
    pass