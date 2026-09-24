"""A HANDOVER TAKES NO MONEY AT ACCEPT, AND SAYS HOW IT ENDED EXACTLY ONCE

Revision ID: w1a01_transfer_handover
Revises: v1a01_billing_account
Create Date: 2026-09-24

=============================================================================
WHAT THIS IS

Two nullable columns on ``subscription_transfer``, and one partial index:

  ``collect_at``       - this handover owes a first charge, from this instant
  ``outcome_seen_at``  - the payer who ASKED has been shown how it ended

They are one revision because they are one feature. A handover is a single act
with two ends: the money it moves, and the telling of the person who started it.
Neither column can be read by code that does not also know about the other, and
neither has ever existed anywhere - both were added to
``docs/schema/01_schema_rebased.sql`` in the same change. Splitting them would
buy two bookmarks in ``alembic_version`` and nothing else.

-----------------------------------------------------------------------------
collect_at - THE CHARGE IS PARKED UNTIL THE DAY IT STARTS

Accepting a handover charged the incoming payer inside the accept request, for
the window between the OUTGOING payer's ``paid_through`` and the incoming
payer's own period end. That window is usually in the FUTURE - the outgoing
payer has bought days that have not been used yet - so the customer was asked
for money weeks before the thing it pays for begins. Accepted on 24 September,
the charge read "HKD 245.16 for 18 Oct 2026 to 6 Nov 2026", taken today.

A handover should not take money. The window does not change and the amount does
not change; only the DAY the card is charged moves, from the accept to the start
of the window it pays for. Which needs one fact written down: this company owes
a first charge, from this instant.

WHY A COLUMN AND NOT A STATUS, OR AN INFERENCE. A STATUS would have to live in
``transfer_status``, and the three states that mean "an offer is open" - pending,
charging, charged - are the condition of ``uq_subscription_transfer_open``, the
partial unique index that allows one live offer per company. A handover waiting
for its collection date is FINISHED: the payer has flipped, the consent is
recorded, the old payer is no longer liable, and the company must be free to be
handed on again. Parking it in an open state would hold that slot for weeks.

AN INFERENCE from the columns already here was the alternative, and it does not
hold. The obvious one - ``status = 'accepted' AND charge_invoice_id IS NULL`` -
is wrong twice over: a charge whose invoice totals zero succeeds with no invoice
id, and a trial-only handover legitimately completes having charged nothing at
all. Both would read as "money is owed" forever.

NOT NULL means: the first charge for this handover has not been collected, and
becomes collectable at this instant. The daily pass picks up every row whose
``collect_at`` has passed, charges it on the incoming payer's card, and CLEARS
the column. Cleared is the only marker of "settled" - there is no second flag to
disagree with it. NULL is every other handover, including every one that already
exists: one that charged at accept (because its window had already begun) and
one that charged nothing (a trial-only company) are both simply NULL, which is
what they are today.

-----------------------------------------------------------------------------
outcome_seen_at - TELLING THE PAYER HOW IT ENDED, ONCE

A handover offer ends in one of three ways the person who ASKED did not choose:
the recipient declines it, the recipient accepts it, or it expires unanswered.
The application emails them, and that was the whole of it - every read of
``subscription_transfer`` in the engine filters on the three OPEN statuses, so a
declined offer is invisible to the portal. The screen it was offered from falls
back to the subscriber picker exactly as though nothing had ever been asked.

The design (Figma 07-I / A-07, and A-08 for an expired one) puts a modal over
Subscription & Billing: "<Name> declined the transfer. You can send a new request
to anyone anytime." Done. A modal like that needs to know one thing the database
could not answer: has this person been told yet. Without it the modal reopens on
every visit forever, which is how people learn to dismiss things without reading
them.

WHY A COLUMN AND NOT THE EMAIL LOG. ``subscription_email_log`` already holds a
durable row per notification, keyed ``transfer-<id>-declined``, and it is
tempting to read that as "they have been told". It is not. It records that an
email was SENT - not delivered, not opened, not read. A message that bounced, or
went to a filtered folder, would silently suppress the only other place the news
appears. Nor is a browser the place for it: the decline happened while the payer
was away, which is exactly the case the front end cannot remember - its existing
"show this once" mechanisms all carry a fact from one screen to the next within a
session, and it stores nothing at all across visits. Asked directly, the choice
was for a marker that holds on every device.

NOT NULL means: the payer who made this offer has been shown how it ended, at
this instant. It is stamped when they press Done, by their own request - not by
the job that emails them, and not by the read that renders the modal, because
neither of those is evidence that a person saw anything. NULL is every other
row, including every one that exists today.

-----------------------------------------------------------------------------
NO BACKFILL, FOR EITHER

Every historic row is NULL, and NULL is the truthful answer for all of them. The
alternative for ``outcome_seen_at`` would be stamping thousands of old transfers
as "seen" on the strength of an assumption, or opening a modal about a handover
somebody answered months ago. The read is narrow enough that the second risk is
real, so the application, not this revision, bounds it.

-----------------------------------------------------------------------------
ONE INDEX, PARTIAL, AND ONLY ON collect_at

``ix_subscription_transfer_collect`` covers only the rows where ``collect_at`` is
NOT NULL. In steady state that is a handful of rows out of every handover ever
made - the same shape, and the same reasoning, as
``ix_subscription_transfer_stranded``, which the repair step reads. A full index
on a column that is NULL for almost every row is mostly a copy of the table.

``outcome_seen_at`` gets no index at all. Its query is "offers I made, in a
terminal state, not yet seen", already narrowed by ``from_user_id`` - a column
``ix_subscription_transfer_to_user`` does not cover, but one that selects a
handful of rows per payer regardless. An index on ``outcome_seen_at`` alone
would be almost entirely NULLs and almost entirely useless. Add one when a slow
query says so, not before.

Off postgres there are no partial indexes, so the plain column index is created
instead. It is a performance difference only; the job's query is identical.

-----------------------------------------------------------------------------
IT TOUCHES pettycashv3 AND NOTHING ELSE

Every revision before this one names ``pettycashv2``. That schema is being
retired - it keeps its shape for its retention period and is then dropped - so a
new column there would be built on something on its way out. This is a
pettycashv3 feature and lives only in pettycashv3.

Which makes this revision a belt to the schema file's braces rather than the
primary source. ``pettycashv3`` carries no ``alembic_version`` of its own: it is
built from ``docs/schema/01_schema_rebased.sql`` (via
``docs/schema/supabase/pettycashv3.sql``, which is regenerated by
``docs/schema/generators/strip_comments.py``), and that file declares both
columns and the index - so a FRESH build already has them. This exists for the
databases that are already up, and it is guarded and idempotent, so running it
against one that has them is a no-op. The chain still runs through
``pettycashv2.alembic_version``, which is only where the bookmark is kept - the
DDL below goes nowhere near that schema.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE

Two nullable ADD COLUMNs and one CREATE INDEX. No rewrite, no lock on existing
traffic, no backfill. Old code does not know the columns exist and behaves
exactly as it does today; new code reads NULL on every historic row and leaves
them alone.

THE DOWNGRADE REFUSES IF MONEY IS OWED. Dropping ``collect_at`` while a row
still carries one discards a debt: the company has changed hands, nobody has
been charged, and after the drop there is nothing left that knows. The downgrade
counts those rows FIRST - before dropping anything at all, including
``outcome_seen_at`` - and raises rather than proceeding. Collect them (run the
daily pass) or clear the column deliberately, and it will run.

``outcome_seen_at`` carries no such weight. Dropping it loses the record that
some people have already been shown an outcome, so a few modals reopen once.
That is an annoyance, not a loss - no money and no entitlement rides on it.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op


revision = "w1a01_transfer_handover"
down_revision = "v1a01_billing_account"
branch_labels = None
depends_on = None

# PETTYCASHV3 ONLY, unlike every revision before it - see the header.
SCHEMA = "pettycashv3"

TRANSFER = "subscription_transfer"
COL_COLLECT = "collect_at"
COL_SEEN = "outcome_seen_at"
IX_COLLECT = "ix_subscription_transfer_collect"


def _inspector(bind):
    return sa.inspect(bind)


def _columns(bind, table) -> set[str]:
    return {c["name"] for c in _inspector(bind).get_columns(table, schema=SCHEMA)}


def _indexes(bind, table) -> set[str]:
    return {i["name"] for i in _inspector(bind).get_indexes(table, schema=SCHEMA) if i.get("name")}


def upgrade():
    bind = op.get_bind()

    if not _inspector(bind).has_table(TRANSFER, schema=SCHEMA):
        print(f"{SCHEMA}.{TRANSFER} does not exist - nothing to do.")
        return

    existing = _columns(bind, TRANSFER)

    for column in (COL_COLLECT, COL_SEEN):
        if column in existing:
            print(f"{SCHEMA}.{TRANSFER}.{column} already exists - skipping.")
            continue
        op.add_column(
            TRANSFER,
            sa.Column(column, sa.TIMESTAMP(timezone=True), nullable=True),
            schema=SCHEMA,
        )
        print(f"Added {SCHEMA}.{TRANSFER}.{column} (all NULL - see the header).")

    if IX_COLLECT in _indexes(bind, TRANSFER):
        print(f"{IX_COLLECT} already exists - skipping.")
        return

    if bind.dialect.name == "postgresql":
        op.create_index(
            IX_COLLECT, TRANSFER, [COL_COLLECT], schema=SCHEMA,
            postgresql_where=sa.text(f"{COL_COLLECT} IS NOT NULL"),
        )
    else:
        op.create_index(IX_COLLECT, TRANSFER, [COL_COLLECT], schema=SCHEMA)
    print(f"Created {IX_COLLECT}.")


def downgrade():
    bind = op.get_bind()

    if not _inspector(bind).has_table(TRANSFER, schema=SCHEMA):
        return

    existing = _columns(bind, TRANSFER)

    # MONEY OWED IS NOT DROPPABLE, and it is checked before ANYTHING is dropped. Each
    # of these rows is a company that has changed hands and has not been charged for
    # it; the column is the only record that the debt exists. Counted first, so a
    # refusal costs nothing and leaves the revision exactly as it was.
    if COL_COLLECT in existing:
        owed = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {SCHEMA}.{TRANSFER} WHERE {COL_COLLECT} IS NOT NULL"
            )
        ).scalar()
        if owed:
            raise RuntimeError(
                f"{owed} handover(s) still have an uncollected charge in "
                f"{SCHEMA}.{TRANSFER}.{COL_COLLECT}. Dropping the column would discard "
                f"the only record that the money is owed. Collect them (run the daily "
                f"pass) or clear the column deliberately, then run this again."
            )

    if COL_SEEN in existing:
        op.drop_column(TRANSFER, COL_SEEN, schema=SCHEMA)
        print(f"Dropped {SCHEMA}.{TRANSFER}.{COL_SEEN}.")
    else:
        print(f"{SCHEMA}.{TRANSFER}.{COL_SEEN} is already gone - nothing to do.")

    if COL_COLLECT not in existing:
        print(f"{SCHEMA}.{TRANSFER}.{COL_COLLECT} is already gone - nothing to do.")
        return

    if IX_COLLECT in _indexes(bind, TRANSFER):
        op.drop_index(IX_COLLECT, TRANSFER, schema=SCHEMA)
    op.drop_column(TRANSFER, COL_COLLECT, schema=SCHEMA)
    print(f"Dropped {SCHEMA}.{TRANSFER}.{COL_COLLECT}.")
