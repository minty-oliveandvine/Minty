# Authentication and access — how a person gets in, and what they may touch

This is the system-wide description. Minty (Flask) is the only issuer of identity: every
other service — `minty-payment-request-api`, `minty-onboarding-api`, `minty-payment-request-web`, `minty-onboarding-web` —
verifies what Minty minted and never signs anyone in itself. Each of those repos has a
`docs/features/authentication.md` that covers its own half and links back here.

## 1. Identities

One `user` row per person (`blueprints/auth/models/user.py`). The columns that matter:

| Column | Meaning |
|---|---|
| `username` | the email address — every sign-in path keys on it (`func.lower(username)`) |
| `password` | Werkzeug hash; **empty/random for passwordless users** (OTP or Xero sign-ups) |
| `approved` | sign-up gate; a user that is not approved cannot sign in |
| `system_role` | `normal` / `admin` / `superadmin` (`blueprints/shared/enums.SystemRole`); the code still calls the last one *superuser* (`services/permission_policy.SystemRole.SUPERUSER`) |
| `xero_email` | the Xero-side identity when the account was created or linked through Xero |
| `signed_in_at`, `last_seen_at` | presence stamps (section 8) |

Membership of a company is a `user_entity` row: `(user_id, entity_id, role, approved)`.
The entity roles, lowest to highest: `entity_base` → `cashier` → `shop_manager` →
`accountant` → `admin` → `super_admin` (`services/permission_policy.Role`, with the
`ROLE_ALIASES` map for the older spellings such as `client` and `super admin`).

## 2. The four ways in

All four end in Flask-Login's `login_user()`; the session is the same afterwards.

**The sign-in PAGE is minty-web's `/login` since phase 2 (2026-10-05)** - log in and invitations
(`?invite=&email=&fn=&ln=`); **sign-up is its own page, `/signup`** (2026-10-09), with the code on `/login/confirm`
(`minty-web/features/auth`, its `docs/features/authentication.md`). Until then they were Flask's
`/` (`templates/login/index.html`) and `/register` (`register.html`) plus minty-onboarding-web's
`/auth` + `/auth/confirm`; those pages are deleted, and `/register` and onboarding's `/auth*` only
forward. Flask stays the identity behind the page (2.2-2.4) and every way TO it goes through
`blueprints/auth/services/hub_login.hub_login_url`: the front door `GET /` (Flask-Login's
`login_view`, so every `login_required` redirect), `/register`, an invitation link, Xero's
wrong-account bounce. It keeps `next` when it is a path on this site (`safe_internal_path`) and
drains the flashes into a signed `?flash=` (the entity list's `hub-flash` hand-over,
`services/entity_list.sign_notices`), which the page reads back from the public
`GET /auth/notices`. Flask-Login's "Please log in to access this page." is category `info`.

### 2.1 Email + password — `POST /login`
`blueprints/auth/routes/login.py`. Looks the user up by `username`, refuses an unapproved
account, checks the hash. Superusers land on `/admin`, everyone else on `/index`.

### 2.2 Email OTP — the passwordless path (also the sign-up path)
`blueprints/auth/routes/email_auth.py` + `blueprints/auth/services/email_auth.py`:

