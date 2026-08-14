"""rename entities.contact_option -> contact_phone, add entities.business_email

Onboarding Step 1 has always collected a "Contact Phone" and a "Business Email"
and the wizard has always POSTed them as ``contact_phone`` / ``business_email``,
but there was nowhere to put them: the entities table had no such columns and
the routes dropped both keys on the floor. These two columns are that home.

The phone reuses ``contact_option``, a varchar(36) that has been on the table
since 0001_full_schema and was never read or written by anything -- verified
NULL in 100% of rows in both the dev database (0 of 63) and production-backup
(0 of 82), so the rename carries no data and the 36 -> 20 narrowing cannot
truncate anything. 20 matches user.user_phone; the wizard caps input at 11
digits and stores digits only.

business_email is varchar(100) to match user.email.

Both stay nullable: Step 1 marks the two fields optional, and every existing
entity predates them.

Revision ID: c1a01_entity_contact_fields
Revises: p1a01_user_presence
Create Date: 2026-08-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "c1a01_entity_contact_fields"
down_revision = "p1a01_user_presence"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.alter_column(
        "entities",
        "contact_option",
        new_column_name="contact_phone",
        existing_type=sa.String(36),
        type_=sa.String(20),
        existing_nullable=True,
        schema=SCHEMA,
    )
    op.add_column(
        "entities",
        sa.Column("business_email", sa.String(100), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("entities", "business_email", schema=SCHEMA)
    op.alter_column(
        "entities",
        "contact_phone",
        new_column_name="contact_option",
        existing_type=sa.String(20),
        type_=sa.String(36),
        existing_nullable=True,
        schema=SCHEMA,
    )
