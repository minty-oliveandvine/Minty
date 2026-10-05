# Modules and subscriptions

Two modules can be on for a company: **Petty Cash** (this app's daily report) and
**Payment Request** (`BILL` — the bills module served by `minty-payment-request-web` +
`minty-payment-request-api`). Whether a company *has* a module, and whether anyone *pays* for it, are
separate questions.

> **Moving out (Part 2 of `docs/modernisation/modernisation_plan.md`, since 2026-09-21).** The
> engine described in §3, the payer portal routes, the module settings page and the daily pass
> move to two new repos: `../minty-subscription-api` (Django, :8000 — `docs/features/subscriptions-api.md`
> there is the route-by-route map) and `../minty-web` (Next.js, :3000 — `docs/features/subscriptions.md`).
> Step 1 (the scaffolds) and step 2 (the engine: all 24 service modules ported 1:1 with 762 of
> their tests, slices A-D on 2026-09-21; the replay golden is slice E) are done; until step 5
> removes them, everything on this page is still the running code and the spec the port is
> checked against - `blueprints/subscription/services/*`, `entity/services/modules.py`, the
> models and `tests/*` are FROZEN for the duration, a bug found by the port is fixed on both
> sides together, never on one. What Flask keeps for good: §2's
> gate (`_is_module_enabled`), `flask modules set|show`, `POST /api/onboarding/modules`, and
> five read-only lookups through a `store_ro.py` that step 5 introduces.
>
> **2026-10-01:** Flask's Jinja module page and the 20 session routes behind it are DELETED
> (the Module tab is a hand-over to minty-web's page), the dark switch is gone from every
> repo, and the in-app notices lost their trial kinds - see §1, §4 and the notices bullet.

## 1. No switch: subscriptions are always on

The dark switch `SUBSCRIPTION_ENABLED` (off unless set; production was to cut over with the
feature dark, 2026-09-18) was **removed on 2026-10-01** in every repo - Minty, minty-onboarding-api,
minty-onboarding-web, minty-payment-request-web, minty-web and minty-subscription-api - because the stack is deployed to
a test site and nothing is dark any more. Its one rule outlives it: **turning the feature on
wrote nothing** - no grant, no trial, no revocation - and taking access away from a module no
subscription backs is still the separate, deliberate `flask subscriptions revoke-ungranted
[--apply]` (`services/access_sweep.py`; dry by default). Migration `m1a01` is a no-op for the
same reason. The daily pass keeps its own switch, `SUBSCRIPTION_SCHEDULER_ENABLED` (§3) - in
Minty AND minty-subscription-api, which share the database, so never on in both.

## 2. Module access (always on)

`entity_function` is the catalogue (`PETTY_CASH`, `PAYMENT_REQUEST`), `entity_function_map`
the per-company switches. `blueprints/entity/services/modules.py` (`set_entity_module`, `get_module_cards`) and the
context processors in
`pettycash/core/hooks.py` (`is_pettycash_enabled`, `is_billing_enabled` — keyed on
`MODULE_BILL`) decide what the side panel, the settings tabs and the dashboard show; a
page of a module that is off renders `entity_no_permission.html` (with a link to the
module settings when the person may open them). The module token minted
for the payment app carries `billing_enabled` / `petty_cash_enabled`, but minty-payment-request-api
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
  minty-subscription-api; Flask's copy of the services is not mirrored (Django replaces them -
  see `flask-subscription-no-more-ports`).

**Every charge names the billing account's card, and there is no fallback** (the
per-entity-cards decision of 2026-08-25). A renewal, a mid-period change, a trial conversion,
a transfer's first charge, a dunning retry and a re-issued invoice all hand the company's
`payer_billing_group` (and so its `stripe_payment_method_id`) to `billing_gateway`. An invoice
raised with no card named is charged by Stripe to the customer's account default, which is a
bug, not a fallback: a company with no nomination is refused or skipped, never billed
elsewhere. Fixed 2026-09-29 in both engines: undoing a cancellation after its extension was
invoiced (`checkout._bill_reinstatement_in_house`) charged the uncovered remainder with no
group, so the invoice carried no `billing_group_id` and went to the account default; it now
resolves the company's group and refuses (409, "Choose a payment method for this company
before restoring this module.") when there is none.

**A refused purchase leaves no open invoice** (2026-09-29, both engines). A declined card raises
out of `Invoice.pay` with the invoice finalized and OPEN, and dunning chases the payer's oldest
open invoice. A trial conversion and a handover already voided theirs; a declined reinstatement
did not, so a customer could later pay for a restore that never happened. All three now void
through `checkout._void_unpaid_invoice` on both failure paths. **Each Stripe item carries its
own days** (same day, both engines): `billing_gateway._item_period` sends the line's recorded
span (`billing.Line.period_start` / `period_end`) instead of the invoice's whole period, so
Stripe's PDF no longer dates a prorated start, a credit or an access extension as a full month.
Minty's own invoice PDF (Figma 09-A) is served by minty-subscription-api
(`GET /api/me/invoices/{id}/pdf`); Flask has no copy of it.

