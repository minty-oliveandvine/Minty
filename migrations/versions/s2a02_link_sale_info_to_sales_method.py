"""Step 2: link entity_sale_setting to the sale_info catalog.

Adds ``entity_sale_setting.sale_info_id`` and backfills it — the sales equivalent of
``entity_function_map.entity_function_id``.

What is deliberately NOT touched:
  * ``sale_id``   — this is entity_sale_setting's PRIMARY KEY, not a method ref.
    report_sale_detail.sale_id is a FK pointing at it. Renaming or repurposing
    it would break that FK plus every filter_by(sale_id=...) in the codebase.
  * ``sale_name`` — entities can rename a method for themselves via
    replace_sales_methods (payment_methods.py:309). The catalog holds the
    canonical name; entity_sale_setting holds this entity's label. Same reason
    entity_function_map does not duplicate entity_function.function_name.
  * ``value_name`` / ``type`` — these move to the catalog conceptually, but are
    kept until Step 5 so this migration changes no behaviour and can be rolled
    back cleanly.

Custom methods: replace_sales_methods derives value_name as
``name.lower().replace(" ", "_") + "_sales"``, so an entity that typed
"Tap & Go" has value_name 'tap_&_go_sales' — matching no catalog row and no
physical column. Those get a per-entity catalog row minted here
(entity_id set, legacy_column NULL) so no row is left with a NULL FK.

Duplicate entity_sale_setting rows exist in production (hence max(sale_id) at
payment_methods.py:38-50). The backfill is a plain UPDATE keyed on
value_name → legacy_column, so duplicates each resolve to the same catalog row
— no row multiplication.

The FK is left NULLABLE. Making it NOT NULL is a Step 5 concern, once the
application is guaranteed to always populate it.

Revision ID: s2a02_sale_info_fk
Revises: s1a01_sales_method
Create Date: 2026-07-27 00:00:00.000000

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "s2a02_sale_info_fk"
down_revision = "s1a01_sales_method"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "entity_sale_setting",
        sa.Column("sale_info_id", sa.String(36), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_entity_sale_setting_sale_info",
        "entity_sale_setting",
        "sale_info",
        ["sale_info_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        # RESTRICT: a catalog row that entities are actively using must not be
        # deletable out from under them. Deactivate it (is_active = FALSE)
        # instead — that is what the flag is for.
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_entity_sale_setting_sale_info_id",
        "entity_sale_setting",
        ["sale_info_id"],
        schema=SCHEMA,
    )

    bind = op.get_bind()

    # 1. Canonical rows: value_name matches a global catalog row's legacy_column.
    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_sale_setting si
            SET sale_info_id = sm.id
            FROM {SCHEMA}.sale_info sm
            WHERE sm.entity_id IS NULL
              AND sm.legacy_column = si.value_name
              AND si.sale_info_id IS NULL
            """
        )
    )

    # 2. Custom rows: anything still unmatched is an entity-invented method.
    #    Mint one per-entity catalog row per distinct (entity_id, value_name).
    #    code is derived from value_name (strip the '_sales' suffix, upper,
    #    non-alphanumerics to '_') and prefixed so it can never collide with a
    #    canonical code that might be added to the global catalog later.
    orphans = bind.execute(
        text(
            f"""
            SELECT DISTINCT entity_id, value_name, type,
                   MIN(sale_name) AS sale_name
            FROM {SCHEMA}.entity_sale_setting
            WHERE sale_info_id IS NULL
              AND entity_id IS NOT NULL
              AND value_name IS NOT NULL
            GROUP BY entity_id, value_name, type
            """
        )
    ).fetchall()

    insert_custom = text(
        f"""
        INSERT INTO {SCHEMA}.sale_info
            (id, entity_id, code, name, type, legacy_column,
             is_active, display_order, created_at, updated_at)
        VALUES
            (:id, :entity_id, :code, :name, :type, NULL, TRUE, 0, NOW(), NOW())
        ON CONFLICT (entity_id, code) DO NOTHING
        """
    )
    link_custom = text(
        f"""
        UPDATE {SCHEMA}.entity_sale_setting si
        SET sale_info_id = sm.id
        FROM {SCHEMA}.sale_info sm
        WHERE sm.entity_id = :entity_id
          AND sm.code      = :code
          AND si.entity_id = :entity_id
          AND si.value_name = :value_name
          AND si.sale_info_id IS NULL
        """
    )

    for entity_id, value_name, mtype, sale_name in orphans:
        base = (value_name or "").removesuffix("_sales")
        code = "CUSTOM_" + "".join(
            ch if ch.isalnum() else "_" for ch in base
        ).upper()[:42]
        bind.execute(
            insert_custom,
            {
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "code": code,
                "name": sale_name or base or "Custom",
                # type is NOT NULL on the catalog; the per-entity type is not,
                # so fall back to Electronic rather than failing the insert.
                "type": mtype or "Electronic",
            },
        )
        bind.execute(
            link_custom,
            {"entity_id": entity_id, "code": code, "value_name": value_name},
        )


def downgrade():
    # Custom catalog rows minted above are left in place — they are referenced
    # by nothing once the column is gone, and dropping them would lose the only
    # record of an entity's invented method names.
    op.drop_index("ix_entity_sale_setting_sale_info_id", "entity_sale_setting", schema=SCHEMA)
    op.drop_constraint(
        "fk_entity_sale_setting_sale_info", "entity_sale_setting", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("entity_sale_setting", "sale_info_id", schema=SCHEMA)
