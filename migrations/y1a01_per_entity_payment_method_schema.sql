-- =====================================================================
--  PER-ENTITY PAYMENT METHODS — schema for a card per company
--
--  *** TARGET SCHEMA: pettycashv2  —  THIS IS THE LIVE SCHEMA ***
--
--  Raw-SQL twin of alembic revision y1a01_billing_group_schema.
--  Run the .sql OR the .py — never both.
--
--  *** ENDS IN ROLLBACK. *** Run once as-is to read the output, then change
--  the last line to COMMIT.
--
--  ------------------------------------------------------------------
--  WHAT THIS CREATES
--
--    1. pettycashv2.payer_billing_group        one card, and its cycle
--    2. pettycashv2.entity_billing_group       which card pays for what
--    3. subscription_invoice.billing_group_id  which card was billed
--
--  Purely additive. Both tables are created EMPTY and nothing reads them:
--  user_stripe_customer.paid_through and its dunning columns stay
--  authoritative until the cutover ships the services that use these.
--
--  ------------------------------------------------------------------
--  WHY A GROUP AND NOT A payment_method_id COLUMN
--
--  A payer has ONE card today, and one paid_through and one dunning clock
--  to go with it. The decision this feature was scoped around is that a
--  DECLINE IS CONTAINED — company A on a good card keeps working while
--  company B's dead card goes to collection. That is impossible while the
--  retry clock is a single per-payer value, because every retry decision
--  is then taken for the whole account at once. So the money state moves
--  onto the group: one card, one paid_through, one dunning clock.
--
--  anchor_at and currency deliberately STAY on user_stripe_customer. Every
--  group of a payer renews on the same period boundaries — one cycle,
--  several invoices — so the month-end clamp is untouched.
--
--  THE CARD IS AN ATTRIBUTE, NOT THE KEY. Entities point at the GROUP and
--  the group names the card, so replacing an expiring card is an UPDATE of
--  one column. Pointing entities straight at a pm_... id would strand the
--  cycle on every card replacement: a new id is a new key, its paid_through
--  starts NULL, and renewals skips NULL outright — the company would
--  quietly stop renewing with nothing raising an error.
--
--  ------------------------------------------------------------------
--  AFTERWARDS, RUN THE BACKFILL
--
--    python scripts/backfill_billing_groups.py          (report only)
--    python scripts/backfill_billing_groups.py --write
--
--  It reads each payer's Stripe default and gives every payer exactly one
--  group holding exactly today's state. It cannot live here: the card id is
--  not in this database, it is on the Stripe customer.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. payer_billing_group
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.payer_billing_group (
    id                        varchar(36)  PRIMARY KEY,
    payer_user_id             varchar(36)  NOT NULL,
    -- pm_.... Mutable: this is how a card is REPLACED without losing the cycle.
    stripe_payment_method_id  varchar(255) NOT NULL,
    -- NULL until this card has actually collected something.
    paid_through              timestamptz  NULL,
    -- Anchors the whole retry schedule. NULL = this card is not in collection.
    dunning_started_at        timestamptz  NULL,
    dunning_attempts          integer      NOT NULL DEFAULT 0,
    created_at                timestamptz  NOT NULL DEFAULT now(),
    updated_at                timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_payer_billing_group_user
        FOREIGN KEY (payer_user_id) REFERENCES pettycashv2."user" (id),
    -- A payer must not hold two groups on one card, or the same company's
    -- renewal could be claimed by either and the two would disagree about
    -- what was paid.
    CONSTRAINT uq_payer_billing_group_payer_card
        UNIQUE (payer_user_id, stripe_payment_method_id)
);

CREATE INDEX IF NOT EXISTS ix_payer_billing_group_payer
    ON pettycashv2.payer_billing_group (payer_user_id);

-- The collection work list. Partial — NULL on nearly every group forever.
CREATE INDEX IF NOT EXISTS ix_payer_billing_group_dunning
    ON pettycashv2.payer_billing_group (dunning_started_at)
 WHERE dunning_started_at IS NOT NULL;


