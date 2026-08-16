"""add user.current_entity_id

Fixes a bug in the signed-in list: presence was a fact about the PERSON —
``signed_in_at`` and ``last_seen_at`` on ``user`` — while Settings > Users asks a
question about a COMPANY. Nothing in the row said which company they were in, so
someone signed in to company A appeared on company B's list too.

This records where they are. Set when a company is opened, cleared when they leave
it or sign out. NULL means signed in to Minty but standing on the entity list,
inside no company — which is where every session starts, so NULL is the correct
value for every existing row and no backfill is possible or wanted.

No foreign key, on purpose. ``entities.last_accessed_by_user_id`` already points
from entities to user, so a constraint back the other way closes a cycle between
the two tables that SQLAlchemy cannot sort for create/drop — it warns today and
says it may raise in future. The reference is inert anyway: it is compared for
equality, never followed, so a row pointing at a deleted company matches nothing,
and presence ages out within the hour regardless.

Revision ID: p2a01_user_current_entity
Revises: c1a01_entity_contact_fields
Create Date: 2026-08-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "p2a01_user_current_entity"
down_revision = "c1a01_entity_contact_fields"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "user",
        sa.Column("current_entity_id", sa.String(length=36), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_user_current_entity_id",
        "user",
        ["current_entity_id"],
        schema=SCHEMA,
    )


def downgrade():
    op.drop_index("ix_user_current_entity_id", table_name="user", schema=SCHEMA)
    op.drop_column("user", "current_entity_id", schema=SCHEMA)
