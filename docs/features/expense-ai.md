# Expense AI — reading a receipt into the expense form

When a receipt is attached on the Expenses page, a vision model reads it and the form's
fields (amount, date, description, supplier, account) are **pre-filled as suggestions**
the person confirms; nothing is saved without their **Add**, a supplier is never created
automatically, and the form stays editable while the read runs (or fails) in the
background. The product description is `docs/expense_ai/Stage 1 AI Implementation in Expense.md`;
the technical one `docs/expense_ai/Stage 1 Expense Implementation Technical.md`.

## Where it lives

- `POST /report/expense/extract` (`blueprints/report/routes/expense_ai.py`) — the receipt
  plus the company's active suppliers and expense accounts go in; structured predictions
  with confidence scores come back. **Constrained matching**: the model is given the
  company's own lists, so its supplier and account suggestions are existing rows, not
  free text.
- `blueprints/report/services/expense_ai.py` — the provider call, the prompt, the
  rate limits, the confidence bands and the size/time limits.
- `flask expense-ai check` (`cli/expense_ai.py`) — one round-trip call from wherever the
  code runs, to prove the configuration.
- The page: `templates/report/expense.html` marks a suggested value visibly, clears it
  with one tap and never overwrites what the person already typed.

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
| `EXPENSE_AI_ENABLED` | off unless `1` — the route answers as disabled and the page shows no suggestions |
| `EXPENSE_AI_MODEL` (`gemini-3.5-flash`), `EXPENSE_AI_THINKING_LEVEL` (`low`), `EXPENSE_AI_MAX_OUTPUT_TOKENS`, `EXPENSE_AI_TIMEOUT_S` | the call |
| `EXPENSE_AI_DIRECT_TIER`, `EXPENSE_AI_ALLOW_DIRECT_API`, `EXPENSE_AI_USE_VERTEX`, `EXPENSE_AI_LOCATION`, `GOOGLE_CLOUD_PROJECT` | which route, and the tier assertion |
| `EXPENSE_AI_RATE_USER_PER_MIN`, `EXPENSE_AI_RATE_ENTITY_PER_HOUR` | in-process rate limits per person and per company |
| `EXPENSE_AI_CONF_HIGH`, `EXPENSE_AI_CONF_MEDIUM` | the confidence bands the page colours |
| `EXPENSE_AI_MAX_FILE_MB` | the receipt size cap |

## Tests

`tests/test_expense_ai.py` (the extraction contract with the provider stubbed, the limits,
the disabled state).