The rules the user chose deliberately (`subscription-pricing-decisions`,
`subscription-tunable-windows` in the notes): a **30-day** card-free trial per module
(`DEFAULT_TRIAL_DAYS`), **15 days** of past-due access (`PAST_DUE_GRACE_DAYS`), dunning
retries on days **1…13** after a failed renewal (`RETRY_OFFSETS_DAYS`), a cancelled paid
module keeps access to the end of what was paid (`DEFAULT_PAID_CANCEL_ACCESS_DAYS`).

**An invoice Stripe will no longer collect is re-issued** (2026-09-28, both engines). Stripe
cancels an invoice's payment once it has been confirmed too many times (ten declines in our test
account; its docs give no number), after which no retry or Retry-payment press can succeed.
`billing_gateway.retry_invoice` detects it (before paying, and after the failed call that
crossed the limit) and `dunning._charge` re-issues the invoice with `billing_gateway.
refresh_invoice` — its recorded lines and Stripe items copied, the period key moved over by
`store.supersede_invoice`, the original voided only once the replacement is open — and charges
the replacement in the same attempt. The whole mechanism, its crash windows and the `L2` replay
that proves it are in minty-subscription-api `docs/features/subscriptions-api.md` §6 and §8.

**Invoices after the fact, drafts, the API version and money mail (2026-09-30, both engines,
byte-identical apart from imports).** The full account is minty-subscription-api's §5 and §6; here,
what each one is:
- **A draft nobody finalized is loud and, for a renewal, finished.** An error or a crash between
  `Invoice.create` and `finalize_invoice` left a draft nothing touched again (dunning chases open
  invoices only; every later pass skipped the period), so the period was never billed.
  `billing_gateway.stranded_draft` logs one `STRANDED DRAFT` ERROR line wherever one is met;
  `renewals._renew_one_group` hands a renewal row still reading "draft" to
  `billing_gateway.resume_invoice`, which adds the missing items only, finalizes and charges the
  account's CURRENT card, and refuses (loudly, charging nothing) anything that is not exactly what
  was reserved; `dunning._nothing_open_but_owed` stops dunning calling it "settled elsewhere".
- **A row says what Stripe says.** `billing_gateway.record_found_invoice` / `refresh_record`:
  a recovered reservation is recorded whole (paid date, link, card), a stored draft/open row is
  re-read before it is answered from, `changes.issue_change` records what it found, and dunning
  re-reads the card's rows still reading "open" when nothing is open.
- **The Stripe API version is pinned** (`stripe_client.STRIPE_API_VERSION`,
  `"2024-12-18.acacia"`, also set by `scripts/subscription/prune_replay_stripe.py`) and
  `tests/test_stripe_api_version.py` fails the build if the SDK moves under it; an invoice
  missing `charge` / `payment_intent` is logged at ERROR.
- **An extension-only invoice** reads "Access extension", not "Renewal" (`portal._event`).
- **Money emails** (receipt, both declines, recovery) go to the billing account's
  `billing_email` when it has one, greeted by its company (`notify.address_for`); the email
  log's recipient is cut to its 200 characters; a second card's retry notice is no longer
  swallowed when another recovers.
