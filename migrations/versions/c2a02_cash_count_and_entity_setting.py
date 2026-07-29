"""Step 2: per-denomination count storage, per-entity selection, and backfill.

Two tables, the cash-count mirrors of report_sale_detail and sale_info:

  * report_cash_count    — one row per (report, denomination) holding the
    counted quantity. Replaces the nine fixed columns on
    report_cashcount_draft, the same way report_sale_detail replaced the
    *_sales columns.
  * entity_cash_setting  — which denominations an entity logs. Absent row =
    use the currency default, so a new entity needs no seeding and
    automatically picks up a denomination added to its currency later.

Both names come from the proposed v3 schema (01_schema.sql section F).
entity_cash_setting mirrors v3's entity_sale_setting exactly, including
``is_active`` rather than ``enabled`` — v3 has no cash equivalent of its own,
which is correction 2 in docs/cash_denomination_schema_review.md.

Why not reuse entity_cash_detail_v2 (entity_id + cash_id, already exists and
already FKs both sides): it holds cash_instock, a running quantity-on-hand.
That is a different thing from "does this entity log this denomination" —
overloading it would make a row's absence ambiguous between "not stocked" and
"not tracked", and enabling a denomination would silently invent a stock
figure. It stays untouched.

report_cash_count hangs off report_draft, matching where
report_cashcount_draft already points. A report and its draft share one id
(ending.py:445 creates the revert draft with id=full_report.id), so one set of
rows serves both — the same reason the sales runbook warns against adding a
separate report_draft_id to report_sale_detail. When v3 merges report /
report_draft / report_v2, this FK re-points at report(id) with no data change.

report_cash_count.cash_value is NOT in v3 (correction 3). It snapshots the
face value as at the time of counting: without it, revaluing or retiring a
denomination silently re-totals every published historical report.

The nine columns on report_cashcount_draft are deliberately left in place and
still written by the application. Same transition shape as
get_cash_sales_from_detail: count rows are the source of truth, the columns
are the fallback for reports predating the backfill. They still have five
readers, including the next-day opening balance.

Revision ID: c2a02_cash_count
Revises: c1a01_cash_denom
Create Date: 2026-07-29 00:00:00.000000

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "c2a02_cash_count"
down_revision = "c1a01_cash_denom"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (report_cashcount_draft column, cash_value, type)
# The nine columns that exist today. There is no note200 column — that value
# was parsed into the running total and then dropped on save, so there is
# nothing recoverable to migrate.
COLUMN_TO_DENOMINATION = [
    ("thousand_note",    1000, "note"),
    ("fivehundred_note",  500, "note"),
    ("onehundred_note",   100, "note"),
    ("fifty_note",         50, "note"),
    ("twenty_note",        20, "note"),
    ("ten_note",           10, "note"),
    ("five_coin",           5, "coin"),
    ("two_coin",            2, "coin"),
    ("one_coin",            1, "coin"),
]


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Per-report, per-denomination counts.
    # ------------------------------------------------------------------
    op.create_table(
        "report_cash_count",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("cash_id", sa.Integer(), nullable=False),
        # v3 calls this ``quantity``. Integer: you cannot hold half a note.
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        # Face value as at the time of counting — see the module docstring.
        sa.Column("cash_value", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
        # One count per denomination per report. This is what the application
        # upsert targets, and what stops a double-submit doubling a total.
        sa.UniqueConstraint("report_id", "cash_id", name="report_cash_count_uq"),
        sa.CheckConstraint("quantity >= 0", name="chk_rcc_qty"),
        schema=SCHEMA,
    )

    # The read path: every counted denomination for one report.
    op.create_index(
        "ix_report_cash_count_report",
        "report_cash_count",
        ["report_id"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # 2. Per-entity denomination selection.
    # ------------------------------------------------------------------
    op.create_table(
        "entity_cash_setting",
        sa.Column("entity_id", sa.String(36), primary_key=True),
        sa.Column("cash_id", sa.Integer(), primary_key=True),
        # FALSE hides a currency default this entity never handles (a shop
        # that refuses HK$1,000 notes). A row is written only when the entity
        # diverges from the default — see resolve_denominations_for_entity.
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        # NULL inherits cash_info.display_order. Set only when an entity
        # reorders its own list.
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["cash_id"], [f"{SCHEMA}.cash_info.cash_id"], ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_entity_cash_setting_entity",
        "entity_cash_setting",
        ["entity_id"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # 3. BACKFILL: nine columns -> count rows   ** MOVES REAL DATA **
    # ------------------------------------------------------------------
    # GUARD RULE — per REPORT, not per denomination: only reports with NO
    # count rows at all are backfilled. Same rationale as the sales backfill
    # (s4a04): a per-denomination guard would insert missing ones alongside
    # app-written rows and silently disagree with what is displayed.
    #
    # Only HKD denominations are targeted. Every historical count was entered
    # through a form whose face values were hardcoded HKD, so HKD is what
    # those numbers mean regardless of the entity's currency. Mapping them to
    # another currency's catalog would silently revalue them.
    #
    # Zero and NULL counts are skipped — the columns default to 0 and most
    # reports leave most denominations empty. A missing row reads as zero (the
    # service layer coalesces), so totals are identical either way.
    catalog = {
        (int(value), kind): (cash_id, value)
        for cash_id, value, kind in bind.execute(
            text(
                f"""
                SELECT ci.cash_id, ci.cash_value, ci.type
                FROM {SCHEMA}.cash_info ci
                JOIN {SCHEMA}.currency_info cu ON cu.id = ci.currency_id
                WHERE cu.currency_code = 'HKD'
                """
            )
        )
    }

    missing = [
        f"{value} {kind}"
        for _, value, kind in COLUMN_TO_DENOMINATION
        if (value, kind) not in catalog
    ]
    if missing:
        raise RuntimeError(
            "cash_info is missing HKD denominations required by the backfill: "
            f"{', '.join(missing)} — did c1a01_cash_denom's seed run?"
        )

    insert_count = text(
        f"""
        INSERT INTO {SCHEMA}.report_cash_count
            (id, report_id, cash_id, quantity, cash_value)
        VALUES (:id, :report_id, :cash_id, :quantity, :cash_value)
        ON CONFLICT (report_id, cash_id) DO UPDATE SET
            quantity   = EXCLUDED.quantity,
            cash_value = EXCLUDED.cash_value,
            updated_at = now()
        """
    )

    column_list = ", ".join(f'cd."{col}"' for col, _, _ in COLUMN_TO_DENOMINATION)
    # report_cashcount_draft.report_id FKs report_draft.id, which is what
    # report_cash_count.report_id references — so a draft deleted between the
    # two migrations simply has no row here, and the FK holds.
    rows = bind.execute(
        text(
            f"""
            SELECT cd.report_id, {column_list}
            FROM {SCHEMA}.report_cashcount_draft cd
            WHERE EXISTS (
                SELECT 1 FROM {SCHEMA}.report_draft d WHERE d.id = cd.report_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM {SCHEMA}.report_cash_count x
                WHERE x.report_id = cd.report_id
            )
            """
        )
    ).fetchall()

    written = 0
    for row in rows:
        report_id = row[0]
        for offset, (_, value, kind) in enumerate(COLUMN_TO_DENOMINATION, start=1):
            quantity = row[offset]
            # NULL and 0 both mean "none counted" — skip; a missing row reads
            # as zero.
            if not quantity:
                continue
            cash_id, cash_value = catalog[(value, kind)]
            bind.execute(
                insert_count,
                {
                    "id": str(uuid.uuid4()),
                    "report_id": report_id,
                    "cash_id": cash_id,
                    "quantity": int(quantity),
                    "cash_value": cash_value,
                },
            )
            written += 1

    print(
        f"backfilled {written} cash count row(s) from "
        f"{len(rows)} report_cashcount_draft row(s)"
    )


def downgrade():
    # The nine columns were never cleared, so dropping these tables loses
    # nothing that is not still recoverable from them.
    op.drop_index(
        "ix_entity_cash_setting_entity", "entity_cash_setting", schema=SCHEMA
    )
    op.drop_table("entity_cash_setting", schema=SCHEMA)
    op.drop_index(
        "ix_report_cash_count_report", "report_cash_count", schema=SCHEMA
    )
    op.drop_table("report_cash_count", schema=SCHEMA)
