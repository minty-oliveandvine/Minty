"""add user_token.refresh_token_last_used_at

Records the last successful refresh of the access_token (stamped in HK
local time). Used to surveil refresh churn and to drive the Connection
Status "Reconnect" prompt when the refresh chain has gone stale.

Revision ID: d5e7f9b1_refresh_used
Revises: c4d6e8f0_user_token
Create Date: 2026-05-13 00:00:02.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "d5e7f9b1_refresh_used"
down_revision = "c4d6e8f0_user_token"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "user_token",
        sa.Column("refresh_token_last_used_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("user_token", "refresh_token_last_used_at", schema=SCHEMA)
