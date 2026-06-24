"""sync user table: add system_role, drop role and company

Migrates existing role values to system_role without data loss:
  admin / super_admin  ->  'superuser'
  everything else      ->  'normal'

Revision ID: 0002_sync_user_columns
Revises: 0001_full_schema
Create Date: 2026-03-17 00:00:01.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0002_sync_user_columns"
down_revision = "0001_full_schema"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    # 1. Add system_role as nullable first so we can backfill
    op.add_column(
        "user",
        sa.Column(
            "system_role",
            sa.String(20),
            nullable=True,
            server_default="normal",
        ),
        schema=SCHEMA,
    )

    # 2. Backfill from the old role column
    op.execute(
        f"""
        UPDATE {SCHEMA}."user"
        SET system_role = CASE
            WHEN lower(replace(replace(role, ' ', '_'), '-', '_'))
                 IN ('admin', 'super_admin')
                THEN 'superuser'
            ELSE 'normal'
        END
        """
    )

    # 3. Make system_role NOT NULL now that every row has a value
    op.alter_column(
        "user",
        "system_role",
        existing_type=sa.String(20),
        nullable=False,
        server_default="normal",
        schema=SCHEMA,
    )

    # 4. Drop the old columns
    op.drop_column("user", "role", schema=SCHEMA)
    op.drop_column("user", "company", schema=SCHEMA)


def downgrade():
    # Restore old columns
    op.add_column(
        "user",
        sa.Column("company", sa.String(150), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "user",
        sa.Column(
            "role",
            sa.String(150),
            nullable=True,
            server_default="user",
        ),
        schema=SCHEMA,
    )

    # Map system_role back to role
    op.execute(
        f"""
        UPDATE {SCHEMA}."user"
        SET role = CASE
            WHEN system_role = 'superuser' THEN 'super_admin'
            ELSE 'user'
        END
        """
    )

    op.alter_column(
        "user",
        "role",
        existing_type=sa.String(150),
        nullable=False,
        server_default="user",
        schema=SCHEMA,
    )

    # Drop system_role
    op.drop_column("user", "system_role", schema=SCHEMA)
