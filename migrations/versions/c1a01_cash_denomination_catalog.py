"""Step 1: turn cash_info into a denomination catalog keyed on currency.

The cash-count equivalent of s1a01's sales_method catalog. Adding a
denomination after this lands should be a single INSERT here, with no schema
change and no code change — today it takes a migration, a model column, a
template edit, and a new hardcoded multiplier in FOUR separate places
(cash_count.py:300-309 and ending.py:666, 1157, 1279).

cash_info has existed since 0001_full_schema but was never seeded and is read
by nothing.

NAMING follows the proposed v3 schema (01_schema.sql section F) so this is a
step TOWARD that design, not away from it. Deviations forced by the live
schema, each resolved at the v3 cutover:

  * cash_id stays an integer PK (v3 uses a UUID ``id``). Rekeying would break
    entity_cash_detail_v2 and report_cash_detail, which both FK it.
  * ``desc`` is not renamed to ``description`` — the existing CashInfo model
    references it.
  * ``type`` stays VARCHAR rather than becoming a cash_type enum.

Two corrections applied on top of v3 — see
docs/cash_denomination_schema_review.md:

  * UNIQUE includes ``type``. v3 proposes UNIQUE (currency_id, cash_value),
    which silently blocks HKD's $10 note and $10 coin from coexisting.
  * is_active + display_order are added. v3 omits both, so a withdrawn note
    could never be retired — deletion is blocked by the RESTRICT FK on
    report_cash_count.

Merge point. The two heads (s4a04_backfill_sales, e5b7d9f1a3c6) forked at
b1d3f5a7c9e2 and never rejoined. This work needs both: currency_info from the
currency branch, and the catalog conventions from the sales branch.

Idempotent: rows upsert on (currency_id, cash_value, type), so re-running
refreshes display metadata without churning cash_ids that counts point at.

Revision ID: c1a01_cash_denom
Revises: s4a04_backfill_sales, e5b7d9f1a3c6
Create Date: 2026-07-29 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "c1a01_cash_denom"
down_revision = ("s4a04_backfill_sales", "e5b7d9f1a3c6")
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (cash_value, type, cash_name, desc, display_order)
# Face values sourced from the hardcoded multipliers in
# blueprints/report/routes/cash_count.py:300-309.
#
# These nine are EXACTLY what the cash count form can post today — the nine
# actual_cash[...] fields in templates/report/cash_count.html:237-245. The
# catalog and the form agree, so nothing is offered that cannot be recorded.
#
# Deliberately omitted until the form renders from this catalog:
#   * HK$200 note — no form field and no column; the value was dropped on save.
#   * HK$10 coin  — the template's '10coins' input has an id but no name, so
#     it adds to the total the cashier sees and never posts.
# Both are one INSERT away afterwards. The coin is only expressible because
# ``type`` is part of the uniqueness constraint below.
HKD_DENOMINATIONS = [
    (1000, "note", "$1,000", "HK$1,000 note", 1),
    (500,  "note", "$500",   "HK$500 note",   2),
    (100,  "note", "$100",   "HK$100 note",   3),
    (50,   "note", "$50",    "HK$50 note",    4),
    (20,   "note", "$20",    "HK$20 note",    5),
    (10,   "note", "$10",    "HK$10 note",    6),
    (5,    "coin", "$5",     "HK$5 coin",     7),
    (2,    "coin", "$2",     "HK$2 coin",     8),
    (1,    "coin", "$1",     "HK$1 coin",     9),
]


def _has_column(bind, table, column):
    return bind.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
              AND column_name = :column
            """
        ),
        {"schema": SCHEMA, "table": table, "column": column},
    ).scalar() is not None


