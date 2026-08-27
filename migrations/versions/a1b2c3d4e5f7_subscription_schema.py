"""Subscription schema — Minty's own billing

Squashes the whole subscription feature into one migration: the billing STATE the
biller reads on every run, the append-only HISTORY (audit log + invoices) that records
what was decided, the tunable POLICY row, and the email dedupe ledger.

These were four revisions (a1b2c3d4e5f7 core, e1a3c5b7d9f2 billing_policy,
b8f3a2c1d4e5 the module seed, n1a01 the email log) while the feature was being built
against an already-stamped database. Nothing had shipped, so that reason is gone and
the schema is one revision again. The module seed stays separate on purpose — it is a
DATA migration over pre-existing tables, not part of this schema, and it has its own
idempotency story.

WHAT THIS CREATES, and why each table exists separately:

  * user_stripe_customer        the billing ACCOUNT. One per payer: the anchor date,
                                the currency, what they are paid through, and the
                                dunning schedule. A payer has one cycle however many
                                entities they pay for, so these live here and not on
                                the module rows.
  * entity_module_subscription  one row per (entity, module): lifecycle phase, the
                                app-level trial, the access window, the cancel
                                extension.
  * entity_billing_consent      per-entity authorisation to charge the payer's card.
                                A card is shared across every entity a payer owns, so
                                having one is NOT permission to bill a given entity.
  * billing_plan                the price catalog, keyed by the SET of module codes —
                                "BILL+PETTY_CASH" is one row at the bundle price, not
                                the sum of two. The bundle IS the discount.
  * billing_policy              the five commercial levers — trial length, cancel
                                access, the past-due window, the retry schedule — as a
                                singleton row instead of Python constants.
  * subscription_audit_log      one row per cancel / uncancel: who did it, the phase
                                either side, the access window granted, the extension
                                worth. The answer to "why was I charged?" months later.
  * subscription_invoice        one row per invoice raised: payer, period, total,
    + subscription_invoice_line status, and the idempotency_key whose UNIQUE index makes
                                billing a period twice impossible rather than unlikely.
  * subscription_email_log      the dedupe ledger for billing emails. Its UNIQUE
                                (event, dedupe_key) is the whole point of the table.

STATE vs HISTORY. The account, module, consent and plan tables are billing state — the
biller reads them on every run to decide what to charge. The audit log and invoices are
history: append-only, and nothing reads them to decide what to charge. Losing the
history would be bad; it would not stop billing. That is why the history tables carry NO
foreign keys to entity/user — a record of why someone was charged must outlive the
entity or user it describes being deleted (lines DO cascade from their invoice header,
which is meaningless without it). And it is why the invoice/audit rows SNAPSHOT names
(entity_name, product_name) rather than joining: an entity renamed next year must not
silently rewrite what last year's invoice said.

Columns from the old chain that are deliberately NOT recreated. Each was written by
the app and read by nothing:

  entity_module_subscription.trial_start   start is recoverable from created_at
  entity_module_subscription.trial_used    answered by the row existing at all
  entity_module_subscription.synced_at     staleness check that was never built; its
                                           only writer had no callers
  entity_module_subscription.current_period_end
                                           written on every conversion and purchase and
                                           read by nothing. Period boundaries are
                                           re-derived from ``anchor_at`` by
                                           ``billing.period_containing``; a STORED
                                           rolling period end is the precise thing that
                                           design exists to avoid, because advancing one
                                           month by month clamps a month-end anchor
                                           permanently
  user_stripe_customer.status              looked like account state, but collection
                                           reads dunning_started_at and access reads
                                           the module row's phase

The Stripe subscription layer is not here either, and no longer exists anywhere. The
columns mirroring a Stripe subscription — and ``stripe_event``, the webhook-idempotency
table whose ``payload`` column kept full event bodies (customer emails, card metadata)
forever and was read by nothing — were added by a follow-on migration that has since
been deleted along with the biller it served.

Stripe remains the payment RAIL: ``user_stripe_customer.stripe_customer_id`` is
load-bearing and stays.

Revision ID: a1b2c3d4e5f7
Revises: r10a10_drop_legacy_report
Create Date: 2026-07-22 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
# Appended to the current head of the Minty-PettyCash line. That head keeps moving as
# the report-consolidation work lands on the base while this branch is in flight:
# s7a07_cash_method, then r6a06_repoint_draft_fks, and now r10a10_drop_legacy_report.
#
# Re-parented rather than merged so the graph stays a single line. The two chains touch
# disjoint tables — report/report_v2/shop_expense and the legacy drops there, billing and
# entity_function* here — so nothing about the billing schema depends on where in that
# order it runs. Sitting on top simply keeps one head; pointing at the OLD parent would
# fork the graph, because the newer report revisions claim it too.
#
# NOTE for any database already stamped with the subscription chain from an EARLIER
# parent: the report revisions between that parent and this one are now ANCESTORS of a
# revision it has recorded, so alembic considers them applied and will never run them.
# Such a database has to have that stretch applied by hand, or be rebuilt. The dev
# database is in exactly this position for r7a07..r10a10.
down_revision = "r10a10_drop_legacy_report"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# The catalog, seeded here rather than fetched so the migration is deterministic and
# runs with no network and no API keys. These are the prices the billing engine quotes
# from; without them ``billing_plan_for_codes`` returns None and every renewal and
# upgrade is SKIPPED rather than mispriced — safe, but nothing gets billed at all.
SEED = [
    ("BILL", "Payment Request", 28000, "HKD"),
    ("PETTY_CASH", "Petty Cash", 28000, "HKD"),
    # Not the sum of the two: the bundle is the discount.
    ("BILL+PETTY_CASH", "Super Minty", 40000, "HKD"),
]

# The policy values the code shipped with. Seeded rather than left to defaults so the
# table is never empty: an empty policy table would send every read down the fallback
# path, which works but hides a missing migration behind correct-looking behaviour.
POLICY_SEED = {
    "trial_days": 30,
    "paid_cancel_access_days": 30,
    "past_due_window_days": 15,
    "retry_offsets_days": "1,2,3,4,5,6,7,8,9,10,11,12,13",
}


def upgrade():
    # --- the billing account -------------------------------------------------
    op.create_table(
        "user_stripe_customer",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Stripe is the payment RAIL even when Minty does the billing: invoices are
        # issued against this customer. It is not the source of truth for what is owed.
        sa.Column("stripe_customer_id", sa.String(255), nullable=False, unique=True),
        # The day of the month every period starts on. Fixed at the first charge, so
        # month-end billing stays correct: 31 Jan clamps to 28 Feb and springs back to
        # 31 Mar rather than pegging the payer to the 28th forever.
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=True),
        # Fixed at the first charge — a payer's invoices must not mix currencies.
        # CHAR(3) FK into the currency registry rather than a free string: this
        # migration now runs after the registry is seeded, so the ISO code can be
        # constrained rather than merely conventional. NULL is still allowed — a payer
        # has no currency until their first charge fixes one.
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_user_stripe_customer_currency",
        ),
        # What the payer has PAID FOR, and what access is measured against. Only ever
        # moves forward, and only after money is collected.
        sa.Column("paid_through", sa.DateTime(timezone=True), nullable=True),
        # Dunning. Timed from the FIRST failure, never from the last attempt, so a
        # delayed worker cannot push the retry tail past the access grace window.
        # NULL = not in dunning.
        sa.Column("dunning_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dunning_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )

    # --- per (entity, module) -------------------------------------------------
    op.create_table(
        "entity_module_subscription",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("function_code", sa.String(100), nullable=False),
        # References ``user`` rather than ``user_stripe_customer``: a trial row exists
        # before the payer has a Stripe customer at all.
        sa.Column(
            "payer_user_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(30), nullable=False),
        # Single access-end authority, and it outranks everything: it is set when a paid
        # module is cancelled under the prorated-extension rule, and when a trial is
        # cancelled but keeps its free days.
        sa.Column("app_access_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        # Null = never charged, i.e. still a free trial. Set once, never cleared, so it
        # keeps answering "is this a PAID module?" after cancellation — which is exactly
        # when trial and paid look alike (both sit in ``scheduled_cancel``). Deliberately
        # NOT in the Stripe layer: both billers set it, and getting this wrong is how a
        # cancelled paid module ends up expired by the trial-end job.
        sa.Column("first_billed_at", sa.DateTime(timezone=True), nullable=True),
        # What the cancel-extension is WORTH, in minor units, plus where it is in its
        # lifecycle (see constants.EXTENSION_STATES). Recorded at cancellation and
        # collected by the next renewal run, so that leaving never depends on a card
        # clearing. NULL amount = nothing owed.
        sa.Column("extension_amount", sa.Integer, nullable=True),
        sa.Column("extension_state", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("entity_id", "function_code",
                            name="uq_entity_module_subscription_entity_code"),
        schema=SCHEMA,
    )
    op.create_index("ix_entity_module_subscription_entity_id",
                    "entity_module_subscription", ["entity_id"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_function_code",
                    "entity_module_subscription", ["function_code"], schema=SCHEMA)
    op.create_index("ix_entity_module_subscription_payer_user_id",
                    "entity_module_subscription", ["payer_user_id"], schema=SCHEMA)
    # The trial-end sweep scans for due trials by date; without this it is a full scan
    # of every module row every day.
    op.create_index("ix_entity_module_subscription_trial_end",
                    "entity_module_subscription", ["trial_end"], schema=SCHEMA)

    # --- per-entity consent ---------------------------------------------------
    op.create_table(
        "entity_billing_consent",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "card" (entered a card in a setup Checkout opened for this entity) or
        # "confirmed" (accepted the in-app charge against an already-saved card).
        # Kept for support: "why was I billed for this entity?"
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )

    # --- price catalog --------------------------------------------------------
    op.create_table(
        "billing_plan",
        sa.Column("id", sa.String(36), primary_key=True),
        # The sorted module SET, joined with "+": "BILL", "PETTY_CASH",
        # "BILL+PETTY_CASH". Keyed this way because the bundle is a price in its own
        # right; summing standalone prices would overcharge by the discount.
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),          # minor units
        # See user_stripe_customer.currency — same registry FK. The SEED below is
        # keyed "HKD", which the registry carries, so the constraint holds on create.
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_billing_plan_currency",
        ),
        sa.Column("interval_months", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_billing_plan_code", "billing_plan", ["code"], schema=SCHEMA)

    for code, name, amount, currency in SEED:
        op.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.billing_plan "
                "(id, code, display_name, amount, currency, interval_months, is_active) "
                "VALUES (gen_random_uuid()::text, :code, :name, :amount, :currency, 1, true)"
            ).bindparams(code=code, name=name, amount=amount, currency=currency)
        )

    # --- policy: the tunable windows ------------------------------------------
    # Five numbers decided how long a trial ran, how long access survived a failed
    # renewal, and when collection gave up. All five lived in Python, so changing a trial
    # from 30 days to 14 was a deploy. They are commercial levers, not arithmetic, and
    # the people who want to move them are not the people who cut releases.
    #
    # ONE ROW, not a key/value table. Typed columns get CHECK constraints and read as
    # documentation; a ``key TEXT, value TEXT`` table gets neither and turns every read
    # into a parse-and-hope. The singleton is enforced by ``CHECK (id = 1)`` — there is
    # one policy, and a second row would silently mean whichever one the query happened
    # to order first.
    #
    # FOUR COLUMNS, NOT FIVE. ``access.PAST_DUE_GRACE_DAYS`` (how long a past-due module
    # still grants access) and ``dunning.GIVE_UP_AFTER_DAYS`` (when collection stops)
    # were separate constants that had to be kept equal by hand. Their coherence rule is
    # ``give_up <= grace``, and the tightest correct setting is equality — a shorter
    # give-up cancels the subscription early and, because ``cancelled`` is terminal, ends
    # access BEFORE the grace window promised. One ``past_due_window_days`` collapses the
    # invariant instead of policing it.
    #
    # WHAT THE DATABASE CAN AND CANNOT ENFORCE. The per-column rules are CHECKs below.
    # The CROSS-column rules — ``max(retry_offsets) < past_due_window_days`` and the
    # two-day settle gap — are not expressible in a CHECK, because parsing the offsets
    # needs a subquery. Those are enforced by the validating loader in
    # ``subscription.services.policy``, which falls back to the in-code defaults and logs
    # loudly rather than letting an incoherent policy reach the biller. A bad edit
    # degrades to the shipped behaviour; it does not charge anyone wrongly.
    op.create_table(
        "billing_policy",
        # Singleton. Not a uuid like the other tables: there is exactly one row, and an
        # id somebody has to look up is worse than one they can type.
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),

        # Length of the card-free onboarding trial. Safe to change at any time: the trial
        # END is stamped once when the trial starts and no path moves it, so editing this
        # affects new trials only and can never shorten one already running.
        sa.Column("trial_days", sa.Integer, nullable=False, server_default="30"),

        # Access granted after an in-app cancellation, charged as a prorated extension.
        # Also safe mid-flight: it is captured into ``app_access_until`` at cancellation.
        # Unlike the others this one costs money — it feeds ``billing.extension_charge``.
        sa.Column("paid_cancel_access_days", sa.Integer, nullable=False,
                  server_default="30"),

        # The single past-due window. Access continues this many days past what was paid
        # for, AND collection gives up on the same day. See the note above on why this
        # is one column rather than two.
        sa.Column("past_due_window_days", sa.Integer, nullable=False,
                  server_default="15"),

        # Days after the FIRST failure on which each retry fires — offsets, not gaps, so
        # "1,2,3,..." is a retry every day from day 1. The LENGTH is the attempt count
        # (``dunning.MAX_ATTEMPTS``), so adding an entry adds a charge attempt. Stops at
        # 13 against a 15-day window because ``policy._dunning_pair`` rejects a schedule
        # whose last retry leaves under two days to settle.
        # CSV rather than a Postgres array: the model layer is shared with a SQLite test
        # app, and a comma-separated list of small integers needs no dialect to read.
        sa.Column("retry_offsets_days", sa.String(100), nullable=False,
                  server_default="1,2,3,4,5,6,7,8,9,10,11,12,13"),

        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # Who moved it. These are commercial levers with customer-visible effects, so
        # "why did trials become 14 days in March" needs an answer.
        sa.Column("updated_by", sa.String(255), nullable=True),

        sa.CheckConstraint("id = 1", name="ck_billing_policy_singleton"),
        # A zero-day trial is legitimate (it turns the trial offer off); a negative one
        # is not.
        sa.CheckConstraint("trial_days >= 0", name="ck_billing_policy_trial_days"),
        sa.CheckConstraint("paid_cancel_access_days >= 0",
                           name="ck_billing_policy_cancel_days"),
        # Must be at least 3: the loader requires a two-day settle gap after the last
        # retry, and a retry cannot fire on day 0.
        sa.CheckConstraint("past_due_window_days >= 3",
                           name="ck_billing_policy_past_due_window"),
        # Format only — that it IS a list of integers. Whether the values are ordered and
        # fit inside the window is the loader's job.
        sa.CheckConstraint(
            r"retry_offsets_days ~ '^[0-9]+(,[0-9]+)*$'",
            name="ck_billing_policy_retry_offsets_format",
        ),
        schema=SCHEMA,
    )

    op.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.billing_policy "
            "(id, trial_days, paid_cancel_access_days, past_due_window_days, "
            " retry_offsets_days, updated_by) "
            "VALUES (1, :trial, :cancel, :window, :offsets, 'migration a1b2c3d4e5f7')"
        ).bindparams(
            trial=POLICY_SEED["trial_days"],
            cancel=POLICY_SEED["paid_cancel_access_days"],
            window=POLICY_SEED["past_due_window_days"],
            offsets=POLICY_SEED["retry_offsets_days"],
        )
    )

    # --- audit log (HISTORY) --------------------------------------------------
    # One row per cancel / uncancel. No foreign keys, deliberately: this is history and
    # must survive the entity or user it describes being deleted, or the record of why
    # someone was charged disappears with the thing it was about.
    op.create_table(
        "subscription_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("function_code", sa.String(100), nullable=False),
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("phase_before", sa.String(30), nullable=True),
        sa.Column("phase_after", sa.String(30), nullable=True),
        sa.Column("app_access_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_amount", sa.Integer, nullable=True),
        sa.Column("extension_state", sa.String(20), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        # The customer's own words from the cancellation dialog, optional on every path.
        # History, which is why it is here and not on entity_module_subscription: a
        # module cancelled, renewed and cancelled again has two reasons worth keeping,
        # and a column on the row would hold only the second. Kept apart from ``note``
        # (which WE write, about the action) so "why do people leave" is a query.
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_audit_log_entity_id",
                    "subscription_audit_log", ["entity_id"], schema=SCHEMA)
    op.create_index("ix_subscription_audit_log_created_at",
                    "subscription_audit_log", ["created_at"], schema=SCHEMA)

    # --- invoices (HISTORY) ---------------------------------------------------
    # The local record of what was billed and the guard against billing a period twice.
    # Names are SNAPSHOTS, entity_id / payer_user_id carry NO foreign key — same "history
    # must outlive its subject" reasoning as the audit log.
    op.create_table(
        "subscription_invoice",
        sa.Column("id", sa.String(36), primary_key=True),
        # WHO owes it. No FK: an invoice is history and must survive the payer row.
        sa.Column("payer_user_id", sa.String(36), nullable=False),
        # WHAT it was issued against. Denormalised from user_stripe_customer rather
        # than joined, because that mapping can be re-pointed (see
        # checkout._resolve_customer_id) and this must keep saying which customer was
        # actually charged.
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        # The processor's own id (in_...). Null while an invoice is being built, or if
        # it was never sent — a renewal with nothing to bill raises no Stripe invoice.
        sa.Column("external_id", sa.String(255), nullable=True),

        # The period this invoice COVERS, half-open [start, end) to match
        # billing.Period. Not the date it was raised — a renewal is raised at the start
        # of the period it bills, a proration part-way through one.
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),

        # CHAR(3) FK into the currency registry, narrowed from String(10). The width
        # was never used — an ISO code is three characters — and the column is now
        # constrained to codes the registry actually carries. Stored UPPER to match
        # currency_info.currency_code; store.reserve_invoice normalises on write, and
        # only the stored copy is normalised (Stripe's own currency is lowercase).
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.ForeignKeyConstraint(
            ["currency"], [f"{SCHEMA}.currency_info.currency_code"],
            name="fk_subscription_invoice_currency",
        ),
        # Minor units, like every other amount in this schema. Never a float.
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        # draft / open / paid / uncollectible / void — the processor's vocabulary,
        # kept as-is so there is no translation layer to disagree with.
        sa.Column("status", sa.String(20), nullable=False),
        # What the customer reads on the invoice (see renewals.renewal_memo).
        sa.Column("memo", sa.String(500), nullable=True),

        # WHICH CARD PAID IT, as a display string ("Visa •••• 4242"). Captured at
        # settle time and never re-derived, because the account's CURRENT default is a
        # different question the moment anyone updates a card — and the invoice it would
        # be wrong about first is a FAILED one, where which card was charged is the whole
        # question. Display only: it is a snapshot for history, like entity_name, and no
        # decision reads it. Null for invoices raised before this column existed, and for
        # any Stripe read that did not come back.
        sa.Column("payment_method", sa.String(100), nullable=True),

        # Stripe's hosted page for this invoice. Stored rather than fetched on demand:
        # rendering an invoice list should not be N Stripe round trips, and the URL is
        # stable for the life of the invoice. Null until it is finalized — a draft has
        # none.
        #
        # The page, not the PDF. Stripe exposes both; this one carries the PDF as a
        # download AND, for an invoice still open, a way to pay it — which is exactly
        # what the customer looking at a failed row needs. A second column holding the
        # direct PDF would only ever be the weaker half of what this already reaches.
        #
        # A CAPABILITY URL: the query token is the authorisation, so anyone holding the
        # link can read the invoice without signing in. Serve it to the payer, never log
        # it.
        sa.Column("hosted_invoice_url", sa.String(500), nullable=True),

        # The double-billing guard. Unique index below turns "we searched and didn't
        # find one" into "the database will not let us". Nullable, because a mid-period
        # purchase has no natural period key.
        sa.Column("idempotency_key", sa.String(255), nullable=True),

        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    # UNIQUE, not merely indexed: this is what makes charging a period twice impossible
    # rather than unlikely.
    op.create_index("uq_subscription_invoice_idempotency_key",
                    "subscription_invoice", ["idempotency_key"],
                    unique=True, schema=SCHEMA)
    # "What have we billed this payer?" — the query support asks.
    op.create_index("ix_subscription_invoice_payer",
                    "subscription_invoice", ["payer_user_id", "period_start"],
                    schema=SCHEMA)
    # Reconciliation against the processor.
    op.create_index("ix_subscription_invoice_external_id",
                    "subscription_invoice", ["external_id"], schema=SCHEMA)

    op.create_table(
        "subscription_invoice_line",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.subscription_invoice.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Every line is attributable to exactly ONE entity — the property that made
        # these invoices readable where the Stripe-subscription ones were not, because
        # there every line inherited the subscription's entity. No FK: history.
        sa.Column("entity_id", sa.String(36), nullable=False),
        # SNAPSHOTS, not references. See the module docstring.
        sa.Column("entity_name", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),

        sa.Column("amount", sa.Integer, nullable=False),
        # full / proration / extension / credit — mirrors billing.Line.kind, which is
        # what decides how the line describes itself to the customer.
        sa.Column("kind", sa.String(20), nullable=False, server_default="full"),
        # The instant a proration was measured from. Null for a whole-period line.
        sa.Column("at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_subscription_invoice_line_invoice_id",
                    "subscription_invoice_line", ["invoice_id"], schema=SCHEMA)
    # "What has this entity been charged?" — per-entity billing history.
    op.create_index("ix_subscription_invoice_line_entity_id",
                    "subscription_invoice_line", ["entity_id"], schema=SCHEMA)

    # --- email dedupe ledger --------------------------------------------------
    # The unique constraint on (event, dedupe_key) is the point of the table. Billing
    # emails fire from daily cron jobs that are deliberately safe to re-run —
    # ``retry-dunning`` gates on the retry schedule, not on when it last ran;
    # ``sweep-access`` re-derives the whole access map every pass. Re-running them must
    # not re-mail the customer, and the only durable way to promise that is a uniqueness
    # constraint in the database rather than a check in the runner.
    op.create_table(
        "subscription_email_log",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # No ``sent_at``. It was here originally and was removed from this revision on
        # 2026-08-27 rather than dropped by a later one: nothing in the chain referenced
        # it, so editing the create is what keeps a fresh build and an existing database
        # identical. Existing databases were ALTERed by hand at the same time — if you
        # meet one that still has the column, that is the reason.
        #
        # ``status`` already carries the fact, and it is the only thing ``notify._claim``
        # reads to decide a send has gone out.
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.user.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("event", "dedupe_key", name="uq_sub_email_event_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sub_email_user_created",
        "subscription_email_log",
        ["user_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade():
    # Reverse of create order. History before state, and lines before their header: they
    # cascade, but dropping the parent out from under an explicit FK is not something to
    # rely on ordering luck for.
    op.drop_table("subscription_email_log", schema=SCHEMA)
    op.drop_table("subscription_invoice_line", schema=SCHEMA)
    op.drop_table("subscription_invoice", schema=SCHEMA)
    op.drop_table("subscription_audit_log", schema=SCHEMA)
    op.drop_table("billing_policy", schema=SCHEMA)
    op.drop_table("billing_plan", schema=SCHEMA)
    op.drop_table("entity_billing_consent", schema=SCHEMA)
    op.drop_table("entity_module_subscription", schema=SCHEMA)
    op.drop_table("user_stripe_customer", schema=SCHEMA)
