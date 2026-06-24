"""add on delete cascade

Revision ID: e58f26f3bb9d
Revises: 0002_sync_user_columns
Create Date: 2026-03-20 09:24:09.142096

"""
from alembic import op

revision = 'e58f26f3bb9d'
down_revision = '0002_sync_user_columns'
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

FK_CHANGES = [
    ("account_info", "account_info_entity_id_fkey", "entities", ["entity_id"], ["id"]),
    ("entity_account_xero", "entity_account_xero_account_id_fkey", "account_info", ["account_id"], ["id"]),
    ("report_detail", "report_detail_entity_id_fkey", "entities", ["entity_id"], ["id"]),
    ("report_v2", "report_v2_entity_id_fkey", "entities", ["entity_id"], ["id"]),
    ("xero_contact_sync", "xero_contact_sync_entity_id_fkey", "entities", ["entity_id"], ["id"]),
    ("sale_info", "sale_info_entity_id_fkey", "entities", ["entity_id"], ["id"]),
    ("entity_cash_detail_v2", "entity_cash_detail_v2_entity_id_fkey", "entities", ["entity_id"], ["id"]),
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