-- ---------------------------------------------------------------------
-- 2. entity_billing_group
--
--    Grain (entity_id, payer_user_id) — the same grain x1a01 widened
--    entity_billing_consent to, for the same reason. Unique on entity_id
--    alone, the OLD payer's nomination would go on naming a card after the
--    company had been handed to someone else, and that card belongs to a
--    different person.
--
--    billing_group_id is NOT NULL. A row saying "no card" would be the
--    account-default fallback by another name, and there is deliberately no
--    fallback: a billable company with no row here is a billing error to be
--    reported, not a default to be inherited silently.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.entity_billing_group (
    id                varchar(36)  PRIMARY KEY,
    entity_id         varchar(36)  NOT NULL,
    payer_user_id     varchar(36)  NOT NULL,
    billing_group_id  varchar(36)  NOT NULL,
    -- capture / chosen / backfill — mirrors entity_billing_consent.source.
    source            varchar(20)  NOT NULL,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_entity_billing_group_entity
        FOREIGN KEY (entity_id) REFERENCES pettycashv2.entities (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_entity_billing_group_user
        FOREIGN KEY (payer_user_id) REFERENCES pettycashv2."user" (id),
    CONSTRAINT fk_entity_billing_group_group
        FOREIGN KEY (billing_group_id)
        REFERENCES pettycashv2.payer_billing_group (id),
    CONSTRAINT uq_entity_billing_group_entity_payer
        UNIQUE (entity_id, payer_user_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_billing_group_entity
    ON pettycashv2.entity_billing_group (entity_id);
CREATE INDEX IF NOT EXISTS ix_entity_billing_group_payer
    ON pettycashv2.entity_billing_group (payer_user_id);
CREATE INDEX IF NOT EXISTS ix_entity_billing_group_group
    ON pettycashv2.entity_billing_group (billing_group_id);


-- ---------------------------------------------------------------------
-- 3. subscription_invoice.billing_group_id
--
--    A renewal stops being one document per payer per period. The
--    double-billing guard and the dunning retry target both have to ask
--    "this GROUP's invoice for this period", and to ask it of the local row
--    rather than by scanning the processor.
--
--    Nullable, no FK, no backfill. NULL on every existing row means "raised
--    before per-entity cards existed", which is exactly true.
-- ---------------------------------------------------------------------
ALTER TABLE pettycashv2.subscription_invoice
    ADD COLUMN IF NOT EXISTS billing_group_id varchar(36) NULL;

CREATE INDEX IF NOT EXISTS ix_subscription_invoice_group
    ON pettycashv2.subscription_invoice (billing_group_id, period_start)
 WHERE billing_group_id IS NOT NULL;


-- ---------------------------------------------------------------------
-- 4. VERIFY — read this before deciding to COMMIT.
-- ---------------------------------------------------------------------

-- Expect both tables, both empty.
SELECT 'payer_billing_group'  AS table_name,
       count(*)               AS rows_expected_zero
  FROM pettycashv2.payer_billing_group
 UNION ALL
SELECT 'entity_billing_group', count(*)
  FROM pettycashv2.entity_billing_group;

-- Expect one row: billing_group_id, character varying, YES (nullable).
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'pettycashv2'
   AND table_name   = 'subscription_invoice'
   AND column_name  = 'billing_group_id';

-- Expect every invoice to have it NULL — nothing is backfilled here.
SELECT count(*) AS invoices,
       count(billing_group_id) AS with_a_group_expected_zero
  FROM pettycashv2.subscription_invoice;

-- If you are running the .sql instead of the .py, alembic will not know.
-- Stamp it by hand ONLY if this database is alembic-managed and you are
-- certain the prior head is k1a01_drop_consent:
--
--   UPDATE pettycashv2.alembic_version SET version_num = 'y1a01_billing_group_schema'
--    WHERE version_num = 'k1a01_drop_consent';


-- =====================================================================
--  *** CHANGE THIS TO  COMMIT;  TO APPLY. ***
-- =====================================================================
ROLLBACK;
