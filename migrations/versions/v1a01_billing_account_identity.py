"""BILLING ACCOUNTS - the payer's account gets an identity, and holds its cards

Revision ID: v1a01_billing_account
Revises: u1a01_subscription_types
Create Date: 2026-09-10

=============================================================================
WHAT THIS IS

Onboarding's card dialog asks for an EMAIL and a BILLING COMPANY before it asks
for a card, and nothing in this application stored either one.

The Stripe customer does carry an email, but ``checkout._payer_identity`` rewrites
it from the ``user`` row on every write - "our record is the source of truth for
who they are" - and the customer's NAME is deliberately the payer's human name,
because an entity name there "would be wrong the moment a second entity is
added". Neither field was a place a payer could put what their invoices should
say.

So the identity goes where the money already is. ``payer_billing_group`` is
already "one payment method, plus everything it pays for": entities point at it,
the cycle lives on it, and one invoice is raised per group. Naming it - giving it
an email and a company - turns it into the BILLING ACCOUNT the payer creates and
recognises, with no new join on any billing query.

Three changes, in one revision because there is no state in which part of it is
useful:

  1. payer_billing_group.billing_email / .billing_company   (new columns)
  2. billing_account_payment_method                          (new table)
  3. uq_payer_billing_group_payer_card                       (dropped)

-----------------------------------------------------------------------------
1. THE IDENTITY COLUMNS ARE NULLABLE, AND STAY THAT WAY

Every group that exists today was created by the backfill or by a card capture
that never asked. NOT NULL would need a value invented for each of them, and an
invented billing company is worse than an absent one: it would print on an
invoice as though the payer had chosen it.

Absent means "this account has not been named", which the application renders as
the payer's own details. That is the same fallback as before this revision, so
nothing changes for an account nobody names.

-----------------------------------------------------------------------------
2. billing_account_payment_method - THE SHELF BEHIND THE DEFAULT

An account may now hold SEVERAL cards. The account still CHARGES exactly one, and
that one is still ``payer_billing_group.stripe_payment_method_id``.

WHY THE DEFAULT IS IN TWO PLACES. It is duplicated on purpose - here as
``is_default``, there as the id itself - because ``renewals`` and ``dunning`` read
the account row and must not join to discover which card to charge. The cost of
that is a pair that can disagree, so ``store.set_group_default_card`` writes both
or neither, and ``uq_billing_account_payment_method_default`` makes a second
default impossible on the database side. A divergence between the two means the
account charges a card the payer is not being shown, which is the one failure in
this area that reaches real money without raising anything.

ON DELETE CASCADE, unlike every other foreign key in this set. A row here is not a
fact about a payment in its own right - it is the account's list. Deleting the
account and keeping the list would leave rows nothing can reach. (Invoices, which
ARE facts in their own right, live on a different table and carry no FK.)

Only ids are held. The number is typed into Stripe Elements and confirmed against
a SetupIntent; no PAN reaches this process, this table or these logs.

-----------------------------------------------------------------------------
3. uq_payer_billing_group_payer_card HAS TO GO

It read ``(payer_user_id, stripe_payment_method_id)`` and said a payer could not
hold two groups on one card. That was right when a group WAS a card. It is wrong
now for two reasons: a payer may legitimately put the same card on two accounts
(one company each, separate invoices), and the constraint says nothing at all
about the cards on the new shelf.

What it was actually protecting - two groups both claiming one entity's renewal -
is held by ``uq_entity_billing_group_entity_payer`` instead, which is where the
claim is recorded. That constraint is untouched.

-----------------------------------------------------------------------------
WHAT THIS CHANGES BENEATH, AND WHAT IT DOES NOT

``paid_through``, ``dunning_started_at`` and ``dunning_attempts`` were per CARD
when a group was a card. They are now per ACCOUNT. In practice the grain has not
moved - one invoice is still raised per group - but the REASON has, and the model
docstring said the old one. It is updated with this revision.

No service behaviour changes here. The backfill gives every existing group a shelf
holding exactly the card it already charges, so an account with one card behaves
identically to before. Nothing reads the new table until the services that use it
ship alongside.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE

Two nullable ADD COLUMNs, one CREATE TABLE, one DROP CONSTRAINT. No rewrite and
no lock on existing traffic. Old code cannot see any of it; new code falls back to
the account row exactly as old code does when the shelf is empty.

THE DOWNGRADE CAN REFUSE. Re-adding the unique constraint fails outright if a
payer has since put one card on two accounts, and dropping the table discards any
card that is not the account default. Both are checked before anything is
dropped, so a refusal costs nothing.
=============================================================================
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "v1a01_billing_account"
down_revision = "u1a01_subscription_types"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

GROUP = "payer_billing_group"
UQ_GROUP_CARD = "uq_payer_billing_group_payer_card"
COL_EMAIL = "billing_email"
COL_COMPANY = "billing_company"

CARD = "billing_account_payment_method"
UQ_CARD_UNIQUE = "uq_billing_account_payment_method_card"
UQ_CARD_DEFAULT = "uq_billing_account_payment_method_default"
IX_CARD_GROUP = "ix_billing_account_payment_method_group"


def _uuid():
    """The id type, matching ``u1a01``: a uuid in the database, a ``str`` in Python.

    ``as_uuid=False`` for the reason that revision spells out at length - every
    interpolated idempotency key in this application is built from these ids as
    text, and a key that changes shape stops matching one already claimed.
    """
    return postgresql.UUID(as_uuid=False)


def _ts():
    return sa.TIMESTAMP(timezone=True)


def _inspector(bind):
    return sa.inspect(bind)


def _columns(bind, table) -> set[str]:
    return {c["name"] for c in _inspector(bind).get_columns(table, schema=SCHEMA)}


def _has_table(bind, table) -> bool:
    return _inspector(bind).has_table(table, schema=SCHEMA)


def _constraints(bind, table) -> set[str]:
    names = {
        c["name"] for c in _inspector(bind).get_unique_constraints(table, schema=SCHEMA)
    }
    return {n for n in names if n}


# --- 1. the identity columns ---------------------------------------------------


def _upgrade_identity_columns(bind):
    present = _columns(bind, GROUP)
    for name in (COL_EMAIL, COL_COMPANY):
        if name in present:
            print(f"{SCHEMA}.{GROUP}.{name} already exists - skipping.")
            continue
        op.add_column(
            GROUP, sa.Column(name, sa.String(255), nullable=True), schema=SCHEMA
        )
        print(f"Added {SCHEMA}.{GROUP}.{name} (all NULL - see the header).")


# --- 2. billing_account_payment_method -----------------------------------------


def _upgrade_card_table(bind):
    if _has_table(bind, CARD):
        print(f"{SCHEMA}.{CARD} already exists - skipping.")
        return

    op.create_table(
        CARD,
        sa.Column("id", _uuid(), primary_key=True),
        # INTERNAL -> payer_billing_group.id, which u1a01 converted to uuid.
        sa.Column("billing_group_id", _uuid(), nullable=False),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["billing_group_id"], [f"{SCHEMA}.{GROUP}.id"],
            name="fk_billing_account_payment_method_group",
            ondelete="CASCADE",
        ),
        # One row per card per account. Re-adding a card the account already holds
        # is an update of that row, never a second one.
        sa.UniqueConstraint(
            "billing_group_id", "stripe_payment_method_id", name=UQ_CARD_UNIQUE
        ),
        schema=SCHEMA,
    )
    op.create_index(IX_CARD_GROUP, CARD, ["billing_group_id"], schema=SCHEMA)

    # AT MOST ONE DEFAULT PER ACCOUNT, enforced rather than merely indexed - a second
    # default is not a slow query, it is an account that cannot say which card it
    # charges. Partial where the dialect supports it, since every non-default row is
    # unconstrained; a plain unique index on billing_group_id alone would allow only
    # ONE card per account, which is the opposite of the point.
    if bind.dialect.name == "postgresql":
        op.create_index(
            UQ_CARD_DEFAULT, CARD, ["billing_group_id"], schema=SCHEMA, unique=True,
            postgresql_where=sa.text("is_default"),
        )
    else:
        # No partial index off postgres. The pair is still unique, so the same card
        # cannot be the default twice; a SECOND default card is caught by the
        # application check in ``store.set_group_default_card`` alone on this path.
        op.create_index(
            UQ_CARD_DEFAULT, CARD, ["billing_group_id", "is_default"], schema=SCHEMA
        )
    print(f"Created {SCHEMA}.{CARD}.")


def _backfill_shelves(bind):
    """Give every existing account a shelf holding exactly the card it charges.

    Written in Python rather than one INSERT..SELECT so the ids are generated the
    way the models generate them - ``str(uuid.uuid4())`` - on every dialect, rather
    than depending on ``gen_random_uuid()`` being present.

    Idempotent: only groups with no row at all are inserted, so a re-run after a
    half-completed migration adds the missing ones and touches nothing else.
    """
    rows = bind.execute(
        sa.text(
            f"""
            SELECT g.id, g.stripe_payment_method_id
              FROM {SCHEMA}.{GROUP} g
             WHERE NOT EXISTS (
                   SELECT 1 FROM {SCHEMA}.{CARD} c
                    WHERE c.billing_group_id = g.id
             )
            """
        )
    ).fetchall()

    if not rows:
        print("No billing accounts need a shelf - nothing to backfill.")
        return

    for group_id, payment_method in rows:
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.{CARD}
                       (id, billing_group_id, stripe_payment_method_id, is_default)
                VALUES (:id, :group_id, :pm, true)
                """
            ),
            {"id": str(uuid.uuid4()), "group_id": group_id, "pm": payment_method},
        )
    print(f"Backfilled {len(rows)} shelf row(s), each the account's current default.")


