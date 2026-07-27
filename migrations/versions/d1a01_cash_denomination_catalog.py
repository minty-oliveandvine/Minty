"""Step 1: turn cash_info into a real denomination catalog and seed HKD.

The cash-count equivalent of s1a01's sales_method catalog. Adding a new
denomination after this lands should be a single INSERT here, with no schema
change and no code change — today it takes a migration, a model column, a
template edit and a new hardcoded multiplier in report_cash_count.

cash_info has existed since 0001_full_schema but was never seeded and is read
by nothing: the nine face values live as literals in
blueprints/report/routes/cash_count.py:300-309. This migration makes the table
the source of truth for those values.

Merge point. The two heads (s4a04_backfill_sales, e5b7d9f1a3c6) forked at
b1d3f5a7c9e2 and never rejoined. This work needs both: country_info's char(2)
country_code from the currency branch, and the catalog conventions established
by the sales branch. Merging here rather than in a separate empty revision
keeps the chain readable.

Three fixes bundled in, because seeding is impossible without them:

  * country_code varchar(3) -> char(2). c8e0a2b4d6f8 rebuilt country_info with
    a char(2) PK and restored cash_info's FK verbatim (varchar -> char(2) is a
    valid reference, so nothing broke), but the column still can't hold a
    clean 'HK' comparison. Widening rows exist to migrate — the table is
    empty — so this is a plain type change.

  * cash_id integer -> identity. It was a bare integer PK with no default, so
    every INSERT had to supply its own id. Adding a denomination from the app
    would have needed a MAX(cash_id)+1 race.

  * display_order + is_active, matching sales_method. Order is what the cash
    count form renders in (high notes first, then coins); is_active retires a
    denomination globally without deleting the historical counts that
    reference it.

The seed is scoped to exactly the nine denominations the cash count form can
post today. The HK$200 note and the HK$10 coin are real currency but have no
working form field, so seeding them would list denominations a cashier cannot
actually record. They go in when the form renders from this catalog.

Idempotent: rows upsert on (country_code, cash_value, type), so re-running
refreshes display metadata without churning cash_ids that counts point at.

Revision ID: d1a01_cash_denom
Revises: s4a04_backfill_sales, e5b7d9f1a3c6
Create Date: 2026-07-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "d1a01_cash_denom"
down_revision = ("s4a04_backfill_sales", "e5b7d9f1a3c6")
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (cash_value, type, cash_name, desc, display_order)
# Face values sourced from the hardcoded multipliers in
# blueprints/report/routes/cash_count.py:300-309. Notes descend, then coins
# descend; display_order is global across both so the form renders one
# continuous list.
#
# These nine are EXACTLY what the cash count form can post today — the nine
# actual_cash[...] fields in templates/report/cash_count.html:237-245. The
# catalog and the form agree, so nothing is offered that cannot be recorded.
#
# Deliberately omitted until the form renders from this catalog:
#   * HK$200 note — parsed by cash_count.py and added to the running total,
#     but no form field and no column, so it is dropped on save.
#   * HK$10 coin — the template's '10coins' input has an id but no name, so
#     it never posts.
# Both are one INSERT away once the form loops over this table.
HKD_DENOMINATIONS = [
    (1000.0, "note", "$1,000", "HK$1,000 note", 1),
    (500.0,  "note", "$500",   "HK$500 note",   2),
    (100.0,  "note", "$100",   "HK$100 note",   3),
    (50.0,   "note", "$50",    "HK$50 note",    4),
    (20.0,   "note", "$20",    "HK$20 note",    5),
    (10.0,   "note", "$10",    "HK$10 note",    6),
    (5.0,    "coin", "$5",     "HK$5 coin",     7),
    (2.0,    "coin", "$2",     "HK$2 coin",     8),
    (1.0,    "coin", "$1",     "HK$1 coin",     9),
]


def _column_type(bind, table, column):
    return bind.execute(
        text(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
              AND column_name = :column
            """
        ),
        {"schema": SCHEMA, "table": table, "column": column},
    ).scalar()


