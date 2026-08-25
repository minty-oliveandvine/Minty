"""Drop the four abandoned consent tables.

WHAT THESE WERE
---------------
An earlier, more elaborate consent design that was built and then dropped:

    2026-06-24  42f73fab  added blueprints/consent/ (models, services) and
                          migration 093b4bd031f1, which created these four
                          tables: terms_version, terms_user_principal,
                          consent_record, consent_event.
    2026-07-08  4baa65ef  deleted the whole blueprints/consent/ module AND
                          migration 093b4bd031f1 — but never dropped the
                          tables, so they were left stranded in the database
                          with nothing in the repo that creates or reads them.

The Terms of Use feature that actually shipped took a different, simpler
approach: ONE table, ``pettycashv2.terms_consent`` (see t1a01_terms_consent).
That one is live and must not be touched.

WHY BOTHER
----------
They are empty, so this reclaims nothing. It removes ambiguity: someone looking
for "the terms table" currently finds five candidates and has to work out which
is real. Four of them are archaeology.

VERIFIED BEFORE WRITING THIS
----------------------------
    * 0 rows in all four
    * 0 foreign keys pointing at them from outside the set (the only FKs are
      between the four themselves)
    * 0 views depending on them
    * 0 references anywhere in the codebase
    * ``093b4bd031f1`` is NOT present in alembic_version, so there is no stale
      revision to reconcile

NOT TO BE CONFUSED WITH
-----------------------
``pettycashv2.entity_billing_consent`` — 19 rows, live, and nothing to do with
the Terms. It records that a company agreed to be CHARGED, and belongs to
blueprints/subscription. Do not sweep it up with these.

REVERSIBLE
----------
``downgrade`` recreates all four exactly as 093b4bd031f1 defined them,
recovered from git history. It restores the structure, not data — there was
never any data.

Revision ID: k1a01_drop_consent
Revises: x1a01_transfer_schema
Create Date: 2026-08-25

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1a01_drop_consent"
down_revision = "x1a01_transfer_schema"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Child first: consent_event -> consent_record -> {terms_user_principal,
# terms_version}. Dropping a parent first would fail on the foreign keys, and
# using CASCADE to get around that would silently take anything else attached.
_DROP_ORDER = (
    "consent_event",
    "consent_record",
    "terms_user_principal",
    "terms_version",
)


def upgrade():
    bind = op.get_bind()

    # Refuse to drop anything holding rows. They were empty when this was
    # written and nothing writes to them, but a migration that destroys data
    # because an assumption went stale is exactly the migration nobody
    # forgives. Cheap to check, and it turns a silent loss into a loud stop.
    for table in _DROP_ORDER:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": SCHEMA, "t": table},
        ).scalar()
        if not exists:
            continue
        count = bind.execute(
            sa.text(f'SELECT count(*) FROM {SCHEMA}."{table}"')  # noqa: S608
        ).scalar()
        if count:
            raise RuntimeError(
                f"{SCHEMA}.{table} holds {count} row(s). These tables were "
                "abandoned and expected to be empty — something has started "
                "using them. Investigate before dropping."
            )

    for table in _DROP_ORDER:
        op.execute(f'DROP TABLE IF EXISTS {SCHEMA}."{table}"')


def downgrade():
    """Recreate the four tables exactly as 093b4bd031f1 defined them.

    Parents first, mirroring the original migration's order.
    """
    op.create_table(
        "terms_version",
        sa.Column("terms_ver_id", sa.String(length=36), nullable=False),
        sa.Column("doc_url", sa.Text(), nullable=False),
        sa.Column("ver_label", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column(
            "published_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("terms_ver_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "terms_user_principal",
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("account_ref", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_ref"], [f"{SCHEMA}.user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("principal_id"),
        sa.UniqueConstraint("account_ref"),
        schema=SCHEMA,
    )
    op.create_table(
        "consent_record",
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("terms_ver_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("captured_ip", postgresql.INET(), nullable=False),
        sa.Column("captured_ua", sa.Text(), nullable=False),
        sa.Column("capture_method", sa.Text(), nullable=False),
        sa.Column("record_hash", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            [f"{SCHEMA}.terms_user_principal.principal_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["terms_ver_id"],
            [f"{SCHEMA}.terms_version.terms_ver_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("record_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_pettycashv2_consent_record_principal_id",
        "consent_record",
        ["principal_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_pettycashv2_consent_record_terms_ver_id",
        "consent_record",
        ["terms_ver_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_table(
        "consent_event",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("event_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("event_state", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["record_id"], [f"{SCHEMA}.consent_record.record_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("event_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_pettycashv2_consent_event_record_id",
        "consent_event",
        ["record_id"],
        unique=False,
        schema=SCHEMA,
    )
