"""add invitations.first_name / last_name

The invitee's name is now captured at invite time and persisted, so the
pending-invite cards (onboarding Step 8 + Settings -> Users) keep the
name/email/role format when the invite is re-read from the DB on resume.
Previously the name lived only in the accept URL. Existing rows are left NULL.

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d2
Create Date: 2026-07-02 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "f8a9b2c3d4e5"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "invitations",
        sa.Column("first_name", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "invitations",
        sa.Column("last_name", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("invitations", "last_name", schema=SCHEMA)
    op.drop_column("invitations", "first_name", schema=SCHEMA)
