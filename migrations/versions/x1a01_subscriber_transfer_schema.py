"""TRANSFER — all schema for handing an entity's subscription to a new payer

Revision ID: x1a01_transfer_schema
Revises: p2a01_user_current_entity
Create Date: 2026-08-17

=============================================================================
WHAT THIS IS

The whole schema for "change subscriber", in one revision because it is one feature and
there is no state in which half of it is useful:

  1. entity_module_subscription.billed_through      (new column)
  2. pettycashv2.subscription_transfer              (new table)
  3. subscription_audit_log.payer_before / _after   (new columns)
  4. entity_billing_consent                         (UNIQUE entity_id -> entity_id,user_id)

1-3 are purely additive. 4 swaps a constraint and is the only part that changes an
existing rule.

-----------------------------------------------------------------------------
1. billed_through — "someone else already paid for these days"

Meaning: money already collected covers this row up to (exclusive) this instant, from a
source OTHER than the current payer's account cycle. NULL — every row that exists when
this runs — means "no such claim", i.e. exactly today's behaviour. Hence no backfill.

It exists because a transfer buys days outside a renewal: the entity moves on 20 Aug, the
old payer had paid it to 12 Sept, and the new payer is invoiced AT ACCEPT for 12 Sept ->
their own period end. ``renewals`` must then not bill those days again, and must still
advance the payer's cycle over them — excluding without advancing keeps the account
permanently due and re-bills it the next day.

Forward-only and never cleared. Deliberately absent from ``_MODULE_MUTABLE_FIELDS``, so
``upsert_module_row`` RAISES on it and no existing field-dict writer can clobber it.

NOT ``app_access_until``, which is the closest-looking column and wrong four ways over:
``access.access_end`` returns it at precedence rule 1 (before the past-due branch, so a
row carrying it gets no grace), and every successful charge, ``terminate_lapsed_module``
and ``_expire_due_trial`` all clear it.

NOT the old ``current_period_end`` either. That one rolled monthly and was recomputed per
entity, which is how three rows of one payer came to hold three different answers. This is
written twice in the life of a transfer and only ever moves forward.

-----------------------------------------------------------------------------
2. subscription_transfer — the offer AND the journal

Accepting has to charge the new payer and then move ``payer_user_id``, and those two
cannot be one transaction. Every helper in ``store`` commits its own unit of work: the
anchor by ``start_billing_cycle``, the invoice row by ``reserve_invoice`` BEFORE the
processor is contacted, its ``open`` status by ``settle_invoice`` before the payment is
even attempted. By the time a card declines, three writes are already on disk.

So the accept is ORDERED rather than atomic — charge first, flip second — and the order
needs somewhere durable to say how far it got:

    pending -> charging -> charged -> accepted

``charging`` is committed before the charge is attempted, ``charged`` once the money is in,
``accepted`` once the pointer has moved. A process that dies in between leaves a row saying
exactly where, which a retried accept and ``transfers.repair_stranded`` both finish by
ADOPTING the invoice already paid under the stored key — never by charging again.

The renewal runner already works this way. The difference is that a renewal recomputes its
key on the next pass anyway, so a crash repairs itself; an accept is a one-shot user action
that nothing would revisit. Hence the row.

``charge_attempt`` is what makes the idempotency key safe in both directions:
``transfer-{id}-{attempt}`` is identical for a double-click within one attempt, so the
unique index on ``subscription_invoice.idempotency_key`` refuses the second — and different
on the next attempt, so a declined card can be fixed and retried. Without the counter a
fixed key would JAM, because voiding an invoice deliberately keeps its row and key claimed.

The two partial indexes: ``uq_..._open`` is the double-accept guard, and it covers the
in-flight states as well as ``pending`` — a unique index on ``pending`` alone would let a
second accept start while the first was mid-charge, and both would move the same pointer.
``ix_..._stranded`` is the repair step's work list and is normally EMPTY.

No FK on either user — this records something that happened between two people and must
survive either of them being deleted. The entity FK does cascade: an offer to take over a
company that no longer exists is not history worth keeping.

-----------------------------------------------------------------------------
3. payer_before / payer_after — the audit log learns a second party

The log was built for actions with ONE party: cancel, uncancel, terminate. Its
``payer_user_id`` answers "whose bill was this", and for those three that is the whole
story. A transfer has two, and recording it as a single id loses the only question anyone
asks afterwards — where did this company's bill go, and who agreed to take it on.

``payer_user_id`` keeps its meaning (the payer at the time of the action, so the OUTGOING
one on a transfer). NULL on both new columns means "not a payer change", which is true of
every row written before this and every non-transfer action after it — so there is nothing
to backfill.

No width change for ``action``: the four new values are ``transfer_offered`` (16),
``transfer_accepted`` (17), ``transfer_declined`` (17) and ``transfer_cancelled`` (18).
The shipped column is VARCHAR(40) and the MODEL declares String(20) — the model is the
binding constraint, and all four fit it. Counted, not assumed.

-----------------------------------------------------------------------------
4. Consent per (entity, payer) — a latent authorisation hole

``entity_billing_consent`` is the gate the trial-end job checks before converting a trial
to a real charge with no user action at all. Unique on ``entity_id`` alone it holds exactly
one answer per company, and ``has_billing_consent`` never asked WHOSE. Indistinguishable
from correct only because an entity's payer never changed.

The moment a subscription can be handed over, the old payer's row becomes the authorisation
for charging the NEW payer's card. Worse, the accept could not even record the new payer's
consent: ``record_billing_consent`` early-returns when a row exists, so it would silently
no-op and leave the old row standing.

No backfill and nothing deleted. Every existing row already names its payer in ``user_id``;
widening the constraint just makes those rows mean what they always said. Old rows stay,
because "why was I billed for this entity in June" is asked most often by the person who no
longer pays.

The old constraint was declared inline as ``unique=True``, so the server named it and the
name is not written down anywhere. It is found by INSPECTION at run time; if it cannot be
found this says so and continues, since a leftover single-column unique would announce
itself the first time a second payer consents.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

Parts 1-3 are additive: nullable ADD COLUMNs and a CREATE TABLE, so no rewrite and no lock
on existing traffic. Part 4 drops a unique constraint (brief lock, no rewrite) and only
ever ALLOWS rows that were previously refused — so old code keeps working against the new
shape and a deploy in either order is safe. Nothing reads any of it until the transfer
service ships.

-----------------------------------------------------------------------------
THE DOWNGRADE CHECKS BEFORE IT DESTROYS

It runs in reverse, and the consent check comes FIRST so it aborts before anything else is
dropped. Two things it will not do quietly:

  * it REFUSES outright if any entity holds consent from more than one payer, because only
    one can survive UNIQUE (entity_id) and collapsing them would fabricate a record about
    the wrong person — the exact failure part 4 exists to prevent;
  * it WARNS, loudly and with counts, if transfers have run: dropping this discards who
    each company's bill moved between, re-bills every transferred entity on its new payer's
    next renewal for days already invoiced at accept, and — for any offer still mid-accept
    — abandons money already collected whose payer flip would never now be completed.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op


revision = "x1a01_transfer_schema"
down_revision = "p2a01_user_current_entity"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

EMS = "entity_module_subscription"
BILLED_THROUGH = "billed_through"
IX_BILLED_THROUGH = "ix_ems_billed_through"

TRANSFER = "subscription_transfer"
OPEN_STATUSES = "'pending','charging','charged'"
STRANDED_STATUSES = "'charging','charged'"

AUDIT = "subscription_audit_log"
AUDIT_COLUMNS = ("payer_before", "payer_after")
IX_AUDIT_PAYER_AFTER = "ix_sub_audit_payer_after"

CONSENT = "entity_billing_consent"
CONSENT_PAIR = "uq_entity_billing_consent_entity_user"


def _columns(bind, table) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table, schema=SCHEMA)}


def _has_table(bind, table) -> bool:
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def _uniques(bind, table) -> list[dict]:
    return sa.inspect(bind).get_unique_constraints(table, schema=SCHEMA)


def _consent_single_column_unique(bind) -> str | None:
    """The old ``UNIQUE (entity_id)``, whatever the server chose to call it."""
    for constraint in _uniques(bind, CONSENT):
        if list(constraint.get("column_names") or []) == ["entity_id"]:
            return constraint.get("name")
    return None


# --- 1. billed_through ---------------------------------------------------------


def _upgrade_billed_through(bind):
    if BILLED_THROUGH in _columns(bind, EMS):
        print(f"{SCHEMA}.{EMS}.{BILLED_THROUGH} already exists — skipping.")
        return
    op.add_column(
        EMS,
        sa.Column(BILLED_THROUGH, sa.TIMESTAMP(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    # Partial: NULL on every row that has never been transferred, which is nearly all of
    # them forever. Indexing only the non-null values keeps it small and still serves the
    # one query that reads it as a predicate.
    if bind.dialect.name == "postgresql":
        op.create_index(
            IX_BILLED_THROUGH, EMS, [BILLED_THROUGH], schema=SCHEMA,
            postgresql_where=sa.text(f"{BILLED_THROUGH} IS NOT NULL"),
        )
    else:
        op.create_index(IX_BILLED_THROUGH, EMS, [BILLED_THROUGH], schema=SCHEMA)
    print(f"Added {SCHEMA}.{EMS}.{BILLED_THROUGH} (all NULL — no backfill, by design).")


# --- 2. subscription_transfer --------------------------------------------------


def _upgrade_transfer_table(bind):
    if _has_table(bind, TRANSFER):
        print(f"{SCHEMA}.{TRANSFER} already exists — skipping.")
        return

    op.create_table(
        TRANSFER,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("from_user_id", sa.String(36), nullable=False),
        sa.Column("to_user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("responded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accepted_billed_through", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accepted_anchor_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("quoted_amount", sa.Integer(), nullable=True),
        sa.Column("quoted_currency", sa.String(3), nullable=True),
        sa.Column("charge_attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("charge_key", sa.String(120), nullable=True),
        sa.Column("charge_invoice_id", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="fk_subscription_transfer_entity", ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )

    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_subscription_transfer_open", TRANSFER, ["entity_id"], unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text(f"status IN ({OPEN_STATUSES})"),
        )
        op.create_index(
            "ix_subscription_transfer_stranded", TRANSFER, ["status"], schema=SCHEMA,
            postgresql_where=sa.text(f"status IN ({STRANDED_STATUSES})"),
        )
    else:
        # SQLite (tests) builds its schema from the model, which declares both partial
        # indexes with ``sqlite_where``. These plain forms keep a hand-run of this
        # migration usable without claiming a uniqueness they cannot scope.
        op.create_index(
            "ix_subscription_transfer_open", TRANSFER, ["entity_id", "status"],
            schema=SCHEMA,
        )
        op.create_index(
            "ix_subscription_transfer_stranded", TRANSFER, ["status"], schema=SCHEMA
        )

    op.create_index(
        "ix_subscription_transfer_to_user", TRANSFER, ["to_user_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_transfer_entity", TRANSFER, ["entity_id", "created_at"],
        schema=SCHEMA,
    )
    print(f"Created {SCHEMA}.{TRANSFER} (empty — nothing has been transferred).")


# --- 3. audit payer_before / payer_after ---------------------------------------


def _upgrade_audit_columns(bind):
    present = _columns(bind, AUDIT)
    added = []
    for column in AUDIT_COLUMNS:
        if column in present:
            continue
        op.add_column(
            AUDIT, sa.Column(column, sa.String(36), nullable=True), schema=SCHEMA
        )
        added.append(column)
    if not added:
        print(f"{SCHEMA}.{AUDIT} already has {', '.join(AUDIT_COLUMNS)} — skipping.")
        return

    # Supports "where did this person's companies go" and "who took this one on".
    if bind.dialect.name == "postgresql":
        op.create_index(
            IX_AUDIT_PAYER_AFTER, AUDIT, ["payer_after", "created_at"], schema=SCHEMA,
            postgresql_where=sa.text("payer_after IS NOT NULL"),
        )
    else:
        op.create_index(
            IX_AUDIT_PAYER_AFTER, AUDIT, ["payer_after", "created_at"], schema=SCHEMA
        )
    print(f"Added {', '.join(added)} to {SCHEMA}.{AUDIT} (all NULL — no backfill).")


# --- 4. consent per (entity, payer) --------------------------------------------


def _upgrade_consent_grain(bind):
    if CONSENT_PAIR in {c.get("name") for c in _uniques(bind, CONSENT)}:
        print(f"{SCHEMA}.{CONSENT} is already unique on (entity_id, user_id) — skipping.")
        return

    old = _consent_single_column_unique(bind)
    if old:
        op.drop_constraint(old, CONSENT, type_="unique", schema=SCHEMA)
        print(f"Dropped {old} (UNIQUE on entity_id alone).")
    else:
        print(
            "Could not find a single-column UNIQUE on entity_id — it may already have "
            "been removed. Adding the pair regardless; check by hand if a second consent "
            "for one entity is later refused."
        )
    op.create_unique_constraint(
        CONSENT_PAIR, CONSENT, ["entity_id", "user_id"], schema=SCHEMA
    )
    print(f"{SCHEMA}.{CONSENT} is now unique on (entity_id, user_id). No rows changed.")


# --- the revision ---------------------------------------------------------------


def upgrade():
    bind = op.get_bind()
    # Each part is individually idempotent, in the house style: the .sql twin can be run
    # by hand on an environment alembic does not stamp, and a re-run must not fail.
    _upgrade_billed_through(bind)
    _upgrade_transfer_table(bind)
    _upgrade_audit_columns(bind)
    _upgrade_consent_grain(bind)


def downgrade():
    bind = op.get_bind()

    # CHECKED BEFORE ANYTHING IS DROPPED, so a refusal costs nothing. By now an entity may
    # hold consent from two payers, and only one can survive UNIQUE (entity_id) — picking
    # either fabricates a record about the wrong person.
    clashes = bind.execute(
        sa.text(
            f"SELECT entity_id, count(*) FROM {SCHEMA}.{CONSENT} "
            "GROUP BY entity_id HAVING count(*) > 1"
        )
    ).fetchall()
    if clashes:
        listed = ", ".join(f"{row[0]} ({row[1]} consents)" for row in clashes)
        raise RuntimeError(
            "Refusing to downgrade: these entities have consent from more than one payer, "
            f"and only one can survive UNIQUE (entity_id) — {listed}. Decide which is "
            "correct and delete the others by hand first; collapsing them automatically "
            "would keep a record about the wrong person."
        )

    if _has_table(bind, TRANSFER):
        total = bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.{TRANSFER}")
        ).scalar()
        stranded = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {SCHEMA}.{TRANSFER} "
                f"WHERE status IN ({STRANDED_STATUSES})"
            )
        ).scalar()
        if total:
            print(
                f"WARNING: dropping {SCHEMA}.{TRANSFER} destroys {total} transfer "
                "record(s) — the only record of who handed which company to whom."
            )
        if stranded:
            print(
                f"WARNING: {stranded} of those are mid-accept (charging/charged). That is "
                "money already collected whose payer flip would never now be completed. "
                "Run the repair step before downgrading, or restore from backup."
            )

    if BILLED_THROUGH in _columns(bind, EMS):
        claims = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {SCHEMA}.{EMS} WHERE {BILLED_THROUGH} IS NOT NULL"
            )
        ).scalar()
        if claims:
            print(
                f"WARNING: dropping {BILLED_THROUGH} discards a transfer claim on {claims} "
                "module row(s). Those entities will be billed again on their new payer's "
                "next renewal for days already invoiced at accept."
            )

    # 4 -> 1, the reverse of upgrade().
    if CONSENT_PAIR in {c.get("name") for c in _uniques(bind, CONSENT)}:
        op.drop_constraint(CONSENT_PAIR, CONSENT, type_="unique", schema=SCHEMA)
    if not _consent_single_column_unique(bind):
        op.create_unique_constraint(
            "uq_entity_billing_consent_entity", CONSENT, ["entity_id"], schema=SCHEMA
        )

    audit_present = _columns(bind, AUDIT)
    if set(AUDIT_COLUMNS) & audit_present:
        try:
            op.drop_index(IX_AUDIT_PAYER_AFTER, table_name=AUDIT, schema=SCHEMA)
        except Exception:  # noqa: BLE001 - absent if a previous run half-completed
            pass
        for column in AUDIT_COLUMNS:
            if column in audit_present:
                op.drop_column(AUDIT, column, schema=SCHEMA)

    if _has_table(bind, TRANSFER):
        for name in (
            "ix_subscription_transfer_entity",
            "ix_subscription_transfer_to_user",
            "ix_subscription_transfer_stranded",
            "uq_subscription_transfer_open"
            if bind.dialect.name == "postgresql"
            else "ix_subscription_transfer_open",
        ):
            try:
                op.drop_index(name, table_name=TRANSFER, schema=SCHEMA)
            except Exception:  # noqa: BLE001 - see above
                pass
        op.drop_table(TRANSFER, schema=SCHEMA)

    if BILLED_THROUGH in _columns(bind, EMS):
        try:
            op.drop_index(IX_BILLED_THROUGH, table_name=EMS, schema=SCHEMA)
        except Exception:  # noqa: BLE001 - see above
            pass
        op.drop_column(EMS, BILLED_THROUGH, schema=SCHEMA)
