# Companies (entities), members and administration

A company is an `entities` row; a person belongs to it through `user_entity`
(`role`, `approved`). Code: `blueprints/entity/` (list, settings, modules, payment
methods), `blueprints/user_management/` (the superuser's admin), `blueprints/invitation/`,
`blueprints/auth/routes/leave_entity.py`.

## Select Company and the dashboard

`GET /entity` lists the companies the signed-in person belongs to, with who last opened
each one and when (`entities.last_accessed_by_user_id` / `last_accessed_at`; the how and
its traps are in [entity_last_accessed.md](entity_last_accessed.md)). Opening one
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

One page, `templates/entity/settings.html` (plus `settings_module*.html`), with a side
panel (`templates/components/sidepanel.html`) whose groups show only the modules the
company has on (`data-module-nav`, hidden with an inline `display:none` — a `hidden`
attribute loses to Tailwind's `.flex`):

| Tab | Route | What it edits | Who |
|---|---|---|---|
| Xero / petty cash | `GET/POST /entity/<id>/settings/xero` | the company name, country & currency, the Xero connection and the petty-cash mapping ([xero-integration.md](xero-integration.md) §3), the sales methods ([petty-cash-settings.md](petty-cash-settings.md)) | `ENTITY_UPDATE` / `XERO_SETTINGS_UPDATE` / `COA_UPDATE` — accountant and up; others see it read-only (`settings-readonly`) |
| Entity | `GET/POST /entity/settings/entity/<id>` | country selection, chart-of-accounts choices | as above |
| Users | `GET /entity/settings/users/<id>` | members with role, who pays for the company (the billing-group payer, looked up separately from the role), pending invitations, and who is signed in now (`…/presence`, polled every 20 s — [authentication.md](authentication.md) §8) | admins manage roles and invitations |
| Modules | `GET /entity/settings/module/<id>` | the module switches ([modules-and-subscriptions.md](modules-and-subscriptions.md)) | admin |

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
`tests/test_invitation*.py`, `tests/test_authz_decorators.py`; in the browser
`e2e/03_settings.spec.ts` (mapping, sales methods, users, the Xero page, rename, the
module page, the CSV) and `e2e/01_login.spec.ts` (Select Company).
