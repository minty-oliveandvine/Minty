# Petty-cash settings — currency, denominations, sales methods, the Xero mapping

What a company configures before its first report: on **Petty Cash Settings**
(`/entity/<co>/settings/petty-cash`, `entity_settings_entity` in
`blueprints/entity/routes/settings.py`, template `templates/entity/settings_entity.html`) and
during onboarding Steps 5–7 (the wizard writes the same rows through `/api/onboarding/*`).
Models: `blueprints/entity/models/` (`currency_info`, `cash_info`, `entity_cash_setting`,
`entity_cash_detail`, `sale_info`, `entity_sale_setting`, `entity_pettycash_settings`,
`country_info`); services: `blueprints/entity/services/payment_methods.py`,
`blueprints/report/services/cash_denominations.py`, `blueprints/xero/services/settings.py`.

## The page

The one Flask settings page that stays (the user, 2026-09-30: app settings stay in their own
app; Users, Entity & Integration and the Module tab are minty-web's - since phase 2,
2026-10-05, for the first two). Since 2026-10-01 it is ONE template for every visit, built from the old
`?from=bills` page; the classic page and `settings_entity_bills_ui.html` are gone.

- **Chrome** = minty-web's Module page (`AppHeader` + `SettingsTabs`), which minty-payment-request-web's
  Payment Request Settings wears too: the way back, "Settings", the company, the initials (My Profile)
  and the ≡ (the menu), then the sticky pills Users · Entity & Integration · **Petty Cash
  Settings** · Payment Request Settings (when the payments module is on) · Modules - the Users, Entity &
  Integration and Module pills go through Flask's addresses, which hand over to minty-web.
- **Content** = Payment Request Settings' card (`AccountCodeSettings.tsx`), one per section, each
  collapsible: Country & currency · Xero account mapping · Electronic · Delivery · Petty Cash
  Account Code. One full-width **Save Changes** saves them all.
- **"‹ Back"** returns to the page the person came from, whichever app
  (`static/js/back_link.js`; its `href`, `company_home_url`, is the dashboard - or the payments
  app when Petty Cash is off - for a new tab). The `?from=bills` flag, which used to pick
  "‹ Payments" or "‹ Reports", the tabs' links and the sidebar's Settings, went on 2026-10-05; an
  old link that still carries it opens the same page.
- **Look**: plain CSS in `static/css/settings_page.css` under `#pc-settings`, with Tailwind v4's
  values written out (the page loads Tailwind v3 from a CDN only for the view-only notice and the
  classes the mapping script toggles; the shared toast styles itself).
- **Scripts**: `static/js/petty_cash_settings.js` runs the page (cards, pickers, account codes,
  sales methods, the save, the leave guard); the Xero mapping pickers are
  `templates/entity/partials/xero_mapping_classic_script_fragment.html`. The page's data reaches
  the script as JSON (`#pcs-config`) and is drawn as text.
- **Dialogs**: minty-web's design ([modals.md](modals.md)): "Leave without saving?" guards the
  page once it has loaded, and deleting a sales method asks first.
- **Disconnected from Xero**: said inside the mapping card (with the way to Entity &
  Integration to reconnect), not as a toast. A company that never connected sends no request
  for the Xero lists at all.

### The save, in order

1. The mapping check (`validateMappingBeforeSave`): once any mapping field is set, all nine must
   be.
