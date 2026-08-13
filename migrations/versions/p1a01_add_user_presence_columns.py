"""add user.signed_in_at / user.last_seen_at

Backs the "currently signed in" filter on Settings > Users. See
services/user_presence.py for what each column means and why presence is two
columns on `user` rather than a sessions table.

Both are backfilled to NULL, so every existing account starts off the list and
reappears on its next login — the intended behaviour, and the only honest
starting point given we have no record of who was signed in before this ran.

Revision ID: p1a01_user_presence
Revises: e1a01_entity_last_accessed
Create Date: 2026-08-07 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "p1a01_user_presence"
down_revision = "e1a01_entity_last_accessed"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "user",
        sa.Column("signed_in_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "user",
        sa.Column("last_seen_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("user", "last_seen_at", schema=SCHEMA)
    op.drop_column("user", "signed_in_at", schema=SCHEMA)