def _has_column(bind, table, column):
    return _column_type(bind, table, column) is not None


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Reshape cash_info into a usable catalog.
    # ------------------------------------------------------------------
    # The FK to country_info(country_code) has to come off before the type
    # change and go back after — Postgres will not alter a column another
    # constraint depends on.
    fk_name = bind.execute(
        text(
            f"""
            SELECT c.conname FROM pg_constraint c
            WHERE c.contype = 'f'
              AND c.conrelid = '{SCHEMA}.cash_info'::regclass
              AND c.confrelid = '{SCHEMA}.country_info'::regclass
            """
        )
    ).scalar()
    if fk_name:
        op.drop_constraint(fk_name, "cash_info", schema=SCHEMA, type_="foreignkey")

    if _column_type(bind, "cash_info", "country_code") != "character":
        # Empty table, but TRIM guards the case where a deployment seeded it
        # by hand with a padded or alpha-3 code.
        op.execute(
            f"""
            ALTER TABLE {SCHEMA}.cash_info
            ALTER COLUMN country_code TYPE char(2)
            USING LEFT(TRIM(country_code), 2)
            """
        )

    op.create_foreign_key(
        "fk_cash_info_country_code",
        "cash_info",
        "country_info",
        ["country_code"],
        ["country_code"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    # Bare integer PK with no default — make it self-assigning so the app can
    # insert a denomination without racing on MAX(cash_id)+1.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.cash_info
        ALTER COLUMN cash_id ADD GENERATED BY DEFAULT AS IDENTITY
        """
    )

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

    # A country cannot have two rows for the same face value of the same kind.
    # This is also what the seed upserts on.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.cash_info
        ADD CONSTRAINT uq_cash_info_country_value_type
        UNIQUE (country_code, cash_value, type)
        """
    )

    # The cash count form's read path: denominations for one country, in order.
    op.create_index(
        "ix_cash_info_country_order",
        "cash_info",
        ["country_code", "display_order"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # 2. Seed HKD.
    # ------------------------------------------------------------------
    # Guard on country_info actually having HK — a2c4e6b8d0f2 seeds it, but a
    # database restored from a partial dump would fail the FK with a much
    # less obvious error than this.
    if not bind.execute(
        text(f"SELECT 1 FROM {SCHEMA}.country_info WHERE country_code = 'HK'")
    ).scalar():
        raise RuntimeError(
            "country_info has no 'HK' row — run the a2c4e6b8d0f2 country seed "
            "before this migration"
        )

    insert_denomination = text(
        f"""
        INSERT INTO {SCHEMA}.cash_info
            (country_code, type, cash_value, cash_name, "desc",
             display_order, is_active)
        VALUES
            ('HK', :type, :cash_value, :cash_name, :desc,
             :display_order, TRUE)
        ON CONFLICT (country_code, cash_value, type) DO UPDATE SET
            cash_name     = EXCLUDED.cash_name,
            "desc"        = EXCLUDED."desc",
            display_order = EXCLUDED.display_order
        """
    )
    for value, kind, name, desc, order in HKD_DENOMINATIONS:
        bind.execute(
            insert_denomination,
            {
                "type": kind,
                "cash_value": value,
                "cash_name": name,
                "desc": desc,
                "display_order": order,
            },
        )


def downgrade():
    bind = op.get_bind()

    # Only remove the rows this migration created. A denomination an entity
    # added afterwards is user data — leave it, and leave the columns it needs.
    bind.execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.cash_info
            WHERE country_code = 'HK'
              AND (cash_value, type) IN (
                  {", ".join("(%s, '%s')" % (v, t) for v, t, _, _, _ in HKD_DENOMINATIONS)}
              )
            """
        )
    )

    remaining = bind.execute(
        text(f"SELECT COUNT(*) FROM {SCHEMA}.cash_info")
    ).scalar()
    if remaining:
        # Custom denominations survive, so the catalog columns must too.
        print(
            f"NOTE: keeping cash_info.display_order / is_active — {remaining} "
            "custom denomination row(s) still present"
        )
        return

    op.drop_index("ix_cash_info_country_order", "cash_info", schema=SCHEMA)
    op.execute(
        f"ALTER TABLE {SCHEMA}.cash_info "
        f"DROP CONSTRAINT IF EXISTS uq_cash_info_country_value_type"
    )
    op.drop_column("cash_info", "is_active", schema=SCHEMA)
    op.drop_column("cash_info", "display_order", schema=SCHEMA)
    op.execute(
        f"ALTER TABLE {SCHEMA}.cash_info "
        f"ALTER COLUMN cash_id DROP IDENTITY IF EXISTS"
    )
    # country_code is left as char(2). Reverting it to varchar(3) would not
    # restore anything meaningful — the column was only ever varchar by
    # accident — and would re-break the FK comparison.
