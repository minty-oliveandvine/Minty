"""A TRIAL HAS NO SUBSCRIBER

Revision ID: x2a01_ems_payer_nullable
Revises: x1a01_invoice_line_span
Create Date: 2026-10-08

=============================================================================
WHAT THIS IS

One constraint dropped: ``entity_module_subscription.payer_user_id`` becomes
NULLABLE. Nothing else moves - not the column's type, not ``fk_ems_user``, not
``idx_ems_payer``, not ``uq_ems_entity_code``.

Item 2.50 of ``docs/schema/01_schema_rebased.sql`` declares it NULL, so a FRESH
build already has it. This revision is the belt to that file's braces: it
exists for the databases that are already up.

-----------------------------------------------------------------------------
WHY

The column is the SUBSCRIBER - who pays for the company. It was established by
whoever started the first trial (``checkout.start_module_trial`` passed the
acting user straight into ``store.upsert_module_row``), and that is wrong twice
over. Starting a free trial costs nothing and commits nobody, yet it made one
admin financially responsible for the company, and it locked every OTHER admin
out of the subscription for good: ``store.may_manage_subscription`` admits only
the payer once a payer exists.

So a trial now starts with none, and NULL is what "none" looks like. The
subscriber is established by exactly one act - putting the company on a billing
account and confirming billing - in the onboarding wizard
(``/api/onboarding/billing/authorize``) or in the app (Activate Subscription,
``checkout.activate_entity_billing``). That act stamps the payer onto every one
of the entity's module rows in one UPDATE, with the emptiness in the WHERE, so
two admins activating at the same moment cannot open two billing
relationships.

Until then: ``payer_for_entity`` answers None, any admin holding
``Permission.MODULE_MANAGE`` may act, and the trial EXPIRES at term end instead
of converting, because there is no card and nobody has agreed to be charged.

-----------------------------------------------------------------------------
NO BACKFILL, AND NOTHING CHANGES FOR WHAT IS ALREADY THERE

Every stored row has a non-NULL payer by definition of the constraint it has
been living under, and dropping NOT NULL cannot change a single stored value.
Existing entities keep their subscriber, keep appearing in that subscriber's
Manage Subscriptions list, keep converting at trial end, and keep refusing a
co-admin's action. Only trials started AFTER this ships are subscriber-less.

-----------------------------------------------------------------------------
WHAT STAYS, AND WHY EACH IS SAFE WITH NULLS

``fk_ems_user … ON DELETE CASCADE``  a NULL row is matched by no cascade.
``idx_ems_payer``                    a btree indexes NULLs, and every reader
                                     filters by equality, which NULL never
                                     matches (``module_rows_for_payer``).
``uq_ems_entity_code``               is (entity_id, function_code). The payer
                                     is not in it, so a NULL payer can neither
                                     create nor destroy a conflict.

``entity_billing_group.payer_user_id`` is deliberately LEFT NOT NULL. Its
``UNIQUE (entity_id, payer_user_id)`` is the one-payer-per-entity guard (see
the note at item 2.46 of the schema file), and NULLs are distinct in a Postgres
unique index - a nullable column there would let unlimited rows share one
entity and silently void the rule.

Noticed in passing, NOT touched here: the Flask model names this table's unique
key ``uq_ems_entity_function`` while the SQL calls it ``uq_ems_entity_code``.
Pre-existing drift. Do not "fix" it blind.

-----------------------------------------------------------------------------
IT TOUCHES pettycashv3 AND NOTHING ELSE

As ``x1a01`` and ``w1a01``: pettycashv2 is being retired, so nothing new is
built on it, and ``pettycashv3`` carries no ``alembic_version`` of its own -
the chain's bookmark stays in pettycashv2's, and the DDL below goes nowhere
near that schema.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE

Dropping NOT NULL is a catalogue-only change in Postgres: no table rewrite, no
default to fill, no index touched, and the ACCESS EXCLUSIVE lock is held for
the length of a catalogue update. Old code never writes NULL, so it behaves
exactly as it does today. Guarded and idempotent - a database that is already
nullable is a no-op.

The downgrade REFUSES while any row is NULL, loudly and with the count. There
is no honest way to invent a subscriber for a company that has none; giving one
the admin who happened to start the trial is precisely the behaviour this
revision exists to remove. Activate those companies, or delete their rows, then
reverse.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "x2a01_ems_payer_nullable"
down_revision = "x1a01_invoice_line_span"
branch_labels = None
depends_on = None

# PETTYCASHV3 ONLY, as x1a01 - see the header.
SCHEMA = "pettycashv3"

TABLE = "entity_module_subscription"
COLUMN = "payer_user_id"


def _column(bind) -> dict | None:
    """The column's reflected definition, or None when the table has no such column."""
    for col in sa.inspect(bind).get_columns(TABLE, schema=SCHEMA):
        if col["name"] == COLUMN:
            return col
    return None


def upgrade():
    bind = op.get_bind()

    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        print(f"{SCHEMA}.{TABLE} does not exist - nothing to do.")
        return

    col = _column(bind)
    if col is None:
        print(f"{SCHEMA}.{TABLE}.{COLUMN} does not exist - nothing to do.")
        return
    if col["nullable"]:
        print(f"{SCHEMA}.{TABLE}.{COLUMN} is already nullable - skipping.")
        return

    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=postgresql.UUID(),
        nullable=True,
        schema=SCHEMA,
    )
    print(
        f"{SCHEMA}.{TABLE}.{COLUMN} is now nullable - a trial has no subscriber "
        "until billing is confirmed (see the header). No row changed."
    )


def downgrade():
    bind = op.get_bind()

    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        return

    col = _column(bind)
    if col is None or not col["nullable"]:
        print(f"{SCHEMA}.{TABLE}.{COLUMN} is already NOT NULL - nothing to do.")
        return

    orphans = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE {COLUMN} IS NULL"  # noqa: S608
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} module row(s) in {SCHEMA}.{TABLE} have no subscriber. "
            "They must be given one - by activating those companies' subscriptions - "
            "or deleted, before this revision can be reversed. This migration will "
            "not invent a payer for a company that has none."
        )

    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=postgresql.UUID(),
        nullable=False,
        schema=SCHEMA,
    )
    print(f"{SCHEMA}.{TABLE}.{COLUMN} is NOT NULL again.")
