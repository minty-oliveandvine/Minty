"""Add entities.last_accessed_at and entities.last_accessed_by_user_id.

Team-wide "last logged in" for the Select Company card: when an entity was last
opened, and by which user. Written on entity open by
``blueprints.entity.routes.modules.record_entity_access``.

Entity-level rather than per-user on purpose — the card answers "who last
touched this company", which includes superuser visits that have no
``user_entity`` row.

NO BACKFILL. Both columns stay NULL until each entity's next open, and the card
renders a greyed-out clock for that state. There is no historical source to
backfill from: nothing recorded entity opens before this.

The FK is ``ON DELETE SET NULL``, not CASCADE — deleting a user must not delete
the entity, it just forgets who last opened it.

Revision ID: e1a01_entity_last_accessed
Revises: m1a01_revoke_ungranted
Create Date: 2026-08-05

"""

import sqlalchemy as sa
from alembic import op

revision = "e1a01_entity_last_accessed"
down_revision = "m1a01_revoke_ungranted"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entities",
        sa.Column("last_accessed_at", sa.TIMESTAMP(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "entities",
        sa.Column("last_accessed_by_user_id", sa.String(length=36), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_entities_last_accessed_by_user_id",
        "entities",
        "user",
        ["last_accessed_by_user_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_entities_last_accessed_by_user_id",
        "entities",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("entities", "last_accessed_by_user_id", schema=SCHEMA)
    op.drop_column("entities", "last_accessed_at", schema=SCHEMA)