2. **At least one account code** (below) — before anything is written.
3. The pending sales-method changes, each through its own API call (deletions, additions,
   renames, then the order). **Any that fails stops the save** and the toast names it ("I
   couldn't rename "Visa": This method is shared with other companies…"); nothing else is
   posted, and what did go through is remembered so the next Save redoes only the rest.
4. The form `POST /entity/<co>/settings/petty-cash`: country and currency, the mapping, and the
   ticked codes.

Save stays off until the Xero lists have loaded, while no account code is ticked, and while
nothing has changed (2026-10-05): the page measures its changes the way "Leave without saving?"
does (`isDirty` - the form's fields, the ticks and the sales methods against what it loaded), so
an edit put back by hand turns Save off again. The mapping pickers write their hidden `<select>`s
from script, which fires no event, so any click, key or blur on the page re-checks Save. An Enter
in a text box no longer submits the page (the boxes' own Enter still works: add a method, pick
a suggestion, finish a rename).

## Country and currency

`entities.country_code` → `country_info`, `entities.currency_id` → `currency_info` (ISO
code, symbol, decimal places). **Every money figure a company sees is formatted in its
currency** — never the report's stored code and never a default — so the registries must
exist before a company is created (the onboarding wizard's Step 1 reads them from
`/api/onboarding/countries` and `/currencies`). Changing the country is
`POST /entity/<co>/settings/petty-cash` (`ENTITY_UPDATE`).

## Denominations (the cash count)

`cash_info` is the catalogue of a currency's notes and coins; `entity_cash_setting` is a
per-company override (a row only where the company diverges — a company with none logs
every active denomination of its currency and picks up new ones automatically);
`entity_cash_detail` is the cash in stock per denomination after each count.
`resolve_denominations_for_entity` in `cash_denominations.py` is the one resolver; the
cash-count page's calculator and the `.docx` export's `qty*` placeholders read from it.

## Sales methods

The Sales page shows cash, the **electronic** methods and the **delivery** platforms the
company chose (`SaleType`: `electronic` / `delivery` / `other`). `sale_info` is the shared
catalogue (Visa, Alipay, Foodpanda, …), `entity_sale_setting` the company's selection with
its order:

- `GET /api/entities/<id>/payment-methods` — the company's list;
  `…/payment-methods/available` — catalogue rows it has not added yet, grouped by type;
- `POST` add, `PUT …/<method_id>` rename/retype, `DELETE …/<method_id>`,
  `PUT …/payment-methods/reorder` (refuses an empty list);
- `replace_sales_methods(user_id, entity_id, electronic, delivery)` reconciles the whole
  set to two name lists (what the wizard's Step 5 and the seed use).

On the page, every change is pending until Save. "Add New Method" opens the catalogue picker: a
method another company already uses is picked from the list (the page posts the catalogue's own
`value_name`, which the API matches first, so "Viza" never mints a second row); "+ Other" types
a new one. A rename of a method other companies share is refused by the API (409) — and now
says so. Rows: rename by clicking the name; Move up, Move down and Delete under the ⋮.

`SALES_METHOD_*` permissions: accountant and up. A method with sales already recorded
against it stays in the report history (the report row keeps its own name/amount).

## The Xero mapping (accounts and contacts)

The six accounts and three contacts a publish posts to, chosen from the synced chart and
contacts — [xero-integration.md](xero-integration.md) §3. A company can also create a new
Xero contact from Minty (`POST /entity/contact/create`, `POST /report/expense/create_contact`).
The pickers draw Xero's names as text.

## Account codes for the expense picker

`entity_account_xero.is_active` decides which synced expense accounts the Expenses page
offers (`COA_*` permissions to change); the bill module's own list is
`entity_bill_account_xero` (minty-payment-request-api's, synced by Minty). The tick is stored there ONLY:
since 2026-10-01 a save (and onboarding Step 5, `sync_entity_account_xero_active`) never writes
`account_info.status`, which is Xero's own "still active". Before, a save marked unticked codes
and every liability account INACTIVE, so with Xero disconnected the Discrepancy and Director
fields lost their saved choice and the save said "Please select: Discrepancy account code"
(see `docs/features/xero-integration.md` §3). A save no longer calls Xero at all.

**At least one stays ticked** (2026-10-01): a save that ticks none would switch every code off,
and a petty cash expense can only use the codes ticked here. The page greys Save and says why
beside it ("Pick at least one account code." - said once; the route's refusal uses the same
words); the route refuses it too, before anything is written
(`saveable_account_codes` in `blueprints/entity/services/settings.py`: the page's own list,
rows WITH a code — a row without one can never be ticked back on, so it never counts and is not
offered). A company with no codes saves as before. Onboarding's Step 5 has the same rule since
2026-10-01 (`save_account_codes` answers 400; it asks `listed_only=False`, because its codes
have no `entity_account_xero` row yet), and Payment Request Settings keeps at least one bill code
(minty-payment-request-api's PUT answers 409). Onboarding's Step 8 (the Payment Request codes) has it too:
the wizard shows the same words and does not post, and Flask's `save_bill_codes`
(`blueprints/entity/services/onboarding_bill_codes.py`) answers 400 when the company has codes
and none is ticked.

Step 8 is still answered by Flask (`/api/onboarding/bill-codes`, reached through
minty-onboarding-api's pass-through), although the table it writes, `entity_bill_account_xero`, is
minty-payment-request-api's. Kept there by decision (2026-10-01, "keep in flask for now"). When it moves
to minty-payment-request-api, the agreed shape is: Xero connect (Step 3, Flask) fills
`entity_bill_account_xero`, so minty-payment-request-api only ever reads its own table, and Flask's route
plus the pass-through are deleted.

**The first-ever save** (no `entity_pettycash_settings` row yet) used to switch every code on
and leave for the dashboard before the ticks were saved. Now the mapping service hands back to
the page (`defer_success_redirect`), the ticks and country/currency are saved, and THEN the
first save opens the dashboard (`?success=true`) as before.

The ticks are posted from the page's own set by a `formdata` listener (sorted, never blank),
not by the boxes — so a search that hides a ticked row, an Enter, or a Save before the list is
drawn cannot drop one. (Before this, each of those switched codes off.)

## Tests

`tests/test_petty_cash_settings_page.py` (the account-code rule, the first save, the two ways
in, the codes as data, view-only, the disconnected notice),
`tests/test_xero_data_and_onboarding_codes.py` (the mapping lists' database fallback and masked
bank numbers, onboarding's codes rule), `tests/test_char_entities.py`,
`tests/test_char_sales_methods.py`, `tests/test_payment_methods_permissions.py`,
`tests/test_char_report_lifecycle.py` (the cash count with the currency's denominations),
`tests/test_char_xero_sync.py` (the mapping and the cache);
`e2e/03_settings.spec.ts` (the mapping and the sales-methods editor, end to end into the
Sales page).
