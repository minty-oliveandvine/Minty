"""AI STAGE 1 — record thinking tokens on the extraction audit row

Revision ID: ai1a02_thought_tokens
Revises: ai1a01_ai_expense_suggestion
Create Date: 2026-09-03

=============================================================================
WHAT THIS IS

One nullable integer column on a table this feature owns:

    pettycashv2.ai_expense_suggestion.thought_tokens

-----------------------------------------------------------------------------
WHY IT IS NOT ENOUGH TO FOLD THESE INTO output_tokens

Gemini 3.x reports thinking tokens separately from output tokens, and they
behave differently from both of the other counts:

  * They are INVISIBLE in the reply. A measured call returned 207 tokens of
    JSON alongside 322 thought tokens.
  * They are BILLED at the output rate. Leaving them out of estimated_cost
    understated that call by roughly 60 %, which is exactly the direction a
    cost model must not be wrong in.
  * They are drawn from the SAME max_output_tokens allowance as the reply.

That last one is why the column earns its place rather than being a nicety.
A long think exhausts the budget and truncates the JSON mid-object, and the
audit row then reads `status=incomplete, output_tokens=31` — which looks like
a model that barely answered, not a model that thought too long. Without the
thought count beside it the two are indistinguishable, and the fix (raise
max_output_tokens) is invisible.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

An ADD COLUMN of a nullable integer with no default: no table rewrite, no
backfill, no lock worth naming. Rows written before this revision keep a NULL,
which is honest — we did not record the number, and inventing one would make
the cost history look measured when it was not.

Old code ignores a column it does not select.

-----------------------------------------------------------------------------
FULLY REVERSIBLE

downgrade() drops the column and loses only the thinking counts recorded
since it ran.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "ai1a02_thought_tokens"
down_revision = "ai1a01_ai_expense_suggestion"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
TABLE = "ai_expense_suggestion"
COLUMN = "thought_tokens"


def _has_column(bind) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE, schema=SCHEMA):
        return False
    return COLUMN in {c["name"] for c in inspector.get_columns(TABLE, schema=SCHEMA)}


def upgrade():
    bind = op.get_bind()
    if _has_column(bind):
        print(f"{SCHEMA}.{TABLE}.{COLUMN} already exists — nothing to do.")
        return

    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    print(f"Added {SCHEMA}.{TABLE}.{COLUMN} (NULL on existing rows, by design).")


def downgrade():
    bind = op.get_bind()
    if not _has_column(bind):
        return
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