- **The daily pass no longer crashes** when a card is still due after the renewal step
  (`daily._log_renewal_backlog` read the per-card list as pairs, outside the step's try).
Tests: `tests/test_invoice_resume.py`, `tests/test_daily_backlog.py`,
`tests/test_stripe_api_version.py`, and new cases in the renewal, dunning, change, transfer,
portal, notification and scheduler tests. `tests/conftest.py` now overrides `caplog` so loguru's
records reach it, and a test asserts on the engine's log exactly as the Django twin does.

### The passes
`services/daily.run_daily` runs five jobs in this order — `notify-trial-ending` →
`close-trials` → `run-renewals` → `retry-dunning` → `sweep-access` — as a **full** pass once
a day and a **light** pass (the two a customer feels, then a sweep of just the payers they
touched) every hour except the full one; `services/app_runtime/scheduler.py` is the in-process
APScheduler timer (two gunicorn workers → both fire, a Postgres advisory lock lets one
run; **off unless `SUBSCRIPTION_SCHEDULER_ENABLED`**). The same jobs are the
`flask subscriptions …` commands (`cli/subscription_access.py`: `run-daily`,
`close-trials`, `run-renewals`, `retry-dunning`, `notify-trial-ending`, `sweep-access`,
`reconcile-customers`, `revoke-ungranted`); `flask plans list`, `flask modules set|show`.

### What the pages do
- The **Module tab** (`GET /entity/<co>/settings/modules`) is a **hand-over**: the route mints
  the company's module token and redirects to
  `MINTY_WEB_URL/landing?next=/subscription/entities/<shortid>/<name>/modules` (`tests/test_minty_web_handoff.py`;
  the page's Back returns to wherever the person came from, so nothing is carried). The page is minty-web's (Part 2 step 4a,
  `../minty-web/docs/features/subscriptions.md` §9) and posts its 19 actions to
  minty-subscription-api. **Flask's Jinja module page, its partials (`module_*.html`), the lapsed-trial
  restart screen and the 20 session routes under `…/module/<id>/…` (the 19 actions and the
  dark-only `/toggle`) were deleted on 2026-10-01**; the engine services they called stay until
  Flask's engine goes as a whole. Two more doors exist for that page:
  `GET /handoff/minty-web?next=&entity_id=` (login-gated re-entry when minty-web's token
  lapses - a scoped token with `entity_id`, unscoped without; `next` is a path only) and
  `GET /entity/<co>/settings/payment-request` (the Payment Settings tab as a URL: the redirect
  `billing_settings_app_url` builds, since only Flask mints the payments-app token;
  `tests/test_settings_payments_redirect.py`).
- The **in-app notices** (`services/notices.py`; the Petty Cash dashboard's once-per-login
  modal `partials/subscription_notice_modal.html`, and `GET /api/entity/<id>/subscription-notice`
  for the payment app's landing page): **two kinds only since 2026-10-01** - `past_due` ("payment
  failed", critical) and a PAID module's `pending_cancel` ("is ending", warning). Every TRIAL
  notice (trial ending, a trial that will not convert, a lapsed trial, a cancelled trial running
  out) was removed by the user's decision; the trial-ending EMAIL still warns a trial that will
  not convert. `_NOTICE_ORDER` (`entity/services/modules.py`) must list every kind emitted - the
  sort `.index()`es it, and the API answers `{"items": []}` on any builder failure (logged).
  The one button, "Go to subscription settings", is `/handoff/minty-web?next=<module page>
  &entity_id=` - a Minty path the payment app wraps in `buildMintyEnterUrl`, authenticated at
  the click (`minty_web_module_page_handoff`), landing on minty-web's Module page.
- The **payer portal** lives in minty-web (`/subscription/*`, served by minty-subscription-api's
  `/api/me/*`). Flask's `/api/me/*` (`blueprints/subscription/routes/portal.py`) has **no browser
  caller since 2026-10-01** - minty-payment-request-web's portal pages were deleted - and goes with the
  engine. Every "open my profile" link (`bills_app_profile_url`, the sidebar) goes through
  `GET /profile` (`entity.open_profile`), which always hands over to minty-web's My Profile;
  the transfer emails link to minty-web's portal through `/handoff/minty-web`
  (`notify.portal_url`).
- Emails: `services/notify.py` — eight events, exactly the approved Figma designs (trial
  ending, renewal failed, dunning retry failed, payment recovered, the four transfer notices),
  each sent once per `dedupe_key` and logged in `subscription_email_log`. The receipt
  (`renewal_paid`) and `trial_expired` were retired on 2026-09-30, so a successful charge and a
  lapsed trial are silent. Who gets them (`notify.address_for`): the three about money go to
  the billing account's address — its `billing_email`, else the business email every company
  on it shares, else the payer (`store.account_email`, the same rule as the invoice's Bill to);
  trial ending goes to the company's business email, else the payer; the transfer notices go
  to the person. Dates are written in the company's time zone (`entities.timezone`, Hong Kong
  when unset); an email about a whole billing account uses the zone all its companies share,
  else Hong Kong (`notify.account_zone`). The two payment-failed emails name the LAST FULL DAY
  to pay - the day before the account's past-due access runs out (`dunning.suspension_at`:
  `paid_through` + the past-due window), because from that moment "Pay now" is refused
  (decided 2026-09-30). The app's own "Pay by" line still prints the day access ends, in UTC,
  so it can read a day later than the email until Part 3's date work.

### Tooling
`scripts/subscription/replay_scenarios.py` seeds scenarios by living them (a test clock);
`scripts/subscription/copy_replay_to_rds.py`. Its catalogue is Figma 05·A: one company per
module-status combination, named for its frame ("M44 Nexora Health Limited"). The table, the ten
frames it cannot live and why, and its shelf life are in minty-subscription-api
`docs/features/subscriptions-api.md` §8, "The replay catalogue". The Django port there runs the
same shapes.

## Tests

`tests/test_access_rules.py`, `tests/test_double_buy_guard.py`,
`tests/test_subscription_*.py`, `tests/test_billing_*.py`, `tests/test_one_payer_per_entity.py`,
`tests/test_minty_web_handoff.py` (the Module tab is a hand-over, and nothing else answers under
it); Minty's `e2e/03_settings.spec.ts` reads that redirect. The Jinja module-page tests
(`test_subscription_templates`, `test_consent_takeover`, `test_restart_billing_guard`,
`test_purchase_card_choice`, `test_retry_decline_wording`, the dark suite) went with the page on
2026-10-01.
