# Expense AI — reading a receipt into the expense form

When a receipt is attached on minty-petty-cash-web's Expenses stage, a vision model reads it and the form's
fields (amount, date, description, supplier, account) are **pre-filled as suggestions**
the person confirms; nothing is saved without their **Add**, a supplier is never created
automatically, and the form stays editable while the read runs (or fails) in the
background. The product description is `docs/expense_ai/Stage 1 AI Implementation in Expense.md`;
the technical one `docs/expense_ai/Stage 1 Expense Implementation Technical.md`.

## Where it lives

- `POST /api/internal/petty-cash/expense-extract` (`blueprints/report/routes/expense_ai.py`) —
  where minty-petty-cash-api (which holds no model code) forwards a receipt under a scoped
  service assertion, and `POST /api/petty-cash/v1/companies/<id>/reports/expenses/extract`, the
  same reading through Flask's own copy of the Petty Cash API (`docs/features/petty-cash-api.md`).
  The receipt plus the company's active suppliers and expense accounts go in; structured
  predictions with confidence scores come back. **Constrained matching**: the model is given the
  company's own lists, so its supplier and account suggestions are existing rows, not free text.
  Both end in `report/routes/expense_ai.py::read_receipt`, so there is one log line and one
  answer shape. The session route `POST /report/expense/extract` went with Flask's pages on
  2026-10-20.
- `blueprints/report/services/expense_ai.py` — the provider call, the prompt, the
  rate limits, the confidence bands and the size/time limits. Still the ONLY module that
  talks to the model.
- `flask expense-ai check` (`cli/expense_ai.py`) — one round-trip call from wherever the
  code runs, to prove the configuration.
- The screen is minty-petty-cash-web's: it marks a suggested value visibly, clears it with one
  tap and never overwrites what the person already typed.

## Provider

**Gemini through the direct API, paid tier** (a decision of 3 September 2026); the Vertex AI
route (`asia-southeast1`, IAM instead of a key, in-region processing) remains implemented
and is selected automatically when `GOOGLE_CLOUD_PROJECT` is set. The paid tier settles
that content is not used to train and no human reads it; it does **not** settle
residency — receipts cross a border they otherwise do not — which belongs in the customer
disclosure. The free tier is unusable for customer receipts, and because the SDK cannot
tell the tiers apart the tier is stated in configuration and
`_check_tier_matches_reality()` shouts when Google's quota errors contradict it.

## Configuration (all `EXPENSE_AI_*`)

| Variable | Meaning |
|---|---|
| `EXPENSE_AI_ENABLED` | off unless `1` — the route answers as disabled and the app shows no suggestions |
| `EXPENSE_AI_MODEL` (`gemini-3.5-flash`), `EXPENSE_AI_THINKING_LEVEL` (`low`), `EXPENSE_AI_MAX_OUTPUT_TOKENS`, `EXPENSE_AI_TIMEOUT_S` | the call |
| `EXPENSE_AI_DIRECT_TIER`, `EXPENSE_AI_ALLOW_DIRECT_API`, `EXPENSE_AI_USE_VERTEX`, `EXPENSE_AI_LOCATION`, `GOOGLE_CLOUD_PROJECT` | which route, and the tier assertion |
| `EXPENSE_AI_RATE_USER_PER_MIN`, `EXPENSE_AI_RATE_ENTITY_PER_HOUR` | in-process rate limits per person and per company |
| `EXPENSE_AI_CONF_HIGH`, `EXPENSE_AI_CONF_MEDIUM` | the confidence bands the app colours |
| `EXPENSE_AI_MAX_FILE_MB` | the receipt size cap |

## Tests

`tests/test_expense_ai.py` (the extraction contract with the provider stubbed, the limits,
the disabled state); `tests/test_expense_ai_routes.py` (the API route and the internal route, the model stubbed: switched off, a checked suggestion, refusals, who may ask,
the assertion).
