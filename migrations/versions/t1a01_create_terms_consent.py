"""TERMS 1 — create terms_consent, the record of who agreed to which Terms

Revision ID: t1a01_terms_consent
Revises: b8f3a2c1d4e5
Create Date: 2026-08-06

=============================================================================
WHAT THIS IS

One new table. Nothing else is touched — no column added to an existing table,
no constraint changed, no data moved, no row rewritten.

    pettycashv2.terms_consent

It holds one row per (person, version of the Terms). Rows are only ever
inserted; the application never updates or deletes them. That is what makes the
table evidence rather than state.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

This is purely additive, which means the deploy order that governs the report
consolidation does NOT apply here:

  * Old code ignores a table it has never heard of. Running this migration
    ahead of the application code is harmless.
  * Nothing reads the table until the Phase 3 accept screen and the Phase 4
    gate ship. Until then it simply sits empty.
  * CREATE TABLE takes no lock on anything that already exists, so there is no
    blocking of live traffic and no rewrite of a large table.

So: schema first, code after — the ordinary direction for an addition.

-----------------------------------------------------------------------------
NO BACKFILL, DELIBERATELY

This migration inserts no rows, and no later one should either.

Existing users have not agreed to anything. Inventing a consent record for them
would defeat the entire purpose of the table — a fabricated record is worse than
an absent one, because it looks genuine. They are asked on their next login, by
the Phase 4 gate.

-----------------------------------------------------------------------------
WHY document_hash IS NOT NULL

Recording "they accepted beta-1" proves someone clicked a button with a label
on it. It does not prove what the document said. The column stores the SHA-256
of the exact wording shown (see legal/registry.py), so the click and the text
are pinned to each other and neither side can rewrite what was agreed.

A row without it would be unverifiable, so the column cannot be null.

-----------------------------------------------------------------------------
WHY THE UNIQUE INDEX

`(user_id, terms_version)` is unique so a double-click, two open tabs, or a
retried request produce ONE row, not several. The service layer treats the
resulting constraint violation as success. Without the index the evidence trail
would accumulate duplicates that look like repeated agreements.

-----------------------------------------------------------------------------
FULLY REVERSIBLE

downgrade() drops the table. Note what that means: it destroys the consent
records themselves. It is safe today, while the table is empty, and it is NOT
safe once real agreements have been recorded — take a backup first at that
point. There is no way to reconstruct a consent record after the fact, which is
precisely why they are worth keeping.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "t1a01_terms_consent"
down_revision = "b8f3a2c1d4e5"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
TABLE = "terms_consent"


def _has_table(bind) -> bool:
    return sa.inspect(bind).has_table(TABLE, schema=SCHEMA)


def upgrade():
    bind = op.get_bind()

    # Idempotent. The .sql twin can be run by hand on an environment that
    # alembic does not stamp, and this revision must not then fail on it.
    if _has_table(bind):
        print(f"{SCHEMA}.{TABLE} already exists — nothing to do.")
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.user.id"],
            name="fk_terms_consent_user",
            # Section 13 of the Terms allows permanent deletion of a user.
            # Consent records about a deleted person are data we would have no
            # reason to hold, so they go with them.
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "terms_version", name="uq_terms_consent_user_version"
        ),
        schema=SCHEMA,
    )

    # Supports the gate's per-request lookup and the admin history view. The
    # unique constraint above already covers (user_id, terms_version), but a
    # plain user_id index serves "everything this person agreed to" without
    # naming a version.
    op.create_index(
        "ix_terms_consent_user", TABLE, ["user_id"], unique=False, schema=SCHEMA
    )

    print(f"Created {SCHEMA}.{TABLE} (empty — no backfill, by design).")


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind):
        return

    # Loud, because by the time anyone runs this in anger the table may hold
    # records that cannot be reconstructed.
    count = bind.execute(
        sa.text(f"SELECT count(*) FROM {SCHEMA}.{TABLE}")
    ).scalar()
    if count:
        print(
            f"WARNING: dropping {SCHEMA}.{TABLE} DESTROYS {count} consent "
            "record(s). They cannot be recreated. Restore from backup if this "
            "was not intended."
        )

    op.drop_index("ix_terms_consent_user", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
