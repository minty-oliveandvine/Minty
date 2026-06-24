"""Add is_active column to entity_account_xero

Tick state for the petty cash CoA was previously encoded as row presence
(delete on untick, insert on tick). With this column, unticked rows stay
around with is_active=false, mirroring how entity_bill_account_xero works.

Existing rows are backfilled to is_active=true because everything in the
table today represents a currently-selected account.

Revision ID: f5a7c9d1b3e2
Revises: e3f5a7c9b1d2
Create Date: 2026-05-19 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f5a7c9d1b3e2"
down_revision = "e3f5a7c9b1d2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entity_account_xero",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("entity_account_xero", "is_active", schema=SCHEMA)
