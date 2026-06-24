"""add entities.period_lock_date and entities.end_of_year_lock_date

Also merges the two open heads (37799fa97f37, d7f332f8571f) into one
linear history.

Revision ID: a1b2c3d4e5f6_lock_dates
Revises: 37799fa97f37, d7f332f8571f
Create Date: 2026-05-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "a1b2c3d4e5f6_lock_dates"
down_revision = ("37799fa97f37", "d7f332f8571f")
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entities",
        sa.Column("period_lock_date", sa.Date(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "entities",
        sa.Column("end_of_year_lock_date", sa.Date(), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("entities", "end_of_year_lock_date", schema=SCHEMA)
    op.drop_column("entities", "period_lock_date", schema=SCHEMA)
