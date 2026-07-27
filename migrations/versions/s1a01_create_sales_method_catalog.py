"""Step 1: create the sales_method catalog and seed the 11 canonical methods.

The catalog that ``sale_info`` will point at — the sales equivalent of
``entity_function``. Adding a new sales method after this lands should be a
single INSERT here, with no schema change and no code change.

Row scoping mirrors the "global vs per-entity" split used elsewhere:
  * ``entity_id IS NULL``  → global catalog row, available to every entity
  * ``entity_id`` set      → custom method owned by that one entity

``legacy_column`` is the bridge back to the physical ``*_sales`` columns on
report / report_draft. It exists ONLY to drive the Step 3.5 data backfill and
is dropped in Step 5 — a new method must never need one, or we're back to
editing schema per method.

Seeded ``deliveroo_sales`` with is_active = FALSE: it is already filtered out
of the payment-method list (blueprints/entity/services/payment_methods.py:47)
but still exists as a column and still carries historical amounts.

Cash is deliberately NOT seeded. ``cash_sales`` is a separate concept — it is
read from report_draft.cash_sales, has its own ``type == "Cash"`` branch in
calculate_sales_from_report_sale_detail, and is absent from the per-entity seed
in create_default_entity_settings. It keeps its column.

UUIDs are generated in Python rather than via gen_random_uuid() so this runs on
any DB role / search_path / Postgres version (same rationale as
b8f3a2c1d4e5_seed_modules_and_backfill).

Idempotent: catalog rows upsert on (entity_id, code), so re-running refreshes
display metadata without churning PKs or creating duplicates.

Revision ID: s1a01_sales_method
Revises: c2e4a6b8d0f1
Create Date: 2026-07-27 00:00:00.000000

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "s1a01_sales_method"
down_revision = "c2e4a6b8d0f1"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (code, display name, type, legacy_column, is_active, display_order)
# Sourced from create_default_entity_settings in
# blueprints/entity/services/shared.py:118-178 — keep in sync.
CANONICAL_METHODS = [
    ("VISA",      "Visa",       "Electronic", "visa_sales",      True,  1),
    ("ALIPAY",    "Alipay",     "Electronic", "alipay_sales",    True,  2),
    ("WECHAT",    "WeChat Pay", "Electronic", "wechat_sales",    True,  3),
    ("MASTER",    "Mastercard", "Electronic", "master_sales",    True,  4),
    ("UNIONPAY",  "UnionPay",   "Electronic", "unionpay_sales",  True,  5),
    ("AMEX",      "Amex",       "Electronic", "amex_sales",      True,  6),
    ("OCTOPUS",   "Octopus",    "Electronic", "octopus_sales",   True,  7),
    ("FOODPANDA", "Food Panda", "Delivery",   "foodpanda_sales", True,  1),
    ("KEETA",     "Keeta",      "Delivery",   "keeta_sales",     True,  2),
    ("OPENRICE",  "OpenRice",   "Delivery",   "openrice_sales",  True,  3),
    ("DELIVEROO", "Deliveroo",  "Delivery",   "deliveroo_sales", False, 4),
]


def upgrade():
    op.create_table(
        "sales_method",
        sa.Column("id", sa.String(36), primary_key=True),
        # NULL = global catalog row; set = custom method for that entity.
        sa.Column(
            "entity_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        # 'Electronic' | 'Delivery' — matches sale_info.type values.
        sa.Column("type", sa.String(20), nullable=False),
        # Transition bridge to the physical *_sales columns. Dropped in Step 5.
        sa.Column("legacy_column", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        schema=SCHEMA,
    )

    # NULLS NOT DISTINCT so the 11 global rows (entity_id IS NULL) can't be
    # duplicated — without it Postgres treats every NULL as distinct and the
    # constraint would not protect the global catalog at all.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.sales_method
        ADD CONSTRAINT uq_sales_method_entity_code
        UNIQUE NULLS NOT DISTINCT (entity_id, code)
        """
    )

    # Backfill lookups hit legacy_column; reads filter on is_active.
    op.create_index(
        "ix_sales_method_legacy_column",
        "sales_method",
        ["legacy_column"],
        schema=SCHEMA,
    )

    bind = op.get_bind()
    insert_method = text(
        f"""
        INSERT INTO {SCHEMA}.sales_method
            (id, entity_id, code, name, type, legacy_column,
             is_active, display_order, created_at, updated_at)
        VALUES
            (:id, NULL, :code, :name, :type, :legacy_column,
             :is_active, :display_order, NOW(), NOW())
        ON CONFLICT (entity_id, code) DO UPDATE
        SET name          = EXCLUDED.name,
            type          = EXCLUDED.type,
            legacy_column = EXCLUDED.legacy_column,
            is_active     = EXCLUDED.is_active,
            display_order = EXCLUDED.display_order,
            updated_at    = NOW()
        """
    )
    for code, name, mtype, legacy_column, is_active, order in CANONICAL_METHODS:
        bind.execute(
            insert_method,
            {
                "id": str(uuid.uuid4()),
                "code": code,
                "name": name,
                "type": mtype,
                "legacy_column": legacy_column,
                "is_active": is_active,
                "display_order": order,
            },
        )


def downgrade():
    op.drop_index("ix_sales_method_legacy_column", "sales_method", schema=SCHEMA)
    op.drop_table("sales_method", schema=SCHEMA)