def _has_constraint(bind, name):
    return bind.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": name}
    ).scalar() is not None


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Re-key from country_code to currency_id.
    # ------------------------------------------------------------------
    # A denomination is a property of the CURRENCY, not the country: two
    # countries sharing a currency would otherwise duplicate every row, and a
    # revaluation would have to touch each copy. The legacy country_code
    # column exists only because that FK already existed on the table.
    #
    # country_code is left in place so nothing that still reads it breaks;
    # the v3 cutover drops it.
    if not _has_column(bind, "cash_info", "currency_id"):
        op.add_column(
            "cash_info",
            sa.Column("currency_id", UUID(as_uuid=False), nullable=True),
            schema=SCHEMA,
        )

    if not _has_constraint(bind, "fk_cash_info_currency"):
        op.create_foreign_key(
            "fk_cash_info_currency",
            "cash_info",
            "currency_info",
            ["currency_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="RESTRICT",
        )

    # Backfill any pre-existing rows. The table is expected to be empty, but a
    # hand-seeded deployment must not be stranded with a NULL currency_id.
    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.cash_info ci
            SET currency_id = co.currency_id
            FROM {SCHEMA}.country_info co
            WHERE ci.currency_id IS NULL
              AND ci.country_code IS NOT NULL
              AND TRIM(ci.country_code) = co.country_code
            """
        )
    )

    # ------------------------------------------------------------------
    # 2. Catalog columns.
    # ------------------------------------------------------------------
    if not _has_column(bind, "cash_info", "display_order"):
        op.add_column(
            "cash_info",
            sa.Column(
                "display_order", sa.Integer(), nullable=False, server_default="999"
            ),
            schema=SCHEMA,
        )
    if not _has_column(bind, "cash_info", "is_active"):
        op.add_column(
            "cash_info",
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            schema=SCHEMA,
        )

    # Uniqueness INCLUDING type — see the module docstring.
    if not _has_constraint(bind, "uq_cash_info_currency_value_type"):
        op.create_unique_constraint(
            "uq_cash_info_currency_value_type",
            "cash_info",
            ["currency_id", "cash_value", "type"],
            schema=SCHEMA,
        )

    # ------------------------------------------------------------------
    # 3. cash_id must self-assign.
    # ------------------------------------------------------------------
    # Otherwise adding a denomination needs a MAX(cash_id)+1 race. v3 uses
    # gen_random_uuid() and avoids this entirely.
    #
    # Only convert a column with NO default: a live database may already have
    # it as serial (a plain DEFAULT nextval), which is functionally
    # equivalent — and Postgres rejects adding an identity on top of an
    # existing default with "column ... already has a default value".
    has_default, is_identity = bind.execute(
        text(
            f"""
            SELECT a.atthasdef, a.attidentity <> ''
            FROM pg_attribute a
            WHERE a.attrelid = '{SCHEMA}.cash_info'::regclass
              AND a.attname = 'cash_id'
            """
        )
    ).one()
    if not has_default and not is_identity:
        op.execute(
            f"""
            ALTER TABLE {SCHEMA}.cash_info
            ALTER COLUMN cash_id ADD GENERATED BY DEFAULT AS IDENTITY
            """
        )

    # The cash count form's read path: denominations for one currency, in order.
    op.create_index(
        "ix_cash_info_currency_order",
        "cash_info",
        ["currency_id", "display_order"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # 4. Seed HKD.
    # ------------------------------------------------------------------
    # Fails loudly rather than tripping an opaque FK violation.
    hkd = bind.execute(
        text(
            f"SELECT id FROM {SCHEMA}.currency_info WHERE currency_code = 'HKD'"
        )
    ).scalar()
    if not hkd:
        raise RuntimeError(
            "currency_info has no HKD row — run the e5b7d9f1a3c6 currency seed "
            "before this migration"
        )

    insert_denomination = text(
        f"""
        INSERT INTO {SCHEMA}.cash_info
            (currency_id, country_code, type, cash_value, cash_name, "desc",
             display_order, is_active)
        VALUES
            (:currency_id, 'HK', :type, :cash_value, :cash_name, :desc,
             :display_order, TRUE)
        ON CONFLICT (currency_id, cash_value, type) DO UPDATE SET
            cash_name     = EXCLUDED.cash_name,
            "desc"        = EXCLUDED."desc",
            display_order = EXCLUDED.display_order
        """
    )
    for value, kind, name, desc, order in HKD_DENOMINATIONS:
        bind.execute(
            insert_denomination,
            {
                "currency_id": hkd,
                "type": kind,
                "cash_value": value,
                "cash_name": name,
                "desc": desc,
                "display_order": order,
            },
        )


def downgrade():
    bind = op.get_bind()

    # Only remove the rows this migration created. A denomination added
    # afterwards is user data — leave it, and leave the columns it needs.
    hkd = bind.execute(
        text(f"SELECT id FROM {SCHEMA}.currency_info WHERE currency_code = 'HKD'")
    ).scalar()
    if hkd:
        values = ", ".join(
            "(%s, '%s')" % (v, t) for v, t, _, _, _ in HKD_DENOMINATIONS
        )
        bind.execute(
            text(
                f"""
                DELETE FROM {SCHEMA}.cash_info
                WHERE currency_id = :hkd
                  AND (cash_value, type) IN ({values})
                """
            ),
            {"hkd": hkd},
        )

    remaining = bind.execute(
        text(f"SELECT COUNT(*) FROM {SCHEMA}.cash_info")
    ).scalar()
    if remaining:
        # Custom denominations survive, so the catalog columns must too.
        print(
            f"NOTE: keeping cash_info catalog columns — {remaining} custom "
            "denomination row(s) still present"
        )
        return

    op.drop_index("ix_cash_info_currency_order", "cash_info", schema=SCHEMA)
    op.execute(
        f"ALTER TABLE {SCHEMA}.cash_info "
        f"DROP CONSTRAINT IF EXISTS uq_cash_info_currency_value_type"
    )
    op.drop_column("cash_info", "is_active", schema=SCHEMA)
    op.drop_column("cash_info", "display_order", schema=SCHEMA)
    op.execute(
        f"ALTER TABLE {SCHEMA}.cash_info "
        f"DROP CONSTRAINT IF EXISTS fk_cash_info_currency"
    )
    op.drop_column("cash_info", "currency_id", schema=SCHEMA)
    # DROP IDENTITY IF EXISTS is a no-op on a serial column, so a database
    # that already had a default keeps it — upgrade() left that case alone and
    # downgrade must not strip it.
    op.execute(
        f"ALTER TABLE {SCHEMA}.cash_info "
        f"ALTER COLUMN cash_id DROP IDENTITY IF EXISTS"
    )
