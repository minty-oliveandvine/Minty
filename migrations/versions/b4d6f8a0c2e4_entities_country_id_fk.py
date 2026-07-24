"""Rename entities.country_code -> country_id and FK it to country_info.

Mirrors the currency change (entities.currency_code -> currency_id): the
entities table now references the country registry by uuid instead of
carrying the raw ISO alpha-2 code.

Steps:
  1. rename ``entities.country_code`` to ``country_id`` and widen it to
     varchar(36) so it can hold a uuid;
  2. remap existing values: an entity holding e.g. 'HK' is pointed at the
     ``country_info.country_id`` uuid of the row whose ``country_code`` is
     'HK' (resolved at migration time, so it works regardless of which uuids
     the country seed generated);
  3. clear any leftover value that matches neither a country code nor an
     existing country uuid — such rows would break the FK;
  4. add ``fk_entities_country_id`` FOREIGN KEY -> country_info(country_id)
     if it doesn't exist yet.

Idempotent — re-running is a no-op: the rename is guarded, already-remapped
uuid values match no country_code so step 2 skips them, and step 3 leaves
valid uuids alone.

Revision ID: b4d6f8a0c2e4
Revises: a2c4e6b8d0f2
Create Date: 2026-07-15 00:00:00.000000

"""

from alembic import op
from sqlalchemy import text

revision = "b4d6f8a0c2e4"
down_revision = "a2c4e6b8d0f2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    bind = op.get_bind()

    # 1. Rename (guarded) + widen to hold a uuid.
    cols = {
        row[0]
        for row in bind.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{SCHEMA}' AND table_name = 'entities'"
        ))
    }
    if "country_code" in cols and "country_id" not in cols:
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities "
            "RENAME COLUMN country_code TO country_id"
        ))
    bind.execute(text(
        f"ALTER TABLE {SCHEMA}.entities "
        "ALTER COLUMN country_id TYPE character varying(36)"
    ))

    # 2. Remap ISO alpha-2 values to the registry uuid ('HK' -> uuid of the
    #    country_info row whose country_code = 'HK').
    remapped = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET country_id = co.country_id
        FROM {SCHEMA}.country_info co
        WHERE e.country_id = co.country_code
    """)).rowcount

    # 3. Anything left that isn't a valid country uuid can't satisfy the FK.
    cleared = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET country_id = NULL
        WHERE e.country_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.country_info co
              WHERE co.country_id = e.country_id
          )
    """)).rowcount
    print(f"entities country remap: {remapped} remapped, {cleared} cleared")

    # 4. FK to the country registry (create only if missing).
    bind.execute(text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_entities_country_id'
                  AND conrelid = '{SCHEMA}.entities'::regclass
            ) THEN
                ALTER TABLE {SCHEMA}.entities
                ADD CONSTRAINT fk_entities_country_id
                FOREIGN KEY (country_id)
                REFERENCES {SCHEMA}.country_info(country_id);
            END IF;
        END $$;
    """))


def downgrade():
    # Intentional no-op — reversing would replace uuid references with raw
    # ISO codes and drop the integrity guarantee the FK provides.
    pass