# --- 3. the constraint that has to go ------------------------------------------


def _upgrade_drop_group_unique(bind):
    if UQ_GROUP_CARD not in _constraints(bind, GROUP):
        print(f"{UQ_GROUP_CARD} is already absent - skipping.")
        return
    op.drop_constraint(UQ_GROUP_CARD, GROUP, type_="unique", schema=SCHEMA)
    print(f"Dropped {UQ_GROUP_CARD} - see the header for what replaces it.")


# --- the revision ---------------------------------------------------------------


def upgrade():
    bind = op.get_bind()
    # Each part is individually idempotent, in the house style: the .sql twin can be
    # run by hand on an environment alembic does not stamp, and a re-run must not fail.
    _upgrade_identity_columns(bind)
    _upgrade_card_table(bind)
    _backfill_shelves(bind)
    _upgrade_drop_group_unique(bind)


def _cards_beyond_the_default(bind) -> int:
    """Cards on a shelf that are NOT the account's charged card.

    These are the only rows the drop would actually lose - every default is
    recoverable from ``payer_billing_group.stripe_payment_method_id``.
    """
    return bind.execute(
        sa.text(
            f"""
            SELECT count(*)
              FROM {SCHEMA}.{CARD} c
              JOIN {SCHEMA}.{GROUP} g ON g.id = c.billing_group_id
             WHERE c.stripe_payment_method_id <> g.stripe_payment_method_id
            """
        )
    ).scalar()


