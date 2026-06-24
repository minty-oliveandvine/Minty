"""add entities.connected_by_user_id

Tracks which user authorised the Xero connection for an entity. The Xero
token resolver uses this to deterministically pick the right user's token
when calling Xero on the entity's behalf, instead of guessing via the legacy
``User.xero_entity_id == entity.xero_org_id`` lookup.

Revision ID: b3c5d7e9_connected_by
Revises: a7b8c9d0e1f2
Create Date: 2026-05-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "b3c5d7e9_connected_by"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entities",
        sa.Column("connected_by_user_id", sa.String(36), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "entities_connected_by_user_id_fkey",
        source_table="entities",
        referent_table="user",
        local_cols=["connected_by_user_id"],
        remote_cols=["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint(
        "entities_connected_by_user_id_fkey",
        "entities",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_column("entities", "connected_by_user_id", schema=SCHEMA)
