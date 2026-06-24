"""email_otp

Revision ID: add_email_otp
Revises: <your current head revision>
Create Date: 2026-06-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_email_otp"            
down_revision = "b8f3a2c1d4e5" 
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_otp",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="pettycashv2",
    )
    op.create_index(
        op.f("ix_email_otp_email"),
        "email_otp",
        ["email"],
        unique=False,
        schema="pettycashv2",
    )


def downgrade():
    op.drop_index(
        op.f("ix_email_otp_email"),
        table_name="email_otp",
        schema="pettycashv2",
    )
    op.drop_table("email_otp", schema="pettycashv2")