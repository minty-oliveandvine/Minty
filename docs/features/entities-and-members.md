# Companies (entities) and members

A company is an `entities` row; a person belongs to it through `user_entity`
(`role`, `approved`). Code: `blueprints/entity/` (list, settings, modules, payment
methods), `blueprints/user_management/` (accounts and roles), `blueprints/invitation/`,
`blueprints/auth/routes/leave_entity.py`. Every screen is minty-web's; Flask draws no page
(2026-10-20).

## Select Company and the dashboard

`GET /entity` lists the companies the signed-in person belongs to, with who last opened
each one and when (`entities.last_accessed_by_user_id` / `last_accessed_at`; the how and
its traps are in [entity_last_accessed.md](entity_last_accessed.md)). The list is built once,
in `blueprints/entity/services/entity_list.py::build_entity_list`, for its one reader:

- **minty-web's list** (`/entities`, the hub's "Select Company", 2026-09-29) — `/entity` mints
  an unscoped token and sends the browser there
  (`routes/list.py::_to_minty_web_list`), which reads `GET /api/me/entities`
  (`routes/me_api.py`, bearer + CORS for minty-web through `blueprints/shared/hub_api.py`).
  Each company carries `id`, `name`, `status`, `modules`, `trial_modules`, `trial_module_names`,
  `last_accessed_at`, `last_accessed_by` and, since 2026-10-19, what needs attention: `role` (the
  CALLER's own `user_entity.role` - `entity_base` … `super_admin` - or `"superadmin"` for a
  superuser with no membership there; joined on the caller's id, so nobody else's role leaks),
  `trial_ends_on` (`YYYY-MM-DD`, the earliest end among `trial_modules`, on the company's calendar:
  `entities.timezone`, else Hong Kong, as minty-subscription-api dates its emails) and
  `payment_failed` (a module reads "payment failed" - the rule is in
  [modules-and-subscriptions.md](modules-and-subscriptions.md) §3). Read-only, batched for the
  whole list (`tests/test_hub_entity_list.py` counts the queries). **Whether or not Terms are owed** (since 2026-09-29):
  minty-web's own Terms gate takes the acceptance ([legal-terms.md](legal-terms.md), minty-web's
  panel). Seventy-odd routes flash a message
  and redirect to `/entity`; the redirect drains those flashes, signs them (`itsdangerous`,
  salt `hub-flash`, five minutes) into `?flash=`, and the API hands them back as `notices`, so
  none is lost on the way. A redirect INTO another app (onboarding, minty-web, the payments
  app) drops the queue instead, logging each message (`pettycash/core/hooks.py::drop_flashes_leaving_flask`):
  those apps never show it, and onboarding's Xero connect used to pile one up per attempt that
  the list then toasted all at once when the wizard finished. minty-web must be deployed
  wherever Flask is. A refused browser request (`services/authz.py::_forbidden`) reaches the list
  the same way: its message flashed, then `/entity`.

Clicking one goes
through `GET /entity/<co>/modules` (`routes/modules.py::module_selector`, a router): a company
still onboarding resumes its wizard, someone outside it goes back to the list, one module goes
straight into it, and both go to **minty-web's module choice** (`/entity/<shortid>/<name>`,
with a token scoped to the company - phase 2, 2026-10-05; it was the payments app's
`/module-selection`), whose two doors enter each module through `/entity/<co>/enter`
(`tests/test_module_selector.py`). Opening Petty Cash (`GET /entity/<co>/petty-cash`) hands over
to minty-petty-cash-web's dashboard through `/handoff/petty-cash-web`
([petty-cash-api.md](petty-cash-api.md)). A person with no company is sent to the list.

## Creating a company

`GET /entity/create` no longer renders a form: it launches the **onboarding wizard**
(`onboarding_launch_url(user, fresh=True)`) — the wizard's Step 1 creates the row through
`POST /api/onboarding/create`, Xero, sales methods, account codes, invitations and modules
follow on its later steps, and minty-onboarding-api's `POST /api/onboarding/finalize` flips the
company from `onboarding` to live and starts its trials through minty-subscription-api (Flask's
finalize was deleted on 2026-10-06; [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md)).
The old WTForms create form (`POST /entity/create`) and its `/entity/success` page were deleted on
2026-10-20.

