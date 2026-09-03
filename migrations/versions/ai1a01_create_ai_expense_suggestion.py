"""AI STAGE 1 — create ai_expense_suggestion, the extraction audit table

Revision ID: ai1a01_ai_expense_suggestion
Revises: s5a05_drop_legacy_sales
Create Date: 2026-09-03

=============================================================================
WHAT THIS IS

One new table. Nothing existing is touched — no column added, no constraint
changed, no row rewritten.

    pettycashv2.ai_expense_suggestion

One row per extraction attempt on the Add New Expense card, successful or not.
It holds metadata, token usage and the post-validation suggested values. It
does NOT hold receipt bytes, the prompt, the raw model reply, or any
credential (plan §10.2, §8.4).

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

Purely additive. Old code ignores a table it has never heard of, CREATE TABLE
takes no lock on anything that already exists, and nothing reads the table
until the extract endpoint ships behind EXPENSE_AI_ENABLED (default off).

-----------------------------------------------------------------------------
WHY THE FOREIGN KEYS ARE ABSENT

entity_id / user_id / report_id are recorded as plain ids, not constrained.
The table is measurement data about a suggestion, not a record that must stay
referentially consistent with a report — and a FK to `report` would block the
ordinary deletion of a draft the user abandoned. The 90-day purge (§8.5)
removes these rows long before the question matters.

-----------------------------------------------------------------------------
FULLY REVERSIBLE

downgrade() drops the table. Per §11.3 that is rollback level 4 and costs
audit history only: no expense, report, receipt or Xero record depends on a
row here. Levels 1 and 2 (the kill switch and the per-entity flag) are the
rollbacks that should ever actually be used.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "ai1a01_ai_expense_suggestion"
down_revision = "s5a05_drop_legacy_sales"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
TABLE = "ai_expense_suggestion"


def _has_table(bind) -> bool:
    return sa.inspect(bind).has_table(TABLE, schema=SCHEMA)


def upgrade():
    bind = op.get_bind()

    # Idempotent: this revision must not fail on an environment where the
    # table was created by hand.
    if _has_table(bind):
        print(f"{SCHEMA}.{TABLE} already exists — nothing to do.")
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        # Identity
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("report_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Request
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("provider_request_id", sa.String(120), nullable=True),
        # Compliance-relevant (§8.5): evidences where inference ran, per call.
        sa.Column("location", sa.String(60), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("thinking_level", sa.String(16), nullable=True),
        # Usage
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        # Result — post-validation only
        sa.Column("status", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("suggested_fields", sa.Text(), nullable=True),
        sa.Column("confidence_by_field", sa.Text(), nullable=True),
        # Outcome — written on Add (§11.4)
        sa.Column("accepted_fields", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    # Serves both readers: the per-entity accept-rate report (§11.4) and the
    # 90-day purge (§8.5), which sweeps on created_at.
    op.create_index(
        "ix_ai_expense_suggestion_entity_created",
        TABLE,
        ["entity_id", "created_at"],
        unique=False,
        schema=SCHEMA,
    )

    print(f"Created {SCHEMA}.{TABLE} (empty — no backfill, by design).")


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind):
        return

    count = bind.execute(sa.text(f"SELECT count(*) FROM {SCHEMA}.{TABLE}")).scalar()
    if count:
        print(
            f"Dropping {SCHEMA}.{TABLE} discards {count} audit row(s). "
            "This is measurement data only — no expense, report, receipt or "
            "Xero record depends on it."
        )

    op.drop_index(
        "ix_ai_expense_suggestion_entity_created", table_name=TABLE, schema=SCHEMA
    )
    op.drop_table(TABLE, schema=SCHEMA)
