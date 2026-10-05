# Companies (entities), members and administration

A company is an `entities` row; a person belongs to it through `user_entity`
(`role`, `approved`). Code: `blueprints/entity/` (list, settings, modules, payment
methods), `blueprints/user_management/` (the superuser's admin), `blueprints/invitation/`,
`blueprints/auth/routes/leave_entity.py`.

## Select Company and the dashboard

`GET /entity` lists the companies the signed-in person belongs to, with who last opened
each one and when (`entities.last_accessed_by_user_id` / `last_accessed_at`; the how and
its traps are in [entity_last_accessed.md](entity_last_accessed.md)). The list is built once,
in `blueprints/entity/services/entity_list.py::build_entity_list`, for its one reader:

- **minty-web's list** (`/entities`, the hub's "Select Company", 2026-09-29) — `/entity` mints
  an unscoped token and sends the browser there
  (`routes/list.py::_to_minty_web_list`), which reads `GET /api/me/entities`
  (`routes/me_api.py`, bearer + CORS for minty-web through `blueprints/shared/hub_api.py`). **Whether or not Terms are owed** (since 2026-09-29):
  minty-web's own Terms gate takes the acceptance ([legal-terms.md](legal-terms.md), minty-web's
  panel). Seventy-odd routes flash a message
  and redirect to `/entity`; the redirect drains those flashes, signs them (`itsdangerous`,
  salt `hub-flash`, five minutes) into `?flash=`, and the API hands them back as `notices`, so
  none is lost on the way. A redirect INTO another app (onboarding, minty-web, the payments
  app) drops the queue instead, logging each message (`pettycash/core/hooks.py::drop_flashes_leaving_flask`):
  those apps never show it, and onboarding's Xero connect used to pile one up per attempt that
  the list then toasted all at once when the wizard finished. Always - the `MINTY_WEB_HUB`
  switch and the Jinja page (`templates/entity/index.html`, `entity_list_empty.html`) went in
  phase 2 (2026-10-05), so minty-web must be deployed wherever Flask is.

Clicking one goes
through `GET /entity/<co>/modules` (`routes/modules.py::module_selector`, a router): a company
still onboarding resumes its wizard, someone outside it goes back to the list, one module goes
straight into it, and both go to **minty-web's module choice** (`/entities/<shortid>/<name>`,
with a token scoped to the company - phase 2, 2026-10-05; it was the payments app's
`/module-selection`), whose two doors enter each module through `/entity/<co>/enter`
(`tests/test_module_selector.py`). Opening Petty Cash
(`GET /entity/<co>/petty-cash`) is the **dashboard**: today's report state, the module cards and — when
subscriptions are on — the subscription notices ([modules-and-subscriptions.md](modules-and-subscriptions.md)).
A person with no company is sent to create one.

## Creating a company

`GET /entity/create` no longer renders a form: it launches the **onboarding wizard**
(`onboarding_launch_url(user, fresh=True)`) — the wizard's Step 1 creates the row through
`POST /api/onboarding/create`, Xero, sales methods, account codes, invitations and modules
follow on its later steps, and `POST /api/onboarding/finalize` flips the company from
`onboarding` to live ([onboarding-and-module-handoff.md](onboarding-and-module-handoff.md)).
`GET /entity/success` is the return page.

## Settings (`/entity/<id>/settings/…`)

