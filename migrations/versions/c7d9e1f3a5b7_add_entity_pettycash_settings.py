"""create entity_pettycash_settings; migrate role tags off entity_account_xero

This migration:
1. Creates pettycashv2.entity_pettycash_settings (one row per entity, one column per role).
2. Backfills it from the semantic role rows currently stored in entity_account_xero
   (types "pettycash", "bank", "cash_sale", "discrepancy", "discrepancy_account",
   "director") and from xero_contact_sync.category rows ("cashsale_contact",
   "director_contact", "discrepancy_contact").
3. Rewrites entity_account_xero.type from those semantic tags to the underlying
   Xero account type pulled from the joined account_info row, so that
   entity_account_xero becomes the petty cash CoA selection list (mirroring how
   entity_bill_account_xero works for the bill side).
4. Nulls out xero_contact_sync.category — those rows are now linked via the new
   table; the contacts themselves stay in xero_contact_sync.

Revision ID: c7d9e1f3a5b7
Revises: 37799fa97f37
Create Date: 2026-05-19 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c7d9e1f3a5b7"
down_revision = "37799fa97f37"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    op.create_table(
        "entity_pettycash_settings",
        sa.Column("entity_id", sa.String(36), primary_key=True),
        sa.Column("pettycash_account_id", sa.String(36), nullable=True),
        sa.Column("bank_account_id", sa.String(36), nullable=True),
        sa.Column("cash_sale_account_id", sa.String(36), nullable=True),
        sa.Column("discrepancy_bank_account_id", sa.String(36), nullable=True),
        sa.Column("discrepancy_account_id", sa.String(36), nullable=True),
        sa.Column("director_account_id", sa.String(36), nullable=True),
        sa.Column("cash_sale_contact_id", sa.String(36), nullable=True),
        sa.Column("director_contact_id", sa.String(36), nullable=True),
        sa.Column("discrepancy_contact_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP,
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP,
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pettycash_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cash_sale_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["discrepancy_bank_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["discrepancy_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["director_account_id"],
            [f"{SCHEMA}.account_info.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cash_sale_contact_id"],
            [f"{SCHEMA}.xero_contact_sync.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["director_contact_id"],
            [f"{SCHEMA}.xero_contact_sync.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["discrepancy_contact_id"],
            [f"{SCHEMA}.xero_contact_sync.id"],
            ondelete="SET NULL",
        ),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.entity_pettycash_settings (
            entity_id,
            pettycash_account_id,
            bank_account_id,
            cash_sale_account_id,
            discrepancy_bank_account_id,
            discrepancy_account_id,
            director_account_id,
            cash_sale_contact_id,
            director_contact_id,
            discrepancy_contact_id
        )
        SELECT
            ai.entity_id,
            MAX(CASE WHEN eax.type = 'pettycash'           THEN eax.account_id END),
            MAX(CASE WHEN eax.type = 'bank'                THEN eax.account_id END),
            MAX(CASE WHEN eax.type = 'cash_sale'           THEN eax.account_id END),
            MAX(CASE WHEN eax.type = 'discrepancy'         THEN eax.account_id END),
            MAX(CASE WHEN eax.type = 'discrepancy_account' THEN eax.account_id END),
            MAX(CASE WHEN eax.type = 'director'            THEN eax.account_id END),
            NULL,
            NULL,
            NULL
        FROM {SCHEMA}.entity_account_xero eax
        JOIN {SCHEMA}.account_info ai ON eax.account_id = ai.id
        WHERE eax.type IN (
            'pettycash', 'bank', 'cash_sale',
            'discrepancy', 'discrepancy_account', 'director'
        )
        GROUP BY ai.entity_id
        ON CONFLICT (entity_id) DO NOTHING
        """
    )

    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET cash_sale_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'cashsale_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET director_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'director_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET discrepancy_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'discrepancy_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
        """
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.entity_pettycash_settings (entity_id)
        SELECT DISTINCT entity_id
        FROM {SCHEMA}.xero_contact_sync
        WHERE category IN ('cashsale_contact', 'director_contact', 'discrepancy_contact')
        ON CONFLICT (entity_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET cash_sale_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'cashsale_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
          AND eps.cash_sale_contact_id IS NULL
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET director_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'director_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
          AND eps.director_contact_id IS NULL
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_pettycash_settings eps
        SET discrepancy_contact_id = sub.id
        FROM (
            SELECT DISTINCT ON (entity_id) id, entity_id
            FROM {SCHEMA}.xero_contact_sync
            WHERE category = 'discrepancy_contact'
            ORDER BY entity_id, id
        ) sub
        WHERE eps.entity_id = sub.entity_id
          AND eps.discrepancy_contact_id IS NULL
        """
    )

    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = ai.type
        FROM {SCHEMA}.account_info ai
        WHERE eax.account_id = ai.id
          AND eax.type IN (
              'pettycash', 'bank', 'cash_sale',
              'discrepancy', 'discrepancy_account', 'director'
          )
          AND ai.type IS NOT NULL
        """
    )

    op.execute(
        f"""
        DELETE FROM {SCHEMA}.entity_account_xero eax
        USING {SCHEMA}.account_info ai
        WHERE eax.account_id = ai.id
          AND ai.type IN (
              'BANK', 'EQUITY', 'OTHERINCOME', 'SALES', 'REVENUE'
          )
        """
    )

    op.execute(
        f"""
        UPDATE {SCHEMA}.xero_contact_sync
        SET category = NULL
        WHERE category IN ('cashsale_contact', 'director_contact', 'discrepancy_contact')
        """
    )


def downgrade():
    op.execute(
        f"""
        UPDATE {SCHEMA}.xero_contact_sync xcs
        SET category = 'cashsale_contact'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE xcs.id = eps.cash_sale_contact_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.xero_contact_sync xcs
        SET category = 'director_contact'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE xcs.id = eps.director_contact_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.xero_contact_sync xcs
        SET category = 'discrepancy_contact'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE xcs.id = eps.discrepancy_contact_id
        """
    )

    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'pettycash'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.pettycash_account_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'bank'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.bank_account_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'cash_sale'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.cash_sale_account_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'discrepancy'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.discrepancy_bank_account_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'discrepancy_account'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.discrepancy_account_id
        """
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.entity_account_xero eax
        SET type = 'director'
        FROM {SCHEMA}.entity_pettycash_settings eps
        WHERE eax.account_id = eps.director_account_id
        """
    )

    op.drop_table("entity_pettycash_settings", schema=SCHEMA)
