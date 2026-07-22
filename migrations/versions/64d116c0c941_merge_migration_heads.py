"""merge migration heads

Revision ID: 64d116c0c941
Revises: c2e4a6b8d0f1, f8a9b2c3d4e5
Create Date: 2026-07-22 10:21:43.474907

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '64d116c0c941'
down_revision = ('c2e4a6b8d0f1', 'f8a9b2c3d4e5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
