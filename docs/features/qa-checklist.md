# Manual QA checklist — Minty

Minty's one manual QA checklist (one per repo). It covers two surfaces:

1. **What the onboarding wizard depends on here** — email OTP sign-in, minting the
   onboarding JWT, the Xero OAuth connect/callback round-trip for step 4, and
   launching/resuming the wizard.
2. **The daily petty-cash report wizard's 6 steps** — Opening, Sales, Expenses, Deposit,
   Cash Count, Ending (`templates/components/stepper.html`/`.md`).

Still uncovered here (no checklist items yet, feature docs only — see
[README.md](README.md)): petty-cash settings, receipts/attachments as a feature, report
history/exports, Xero publish/republish, the modules/subscription reads, the sidebar,
modals, toasts, the terms gate and expense AI.

Run this alongside the automated suites named in each section, not instead of them. Tick
each box against a disposable test entity and a disposable OTP-only inbox — never a real
company or a real Xero organisation (see "The onboarding-connect race" below for why).
`POST /report/delete/<id>` is a hard delete, not a reversible void.

## Email OTP sign-in (the identity gate before the onboarding JWT)

`blueprints/auth/routes/email_auth.py` + `services/email_auth.py`
([authentication.md](authentication.md) §2.2); `tests/test_otp_identity_gate.py`.

- [ ] `POST /auth/email/request-code` in login mode (`mode: "login"`) for an address with
      no `user` row → 404 "Please sign up first", **before** any code is sent.
- [ ] The same unknown address in sign-up mode is accepted (a code is sent).
- [ ] An address held only as `user.xero_email` (never `username`) gets a code in login
      mode — the gate reads `resolve_user_by_email`, not `username` alone.
- [ ] An address that is only `username`/`email_otp`-known with no resolvable user row no
      longer opens the gate (the pre-2026-10-05 regression).
- [ ] The 6-digit code expires at 60 s; a code entered after that is refused.
- [ ] Resend cooldown is 60 s; failed-attempt counts carry forward across a resend (not
      reset to zero).
- [ ] The 5th wrong code locks the address for 15 minutes, HTTP 429 `ERR_LOCKED`, anchored
      to the row's `created_at` (check the lock clears itself at 15 minutes, not on next
      request).
- [ ] If the mail send itself fails, the code request is rolled back and answers 400 — a
      retry right after succeeds (no orphaned "code was sent but isn't valid" state).
- [ ] `POST /auth/email/verify-code` with a correct code signs an existing user in.
- [ ] The same call for a brand-new address with a first/last name creates the
      passwordless user on the spot, with terms consent recorded as `signup_otp` (or
      `signup_invite` when an invite token rode along).
- [ ] A new address with **no** name answers 404 "please sign up" rather than creating a
      blank account.
- [ ] `GET /auth/email/handoff` sets the session cookie on Minty's origin and then honours
      a signed `next` only when it is a path on this site; otherwise it falls back to
      `/admin` or `/index`.
- [ ] Every address field in this flow is `type="text"`, English-only, rejects non-ASCII as
      it's typed (not just on submit).

## Minting the onboarding JWT

`blueprints/entity/routes/create.py::_mint_onboarding_token` / `onboarding_launch_url`
([authentication.md](authentication.md) §6, §9; [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md)).

- [ ] `GET /entity/create` (brand-new company) mints a token and redirects with `fresh=1`
      and **no** `entity_id`.
- [ ] Resuming an in-progress company passes `entity_id=` and never sets `fresh`.
- [ ] Decode the minted token: claims are exactly `user_id`, `scope: "onboarding"`, `iat`,
      `exp` — nothing else (no `entity_id`, no role claims — those belong to the module
      token, not this one).
- [ ] Token lifetime is 60 minutes from `iat`.
- [ ] The token is HS256, signed with `SECRET_KEY` — verify it decodes successfully against
      minty-onboarding-api's `OnboardingBearerAuth` using the **same** local `.env` value;
      a deliberately wrong key 401s (this is the cross-repo failure mode the
      `prod-secret-key-differs-from-local` note warns about).
- [ ] An invitation link lands on the wizard's `/auth` page with the onboarding token and
      the invite token riding together — the invite is still honoured after that landing.
- [ ] `GET /entity/<id>/enter?token=` (the *module*-token re-entry route) refuses an
      onboarding-scoped token — the two token kinds are not interchangeable
      (`test_billing_relogin_handback.py`, `test_url_security.py`).

## Xero OAuth connect/callback (onboarding step 4)

`blueprints/xero/routes/routes.py`, `services/integration.py`
([xero-integration.md](xero-integration.md) §1–2); `tests/test_xero_scopes.py`,
`tests/test_xero_entity_connect_race.py`.

