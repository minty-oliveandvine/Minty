# Authentication and access — how a person gets in, and what they may touch

This is the system-wide description. Minty (Flask) is the only issuer of identity: every
other service — `billing-backend`, `onboarding-backend`, `billing-frontend`, `onboarding` —
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

### 2.1 Email + password — `POST /login`
`blueprints/auth/routes/login.py`. Looks the user up by `username`, refuses an unapproved
account, checks the hash. Superusers land on `/admin`, everyone else on `/index`.

### 2.2 Email OTP — the passwordless path (also the sign-up path)
`blueprints/auth/routes/email_auth.py` + `blueprints/auth/services/email_auth.py`:

1. `POST /auth/email/check` — is this address known? (`user.username`, then the `email_otp`
   table). In login mode an unknown address is refused **before** a code is sent — see
   `minty-otp-identity-gate` in the notes: the check reads only `User.username`, so an
   account that only Xero could resolve gets "Please sign up first".
2. `POST /auth/email/request-code` — a 6-digit code, valid **60 s**, resend cooldown 60 s.
   Failed attempts are carried forward across resends (`email_otp.attempts`); at 5 the
   address is locked for **15 minutes** (HTTP 429, `ERR_LOCKED`). The lock is anchored to the
   row's `created_at` and clears itself. A code whose email fails to send is rolled back and
   the request answers 400, so the user can retry at once.
3. `POST /auth/email/verify-code` — a correct code either signs the existing user in, or —
   for a new address — returns a signed sign-up token (`itsdangerous`, 15 minutes) that
   `POST /auth/email/complete` spends to create the passwordless user
   (`_create_passwordless_user`), recording terms consent with source `signup_otp`, or
   `signup_invite` when an invitation token rode along (section 2.4).
4. `GET /auth/email/handoff` — the same-origin landing after a cross-origin verify: the
   onboarding app talks to Flask from another origin, so the verify answer carries a
   short-lived signed hand-off URL (`_HANDOFF_SALT`) that sets the cookie on Minty's origin.

The mail goes out through Flask-Mail on Brevo SMTP (`MAIL_*` / `BREVO_EMAIL` in `.env`).

### 2.3 Sign in with Xero — `GET /xero_auth`
`blueprints/xero/routes/routes.py::xero_auth`. Plain OpenID Connect against Xero with
scope `openid profile email offline_access` and `prompt=login`; the state is `auth` (or
`auth:invite:<token>`). The callback (`/callback`) reads the email out of the id_token,
resolves the user (`blueprints/auth/services/identity.resolve_user_by_email`) or creates a
passwordless one with the Xero name, and signs them in. **This is identity only** — the
company's Xero *connection* is a different flow with different scopes (`/xero_connect`,
see [xero-integration.md](xero-integration.md)).

### 2.4 Invitation
`blueprints/invitation/`: an admin sends an invite (`POST /minty/api/invitation/send`), the
email link `GET /invitation/accept/<token>` bounces to the onboarding app's `/auth` page
with the token; the OTP or Xero sign-in then carries it (`invite=` / state
`auth:invite:`), the user is created if needed, the invitation is accepted and the
`user_entity` row written. `GET /legal/invite-terms-status` tells the sign-up screen
whether that person still owes terms consent. Pending invites can be listed, resent and
cancelled from the entity's Users tab.

### Sign-up with approval (legacy)
`GET/POST /register` no longer creates an account — a plain form POST only re-renders the
page, and sign-up runs through the OTP path above. The approval gate remains for older
accounts that were never approved (`POST /approve_user/<id>` / `reject_user` on the
`/admin` list).

Password reset is the legacy `/login` page's "Forgot Password?" modal:
`POST /reset_password` stores a `uuid4()` in `user.reset_token` with a 1-hour
`reset_token_expiry` and emails a link to `/reset_password/<token>`, which sets the new
password and clears both columns (`blueprints/auth/routes/password_reset.py`). The address
is matched case-insensitively on `email` or `username`, and known or not it gets the same
neutral flash, so the form cannot be used to find out who has an account; the link is built
on `PUBLIC_URL` (the request host when that is unset).

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

## 4. The terms gate

`blueprints/legal/routes/gate.py::require_terms_acceptance` runs on every request: a
signed-in user who has not accepted the current terms version is redirected to `/entity`,
whose acceptance panel is a modal over the Select Company list (JSON callers get a JSON 403
instead of a redirect; `/legal/accept` is the standalone fallback). With `MINTY_WEB_HUB` on,
`/entity` hands the browser to minty-web whether or not terms are owed, and minty-web's own
gate draws the same panel over every page of that app, recording through
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
- The `/admin` pages and `/minty/api/users/*` are superuser-only
  (`blueprints/user_management/`).

`tests/test_user_permission_matrix_coverage.py` walks every route and fails when a
state-changing route has no permission check.

## 6. Hand-off tokens — how the other apps know who you are

Minty mints two kinds of HS256 JWT over the **shared `SECRET_KEY`** (the same value must be
set on Minty, billing-backend and onboarding-backend; a mismatch 401s every call — see the
`prod-secret-key-differs-from-local` note).

| Token | Minted by | Lifetime | Claims | Verified by |
|---|---|---|---|---|
| module / billing | `blueprints/entity/routes/modules.py::_generate_module_token` when a person clicks **Payments** (`/entity/<id>/bills`, `/entity/<id>/modules`) | 30 min | `user_id`, `entity_id`, `xero_org_id`, `role`, `system_role`, `module: "billing"`, `sid` (the login session id, `LOGIN_SID_SESSION_KEY`), `billing_enabled`, `petty_cash_enabled`, `iat`, `exp` | billing-backend `core/auth.BearerAuth` |
| onboarding | `blueprints/entity/routes/create.py::_mint_onboarding_token` when the wizard is launched | 60 min | `user_id`, `scope: "onboarding"`, `iat`, `exp` | onboarding-backend `core/auth.OnboardingBearerAuth`; Flask's own `/api/onboarding/*` routes |

