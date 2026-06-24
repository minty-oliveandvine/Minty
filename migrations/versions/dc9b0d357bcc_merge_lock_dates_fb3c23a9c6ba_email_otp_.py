"""merge lock-dates (fb3c23a9c6ba) + email-otp heads

Revision ID: dc9b0d357bcc
Revises: add_email_otp, fb3c23a9c6ba
Create Date: 2026-06-04 16:17:02.361571

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dc9b0d357bcc'
down_revision = ('add_email_otp', 'fb3c23a9c6ba')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
