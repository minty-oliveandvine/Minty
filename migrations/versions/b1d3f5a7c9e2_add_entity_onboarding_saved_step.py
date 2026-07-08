"""Add onboarding_saved_step to entities

Tracks how far an entity has progressed through onboarding so the flow can be
resumed. Existing entities are treated as fully onboarded and backfilled to
step 9 (the final step); new rows default to 9 as well. The column stays
nullable, matching the raw SQL rollout.

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d2
Create Date: 2026-07-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b1d3f5a7c9e2"
down_revision = "a9c1e3f5b7d2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entities",
        sa.Column("onboarding_saved_step", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.entities "
        "SET onboarding_saved_step = 9 WHERE onboarding_saved_step IS NULL"
    )
    op.alter_column(
        "entities",
        "onboarding_saved_step",
        server_default=sa.text("9"),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("entities", "onboarding_saved_step", schema=SCHEMA)
