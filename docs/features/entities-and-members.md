# Companies (entities), members and administration

A company is an `entities` row; a person belongs to it through `user_entity`
(`role`, `approved`). Code: `blueprints/entity/` (list, settings, modules, payment
methods), `blueprints/user_management/` (the superuser's admin), `blueprints/invitation/`,
`blueprints/auth/routes/leave_entity.py`.

## Select Company and the dashboard

`GET /entity` lists the companies the signed-in person belongs to, with who last opened
each one and when (`entities.last_accessed_by_user_id` / `last_accessed_at`; the how and
its traps are in [entity_last_accessed.md](entity_last_accessed.md)). The list is built once,
in `blueprints/entity/services/entity_list.py::build_entity_list`, for two readers:

- **minty-web's list** (`/entities`, the hub's "Select Company", 2026-09-29) — with
  `MINTY_WEB_HUB` on, `/entity` mints an unscoped token and sends the browser there
  (`routes/list.py::_to_minty_web_list`), which reads `GET /api/me/entities`
  (`routes/me_api.py`, bearer + CORS for minty-web through `blueprints/shared/hub_api.py`). **Whether or not Terms are owed** (since 2026-09-29):
  minty-web's own Terms gate takes the acceptance ([legal-terms.md](legal-terms.md), minty-web's
  panel). Seventy-odd routes flash a message
  and redirect to `/entity`; the redirect drains those flashes, signs them (`itsdangerous`,
  salt `hub-flash`, five minutes) into `?flash=`, and the API hands them back as `notices`, so
  none is lost on the way. `MINTY_WEB_HUB` is **off unless set** — `/entity` is the first page
  after every login, so it is switched on only where minty-web is deployed.
- **the Jinja page** (`templates/entity/index.html`), everywhere else.

Opening one
(`GET /entity/<id>`) is the **dashboard**: today's report state, the module cards and — when
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

Tabs of their own templates (`settings.html` and `settings_users.html`, with the `*_bills_ui.html`
dress when reached from the payments app with `?from=bills`; Petty Cash Settings is ONE template,
`settings_entity.html`, for both ways in - `?from=bills` changes only its way back and its tabs'
links, [petty-cash-settings.md](petty-cash-settings.md); the Module tab is a hand-over to
minty-web's page, [modules-and-subscriptions.md](modules-and-subscriptions.md)),
each carrying the sidebar ([sidebar.md](sidebar.md)), whose module groups show
only the modules the company has on (`data-module-nav`, hidden with an inline `display:none` — a
`hidden` attribute loses to Tailwind's `.flex`). The sidebar's **Settings** opens the settings of
the app it is pressed in: Petty Cash Settings from the Petty Cash pages, the payments app's
Payment Settings from the `?from=bills` ones.

| Tab | Route | What it edits | Who |
|---|---|---|---|
| Entity & Integration | `GET/POST /entity/<id>/settings/xero` | the company name, country & currency, the Xero connection ([xero-integration.md](xero-integration.md)) | `ENTITY_UPDATE` / `XERO_SETTINGS_UPDATE` — accountant and up; others see it read-only (`settings-readonly`) |
| Petty Cash Settings | `GET/POST /entity/settings/entity/<id>` (Petty Cash on only) | country & currency, the Xero account mapping - the accounts and contacts the dashboard's "Setup Required" asks for ([xero-integration.md](xero-integration.md) §3) - the sales settlement methods and the petty-cash account codes, at least one of which stays ticked ([petty-cash-settings.md](petty-cash-settings.md)) | `ENTITY_UPDATE` / `COA_UPDATE` / `COA_CREATE` / `COA_DELETE` - as above |
| Users | `GET /entity/settings/users/<id>` | members with role, who pays for the company (the billing-group payer, looked up separately from the role), pending invitations, and who is signed in now (`…/presence`, polled every 20 s — [authentication.md](authentication.md) §8) | admins manage roles and invitations |
| Module | `GET /entity/settings/module/<id>` | a hand-over to minty-web's Module page (`?from=bills` travels on; [modules-and-subscriptions.md](modules-and-subscriptions.md)) | `MODULE_VIEW` |

Renaming the company is reflected in the header at once (`e2e/03_settings.spec.ts`).

## Members, roles, invitations

- Roles and what they allow: [authentication.md](authentication.md) §1 and §5.
- Changing a member: `PATCH /minty/api/users/<id>/role` and `DELETE …/role` (remove from
  the company), `PATCH /minty/api/users/<id>` (details); a person may not promote above
  their own rank (`can_manage_role_assignment`).
- Inviting: `POST /minty/api/invitation/send` mails a link that lands on the onboarding
  app's sign-in page; `GET /minty/api/invitation/<entity>/pending`, `…/resend`,
  `…/cancel`. `GET /invitation/xero-not-connected/<entity>` is the page a person sees when
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
