"""add invitations.expires_at

Invitations now lapse after a TTL (default 7 days, Hong Kong time). The value is
stamped at creation in the service layer; existing rows are left NULL and are
treated as never-expiring by the accept flow.

Revision ID: a9c1e3f5b7d2
Revises: f3a1c2b4d6e8
Create Date: 2026-06-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "a9c1e3f5b7d2"
down_revision = "f3a1c2b4d6e8"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "invitations",
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("invitations", "expires_at", schema=SCHEMA)
