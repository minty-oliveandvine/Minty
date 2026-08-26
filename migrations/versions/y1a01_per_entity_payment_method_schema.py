"""PER-ENTITY PAYMENT METHODS — the schema for a card per company

Revision ID: y1a01_billing_group_schema
Revises: k1a01_drop_consent
Create Date: 2026-08-25

=============================================================================
WHAT THIS IS

A payer has exactly ONE card today. ``services.payment_methods`` says so in its own
docstring: the engine reads ``invoice_settings.default_payment_method`` on the payer's
single Stripe customer and nothing else, so every "choose a card" control in the app is
really "change the account default", and changing it repoints every company that payer
pays for.

This revision lays the schema for a card per COMPANY, with invoices grouped by the card
the companies are set to. Three tables' worth of structure, in one revision because there
is no state in which half of it is useful:

  1. pettycashv2.payer_billing_group              (new table)  — a card and its cycle
  2. pettycashv2.entity_billing_group             (new table)  — which card pays for what
  3. subscription_invoice.billing_group_id        (new column) — which card was billed

Nothing is dropped and nothing is backfilled by this revision. It is purely additive, and
no service reads any of it: ``user_stripe_customer.paid_through`` and its dunning columns
remain authoritative until the cutover lands.

-----------------------------------------------------------------------------
1. payer_billing_group — one card, and the cycle that card owns

A "group" is one payment method plus everything it pays for. Three fields move off
``user_stripe_customer`` onto it, and each one had to:

  * ``paid_through`` — one invoice is raised per group, so this is exactly the grain the
    money is collected at. A payer with two cards has two answers to "what has been paid
    for", and one column cannot hold both;
  * ``dunning_started_at`` / ``dunning_attempts`` — the decision this feature was scoped
    around is that a DECLINE IS CONTAINED: company A on a good card keeps working while
    company B's dead card goes to collection. That is impossible while the retry clock is
    a single per-payer value, because every retry decision is then taken for the whole
    account at once.

This is NOT the per-row ``current_period_end`` coming back. That one was removed for
drifting between one payer's entities, and it drifted because it was refreshed only when
its own entity happened to be touched — three rows of one payer holding three different
answers to the same question. This value is written by exactly one thing, the charge that
collected it, and there is one such charge per group per period.

``anchor_at`` and ``currency`` deliberately STAY on ``user_stripe_customer``. Every group
of a payer renews on the same period boundaries — one cycle, several invoices — so
``billing.period_containing`` and the month-end clamp are untouched, and a payer's
invoices still cannot mix currencies.

THE CARD IS AN ATTRIBUTE, NOT THE KEY. Entities point at the group; the group names the
card. If they pointed straight at a ``pm_...`` id, replacing an expiring card would
strand the cycle — a new id is a new key, its ``paid_through`` starts NULL, and
``renewals.due_renewals`` skips NULL outright, so the company would quietly stop renewing
with nothing raising an error. Here, replacing a card is an UPDATE of one column.

UNIQUE (payer_user_id, stripe_payment_method_id): a payer must not hold two groups on one
card, or the same company's renewal could be claimed by either and the two would disagree
about what was paid.

-----------------------------------------------------------------------------
2. entity_billing_group — which card pays for this company

Grain (entity_id, payer_user_id), which is the same grain ``x1a01`` widened
``entity_billing_consent`` to, for the same reason. Unique on ``entity_id`` alone, the OLD
payer's nomination would go on naming a card after the company had been handed to someone
else — and that card belongs to a different person. The previous payer's row stays as
history.

NOT a column on ``entity_module_subscription``: that table is per (entity, MODULE), so a
card held there would have to be kept in agreement across an entity's rows. That is the
burden ``payer_user_id`` already carries, and the reason ``store.upsert_module_row``
refuses to change it rather than trusting callers. One row per company is the honest
shape for a per-company fact.

``billing_group_id`` is NOT NULL. A row here exists to say which card pays; a row saying
"none" would be the account-default fallback by another name, and there is deliberately
no fallback — a billable entity with no row is a billing error to be reported, not a
default to be inherited silently.

ON DELETE CASCADE on the entity: a nomination for a company that no longer exists is not
history worth keeping (the invoices are, and they are on a different table with no FKs).

-----------------------------------------------------------------------------
3. subscription_invoice.billing_group_id — which card was billed

A renewal stops being one document per payer per period. Both
``renewals._already_invoiced`` (the double-billing guard) and
``dunning._current_period_key`` (the retry target) currently ask "the payer's invoice for
this period"; per group they have to ask "this GROUP's invoice for this period", and they
must be able to ask it of the local row rather than by scanning the processor.

Nullable, no FK, no backfill. NULL on every existing row means "raised before per-entity
cards existed", which is exactly true and is what those rows should say: one card paid
for everything on them.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

Two CREATE TABLEs and one nullable ADD COLUMN — no rewrite, no lock on existing traffic,
nothing reading it. A deploy in either order is safe: old code cannot see the tables, and
new code does not consult them until the cutover revision ships the services that do.

The tables are EMPTY after this runs. ``scripts/backfill_billing_groups.py`` is what
makes them true — it reads each payer's Stripe default and gives every payer exactly one
group holding exactly today's state, so the cutover is a behavioural no-op until someone
nominates a second card. It needs Stripe and therefore cannot live in a migration.

-----------------------------------------------------------------------------
THE DOWNGRADE REFUSES ONCE THE CUTOVER HAS RUN

Before the cutover these tables are decoration and dropping them costs nothing. After it,
they are the ONLY record of what each card has collected, and ``user_stripe_customer``
holds a stale copy at best. So the downgrade checks first and REFUSES outright if any
group's ``paid_through`` or dunning clock has moved past what its payer's row still says.
Dropping them there would re-bill periods already paid and abandon collection runs
already in progress — silently, and for real money.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op


revision = "y1a01_billing_group_schema"
down_revision = "k1a01_drop_consent"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

GROUP = "payer_billing_group"
UQ_GROUP_CARD = "uq_payer_billing_group_payer_card"
IX_GROUP_PAYER = "ix_payer_billing_group_payer"
IX_GROUP_DUNNING = "ix_payer_billing_group_dunning"

NOMINATION = "entity_billing_group"
UQ_NOMINATION = "uq_entity_billing_group_entity_payer"
IX_NOMINATION_ENTITY = "ix_entity_billing_group_entity"
IX_NOMINATION_PAYER = "ix_entity_billing_group_payer"
IX_NOMINATION_GROUP = "ix_entity_billing_group_group"

INVOICE = "subscription_invoice"
INVOICE_GROUP = "billing_group_id"
IX_INVOICE_GROUP = "ix_subscription_invoice_group"

CUSTOMER = "user_stripe_customer"


def _columns(bind, table) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table, schema=SCHEMA)}


def _has_table(bind, table) -> bool:
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


# --- 1. payer_billing_group ----------------------------------------------------


def _upgrade_group_table(bind):
    if _has_table(bind, GROUP):
        print(f"{SCHEMA}.{GROUP} already exists — skipping.")
        return

    op.create_table(
        GROUP,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=False),
        # NULL until this card has actually collected something. ``due_renewals`` skips
        # a NULL, which is what stops a freshly nominated card being billed for history.
        sa.Column("paid_through", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dunning_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "dunning_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        # FK to ``user``, not to ``user_stripe_customer`` — the same choice the module
        # rows make, so a group can be nominated before the payer has been charged.
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="fk_payer_billing_group_user",
        ),
        sa.UniqueConstraint(
            "payer_user_id", "stripe_payment_method_id", name=UQ_GROUP_CARD
        ),
        schema=SCHEMA,
    )
    op.create_index(IX_GROUP_PAYER, GROUP, ["payer_user_id"], schema=SCHEMA)

    # The collection work list. Partial on postgres: NULL on nearly every group forever,
    # and the one query that reads it reads it as a predicate.
    if bind.dialect.name == "postgresql":
        op.create_index(
            IX_GROUP_DUNNING, GROUP, ["dunning_started_at"], schema=SCHEMA,
            postgresql_where=sa.text("dunning_started_at IS NOT NULL"),
        )
    else:
        op.create_index(IX_GROUP_DUNNING, GROUP, ["dunning_started_at"], schema=SCHEMA)

    print(
        f"Created {SCHEMA}.{GROUP} (empty — scripts/backfill_billing_groups.py fills it)."
    )


# --- 2. entity_billing_group ---------------------------------------------------


def _upgrade_nomination_table(bind):
    if _has_table(bind, NOMINATION):
        print(f"{SCHEMA}.{NOMINATION} already exists — skipping.")
        return

    op.create_table(
        NOMINATION,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("billing_group_id", sa.String(36), nullable=False),
        # capture / chosen / backfill — mirrors entity_billing_consent.source.
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="fk_entity_billing_group_entity", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="fk_entity_billing_group_user",
        ),
        sa.ForeignKeyConstraint(
            ["billing_group_id"], [f"{SCHEMA}.{GROUP}.id"],
            name="fk_entity_billing_group_group",
        ),
        # One nomination per company per payer. NOT on entity_id alone — see the header.
        sa.UniqueConstraint("entity_id", "payer_user_id", name=UQ_NOMINATION),
        schema=SCHEMA,
    )
    op.create_index(IX_NOMINATION_ENTITY, NOMINATION, ["entity_id"], schema=SCHEMA)
    op.create_index(IX_NOMINATION_PAYER, NOMINATION, ["payer_user_id"], schema=SCHEMA)
    op.create_index(
        IX_NOMINATION_GROUP, NOMINATION, ["billing_group_id"], schema=SCHEMA
    )
    print(f"Created {SCHEMA}.{NOMINATION} (empty — nothing has been nominated yet).")


# --- 3. subscription_invoice.billing_group_id ----------------------------------


def _upgrade_invoice_column(bind):
    if INVOICE_GROUP in _columns(bind, INVOICE):
        print(f"{SCHEMA}.{INVOICE}.{INVOICE_GROUP} already exists — skipping.")
        return

    op.add_column(
        INVOICE, sa.Column(INVOICE_GROUP, sa.String(36), nullable=True), schema=SCHEMA
    )
    # (group, period_start) is the shape both readers want: "this group's invoice for
    # this period". Partial on postgres — NULL on every row raised before groups.
    if bind.dialect.name == "postgresql":
        op.create_index(
            IX_INVOICE_GROUP, INVOICE, [INVOICE_GROUP, "period_start"], schema=SCHEMA,
            postgresql_where=sa.text(f"{INVOICE_GROUP} IS NOT NULL"),
        )
    else:
        op.create_index(
            IX_INVOICE_GROUP, INVOICE, [INVOICE_GROUP, "period_start"], schema=SCHEMA
        )
    print(
        f"Added {SCHEMA}.{INVOICE}.{INVOICE_GROUP} (all NULL — no backfill, by design)."
    )


# --- the revision ---------------------------------------------------------------


def upgrade():
    bind = op.get_bind()
    # Each part is individually idempotent, in the house style: the .sql twin can be run
    # by hand on an environment alembic does not stamp, and a re-run must not fail.
    _upgrade_group_table(bind)
    _upgrade_nomination_table(bind)
    _upgrade_invoice_column(bind)


def _cutover_has_run(bind) -> list:
    """Groups whose money state has moved past what ``user_stripe_customer`` still says.

    Empty before the cutover — the backfill copies the payer's values verbatim, so every
    group matches its payer exactly and dropping the tables loses nothing. Non-empty
    afterwards, and then these rows are the ONLY record of what each card collected.
    """
    return bind.execute(
        sa.text(
            f"""
            SELECT g.id, g.payer_user_id, g.paid_through, g.dunning_started_at
              FROM {SCHEMA}.{GROUP} g
              LEFT JOIN {SCHEMA}.{CUSTOMER} u ON u.user_id = g.payer_user_id
             WHERE (g.paid_through IS NOT NULL
                    AND (u.paid_through IS NULL OR g.paid_through <> u.paid_through))
                OR (g.dunning_started_at IS NOT NULL
                    AND (u.dunning_started_at IS NULL
                         OR g.dunning_started_at <> u.dunning_started_at))
            """
        )
    ).fetchall()


def downgrade():
    bind = op.get_bind()

    # CHECKED BEFORE ANYTHING IS DROPPED, so a refusal costs nothing.
    if _has_table(bind, GROUP):
        diverged = _cutover_has_run(bind)
        if diverged:
            listed = ", ".join(
                f"group {row[0]} (payer {row[1]}, paid_through {row[2]}, "
                f"dunning {row[3]})"
                for row in diverged[:10]
            )
            raise RuntimeError(
                f"Refusing to downgrade: {len(diverged)} billing group(s) hold money "
                "state that user_stripe_customer does not — the cutover has run and "
                f"these rows are the only record of it. {listed}. Dropping them re-bills "
                "periods already paid and abandons collection runs in progress. Migrate "
                "the state back onto user_stripe_customer by hand first, or restore from "
                "backup."
            )

    if _has_table(bind, NOMINATION):
        total = bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.{NOMINATION}")
        ).scalar()
        if total:
            print(
                f"WARNING: dropping {SCHEMA}.{NOMINATION} discards {total} card "
                "nomination(s). Every company goes back to being billed on its payer's "
                "account default, whichever card that now is."
            )

    # 3 -> 1, the reverse of upgrade(). Child table before parent, or the FK blocks it.
    if INVOICE_GROUP in _columns(bind, INVOICE):
        try:
            op.drop_index(IX_INVOICE_GROUP, table_name=INVOICE, schema=SCHEMA)
        except Exception:  # noqa: BLE001 - absent if a previous run half-completed
            pass
        op.drop_column(INVOICE, INVOICE_GROUP, schema=SCHEMA)

    if _has_table(bind, NOMINATION):
        for name in (
            IX_NOMINATION_GROUP, IX_NOMINATION_PAYER, IX_NOMINATION_ENTITY
        ):
            try:
                op.drop_index(name, table_name=NOMINATION, schema=SCHEMA)
            except Exception:  # noqa: BLE001 - see above
                pass
        op.drop_table(NOMINATION, schema=SCHEMA)

    if _has_table(bind, GROUP):
        for name in (IX_GROUP_DUNNING, IX_GROUP_PAYER):
            try:
                op.drop_index(name, table_name=GROUP, schema=SCHEMA)
            except Exception:  # noqa: BLE001 - see above
                pass
        op.drop_table(GROUP, schema=SCHEMA)
