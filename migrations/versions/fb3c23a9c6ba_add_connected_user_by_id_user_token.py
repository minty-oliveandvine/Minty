"""add connected_user_by_id, user_token

Revision ID: fb3c23a9c6ba
Revises: bff9bac00938
Create Date: 2026-05-15 10:17:10.674338

NOTE: This migration is intentionally a no-op. Both objects it originally
created -- ``entities.connected_by_user_id`` and the ``pettycashv2.user_token``
table -- are already created by shared-ancestor migrations
``b3c5d7e9_connected_by`` and ``c4d6e8f0_user_token``, which run before this
revision on every path. Running the original DDL here failed with
"column/relation already exists". The body is neutralized so the revision can
remain in history and be merged with the other head without breaking upgrades.

"""

# revision identifiers, used by Alembic.
revision = 'fb3c23a9c6ba'
down_revision = 'bff9bac00938'
branch_labels = None
depends_on = None


def upgrade():
    # No-op: see module docstring. Objects already exist via
    # b3c5d7e9_connected_by and c4d6e8f0_user_token.
    pass


def downgrade():
    # No-op: this revision created nothing, so there is nothing to revert.
    # The owning objects are dropped by the migrations that actually created
    # them (b3c5d7e9_connected_by / c4d6e8f0_user_token).
    pass