"""full schema - consolidated migration matching all current models

Revision ID: 0001_full_schema
Revises:
Create Date: 2026-03-17 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_full_schema"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    # ------------------------------------------------------------------
    # Tables with NO foreign-key dependencies
    # ------------------------------------------------------------------
    op.create_table(
        "currency_info",
        sa.Column("currency_id", sa.String(10), nullable=False),
        sa.Column("currency_name", sa.String(50), nullable=False),
        sa.Column("currency_symbol", sa.String(10), nullable=True),
        sa.Column("iso_code", sa.String(3), nullable=True),
        sa.PrimaryKeyConstraint("currency_id"),
        sa.UniqueConstraint("iso_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("currency_code", sa.String(10), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("minimum_qty", sa.Integer(), nullable=True),
        sa.Column("deposit_frequency", sa.Integer(), nullable=True),
        sa.Column("deposit_day", sa.Integer(), nullable=True),
        sa.Column("contact_option", sa.String(36), nullable=True),
        sa.Column("xero_org_id", sa.String(36), nullable=True),
        sa.Column("xero_short_code", sa.String(50), nullable=True),
        sa.Column("currency_format", sa.String(30), nullable=True),
        sa.Column("timezone", sa.String(30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("last_connected_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("expiry", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "share_link",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("path_segment", sa.String(255), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("transaction_date", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    with op.batch_alter_table("share_link", schema=SCHEMA) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pettycashv2_share_link_path_segment"),
            ["path_segment"],
            unique=True,
        )

    op.create_table(
        "user",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(100), nullable=True),
        sa.Column("password", sa.String(150), nullable=False),
        sa.Column("xero_user_id", sa.UUID(), nullable=True),
        sa.Column("first_name", sa.String(150), nullable=False),
        sa.Column("last_name", sa.String(150), nullable=False),
        sa.Column("user_phone", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("username", sa.String(150), nullable=False),
        sa.Column("xero_entity_id", sa.String(36), nullable=True),
        sa.Column(
            "system_role",
            sa.String(20),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("reset_token", sa.String(100), nullable=True),
        sa.Column("reset_token_expiry", sa.DateTime(), nullable=True),
        sa.Column("xero_token", sa.String(2048), nullable=True),
        sa.Column("access_token", sa.String(2048), nullable=True),
        sa.Column("refresh_token", sa.String(255), nullable=True),
        sa.Column("id_token", sa.String(2048), nullable=True),
        sa.Column("expires_in", sa.Integer(), nullable=True),
        sa.Column("token_created_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("xero_user_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "xero_bank_transaction",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sync_report_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("xero_contact_id", sa.String(36), nullable=False),
        sa.Column("xero_contact_name", sa.String(100), nullable=True),
        sa.Column("unit_amount", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("xero_account_id", sa.String(36), nullable=False),
        sa.Column("xero_account_code", sa.String(10), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("xero_bank_account_id", sa.String(36), nullable=False),
        sa.Column("xero_bank_transaction_id", sa.String(36), nullable=False),
        sa.Column("subtotal", sa.Float(), nullable=True),
        sa.Column("total_tax", sa.Float(), nullable=True),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("status", sa.String(10), nullable=True),
        sa.Column("create_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # Level 1 – depend only on root tables
    # ------------------------------------------------------------------
    op.create_table(
        "account_info",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("xero_account_id", sa.String(36), nullable=True),
        sa.Column("xero_code", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("class_type", sa.String(50), nullable=True),
        sa.Column("bank_account_number", sa.String(50), nullable=True),
        sa.Column("bank_account_type", sa.String(50), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["pettycashv2.entities.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "country_info",
        sa.Column("country_code", sa.String(3), nullable=False),
        sa.Column("country_name_en", sa.String(50), nullable=False),
        sa.Column("country_name_ko", sa.String(50), nullable=True),
        sa.Column("currency_id", sa.String(10), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency_id"], ["pettycashv2.currency_info.currency_id"]
        ),
        sa.PrimaryKeyConstraint("country_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("invited_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["pettycashv2.entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["pettycashv2.user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
        schema=SCHEMA,
    )

    op.create_table(
        "report",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("next_transaction_date", sa.Date(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("opening_balance", sa.Float(), nullable=False),
        sa.Column("cash_addition", sa.Float(), nullable=False),
        sa.Column("adjusted_opening_balance", sa.Float(), nullable=True),
        sa.Column("cash_sales", sa.Float(), nullable=False),
        sa.Column("visa_sales", sa.Float(), nullable=False),
        sa.Column("alipay_sales", sa.Float(), nullable=False),
        sa.Column("wechat_sales", sa.Float(), nullable=False),
        sa.Column("master_sales", sa.Float(), nullable=False),
        sa.Column("unionpay_sales", sa.Float(), nullable=False),
        sa.Column("amex_sales", sa.Float(), nullable=False),
        sa.Column("octopus_sales", sa.Float(), nullable=False),
        sa.Column("deliveroo_sales", sa.Float(), nullable=False),
        sa.Column("foodpanda_sales", sa.Float(), nullable=False),
        sa.Column("keeta_sales", sa.Float(), nullable=False),
        sa.Column("openrice_sales", sa.Float(), nullable=False),
        sa.Column("shop_sales", sa.Float(), nullable=False),
        sa.Column("delivery_sales", sa.Float(), nullable=False),
        sa.Column("total_sales", sa.Float(), nullable=False),
        sa.Column("expenses", sa.Float(), nullable=False),
        sa.Column("bank_deposit", sa.Float(), nullable=False),
        sa.Column("closing_balance", sa.Float(), nullable=False),
        sa.Column("receipt_files", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(150), nullable=True),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("xero_integrated_yes", sa.Boolean(), nullable=True),
        sa.Column("safe_box_balance", sa.Float(), nullable=True),
        sa.Column("discrepancy_amount", sa.Float(), nullable=True),
        sa.Column("discrepancy_reason", sa.String(300), nullable=True),
        sa.Column("discrepancy_type", sa.String(20), nullable=True),
        sa.Column("publishing_status", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["pettycashv2.user.username"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_detail",
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("opening_balance", sa.Float(), nullable=True),
        sa.Column("adjusted_opening_balance", sa.Float(), nullable=True),
        sa.Column("nocashsale_total", sa.Float(), nullable=True),
        sa.Column("cashsale_total", sa.Float(), nullable=True),
        sa.Column("expense_total", sa.Float(), nullable=True),
        sa.Column("discrepancy_amount", sa.Float(), nullable=True),
        sa.Column("discrepancy_description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["pettycashv2.entities.id"]),
        sa.PrimaryKeyConstraint("report_id", "entity_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_draft",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("next_transaction_date", sa.Date(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("opening_balance", sa.Float(), nullable=True),
        sa.Column("cash_addition", sa.Float(), nullable=True),
        sa.Column("adjusted_opening_balance", sa.Float(), nullable=True),
        sa.Column("cash_sales", sa.Float(), nullable=True),
        sa.Column("visa_sales", sa.Float(), nullable=True),
        sa.Column("alipay_sales", sa.Float(), nullable=True),
        sa.Column("wechat_sales", sa.Float(), nullable=True),
        sa.Column("master_sales", sa.Float(), nullable=True),
        sa.Column("unionpay_sales", sa.Float(), nullable=True),
        sa.Column("amex_sales", sa.Float(), nullable=True),
        sa.Column("octopus_sales", sa.Float(), nullable=True),
        sa.Column("deliveroo_sales", sa.Float(), nullable=True),
        sa.Column("foodpanda_sales", sa.Float(), nullable=True),
        sa.Column("keeta_sales", sa.Float(), nullable=True),
        sa.Column("openrice_sales", sa.Float(), nullable=True),
        sa.Column("shop_sales", sa.Float(), nullable=True),
        sa.Column("delivery_sales", sa.Float(), nullable=True),
        sa.Column("total_sales", sa.Float(), nullable=True),
        sa.Column("expenses", sa.Float(), nullable=True),
        sa.Column("bank_deposit", sa.Float(), nullable=True),
        sa.Column("closing_balance", sa.Float(), nullable=True),
        sa.Column("receipt_files", sa.Text(), nullable=True),
        sa.Column("current_section", sa.String(20), nullable=True),
        sa.Column("completed_sections", sa.JSON(), nullable=True),
        sa.Column("uploaded_by", sa.String(150), nullable=True),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("withdrawal_type", sa.String(20), nullable=True),
        sa.Column("withdrawal_bank_account", sa.String(36), nullable=True),
        sa.Column("xero_integrated_yes", sa.Boolean(), nullable=True),
        sa.Column("safe_box_balance", sa.Float(), nullable=True),
        sa.Column("discrepancy_amount", sa.Float(), nullable=True),
        sa.Column("discrepancy_reason", sa.String(300), nullable=True),
        sa.Column("discrepancy_type", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["pettycashv2.user.username"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_v2",
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("starting_balance", sa.Float(), nullable=True),
        sa.Column("add_cash_amount", sa.Float(), nullable=True),
        sa.Column("cash_from_type", sa.String(10), nullable=True),
        sa.Column("add_cash_bank_account_id", sa.String(36), nullable=True),
        sa.Column("opening_balance", sa.Float(), nullable=True),
        sa.Column("adjusted_opening_balance", sa.Float(), nullable=True),
        sa.Column("xero_organiztion_id", sa.String(36), nullable=True),
        sa.Column("cashsale_total", sa.Float(), nullable=True),
        sa.Column("nocashsale_total", sa.Float(), nullable=True),
        sa.Column("cash_deposit", sa.Float(), nullable=True),
        sa.Column("expense_total", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["pettycashv2.entities.id"]),
        sa.PrimaryKeyConstraint("report_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), nullable=True),
        sa.Column("permission_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["pettycashv2.permissions.id"]
        ),
        sa.ForeignKeyConstraint(["role_id"], ["pettycashv2.roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "sale_info",
        sa.Column("sale_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("sale_name", sa.String(80), nullable=True),
        sa.Column("value_name", sa.String(80), nullable=True),
        sa.Column("create_date", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["pettycashv2.entities.id"]),
        sa.PrimaryKeyConstraint("sale_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "user_entity",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "create_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column(
            "joined_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["pettycashv2.entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["pettycashv2.user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "entity_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "xero_contact_sync",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("xero_contact_id", sa.String(36), nullable=False),
        sa.Column("xero_org_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["pettycashv2.entities.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # Level 2 – depend on level-1 tables
    # ------------------------------------------------------------------
    op.create_table(
        "cash_info",
        sa.Column("cash_id", sa.Integer(), nullable=False),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("type", sa.String(10), nullable=True),
        sa.Column("cash_value", sa.Float(), nullable=True),
        sa.Column("cash_name", sa.String(10), nullable=True),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["country_code"], ["pettycashv2.country_info.country_code"]
        ),
        sa.PrimaryKeyConstraint("cash_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "entity_account_xero",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("xero_org_id", sa.String(36), nullable=True),
        sa.Column("xero_account_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["pettycashv2.account_info.id"]
        ),
        sa.PrimaryKeyConstraint("id", "account_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_cashcount_draft",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("thousand_note", sa.Integer(), nullable=True),
        sa.Column("fivehundred_note", sa.Integer(), nullable=True),
        sa.Column("onehundred_note", sa.Integer(), nullable=True),
        sa.Column("fifty_note", sa.Integer(), nullable=True),
        sa.Column("twenty_note", sa.Integer(), nullable=True),
        sa.Column("ten_note", sa.Integer(), nullable=True),
        sa.Column("five_coin", sa.Integer(), nullable=True),
        sa.Column("two_coin", sa.Integer(), nullable=True),
        sa.Column("one_coin", sa.Integer(), nullable=True),
        sa.Column("safe_box_balance", sa.Float(), nullable=True),
        sa.Column("discrepancy_amount", sa.Float(), nullable=True),
        sa.Column("discrepancy_reason", sa.String(300), nullable=True),
        sa.Column("discrepancy_type", sa.String(20), nullable=True),
        sa.Column("actual_cash_total", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["pettycashv2.report_draft.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_expense_detail",
        sa.Column("expense_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("info_filepath", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("create_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.PrimaryKeyConstraint("expense_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("field_changed", sa.String(255), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["pettycashv2.report.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["pettycashv2.user.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    with op.batch_alter_table("report_history", schema=SCHEMA) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pettycashv2_report_history_company"),
            ["company"],
            unique=False,
        )

    op.create_table(
        "report_history_draft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_draft_id", sa.String(36), nullable=False),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("field_changed", sa.String(255), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["pettycashv2.report_draft.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["pettycashv2.user.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    with op.batch_alter_table(
        "report_history_draft", schema=SCHEMA
    ) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pettycashv2_report_history_draft_company"),
            ["company"],
            unique=False,
        )

    op.create_table(
        "report_history_v2",
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("history_id", sa.String(36), nullable=False),
        sa.Column("emp_id", sa.String(36), nullable=True),
        sa.Column("create_date", sa.DateTime(), nullable=True),
        sa.Column("opening_balance", sa.Float(), nullable=True),
        sa.Column("adjusted_opening_balance", sa.Float(), nullable=True),
        sa.Column("sale_amount", sa.Float(), nullable=True),
        sa.Column("expense_amount", sa.Float(), nullable=True),
        sa.Column("withdraw_amount", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("xero_organiztion_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.PrimaryKeyConstraint("report_id", "history_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_sale_detail",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sale_id", sa.String(36), nullable=True),
        sa.Column("report_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("create_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"], ["pettycashv2.sale_info.sale_id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "shop_expense",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("item", sa.String(150), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("remarks", sa.String(300), nullable=True),
        sa.Column("files", sa.Text(), nullable=True),
        sa.Column("s3_key", sa.String(255), nullable=True),
        sa.Column("contact_id", sa.String(36), nullable=True),
        sa.Column("contact_name", sa.String(150), nullable=True),
        sa.Column("account_id", sa.String(36), nullable=True),
        sa.Column("account_code", sa.String(20), nullable=True),
        sa.Column("item_code", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "shop_expense_draft",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_draft_id", sa.String(36), nullable=False),
        sa.Column("item", sa.String(150), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("remarks", sa.String(300), nullable=True),
        sa.Column("files", sa.Text(), nullable=True),
        sa.Column("s3_key", sa.String(255), nullable=True),
        sa.Column("contact_id", sa.String(36), nullable=True),
        sa.Column("contact_name", sa.String(150), nullable=True),
        sa.Column("account_id", sa.String(36), nullable=True),
        sa.Column("account_code", sa.String(20), nullable=True),
        sa.Column("item_code", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_draft_id"], ["pettycashv2.report_draft.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "xero_bank_transfer",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sync_report_id", sa.String(36), nullable=False),
        sa.Column("from_bank_account_id", sa.String(36), nullable=False),
        sa.Column("to_bank_account_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("transfer_date", sa.DateTime(), nullable=False),
        sa.Column("xero_bank_transfer_id", sa.String(36), nullable=False),
        sa.Column("from_bank_transaction_id", sa.String(36), nullable=False),
        sa.Column("to_bank_transaction_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(10), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sync_report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.PrimaryKeyConstraint("id", "sync_report_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "xero_report_sync",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("sync_statuc", sa.String(20), nullable=True),
        sa.Column("reported_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("xero_reponse_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.PrimaryKeyConstraint("id", "report_id"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # Level 3 – depend on level-2 tables
    # ------------------------------------------------------------------
    op.create_table(
        "entity_cash_detail_v2",
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("cash_id", sa.Integer(), nullable=False),
        sa.Column("cash_type", sa.String(30), nullable=True),
        sa.Column("cash_instock", sa.Float(), nullable=True),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cash_id"], ["pettycashv2.cash_info.cash_id"]
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["pettycashv2.entities.id"]
        ),
        sa.PrimaryKeyConstraint("entity_id", "cash_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "report_cash_detail",
        sa.Column("cash_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("create_at", sa.DateTime(), nullable=True),
        sa.Column("count", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cash_id"], ["pettycashv2.cash_info.cash_id"]
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["pettycashv2.report_v2.report_id"]
        ),
        sa.PrimaryKeyConstraint("cash_id"),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("report_cash_detail", schema=SCHEMA)
    op.drop_table("entity_cash_detail_v2", schema=SCHEMA)
    op.drop_table("xero_report_sync", schema=SCHEMA)
    op.drop_table("xero_bank_transfer", schema=SCHEMA)
    op.drop_table("shop_expense_draft", schema=SCHEMA)
    op.drop_table("shop_expense", schema=SCHEMA)
    op.drop_table("report_sale_detail", schema=SCHEMA)
    op.drop_table("report_history_v2", schema=SCHEMA)
    with op.batch_alter_table("report_history_draft", schema=SCHEMA) as b:
        b.drop_index(b.f("ix_pettycashv2_report_history_draft_company"))
    op.drop_table("report_history_draft", schema=SCHEMA)
    with op.batch_alter_table("report_history", schema=SCHEMA) as b:
        b.drop_index(b.f("ix_pettycashv2_report_history_company"))
    op.drop_table("report_history", schema=SCHEMA)
    op.drop_table("report_expense_detail", schema=SCHEMA)
    op.drop_table("report_cashcount_draft", schema=SCHEMA)
    op.drop_table("entity_account_xero", schema=SCHEMA)
    op.drop_table("cash_info", schema=SCHEMA)
    op.drop_table("xero_contact_sync", schema=SCHEMA)
    op.drop_table("user_entity", schema=SCHEMA)
    op.drop_table("sale_info", schema=SCHEMA)
    op.drop_table("role_permissions", schema=SCHEMA)
    op.drop_table("report_v2", schema=SCHEMA)
    op.drop_table("report_draft", schema=SCHEMA)
    op.drop_table("report_detail", schema=SCHEMA)
    op.drop_table("report", schema=SCHEMA)
    op.drop_table("invitations", schema=SCHEMA)
    op.drop_table("country_info", schema=SCHEMA)
    op.drop_table("account_info", schema=SCHEMA)
    op.drop_table("xero_bank_transaction", schema=SCHEMA)
    op.drop_table("user", schema=SCHEMA)
    with op.batch_alter_table("share_link", schema=SCHEMA) as b:
        b.drop_index(b.f("ix_pettycashv2_share_link_path_segment"))
    op.drop_table("share_link", schema=SCHEMA)
    op.drop_table("sessions", schema=SCHEMA)
    op.drop_table("roles", schema=SCHEMA)
    op.drop_table("permissions", schema=SCHEMA)
    op.drop_table("entities", schema=SCHEMA)
    op.drop_table("currency_info", schema=SCHEMA)
