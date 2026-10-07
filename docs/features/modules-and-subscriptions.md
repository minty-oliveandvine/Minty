# Modules and subscriptions

Two modules can be on for a company: **Petty Cash** (this app's daily report) and
**Payment Request** (`BILL` — the bills module served by `minty-payment-request-web` +
`minty-payment-request-api`). Whether a company *has* a module, and whether anyone *pays* for it, are
separate questions.

> **The engine is gone from Flask (2026-10-06).** Subscriptions are `../minty-subscription-api`
> (Django, :8000 - `docs/features/subscriptions-api.md` there is the route-by-route map) and
> `../minty-web` (Next.js, :3000 - `docs/features/subscriptions.md`): the engine, the payer
> portal, the module settings page, the emails, the CLI and the daily pass. Flask's copy - the
> 24 `blueprints/subscription/services/*` modules, `routes/portal.py` (`/api/me/*`), the onboarding
> billing routes and finalize, `GET /api/entity/<id>/subscription-notice`, `cli/subscription_*.py`,
> `services/app_runtime/scheduler.py`, `scripts/subscription/*` (except `build_email_assets.py`),
> `stripe` and `apscheduler` - was deleted on 2026-10-06 (Part 2 step 5). This page now describes
> what Flask keeps; the engine's history is in git and in the plan.

## 1. No switch: subscriptions are always on

The dark switch `SUBSCRIPTION_ENABLED` (off unless set; production was to cut over with the
feature dark, 2026-09-18) was **removed on 2026-10-01** in every repo - Minty, minty-onboarding-api,
minty-onboarding-web, minty-payment-request-web, minty-web and minty-subscription-api - because the stack is deployed to
a test site and nothing is dark any more. Its one rule outlives it: **turning the feature on
wrote nothing** - no grant, no trial, no revocation - and taking access away from a module no
subscription backs is still the separate, deliberate `manage.py subscriptions revoke-ungranted
[--apply]` on minty-subscription-api (dry by default). Migration `m1a01` is a no-op for the same
reason. The daily pass keeps its own switch, `SUBSCRIPTION_SCHEDULER_ENABLED` - on
minty-subscription-api only since 2026-10-06 (Flask has no pass any more).

## 2. Module access (always on)

`entity_function` is the catalogue (`PETTY_CASH`, `PAYMENT_REQUEST`), `entity_function_map`
the per-company switches. `blueprints/entity/services/modules.py` (`set_entity_module`, `apply_module_selections`) and the
context processors in
`pettycash/core/hooks.py` (`is_pettycash_enabled`, `is_billing_enabled` — keyed on
`MODULE_BILL`) decide what the side panel, the settings tabs and the dashboard show; a
page of a module that is off renders `entity_no_permission.html` (with a link to the
module settings when the person may open them). The module token minted
for the payment app carries `billing_enabled` / `petty_cash_enabled`, but minty-payment-request-api
re-reads the map (`/api/auth/entitlements`) — the database decides, not the claim.

A billed module cannot be switched off by hand: `set_entity_module` refuses with 409 unless the
caller is the subscription sync, asking `store_ro.module_is_paid` (active, past due, or a PAID
module winding down; a trial or a cancelled trial is free to switch).

## 3. What Flask still does about subscriptions

**Reads, through `blueprints/subscription/services/store_ro.py` only** (the models stay for
Alembic and `models.db`; `tests/test_zz_no_stripe.py` fails if anything else in
`blueprints.subscription.services`, `stripe` or `apscheduler` is imported again):

- `payer_for_entity`, `rows_for_entity`, `entities_paid_for_by`, `pending_transfer_for_entity` -
  the membership guards: the payer cannot be removed, demoted or deactivated, and someone a
  handover is offered to cannot be demoted (`user_management/services/roles.py`,
  `approve_reject_access.py`, the Users tab's subscriber mark in `entity/routes/hub_settings.py`);
- `module_is_paid` - the manual module switch (§2);
- `trial_modules_for_entities` - the entity list's trial badge (`entity/services/entity_list.py`,
  served to minty-web by `GET /api/me/entities`), against the DATABASE's clock, with a six-hour
  closing window for a trial the pass has not closed yet.

**The dashboard notice.** The Petty Cash dashboard shows the subscription notice once per company
per login (`entity/services/modules.py::claim_subscription_notice`, `NOTICE_SEEN_SESSION_KEY`;
`?notice=1` re-shows it in debug). The notice itself comes from minty-subscription-api's
`GET /api/entities/{id}/subscription-notice`, asked server-side by `services/subscription_api.py::
fetch_notice` as the person viewing (a five-minute token Flask mints with the shared `SECRET_KEY`,
naming the person and the company); any failure is no notice, logged. Two kinds: `past_due` and a
paid `pending_cancel`. The button, "Go to subscription settings", is
`minty_web_module_page_handoff` → minty-web's Module page. minty-payment-request-web's landing
page reads the same endpoint itself.

**The doors to minty-web.**
- The **Module tab** (`GET /entity/<co>/settings/modules`) is a **hand-over**: the route mints
  the company's module token and redirects to
  `MINTY_WEB_URL/landing?next=/entity/<shortid>/<name>/settings/modules` (`modules.py::minty_web_company_path`; `/subscription/entities/…/modules` until phase 2) (`tests/test_minty_web_handoff.py`;
  the page's Back returns to wherever the person came from, so nothing is carried). The page is minty-web's (Part 2 step 4a,
  `../minty-web/docs/features/subscriptions.md` §9) and posts its actions to
  minty-subscription-api. Flask's Jinja module page and its 20 session routes were deleted on
  2026-10-01.
- `GET /handoff/minty-web?next=&entity_id=` - login-gated re-entry when minty-web's token lapses
  (a scoped token with `entity_id`, unscoped without; `next` is a path only). The subscription
  emails and the notice link through it.
- `GET /entity/<co>/settings/payment-request` - the Payment Request Settings tab as a URL (the
  redirect `billing_settings_app_url` builds, since only Flask mints the payments-app token;
  `tests/test_settings_payments_redirect.py`).
- Every "open my profile" link goes through `GET /profile` (`entity.open_profile`), always to
  minty-web's My Profile; the payer portal is minty-web's `/subscription/*`.

**Onboarding.** `POST /api/onboarding/modules` (the wizard's Step 2 selection, written to the
map) and `/api/onboarding/invite` + `/invite/cancel` stay here (minty-web's "Invite someone new"
reaches the invite through minty-subscription-api's `core/flask_client.py`). The card, consent and
finalize routes are minty-onboarding-api → minty-subscription-api since 2026-10-06; finalize's
failed trial start now fails finalize and the All Set screen offers Try again.

**Tooling.** `flask modules set|show` (`cli/modules.py`). Scenario replay, the scheduler and every
`subscriptions` command are `manage.py` commands on minty-subscription-api (its
`docs/features/subscriptions-api.md` §8 holds the replay catalogue, Figma 05·A).
`scripts/subscription/build_email_assets.py` stays: it builds the email images
minty-subscription-api ships (`billing/static/email/`).

## Tests

`tests/test_subscription_store_ro.py` (each read over real rows), `tests/test_subscription_notice.py`
(the once-per-login claim, the login id, `fetch_notice`), `tests/test_zz_no_stripe.py` (the
guard), `tests/test_module_access_gate.py` (the gate fails closed),
`tests/test_membership_removal_guards.py`, `tests/test_minty_web_handoff.py` (the Module tab is a
hand-over, and nothing else answers under it); Minty's `e2e/03_settings.spec.ts` reads that
redirect. The ~45 engine test files went with the engine on 2026-10-06; their Django twins are
minty-subscription-api's suite.