- [ ] `GET /xero_connect?entity_id=…` requires `XERO_SETTINGS_UPDATE` (an admin on that
      entity) — a cashier/shop_manager session is refused.
- [ ] The outgoing OAuth `state` carries the entity as `<base>:<entity_id>:<name>[:<initiator>]`
      — confirm by inspecting the redirect URL, since the Flask session does not survive
      the round trip to Xero and back.
- [ ] The requested scope set is the app's exact minimal granular list — not the composite
      `accounting.transactions` (Xero rejects that scope for this app registration).
- [ ] `/xero_reconnect` requests the identical scope set as first-time connect.
- [ ] `GET /callback` exchanges the code onto the **connecting user's** `user_token` row,
      and stamps `entities.connected_by_user_id` as that same user — not whoever currently
      holds any token on the entity.
- [ ] After callback: `entities.xero_org_id`, `xero_tenant_name` are set and
      `status = connected`.
- [ ] Connecting an organisation that is already linked to a **different** company
      disconnects that other company first — one Xero organisation ↔ one company at a
      time. (Use a scratch Demo Company for this check, never a shared/real org — see the
      callout below.)
- [ ] The background sync kicks off after callback (contacts, chart of accounts, bill
      account codes) and `GET /api/entity/<id>/xero-sync-status` reports progress while it
      runs.
