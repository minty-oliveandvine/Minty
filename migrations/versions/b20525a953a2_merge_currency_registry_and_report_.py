"""merge currency registry and report draft heads

Revision ID: b20525a953a2
Revises: c2e4a6b8d0f1, e5b7d9f1a3c6
Create Date: 2026-07-24 15:45:00.976074

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b20525a953a2'
down_revision = ('c2e4a6b8d0f1', 'e5b7d9f1a3c6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
