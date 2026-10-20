-- ===========================================================================
-- pettycashv3 :: which countries are offered   (HAND-MAINTAINED - NOT generated)
--
-- THE RULE (owner, 2026-10-20): Hong Kong is the one market Minty sells in, so HK is the only
-- active country. `country_info.is_active` is what the onboarding wizard's Country list and its
-- Phone Number picker show (minty-onboarding-api `api_reference.py`), and what Flask's
-- country lists and minty-petty-cash-api's settings filter on. Every other row stays in the
-- table: a company already set to another country keeps it (petty-cash settings adds the
-- company's own country back), the subscription billing address lists every country, and the
-- onboarding API's dial-code check reads every row's `phone_code`, active or not.
--
-- APPLIED to Supabase pettycashv3 on 2026-10-20, together with seed_country_phone_codes.sql
-- (before: 249 countries, all active, 0 dial codes). Opening another market means changing
-- this file AND the row together.
--
-- NOT in scripts/load_catalogue.py: that loader promises never to overwrite a value, and this
-- file does. Run it on its own, against the schema it names; for another schema, rewrite the
-- `pettycashv3.` prefix first (never pipe it in as-is).
-- ===========================================================================

BEGIN;

UPDATE pettycashv3.country_info
SET is_active = (country_code = 'HK')
WHERE is_active IS DISTINCT FROM (country_code = 'HK');

COMMIT;
