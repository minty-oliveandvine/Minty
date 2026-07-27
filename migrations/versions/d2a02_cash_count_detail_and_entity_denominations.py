"""Step 2: per-denomination count storage + per-entity denomination choice.

Two tables, the cash-count mirrors of report_sale_detail and sale_info:

  * report_cashcount_detail — one row per (report, denomination) holding the
    counted quantity. Replaces the nine fixed columns on
    report_cashcount_draft, the same way report_sale_detail replaced the
    *_sales columns.

  * entity_cash_denomination — which denominations an entity actually logs.
    Absent row = use the country default, so a new entity needs no seeding
    and automatically picks up a denomination added to its country later.

Why not reuse entity_cash_detail_v2 (entity_id + cash_id, already exists and
already FKs both sides): it holds cash_instock, a running quantity-on-hand.
That is a different thing from "does this entity log this denomination" —
overloading it would mean a row's absence is ambiguous between "not stocked"
and "not tracked", and enabling a denomination would silently invent a stock
figure. It stays untouched.

report_cashcount_detail hangs off report_draft, matching where
report_cashcount_draft already points. Cash counts are entered during the
draft flow and the draft id is carried onto the posted report, so the id
stays valid after submission — this is the same id report_sale_detail keys
on. CASCADE matches report_cashcount_draft's existing delete behaviour, which
tests/test_delete_report_cleanup.py already covers.

The nine columns on report_cashcount_draft are deliberately left in place and
still written by Step 4. Same transition shape as get_cash_sales_from_detail:
detail table is the source of truth, columns are the fallback for rows
predating the backfill. A later step drops them once no fallback read remains.

Revision ID: d2a02_cashcount_detail
Revises: d1a01_cash_denom
Create Date: 2026-07-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d2a02_cashcount_detail"
down_revision = "d1a01_cash_denom"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    # ------------------------------------------------------------------
    # Per-report, per-denomination counts.
    # ------------------------------------------------------------------
    op.create_table(
        "report_cashcount_detail",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("cash_id", sa.Integer(), nullable=False),
        # Quantity of this denomination counted. Integer: you cannot hold
        # half a note. (report_cashcount_draft used Integer for the note and
        # coin columns too — only the derived totals were Float.)
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        # Face value at the time of counting. Denormalised on purpose: if a
        # denomination is ever revalued or retired, historical reports must
        # still total to what was actually counted that day. Step 4 writes it
        # from cash_info.cash_value.
        sa.Column("cash_value", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], [f"{SCHEMA}.report_draft.id"], ondelete="CASCADE"
        ),
        # RESTRICT, not CASCADE: deleting a denomination must never silently
        # delete the historical counts that reference it. Retire it with
        # is_active = FALSE instead.
        sa.ForeignKeyConstraint(
            ["cash_id"], [f"{SCHEMA}.cash_info.cash_id"], ondelete="RESTRICT"
        ),
        # One count per denomination per report. This is what the Step 4
        # upsert targets, and what stops a double-submit doubling a total.
        sa.UniqueConstraint(
            "report_id", "cash_id", name="uq_cashcount_detail_report_cash"
        ),
        schema=SCHEMA,
    )

    # The read path: every counted denomination for one report.
    op.create_index(
        "ix_cashcount_detail_report",
        "report_cashcount_detail",
        ["report_id"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # Per-entity denomination choice.
    # ------------------------------------------------------------------
    op.create_table(
        "entity_cash_denomination",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("cash_id", sa.Integer(), nullable=False),
        # FALSE hides a country default this entity never handles (a shop
        # that refuses HK$1,000 notes). A row is only written when the entity
        # diverges from the default — see resolve_denominations_for_entity.
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        # NULL = inherit cash_info.display_order. Set only when an entity
        # reorders its own list.
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(), server_default=sa.func.current_timestamp()
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["cash_id"], [f"{SCHEMA}.cash_info.cash_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "entity_id", "cash_id", name="uq_entity_cash_denomination"
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_entity_cash_denomination_entity",
        "entity_cash_denomination",
        ["entity_id"],
        schema=SCHEMA,
    )


def downgrade():
    op.drop_index(
        "ix_entity_cash_denomination_entity",
        "entity_cash_denomination",
        schema=SCHEMA,
    )
    op.drop_table("entity_cash_denomination", schema=SCHEMA)
    op.drop_index(
        "ix_cashcount_detail_report", "report_cashcount_detail", schema=SCHEMA
    )
    op.drop_table("report_cashcount_detail", schema=SCHEMA)
