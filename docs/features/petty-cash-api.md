# Petty Cash API - what minty-petty-cash-web calls

Petty Cash is getting its own front end, `minty-petty-cash-web` (port 3010; its `docs/features/petty-cash-web.md`). That app reads and writes a company's petty cash through a **bearer JSON API**. Until 2026-10-14, every report, expense and settings route here was a session-cookie page or session AJAX (`report/routes/*`), with nothing a cross-origin app could call.

**Where it lives.** For now the API lives in this app as the blueprint `blueprints/petty_cash_api/`. The owner's target (2026-10-14) is a separate Django service, `minty-petty-cash-api`, on port 8010, serving **the same paths**. The front end reads it as `PETTY_CASH_API_URL`, so only that address changes when it moves. Flask's HTML pages and these routes call the same services. Each wave extracts a request-free service out of a route and points both at it, so there is no duplicated logic.

## The door (`guard.py`) - fails closed

Every rule is under `/api/petty-cash/v1/companies/<entity_id>`. The company comes from that address and nowhere else: not the body, and not the token's `entity_id` claim. A test checks that every rule starts with the prefix.

`before_request` runs these checks in order, before any view:

| Check | Refusal |
|---|---|
| `OPTIONS` | `204` with CORS, no token needed |
| A valid HS256 token carrying `module == MODULE_TOKEN_CLAIM`, minted by `_generate_module_token` (`bearer_api.claims_from_bearer`). An onboarding-scope token, a hub token without the claim, an expired token or a session cookie alone are all refused. | `401 {"error": "unauthorized"}` |
| The person exists and `approved` is true | `401` |
| Membership, or a superuser (`profile.entity_context`, the same test `/handoff/minty-web` uses). A stranger, an unknown id and a malformed id all get the same answer. | `403` "You don't have access to that company." |
| The company is past onboarding | `409` |
| Petty Cash is on (`modules._is_module_enabled`, which denies on every unknown) | `403` |

**Exceptions.** Anything that throws, in the guard or a view, goes to the blueprint's `errorhandler`. It rolls back, logs with `logger.exception` and answers `500` with "Something went wrong on our side. Please try again." The detail is never sent. Contrast `report.routes.module_guard`, the old pages' gate, which **lets a request through** when it cannot find the company or the check throws. That fail-open gate is still in place on the old pages; this surface does not inherit it.

**Responses.** Every response is JSON. A refusal is `{"error": "<sentence>"}`, a sentence the app shows as it stands. The one exception is `unauthorized`, which the app answers by going back through `/handoff/petty-cash-web`. Every response is `Cache-Control: no-store`.

**CORS** is stamped in `after_request`, so refusals and 500s carry it too:
- the origin is `PETTY_CASH_WEB_URL` (default `http://localhost:3010`), or a `petty-cash` preview-set origin where `PREVIEW_ORIGIN_REGEX` allows it;
- `Vary: Origin`;
- methods `GET, POST, PUT, PATCH, DELETE, OPTIONS`;
- headers `Authorization, Content-Type` only (no `X-Entity-Id`).

**CSRF.** The whole blueprint is exempt (`services/app_runtime/legacy/bootstrap.py`). That is safe only because nothing in the package reads the session cookie. `tests/test_petty_cash_api_door.py` parses the package and fails on a bare `session`, a `current_user` or a `login_required`.

## The way in: `GET /handoff/petty-cash-web?next=&entity_id=`

The hand-off is in `blueprints/entity/routes/modules.py`. Flask is the only minter, and the app has no refresh of its own: a lapsed token comes back here (the app's `lib/handoff.ts`).
- **Login-gated.**
- **`next` is a path only** (`safe_next`, never an open redirect). The default is the company's `/entity/<shortid>/<name>/petty-cash`.
- **`entity_id`** is a uuid **or the app's address form `<shortid>/<name>`**, resolved by `entity_ref.resolve`. The app's cookie lapses with its token, and after that its address is all it knows of the company.
- **Refusals:**
  - no company → minty-web's company list;
  - not a member → `entity.entity_list` with a flash, and no token;
  - onboarding → the wizard;
  - Petty Cash off → `entity.entity_list` with a flash.
- **Destination.** `<petty-cash-web>/landing?token=&entity_id=&entity_name=&next=`, through `preview_origin.handoff_origin("petty-cash", …)`, so a preview set stays in its set.

## Endpoints

| Method · path (under `/api/petty-cash/v1/companies/<id>`) | Answers |
|---|---|
| `GET ""` | `{company: {id, name, role, role_label, currency: {code, decimal_places} \| null}, person: {id, first_name, last_name, name, initials, email}}`: what the app shell needs before any page |
| `GET /home` | The dashboard's state. It comes from `entity/services/dashboard.py::dashboard_state`, the same function the Jinja dashboard reads. Fields: `server_today` (Hong Kong), `currency_code`, `latest` (the latest report, drafts included, and its deposit with whether it can be corrected), `draft` (the newest), `draft_date` (the earliest draft: the calendar's floor), `published` (submitted days, by date), `today_has_report`, `today_is_latest_report`, `xero_settings`, and `permissions` (`read_only` for a superuser outside the company, `correct_deposit`). The live Xero bank-account read the Jinja page makes is left out, because it feeds a control that page never shows. |
| `POST /deposit-correction` | `{kind: "change" \| "no", date, amount}`: the "Before You Start" correction of the previous day's deposit. Needs `REPORT_EDIT_ENTITY`, and bad input is refused with a 422. The work is `report/routes/legacy.py::correct_previous_deposit`, shared with the Jinja page's `/api/check-dept-bank-yest`. It may reverse or update the deposit in Xero. The answer adds `next_transaction_date` (the day to open next) in place of the Jinja page's Flask `redirect_url`. |

The app is ported from Flask's pages one at a time (`development` of minty-petty-cash-web): dashboard, then the report wizard, history, settings and Xero publish. Each new route needs a row here, an entry in `tests/_baseline/route_inventory.json` and its tests.

## Tests

| File | What it covers |
|---|---|
| `tests/test_petty_cash_api_door.py` | The guard. Each refusal and its status, CORS on refusals and 500s, preview origins only with the regex, the AST rule, the CSRF exemption, and every rule naming the company. |
| `tests/test_petty_cash_web_handoff.py` | The hand-off. The token's claims, the address form, `next`, the refusals and the preview set. |
