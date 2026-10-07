-- ===========================================================================
-- pettycashv3 :: the subscription catalogue   (HAND-MAINTAINED - NOT generated)
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/seed_catalogue.sql
--
-- WHY THIS FILE EXISTS. A database built from 01_schema_rebased.sql has no `billing_plan` and
-- no `billing_policy` rows, so no subscription journey can run against it: a trial start has no
-- plan to start and no window to take its dates from. Until 2026-10-07 those two tables only
-- ever arrived by MIGRATING a legacy database - 02_data_foundation_rebased.sql reads them out of
-- `pettycashv2` in the same database, which an empty one does not have - and nothing in any repo
-- created them (`manage.py plans list` is read-only and says so: "the catalog is edited by hand
-- in SQL"). The catalogue therefore lived in the databases it had been typed into, and nowhere in
-- version control. This file is the catalogue, in git. It is what makes a cold start usable:
-- without it, `stack-e2e.yml` fails its catalogue check and the subscription journeys cannot run.
--
-- THE VALUES are the ones both `pettycashv3_data` and `pettycashv3_supabase` carry, read
-- 2026-10-07; the two agree on every column. The row IDs are deliberately NOT reproduced: they
-- differ per database by design, and `code` is the natural key the application looks a plan up by
-- (see `billing/services/store.py`), so the ids are minted by the column default here.
--
-- IDEMPOTENT. Re-running changes nothing. It also never UPDATEs an existing row, so a price
-- edited in a database is never silently reverted by a later run - which is the other half of the
-- rule below.
--
-- CHANGING A PRICE OR A WINDOW is a business decision, not a migration: change the row in the
-- database AND this file in the same change, or the two drift and this file stops being the
-- record. The windows in particular are deliberate (the dunning ladder stops at 13 on purpose).
--
-- WHAT IS NOT HERE. The full reference lists - 168 currencies, 249 countries, the 9 HKD
-- denominations, the 6 roles - are not seeded by this file; only the one `currency_info` row the
-- plans' foreign key needs. A fresh production install would want the rest, which is Part 3
-- step 2's "cold start from empty works" for `minty-db`, not this file's job. For the browser
-- suites, `scripts/e2e_seed.py` creates what it needs (HKD, the denominations, the modules).
-- ===========================================================================

BEGIN;

-- --------------------------------------------------------------------------
-- The one currency the plans below point at.
--
-- `billing_plan.currency` is a FOREIGN KEY to `currency_info.currency_code`, so on an empty
-- database this row has to exist before any plan does. `scripts/e2e_seed.py` also creates HKD,
-- but it runs after the services are up and this file runs before them, so it cannot be relied
-- on here. ON CONFLICT makes the overlap harmless either way.
-- --------------------------------------------------------------------------
INSERT INTO pettycashv3.currency_info (currency_code, currency_name, symbol, decimal_places, is_active)
VALUES ('HKD', 'Hong Kong Dollar', '', 2, TRUE)
ON CONFLICT (currency_code) DO NOTHING;

-- --------------------------------------------------------------------------
-- The price catalogue.
--
-- `amount` is an INTEGER in the minor unit of `currency` - 28000 is HKD 280.00, not 28,000.
-- `code` is the module combination the plan covers: a company on both modules is billed the
-- combined plan, which is why `BILL+PETTY_CASH` is cheaper than the two singles together.
-- --------------------------------------------------------------------------
INSERT INTO pettycashv3.billing_plan (code, display_name, amount, currency, interval_months, is_active)
VALUES
  ('PETTY_CASH',      'Petty Cash',      28000, 'HKD', 1, TRUE),
  ('BILL',            'Payment Request', 28000, 'HKD', 1, TRUE),
  ('BILL+PETTY_CASH', 'Super Minty',     40000, 'HKD', 1, TRUE)
ON CONFLICT (code) DO NOTHING;

-- --------------------------------------------------------------------------
-- The policy row. One row, ever: `ck_billing_policy_singleton` is CHECK (id = 1).
--
--   trial_days               a module's free trial, in days
--   paid_cancel_access_days  access kept after a PAID subscription is cancelled
--   past_due_window_days     how long an unpaid subscription stays past_due before access goes
--                            (CHECK >= 3)
--   retry_offsets_days       the dunning ladder, in days after the invoice. 1..13 is a decision,
--                            not an omission: there is deliberately no day-14 retry.
--
-- Every value below is also the column's DEFAULT in 01_schema_rebased.sql. They are written out
-- anyway, because this file is meant to be the readable record of what the numbers are.
-- --------------------------------------------------------------------------
INSERT INTO pettycashv3.billing_policy
  (id, trial_days, paid_cancel_access_days, past_due_window_days, retry_offsets_days, updated_by)
VALUES
  (1, 30, 30, 15, '1,2,3,4,5,6,7,8,9,10,11,12,13', 'seed_catalogue.sql')
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- --------------------------------------------------------------------------
-- What is now there. `manage.py plans list` in minty-subscription-api prints the same catalogue
-- from the application's side, and is the quickest proof a service reaches this database.
-- --------------------------------------------------------------------------
SELECT code, display_name, amount, currency, interval_months, is_active
  FROM pettycashv3.billing_plan
 ORDER BY code;

SELECT id, trial_days, paid_cancel_access_days, past_due_window_days, retry_offsets_days
  FROM pettycashv3.billing_policy;
