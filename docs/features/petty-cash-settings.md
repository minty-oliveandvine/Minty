# Petty-cash settings — currency, denominations, sales methods, the Xero mapping

What a company configures before its first report. **The screen is minty-petty-cash-web's
Petty Cash Settings** (`/entity/<shortid>/<name>/settings/petty-cash`; its `docs/features/`), over
minty-petty-cash-api; onboarding Steps 5–7 write the same rows through `/api/onboarding/*`.
Flask's Jinja page and its form POST were deleted on 2026-10-20; its address
`GET /entity/<co>/settings/petty-cash` (`entity_settings_entity` in
`blueprints/entity/routes/settings.py`: `COA_VIEW`, Petty Cash on) stays and hands over through
`/handoff/petty-cash-web`. Flask's bearer copy of the API serves the same screen's calls
(`GET /settings`, `PUT /settings/country`, the `/sales-methods` routes, `GET /settings/xero`,
`PUT /settings/xero/mapping`, `PUT /settings/xero/account-codes`; [petty-cash-api.md](petty-cash-api.md)),
and minty-petty-cash-api forwards the three Xero cards to `POST /api/internal/xero/petty-cash-settings`.
Models: `blueprints/entity/models/` (`currency_info`, `cash_info`, `entity_cash_setting`,
`entity_cash_detail`, `sale_info`, `entity_sale_setting`, `entity_pettycash_settings`,
`country_info`); services: `blueprints/entity/services/payment_methods.py`,
`blueprints/entity/services/xero_mapping.py`, `blueprints/entity/services/xero_account_mapping_post.py`,
`blueprints/report/services/cash_denominations.py`, `blueprints/xero/services/settings.py`.

## Country and currency

`entities.country_code` → `country_info`, `entities.currency_id` → `currency_info` (ISO
code, symbol, decimal places). **Every money figure a company sees is formatted in its
currency** — never the report's stored code and never a default — so the registries must
exist before a company is created (the onboarding wizard's Step 1 reads them from
`/api/onboarding/countries` and `/currencies`). A change is
`apply_country_currency_selection` (`ENTITY_UPDATE` and `COA_UPDATE/CREATE/DELETE`), checked by
`country_currency.checked_country_currency` (an unknown country or currency is refused), which
minty-web's Entity & Integration save shares.

## Denominations (the cash count)

`cash_info` is the catalogue of a currency's notes and coins, unique on (currency, value), so
a note and a coin of the same face value cannot both exist (HKD's $10 is a note). c5a05 keyed
it on type too and made `type` NOT NULL on 2026-10-13; that was withdrawn on 2026-10-14
(`migrations/c5a05_down.sql`).
`entity_cash_setting` holds
the company's own list: setting a currency (creation, the onboarding wizard, Petty Cash
Settings, the hub's Entities & Integration save) writes one row per active denomination of it and drops
any other currency's rows, keeping rows already there so the company's on/off and order
survive a re-save (`entity/services/cash_settings.py`; minty-onboarding-api has the same
rule). A denomination with no row — every one for a company created before 2026-10-12, or one
added to the currency later — counts as on;
`entity_cash_detail` is the company's cash in stock: per denomination, the MONEY its latest
**submitted** report counted (`cash_instock`; `cash_type` copied from `cash_info`). Its rows
are made and rebuilt only by `refresh_cash_stock` (`report/services/cash_denominations.py`)
on submit, revert to draft, delete and a submitted report's cash-count edit - one per active
denomination of the current currency, other currencies' rows removed, 0 where not counted.
Onboarding never writes it; a draft never moves it.
`resolve_denominations_for_entity` in `cash_denominations.py` is the one resolver; the cash
count reads from it.

## Sales methods

The Sales stage shows cash, the **electronic** methods and the **delivery** platforms the
company chose (`SaleType`: `electronic` / `delivery` / `other`). `sale_info` is the shared
catalogue (Visa, Alipay, Foodpanda, …), `entity_sale_setting` the company's selection with
its order:

- `GET /api/entities/<id>/payment-methods` — the company's list;
  `…/payment-methods/available` — catalogue rows it has not added yet, grouped by type;
- `POST` add, `PUT …/<method_id>` rename/retype, `DELETE …/<method_id>`,
  `PUT …/payment-methods/reorder` (refuses an empty list);
- `replace_sales_methods(user_id, entity_id, electronic, delivery)` reconciles the whole
  set to two name lists (what the wizard's Step 5 and the seed use).

The bearer API's `/sales-methods` routes do the same for minty-petty-cash-web: a catalogue
method is added by its id, so "Viza" never mints a second row, and a rename of a method other
companies share is refused (409).

`SALES_METHOD_*` permissions: accountant and up. A method with sales already recorded
against it stays in the report history (the report row keeps its own name/amount).

## The Xero mapping (accounts and contacts)

The six accounts and three contacts a publish posts to, chosen from the synced chart and
contacts — [xero-integration.md](xero-integration.md) §3, read and saved through
`entity/services/xero_mapping.py`: the connection is checked live (Xero's `/connections`) and the
lists refreshed from Xero when it is. A mapping choice the lists do not offer is refused ("Choose
the … from the list.") - an unoffered id used to be saved as a made-up "Unknown Account" /
"Unknown Contact" row (`tests/test_xero_mapping_state.py`). Without a live connection the mapping
and the account codes are not offered (409). A new Xero contact is the bearer API's
`POST /suppliers` (`entity/services/suppliers.py`).

## Account codes for the expense picker

`entity_account_xero.is_active` decides which synced expense accounts the Expenses stage
offers (`COA_*` permissions to change); the bill module's own list is
`entity_bill_account_xero` (minty-payment-request-api's, synced by Minty). The tick is stored there ONLY:
since 2026-10-01 a save (and onboarding Step 5, `sync_entity_account_xero_active`) never writes
`account_info.status`, which is Xero's own "still active". Before, a save marked unticked codes
and every liability account INACTIVE, so with Xero disconnected the Discrepancy and Director
fields lost their saved choice (see `docs/features/xero-integration.md` §3).

**At least one stays ticked** (2026-10-01): a save that ticks none would switch every code off,
and a petty cash expense can only use the codes ticked here. The save is refused ("Pick at least
one account code.", 422) before anything is written (`xero_mapping.save_account_codes`, over
`saveable_account_codes` in `blueprints/entity/services/settings.py`: rows WITH a code — a row
without one can never be ticked back on, so it never counts and is not offered). A company with
no codes saves as before. Onboarding's Step 5 has the same rule since
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

## Tests

`tests/test_petty_cash_api_settings.py` and `tests/test_petty_cash_api_xero_settings.py` (the
screen's calls: country and currency, the sales methods, the mapping and the account-code rule),
`tests/test_petty_cash_internal_xero_settings.py` (the internal route),
`tests/test_xero_mapping_state.py`, `tests/test_xero_data_and_onboarding_codes.py` (the mapping
lists' database fallback and masked bank numbers, onboarding's codes rule),
`tests/test_payment_methods_permissions.py`, `tests/test_char_xero_sync.py` (the mapping and the
cache), `tests/test_petty_cash_web_handoff.py` (the address's hand-off). The screen is tested in
minty-petty-cash-web.