- [ ] A re-sync after an organisation switch clears the entity's petty-cash mapping
      (`entity_pettycash_settings`'s FKs are `ON DELETE SET NULL`) — expected, not a bug;
      it must be picked again (out of scope here — see `xero-integration.md` §3).

## Launching and resuming the wizard (module handoff)

[onboarding-and-module-handoff.md](onboarding-and-module-handoff.md); `tests/test_onboarding_launch_fresh.py`,
`tests/test_onboarding_module_state.py`, `tests/test_onboarding_csrf_exempt.py`.

- [ ] The redirect to the wizard is `<ONBOARDING_WEB_URL>/?token=<jwt>[&entity_id=…][&fresh=1]`
      — no other query params leak the token elsewhere (e.g. not also appended to a
      Referer-visible link).
- [ ] `/api/onboarding/*` calls that still run through Minty (not proxied to
      minty-onboarding-api) are CSRF-exempt — confirm a same-path POST without a CSRF
      token still succeeds for those, while an ordinary session-authenticated Flask route
      elsewhere is not.
- [ ] CORS on Minty's `/api/onboarding/*` answers names `ONBOARDING_WEB_URL` only — a
      request with a different `Origin` does not get `Access-Control-Allow-Origin` back.
- [ ] A wizard session with nothing granted yet lands on the Modules step (state's
      `current_step` derivation) rather than skipping ahead.
- [ ] An explicit module grant (and an explicitly disabled one) shows the same on both the
      wizard's state response and wherever Minty itself reads the grant.

## The onboarding-connect race (read before testing Xero connect by hand)

**The entity on a Xero connect/callback is resolved from the OAuth `state` string, not
from the Flask session** — the session does not survive the round trip to Xero's
authorize page and back. `tests/test_xero_entity_connect_race.py` exists because two
people onboarding and connecting Xero *at the same time* used to let one user's callback
bind the wrong user's entity
(`test_old_code_would_have_corrupted_data_regression_proof`). One tester clicking through
the flow once will never see this — it only shows up with two concurrent sessions. If you
want to exercise it by hand:

1. Use two disposable onboarding entities, never two people racing to connect the **same**
   entity or the same real Xero organisation.
2. Start both `/xero_connect` redirects before either completes `/callback`, so the two
   `state` values are both in flight together.
3. Confirm afterward that each entity's `xero_org_id` and `connected_by_user_id` match the
   session that actually requested it — not swapped.

Don't test this against a shared or production Xero organisation: connecting it elsewhere
disconnects whoever currently holds it (see the connect checklist above).

# The daily report wizard — the 6 steps

One report per company per day. Full route/model detail is in
[report-wizard.md](report-wizard.md); `tests/test_char_report_lifecycle.py` walks the whole
thing on Postgres and `e2e/02_report_wizard.spec.ts` is the only suite that runs the pages'
inline JavaScript.

- [ ] A fresh company's first report opens as a **draft** — there is no separate draft
      table; the row the wizard fills IS `pettycashv3.report` from the first save.
- [ ] The stepper's 6 dots match the page order exactly: Opening → Sales → Expenses →
      Deposit → Cash Count → Ending (the 7th page, Submitted, has no dot of its own).

## Step 1 — Opening

`blueprints/report/routes/opening.py`; `templates/report/opening.html`. The page POSTs back
to its own route (`/entity/<co>/petty-cash/reports/new/opening`); the only separate call it
makes is `POST /report/<id>/edit/withdrawal` (AJAX, submitted-report edit mode only), and
server-side it calls Xero's Accounts API via `get_accounts_from_xero` to list bank accounts.

### Starting balance (chained from the previous day)

- [ ] A second or later report's starting balance equals **yesterday's `closing_balance`** —
      there is no field for it on this page.
- [ ] With yesterday's `closing_balance` null, it falls back to yesterday's
      `actual_cash_total` (the physical count); with that also null, `0`. Confirm the
      fallback order by clearing one on a disposable report.
- [ ] A brand-new company's first report starts at `0` (`is_first_report`).
- [ ] A first report's date cannot be before the onboarding draft's `transaction_date`
      (`_onboarding_floor_date` / `_first_report_date_error`) — the refusal quotes that date.
- [ ] No report's date can be in the future (`future_date_error`).
- [ ] A later report's date must be **exactly** the day after the last submitted one — try
      skipping a day and repeating a day; both refused, naming the expected date.
- [ ] If the Xero token isn't valid, the bank-account list is simply empty — confirm the page
      still renders and saves rather than erroring.

### Addition to Cash Drawer (`cash_addition`)

- [ ] Typing an amount live-updates "Opening Cash Balance" as `Starting + Addition`
      (`updateOpeningCashBalance()`), before any save.
- [ ] A blank or `-` addition is treated as `0` on submit (`cleanFormData()` strips commas
      and normalizes blank/dash to `'0'`).
- [ ] If `opening_balance + cash_addition` would be negative, both **Save & Next** and
      **Save & Exit** are blocked and the "Fix Negative Balance" modal opens
      (`validateOpeningCashBalance()`) — its only exit is back to the dashboard.
- [ ] Saved as `report.cash_addition`, and folded into
      `report.adjusted_opening_balance = opening_balance + cash_addition` — both columns move
      together, never just one.

### Withdrawal source ("Withdrawal from": Company Bank / Personal)

- [ ] On a draft the radio is editable and saves with the page as
      `report.cash_addition_type`.
- [ ] Re-saving a draft without touching the radio keeps the previous choice — a company with
      no petty-cash bank-account setting no longer loses it on a second visit (fixed
      2026-10-05: the save used to require a hidden `bank_account` value that was empty for
      such a company).
- [ ] On a submitted report opened with `?report_edit=true`, only this radio is editable;
      every balance field stays read-only.
- [ ] In that edit mode the radio does **not** save on change — it only sets
      `markWithdrawalDirty()`; **Save changes** fires `saveWithdrawalSource()`
      (`POST /report/<id>/edit/withdrawal`). Confirm an unsaved change warns on step
      navigation and that the dirty flag clears after a successful save.
- [ ] The bank account itself is never per report — it's the company's Petty Cash Settings
      value, shown for display only.

### What the first save writes

- [ ] One row is **inserted** into `pettycashv3.report` with: `transaction_date`,
      `next_transaction_date`, `opening_balance`, `cash_addition`,
      `adjusted_opening_balance`, `closing_balance` (= the adjusted opening figure),
      `cashsale_total`/`nocashsale_total`/`total_sales`/`expense_total`/`bank_deposit` all
      `0.0`, `current_section = "opening"`, `completed_sections = []`, `created_by`,
      `cash_addition_type`, `entity_id`, `status = "draft"`.
- [ ] `completed_sections` then gains `"opening"` exactly once (`update_draft_progress`) — no
      duplicate entries on a re-save.
- [ ] One `report_history` row is written per save (`log_history`), `field_changed =
      "opening_entry"`, `action` = `created` on the first save and `updated` afterward.
- [ ] Saving the same date twice updates the **existing** draft row — no second row for that
      date.
- [ ] **DB:** `SELECT opening_balance, cash_addition, cash_addition_type,
      adjusted_opening_balance, completed_sections, status FROM pettycashv3.report WHERE
      entity_id = '<id>' ORDER BY transaction_date DESC LIMIT 1;`

### Navigation

- [ ] Clicking another stepper step with unsaved changes is blocked with a warning toast, not
      a silent navigation (`navigateToStep()` / `hasUnsavedChanges()`).
- [ ] **Save & Next** goes to Sales; **Save & Exit** goes to the report dashboard — both save
      first.
- [ ] The stepper reflects the furthest step reached (`completed_sections`), not the page
      being viewed.

## Step 2 — Sales

- [ ] One amount field per sales method the company actually has set up — cash, the
      electronic methods, the delivery platforms. A method not configured simply doesn't
      appear; it is never a disabled or zero row.
- [ ] **DB:** `SELECT sale_id, amount FROM pettycashv3.report_sale WHERE report_id = '<id>';`
      — one row per method entered.

## Step 3 — Expenses

- [ ] Each line persists the moment it's added (`POST /report/expense/add`), not batched at
      the end — add a line, refresh mid-wizard, confirm it survived.
- [ ] Supplier and account pickers search the company's synced Xero contacts and active
      expense accounts; a new supplier can be created in Xero from the form
      (`/report/expense/create_contact`).
- [ ] A system account (bank, petty cash, a mapped control account) is refused as an expense
      account at **publish** time (`validate_expenses_for_system_accounts`) — not blocked at
      entry, so confirm it's caught later rather than accepted forever.
- [ ] Every expense line must carry a receipt before the day can be submitted
      (`validate_drafts`) — try reaching Ending with one bare line.
- [ ] **A receipt always opens the full-screen viewer, never a new tab and never a
      download.** Check all four pages that show one: the Expenses step (upload box, the
      Expense Details tiles, and a non-image/non-PDF receipt), the report detail page's
      **Files** column, `edit_report`'s existing *and* just-picked files, and the index
      page's new-row **Preview** button. A file that cannot be drawn shows the viewer's own
      sentence rather than offering itself for download.
- [ ] Escape closes the receipt viewer only — the Expense Details modal under it stays
      open, and a second Escape closes that.
- [ ] `account_id`, `contact_id`, `account_code`, `contact_name` are derived properties, not
      columns — a Xero id matching no synced row logs a warning and leaves the link null
      rather than erroring (only visible from a DB check).
- [ ] **DB:** `SELECT account_id, contact_id, amount FROM pettycashv3.report_expense WHERE
      report_id = '<id>';`

## Step 4 — Deposit

- [ ] The page shows the cash on hand before you enter today's bank deposit.
- [ ] **DB:** `SELECT bank_deposit FROM pettycashv3.report WHERE id = '<id>';`

## Step 5 — Cash Count

- [ ] The calculator modal totals the denominations counted, from the company's currency's
      own denomination catalogue.
- [ ] A discrepancy reason is required only when the counted total and the book figure
      disagree.
- [ ] Counting every denomination as zero is distinguishable from never visiting the step —
      `completed_sections` records the visit; a genuine all-zero count still stores rows with
      `quantity = 0`.
- [ ] **DB:** `SELECT cash_id, quantity, cash_value FROM pettycashv3.report_cash_count WHERE
      report_id = '<id>';` and `SELECT discrepancy_amount, discrepancy_type,
      discrepancy_reason FROM pettycashv3.report WHERE id = '<id>';`

## Step 6 — Ending

- [ ] The summary matches `opening + cash_addition + cash_sales − expenses − bank_deposit`
      (the closing balance the cash count was compared against).
- [ ] **Finish** flips the report to submitted — the figures here match the Submitted page
      and the exports immediately afterward.
- [ ] `POST /report/<id>/convert-to-draft` reopens only the **most recent** submitted report;
      an older one is refused.
- [ ] **DB:** `SELECT status, submitted_at FROM pettycashv3.report WHERE id = '<id>';` — both
      set together by Finish.

## Out of scope for this checklist

- **Petty-cash settings, receipts/attachments as a feature, report history/exports, Xero
  publish/republish, the Submitted page, the modules/subscription reads, the sidebar,
  modals, toasts, the terms gate, expense AI** — no checklist items yet; see the table in
  [README.md](README.md) for where each is documented, and add a section here when that
  surface needs one (one checklist per repo).
- **Finalize and the All Set step (step 9)** — served by minty-onboarding-api, not Minty;
  its own checklist (`minty-onboarding-api/docs/features/qa-checklist.md`) covers it,
  including the "never land a test session on saved step 9" trap.
- **Required-field marks** — Flask's ~33 mandatory-but-unmarked fields were audited on
  2026-10-09 when the four Next.js frontends were marked, and deliberately left alone here.
  The findings, the two existing Flask markers, the Bootstrap-only trap and three bugs the
  audit turned up are in [required-field-marks.md](required-field-marks.md).
- **The email OTP's actual inbox delivery** — ends at a real mailbox; this checklist only
  covers what Minty does before and after the mail is sent.

## See also

- [authentication.md](authentication.md) — the system-wide auth picture; §2.2 (OTP), §6
  (hand-off tokens), §9 (shared `SECRET_KEY`).
- [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md) — the launch URL,
  the `/api/onboarding/*` dual-backend table, and Minty's side of the hand-off.
- [xero-integration.md](xero-integration.md) — §1 "Connecting" and §2 "Tokens" for the
  connect/callback mechanics this checklist exercises.
- [report-wizard.md](report-wizard.md) — the full route/model reference for the 6 steps,
  plus `templates/components/stepper.md` for the stepper component itself.
- [README.md](README.md) — the full feature index; the surfaces this checklist doesn't
  cover yet are all listed there.
- `minty-onboarding-api/docs/features/qa-checklist.md` — the sibling checklist on the
  other side of the handoff (the wizard's own endpoints, the step-9 trap, finalize).
