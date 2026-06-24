"""Add name column to entity_account_xero and backfill from account_info

Mirrors entity_bill_account_xero which already carries account_name. Lets us
answer "what's this row?" without always joining to account_info.

Revision ID: e3f5a7c9b1d2
Revises: d2e4f6a8b0c1
Create Date: 2026-05-19 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e3f5a7c9b1d2"
down_revision = "d2e4f6a8b0c1"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entity_account_xero",
        sa.Column("name", sa.String(80), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET name = ai.name
        FROM {SCHEMA}.account_info ai
        WHERE eax.account_id = ai.id
          AND eax.name IS NULL
        """
    )


def downgrade():
    op.drop_column("entity_account_xero", "name", schema=SCHEMA)
