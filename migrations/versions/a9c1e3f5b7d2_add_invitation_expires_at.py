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
    if _has_column("invitations", "expires_at"):
        return
    op.add_column(
        "invitations",
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("invitations", "expires_at", schema=SCHEMA)
