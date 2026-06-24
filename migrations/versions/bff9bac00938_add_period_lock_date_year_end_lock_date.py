"""add period_lock_date, year_end_lock_date

Revision ID: bff9bac00938
Revises: a1b2c3d4e5f6_lock_dates
Create Date: 2026-05-15 10:15:53.113862

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bff9bac00938'
down_revision = 'a1b2c3d4e5f6_lock_dates'
branch_labels = None
depends_on = None
SCHEMA='pettycashv2'


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