Flask draws ONE tab: Petty Cash Settings = `settings_entity.html`
([petty-cash-settings.md](petty-cash-settings.md)) - each app keeps its own settings. **Users,
Entity & Integration and Module are minty-web's** (`/entities/<shortid>/<name>/settings/<tab>`,
phase 2 - 2026-10-05, `minty-web/docs/features/company-settings.md`): their Flask addresses stay
as HAND-OVERS (`routes/settings.py::_to_hub_tab` - a company-scoped token, and whatever was
flashed on the way signed into `?flash=`; the Xero reconnect's outcome reaches the tab that way),
over Flask's bearer routes `/api/me/company/*` (`routes/hub_settings.py`, below). The Jinja pages
(`settings_users_bills_ui.html` and its five partials, `settings_xero_bills_ui.html`) and their
session JSON routes are deleted.
**One look, and a real Back (2026-10-05).** The `?from=bills` flag is gone: every Flask settings
page has one look, whichever app the person came from, and its "‹ Back" returns to the page they
came from (`static/js/back_link.js`: the last entry in this tab's history outside
`/entity/settings/*` and `/entity/<id>/settings/*`, through the Navigation API; the link's `href` -
the company's home, `company_home_url` - is the fallback for a new tab). The tabs are
each carrying the sidebar ([sidebar.md](sidebar.md)), whose module groups show
only the modules the company has on (`data-module-nav`, hidden with an inline `display:none` — a
`hidden` attribute loses to Tailwind's `.flex`). The sidebar's **Settings** opens the settings of
the app it is pressed in - on Flask, Petty Cash Settings (Entity & Integration for a company
without Petty Cash); the payments app's own sidebar opens its Payment Request Settings.

| Tab | Route | What it edits | Who |
|---|---|---|---|
| Entity & Integration | minty-web; `GET /entity/<co>/settings/integration` hands over. Reads `GET /api/me/company/integration`, saves `PATCH` (name / `country_code` / `currency_id`), `POST /api/me/company/xero/disconnect` | the company name, country & currency, the Xero connection ([xero-integration.md](xero-integration.md)) | read `XERO_SETTINGS_VIEW` (cashier+); save `XERO_SETTINGS_UPDATE` (accountant+); rename `ENTITY_RENAME` (admin) |
| Petty Cash Settings | `GET/POST /entity/<co>/settings/petty-cash` (Petty Cash on only) | country & currency, the Xero account mapping - the accounts and contacts the dashboard's "Setup Required" asks for ([xero-integration.md](xero-integration.md) §3) - the sales settlement methods and the petty-cash account codes, at least one of which stays ticked ([petty-cash-settings.md](petty-cash-settings.md)) | `ENTITY_UPDATE` / `COA_UPDATE` / `COA_CREATE` / `COA_DELETE` - as above |
| Users | minty-web; `GET /entity/<co>/settings/users` hands over. Reads `GET /api/me/company/users` | members with role, who pays for the company (the billing-group payer, looked up separately from the role), pending invitations; per row whether this person may change the role / remove | read `USER_VIEW_ALL` and invite `USER_INVITE` (shop manager+); change a role `USER_ROLE_ASSIGN` (shop manager+); remove `USER_ROLE_DELETE` (accountant+) - each also the rank rule below |
| Module | `GET /entity/<co>/settings/modules` | a hand-over to minty-web's Module page ([modules-and-subscriptions.md](modules-and-subscriptions.md)) | `MODULE_VIEW` |

Renaming the company is reflected in the header at once (`e2e/03_settings.spec.ts`).

## Members, roles, invitations

- Roles and what they allow: [authentication.md](authentication.md) §1 and §5.
- The routes (bearer, minty-web's Users tab - `blueprints/entity/routes/hub_settings.py`; the
  session `/minty/api/invitation/*` and `/minty/api/users/<id>[/role]` routes went in phase 2):
  the company comes from `?entity=` ALONE and must be the person's (`profile.entity_context`) -
  the session PATCH read it from the query for its check and from the body for its write.
  `PATCH /api/me/company/users/<id>` `{role}` changes a role; `DELETE` removes, through the
  guards in order: rank 403 → the payer 409 → the last admin 409 → a pending handover's nominee
  409 (`services/roles.py`). Roles are the four assignable ones only (`enums.ASSIGNABLE_ENTITY_ROLES`,
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
  `/api/onboarding/invite`, the payer's invite-admin - because the Jinja tab once drew
  `<svg/onload=…>` from an invitation's address. `tests/test_hub_company_settings.py`. `GET /invitation/xero-not-connected/<entity>` is the page a person sees when
  they were added to a company that has no Xero connection yet. Invitation expiry and the
  superuser rules are in `tests/test_invitation*.py`, `tests/test_invite_superuser.py`.
- **The invitation email** (`invite._build_invitation_html`) is hand-built HTML: every name and
  URL in it is escaped once at the top (a company or person can be named `<b>…</b>`), the
  subject is one line (a company name with a line break was refused by Flask-Mail and the send
  swallowed), the inviter is the non-blank parts of their name, and the logo is served from
  `email_base_url()` - `PETTY_CASH_URL`, else the request's own root (the old fallback doubled
  `/static/` and 404'd). The password-reset email uses the same helper. Tested in
  `tests/test_char_access.py`.
- **Email input: English only.** The invite's email field (and the company's business email)
  takes printable ASCII only: it is `type="text" inputmode="email" data-email-ascii`, not
  `type="email"` (which accepts a Korean domain and hides it as punycode), strips anything
  else as it is typed and says "Email can only contain English letters, numbers and
  symbols." (`static/js/email_input.js`). The server answers such an address with that
  sentence and a 400 - the invite, the onboarding invite, and the business email on
  `/api/onboarding/create`, `PUT /api/onboarding/entity/<id>` and the `/entity/create` form
  ([authentication.md](authentication.md) §2, "Email input: English only").
- `GET /leave-entity` is "log out of the company": back to Select Company with the Flask
  session kept and presence dropped (membership is untouched); Log out from the list ends
  the session.
- Your own account: `GET/PATCH /minty/api/users/me`, `DELETE /minty/api/users/me`
  (deactivate).

## The superuser's administration (`system_role = superadmin`)

`GET /admin` (all users; approve / reject sign-ups — `POST /approve_user/<id>`,
`/reject_user/<id>`), `GET /admin_dashboard`, `GET/POST /find_user`,
`POST /minty/api/users/create`, `GET /minty/api/users/<id>/consents` (a person's terms
consent history), `GET/POST /admin/download_statements` (statements across companies),
`POST /api/client-logs` (the browser's log sink). A superuser sees every company but is
**read-only** on the ones they are not a member of.

## Tests

`tests/test_char_entities.py` (the tabs and their permissions), `tests/test_entity_*.py`
(list, create, selection, the trial badge), `tests/test_user_presence.py`,
`tests/test_settings_users_subscriber_tag.py`, `tests/test_one_payer_per_entity.py`,
`tests/test_invitation*.py`, `tests/test_authz_decorators.py`, `tests/test_email_english_only.py`; in the browser
`e2e/03_settings.spec.ts` (mapping, sales methods, users, the Xero page, rename, the
module page, the CSV) and `e2e/01_login.spec.ts` (Select Company).
