# Modules and subscriptions

Two modules can be on for a company: **Petty Cash** (this app's daily report) and
**Payment Request** (`BILL` — the bills module served by `billing-frontend` +
`billing-backend`). Whether a company *has* a module, and whether anyone *pays* for it, are
separate questions, and the second one is switched off in production today.

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
- Who pays: `user_stripe_customer` (the payer's Stripe customer),
  `payer_billing_group` / `entity_billing_group` (a payer's companies grouped so a card
  can be chosen per company — `billing_account_payment_method`), `entity_billing_consent`
  (the payer's consent to be billed for this company; recorded before any charge).

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
  (`subscription-restart-screen` note).
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
`scripts/subscription/copy_replay_to_rds.py`; the numbered dev scenarios are in the
`subscription-scenario-catalogue` note.

## Tests

`tests/test_char_subscription_dark.py` (dark), `tests/test_access_rules.py`,
`tests/test_double_buy_guard.py`, `tests/test_subscription_*.py`, `tests/test_billing_*.py`,
`tests/test_one_payer_per_entity.py`; billing-frontend's `03_payer_portal.spec.ts`
(live and dark) and Minty's `e2e/03_settings.spec.ts` (the dark module page: a switch is
pending until Save, Save repaints tabs and side panel).
