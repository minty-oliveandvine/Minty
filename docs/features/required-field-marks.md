# Required-field marks — the Flask audit (deferred)

Audited 2026-10-09 alongside the change that marked the four Next.js frontends. **No Flask file
was touched**, by the owner's decision: this records what is here so it is picked up rather
than re-discovered.

The rule the other repos now follow: **a mandatory field shows a red `*` from the moment the
form opens, and its control turns red only once a submit has been refused.** The mark is
`aria-hidden` and requiredness is announced on the control (`aria-required`, or the native
`required`), because an asterisk read aloud is "star".

## Flask already has the convention — twice

| Marker | Where it lives | Used by |
|---|---|---|
`<span class="text-red-500">*</span>` | inline, Tailwind pages | `entity/entity_create.html` (107, 117, 136, 155, 165), `report/expense.html` (258, 283, 300, 318, 328), `report/index.html` (276, 303, 330), `entity/entity_dashboard_v2.html` (2164, 2175, 2196) |
`<span class="pcs-required">*</span>` | `static/css/settings_page.css:459` (`color: #e7000b`) | `entity/partials/xero_account_mapping_cards_classic.html:20` only |

**`templates/entity/entity_create.html` is the reference implementation**: every field has
`required`, the asterisk, and a `{{ error }}` block in `text-red-500`.

`report/expense.html:258` is the only *dynamic* marker — `#receiptRequiredMark` is hidden once
files are attached (`expense.html:3070-3073`) and restored at `3266-3267`.

## The trap before anything else

**Six templates load Bootstrap 4 only, with no Tailwind, so `text-red-500` silently does
nothing there** and the mark must be `text-danger` (or `pcs-required`):
`login.html`, `index.html`, `edit_report.html`, `report_detail.html`, `find_user.html`,
`reset_token.html`, `download_statements.html`, `admin.html`.

There is also **no shared label partial** — `templates/components/components.html` holds only
`xero_button`, `header`, `logo` and `toast` — so a marker is per-template until one is added.

## Mandatory but unmarked — ~33 fields

| Page | Fields | How requiredness is enforced |
|---|---|---|
`login.html` | Username (105), Password (109), reset-modal Username (174), reset-modal Email (184) | WTForms `DataRequired` (`blueprints/auth/forms.py:7-10`); the modal pair is native `required`. **4** |
`index.html` | Opening Drawer Balance (242/256), Addition to Cash Balance (262/270), Transaction Date (287/301), Bank Deposit (513/521) | native `required`; `static/js/scripts.js:682-700` already adds `is-invalid` + "This field is required." after submit, so only the up-front mark is missing. **4** |
`entity/settings_entity.html` + `partials/xero_account_mapping_cards_classic.html` | the 9 in `REQUIRED_MAPPING_FIELDS` (`xero_mapping_classic_script_fragment.html:125-137`), plus Select Country (111) and Select Currency (121) | hard save-blocker client *and* server; red borders already appear (`_setMappingHighlight`, fragment 148). The 9 are `<h3 class="pcs-field-title">` headings, not `<label>`s. **11** |
`find_user.html` | First Name (190), Last Name (196), Entity (202) | WTForms `DataRequired` (`blueprints/user_management/forms.py:7-13`) — server-only, no client hint. **3** |
`reset_token.html` | New Password (60), Confirm Password (66) | WTForms `DataRequired` / `EqualTo` (`auth/forms.py:20-23`). **2** |
`download_statements.html` | Start Date (46), End Date (50) | native `required`. **2** |
`report/cash_count.html` | the discrepancy description (textarea at 283) | conditionally required when the discrepancy exceeds 0.01 (1165-1180). **See the bug below.** **1** |
`report/expense.html` | submitted-report edit modal: Supplier (3443), Account Code (3447) | `expense_validate_drafts` (`blueprints/report/routes/api.py:1888`) rejects a null `contact_id`/`account_id`. **2** |
`entity/entity_dashboard_v2.html` | the `bankConfirm` radio group (223-231) | JS refuses at 1000-1004. **1** |
`entity/partials/electronic_delivery_section.html` | Method (44), Name (52) | gate the Add button. **2** |
`edit_report.html` | Opening Drawer Balance (153/160) | native `required` but also `readonly`, so unreachable-empty. **1 nominal** |

### Worth doing first

1. **`login.html`** — every user, every session, 4 unmarked required fields. Bootstrap-only, so
   `text-danger`.
2. **`report/cash_count.html`'s discrepancy description** — the only conditionally required
   field in the wizard, and see the bug below.
3. **The Xero mapping's 11** — a hard save blocker with red borders but no up-front marker.
4. **`index.html`'s 4** — the invalid state already exists; only the mark is missing.

## Three bugs found in the same audit (none fixed)

1. **`report/cash_count.html` — a marker that was never rendered.** Lines 775, 790 and 913 all
   call `document.getElementById('descriptionRequired')` to show and hide a conditional
   asterisk, but **`id="descriptionRequired"` exists nowhere in the file** (0 matches). The
   field it belongs to (the discrepancy description, textarea at 283) also has **no `<label>`
   at all** — only a placeholder. So the marker was designed, wired up, and never added.
2. **`report/deposit.html` — Deposit Amount is neither marked nor enforced.**
   `validateDepositAmount()` (539-551) is defined and **never called**; the submit paths at 343
   and 379 call only `validateCurrentBalance()`, and the server defaults it
   (`routes/deposit.py:244` `safe_float(request.form.get("bank_deposit", 0))`).
   **Do not simply start calling it** — a day with no bank deposit is legitimate, so enforcing
   it would block a real flow. The honest fix is to delete the dead function. The same shape
   sits at `cash_count.html:1250`, whose `'Please enter Safebox Cash Balance'` is unreachable
   behind an always-true stub (1099-1106).
3. **`report/index.html` — marked but not required**, the inverse problem. Lines 276, 303 and
   330 carry asterisks on a form whose submit handler (492-497) calls `preventDefault()` and
   redirects to `/report/resume` without reading a single field; `#amountError` (295) and
   `#bankError` (322) are never shown. While there: `id="amountError"` is **duplicated** at 295
   and 341, and `cancelBtn` / `proceedBtn` are duplicated at 248/347 and 254/354.

## See also

- `minty-payment-request-web/docs/features/payment-requests.md` — the convention as built,
  including why the mark is `aria-hidden`.
- `minty-onboarding-web`'s `.req` class (`app/globals.css`) — documented there as "shared by
  every form", and the nearest thing to a house style.
