# Features — what Minty does and where each part lives

One page per feature: what it does for the person using it, how the code does it, the
rules that are easy to break, and which tests pin it. Written for someone new to the
codebase; the deeper records (the schema decision register, the modernisation plan, the
notes in `docs/code_cleanse/`) are linked, not repeated.

Minty is the Flask backend of the system - **backend only since 2026-10-20: it draws no page**.
It owns identity, the companies, the Xero connection and the petty-cash report's rules, and it
launches the Next.js apps with a short-lived token: the hub (`../minty-web` +
`../minty-subscription-api`: sign-in, companies, settings tabs, profile, subscriptions), the
onboarding wizard (`../minty-onboarding-web` + `../minty-onboarding-api`), the payment-request
module (`../minty-payment-request-web` + `../minty-payment-request-api`) and Petty Cash
(`../minty-petty-cash-web` + `../minty-petty-cash-api`). Each of those repos has its own
`docs/features/` folder in the same shape.

| Feature | Document |
|---|---|
| Signing in, sessions, roles, the hand-off tokens, Xero OAuth tokens | [authentication.md](authentication.md) — the system-wide description; the other repos' `authentication.md` files cover their half |
| Companies, members, invitations, the superuser's two JSON routes | [entities-and-members.md](entities-and-members.md) |
| Currency, denominations, sales methods, the Xero mapping | [petty-cash-settings.md](petty-cash-settings.md) |
| The daily report's rules — the services behind minty-petty-cash-web's Daily Closing | [report-wizard.md](report-wizard.md) |
| Petty Cash's bearer API (Flask's copy; minty-petty-cash-api serves production), `/handoff/petty-cash-web` and the old addresses that hand over | [petty-cash-api.md](petty-cash-api.md) |
| Receipts: storage, naming, the comma trap | [receipts-and-attachments.md](receipts-and-attachments.md) |
| History, the movements CSV, share links | [report-history-and-exports.md](report-history-and-exports.md) |
| Connecting a company to Xero, syncing, publishing and republishing a day | [xero-integration.md](xero-integration.md) |
| Modules, the subscription reads Flask keeps | [modules-and-subscriptions.md](modules-and-subscriptions.md) |
| Launching the wizard and the payment module; `/api/onboarding/*` | [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md) |
| Manual QA checklist — onboarding's dependencies here (OTP sign-in, Xero connect, the onboarding JWT) | [qa-checklist.md](qa-checklist.md) |
| Modals - minty-web's design on every app (Flask has none) | [modals.md](modals.md) |
| Toasts - minty-web's card on every app, the system-wide rule the other repos link (Flask has none) | [toasts.md](toasts.md) |
| Terms of Use versions, the consent record, the gate | [legal-terms.md](legal-terms.md) |
| Reading a receipt with Gemini | [expense-ai.md](expense-ai.md) |
| Configuration, storage, mail, logging, the test suites, scripts | [operations.md](operations.md) |
| "Last logged in" on Select Company (a worked example of one feature's port) | [entity_last_accessed.md](entity_last_accessed.md) |
| User-facing error copy (the standard for every repo), every error answered as JSON | [ERROR_MESSAGE_LEAKS.md](ERROR_MESSAGE_LEAKS.md) |
| CI and the stack E2E job | [ci.md](ci.md) |
| The visual-anchors design review (2026-10-19, the Next apps' screens) | [visual-anchors-review.md](visual-anchors-review.md) |

Elsewhere in `docs/`: `schema/` (the redesigned database, its generators and the one-hop
migration), `modernisation/modernisation_plan.md` (Phase A–E and Part 2), `terms/` (the
T&C runbook), `code_cleanse/` (the per-repo work documents), `expense_ai/` (the AI
feature's product and technical papers), `archive/` (superseded runbooks).

Keep these current: when a route, a rule or a test named here changes, change the line
that names it in the same commit.
