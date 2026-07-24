"""Rename entities.country_id -> entities.country_code.

Since c8e0a2b4d6f8 the column holds the 2-letter ISO code (char(2)) and
references country_info(country_code), so the old name was misleading. A
column rename keeps the FK working — Postgres rewrites the constraint's
column reference automatically — and the constraint itself is renamed from
fk_entities_country_id to fk_entities_country_code to match.

Idempotent — the rename only runs while the old column name exists.

Revision ID: d0f2b4c6e8a0
Revises: c8e0a2b4d6f8
Create Date: 2026-07-17 00:00:00.000000

"""

from alembic import op
from sqlalchemy import text

revision = "d0f2b4c6e8a0"
down_revision = "c8e0a2b4d6f8"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def _column_exists(bind, table, column):
    return bind.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
    ), {"s": SCHEMA, "t": table, "c": column}).scalar() is not None


def _constraint_exists(bind, table, name):
    return bind.execute(text(
        "SELECT 1 FROM pg_constraint "
        f"WHERE conrelid = ('{SCHEMA}.' || :t)::regclass AND conname = :n"
    ), {"t": table, "n": name}).scalar() is not None


def upgrade():
    bind = op.get_bind()
    if _column_exists(bind, "entities", "country_id"):
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities RENAME COLUMN country_id TO country_code"
        ))
    if _constraint_exists(bind, "entities", "fk_entities_country_id"):
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities RENAME CONSTRAINT "
            "fk_entities_country_id TO fk_entities_country_code"
        ))


def downgrade():
    bind = op.get_bind()
    if _column_exists(bind, "entities", "country_code"):
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities RENAME COLUMN country_code TO country_id"
        ))
    if _constraint_exists(bind, "entities", "fk_entities_country_code"):
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities RENAME CONSTRAINT "
            "fk_entities_country_code TO fk_entities_country_id"
        ))