1. Is this address known? Asked by `POST /auth/email/request-code` itself in login mode
   (`mode: "login"`): an unknown address is refused **before** a code is sent (404 "Please sign
   up first"), by the same rule verify signs in by - `identity.resolve_user_by_email`
   (`user.email` or `user.xero_email`). Until 2026-10-05 the gate read `user.username` and the
   `email_otp` table, so an account only Xero could resolve was refused;
   `tests/test_otp_identity_gate.py` pins the rule. (`POST /auth/email/check` served only
   Flask's login page and went with it.)
2. `POST /auth/email/request-code` — a 6-digit code, valid **60 s**, resend cooldown 60 s.
   Failed attempts are carried forward across resends (`email_otp.attempts`); at 5 the
   address is locked for **15 minutes** (HTTP 429, `ERR_LOCKED`). The lock is anchored to the
   row's `created_at` and clears itself. A code whose email fails to send is rolled back and
   the request answers 400, so the user can retry at once.
3. `POST /auth/email/verify-code` — a correct code either signs the existing user in, or —
   for a new address that came with a first and last name — creates the passwordless user
   on the spot (`_create_passwordless_user`), recording terms consent with source
   `signup_otp`, or `signup_invite` when an invitation token rode along (section 2.4). A new
   address with no name answers 404 "please sign up". Either way the answer carries a
   hand-off URL (step 4), with the page's `next` signed into it. (A separate "choose a username" step, `POST /auth/email/complete`,
   had no client and was deleted on 2026-10-01.)
4. `GET /auth/email/handoff` — the same-origin landing after a cross-origin verify: the
   sign-in page talks to Flask from another origin, so the verify answer carries a
   short-lived signed hand-off URL (`_HANDOFF_SALT`) that sets the cookie on Minty's origin,
   then goes to the signed `next` when it is a path on this site (checked again), else
   `/admin` or `/index` (`tests/test_hub_sign_in.py`).

The mail goes out through Flask-Mail on Brevo SMTP (`SMTP_URL` / `MAIL_FROM` in `.env`); every
SMTP step times out after the URL's `?timeout=` seconds (10), so a stalled server fails the send - the
code request's open transaction included - instead of hanging it (`services/app_runtime/mail.py`).

### 2.3 Sign in with Xero — `GET /xero_auth`
`blueprints/xero/routes/routes.py::xero_auth`. Plain OpenID Connect against Xero with
scope `openid profile email offline_access` and `prompt=login`; the state is `auth` (or
`auth:invite:<token>`). The callback (`/callback`) reads the email out of the id_token,
resolves the user (`blueprints/auth/services/identity.resolve_user_by_email`) or creates a
passwordless one with the Xero name, and signs them in. **This is identity only** — the
company's Xero *connection* is a different flow with different scopes (`/xero_connect`,
see [xero-integration.md](xero-integration.md)).

### 2.4 Invitation
`blueprints/invitation/`: someone sends an invite from the company's Users tab (minty-web;
`POST /api/me/company/invitations`, `entity/routes/hub_settings.py`), the
email link `GET /invitation/accept/<token>` bounces to the sign-in page (`hub_login_url`)
with the token, the invited address and the inviter's names; the OTP or Xero sign-in then carries it (`invite=` / state
`auth:invite:`), the user is created if needed, the invitation is accepted and the
`user_entity` row written. `POST /legal/invite-terms-status` (the invite token in the JSON
body, never the URL) tells the sign-up screen whether that person still owes terms consent.
The sign-in page clears the invite from its address bar on arrival and hands it to
`/login/confirm` in sessionStorage, not the query string. Pending invites can be listed, resent and
cancelled from the company's Users tab (minty-web, phase 2).

### Sign-up with approval (legacy)
`GET/POST /register` creates nothing - it forwards to the hub's `/signup` (phase 2; the address
was `/login?mode=signup` until 2026-10-09 - `hub_login_url(mode="signup")` builds it, so the mode
is the PATH and never a query parameter), and sign-up runs through the OTP path above. The approval gate remains for older
accounts that were never approved (`POST /approve_user/<id>` / `reject_user` on the
`/admin` list).

Password reset is the legacy `/login` page's "Forgot Password?" modal:
`POST /reset_password` stores a `uuid4()` in `user.reset_token` with a 1-hour
`reset_token_expiry` and emails a link to `/reset_password/<token>`, which sets the new
password and clears both columns (`blueprints/auth/routes/password_reset.py`). The address
is matched case-insensitively on `email` or `username`, and known or not it gets the same
neutral flash, so the form cannot be used to find out who has an account; the link is built
on `PETTY_CASH_URL` (the request host when that is unset).

### Email input: English only
Every typed email address is printable ASCII (0x21-0x7E) and nothing else (2026-10-01).

