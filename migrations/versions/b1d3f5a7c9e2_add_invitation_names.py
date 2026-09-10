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


revision = "b1d3f5a7c9e2"
down_revision = "a9c1e3f5b7d2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"




def _has_column(table: str, column: str) -> bool:
    """True if the column already exists.

    production-backup - and therefore production - carries these columns already,
    while its alembic_version still points at the revision BEFORE this one: the
    DDL was applied without stamping. A plain add_column then fails with
    DuplicateColumn and the whole upgrade stops.

    The column definitions were compared against what this revision declares and
    match exactly, so skipping the add when it is already there is safe and makes
    the revision idempotent.
    """
    bind = op.get_bind()
    return bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
        ),
        {"s": SCHEMA, "t": table, "c": column},
    ).scalar() is not None


def upgrade():
    if not _has_column("invitations", "first_name"):
        op.add_column(
            "invitations",
            sa.Column("first_name", sa.String(length=100), nullable=True),
            schema=SCHEMA,
        )
    if not _has_column("invitations", "last_name"):
        op.add_column(
            "invitations",
            sa.Column("last_name", sa.String(length=100), nullable=True),
            schema=SCHEMA,
        )


def downgrade():
    op.drop_column("invitations", "last_name", schema=SCHEMA)
    op.drop_column("invitations", "first_name", schema=SCHEMA)