def _duplicate_payer_cards(bind) -> list:
    """Payers holding one card on more than one account.

    Legal after this revision, and exactly what ``uq_payer_billing_group_payer_card``
    forbids - so the downgrade cannot re-add it while any of these exist.
    """
    return bind.execute(
        sa.text(
            f"""
            SELECT payer_user_id, stripe_payment_method_id, count(*) AS n
              FROM {SCHEMA}.{GROUP}
             GROUP BY payer_user_id, stripe_payment_method_id
            HAVING count(*) > 1
            """
        )
    ).fetchall()


def downgrade():
    bind = op.get_bind()

    # CHECKED BEFORE ANYTHING IS DROPPED, so a refusal costs nothing.
    if _has_table(bind, GROUP):
        duplicates = _duplicate_payer_cards(bind)
        if duplicates:
            listed = ", ".join(
                f"payer {row[0]} holds card {row[1]} on {row[2]} accounts"
                for row in duplicates[:10]
            )
            raise RuntimeError(
                f"Refusing to downgrade: {len(duplicates)} payer/card pair(s) exist on "
                f"more than one billing account, which {UQ_GROUP_CARD} forbids. "
                f"{listed}. Merge or repoint those accounts by hand first - re-adding "
                "the constraint here would fail partway through the downgrade and "
                "leave the revision neither applied nor reverted."
            )

    if _has_table(bind, CARD):
        extra = _cards_beyond_the_default(bind)
        if extra:
            print(
                f"WARNING: dropping {SCHEMA}.{CARD} discards {extra} saved card(s) that "
                "are not their account's default. The defaults survive on "
                f"{GROUP}.stripe_payment_method_id; these do not, and the payer will "
                "have to add them again."
            )

    # 3 -> 1, the reverse of upgrade().
    if _has_table(bind, GROUP) and UQ_GROUP_CARD not in _constraints(bind, GROUP):
        op.create_unique_constraint(
            UQ_GROUP_CARD, GROUP,
            ["payer_user_id", "stripe_payment_method_id"], schema=SCHEMA,
        )

    if _has_table(bind, CARD):
        for name in (UQ_CARD_DEFAULT, IX_CARD_GROUP):
            try:
                op.drop_index(name, table_name=CARD, schema=SCHEMA)
            except Exception:  # noqa: BLE001 - absent if a previous run half-completed
                pass
        op.drop_table(CARD, schema=SCHEMA)

    present = _columns(bind, GROUP)
    for name in (COL_COMPANY, COL_EMAIL):
        if name in present:
            op.drop_column(GROUP, name, schema=SCHEMA)
