# Petty-cash settings — currency, denominations, sales methods, the Xero mapping

What a company configures before its first report, all on `/entity/<id>/settings/xero`
(the "Petty cash settings" side of `templates/entity/settings.html`) and during
onboarding Steps 5–7 (the wizard writes the same rows through `/api/onboarding/*`).
Models: `blueprints/entity/models/` (`currency_info`, `cash_info`, `entity_cash_setting`,
`entity_cash_detail`, `sale_info`, `entity_sale_setting`, `entity_pettycash_settings`,
`country_info`); services: `blueprints/entity/services/payment_methods.py`,
`blueprints/report/services/cash_denominations.py`, `blueprints/xero/services/settings.py`.

## Country and currency

`entities.country_code` → `country_info`, `entities.currency_id` → `currency_info` (ISO
code, symbol, decimal places). **Every money figure a company sees is formatted in its
currency** — never the report's stored code and never a default — so the registries must
exist before a company is created (the onboarding wizard's Step 1 reads them from
`/api/onboarding/countries` and `/currencies`). Changing the country is
`POST /entity/settings/entity/<id>` (`ENTITY_UPDATE`).

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
  `…/payment-methods/available` — catalogue rows it has not added yet, grouped by type
  (matched by name so a rename does not mint a near-duplicate);
- `POST` add, `PUT …/<method_id>` rename/retype, `DELETE …/<method_id>`,
  `PUT …/payment-methods/reorder`;
- `replace_sales_methods(user_id, entity_id, electronic, delivery)` reconciles the whole
  set to two name lists (what the wizard's Step 5 and the seed use).

`SALES_METHOD_*` permissions: accountant and up. A method with sales already recorded
against it stays in the report history (the report row keeps its own name/amount).

## The Xero mapping (accounts and contacts)

The six accounts and three contacts a publish posts to, chosen from the synced chart and
contacts — [xero-integration.md](xero-integration.md) §3. A company can also create a new
Xero contact from Minty (`POST /entity/contact/create`, `POST /report/expense/create_contact`).

## Account codes for the expense picker

`entity_account_xero.is_active` decides which synced expense accounts the Expenses page
offers (`COA_*` permissions to change); the bill module's own list is
`entity_bill_account_xero` (billing-backend's, synced by Minty).

## Tests

`tests/test_char_entities.py`, `tests/test_char_sales_methods.py`,
`tests/test_payment_methods_permissions.py`, `tests/test_char_report_lifecycle.py` (the
cash count with the currency's denominations), `tests/test_char_xero_sync.py` (the mapping
and the cache);
`e2e/03_settings.spec.ts` (the mapping and the sales-methods editor, end to end into the
Sales page).
