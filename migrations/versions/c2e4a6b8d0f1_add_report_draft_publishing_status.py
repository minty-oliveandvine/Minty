"""Add publishing_status to report_draft

Reverting a submitted report to draft deletes its Report row, which is where
publishing_status lived. That column is the only signal that the report was
already pushed to Xero, and re-publishing without it silently creates duplicate
transactions. Carry the value onto the draft so it survives the revert and can
be restored onto the Report when the draft is submitted again.

Nullable with no default: a draft that was never published stays NULL.

Revision ID: c2e4a6b8d0f1
Revises: b1d3f5a7c9e2
Create Date: 2026-07-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c2e4a6b8d0f1"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "report_draft",
        sa.Column("publishing_status", sa.String(length=20), nullable=True),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_column("report_draft", "publishing_status", schema=SCHEMA)
