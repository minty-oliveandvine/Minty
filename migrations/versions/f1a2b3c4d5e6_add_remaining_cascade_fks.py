"""add remaining on delete cascade FKs

Revision ID: f1a2b3c4d5e6
Revises: e58f26f3bb9d
Create Date: 2026-03-20 10:00:00.000000

"""
from alembic import op

revision = 'f1a2b3c4d5e6'
down_revision = 'e58f26f3bb9d'
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

FK_CHANGES = [
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
