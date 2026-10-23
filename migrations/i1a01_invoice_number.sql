-- =====================================================================
--  AN INVOICE HAS ITS OWN NUMBER (2026-10-23, item 24 of
--  docs/schema/01_schema_rebased.sql)
--
--  TARGET: a pettycashv3-shaped schema built before item 24. Run with psql;
--  the schema is a variable, and nothing commits unless asked:
--
--    psql "$URL" -v ON_ERROR_STOP=1 -v schema=pettycashv3 -f i1a01_invoice_number.sql
--        -> runs everything, prints the checks, ROLLS BACK
--    ... -v apply=1 ...
--        -> the same, then COMMIT
--
--  WHAT
--
--    subscription_invoice.invoice_number VARCHAR(40) NULL, unique
--        (idx_si_invoice_number): INV-<ACCOUNT>-YYYYMM-NNNN, written by
--        minty-subscription-api when an invoice is first issued.
--    subscription_invoice_counter (period, last_value): one counter per month.
--
--  SAFE TO RUN ON LIVE: a nullable ADD COLUMN (no rewrite), an index over a
--  column that is NULL on every row, and a new empty table. No backfill
--  (owner): rows issued before keep showing Stripe's id. Idempotent.
--
--  DOWN (by hand): DROP TABLE subscription_invoice_counter;
--    DROP INDEX idx_si_invoice_number;
--    ALTER TABLE subscription_invoice DROP COLUMN invoice_number;
-- =====================================================================

\if :{?schema}
\else
  \set schema pettycashv3
\endif

BEGIN;
SET LOCAL search_path TO :"schema";

ALTER TABLE subscription_invoice
  ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(40) NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_si_invoice_number
  ON subscription_invoice (invoice_number);

CREATE TABLE IF NOT EXISTS subscription_invoice_counter (
  period     VARCHAR(6) NOT NULL,
  last_value INTEGER    NOT NULL,
  CONSTRAINT subscription_invoice_counter_pkey PRIMARY KEY (period)
);

-- after: both present (must be 1 and 1)
SELECT count(*) AS invoice_number_column
  FROM information_schema.columns
 WHERE table_schema = :'schema' AND table_name = 'subscription_invoice'
   AND column_name = 'invoice_number';
SELECT count(*) AS counter_table
  FROM information_schema.tables
 WHERE table_schema = :'schema' AND table_name = 'subscription_invoice_counter';

\if :{?apply}
  COMMIT;
  \echo 'i1a01 COMMITTED'
\else
  ROLLBACK;
  \echo 'i1a01 dry run - ROLLED BACK (pass -v apply=1 to commit)'
\endif