The browser is sent to `billing-frontend` `/landing?token=…&entity_id=…&entity_name=…`,
which stores the token in the `billing_token` cookie (8 hours; billing-backend
`POST /api/auth/token/refresh` re-mints it before it lapses) and to the onboarding app
with `?token=…`. minty-web (the hub, Part 2) is entered the same way through its `/landing`,
and comes back for a fresh token through `GET /handoff/minty-web?next=&entity_id=` (login-gated,
`entity/routes/modules.py`). Its entity list and My Profile read Flask's **hub surface**
(`blueprints/shared/hub_api.py`: `GET /api/me/entities`, `GET`/`PATCH /api/me/profile`) with that
token — bearer only, and a token naming an unknown or switched-off (`approved` false) account is
refused like a bad one. Its CORS names the caller when it is `MINTY_WEB_URL` or
`FRONTEND_APP_URL` (billing-frontend, whose copy of the sidebar's My Profile reads and saves the
same profile since 2026-09-30), minty-web's otherwise. This app's own pages draw that sidebar
too ([sidebar.md](sidebar.md)): `GET /me/sidebar-token` (session, same-origin, `no-store`, a 401
rather than a redirect when signed out) hands the page an unscoped module token, and the page
calls the same routes with it. The profile's header avatar and the sidebar open My Profile in
place; the avatar's `href` - `GET /profile?entity_id=&from=` (`modules.py::open_profile`) - is
the way in when scripts are off, and still the payments app's old links: it mints the token at
the click and picks the profile, minty-web's while `MINTY_WEB_HUB` is on, billing-frontend's
otherwise. Coming back is `GET /entity/<id>/enter?token=…` (re-validates the JWT and
re-establishes the Flask session) — `billing-relogin` is the legacy "my token ran out"
return. The e2e suites of the two Next apps mint these tokens themselves with the same
secret (their `e2e/README.md` explains why nothing is bypassed by that).

The entitlement claims in the token are a hint only: billing-backend re-reads
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
- billing-backend never refreshes: when its stored copy is expired it calls
  `POST /api/internal/xero/token` with a 60-second assertion JWT (`scope:
  xero-access-token`, `entity_id` in the **signed claims**, never the body) and gets a live
  access token back; 409 means "reconnect required". Its `XERO_TOKEN_SERVICE_URL` /
  `FLASK_APP_URL` must point at the Minty host.
- Tokens are never logged: `tests/test_zz_no_token_logging.py` fails any logger f-string
  that formats a value named like a token.

## 8. Who is signed in (presence)

`services/user_presence.py`: `signed_in_at` is stamped at login, `last_seen_at` at most
once a minute on real traffic (`SEEN_REFRESH_SECONDS`), never by the Users tab's own
20-second poll (`PRESENCE_INERT_ENDPOINTS`). The Users tab lists members seen in the last
30 minutes (`DEFAULT_PRESENCE_WINDOW_SECONDS`, or `IDLE_TIMEOUT_SECONDS` when set);
billing-backend's `POST /api/auth/logout` clears the stamps the same way, so leaving from
the payment module counts as leaving.

## 9. Configuration

| Variable | Used for |
|---|---|
| `SECRET_KEY` | sessions, CSRF, both hand-off JWTs, the internal token assertion — **shared across the three backends** |
| `WTF_CSRF_SECRET_KEY` | CSRF (falls back to `SECRET_KEY`) |
| `SESSION_TYPE`, `SESSION_SQLALCHEMY_TABLE` | server-side sessions (`sqlalchemy`, `sessions`) |
| `MAIL_*`, `BREVO_EMAIL` | OTP, invitation and reset mail |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI` | both OAuth flows |
| `PUBLIC_URL` | absolute links in mail and hand-offs |
| `MINTY_WEB_URL`, `FRONTEND_APP_URL` | minty-web's and billing-frontend's origins - the hand-offs, and the hub routes' CORS |
| `BILLING_API_URL` | minty-billing-api, read from the browser by the sidebar's Subscriptions Overview (default `http://localhost:8004`) |
| `IDLE_TIMEOUT_SECONDS` | the presence window (there is no idle logout) |

## 10. Where it is tested

`tests/test_auth_register_login.py`, `tests/test_login_flash_drain.py` and
`tests/test_xero_login_flash_drain.py` (the sign-in paths), `tests/test_password_reset.py`
(the reset email, the neutral answer, expired and spent links), `tests/test_terms_signup_consent.py`
(OTP sign-up, invite tokens, consent sources),
`tests/test_authz_decorators.py`, `tests/test_user_permission_matrix_coverage.py` (every
write route has a check), `tests/test_terms_gate.py`, `tests/test_invitation*.py`,
`tests/test_billing_relogin_handback.py` (the return from the payment module),
`tests/test_xero_scopes.py` (connect and reconnect request the same minimal scope set),
`tests/test_char_subscription_dark.py` (the 404s while subscriptions are dark),
`tests/test_zz_no_token_logging.py`, `tests/test_sidebar.py` (`/me/sidebar-token`, the hub's two
origins); in the browser, `e2e/01_login.spec.ts` (login, wrong
password, the terms modal on first sign-in) and the two Next suites' hand-off specs.