- **The fields** are `type="text" inputmode="email" … data-email-ascii`, not `type="email"`:
  the browser's email input refuses Hangul before the "@" but takes it after, as an
  international domain, and hands `.value` back as punycode (`xn--…`), so no script could
  see it. `static/js/email_input.js` (minty-web `lib/emailInput.ts`'s twin) strips anything
  else as it is typed (after an IME composition ends), keeps the caret, and shows "Email can
  only contain English letters, numbers and symbols." under the field; the pages check the
  shape with `MintyEmail.isEmail`. The fields: the legacy `/login` reset modal, the Users
  tab's invite, `/entity/create` and the sidebar's My Profile - and minty-web's `/login`
  (sign-in and sign-up, `lib/emailInput.ts`).
- **The server** refuses one loudly in the same words (`blueprints/shared/email_rules.py`):
  `POST /auth/email/request-code` 400 (login mode too, before its 404), the invite
  (`/api/me/company/invitations`, `/api/onboarding/invite`) 400 - an invite's address must also
  be an address with no markup (`invite_address_error`) - the business email
  (`/api/onboarding/create`, `PUT /api/onboarding/entity/<id>`, the `/entity/create` form) 400,
  and My Profile (`PATCH /api/me/profile`) 422. The onboarding billing email and the payer
  portal's invite-admin are minty-subscription-api's since 2026-10-06 (it refuses them there).
- Stored addresses are not rewritten.

## 3. The session

Server-side sessions: `SESSION_TYPE=sqlalchemy`, table `sessions` in the application
schema (`SESSION_SQLALCHEMY_SCHEMA = SCHEMA`), lifetime **24 hours**
(`PERMANENT_SESSION_LIFETIME`), cookie `HttpOnly`, `SameSite=Lax`
(`services/app_runtime/legacy/bootstrap.py`). CSRF is Flask-WTF's `CSRFProtect` on every
form and JSON POST unless a route is explicitly exempted (the onboarding API and the
internal token endpoint are; `tests/test_char_*` post with the token).

There is **no idle logout** any more (the backstop was removed in C10); `last_activity` is
only reset at login. What "still here" means for the Users tab is section 8.

`pettycash/core/hooks.py` runs three request hooks:
- `before_request_middleware` — a cookie that names a user Flask-Login cannot load is
  cleared (otherwise the redirect target is guarded by the same check: an infinite loop).
- `block_readonly_superuser_writes` — a superuser with no membership on the target company
  can read but not write (section 5).
- `after_request_middleware` — silently refreshes an expired Xero access token for the
  signed-in user (section 7).

`GET /logout` clears the Xero token from the session, calls `logout_user()` and stamps
`signed_in_at = NULL` (`services/user_presence.mark_signed_out`).

The session cookie is `Secure` everywhere but local development (`APP_ENV=development`,
plain http): `SESSION_COOKIE_SECURE = not is_development()`.

### 3.1 Redirects and response headers (the URL security round, 2026-10-05)

- **Redirect targets.** Every redirect to a value the request supplied - `?next=` on
  `/entity/<id>/enter`, `/handoff/minty-web` and `/xero_auth` (checked when stored AND when
  popped after the Xero round trip), the Terms gate's remembered page, the "back where you
  came from" Referer redirects in `hooks.py` - goes through ONE rule,
  `blueprints/shared/safe_redirect.py`: a path on this site, no `//host`, no backslash, no
  control character (browsers drop tab/CR/LF, so `/%09/evil.com` arrived as `//evil.com`), no
  `..`, nothing `urlsplit` reads as a scheme or host. The Next apps share the same rule as
  `lib/safeNext.ts` (minty-web; copied in minty-payment-request-web).
- **Headers** (`pettycash/core/http_hardening.py`, on every response): `Referrer-Policy:
  same-origin` (not `no-referrer`: `WTF_CSRF_SSL_STRICT` needs a same-origin Referer on HTTPS
  form posts), `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, HSTS outside
  development, and `Cache-Control: no-store` on any page whose path holds a secret
  (`/reset_password/<token>`, `/invitation/accept/<token>`, share links). The three Next apps
  send the same set from `next.config.ts` (`frame-ancestors 'self'` instead of a full CSP).
- **Logs never hold a secret from an address.** gunicorn's access log (it printed the whole
  request line) is off in the `Procfile`; `http_hardening` logs `METHOD path status ms` with
  the query string dropped and secret path segments shown as `[redacted]`. The Datadog
  browser logs send `origin + path` only (`static/js/datadog-logs.js`, also scrubbing the
  SDK's own `view.url`/`view.referrer`), and a share-link path as `/Minty_Report/[redacted]`.
  Loguru's `diagnose` (variable values in tracebacks) is on in development only, and the Xero
  token refresh no longer logs its Basic `Authorization` header.
- **No state change by GET**: publishing to Xero, disconnecting Xero (a CSRF-checked form
  POST since 2026-10-05) and the invite Terms check (`POST`, the token in the body) all refuse
  GET.
- **Still open** (recorded, not built): the five-minute `/auth/email/handoff?h=` token can be
  replayed inside its window (single use needs a store - a schema change); the Xero OAuth
  `state` carries no per-session nonce (login CSRF); `/logout` and `/leave-entity` are GETs;
  tokens still ride in query strings between the apps (a one-time-code exchange would end
  that - also a schema change).

### 3.2 Addresses: `/entity/<shortid>/<name>/...` (2026-10-05)

Every company page hangs off **`<co>` = `<shortid>/<name>`**: the first 8 characters of the
company's id, then its name as a readable segment, e.g. `/entity/360812e1/harbour-and-vine-limited`.
The short id decides; the name is only for reading (`blueprints/shared/entity_ref.py`):

- **The converter** (`<entity:...>` in a rule) matches `<shortid>/<name>` or a full uuid and resolves
  it to the uuid as the address is matched, so guards and views receive exactly what they did
  before. **A GET whose address used a full uuid, an old name or capitals is 308'd to the canonical
  one** (query kept) - a rename never breaks a link, and the other apps, which know only uuids, link
  `/entity/<uuid>/...` and let Flask show the readable form.
- **An unknown company is not a 404 there**: it resolves to the nil uuid and the usual sign-in, Terms
  and membership checks answer, so an address tells a stranger nothing about which short ids exist.
  Two companies sharing a short id are told apart by name, else logged and treated as unknown.
- **Slug** (`slugify_name`, mirrored by minty-web's `lib/companyRef.ts`): lowercase, `&` -> "and",
  letters and digits of any script kept, anything else one `-`, 60 characters, `company` when empty.
  No schema change: nothing is stored.
- **The scheme:**

  | Page | Address |
  |---|---|
  | Dashboard | `/entity/<co>/petty-cash` (the bare `/entity/<co>` redirects there) |
  | Report history, CSV | `/entity/<co>/petty-cash/reports`, `/petty-cash/reports/download-csv` |
  | Wizard step | `/entity/<co>/petty-cash/reports/new/<step>`, `/entity/<co>/petty-cash/reports/<report_id>/<step>` (`opening`, `sale`, `expense`, `deposit`, `cash-count`, `ending`, `submitted`) |
  | Resume; summaries | `/entity/<co>/petty-cash/reports/resume`; `/petty-cash/reports/summary` (by day), `/petty-cash/reports/<report_id>/summary` |
  | Settings tabs | `/entity/<co>/settings/users`, `/integration`, `/petty-cash`, `/modules` (minty-web), `/payment-request` (the payments app) |
  | Hand-overs | `/entity/<co>/enter`, `/payment-request`, `/modules`, `/xero-not-connected` |

  Module names are `petty-cash` and `payment-request` (the user's call). minty-web's company pages are
  `/entity/<shortid>/<name>/…` too (the module page `…/settings/modules` since phase 2), and the payments app's pages are
  `/entity/<shortid>/<name>/payment-request[/<id>]` and `/settings/payment-request` on its origin -
  the hand-overs land there (`billing_app_home_url`; `/payment-request?request=<id>` lands on one
  request), and its middleware sends another company's page back here
  (`minty-payment-request-web/docs/features/authentication.md`).
- **Old addresses keep working** (`blueprints/shared/legacy_addresses.py`): each pre-2026-10-05 rule
  308s straight to the readable address (308 keeps a form's method and body). Old `/report/...`
  wizard GETs by a signed-in person move the same way (`report/routes/company_addresses.py`), which
  also refuses (404, logged) a report shown under another company's address. Petty Cash moved
  under its module name the same day (the user's call, matching `/payment-request`): the bare
  `/entity/<co>` and `/entity/<co>/reports[/...]` 308 to `/entity/<co>/petty-cash[/reports/...]`
  (GET and POST, query kept). JSON APIs, OAuth,
  `/profile` and `/handoff/minty-web` keep the uuid.
- Tests: `tests/test_entity_ref.py`; `F.co(app_or_client, entity_id)` gives a company's prefix.

## 4. The terms gate

`blueprints/legal/routes/gate.py::require_terms_acceptance` runs on every request: a
signed-in user who has not accepted the current terms version is redirected to `/entity`
(JSON callers get a JSON 403 instead of a redirect; `/legal/accept` is the standalone fallback).
`/entity` hands the browser to minty-web whether or not terms are owed (always, since phase 2 -
the Jinja list and its panel are gone), and minty-web's own gate draws the panel over every
page of that app, recording through
`POST /api/me/terms/accept` (bearer, `source = "hub"`). The allow-list is keyed on **endpoint
names**, not paths: the legal routes (minty-web's two included), the login/OTP endpoints,
logout and `leave-entity`, static files. Versions, pinning and consent records are in
[legal-terms.md](legal-terms.md).

## 5. Roles and permissions inside Minty

`services/permission_policy.py` is the matrix; `services/authz.py` has the decorators
(`require_entity_access(entity_keys=…)`, `require_permission(Permission.X, entity_keys=…)`)
that read the entity id from the URL, query string or body and answer 403 with the route's
own wording.

- `has_permission(user, permission, entity_id)` resolves the **effective role**: the
  `user_entity.role` (approved), or `super_admin` for a system superuser — but a superuser
  with **no** membership on the company is *read-only* (`is_superuser_readonly`): every
  write route refuses them, and the hook above backs that up for routes that use no
  decorator.
- `PERMISSION_RULES` maps each `Permission` to a minimum role (`READONLY_ALLOWED_PERMISSIONS`
  is what a read-only superuser keeps). The ones people ask about:
  `REPORT_PUBLISH`, `XERO_SETTINGS_UPDATE`, `SALES_METHOD_*`, `COA_*`, `ENTITY_UPDATE` and
  `USER_ROLE_DELETE` need **accountant**; report editing/deleting has an *own* and an
  *entity* variant; `can_view_report` allows the creator or anyone with
  `REPORT_VIEW_ENTITY`.
- The `/admin` pages and `/minty/api/users/create` / `…/<id>/consents` are superuser-only
  (`blueprints/user_management/`); `/minty/api/users/me` is the person's own. A company's members
  are managed per company - minty-web's Users tab over `/api/me/company/*` (each action its
  permission and the rank rule; [entities-and-members.md](entities-and-members.md)).

`tests/test_user_permission_matrix_coverage.py` walks every route and fails when a
state-changing route has no permission check.

## 6. Hand-off tokens — how the other apps know who you are

Minty mints two kinds of HS256 JWT over the **shared `SECRET_KEY`** (the same value must be
set on Minty, minty-payment-request-api, minty-onboarding-api and minty-subscription-api; a mismatch 401s every call — see the
`prod-secret-key-differs-from-local` note).

| Token | Minted by | Lifetime | Claims | Verified by |
|---|---|---|---|---|
| module / billing | `blueprints/entity/routes/modules.py::_generate_module_token` when a person clicks **Payments** (`/entity/<co>/payment-request`, `/entity/<id>/modules`) | 30 min | `user_id`, `entity_id`, `xero_org_id`, `role`, `system_role`, `module: "billing"`, `sid` (the login session id, `LOGIN_SID_SESSION_KEY`), `billing_enabled`, `petty_cash_enabled`, `iat`, `exp` | minty-payment-request-api `core/auth.BearerAuth` |
| onboarding | `blueprints/entity/routes/create.py::_mint_onboarding_token` when the wizard is launched | 60 min | `user_id`, `scope: "onboarding"`, `iat`, `exp` | minty-onboarding-api `core/auth.OnboardingBearerAuth`; Flask's own `/api/onboarding/*` routes |

The browser is sent to `minty-payment-request-web` `/landing?token=…&entity_id=…&entity_name=…`,
which stores the token in the `billing_token` cookie (8 hours; minty-payment-request-api
`POST /api/auth/token/refresh` re-mints it before it lapses) and to the onboarding app
with `?token=…`. minty-web (the hub, Part 2) is entered the same way through its `/landing`,
and comes back for a fresh token through `GET /handoff/minty-web?next=&entity_id=` (login-gated,
`entity/routes/modules.py`). Its entity list and My Profile read Flask's **hub surface**
(`blueprints/shared/hub_api.py`: `GET /api/me/entities`, `GET`/`PATCH /api/me/profile`) with that
token — bearer only, and a token naming an unknown or switched-off (`approved` false) account is
refused like a bad one. Its CORS names the caller when it is `MINTY_WEB_URL` or
`PAYMENT_REQUEST_WEB_URL` (minty-payment-request-web, whose copy of the sidebar's My Profile reads and saves the
same profile since 2026-09-30), minty-web's otherwise. This app's own pages draw that sidebar
too ([sidebar.md](sidebar.md)): `GET /me/sidebar-token` (session, same-origin, `no-store`, a 401
rather than a redirect when signed out) hands the page an unscoped module token, and the page
calls the same routes with it. The profile's header avatar and the sidebar open My Profile in
place; the avatar's `href` - `GET /profile?entity_id=&from=` (`modules.py::open_profile`) - is
the way in when scripts are off, and still the payments app's old links (its `/profile*`
addresses forward here): it mints the token at the click and hands over to minty-web's My Profile
- always, since minty-payment-request-web's profile page was deleted on 2026-10-01. Coming back is `GET /entity/<id>/enter?token=…` (re-validates the JWT and
re-establishes the Flask session). Since 2026-10-05 it takes a **module** token only (`module`
claim = `MODULE_TOKEN_CLAIM`; the onboarding token is refused) and signs in only a member of
`<id>` (or a superuser); before that ANY token signed with the key - the onboarding one
included - became a session for any company. `billing-relogin` is the legacy "my token ran out"
return. The e2e suites of the two Next apps mint these tokens themselves with the same
secret (their `e2e/README.md` explains why nothing is bypassed by that).

The entitlement claims in the token are a hint only: minty-payment-request-api re-reads
`entity_function_map` (`GET /api/auth/entitlements`) and the DB decides what the module
shows.

## 7. Xero OAuth tokens (the company's accounting connection)

Different thing from sign-in: a **per-user** `user_token` row (access token, refresh token,
expiry) obtained when that user connects a company to Xero (`/xero_connect`, scopes in
`tests/test_xero_scopes.py`). The company remembers who connected it
(`entities.connected_by_user_id`), and that is whose token every publish uses:

- `services/auth/token_service.resolve_xero_token(entity_id, current_user)` — the
  connector's token first, the current user's own as a logged fallback, else `None` (the
  UI shows *Reconnect*).
- **Only Flask refreshes.** Xero rotates the refresh token on every use and invalidates the
  old one, so two refreshers brick the connection. Refreshes are serialised per bearer with
  a Postgres advisory lock held across the HTTP call (`_xero_refresh_lock`), and the
  `after_request` hook refreshes an expired access token silently on normal traffic.
- minty-payment-request-api never refreshes: when its stored copy is expired it calls
  `POST /api/internal/xero/token` with a 60-second assertion JWT (`scope:
  xero-access-token`, `entity_id` in the **signed claims**, never the body) and gets a live
  access token back; 409 means "reconnect required". Its `PETTY_CASH_URL` must point at the
  Minty host (the token URL is derived from it: `PETTY_CASH_URL/api/internal/xero/token`).
- Tokens are never logged: `tests/test_zz_no_token_logging.py` fails any logger f-string
  that formats a value named like a token.

## 8. Who is signed in (presence)

`services/user_presence.py`: `signed_in_at` is stamped at login, `last_seen_at` at most
once a minute on real traffic (`SEEN_REFRESH_SECONDS`). "Signed in" means seen in the last
30 minutes (`DEFAULT_PRESENCE_WINDOW_SECONDS`, or `IDLE_TIMEOUT_SECONDS` when set). Nothing
shows the list now: the Users tab's "Online Users" section was switched off, and its poll
(`/entity/settings/users/<id>/presence`, `PRESENCE_INERT_ENDPOINTS`) went with Flask's Users
page in phase 2 (2026-10-05);
minty-payment-request-api's `POST /api/auth/logout` clears the stamps the same way, so leaving from
the payment module counts as leaving.

## 9. Configuration

| Variable | Used for |
|---|---|
| `SECRET_KEY` | sessions, CSRF, both hand-off JWTs, the internal token assertion — **shared with the three Django APIs** |
| `SESSION_TYPE`, `SESSION_SQLALCHEMY_TABLE` | server-side sessions (`sqlalchemy`, `sessions`) |
| `SMTP_URL`, `MAIL_FROM` | OTP, invitation and reset mail |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET` | both OAuth flows (redirect URI `PETTY_CASH_URL/callback`) |
| `PETTY_CASH_URL` | absolute links in mail and hand-offs, and the Xero redirect URI |
| `MINTY_WEB_URL`, `PAYMENT_REQUEST_WEB_URL` | minty-web's and minty-payment-request-web's origins - the hand-offs, and the hub routes' CORS |
| `SUBSCRIPTION_API_URL` | minty-subscription-api, read from the browser by the sidebar's Subscriptions Overview (default `http://localhost:8000`) |
| `IDLE_TIMEOUT_SECONDS` | the presence window (there is no idle logout) |

Every service's variables are listed in [`docs/ENVIRONMENT.md`](../ENVIRONMENT.md).

## 10. Where it is tested

`tests/test_auth_register_login.py`, `tests/test_login_flash_drain.py` and
`tests/test_xero_login_flash_drain.py` (the sign-in paths), `tests/test_password_reset.py`
(the reset email, the neutral answer, expired and spent links), `tests/test_terms_signup_consent.py`
(OTP sign-up, invite tokens, consent sources),
`tests/test_authz_decorators.py`, `tests/test_user_permission_matrix_coverage.py` (every
write route has a check), `tests/test_terms_gate.py`, `tests/test_invitation*.py`,
`tests/test_billing_relogin_handback.py` (the return from the payment module),
`tests/test_xero_scopes.py` (connect and reconnect request the same minimal scope set),
`tests/test_zz_no_token_logging.py`, `tests/test_url_security.py` (the redirect rule, `/enter`'s
token and membership checks, the headers, the redacted access log, GET refusals, the deleted
routes, the download and export guards), `tests/test_sidebar.py` (`/me/sidebar-token`, the hub's two
origins), `tests/test_email_english_only.py` (every path refuses a non-English address); in the browser, `e2e/01_login.spec.ts` (login, wrong
password, the terms modal on first sign-in) and the two Next suites' hand-off specs.
