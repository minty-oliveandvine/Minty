"""cascade delete for report_v2 and sale_info child tables

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-03-20 10:10:00.000000

"""
from alembic import op

revision = 'a7b8c9d0e1f2'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

FK_CHANGES = [
    # Children of report_v2
    ("report_expense_detail", "report_expense_detail_report_id_fkey", "report_v2", ["report_id"], ["report_id"]),
    ("report_sale_detail", "report_sale_detail_report_id_fkey", "report_v2", ["report_id"], ["report_id"]),
    ("report_cash_detail", "report_cash_detail_report_id_fkey", "report_v2", ["report_id"], ["report_id"]),
    ("report_history_v2", "report_history_v2_report_id_fkey", "report_v2", ["report_id"], ["report_id"]),
    ("xero_report_sync", "xero_report_sync_report_id_fkey", "report_v2", ["report_id"], ["report_id"]),
    ("xero_bank_transfer", "xero_bank_transfer_sync_report_id_fkey", "report_v2", ["sync_report_id"], ["report_id"]),
    # Children of sale_info
    ("report_sale_detail", "report_sale_detail_sale_id_fkey", "sale_info", ["sale_id"], ["sale_id"]),
]


def upgrade():
    for table, fk_name, ref_table, local_cols, remote_cols in FK_CHANGES:
        op.drop_constraint(fk_name, table, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            fk_name, table, ref_table,
            local_cols, remote_cols,
            source_schema=SCHEMA, referent_schema=SCHEMA,
            ondelete="CASCADE",
        )


def downgrade():
    for table, fk_name, ref_table, local_cols, remote_cols in FK_CHANGES:
        op.drop_constraint(fk_name, table, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            fk_name, table, ref_table,
            local_cols, remote_cols,
            source_schema=SCHEMA, referent_schema=SCHEMA,
        )
