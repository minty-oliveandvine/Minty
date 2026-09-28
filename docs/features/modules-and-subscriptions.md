# Modules and subscriptions

Two modules can be on for a company: **Petty Cash** (this app's daily report) and
**Payment Request** (`BILL` — the bills module served by `billing-frontend` +
`billing-backend`). Whether a company *has* a module, and whether anyone *pays* for it, are
separate questions, and the second one is switched off in production today.

> **Moving out (Part 2 of `docs/modernisation/modernisation_plan.md`, since 2026-09-21).** The
> engine described in §3, the payer portal routes, the module settings page and the daily pass
> move to two new repos: `../minty-billing-api` (Django, :8004 — `docs/features/subscriptions-api.md`
> there is the route-by-route map) and `../minty-web` (Next.js, :3002 — `docs/features/subscriptions.md`).
> Step 1 (the scaffolds) and step 2 (the engine: all 24 service modules ported 1:1 with 762 of
> their tests, slices A-D on 2026-09-21; the replay golden is slice E) are done; until step 5
> removes them, everything on this page is still the running code and the spec the port is
> checked against - `blueprints/subscription/services/*`, `entity/services/modules.py`, the
> models and `tests/*` are FROZEN for the duration, a bug found by the port is fixed on both
> sides together, never on one. What Flask keeps for good: §2's
> gate (`_is_module_enabled`), the dark toggle, `flask modules set|show`, `POST /api/onboarding/modules`,
> the m1a01 skip, and five read-only lookups through a `store_ro.py` that step 5 introduces.

## 1. The switch: `SUBSCRIPTION_ENABLED` (off unless set)

`blueprints/shared/feature_flags.py` — `subscriptions_enabled()` and
`@require_subscriptions_enabled` (404). The same name is read by onboarding-backend
(`config.settings.SUBSCRIPTION_ENABLED`) and billing-frontend
(`NEXT_PUBLIC_SUBSCRIPTION_ENABLED`, on unless `0`); Minty is the real guard.

**Dark** (the cutover state, `tests/test_char_subscription_dark.py`):
- module access is `entity_function_map.is_enabled`, nothing else;
- the module page is a plain list of the two modules with an admin switch and a **Save**
  button (`POST /entity/settings/module/<id>/toggle` with `{modules: {code: bool}}`, a
  dark-only route; the page repaints the tabs and the side panel without a reload —
  `templates/entity/partials/module_plain_section.html`);
- every quote / charge / card / portal route answers 404: the 19 module actions on the
  settings page, `/api/me/*`, the onboarding billing routes, the subscription-notice API;
  the wizard's Step 2 is a plain module pick and `finalize` starts no trial;
- the scheduler does not start whatever `SUBSCRIPTION_SCHEDULER_ENABLED` says; migration
  `m1a01` skips its revocation.

**Switching it on writes nothing** — no grant, no trial, no revocation. Taking access away
from a module no subscription backs is the separate launch-day command
`flask subscriptions revoke-ungranted [--apply]` (`services/access_sweep.py`; dry by
default, refused while dark). The plan for that day is Phase E step 8b of
`docs/modernisation/modernisation_plan.md`.

## 2. Module access (always on)

`entity_function` is the catalogue (`PETTY_CASH`, `PAYMENT_REQUEST`), `entity_function_map`
the per-company switches. `blueprints/entity/services/modules.py` (`set_entity_module`,
`get_plain_module_cards`, `get_module_cards`) and the context processors in
`pettycash/core/hooks.py` (`is_pettycash_enabled`, `is_billing_enabled` — keyed on
`MODULE_BILL`) decide what the side panel, the settings tabs and the dashboard show; a
page of a module that is off renders `entity_no_permission.html` ("This module isn't
switched on…" while dark, with a link to the module settings). The module token minted
for the payment app carries `billing_enabled` / `petty_cash_enabled`, but billing-backend
re-reads the map (`/api/auth/entitlements`) — the database decides, not the claim.

## 3. The subscription engine (when on)

Minty is its own biller: the Stripe *subscription* objects were retired; Minty charges
synchronously through Stripe **invoices** (`services/stripe_client.py`:
`Invoice.create` / `InvoiceItem.create` / `finalize_invoice` / `pay` / `void_invoice`) and
owns every state. Models in `blueprints/subscription/models/`:

- `entity_module_subscription` — **one row per (company, module)**, the source of truth:
  `payer_user_id`, `phase` (trial / active / past_due / scheduled_cancel / cancelled /
  expired — `SubscriptionStatus`), `trial_end`, `billed_through`, `app_access_until`, the
  cancel-extension state. A bundle (both modules) is billed as **one** price
  (`store.billing_plan_for_codes`) — never sum the rows.
- `billing_plan` (prices), `billing_policy` (the tunable windows), `subscription_invoice`
  and `subscription_audit_log`, `subscription_email_log` (each notice sent once),
  `subscription_transfer` (handing a company's bill to another admin).
- Who pays: `user_stripe_customer` (the payer's Stripe customer and their one billing
  anchor), `payer_billing_group` — a **billing account**: a name (`billing_company`, the
  invoice's "Bill to") and `billing_email`, the ONE card it charges, its other cards on
  `billing_account_payment_method`, its own `paid_through` and dunning clock; a payer may
  hold several, all renewing on the payer's anchor — `entity_billing_group` (which account
  pays for a company; `source` says how it got there, `moved` for the payer portal's
  "Change billing account"), `entity_billing_consent` (the payer's consent to be billed
  for this company; recorded before any charge). Since 2026-09-25 the accounts are read,
  renamed, re-carded and given companies from minty-web's payer portal, served by
  minty-billing-api; Flask's copy of the services is not mirrored (subscriptions are dark
  here, and Django replaces them).

The rules the user chose deliberately (`subscription-pricing-decisions`,
`subscription-tunable-windows` in the notes): a **30-day** card-free trial per module
(`DEFAULT_TRIAL_DAYS`), **15 days** of past-due access (`PAST_DUE_GRACE_DAYS`), dunning
retries on days **1…13** after a failed renewal (`RETRY_OFFSETS_DAYS`), a cancelled paid
module keeps access to the end of what was paid (`DEFAULT_PAID_CANCEL_ACCESS_DAYS`).

### The passes
`services/daily.run_daily` runs five jobs in this order — `notify-trial-ending` →
`close-trials` → `run-renewals` → `retry-dunning` → `sweep-access` — as a **full** pass once
a day and a **light** pass (the two a customer feels, then a sweep of just the payers they
touched) every other hour; `services/app_runtime/scheduler.py` is the in-process
APScheduler timer (two gunicorn workers → both fire, a Postgres advisory lock lets one
run; **off unless `SUBSCRIPTION_SCHEDULER_ENABLED`**). The same jobs are the
`flask subscriptions …` commands (`cli/subscription_access.py`: `run-daily`,
`close-trials`, `run-renewals`, `retry-dunning`, `notify-trial-ending`, `sweep-access`,
`reconcile-customers`, `revoke-ungranted`); `flask plans list`, `flask modules set|show`.

### What the pages do
- The **module page** (`/entity/settings/module/<id>`): cards per module with the
  subscription state, and the 19 actions under `…/module/<id>/…` — quotes
  (`subscribe-preview`, `resume-preview`, `cancel-preview`, `restart-quote`), the charges
  (`checkout`, `confirm-billing`, `restart-billing`, `retry-payment`), cards
  (`payment-methods*`, `payment-method`), `start-trial`, `cancel`, `renew`,
  `authorize-billing`, `manage-billing` (the Stripe portal), `checkout-complete`. The
  lapsed-trial **restart screen** keys on the access gate, not on `trial_end`
  (`subscription-restart-screen` note). **Live, the page is minty-web's now** (Part 2 step
  4a, `../minty-web/docs/features/subscriptions.md` §9): the route mints the company's module
  token and redirects to `MINTY_WEB_URL/landing?next=/subscription/entities/<id>/modules`
  (`?from=bills` travels in `next`); `MINTY_WEB_MODULE_PAGE=0` keeps the Jinja page, and the
  test suite runs that way so the tests above still describe what they exercise
  (`tests/test_minty_web_handoff.py`). Two more doors exist for that page:
  `GET /handoff/minty-web?next=&entity_id=` (login-gated re-entry when minty-web's token
  lapses - a scoped token with `entity_id`, unscoped without; `next` is a path only) and
  `GET /entity/settings/payments/<id>` (the Payment Settings tab as a URL: the redirect
  `billing_settings_app_url` builds, since only Flask mints the payments-app token;
  `tests/test_settings_payments_redirect.py`).
- The **dashboard notices** (`services/notices.py`, `/api/entity/<id>/subscription-notice`
  for the payment app's landing page): trial ending, past due, expired, cancelled — one
  popup per scenario (`subscription-dashboard-notice-coverage`).
- The **payer portal** lives in billing-frontend and reads `/api/me/*`
  (`blueprints/subscription/routes/portal.py`): the companies the caller pays for with
  each module's state, invoices, saved cards and the card per company, inviting an admin
  and **transferring** a company's bill to another admin (offer / respond / cancel).
- Emails: `services/notify.py` — ten events (trial ending / expired, renewal paid (a receipt)
  / failed, dunning retry failed, payment recovered, the four transfer notices), each sent
  once per `dedupe_key` and logged in `subscription_email_log`.

### Tooling
`scripts/subscription/replay_scenarios.py` seeds scenarios by living them (a test clock);
`scripts/subscription/copy_replay_to_rds.py`. Its catalogue is Figma 05·A: one company per
module-status combination, named for its frame ("M44 Nexora Health Limited"). The table, the ten
frames it cannot live and why, and its shelf life are in minty-billing-api
`docs/features/subscriptions-api.md` §8, "The replay catalogue". The Django port there runs the
same shapes.

## Tests

`tests/test_char_subscription_dark.py` (dark), `tests/test_access_rules.py`,
`tests/test_double_buy_guard.py`, `tests/test_subscription_*.py`, `tests/test_billing_*.py`,
`tests/test_one_payer_per_entity.py`; billing-frontend's `03_payer_portal.spec.ts`
(live and dark) and Minty's `e2e/03_settings.spec.ts` (the dark module page: a switch is
pending until Save, Save repaints tabs and side panel).
