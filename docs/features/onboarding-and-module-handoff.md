# Onboarding and the hand-offs to the other apps

Minty is the hub: it signs people in, and it launches two separate web apps with a
short-lived token — the **onboarding wizard** (`../minty-onboarding-web`, Next.js, backed by
`../minty-onboarding-api`) and the **payment module** (`../minty-payment-request-web`, backed by
`../minty-payment-request-api`). This page is Minty's side; each app documents its own in its
`docs/features/`. The token mechanics are in [authentication.md](authentication.md) §6.

## Launching the wizard

`onboarding_launch_url(user, entity_name=, entity_id=, fresh=)`
(`blueprints/entity/routes/create.py`) builds `<ONBOARDING_WEB_URL>/?token=<jwt>[&entity_id=…][&fresh=1]`:
the token is the 60-minute `scope: "onboarding"` JWT; `entity_id` resumes an in-progress
company; `fresh=1` starts a brand-new one (what `GET /entity/create` sends). Invitations
land on the wizard's `/auth` page the same way (with the invite token instead).

## `/api/onboarding/*` — served by two backends, same paths

Every wizard call is under `/api/onboarding/`. **Both** Minty (`blueprints/entity/routes/create.py`)
and `minty-onboarding-api` answer the same paths byte for byte; the wizard's
`lib/apiRoutes.ts` lists which paths go to Django — a move is one line there. Today Django
serves them all, and roughly two-thirds are thin proxies back to Flask for the things
only one service may do (Stripe, Xero tokens, subscription writes). Auth on both sides is
the onboarding JWT (Flask reads `entity_id` from the query or body; no `X-Entity-Id`
header). The endpoints, in wizard order:

| Step | Endpoints |
|---|---|
| reference | `server-time` (HK "today", server-authoritative), `currencies`, `countries` |
| resume | `state` (everything saved so far, `saved_step`, `current_step`), `saved-step` (Save & Exit) |
| 1 Basic | `create`, `entity/<id>` (edit an in-progress company) |
| 2 Modules | `modules`, `plans`, the billing routes `payment-method*`, `billing/*`, `billing/authorize` |
| 3 Invite | `invite` (GET/POST), `invite/cancel` |
| 4 Accounting | Xero connect is Minty's `/xero_connect` with the entity in the state; `xero/disconnect` |
| 5–7 Petty cash | `sales-methods`, `opening-balance`, `account-codes`, `contacts`, `contacts/create` |
| 8 Bills | `bill-codes` |
| 9 All Set | `finalize` — flips the company live (`status`), enables the chosen modules and starts their card-free trials (`trial_end` in the answer; null when none could be started) |

**Arriving on step 9 finalizes** (the wizard calls it on arrival, the screen commits
nothing) — a test must never navigate there directly (`onboarding-step9-finalizes-on-arrival`
note, `minty-onboarding-web/e2e/README.md`).

## Launching the payment module

From the dashboard's module cards: `GET /entity/<id>/modules` (the picker),
`GET /entity/<co>/payment-request` (straight to the bills list). Both mint the 30-minute module JWT
and redirect to `<minty-payment-request-web>/landing?token=&entity_id=&entity_name=&next=&from=`.
The payment app calls minty-payment-request-api with the token as a bearer; minty-payment-request-api verifies
it with the shared secret, re-reads the person's role on the company and the module map,
and asks Minty for a live Xero token when it publishes. Coming back:
`GET /entity/<id>/enter?token=` (re-validates the token, re-establishes the session);
`GET /entity/<id>/billing-relogin` is the legacy "token expired" return;
`GET /api/entity/<id>/subscription-notice` feeds the payment app's landing-page notice.
minty-payment-request-api triggers Minty's Xero syncs through
`POST /api/entities/<id>/billing/sync-*` (JWT-authenticated).

## Configuration

`ONBOARDING_WEB_URL` (the wizard's origin, also the CORS origin Minty stamps on the
`/api/onboarding/*` answers — `blueprints/shared/bearer_api.py`), `PAYMENT_REQUEST_WEB_URL` (the
payment app), `PETTY_CASH_URL` (Minty's own absolute URL), `SECRET_KEY` shared with the
Django APIs. On the apps' side `PETTY_CASH_URL` points back at Minty (see
`minty-production-host-topology` for the apex/www trap). Every service's variables:
[`docs/ENVIRONMENT.md`](../ENVIRONMENT.md).

## Tests

`tests/test_onboarding_*.py` (launch, CSRF exemption, module state, plans, payment
method — the API through Flask), `tests/test_billing_relogin_handback.py`; the two Next suites
end to end
(`minty-onboarding-web/e2e`, `minty-payment-request-web/e2e`) with the tokens minted from the shared secret.
