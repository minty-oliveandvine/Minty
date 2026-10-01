# Features — what Minty does and where each part lives

One page per feature: what it does for the person using it, how the code does it, the
rules that are easy to break, and which tests pin it. Written for someone new to the
codebase; the deeper records (the schema decision register, the modernisation plan, the
notes in `docs/code_cleanse/`) are linked, not repeated.

Minty is the Flask hub of a seven-app system. It owns identity, the companies, the daily
petty-cash report and the Xero connection, and it launches the Next.js apps with a
short-lived token: the onboarding wizard (`../onboarding` + `../onboarding-backend`), the
payment-request module (`../billing-frontend` + `../billing-backend`) and, since Part 2 of
the modernisation plan (scaffolded 2026-09-21), the subscription pages, the profile and the
entity list of
the new hub (`../minty-web` + `../minty-billing-api`). Each of those repos has its own
`docs/features/` folder in the same shape.

| Feature | Document |
|---|---|
| Signing in, sessions, roles, the hand-off tokens, Xero OAuth tokens | [authentication.md](authentication.md) — the system-wide description; the other repos' `authentication.md` files cover their half |
| Companies, members, invitations, the superuser's admin | [entities-and-members.md](entities-and-members.md) |
| Currency, denominations, sales methods, the Xero mapping | [petty-cash-settings.md](petty-cash-settings.md) |
| The daily report — opening to submitted | [report-wizard.md](report-wizard.md) |
| Receipts: storage, naming, the comma trap, downloads | [receipts-and-attachments.md](receipts-and-attachments.md) |
| History, detail pages, CSV / Excel / docx / screenshot exports, share links | [report-history-and-exports.md](report-history-and-exports.md) |
| Connecting a company to Xero, syncing, publishing and republishing a day | [xero-integration.md](xero-integration.md) |
| Modules, the subscription engine, the in-app notices, the scheduler | [modules-and-subscriptions.md](modules-and-subscriptions.md) |
| Launching the wizard and the payment module; `/api/onboarding/*` | [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md) |
| The sidebar on every page with a header - the menu and My Profile (minty-web's, ported) | [sidebar.md](sidebar.md) |
| Modals - minty-web's design on every app; the Flask port and "Leave without saving?" | [modals.md](modals.md) |
| Toasts - minty-web's card on every app; the one shared toast here | [toasts.md](toasts.md) |
| Terms of Use versions, the consent record, the gate | [legal-terms.md](legal-terms.md) |
| Reading a receipt with Gemini | [expense-ai.md](expense-ai.md) |
| Configuration, storage, mail, logging, the test suites, scripts | [operations.md](operations.md) |
| "Last logged in" on Select Company (a worked example of one feature's port) | [entity_last_accessed.md](entity_last_accessed.md) |
| User-facing error copy and the leak classes that were closed | [ERROR_MESSAGE_LEAKS.md](ERROR_MESSAGE_LEAKS.md) |

Elsewhere in `docs/`: `schema/` (the redesigned database, its generators and the one-hop
migration), `modernisation/modernisation_plan.md` (Phase A–E and Part 2), `terms/` (the
T&C runbook), `code_cleanse/` (the per-repo work documents), `expense_ai/` (the AI
feature's product and technical papers), `archive/` (superseded runbooks).

Keep these current: when a route, a rule or a test named here changes, change the line
that names it in the same commit.
