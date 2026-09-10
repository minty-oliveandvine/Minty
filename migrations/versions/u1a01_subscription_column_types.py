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
WHY DROP AND CREATE RATHER THAN ALTER

The subscription data is test data and is being discarded by decision, so this
recreates the tables empty instead of converting rows in place. Two facts make
that safe, and both were checked rather than assumed:

  * NO foreign key from outside these 13 tables points into them, so the drops
    cascade nothing. The only inbound references are between the 13 themselves.
  * Every value in every converting column IS castable, so the ALTER route would
    also have worked - it is simply much longer for data nobody wants.

The tables come back with their live shape otherwise: the same columns in the
same order, the same nullability and server defaults, the same foreign keys with
the same ON DELETE behaviour, and the same indexes.

-----------------------------------------------------------------------------
TWO UNIQUE INDEXES THAT MUST SURVIVE THE RECREATE

Both are declared in the models as ``Index(..., unique=True)`` rather than
``UniqueConstraint``, which makes them easy to miss when comparing schemas at the
constraint level - and the redesign schema DID miss them, declaring
``idempotency_key`` with no index at all and the open-transfer index as a plain
one. Neither is a lookup aid:

  uq_subscription_invoice_idempotency_key
      the double-charge guard. ``billing_gateway`` claims the key BEFORE the
      charge and relies on the database to refuse a duplicate.

  uq_subscription_transfer_open
      one open transfer offer per entity. Without the uniqueness two live claims
      on one entity are possible.

They are recreated here as UNIQUE, and ``01_schema_rebased.sql`` is corrected to
match separately.

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
POSTGRES ONLY

Enums, uuid and partial indexes are all Postgres-shaped. On any other dialect this
revision prints and returns without changing anything. The test suite builds its
schema from the models with ``create_all`` rather than from alembic, so it never
reaches this code.

-----------------------------------------------------------------------------
THE DOWNGRADE

Restores the previous SHAPE - varchar ids, varchar status columns - and drops the
four types. Note it keeps BOTH unique indexes: the live schema has always had
them, and it is the redesign schema, not this database, that lost them. The
tables come back EMPTY, which is honest rather than lossy here: this revision
already discarded the rows on the way up, by decision, and there is nothing left
to restore them from.

Revision ID: u1a01_subscription_types
Revises: z1a01_drop_payer_cycle
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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

# Drop order: children before parents. Only two references run between these
# tables - invoice_line -> invoice and nomination -> group - so everything else
# is free.
DROP_ORDER = [
    INVOICE_LINE, INVOICE, NOMINATION, GROUP, CONSENT, MODULE, CUSTOMER,
    TRANSFER, AUDIT, EMAIL, TERMS, PLAN, POLICY,
]

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

OPEN_STATUSES = ("pending", "charging", "charged")
STRANDED_STATUSES = ("charging", "charged")

UQ_INVOICE_IDEMPOTENCY = "uq_subscription_invoice_idempotency_key"
UQ_TRANSFER_OPEN = "uq_subscription_transfer_open"

# The billing_plan rows the application looks up by CODE - nothing references the
# id, so fresh uuids here cost nothing. Amounts are minor units.
PLAN_SEED = [
    ("BILL", "Payment Request", 28000),
    ("PETTY_CASH", "Petty Cash", 28000),
    ("BILL+PETTY_CASH", "Super Minty", 40000),
]


def _uuid():
    """The id type. as_uuid=False so values stay Python strings.

    This is what keeps the application change a type-only edit: every
    ``str(uuid.uuid4())`` default, every ``str(x)`` coercion at a query boundary,
    and - most importantly - every interpolated idempotency key such as
    ``f"transfer-{offer.id}-{n}"`` keeps producing byte-identical text. Under
    as_uuid=True those keys change and a retry stops matching what was already
    claimed. Matches the existing precedent at entity/models/currency_info.py:18.
    """
    return postgresql.UUID(as_uuid=False)


def _enum(name):
    """Bind to the type this revision creates; never try to create it inline."""
    return postgresql.ENUM(
        *ENUM_TYPES[name], name=name, schema=SCHEMA, create_type=False
    )


def _ts():
    return sa.TIMESTAMP(timezone=True)


def _now():
    return sa.func.now()


