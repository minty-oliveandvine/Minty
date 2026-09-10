"""Give the subscription tables their real column types: uuid, and four enums.

WHAT THIS IS

The 13 subscription/billing tables were compared column by column against the
schema the redesign targets (``docs/schema/01_schema_rebased.sql``, section K).
They already agree on everything that is hard to change: 13/13 tables, 132/132
columns, every column name matching, zero nullability differences, and every
value already valid for the enum it is destined for. The entire remaining gap is
types - ids declared ``varchar(36)`` that are uuids, and status columns declared
``varchar`` that are closed vocabularies this application owns.

This closes the part of that gap which can be closed without touching the rest of
the schema.

-----------------------------------------------------------------------------
15 OF 35 ID COLUMNS, AND WHY NOT THE OTHER 20

PostgreSQL cannot build a foreign key from a ``uuid`` column to a ``varchar`` one:
there is no equality operator between the types, and ``ADD CONSTRAINT`` fails
outright. ``pettycashv2.user.id`` and ``pettycashv2.entities.id`` are both still
``varchar(36)``, so every column pointing at them has to stay ``varchar(36)`` too.

    converted, 15    the 12 own primary keys, plus the three foreign keys that
                     stay inside this set - subscription_invoice_line.invoice_id,
                     entity_billing_group.billing_group_id and
                     subscription_invoice.billing_group_id

    left alone, 20   12 columns referencing user.id, 6 referencing entities.id,
                     and subscription_audit_log.payer_before / payer_after, which
                     carry no foreign key today but sit beside payer_user_id and
                     would be strange as a different type from it

THAT BOUNDARY IS DELIBERATE AND IS NOT A HALF-FINISHED JOB. Converting the other
20 means converting ``user.id`` and ``entities.id``, which reaches every table in
the database that references them, and is separately blocked today by one row:
a user whose id is the literal four-character text 'NULL'. Anyone extending this
revision to "finish" the outward columns will hit the foreign-key wall on the
first ADD CONSTRAINT.

-----------------------------------------------------------------------------
WHY ALTER IN PLACE, AND NOT DROP AND CREATE

An earlier draft of this revision recreated the 13 tables empty, on the reasoning
that the subscription rows were test data being discarded anyway. That reasoning
held for one database and not for the others. Measured on Supabase on 2026-09-10,
the same 13 tables hold 48 rows that are not test data: an account paid through
2026-09-12 with its Stripe customer and payment-method ids, three paid invoices
and two deliberately voided ones, 13 live trials, and six terms_consent rows,
which are a legal record of who accepted what and when. A revision that empties
those is not a type change, it is a data loss with a type change attached.

So the conversion is done with ALTER, which keeps every row. That route was
checked rather than assumed, on both databases:

  * every value in all 15 converting id columns is already a well-formed uuid -
    zero exceptions, so ``USING id::uuid`` cannot fail
  * every value in all 7 converting status columns is already inside the label
    set of the enum it is moving to
  * none of the converting columns carries a DEFAULT or a CHECK constraint, so
    nothing has to be dropped and restored around the type change
  * nothing outside these tables depends on them: no views, no publications, no
    row-level-security policies, no grants beyond the owner, and the only two
    inbound foreign keys run between the tables themselves

Each column is converted only if it is not already converted, so a re-run is a
no-op rather than a second rewrite, and the two seeded reference tables are
filled with ON CONFLICT DO NOTHING rather than a blind INSERT.

-----------------------------------------------------------------------------
THE TWO FOREIGN KEYS AND THE TWO INDEXES THAT COME APART FIRST

``ALTER COLUMN ... TYPE`` rebuilds the indexes over a column by itself, and both
sides of a foreign key have to move together, so exactly four objects are dropped
before the conversion and rebuilt after it:

  subscription_invoice_line_invoice_id_fkey, fk_entity_billing_group_group
      the only two foreign keys inside this set. Postgres will not hold a key
      whose sides disagree on type, even for the length of one statement.

  uq_subscription_transfer_open, ix_subscription_transfer_stranded
      both are PARTIAL, and their predicates name the status values. Postgres
      cannot re-derive ``status = 'pending'::varchar`` once status is an enum,
      so the predicates are rewritten against the enum type here.

``uq_subscription_invoice_idempotency_key`` - the double-charge guard, which
``billing_gateway`` claims BEFORE the charge and relies on the database to refuse
a duplicate - is NOT one of them. Its column does not convert and its index is
never dropped. It is named here only because the redesign schema declared
``idempotency_key`` with no index at all, and that is corrected separately.

-----------------------------------------------------------------------------
THE FOUR ENUM TYPES, AND THE THREE LABELS WITH NO CONSTANT

These are the first Postgres enum types in this migration tree. Values come from
``blueprints/subscription/constants.py``, which is the application's single source
for these vocabularies - except for ``extension_state``, which needs three labels
that constants.py does NOT declare:

    deleted, credited, refunded

They are terminal outcomes written by the retired Stripe invoice-item path
(see the comment at entity_module_subscription.py:100-107). Leaving them out does
NOT fail a write - SQLAlchemy raises LookupError when READING a value outside the
label set, so the omission would surface later, on some unrelated read, far from
the cause. An enum has to cover what the code can produce, not what today's rows
happen to hold.

-----------------------------------------------------------------------------
ONE THING THAT IS NOT A TYPE

``billing_policy.retry_offsets_days`` has carried the stale four-retry DEFAULT
'1,4,7,10,13' while its single live ROW holds the daily 1..13 schedule the code
agrees with. The default is brought into line with the row here, because this is
the revision that reworks this table's declaration either way.

-----------------------------------------------------------------------------
POSTGRES ONLY

Enums, uuid and partial indexes are all Postgres-shaped. On any other dialect this
revision prints and returns without changing anything. The test suite builds its
schema from the models with ``create_all`` rather than from alembic, so it never
reaches this code.

-----------------------------------------------------------------------------
THE DOWNGRADE

Converts back - varchar ids, varchar status columns, the old default - and drops
the four types. It keeps the rows, exactly as the upgrade does, and rebuilds the
same four objects on the way back with text predicates.

Revision ID: u1a01_subscription_types
Revises: z1a01_drop_payer_cycle
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op

revision = "u1a01_subscription_types"
down_revision = "z1a01_drop_payer_cycle"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

PLAN = "billing_plan"
POLICY = "billing_policy"
GROUP = "payer_billing_group"
NOMINATION = "entity_billing_group"
CONSENT = "entity_billing_consent"
MODULE = "entity_module_subscription"
CUSTOMER = "user_stripe_customer"
INVOICE = "subscription_invoice"
INVOICE_LINE = "subscription_invoice_line"
TRANSFER = "subscription_transfer"
AUDIT = "subscription_audit_log"
EMAIL = "subscription_email_log"
TERMS = "terms_consent"

T_PHASE = "subscription_phase"
T_EXTENSION = "extension_state"
T_TRANSFER = "transfer_status"
T_OUTCOME = "audit_outcome"

PHASES = ("trial", "active", "past_due", "scheduled_cancel", "cancelled", "expired")
# pending / invoiced have constants; the other three are the retired invoice-item
# path's terminal outcomes. See the docstring - omitting them breaks READS.
EXTENSION_STATES = ("pending", "invoiced", "deleted", "credited", "refunded")
TRANSFER_STATUSES = (
    "pending", "charging", "charged", "accepted", "declined", "cancelled", "expired",
)
OUTCOMES = ("succeeded", "aborted")

ENUM_TYPES = {
    T_PHASE: PHASES,
    T_EXTENSION: EXTENSION_STATES,
    T_TRANSFER: TRANSFER_STATUSES,
    T_OUTCOME: OUTCOMES,
}

#: The 12 own primary keys, then the 3 foreign keys that stay inside this set.
#: Everything else stays varchar(36) - see the docstring.
UUID_COLUMNS = (
    (PLAN, "id"),
    (GROUP, "id"),
    (NOMINATION, "id"),
    (NOMINATION, "billing_group_id"),
    (CONSENT, "id"),
    (MODULE, "id"),
    (CUSTOMER, "id"),
    (INVOICE, "id"),
    (INVOICE, "billing_group_id"),
    (INVOICE_LINE, "id"),
    (INVOICE_LINE, "invoice_id"),
    (TRANSFER, "id"),
    (AUDIT, "id"),
    (EMAIL, "id"),
    (TERMS, "id"),
)

#: table, column, enum type, and the varchar width to return to on the way down.
ENUM_COLUMNS = (
    (MODULE, "phase", T_PHASE, 30),
    (MODULE, "extension_state", T_EXTENSION, 20),
    (AUDIT, "phase_before", T_PHASE, 30),
    (AUDIT, "phase_after", T_PHASE, 30),
    (AUDIT, "extension_state", T_EXTENSION, 20),
    (AUDIT, "outcome", T_OUTCOME, 20),
    (TRANSFER, "status", T_TRANSFER, 20),
)

#: child table, constraint, column, parent table, tail. The only two foreign keys
#: inside this set, and the reason the sides have to move together.
INNER_FKS = (
    (INVOICE_LINE, "subscription_invoice_line_invoice_id_fkey", "invoice_id",
     INVOICE, " ON DELETE CASCADE"),
    (NOMINATION, "fk_entity_billing_group_group", "billing_group_id", GROUP, ""),
)

OPEN_STATUSES = ("pending", "charging", "charged")
STRANDED_STATUSES = ("charging", "charged")

UQ_TRANSFER_OPEN = "uq_subscription_transfer_open"
IX_TRANSFER_STRANDED = "ix_subscription_transfer_stranded"

RETRY_OFFSETS_NEW = "1,2,3,4,5,6,7,8,9,10,11,12,13"
RETRY_OFFSETS_OLD = "1,4,7,10,13"

# The billing_plan rows the application looks up by CODE - nothing references the
# id, so fresh uuids here cost nothing. Amounts are minor units.
PLAN_SEED = [
    ("BILL", "Payment Request", 28000),
    ("PETTY_CASH", "Petty Cash", 28000),
    ("BILL+PETTY_CASH", "Super Minty", 40000),
]


# --- reading the catalog --------------------------------------------------------


def _udt(bind, table, column):
    """The column's underlying type name: 'varchar', 'uuid', or an enum's name.

    None when the column is absent, which is what makes every step below safe to
    run against a database that is already part-way there.
    """
    return bind.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table "
            "AND column_name = :column"
        ),
        {"schema": SCHEMA, "table": table, "column": column},
    ).scalar()


def _has_constraint(bind, table, name) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema AND t.relname = :table "
                "AND c.conname = :name"
            ),
            {"schema": SCHEMA, "table": table, "name": name},
        ).scalar()
    )


def _pending(bind):
    """What is left to convert, column by column.

    Per column rather than one flag, so a database in any partial state finishes
    correctly and a converted one does nothing at all.
    """
    ids = [(t, c) for t, c in UUID_COLUMNS if _udt(bind, t, c) not in (None, "uuid")]
    enums = [
        (t, c, type_name)
        for t, c, type_name, _ in ENUM_COLUMNS
        if _udt(bind, t, c) not in (None, type_name)
    ]
    currency = _udt(bind, TRANSFER, "quoted_currency") == "varchar"
    return ids, enums, currency


def _pending_down(bind):
    """The mirror of _pending: what is left to convert BACK."""
    ids = [(t, c) for t, c in UUID_COLUMNS if _udt(bind, t, c) == "uuid"]
    enums = [
        (t, c, width)
        for t, c, type_name, width in ENUM_COLUMNS
        if _udt(bind, t, c) == type_name
    ]
    currency = _udt(bind, TRANSFER, "quoted_currency") == "bpchar"
    return ids, enums, currency


# --- 1. the enum types ----------------------------------------------------------


def _upgrade_enum_types(bind):
    existing = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT t.typname FROM pg_type t "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE n.nspname = :schema AND t.typtype = 'e'"
            ),
            {"schema": SCHEMA},
        )
    }
    for name, labels in ENUM_TYPES.items():
        if name in existing:
            print(f"{SCHEMA}.{name} already exists - skipping.")
            continue
        values = ", ".join(f"'{v}'" for v in labels)
        op.execute(f"CREATE TYPE {SCHEMA}.{name} AS ENUM ({values})")
        print(f"Created type {SCHEMA}.{name} ({len(labels)} labels).")


# --- 2. the four objects that come apart around the conversion ------------------


def _status_in(statuses, as_enum) -> str:
    """The index predicates. The literals are cast once status IS an enum."""
    if as_enum:
        values = ", ".join(f"'{s}'::{SCHEMA}.{T_TRANSFER}" for s in statuses)
    else:
        values = ", ".join(f"'{s}'" for s in statuses)
    return f"status IN ({values})"


def _drop_status_indexes():
    for name in (UQ_TRANSFER_OPEN, IX_TRANSFER_STRANDED):
        op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{name}")


def _create_status_indexes(bind):
    """Rebuild both partial indexes against whatever type status now has."""
    as_enum = _udt(bind, TRANSFER, "status") == T_TRANSFER
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {UQ_TRANSFER_OPEN} "
        f"ON {SCHEMA}.{TRANSFER} (entity_id) "
        f"WHERE {_status_in(OPEN_STATUSES, as_enum)}"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {IX_TRANSFER_STRANDED} "
        f"ON {SCHEMA}.{TRANSFER} (status) "
        f"WHERE {_status_in(STRANDED_STATUSES, as_enum)}"
    )


def _drop_inner_fks():
    for table, name, _column, _parent, _tail in INNER_FKS:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT IF EXISTS {name}")


def _create_inner_fks(bind):
    for table, name, column, parent, tail in INNER_FKS:
        if _has_constraint(bind, table, name):
            continue
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES {SCHEMA}.{parent}(id){tail}"
        )


# --- 3. the columns -------------------------------------------------------------


def _upgrade_columns(bind):
    ids, enums, currency = _pending(bind)
    if not (ids or enums or currency):
        print("Columns are already uuid and enum - nothing to convert.")
        return

    _drop_status_indexes()
    _drop_inner_fks()

    for table, column in ids:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {column} "
            f"TYPE uuid USING {column}::uuid"
        )
    for table, column, type_name in enums:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {column} "
            f"TYPE {SCHEMA}.{type_name} USING {column}::text::{SCHEMA}.{type_name}"
        )
    if currency:
        # CHAR(3), matching every other currency column in the schema.
        op.execute(
            f"ALTER TABLE {SCHEMA}.{TRANSFER} "
            "ALTER COLUMN quoted_currency TYPE CHAR(3)"
        )

    _create_inner_fks(bind)
    _create_status_indexes(bind)
    print(
        f"Converted {len(ids)} id column(s) to uuid and {len(enums)} status "
        "column(s) to enums, rows intact."
    )


def _downgrade_columns(bind):
    ids, enums, currency = _pending_down(bind)
    if not (ids or enums or currency):
        print("Columns are already varchar - nothing to convert back.")
        return

    _drop_status_indexes()
    _drop_inner_fks()

    # Enums first: the types cannot be dropped while a column still uses one.
    for table, column, width in enums:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {column} "
            f"TYPE VARCHAR({width}) USING {column}::text"
        )
    for table, column in ids:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {column} "
            f"TYPE VARCHAR(36) USING {column}::text"
        )
    if currency:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{TRANSFER} "
            "ALTER COLUMN quoted_currency TYPE VARCHAR(3)"
        )

    _create_inner_fks(bind)
    _create_status_indexes(bind)
    print(
        f"Converted {len(ids)} id column(s) and {len(enums)} status column(s) "
        "back to varchar, rows intact."
    )


# --- 4. the two declarations that are not types ---------------------------------


def _set_retry_offsets_default(value):
    op.execute(
        f"ALTER TABLE {SCHEMA}.{POLICY} "
        f"ALTER COLUMN retry_offsets_days SET DEFAULT '{value}'"
    )


def _upgrade_seed(bind):
    """billing_plan and billing_policy are reference data, not user data.

    A database that has them keeps what it has: these are the rows the application
    reads to answer "what does a module cost" and "how long is a trial", and one
    that already answered is not improved by a second copy. ON CONFLICT rather
    than a guard, so the two cases - seeded and not - take the same path.
    """
    planted = 0
    for code, name, amount in PLAN_SEED:
        result = bind.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.{PLAN} "
                "(id, code, display_name, amount, currency, interval_months, is_active) "
                "VALUES (gen_random_uuid(), :code, :name, :amount, 'HKD', 1, true) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "amount": amount},
        )
        planted += result.rowcount or 0
    result = bind.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.{POLICY} "
            "(id, trial_days, paid_cancel_access_days, past_due_window_days, "
            " retry_offsets_days, updated_by) "
            "VALUES (1, 30, 30, 15, :offsets, :who) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"offsets": RETRY_OFFSETS_NEW, "who": f"migration {revision}"},
    )
    policy = result.rowcount or 0
    print(
        f"Seeded {planted} billing_plan row(s) and {policy} billing_policy row(s); "
        "anything already present was left as it stands."
    )


# --- the revision ---------------------------------------------------------------


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        print(f"{bind.dialect.name} is not postgresql - skipping {revision}.")
        return
    # Each part is individually idempotent, in the house style: a column converts
    # only if it is not converted, and the seed inserts only what is missing. A
    # re-run changes nothing and loses nothing.
    _upgrade_enum_types(bind)
    _upgrade_columns(bind)
    _set_retry_offsets_default(RETRY_OFFSETS_NEW)
    _upgrade_seed(bind)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        print(f"{bind.dialect.name} is not postgresql - skipping {revision} downgrade.")
        return
    _downgrade_columns(bind)
    _set_retry_offsets_default(RETRY_OFFSETS_OLD)
    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.{name}")
