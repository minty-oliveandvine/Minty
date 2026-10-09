# Xero integration — connecting a company, syncing its books, publishing the day

Two things share the word "Xero" and must not be confused: **signing in with Xero** (an
identity, [authentication.md](authentication.md) §2.3) and **connecting a company to a
Xero organisation** (this document). Code: `blueprints/xero/` (routes, `services/publish.py`,
`services/integration.py`, `services/settings.py`, `services/publish_record.py`),
`services/auth/token_service.py` (tokens), `blueprints/entity/services/settings.py` (the
sync), the Entity & Integration tab (minty-web's since phase 2, over `entity/routes/hub_settings.py`) and `report/submitted.html`.

## 1. Connecting

`GET /xero_connect?entity_id=…` (an admin, `XERO_SETTINGS_UPDATE`) sends the browser to
Xero's authorize page with the app's **minimal granular scope set** (`tests/test_xero_scopes.py`
pins it and keeps `/xero_reconnect` identical — the composite `accounting.transactions`
scope is rejected by Xero for this app, so do not collapse them). The OAuth `state`
carries the entity (`<base>:<entity_id>:<name>[:<initiator>]`) because the Flask session
does not survive the round-trip. `GET /callback`:

1. exchanges the code (`integration.get_auth_token`), stores the bundle on the
   **connecting user's** `user_token` row (`upsert_user_token`) and records
   `entities.connected_by_user_id`;
2. binds the tenant: `entities.xero_org_id`, `xero_tenant_name`, `status = connected`
   (`EntityStatus`: `onboarding` / `connected` / `disconnected`). One organisation may be
   connected to one company at a time, and connecting it elsewhere is **refused** — see
   §1.1;
3. starts the **background sync** (`sync_all_accounts_and_contacts_background`, one thread,
   three sections): contacts → `xero_contact_sync`, the chart of accounts → `account_info`
   (+ `entity_account_xero` for the expense picker) and the bill account codes →
   `entity_bill_account_xero` (minty-payment-request-api's table; Minty writes it, there is no FK
   across that boundary by design). `GET /api/entity/<id>/xero-sync-status` reports the
   sync's progress for the settings page; the cached rows are also what the pages use when
   Xero is down.

### 1.1 One organisation, one company — and the move (2026-10-09)

`_live_org_claimant` (`xero/routes/routes.py`) decides this on every connect and reconnect.
Every company whose `xero_org_id` matches the tenant the person picked is examined:

| the other company's claim | what happens |
|---|---|
| `status = "disconnected"` | a stale claim our own status disowns: cleared, connect allowed |
| held by **another** user | live-probed with **its own** connector token; a live claim **blocks** |
| held by the **same** user | **blocks** without probing — the token is shared, so the probe cannot answer |
| no connector / probe fails / tenant gone | a ghost: reconciled, connect allowed |

**The same-user case used to be the silent one.** It unlinked the other company and let the
connect through, so the person saw the ordinary "Connected to Xero!" message and no error at
all, while their other company lost Xero with nobody told. It blocks now, and freeing an
organisation is always asked for.

**The empty auth event is the same story, and it used to lie.** Xero grants nothing when the
organisation picked is already connected to the app, so `GET /connections?authEventId=<id>`
comes back **empty** and the guard above never runs — the callback bailed out first and said
*"No organization was picked on Xero's approval screen"*, blaming the person for a choice they
had made (the owner reported exactly this on 2026-10-09). That branch now asks what the token
can see at all (`_all_connections` → `_claimed_elsewhere`, the unfiltered `/connections`) and
names the holder; only when the token sees no organisation does it still say nothing was
picked. **It revokes nothing** — what the token sees was granted by earlier auth events, so
handing one back would disconnect the other company.

A refusal `_revoke_new_grant`s (the OAuth exchange has already completed, so the grant exists
on Xero's side — except on an empty auth event, where there is no new grant) and then
`_refuse_conflict` flashes one sentence AND signs the holder into the redirect — `sign_conflict` / `read_conflict` (`entity/services/entity_list.py`, its own salt,
the notices' 5-minute life). `?xero_conflict=` rides `_to_hub_tab` to minty-web, where
`/api/me/company/integration` answers it as `xero_conflict` (`_conflict` re-settles it against
the database: the holder must still hold something, must not be the company being viewed, and
`can_move` is re-read). Onboarding gets `conflict_entity_id` + `conflict_can_move` on its
return instead. Both then draw the **"That Xero organisation is taken"** dialog.

**The move** the dialog offers is two steps, because the refused attempt's grant was handed
back and there is no token left to reuse (and storing one against a refused connect is not
something to keep):

1. free the organisation — `POST /api/me/company/xero/release` (minty-web) or
   `POST /api/onboarding/xero/release` (the wizard), **authorized on the company being
   freed**, not the one being viewed: `XERO_SETTINGS_UPDATE` there, its own Disconnect's
   permission. Both defer to `disconnect_entity_from_xero`, so it ends `disconnected` —
   the wizard's own `xero/disconnect` leaves `onboarding`, which is wrong for a live company;
2. then the browser goes back through `/xero_reconnect` (or `/xero_connect`) for this company.

Without the permission there is no move, only the company to ask. Nothing is written by
refusing, and a failed release keeps the dialog open to retry. Pinned by
`tests/test_xero_conflict_guard.py`, `tests/test_hub_company_settings.py` and
`tests/test_char_entities.py`; the dialogs by minty-web's `screens.test.tsx` and
minty-onboarding-web's `e2e/xero.spec.ts`.

The sync **replaces** the cached rows, and `entity_pettycash_settings` has nine FKs into
them (`ON DELETE SET NULL`), so a re-sync after an organisation switch clears the petty-cash
mapping — it must be picked again (§3). Disconnecting (`xero/services/disconnect.py`, from
minty-web's Entity & Integration tab through `POST /api/me/company/xero/disconnect` since phase 2 -
the session `POST /entity/settings/xero/disconnect` is gone; it was a GET until 2026-10-05, so any
link could disconnect a company) revokes the grant at Xero, clears the tenant and the cache, and
now asks first in the tab. `/remove/connections/all` (a GET that dropped EVERY Xero organisation of
the user), `/api/refresh_xero_token` (a GET that rotated the refresh token and never stored
the new one) and `/debug/xero-settings/<id>` were deleted on 2026-10-05; none had a caller.

## 2. Tokens

Per-user bundles in `user_token`; a company publishes with its connector's token, the
current user's as a logged fallback (`resolve_xero_token`). **Only Flask refreshes** and it
serialises refreshes per bearer with a Postgres advisory lock held across the HTTP call;
minty-payment-request-api obtains live tokens from `POST /api/internal/xero/token` (a 60-second
assertion JWT over the shared `SECRET_KEY`, scope `xero-access-token`, the entity in the
claims). Xero access tokens live ~30 minutes; `after_request` refreshes an expired one on
normal traffic. Details and the reasons in [authentication.md](authentication.md) §7.

## 3. The petty-cash mapping

`entity_pettycash_settings` names the accounts and contacts every publish posts to:
petty cash (the cash-on-hand bank account), the bank account for deposits, the cash-sale
revenue account, the discrepancy account and its bank account, the director's account for
floats; and three contacts — the cash-sale customer, the director, the discrepancy
contact. Petty Cash Settings (`/entity/<co>/settings/petty-cash`) offers the synced rows; `check_entity_xero_settings_complete` refuses a publish while any
is missing. The seed (`scripts/e2e_seed.py`) writes placeholders for an unconnected shop
and leaves a connected shop's real mapping alone.

**`account_info.status` means "still active in Xero", nothing else** (2026-10-01). Xero's
ACTIVE accounts are upserted ACTIVE; an account archived in Xero is deleted by the sync. Petty
Cash's expense-code ticks live only on `entity_account_xero.is_active`. Until 2026-10-01 the
tick save also wrote `status`: it marked every non-bank/revenue account INACTIVE and brought back
only the ticked codes. The mapping dropdowns list only ACTIVE rows, so the Director's liability
accounts and any unticked Discrepancy code vanished whenever the background re-sync could not
run (disconnected, token expired), and the save then said "Please select: Discrepancy account
code". The mapping lists also always include each saved choice
(`xero_mapping_form_context.py`), and the page logs a console error if a saved choice still
fails to land in its field. Publish checks `status` only, so an unticked code still publishes.

## 4. Publishing a report

`POST /report/submitted/publish_to_xero?entity_id=&report_id=` (`REPORT_PUBLISH` =
accountant and up):

1. resolves the token, checks the mapping is complete, re-syncs a stale `status`;
2. refuses expense lines that point at **system accounts** (the mapped control accounts;
   `validate_expenses_for_system_accounts`) with a 400 that names them;
3. takes the report's row lock — `SELECT … FOR UPDATE NOWAIT` **`OF report`** (the creator
   and their token are outer-joined by eager loads; Postgres cannot lock their side) — a
   second click while it runs gets 409; sets `publishing_status = publishing`;
4. answers **202** and runs `process_xero_integration_background` in a thread; the page
   polls `GET /api/report/<id>/publishing_status` (`publishing_status`,
   `xero_integrated_yes`, `failure_reasons`).

The worker (`xero_integrated_module`) posts five modules, each `(succeeded, failed)`:

| Module | What Xero receives |
|---|---|
| `withdrawal_from` | the float added/withdrawn at the start — a **bank transfer** between the director's or bank account and petty cash |
| `invoices` | the day's cash sales — an **ACCREC invoice** to the cash-sale contact, paid into petty cash |
| `expenses` | one **SPEND bank transaction** per expense line, from petty cash to the supplier and expense account, in batches of 5; the receipt goes up through the **Files API** and is associated with the transaction (`upload_each_file`); the line is found by report + item + amount + account code + contact through the synced rows (`find_expense_line`) |
| `deposit` | the cash banked — a bank transfer petty cash → bank (reference `MT<yyyymmdd>Deposit`) |
| `discrepancy` | a short/over — a bank transaction against the discrepancy account |

Every id Xero returns is kept in `xero_report_sync.xero_response_text` as JSON by
`publish_record.py` (with the org id), so a **republish updates in place** (`POST
/BankTransactions/{id}`, `POST /Invoices/{id}`) and delete-recreates the transfers
(`POST /BankTransfers/{id}` with `{"Status": "DELETED"}` in the body); a record from a
different organisation is ignored, and objects removed from the report are swept
(`_sweep_removed_objects`). Success sets `report.status = published`, `published_at`,
`xero_integrated`, `publishing_status = completed`; any failure leaves `failed` with the
per-module reasons, and the report can be published again. (`integration.get_organisation_lock_dates`
exists but nothing calls it on this side — the lock-date check is minty-payment-request-api's, on
bill publishes; a report dated inside a locked period is refused by Xero itself.)

A report that has been to Xero and is then edited comes back to `submitted` with
`xero_integrated` cleared; its submitted page shows the **republish warning** (a second
publish would duplicate what the record no longer covers). A never-published report gets
the plain button — `publishing_status` is NOT NULL and `unpublished` is that state.

## 5. Other endpoints

`GET /api/xero/bank-transactions/latest/<entity_id>` and
`POST /api/xero/bank-transactions/update/<entity_id>` (edit a deposit already in Xero —
`update_after_deposit_change`), `GET /api/entity/<id>/xero-data` (the cached accounts and
contacts as JSON; from the database when the token no longer works. A bank account carries
only `MaskedBankAccountNumber`, `****` + the last four - the full number never leaves the
server, since 2026-10-01), `POST /api/entities/<id>/billing/sync-*` (the three sync triggers
minty-payment-request-api calls, JWT-authenticated — `blueprints/entity/routes/billing_sync.py`).

## 6. Tests

`tests/test_xero_scopes.py`, `tests/test_char_report_lifecycle.py` (the publish hand-off
with Xero stubbed, the lock, the expense-line lookup by Xero ids), `tests/test_char_xero_sync.py`
and `tests/test_char_xero_tokens.py` (the cache and the token rules), `tests/test_xero_report_republish.py`,
`tests/test_xero_org_switch_invalidation.py`, `tests/test_xero_entity_connect_race.py`,
`tests/test_xero_contact_sync_no_mass_delete.py` (the republish, org-switch and sync
guards), `tests/test_xero_conflict_guard.py` with `tests/test_hub_company_settings.py` and
`tests/test_char_entities.py` (one org = one company, and the move — §1.1),
and — the only thing that talks to Xero — `e2e/04_xero_publish.spec.ts` with
`E2E_XERO=1` against a shop linked to a Demo Company (what it found on 2026-09-18 is in
`docs/modernisation/modernisation_plan.md`, Phase E).
