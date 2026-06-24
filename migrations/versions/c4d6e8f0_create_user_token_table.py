"""create user_token table

Splits OAuth tokens out of the ``user`` row into a dedicated
``pettycashv2.user_token`` table. One row per user (``user_id`` UNIQUE,
``ON DELETE CASCADE``). ``updated_at`` auto-refreshes on row change via a
Postgres trigger so direct SQL updates are covered too (the SQLAlchemy
``onupdate`` only fires on ORM updates).

Revision ID: c4d6e8f0_user_token
Revises: b3c5d7e9_connected_by
Create Date: 2026-05-13 00:00:01.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "c4d6e8f0_user_token"
down_revision = "b3c5d7e9_connected_by"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.create_table(
        "user_token",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()::text"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("access_token_obtained_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("access_token_expires_in", sa.Integer(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("id_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.user.id"],
            name="user_token_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", name="user_token_user_id_key"),
        schema=SCHEMA,
    )

    # Trigger to keep updated_at fresh on any row change (covers raw SQL,
    # not just SQLAlchemy ORM updates).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.user_token_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER user_token_set_updated_at
        BEFORE UPDATE ON {SCHEMA}.user_token
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.user_token_set_updated_at();
        """
    )


def downgrade():
    op.execute(
        f"DROP TRIGGER IF EXISTS user_token_set_updated_at "
        f"ON {SCHEMA}.user_token;"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.user_token_set_updated_at();")
    op.drop_table("user_token", schema=SCHEMA)