## Settings (`/entity/<id>/settings/…`)

Flask draws no tab (2026-10-20); each app keeps its own settings. **Users, Entity & Integration
and Module are minty-web's** (`/entity/<shortid>/<name>/settings/<tab>`,
`minty-web/docs/features/company-settings.md`); **Petty Cash Settings is minty-petty-cash-web's**
(`/entity/<shortid>/<name>/settings/petty-cash`, over minty-petty-cash-api;
[petty-cash-settings.md](petty-cash-settings.md)). Flask's addresses stay as HAND-OVERS: the
minty-web tabs through `routes/settings.py::_to_hub_tab` (a company-scoped token, and whatever was
flashed on the way signed into `?flash=`, plus `?xero_conflict=` when a connect was refused
because another company holds the organisation; the Xero reconnect's outcome reaches the tab
that way), Petty Cash Settings through `/handoff/petty-cash-web`. minty-web's tabs work over
Flask's bearer routes `/api/me/company/*` (`routes/hub_settings.py`, below).

| Tab | Route | What it edits | Who |
|---|---|---|---|
| Entity & Integration | minty-web; `GET /entity/<co>/settings/integration` hands over. Reads `GET /api/me/company/integration`, saves `PATCH` (name / `country_code` / `currency_id`), `POST /api/me/company/xero/disconnect`, `POST /api/me/company/xero/release` (free another company's Xero organisation - authorized on THAT company; [xero-integration.md](xero-integration.md) §1.1) | the company name, country & currency, the Xero connection ([xero-integration.md](xero-integration.md)) | read `XERO_SETTINGS_VIEW` (cashier+); save `XERO_SETTINGS_UPDATE` (accountant+); rename `ENTITY_RENAME` (admin) |
| Petty Cash Settings | minty-petty-cash-web; `GET /entity/<co>/settings/petty-cash` hands over (`COA_VIEW`, Petty Cash on only) | country & currency, the Xero account mapping, the sales settlement methods, the petty-cash account codes ([petty-cash-settings.md](petty-cash-settings.md)) | `ENTITY_UPDATE` / `COA_UPDATE` / `COA_CREATE` / `COA_DELETE`, checked by the API |
| Users | minty-web; `GET /entity/<co>/settings/users` hands over. Reads `GET /api/me/company/users` | members with role, who pays for the company (the billing-group payer, looked up separately from the role), pending invitations; per row whether this person may change the role / remove | read `USER_VIEW_ALL` and invite `USER_INVITE` (shop manager+); change a role `USER_ROLE_ASSIGN` (shop manager+); remove `USER_ROLE_DELETE` (accountant+) - each also the rank rule below |
| Module | `GET /entity/<co>/settings/modules` | a hand-over to minty-web's Module page ([modules-and-subscriptions.md](modules-and-subscriptions.md)) | `MODULE_VIEW` |

Renaming the company is reflected in the header at once - minty-web's Entity & Integration tab
(its `features/company-settings/e2e/12_company_settings.spec.ts`; the API's rules are
`tests/test_hub_company_settings.py`).

## Members, roles, invitations

- Roles and what they allow: [authentication.md](authentication.md) §1 and §5.
- The routes (bearer, minty-web's Users tab - `blueprints/entity/routes/hub_settings.py`; the
  session `/minty/api/invitation/*` and `/minty/api/users/<id>[/role]` routes went in phase 2):
  the company comes from `?entity=` ALONE and must be the person's (`profile.entity_context`) -
  the session PATCH read it from the query for its check and from the body for its write.
  `PATCH /api/me/company/users/<id>` `{role}` changes a role; `DELETE` removes, through the
  guards in order: rank 403 → the payer 409 → the last admin 409 → a pending handover's nominee
  409 (`services/roles.py`). The payer guard reads `store_ro.entities_paid_for_by`, which asks
  for rows naming this person — so since 2026-10-08 a company whose trial has no SUBSCRIBER
  (`payer_user_id` NULL; starting a trial no longer establishes one) does NOT block removing
  the admin who started it. Correct: they carry no bill. The guard still fires the moment
  somebody confirms billing. Roles are the four assignable ones only (`enums.ASSIGNABLE_ENTITY_ROLES`,
  400 otherwise); the rank rule (`can_manage_role_assignment_for_entity`) allows a role AT or
  below your own. **Names are not changed here** - a person edits their own in My Profile (the
  session PATCH renamed anyone).
- Inviting: `POST /api/me/company/invitations` `{email, role, first_name, last_name}` (both names
  required, 400 without - a new invitee's account is made from them) mails a
  link that lands on the sign-in page (minty-web's `/login`, phase 2); `…/<id>/resend` (429 with
  `retry_after` inside the cooldown; 502 when the email fails, after the token rotated) and
  `…/<id>/cancel`, each only for an invitation of the `?entity=` company. The address must be an
  address (`email_rules.invite_address_error`: printable ASCII, one `@`, a dotted domain, no
  markup or quoting characters, ≤150) on every invite path - the Users tab, onboarding's
  `/api/onboarding/invite`, the payer's invite-admin - because a page once drew
  `<svg/onload=…>` from an invitation's address. `tests/test_hub_company_settings.py`.
  `GET /entity/<co>/xero-not-connected` (a person added to a company whose Xero organisation they
  are not in) redirects to the Entity & Integration tab; Flask's page went 2026-10-20. Invitation expiry and the
  superuser rules are in `tests/test_invitation*.py`, `tests/test_invite_superuser.py`.
- **The invitation email** (`invite._build_invitation_html`) is hand-built HTML: every name and
  URL in it is escaped once at the top (a company or person can be named `<b>…</b>`), the
  subject is one line (a company name with a line break was refused by Flask-Mail and the send
  swallowed), the inviter is the non-blank parts of their name, and the logo is served from
  `email_base_url()` - `ACCOUNTS_API_URL`, else the request's own root (the old fallback doubled
  `/static/` and 404'd); it is `static/img/new_logo.png`, the flat mark, drawn 102px wide (its
  transparent margin leaves the cat ~72px; owner, 2026-10-23). Tested in
  `tests/test_char_access.py`.
- **Email input: English only.** The server answers a non-ASCII address with "Email can only
  contain English letters, numbers and symbols." and a 400 - the invite, the onboarding invite,
  and the business email on `/api/onboarding/create`
  ([authentication.md](authentication.md) §2, "Email input: English only"); the fields are the
  Next apps'.
- `GET /leave-entity` is "log out of the company": back to Select Company with the Flask
  session kept and presence dropped (membership is untouched); Log out from the list ends
  the session.
- Your own account: `GET/PATCH /minty/api/users/me`, `DELETE /minty/api/users/me`
  (deactivate).

## The superuser (`system_role = superadmin`)

What is left is two JSON routes: `POST /minty/api/users/create` and
`GET /minty/api/users/<id>/consents` (a person's terms consent history). The Flask admin pages -
`/admin` (all-company report list), `/admin_dashboard` with `/approve_user` / `/reject_user`,
`/find_user`, `/admin/download_statements`, `/download_attachments` - were deleted on 2026-10-20
with no replacement (owner's decision: production showed one superadmin who never signed in, and
every user approved). A superadmin signs in to the company list like everyone, sees every
company, and is **read-only** on the ones they are not a member of.

## Tests

`tests/test_char_entities.py` (the tabs and their permissions), `tests/test_entity_*.py`
(list, create, selection, the trial badge), `tests/test_user_presence.py`,
`tests/test_hub_company_settings.py`, `tests/test_invitation*.py`, `tests/test_authz_decorators.py`,
`tests/test_email_english_only.py`, `tests/test_flask_backend_only.py` (the retired pages, the
hand-overs). The screens are tested in minty-web's and minty-petty-cash-web's own e2e suites.
