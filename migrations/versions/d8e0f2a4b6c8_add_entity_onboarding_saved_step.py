"""Add onboarding_saved_step to entities

Tracks how far an entity has progressed through onboarding so the flow can be
resumed. Existing entities are treated as fully onboarded and backfilled to
step 9 (the final step); new rows default to 9 as well. The column stays
nullable, matching the raw SQL rollout.

NOTE: this file originally shipped with revision id "b1d3f5a7c9e2", which
collided with b1d3f5a7c9e2_add_invitation_names.py (both created off
a9c1e3f5b7d2) and broke ``flask db upgrade`` with "Multiple head revisions".
It was renumbered to d8e0f2a4b6c8 and chained after the invitation-names
migration; the DDL is guarded (IF NOT EXISTS) because databases stamped at
b1d3f5a7c9e2 already carry this column from the original rollout.

Revision ID: d8e0f2a4b6c8
Revises: b1d3f5a7c9e2
Create Date: 2026-07-06 00:00:00.000000

"""

from alembic import op

revision = "d8e0f2a4b6c8"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.execute(
        f"ALTER TABLE {SCHEMA}.entities "
        "ADD COLUMN IF NOT EXISTS onboarding_saved_step INTEGER"
    )
    op.execute(
        f"UPDATE {SCHEMA}.entities "
        "SET onboarding_saved_step = 9 WHERE onboarding_saved_step IS NULL"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.entities "
        "ALTER COLUMN onboarding_saved_step SET DEFAULT 9"
    )


def downgrade():
    op.execute(
        f"ALTER TABLE {SCHEMA}.entities "
        "DROP COLUMN IF EXISTS onboarding_saved_step"
    )
