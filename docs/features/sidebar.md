# The sidebar — the menu and My Profile

Every Petty Cash page with a header — the dashboard, the report wizard, report history, the
settings tabs (Users and Entity & Integration in both dresses, Petty Cash and `?from=bills`;
Petty Cash Settings, one template for both), the entity list while
`MINTY_WEB_HUB` is off, create and no-permission — carries the same sidebar minty-web draws:
**one drawer, two views** (the user's call, 2026-09-29; brought here 2026-09-30).

- the header's **≡** opens the **menu** (Figma 02);
- the header's **initials** open **My Profile** (Figma 10-A / 10-B); the menu's name switches to
  it, its **‹** goes back to the menu, its **×** closes the drawer.

It slides over the page (nothing navigates to open it) and closes on Escape, a click beside it,
or a link inside it. 353 px for the menu; 440 px for My Profile from 640 px up and the whole
screen on a phone — minty-web's sizes, colours and words.

## A port, not a copy to lift

minty-web's sidebar is TypeScript (`components/ui/Sidebar.tsx`, `SideMenu.tsx`, `ViewerBadge.tsx`,
`features/profile`), and billing-frontend carries copies of those files that `@minty/shared`
will replace at Part 3 step 4. Jinja cannot use a TypeScript package, so this one is a **port**:
it retires with these pages when they move to Next (Part 3), and until then a change to
minty-web's menu or profile is a change here too.

| Piece | File |
|---|---|
| What the menu holds on a page, and where each item leads | `blueprints/shared/sidebar.py` (`sidebar_context()`, a context-processor global) |
| The drawer and the menu, drawn server-side; My Profile's skeleton | `templates/components/minty_sidebar.html` |
| Plain CSS, every rule under `#minty-sidebar` (so neither the CDN Tailwind nor its forms plugin can restyle it) | `static/css/minty_sidebar.css` |
| The drawer's behaviour, My Profile, the Subscriptions Overview | `static/js/minty_sidebar.js` (one dependency: `window.MintyEmail`, which the partial loads first) |
| The email field's English-only rule ([authentication.md](authentication.md) §2) | `static/js/email_input.js` |
| Icons and the caped cat (minty-web's `public/menu`, `public/profile`) | `static/img/sidebar/` |

A page includes the partial once, anywhere in its body (`{% include 'components/minty_sidebar.html' %}`;
the Payment Request pages inside `{% with sidebar_from_bills=True %}`), and marks its openers:
`data-sidebar-open="menu"` on the ≡, `data-sidebar-open="profile"` on the initials, whose `href`
(the `/profile` router) stays the way in when scripts are off. The script moves the drawer to the
end of the body, so no ancestor's transform or overflow clips it. `toggleMenu()`,
`closeSidePanel()`, `openNavDrawer()` and `closeNavDrawer()` still work for any old caller.

It replaced `templates/components/sidepanel.html` and the Payment Request pages' own drawer
(`entity/partials/bills_nav_drawer_panel_body.html`), both deleted.

## The menu

Top to bottom: the Minty mark; the person (avatar + name — opens My Profile); **Select Entity**
(`/entity`); **Manage subscriptions** (minty-web's portal through `/handoff/minty-web`); inside a company only, **Petty Cash** (Dashboard, Reports) and
**Payment Request** (Bills → `go_to_bills`); the cat; **Settings** (inside a company only) and
**Logout**.

- The module groups are always in the page and hidden with an inline `display:none` when the
  module is off (`is_petty_cash_enabled` / `is_billing_enabled`), because the module settings
  page shows and hides them from its Save answer (`data-module-nav`). The rule between the two
  groups shows only while both do.
- **Settings opens the settings of the app it is pressed in** (the user's call, 2026-09-30):
  on the Petty Cash pages, the **Petty Cash Settings** tab (`entity_settings_entity` — the
  accounts and contacts a report needs, the sales methods); on the Payment Request pages
  (`?from=bills`), the payments app's **Payment Settings** (`entity_settings_payments`, which
  mints its token at the click — where billing-frontend's own Settings goes). A company without
  Petty Cash has no Petty Cash Settings tab (`require_module`), so it gets Entity & Integration.
  minty-web's own menu keeps its module page.
- **On Petty Cash Settings with unsaved changes**, a link in the drawer — Logout included —
  asks first ("Leave without saving?", [modals.md](modals.md)): the dialog sits above the drawer
  (z-index 250 over 200) and Escape closes only the dialog. The initials and the ≡ never ask.
- **Logout ends the session everywhere** (`/logout`) — in all three apps (the user's call,
  2026-09-30). The old side panel's "leave this company" (`/leave-entity`) is no longer in the
  menu; the route stays.
- The page being shown is marked with `aria-current` only: the design draws it like any other.

## My Profile and the Subscriptions Overview

Drawn in the browser over the **same reads minty-web makes**, so the three apps show one answer:

1. `GET /me/sidebar-token` (session, same-origin, `no-store`; `blueprints/entity/routes/modules.py`)
   hands the page an unscoped 30-minute module token — the reads below take a bearer, not this
   app's session. A signed-out caller gets a 401 it can read, not the sign-in page.
2. `GET /api/me/profile?entity=<company>` with that bearer (the hub route, `hub_api.guard`) —
   the company, its plan line (Payment Request `#2e6ff2`, Petty Cash `#ea9713`, SuperMinty teal
   with the caped cat), the person's role, the details card.
3. Edit → Save sends only what changed as `PATCH /api/me/profile`; Flask's refusal sentence is
   shown in the card; after a save the header's initials and the menu's name change at once.
   The email field is English only (`data-email-ascii`: anything else is stripped as it is
   typed, with the hint under the field); a changed address must also pass
   `MintyEmail.isEmail` before it is sent, and the server refuses a non-English one with 422.
   PASSWORD · Change opens the Xero account page.
4. The **Subscriptions Overview**: minty-billing-api's `GET /api/me/subscriptions`
   (`BILLING_API_URL`, default `http://localhost:8004`), which lists this app's origin
   (`MINTY_PUBLIC_URL`) in its CORS; a failed read (any status) shows the card's "didn't load"
   state with *Try again*. *Manage Subscription* goes to minty-web's portal.

Every bearer call goes without this app's cookie (as minty-web's cross-origin calls do), so the
session-side hooks (Terms gate, read-only superuser block) see no one; a 401 fetches one fresh
token, then says so. A failed read shows its sentence with Try again and logs to the console.

**Trade-off, accepted:** the page's script can read this token — as minty-web's and
billing-frontend's cookie tokens already are, and as it already travels in every handoff URL.

## Tests

`tests/test_sidebar.py` — the menu on each kind of page (in a company, a module off, the entity
list, the Payment Request pages, a company without Petty Cash), where every
item leads, the token route, the hub answering billing-frontend's origin by name, the dashboard's
setup links, every page family carrying the partial and none of the old drawers. The drawer's
behaviour was checked live on 2026-09-30 (menu 353 px, profile 440 px and full width at 375,
Escape and focus, edit-cancel, the overview's figures, the Petty-Cash-only and
Payment-Request pages).