def _has_table(bind, table) -> bool:
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def _already_converted(bind) -> bool:
    """True once the ids are uuid, so a re-run is a no-op rather than a wipe.

    This revision is destructive by design, so "idempotent" cannot mean "run the
    drops again" - that would discard rows written since the first run. It means
    "notice the work is done and stop".
    """
    if not _has_table(bind, TRANSFER):
        return False
    for column in sa.inspect(bind).get_columns(TRANSFER, schema=SCHEMA):
        if column["name"] == "id":
            return type(column["type"]).__name__.upper() == "UUID"
    return False


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


# --- 2. the tables --------------------------------------------------------------


def _drop_tables():
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table} CASCADE")


def _create_plan():
    op.create_table(
        PLAN,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("interval_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_billing_plan_currency",
        ),
        sa.UniqueConstraint("code", name="billing_plan_code_key"),
        schema=SCHEMA,
    )
    op.create_index("ix_billing_plan_code", PLAN, ["code"], schema=SCHEMA)


def _create_policy():
    op.create_table(
        POLICY,
        # Integer, not uuid: a singleton row pinned to id = 1.
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("trial_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "paid_cancel_access_days", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column(
            "past_due_window_days", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column(
            "retry_offsets_days", sa.String(100), nullable=False,
            # The live DEFAULT is the stale four-retry schedule while the live ROW
            # holds 1..13; the row is what the code agrees with, so the default is
            # brought into line with it here.
            server_default="1,2,3,4,5,6,7,8,9,10,11,12,13",
        ),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_billing_policy_singleton"),
        sa.CheckConstraint("trial_days >= 0", name="ck_billing_policy_trial_days"),
        sa.CheckConstraint(
            "paid_cancel_access_days >= 0", name="ck_billing_policy_cancel_days"
        ),
        sa.CheckConstraint(
            "past_due_window_days >= 3", name="ck_billing_policy_past_due_window"
        ),
        sa.CheckConstraint(
            "retry_offsets_days ~ '^[0-9]+(,[0-9]+)*$'",
            name="ck_billing_policy_retry_offsets_format",
        ),
        schema=SCHEMA,
    )


def _create_group():
    op.create_table(
        GROUP,
        sa.Column("id", _uuid(), primary_key=True),
        # OUTWARD -> user.id, stays varchar(36). See the docstring.
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=False),
        sa.Column("paid_through", _ts(), nullable=True),
        sa.Column("dunning_started_at", _ts(), nullable=True),
        sa.Column("dunning_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="fk_payer_billing_group_user",
        ),
        sa.UniqueConstraint(
            "payer_user_id", "stripe_payment_method_id",
            name="uq_payer_billing_group_payer_card",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_payer_billing_group_payer", GROUP, ["payer_user_id"], schema=SCHEMA)
    op.create_index(
        "ix_payer_billing_group_dunning", GROUP, ["dunning_started_at"], schema=SCHEMA,
        postgresql_where=sa.text("dunning_started_at IS NOT NULL"),
    )


def _create_nomination():
    op.create_table(
        NOMINATION,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),      # OUTWARD
        sa.Column("payer_user_id", sa.String(36), nullable=False),  # OUTWARD
        # INTERNAL -> payer_billing_group.id, so it converts with it.
        sa.Column("billing_group_id", _uuid(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="fk_entity_billing_group_entity", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"], name="fk_entity_billing_group_user"
        ),
        sa.ForeignKeyConstraint(
            ["billing_group_id"], [f"{SCHEMA}.{GROUP}.id"],
            name="fk_entity_billing_group_group",
        ),
        sa.UniqueConstraint(
            "entity_id", "payer_user_id", name="uq_entity_billing_group_entity_payer"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_entity_billing_group_entity", NOMINATION, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_entity_billing_group_payer", NOMINATION, ["payer_user_id"], schema=SCHEMA)
    op.create_index("ix_entity_billing_group_group", NOMINATION, ["billing_group_id"], schema=SCHEMA)


def _create_consent():
    op.create_table(
        CONSENT,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("user_id", sa.String(36), nullable=False),    # OUTWARD
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="entity_billing_consent_entity_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="entity_billing_consent_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id", "user_id", name="uq_entity_billing_consent_entity_user"
        ),
        schema=SCHEMA,
    )


def _create_module():
    op.create_table(
        MODULE,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),      # OUTWARD
        sa.Column("function_code", sa.String(100), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("phase", _enum(T_PHASE), nullable=False),
        sa.Column("app_access_until", _ts(), nullable=True),
        sa.Column("trial_end", _ts(), nullable=True),
        sa.Column("first_billed_at", _ts(), nullable=True),
        sa.Column("extension_amount", sa.Integer(), nullable=True),
        sa.Column("extension_state", _enum(T_EXTENSION), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("billed_through", _ts(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="entity_module_subscription_entity_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="entity_module_subscription_payer_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id", "function_code",
            name="uq_entity_module_subscription_entity_code",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_entity_module_subscription_entity_id", MODULE, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_function_code", MODULE, ["function_code"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_payer_user_id", MODULE, ["payer_user_id"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_trial_end", MODULE, ["trial_end"], schema=SCHEMA)
    op.create_index(
        "ix_ems_billed_through", MODULE, ["billed_through"], schema=SCHEMA,
        postgresql_where=sa.text("billed_through IS NOT NULL"),
    )


def _create_customer():
    op.create_table(
        CUSTOMER,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("anchor_at", _ts(), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="user_stripe_customer_user_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_user_stripe_customer_currency",
        ),
        sa.UniqueConstraint("user_id", name="user_stripe_customer_user_id_key"),
        sa.UniqueConstraint(
            "stripe_customer_id", name="user_stripe_customer_stripe_customer_id_key"
        ),
        schema=SCHEMA,
    )


def _create_invoice():
    op.create_table(
        INVOICE,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("payer_user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("period_start", _ts(), nullable=False),
        sa.Column("period_end", _ts(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        # Stripe's vocabulary, not ours - stays varchar. An enum over someone
        # else's value set fails closed the day they add a value.
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("issued_at", _ts(), nullable=True),
        sa.Column("paid_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("payment_method", sa.String(100), nullable=True),
        sa.Column("hosted_invoice_url", sa.String(500), nullable=True),
        # INTERNAL -> payer_billing_group.id. Carries no FK in the live schema and
        # gains none here; only the type changes.
        sa.Column("billing_group_id", _uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_subscription_invoice_currency",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_invoice_external_id", INVOICE, ["external_id"], schema=SCHEMA)
    op.create_index(
        "ix_subscription_invoice_payer", INVOICE, ["payer_user_id", "period_start"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_invoice_group", INVOICE, ["billing_group_id", "period_start"],
        schema=SCHEMA, postgresql_where=sa.text("billing_group_id IS NOT NULL"),
    )
    # THE DOUBLE-CHARGE GUARD. Unique, deliberately - see the docstring.
    op.create_index(
        UQ_INVOICE_IDEMPOTENCY, INVOICE, ["idempotency_key"], unique=True, schema=SCHEMA
    )


def _create_invoice_line():
    op.create_table(
        INVOICE_LINE,
        sa.Column("id", _uuid(), primary_key=True),
        # INTERNAL -> subscription_invoice.id.
        sa.Column("invoice_id", _uuid(), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("entity_name", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="full"),
        sa.Column("at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["invoice_id"], [f"{SCHEMA}.{INVOICE}.id"],
            name="subscription_invoice_line_invoice_id_fkey", ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_invoice_line_invoice_id", INVOICE_LINE, ["invoice_id"], schema=SCHEMA)
    op.create_index("ix_subscription_invoice_line_entity_id", INVOICE_LINE, ["entity_id"], schema=SCHEMA)


def _create_transfer():
    op.create_table(
        TRANSFER,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),     # OUTWARD
        sa.Column("from_user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("to_user_id", sa.String(36), nullable=False),    # OUTWARD
        sa.Column("status", _enum(T_TRANSFER), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("expires_at", _ts(), nullable=False),
        sa.Column("responded_at", _ts(), nullable=True),
        sa.Column("accepted_billed_through", _ts(), nullable=True),
        sa.Column("accepted_anchor_at", _ts(), nullable=True),
        sa.Column("quoted_amount", sa.Integer(), nullable=True),
        # CHAR(3), matching every other currency column in the schema.
        sa.Column("quoted_currency", sa.CHAR(3), nullable=True),
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
    op.create_index(
        "ix_subscription_transfer_entity", TRANSFER, ["entity_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_transfer_to_user", TRANSFER, ["to_user_id", "status"],
        schema=SCHEMA,
    )
    # Both predicates now compare against the enum, so the literals are cast.
    op.create_index(
        "ix_subscription_transfer_stranded", TRANSFER, ["status"], schema=SCHEMA,
        postgresql_where=sa.text(_status_in(STRANDED_STATUSES)),
    )
    # ONE OPEN OFFER PER ENTITY. Unique, deliberately - see the docstring.
    op.create_index(
        UQ_TRANSFER_OPEN, TRANSFER, ["entity_id"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text(_status_in(OPEN_STATUSES)),
    )


def _status_in(statuses) -> str:
    values = ", ".join(f"'{s}'::{SCHEMA}.{T_TRANSFER}" for s in statuses)
    return f"status IN ({values})"


def _create_audit():
    op.create_table(
        AUDIT,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),      # OUTWARD
        sa.Column("function_code", sa.String(100), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("actor_user_id", sa.String(36), nullable=True),   # OUTWARD
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("phase_before", _enum(T_PHASE), nullable=True),
        sa.Column("phase_after", _enum(T_PHASE), nullable=True),
        sa.Column("app_access_until", _ts(), nullable=True),
        sa.Column("extension_amount", sa.Integer(), nullable=True),
        sa.Column("extension_state", _enum(T_EXTENSION), nullable=True),
        sa.Column("outcome", _enum(T_OUTCOME), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        # OUTWARD, and carrying no foreign key here or in the live schema - this is
        # history, and a payer who leaves must not erase the record of having paid.
        sa.Column("payer_before", sa.String(36), nullable=True),
        sa.Column("payer_after", sa.String(36), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_audit_log_entity_id", AUDIT, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_subscription_audit_log_created_at", AUDIT, ["created_at"], schema=SCHEMA)
    op.create_index(
        "ix_sub_audit_payer_after", AUDIT, ["payer_after", "created_at"], schema=SCHEMA,
        postgresql_where=sa.text("payer_after IS NOT NULL"),
    )


def _create_email():
    op.create_table(
        EMAIL,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("recipient", sa.String(200), nullable=True),
        # Ours, but only two values and no enum in the live schema either. Left as
        # varchar so this revision changes exactly what it set out to change.
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="subscription_email_log_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("event", "dedupe_key", name="uq_sub_email_event_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sub_email_user_created", EMAIL, ["user_id", "created_at"], schema=SCHEMA
    )


def _create_terms():
    op.create_table(
        TERMS,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),  # OUTWARD
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("accepted_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="fk_terms_consent_user", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "terms_version", name="uq_terms_consent_user_version"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_terms_consent_user", TERMS, ["user_id"], schema=SCHEMA)


def _upgrade_tables(bind):
    if _already_converted(bind):
        print(f"{SCHEMA}.{TRANSFER}.id is already uuid - skipping the recreate.")
        return
    _drop_tables()
    # Parents before children: payer_billing_group before the nominations that
    # point at it, subscription_invoice before its lines.
    _create_plan()
    _create_policy()
    _create_group()
    _create_nomination()
    _create_consent()
    _create_module()
    _create_customer()
    _create_invoice()
    _create_invoice_line()
    _create_transfer()
    _create_audit()
    _create_email()
    _create_terms()
    print(f"Recreated {len(DROP_ORDER)} subscription tables with uuid and enum types.")


# --- 3. the reference rows ------------------------------------------------------


def _upgrade_seed(bind):
    """billing_plan and billing_policy are reference data, not user data.

    Everything else comes back empty by decision; these two are what the
    application reads to answer "what does a module cost" and "how long is a
    trial", so a database without them is not merely empty, it is broken.
    """
    for code, name, amount in PLAN_SEED:
        bind.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.{PLAN} "
                "(id, code, display_name, amount, currency, interval_months, is_active) "
                "VALUES (gen_random_uuid(), :code, :name, :amount, 'HKD', 1, true)"
            ),
            {"code": code, "name": name, "amount": amount},
        )
    bind.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.{POLICY} "
            "(id, trial_days, paid_cancel_access_days, past_due_window_days, "
            " retry_offsets_days, updated_by) "
            "VALUES (1, 30, 30, 15, '1,2,3,4,5,6,7,8,9,10,11,12,13', :who)"
        ),
        {"who": f"migration {revision}"},
    )
    print(f"Seeded {len(PLAN_SEED)} billing_plan rows and the billing_policy singleton.")


# --- the revision ---------------------------------------------------------------


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        print(f"{bind.dialect.name} is not postgresql - skipping {revision}.")
        return
    already = _already_converted(bind)
    # Each part is individually idempotent, in the house style. Here that means
    # noticing the conversion has already happened rather than repeating it: the
    # recreate discards rows, so a blind re-run would be destructive.
    _upgrade_enum_types(bind)
    _upgrade_tables(bind)
    if not already:
        _upgrade_seed(bind)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        print(f"{bind.dialect.name} is not postgresql - skipping {revision} downgrade.")
        return

    # The rows are already gone - the upgrade discarded them by decision, and the
    # downgrade cannot invent them. It restores the SHAPE so an older build boots.
    print(
        "WARNING: downgrade restores the varchar columns, with EMPTY tables. The "
        "subscription rows were discarded on the way up, by decision."
    )
    _drop_tables()

    op.create_table(
        PLAN,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("interval_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_billing_plan_currency",
        ),
        sa.UniqueConstraint("code", name="billing_plan_code_key"),
        schema=SCHEMA,
    )
    op.create_index("ix_billing_plan_code", PLAN, ["code"], schema=SCHEMA)

    _create_policy()  # integer PK, unchanged by this revision either way

    op.create_table(
        GROUP,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("stripe_payment_method_id", sa.String(255), nullable=False),
        sa.Column("paid_through", _ts(), nullable=True),
        sa.Column("dunning_started_at", _ts(), nullable=True),
        sa.Column("dunning_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="fk_payer_billing_group_user",
        ),
        sa.UniqueConstraint(
            "payer_user_id", "stripe_payment_method_id",
            name="uq_payer_billing_group_payer_card",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_payer_billing_group_payer", GROUP, ["payer_user_id"], schema=SCHEMA)
    op.create_index(
        "ix_payer_billing_group_dunning", GROUP, ["dunning_started_at"], schema=SCHEMA,
        postgresql_where=sa.text("dunning_started_at IS NOT NULL"),
    )

    op.create_table(
        NOMINATION,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("billing_group_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="fk_entity_billing_group_entity", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"], name="fk_entity_billing_group_user"
        ),
        sa.ForeignKeyConstraint(
            ["billing_group_id"], [f"{SCHEMA}.{GROUP}.id"],
            name="fk_entity_billing_group_group",
        ),
        sa.UniqueConstraint(
            "entity_id", "payer_user_id", name="uq_entity_billing_group_entity_payer"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_entity_billing_group_entity", NOMINATION, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_entity_billing_group_payer", NOMINATION, ["payer_user_id"], schema=SCHEMA)
    op.create_index("ix_entity_billing_group_group", NOMINATION, ["billing_group_id"], schema=SCHEMA)

    op.create_table(
        CONSENT,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="entity_billing_consent_entity_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="entity_billing_consent_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id", "user_id", name="uq_entity_billing_consent_entity_user"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        MODULE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("function_code", sa.String(100), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("app_access_until", _ts(), nullable=True),
        sa.Column("trial_end", _ts(), nullable=True),
        sa.Column("first_billed_at", _ts(), nullable=True),
        sa.Column("extension_amount", sa.Integer(), nullable=True),
        sa.Column("extension_state", sa.String(20), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("billed_through", _ts(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{SCHEMA}.entities.id"],
            name="entity_module_subscription_entity_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], [f"{SCHEMA}.user.id"],
            name="entity_module_subscription_payer_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id", "function_code",
            name="uq_entity_module_subscription_entity_code",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_entity_module_subscription_entity_id", MODULE, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_function_code", MODULE, ["function_code"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_payer_user_id", MODULE, ["payer_user_id"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_trial_end", MODULE, ["trial_end"], schema=SCHEMA)
    op.create_index(
        "ix_ems_billed_through", MODULE, ["billed_through"], schema=SCHEMA,
        postgresql_where=sa.text("billed_through IS NOT NULL"),
    )

    op.create_table(
        CUSTOMER,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("anchor_at", _ts(), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="user_stripe_customer_user_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_user_stripe_customer_currency",
        ),
        sa.UniqueConstraint("user_id", name="user_stripe_customer_user_id_key"),
        sa.UniqueConstraint(
            "stripe_customer_id", name="user_stripe_customer_stripe_customer_id_key"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        INVOICE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("period_start", _ts(), nullable=False),
        sa.Column("period_end", _ts(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("issued_at", _ts(), nullable=True),
        sa.Column("paid_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("payment_method", sa.String(100), nullable=True),
        sa.Column("hosted_invoice_url", sa.String(500), nullable=True),
        sa.Column("billing_group_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_subscription_invoice_currency",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_invoice_external_id", INVOICE, ["external_id"], schema=SCHEMA)
    op.create_index(
        "ix_subscription_invoice_payer", INVOICE, ["payer_user_id", "period_start"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_invoice_group", INVOICE, ["billing_group_id", "period_start"],
        schema=SCHEMA, postgresql_where=sa.text("billing_group_id IS NOT NULL"),
    )
    op.create_index(
        UQ_INVOICE_IDEMPOTENCY, INVOICE, ["idempotency_key"], unique=True, schema=SCHEMA
    )

    op.create_table(
        INVOICE_LINE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("entity_name", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="full"),
        sa.Column("at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["invoice_id"], [f"{SCHEMA}.{INVOICE}.id"],
            name="subscription_invoice_line_invoice_id_fkey", ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_invoice_line_invoice_id", INVOICE_LINE, ["invoice_id"], schema=SCHEMA)
    op.create_index("ix_subscription_invoice_line_entity_id", INVOICE_LINE, ["entity_id"], schema=SCHEMA)

    op.create_table(
        TRANSFER,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("from_user_id", sa.String(36), nullable=False),
        sa.Column("to_user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("expires_at", _ts(), nullable=False),
        sa.Column("responded_at", _ts(), nullable=True),
        sa.Column("accepted_billed_through", _ts(), nullable=True),
        sa.Column("accepted_anchor_at", _ts(), nullable=True),
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
    _open = ", ".join(f"'{s}'" for s in OPEN_STATUSES)
    _stranded = ", ".join(f"'{s}'" for s in STRANDED_STATUSES)
    op.create_index(
        "ix_subscription_transfer_entity", TRANSFER, ["entity_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_transfer_to_user", TRANSFER, ["to_user_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscription_transfer_stranded", TRANSFER, ["status"], schema=SCHEMA,
        postgresql_where=sa.text(f"status IN ({_stranded})"),
    )
    op.create_index(
        UQ_TRANSFER_OPEN, TRANSFER, ["entity_id"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text(f"status IN ({_open})"),
    )

    op.create_table(
        AUDIT,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("function_code", sa.String(100), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("phase_before", sa.String(30), nullable=True),
        sa.Column("phase_after", sa.String(30), nullable=True),
        sa.Column("app_access_until", _ts(), nullable=True),
        sa.Column("extension_amount", sa.Integer(), nullable=True),
        sa.Column("extension_state", sa.String(20), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("payer_before", sa.String(36), nullable=True),
        sa.Column("payer_after", sa.String(36), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_audit_log_entity_id", AUDIT, ["entity_id"], schema=SCHEMA)
    op.create_index("ix_subscription_audit_log_created_at", AUDIT, ["created_at"], schema=SCHEMA)
    op.create_index(
        "ix_sub_audit_payer_after", AUDIT, ["payer_after", "created_at"], schema=SCHEMA,
        postgresql_where=sa.text("payer_after IS NOT NULL"),
    )

    op.create_table(
        EMAIL,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("recipient", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", _ts(), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="subscription_email_log_user_id_fkey", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("event", "dedupe_key", name="uq_sub_email_event_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sub_email_user_created", EMAIL, ["user_id", "created_at"], schema=SCHEMA
    )

    op.create_table(
        TERMS,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("accepted_at", _ts(), nullable=False, server_default=_now()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"],
            name="fk_terms_consent_user", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "terms_version", name="uq_terms_consent_user_version"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_terms_consent_user", TERMS, ["user_id"], schema=SCHEMA)

    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.{name}")
