"""Step 3: link report_sale_detail directly to the sales_method catalog.

Adds ``report_sale_detail.sales_method_id`` and backfills it through
sale_info (report_sale_detail.sale_id → sale_info.sale_id → sales_method_id).

Why denormalize the method onto the detail row rather than always joining via
sale_info:

  1. Historical accuracy. ending.py:524 and :976 deliberately use
     ``outerjoin(SaleInfo)`` "to include deleted/disabled sale types" — a
     submitted report must still show amounts for methods the entity has since
     removed. When the sale_info row is gone the outer join yields NULL and the
     amount survives with no way to tell what it was for. Storing the catalog
     id on the detail row makes every report self-describing, permanently.

  2. Duplicate sale_info rows exist (payment_methods.py:38-50 dedupes with
     max(sale_id)). Aggregating through them is fragile; aggregating by
     sales_method_id is not.

NOT added: report_draft_id. It looked necessary until the id lifecycle was
traced — ending.py:445 creates the revert draft with ``id=full_report.id``, so
a report and its draft share one id and one set of detail rows. Adding a second
FK would make two rows carry the same amount with no way to tell which is
authoritative, and would double every sum in
calculate_sales_from_report_sale_detail.

Known gap (NOT fixed here — it is a behaviour change, so it belongs in Step 4):
report/routes/create.py:148 mints a FRESH uuid for Report at first submit while
the draft keeps its own, so a first-time submitted report's detail rows stay
keyed to the draft id. Aligning that (Report(id=draft.id)) makes the id stable
across the whole lifecycle.

Revision ID: s3a03_rsd_method_fk
Revises: s2a02_sale_info_fk
Create Date: 2026-07-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "s3a03_rsd_method_fk"
down_revision = "s2a02_sale_info_fk"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.add_column(
        "report_sale_detail",
        sa.Column("sales_method_id", sa.String(36), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_report_sale_detail_sales_method",
        "report_sale_detail",
        "sales_method",
        ["sales_method_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        # RESTRICT so a catalog row can never be deleted while historical
        # reports still reference it — that would re-open the exact
        # "amount with no method" hole this column exists to close.
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_report_sale_detail_sales_method_id",
        "report_sale_detail",
        ["sales_method_id"],
        schema=SCHEMA,
    )

    # Backfill through the link established in Step 2. Rows whose sale_info
    # row has already been hard-deleted stay NULL — there is nothing left to
    # resolve them from, and that pre-existing data loss is exactly what this
    # column prevents going forward.
    op.get_bind().execute(
        text(
            f"""
            UPDATE {SCHEMA}.report_sale_detail rsd
            SET sales_method_id = si.sales_method_id
            FROM {SCHEMA}.sale_info si
            WHERE si.sale_id = rsd.sale_id
              AND si.sales_method_id IS NOT NULL
              AND rsd.sales_method_id IS NULL
            """
        )
    )


def downgrade():
    op.drop_index(
        "ix_report_sale_detail_sales_method_id",
        "report_sale_detail",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_report_sale_detail_sales_method",
        "report_sale_detail",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("report_sale_detail", "sales_method_id", schema=SCHEMA)
