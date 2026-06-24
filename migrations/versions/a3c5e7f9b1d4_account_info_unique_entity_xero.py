"""Add unique constraint on account_info(entity_id, xero_account_id)

Concurrent background syncs (Xero connect, settings-page GET, expense-page GET
all spawn daemon threads) could each insert the same account before any of
them committed, producing duplicate account_info rows for one Xero account.
There was no DB-level guard. This adds one so the race can no longer duplicate;
the sync upserts use ON CONFLICT on this constraint to merge instead of failing.

Pre-existing duplicates are collapsed in-place before the constraint is added:
for every group sharing (entity_id, xero_account_id) the earliest row survives,
and any reference to a duplicate row -- the role pointers in
entity_pettycash_settings (populated earlier in this same upgrade chain) and any
entity_account_xero child -- is repointed onto the survivor first, so the cleanup
never silently drops a role assignment. The delete is irreversible, so downgrade
only drops the constraint.

Revision ID: a3c5e7f9b1d4
Revises: f5a7c9d1b3e2
Create Date: 2026-05-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a3c5e7f9b1d4"
down_revision = "f5a7c9d1b3e2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
CONSTRAINT = "uq_account_info_entity_xero_account"

# entity_pettycash_settings columns that hold an account_info.id pointer.
SETTINGS_ACCOUNT_COLS = (
    "pettycash_account_id",
    "bank_account_id",
    "cash_sale_account_id",
    "discrepancy_bank_account_id",
    "discrepancy_account_id",
    "director_account_id",
)


def upgrade():
    conn = op.get_bind()

    # Map each duplicate row -> the survivor it should collapse into. Survivor is
    # the earliest-created row (id as a stable tie-break). NULL xero_account_id is
    # excluded: NULLs are not deduplicated by a UNIQUE constraint, so they cannot
    # block it and must not be collapsed.
    op.execute(
        f"""
        CREATE TEMPORARY TABLE _ai_dedup_map ON COMMIT DROP AS
        SELECT id AS loser_id, survivor_id
        FROM (
            SELECT id,
                   first_value(id) OVER (
                       PARTITION BY entity_id, xero_account_id
                       ORDER BY created_at NULLS FIRST, id
                   ) AS survivor_id
            FROM {SCHEMA}.account_info
            WHERE xero_account_id IS NOT NULL
        ) ranked
        WHERE id <> survivor_id
        """
    )

    # Repoint role pointers in entity_pettycash_settings onto the survivor. Guarded
    # because the table only exists once c7d9e1f3a5b7 has run earlier in the chain.
    settings_exists = conn.execute(
        sa.text("SELECT to_regclass(:r)"),
        {"r": f"{SCHEMA}.entity_pettycash_settings"},
    ).scalar()
    if settings_exists:
        for col in SETTINGS_ACCOUNT_COLS:
            op.execute(
                f"""
                UPDATE {SCHEMA}.entity_pettycash_settings eps
                SET {col} = m.survivor_id
                FROM _ai_dedup_map m
                WHERE eps.{col} = m.loser_id
                """
            )

    # Repoint any surviving CoA child rows so the FK cascade does not delete them.
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET account_id = m.survivor_id
        FROM _ai_dedup_map m
        WHERE eax.account_id = m.loser_id
        """
    )

    # Now the duplicates are unreferenced -- remove them.
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.account_info ai
        USING _ai_dedup_map m
        WHERE ai.id = m.loser_id
        """
    )

    op.create_unique_constraint(
        CONSTRAINT,
        "account_info",
        ["entity_id", "xero_account_id"],
        schema=SCHEMA,
    )


def downgrade():
    op.drop_constraint(
        CONSTRAINT, "account_info", schema=SCHEMA, type_="unique"
    )
