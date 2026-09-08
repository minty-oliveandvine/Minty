# Stage 2 — AI Capture Hub: Low-Level Implementation Guide

**Audience:** a developer who is new to this codebase.
**Status:** implementation specification. Nothing here is built yet.
**Companion document:** *Stage 2 AI Implementation in the System.docx* (the high-level version). Read that first if you have not.

---

## 0. How to read this document

Sections 1–5 explain what we are building and how it fits the existing app. Read them once, in order.

Sections 6–15 are the build instructions. Each one names real files, real functions and real tables. When a section says "copy the pattern from X", go and open X — it is there for a reason, and copying it is not laziness, it is how the codebase stays consistent.

Section 19 is the order to build things in. If you only read two sections, read Section 4 (what already exists) and Section 19 (build order).

Anywhere you see **CONFIRM BEFORE CODING**, stop and ask. Those are the points where this document is describing something outside the Minty repository that has not been verified.

---

## 1. What we are building, in plain English

Today, if a user has a receipt, they must first decide where it goes. They open Petty Cash, open a report, open the expense form, and *then* attach the receipt. If it was actually a supplier invoice, they were in the wrong place and have to start again.

The AI Capture Hub removes that decision. The user drops a file — any supported file — into a small bubble in the bottom-right corner of the screen. The system reads it, works out what it is, splits it if it contains several documents, fills in the fields it can, and puts each one in a review list. The user checks each item and presses Confirm, and only then does anything become a real accounting record.

Three rules govern the whole feature:

1. **The AI never writes an accounting record.** It produces drafts. A human confirms every one.
2. **The AI never blocks anything.** If it is slow, down, or wrong, the user can still do everything by hand exactly as they do today.
3. **The AI never decides where a draft goes.** It classifies the document; our Python code applies a fixed routing rule. This is deliberate — see Section 11.4.

---

## 2. Words we use

| Word | Meaning |
| --- | --- |
| **Upload** | One file a user dropped in. One row in `capture_upload`. |
| **Draft** | One document found inside an upload. One row in `capture_draft`. One upload can produce several drafts. |
| **Split** | Working out how many separate documents are inside one file, and which pages belong to each. |
| **Pass 1** | The AI call that splits and classifies. One call per upload. |
| **Pass 2** | The AI call that reads the fields off one document. One call per draft. |
| **Destination** | Where a confirmed draft goes: Petty Cash, or Payment Submission. |
| **Module 1** | This app (Minty / Flask). Petty Cash lives here. The Capture Hub will live here. |
| **Module 2** | `billing-backend` (API) plus `billing-frontend` (Next.js). Payment Submission lives there. |

### A naming trap you will hit on your first day

**In the code, the Payment module is called `BILL`.** You will find `MODULE_BILL`, `entity_bill_account_xero`, `billing_sync.py`, `go_to_bills`. Every one of these means *Payment*.

The user-facing name changed from "Bill" to "Payment". The database constants did not, because renaming them would be a risky migration with zero benefit to any user.

**The rule:** leave the code constants alone. Every word a user can see must say "Payment". Do not "tidy up" `MODULE_BILL`.

---

## 3. Decisions already locked

These were settled in planning. Do not reopen them without asking.

| Decision | Answer |
| --- | --- |
| Where the Capture Hub lives | Minty only. There is one hub, not one per app. |
| Bubble scope | Upload and status only. No chat, no questions, no AI conversation. |
| Multi-document PDFs | Five receipts in one PDF become **five separate drafts**, not one. |
| PDF size limit | 2–3 pages. Anything over 3 pages is rejected at upload. |
| Document limit | At most 10 documents found inside one upload. |
| Unsupported documents | Rejected. See Section 3.1 — there are two rejection points, not one. |
| Auto-posting | Never. Every draft passes through human confirmation. |

### 3.1 Two rejection points, not one

"Reject unsupported documents" cannot all happen at upload time, because at upload time nothing has read the file yet. So there are two distinct places a document gets rejected, and they behave differently.

**Rejection A — at upload. Instant, free, no AI call.**

- Not a PDF, JPEG or PNG (checked by file contents, not the file name)
- Larger than the size limit
- PDF with more than 3 pages
- File is corrupt or empty

The user sees the error immediately. Nothing is stored. Nothing is charged.

**Rejection B — after Pass 1. A few seconds later, costs one AI call.**

- The AI read it and it is a bank statement, a contract, a screenshot, a blank page — anything that is not a receipt or an invoice.

No drafts are created. The upload shows in the queue as **Rejected — not a receipt or invoice**. The file is kept so the user can see what happened.

This check happens **after Pass 1 and before Pass 2**. Pass 1 has to classify anyway in order to split, so we find out it is a bank statement *before* paying for per-document extraction. One wasted call instead of ten.

**The override.** Rejection B must have a "This *is* a receipt — process it anyway" button. The AI will occasionally reject a legitimate crumpled receipt, and without the override the user is stuck with no way forward. The override re-runs the upload with the classification check disabled.

---

## 4. What already exists — read this code before you write any

This is the single most important section. Stage 1 (AI-assisted expense capture) already shipped. It solved most of the hard problems you are about to meet. Do not solve them again differently.

### 4.1 The Stage 1 AI module

**`blueprints/report/services/expense_ai.py`** (~1,050 lines)

This is the only file in the app that talks to an AI model. Read all of it. In particular:

| What | Where | Why it matters to you |
| --- | --- | --- |
| Reason codes (`REASON_DISABLED`, `REASON_TIMEOUT`, …) | Top of file | Stage 2 reuses these names and adds a few. |
| `_env`, `_env_bool`, `_env_int`, `_env_float` | Config section | Every setting is read from the environment **on each call**, so the kill switch works without a deploy. Copy this exactly. |
| `is_enabled()` | Config section | The kill switch. Defaults to **off**. Stage 2 gets its own. |
| `sniff_mime()` and `_MAGIC` | File handling | File type is decided by the first few bytes, never by the extension. |
| `prepare_document()` | File handling | Shrinks the file before it is billed as tokens. **Note:** it also trims PDFs to page 1 — Stage 2 must *not* do that, see Section 11.2. |
| `check_rate_limit()` | Rate limiting | In-process, per-user-per-minute and per-entity-per-hour. |
| `_get_client()` | Client | One client per process, built lazily, cached. Handles both the Vertex route and the direct Gemini API route. |
| `_call_model()` | The call | Error classification by HTTP status, one retry only for retryable classes. This is subtle and correct — reuse it, do not rewrite it. |
| `_validate()` | Bottom of file | The model's reply is **untrusted input**. An account id or contact id is accepted only if it appears in the list we sent in that same request. Anything that fails is dropped, never repaired. |
| `_SYSTEM_INSTRUCTION` | Prompt section | Contains the prompt-injection rule. Copy that paragraph word for word. |

### 4.2 The Stage 1 endpoint and front end

- **`blueprints/report/routes/expense_ai.py`** — `POST /report/expense/extract`. Note that **every outcome returns HTTP 200**. A failure is `{"suggestions": null, "reason": "..."}`. This is deliberate: a non-200 invites the browser to treat it as an error worth showing the user, and the whole point is that failure is invisible.
- **`static/js/expense_ai.js`** (~600 lines) — the browser side. Two rules it exists to enforce: never overwrite something the user already typed, and never block the Add button. Read the header comment.
- **`templates/report/expense.html`** lines ~4533–4543 — how the JS gets its configuration. A `window.EXPENSE_AI = {...}` block, rendered only when `expense_ai_enabled` is true, then the script tag. Copy this pattern.

### 4.3 How the app is put together

| Thing | Where | Notes |
| --- | --- | --- |
| Entry point | `app.py` (13 lines) → `services/app_runtime/legacy/bootstrap.py` | The real setup is in `bootstrap.py`. |
| Blueprint registration | `pettycash/core/blueprint_loader.py` | A hard-coded tuple of `(module_path, attribute)`. You must add yours to it **and** to `_EXPECTED_BLUEPRINTS`, or an import error in your routes will be swallowed at DEBUG level and you will lose an afternoon. |
| Models | `blueprints/<area>/models/*.py`, all re-exported from `models/db.py` | Every model must be imported in `models/db.py` or SQLAlchemy will not know about it. |
| Database schema | `pettycashv2` (PostgreSQL) | Every table needs `__table_args__ = {"schema": "pettycashv2"}`. |
| Migrations | `migrations/versions/*.py` (Alembic) plus a hand-runnable `.sql` twin in `migrations/` | Read `migrations/versions/t1a01_create_terms_consent.py` as the model to follow. |
| Base template | `templates/base/layout.html` | Tailwind via CDN, jQuery 3.7.1, Remix Icon 4.6.0. Brand colour is `#294882` (`primary`). |
| S3 | `blueprints/report/services/s3_storage.py` | `get_s3_client()`, `get_s3_bucket()`, `download_file_from_s3(key)`, `delete_files_from_s3(keys)`. |
| Scheduled jobs | APScheduler 3.11 | **There is no Celery, no Redis queue and no worker process.** This shapes Section 12. |
| Permissions | `services/permission_policy.py` — `has_permission(user, Permission.X, entity_id)` | |
| Module on/off | `blueprints/entity/routes/modules.py` — `_is_module_enabled(entity_id, "PETTY_CASH" \| "BILL")` | |

### 4.4 The trap that decides your blueprint

Open **`blueprints/report/routes/module_guard.py`**.

The entire `report` blueprint is behind a `before_request` gate that denies access when `PETTY_CASH` is off for the entity. Every route in that blueprint, no exceptions.

**Therefore the Capture Hub cannot live in the `report` blueprint.** A customer who bought Payment Submission but not Petty Cash would be locked out of their own capture hub.

The Capture Hub gets its **own blueprint** with its **own gate**: allow if `PETTY_CASH` **or** `BILL` is enabled. Section 9 spells this out.

### 4.5 How Minty and Module 2 already talk

Read **`blueprints/entity/routes/modules.py`**, especially `_generate_module_token()`.

- Minty mints a short-lived **HS256 JWT signed with `SECRET_KEY`**, which both apps share.
- Module 2 calls its backend with `Authorization: Bearer <jwt>` and `X-Entity-Id: <entity_id>`. The backend verifies with the same `SECRET_KEY`.
- `FRONTEND_APP_URL` points at the Module 2 Next.js app.
- Traffic today runs **Module 2 → Minty** (see `blueprints/entity/routes/billing_sync.py`, which Module 2 calls with a Bearer token).

Stage 2 needs the opposite direction: **Minty → Module 2 backend**. The good news is the auth scheme already exists and we can mint exactly the same token. The gap is that Minty has no environment variable for the billing backend's base URL — `docker/stack/docker-compose.yml` has `BILLING_BACKEND_PUBLIC_URL` but the Flask app never reads it. Section 15.2 adds one.

---

## 5. Architecture at a glance

```
  Browser (any page in Minty)
      |
      |  user drops a file on the bubble
      v
  POST /capture/upload                      <- blueprints/capture/routes/upload.py
      |
      |  cheap checks first: module gate, permission, rate limit,
      |  size, magic bytes, PDF page count, duplicate hash
      |
      |-- fails any check --> HTTP 400 with a plain-English message. Nothing stored.
      |
      |  store file in S3, insert capture_upload (status = queued),
      |  start a background thread, return upload_id
      v
  HTTP 202 { upload_id, status: "queued" }
      |
      |  browser polls GET /capture/status every 2s
      v
  Background thread                         <- blueprints/capture/services/pipeline.py
      |
      |  PASS 1 (one AI call): how many documents, which pages, what type
      |     -> nothing usable?  upload.status = rejected_not_supported. STOP.
      |     -> more than 10 documents?  upload.status = rejected_too_many. STOP.
      |
      |  For each document found:
      |     cut the pages out of the PDF (pikepdf)
      |     PASS 2 (one AI call): read the fields
      |     apply the routing rule (Python, not the model)
      |     insert capture_draft (status = ready | needs_clarification)
      |
      v
  capture_upload.status = done
      |
      |  bubble badge updates: "3 drafts ready"
      v
  GET /capture  ->  the Draft Queue page     <- templates/capture/queue.html
      |
      |  user edits fields, presses Confirm
      v
  POST /capture/draft/<id>/confirm
      |
      +-- destination = petty_cash --> insert pettycashv2.shop_expense (local)
      |
      +-- destination = payment    --> POST to billing-backend with a minted JWT
                                        on failure: status = send_failed, retried
                                        by an APScheduler job
```

---

## 6. New files

Create these. Nothing outside this list is modified except the six files in Section 6.2.

### 6.1 New files

```
blueprints/capture/__init__.py                     capture_bp = Blueprint("capture", __name__)
blueprints/capture/routes/__init__.py              imports every route module
blueprints/capture/routes/module_guard.py          the PETTY_CASH-or-BILL gate
blueprints/capture/routes/upload.py                POST /capture/upload
blueprints/capture/routes/queue.py                 GET  /capture  (the page)
blueprints/capture/routes/api.py                   status, list, confirm, reject, retry
blueprints/capture/routes/files.py                 GET  /capture/draft/<id>/file
blueprints/capture/models/__init__.py
blueprints/capture/models/capture_upload.py        one row per uploaded file
blueprints/capture/models/capture_draft.py         one row per document found
blueprints/capture/models/capture_ai_audit.py      one row per AI call
blueprints/capture/services/__init__.py
blueprints/capture/services/capture_ai.py          the ONLY file that calls the model
blueprints/capture/services/pipeline.py            the background worker
blueprints/capture/services/pdf_tools.py           page count, page extraction (pikepdf)
blueprints/capture/services/storage.py             S3 put/get/delete for capture files
blueprints/capture/services/routing.py             the routing rule + destination push
blueprints/capture/services/context.py             the bubble's context processor
blueprints/capture/services/sweeper.py             APScheduler jobs (stuck, retry, retention)

templates/capture/queue.html                       the Draft Queue page
templates/components/ai_capture_bubble.html        the bubble partial
static/js/capture_bubble.js                        bubble behaviour
static/js/capture_queue.js                         queue page behaviour

migrations/versions/ai1a01_create_capture_tables.py
migrations/ai1a01_create_capture_tables.sql        hand-runnable twin

tests/test_capture_upload_validation.py
tests/test_capture_routing_rule.py
tests/test_capture_pipeline.py
tests/test_capture_permissions.py
```

### 6.2 Existing files you must edit

| File | Change |
| --- | --- |
| `pettycash/core/blueprint_loader.py` | Add `("blueprints.capture", "capture_bp")` to the tuple in `register_blueprints()`, **and** add `"blueprints.capture"` to `_EXPECTED_BLUEPRINTS`. |
| `models/db.py` | Import the three new models and add them to `__all__`. |
| `templates/base/layout.html` | Add `{% include 'components/ai_capture_bubble.html' %}` inside `<body>`, just before the closing `</div>` of `.main-container`. **Not** inside `{% block scripts %}` — pages that override that block without `{{ super() }}` would silently lose the bubble. |
| `.env.example` | Add the `CAPTURE_AI_*` block from Appendix A. |
| `requirements.txt` | Nothing new. `google-genai==2.22.0`, `pikepdf==9.4.0` and `Pillow==11.0.0` are already there. |
| `services/app_runtime/legacy/bootstrap.py` | Register the three APScheduler jobs from Section 12.4, next to the existing scheduled jobs. |

---

## 7. Database

Three new tables in the `pettycashv2` schema.

### 7.1 `capture_upload` — one row per file the user dropped

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | String(36) | no | UUID4, primary key |
| `entity_id` | String(36) | no | FK → `pettycashv2.entities.id`. Resolved server-side, never from the client. |
| `uploaded_by` | String(36) | no | FK → `pettycashv2.user.id` |
| `original_filename` | String(255) | yes | Passed through `secure_filename` before storing |
| `mime_type` | String(64) | no | The **sniffed** type, not the declared one |
| `byte_size` | Integer | no | |
| `page_count` | Integer | yes | 1 for images; real page count for PDFs |
| `content_sha256` | String(64) | no | Duplicate detection. Indexed with `entity_id`. |
| `s3_key` | String(512) | no | See Section 7.4 for the key layout |
| `status` | String(32) | no | See Section 16 |
| `reject_reason` | String(64) | yes | A stable code, not a sentence |
| `document_count` | Integer | yes | How many documents Pass 1 found |
| `bypass_classification` | Boolean | no | Default false. Set true by the "process it anyway" override. |
| `created_at` | TIMESTAMP(tz) | no | `server_default=now()` |
| `processing_started_at` | TIMESTAMP(tz) | yes | Used by the stuck-job sweeper |
| `completed_at` | TIMESTAMP(tz) | yes | |

Indexes:
- `ix_capture_upload_entity_status` on `(entity_id, status)` — the queue and badge queries
- `ix_capture_upload_dedupe` on `(entity_id, content_sha256)`
- `ix_capture_upload_created` on `created_at` — the retention sweeper

### 7.2 `capture_draft` — one row per document found

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | String(36) | no | UUID4, primary key |
| `upload_id` | String(36) | no | FK → `capture_upload.id`, `ondelete="CASCADE"` |
| `entity_id` | String(36) | no | Denormalised on purpose: every authorisation check reads it, and going through `upload` for that would add a join to every request |
| `sequence` | Integer | no | 1, 2, 3… within the upload. Drives "Document 2 of 5". |
| `page_start` | Integer | no | 1-based, inclusive |
| `page_end` | Integer | no | 1-based, inclusive |
| `locator` | String(200) | yes | Pass 1's short description, e.g. "top-left receipt, Starbucks". Only used when several documents share one page. |
| `doc_type` | String(32) | no | `receipt`, `invoice`, `other` |
| `doc_type_confidence` | Numeric(4,3) | yes | |
| `destination` | String(32) | no | `petty_cash`, `payment`, `hold`, `rejected` |
| `status` | String(32) | no | See Section 16 |
| `suggested` | JSONB | yes | Pass 2's validated output. The shape is in Appendix B. |
| `confirmed` | JSONB | yes | What the user actually saved. Written on confirm. |
| `document_date` | Date | yes | Lifted out of `suggested` so the queue can sort and filter without unpacking JSON |
| `amount` | Numeric(14,2) | yes | Same reason |
| `currency` | String(3) | yes | Same reason |
| `supplier_name` | String(150) | yes | Same reason |
| `page_s3_key` | String(512) | yes | The single-document file cut out of the original. Null for single-document uploads — then use the parent's `s3_key`. |
| `target_ref` | String(128) | yes | What it became: a `shop_expense.id`, or Module 2's PaymentRequest id |
| `send_attempts` | Integer | no | Default 0 |
| `last_error` | String(500) | yes | Never contains file contents |
| `created_at` | TIMESTAMP(tz) | no | |
| `updated_at` | TIMESTAMP(tz) | no | |
| `confirmed_at` | TIMESTAMP(tz) | yes | |
| `confirmed_by` | String(36) | yes | |

Indexes:
- `ix_capture_draft_entity_status` on `(entity_id, status)`
- `ix_capture_draft_upload` on `upload_id`

### 7.3 `capture_ai_audit` — one row per AI call

**Numbers only.** No amounts, no supplier names, no descriptions, no file bytes. Stage 1's endpoint makes this same choice and explains why: those are a client's financial details, and a metrics table is the wrong place for them. The actual values live in `capture_draft.suggested`, which is protected by the same authorisation as everything else.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | String(36) | UUID4 |
| `upload_id` | String(36) | FK, `ondelete="CASCADE"` |
| `draft_id` | String(36) | Null for Pass 1 |
| `entity_id` | String(36) | |
| `pass_number` | SmallInteger | 1 or 2 |
| `model_id` | String(64) | |
| `location` | String(64) | Same meaning as Stage 1's `location()` — a compliance field |
| `latency_ms` | Integer | |
| `input_tokens` | Integer | |
| `output_tokens` | Integer | |
| `thought_tokens` | Integer | Billed at the output rate. Stage 1 learnt this the hard way — leaving it out understated cost by about 60%. |
| `cached_tokens` | Integer | Zero across repeated calls for one entity means the cacheable prefix is not byte-stable |
| `estimated_cost` | Numeric(12,6) | An indication for the dashboard, not an invoice |
| `status` | String(32) | `ok` or `no_suggestion` |
| `reason` | String(64) | A reason code when not ok |
| `confidence_by_field` | JSONB | Field name → number. No values. |
| `created_at` | TIMESTAMP(tz) | |

### 7.4 S3 key layout

```
capture/{entity_id}/{yyyy}/{mm}/{upload_id}/original.{ext}
capture/{entity_id}/{yyyy}/{mm}/{upload_id}/doc-{sequence}.{ext}
```

Keys contain a UUID, so they are not guessable. That is a second line of defence, not the first — the file endpoint (Section 10.7) re-authorises on every request and streams the bytes. **Never hand an S3 key to the browser.**

### 7.5 The migration

Copy the shape of `migrations/versions/t1a01_create_terms_consent.py` exactly:

- A module docstring that explains what the migration does, why each constraint exists, and whether it is safe to run on live. Yes, a long one. That is the house style and it has repeatedly earned its keep.
- `revision = "ai1a01_capture_tables"`, `down_revision = "<the current head>"` — run `alembic heads` to find it; do not guess.
- `upgrade()` is **idempotent**: check `sa.inspect(bind).has_table(...)` first and return with a printed message if the table exists. The `.sql` twin gets run by hand on environments Alembic does not stamp, and this revision must not then fail.
- `downgrade()` drops the tables, and prints a loud warning naming the row count if any rows exist.
- `SCHEMA = "pettycashv2"` as a constant; pass `schema=SCHEMA` on every `create_table` and `create_index`.

This migration is purely additive: three new tables, nothing existing touched. That means it is safe to run on live at any time and safe to run **before** the application code ships. Schema first, code after.

---

## 8. Configuration

Every setting is read from the environment **on each call**, exactly as `expense_ai.py` does. That is what makes the kill switch work without a deployment. Do not cache these in module-level constants.

The full list is in Appendix A. The four you will care about on day one:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CAPTURE_AI_ENABLED` | `false` | The kill switch. Off means no bubble is rendered, `/capture/*` returns 404, and no model call is ever made. **The feature ships dark.** |
| `CAPTURE_AI_MAX_PAGES` | `3` | Reject a PDF with more pages |
| `CAPTURE_AI_MAX_DOCUMENTS` | `10` | Reject an upload when Pass 1 finds more documents than this |
| `CAPTURE_AI_MAX_CONCURRENT` | `4` | How many uploads may be in Pass 1/Pass 2 at once across the process |

Reuse the Gemini credentials Stage 1 already uses (`GEMINI_API_KEY`, or `GOOGLE_CLOUD_PROJECT` for the Vertex route). Do not add a second key.

---

## 9. The blueprint and its gate

### 9.1 The blueprint

`blueprints/capture/__init__.py`:

```python
from flask import Blueprint

capture_bp = Blueprint("capture", __name__)
```

`blueprints/capture/routes/__init__.py` imports every route module, so that importing the package registers the routes. Follow how `blueprints/report/routes/__init__.py` does it.

Then add to `pettycash/core/blueprint_loader.py`:

- `("blueprints.capture", "capture_bp")` in the tuple inside `register_blueprints()`
- `"blueprints.capture"` in `_EXPECTED_BLUEPRINTS`

**Do not skip the second one.** Without it, any import error in your route files is logged at DEBUG and swallowed, your routes silently do not exist, and `url_for("capture.queue")` fails somewhere completely unrelated. There is a comment in that file about exactly this happening before.

### 9.2 The gate

`blueprints/capture/routes/module_guard.py`. Model it on `blueprints/report/routes/module_guard.py`, with three differences:

1. **The kill switch comes first.** If `CAPTURE_AI_ENABLED` is off, return a 404 for every route in the blueprint. Not a 403 — when the feature is off it does not exist.
2. **Either module opens the gate.** Allow when `_is_module_enabled(entity_id, "PETTY_CASH")` **or** `_is_module_enabled(entity_id, "BILL")` is true.
3. **This gate fails closed.** The report guard deliberately fails *open* when it cannot resolve an entity, because many of its routes carry no entity context. Every capture route carries one. If we cannot resolve an entity here, that is a bug or an attack, and the answer is 403.

Entity resolution order, same as the report guard: `entity_id` in the URL, query string, form or JSON body first; otherwise resolve through `upload_id` or `draft_id` to the owning row's `entity_id`.

On top of the gate, every route also calls `has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id)`. The gate answers "does this company have the feature"; the permission check answers "is this person allowed to use it".

**CONFIRM BEFORE CODING:** `REPORT_EDIT_OWN` is the permission Stage 1 uses, and it is right for the Petty Cash half. Whether a Payment-only user holds it needs checking against `services/permission_policy.py` and the role matrix. If they do not, we need a new permission and a migration to grant it — raise this before you start Section 15.2.

---

## 10. Endpoints

Conventions for all of them:

- JSON in, JSON out, except the page route and the file route.
- Errors the **user caused** (wrong file type, too many pages) return **4xx with a plain-English message**. The user needs to know and can fix it.
- Errors the **AI caused** (timeout, rate limit, provider down) return **200 with a reason code**, exactly as Stage 1 does. The user cannot fix those and should not be shown a stack of red banners.
- `entity_id` is always re-resolved and re-validated server-side. A client-supplied value is never trusted.

### 10.1 `POST /capture/upload`

**Body:** `multipart/form-data` with `file`, and optionally `entity_id`.

**Steps, in this exact order** — cheapest and safest first, so a bad file never reaches the model:

1. Kill switch. Off → 404.
2. Resolve entity. Module gate. Permission check.
3. Rate limit (`check_rate_limit`, copied from Stage 1). Over → **429** `{"error": "rate_limited"}`.
4. `file` present and non-empty? No → 400 `"No file was received."`
5. Read at most `CAPTURE_AI_MAX_FILE_MB + 1` bytes. Over the cap → 400 `"That file is larger than 10 MB."`
6. `sniff_mime(data)` on the magic bytes. `None` → 400 `"Only PDF, JPG and PNG files can be read."`
7. If PDF: `pdf_tools.page_count(data)`. More than `CAPTURE_AI_MAX_PAGES` → 400 `"That PDF has 7 pages. Please upload 3 pages or fewer."` A PDF that pikepdf cannot open → 400 `"That PDF could not be opened."`
8. `content_sha256 = hashlib.sha256(data).hexdigest()`. Look for a `capture_upload` in the same entity, same hash, created in the last 30 days, not in a rejected state. Found → **200** with `{"duplicate": true, "upload_id": "<the existing one>", "message": "You already uploaded this file on 3 March."}` The browser shows the message and links to the existing drafts. **Do not create a second row and do not call the model.**
9. Upload the bytes to S3 under the Section 7.4 key.
10. Insert `capture_upload` with `status = "queued"`. Commit.
11. Hand the id to `pipeline.start(upload_id)` (Section 12).
12. Return **202** `{"upload_id": "...", "status": "queued", "page_count": 3}`.

Note step 8 returns 200, not 409. A duplicate is not an error — it is a helpful answer.

### 10.2 `GET /capture/status`

Polled by the bubble. This runs every two seconds for every user with the bubble open, so it must be **two indexed queries and nothing else**. No AI, no S3, no joins across schemas.

**Query:** `entity_id`, optional `since` (ISO timestamp).

**Response 200:**

```json
{
  "processing": 2,
  "ready": 5,
  "needs_clarification": 1,
  "failed": 0,
  "changed": [
    { "upload_id": "…", "status": "done", "document_count": 3 }
  ]
}
```

`changed` lists only uploads whose `updated_at` is after `since`, capped at 20. It is what lets the bubble say "Your 3-page PDF became 3 drafts" without refetching everything.

### 10.3 `GET /capture/drafts`

Feeds the queue page. `entity_id`, optional `status`, `limit` (default 50, max 200), `cursor`.

Returns each draft as the Appendix B shape, plus its upload's filename and page count. Only drafts whose `entity_id` matches the resolved entity — filter in SQL, not in Python.

### 10.4 `POST /capture/draft/<draft_id>/confirm`

**Body:** the user's final values — this is what they saw and edited on screen, not what the AI suggested.

```json
{
  "destination": "petty_cash",
  "report_id": "…",
  "amount": "128.50",
  "currency": "HKD",
  "description": "Taxi to client meeting",
  "contact_id": "…",
  "contact_name": "…",
  "account_id": "…",
  "account_code": "…",
  "document_date": "2026-09-03"
}
```

**Steps:**

1. Load the draft. Not found, or `entity_id` does not match the resolved entity → **404**. Not 403 — do not confirm the existence of another company's rows.
2. Draft already `posted` → **409** `"This one has already been added."`
3. Validate the submitted values server-side. Do **not** trust `suggested`; the user may have changed everything, and they are the authority. Re-check `account_id` and `contact_id` against the entity's own lists, exactly as `_validate()` does in Stage 1.
4. `destination` must be one the entity actually has enabled. A `payment` destination with `BILL` off → 400.
5. Write `confirmed` JSON, `confirmed_at`, `confirmed_by`. Set `status = "confirming"`. Commit.
6. Hand off to `routing.push(draft_id)` (Section 15).
7. Return 200 with the new status: `posted` if the local write succeeded, `confirming` if it went to a background push.

### 10.5 `POST /capture/draft/<draft_id>/reject`

Sets `status = "archived"`. No body needed. The row and the file stay until the retention sweeper removes them, so "I archived that by mistake" is recoverable by support.

### 10.6 `POST /capture/upload/<upload_id>/retry`

The "This *is* a receipt — process it anyway" override from Section 3.1.

- Only allowed when `status = "rejected_not_supported"`. Any other status → 400.
- Sets `bypass_classification = true`, `status = "queued"`, and restarts the pipeline.
- Counts against the rate limit like any other upload — it is a real AI call.
- Allowed **once** per upload. A second attempt → 400 `"We already tried reading this one twice."` Otherwise a determined user can spend money in a loop on a photo of their lunch.

### 10.7 `GET /capture/draft/<draft_id>/file`

Streams the document image so the user can look at it while reviewing.

- Re-authorise: kill switch, module gate, permission, and `draft.entity_id == resolved entity`.
- Prefer `page_s3_key`; fall back to the parent upload's `s3_key`.
- Stream from S3 through Flask with `Content-Disposition: inline`. **Do not redirect to a presigned S3 URL** — that leaks a URL that keeps working after the user's session ends.
- Set `Cache-Control: private, max-age=300`.

---

## 11. The AI service — `capture_ai.py`

**This is the only Stage 2 file allowed to import the Gemini SDK.** Stage 1 made the same rule for the same reason: keeping every provider-specific line in one module is what makes a future provider change cheap, without building an abstraction layer that would cost more than it saves.

Structure the file the same way `expense_ai.py` is structured: reason codes, then config readers, then schemas, then the prompt, then the call, then validation.

### 11.1 What to copy from Stage 1, unchanged

Copy these as they are. They are correct, and they were correct only after several rounds of production surprises:

- `_env` / `_env_bool` / `_env_int` / `_env_float`
- `sniff_mime()` and `_MAGIC`
- `check_rate_limit()` and its deques
- `_get_client()` — including the Vertex-versus-direct branch and the tier warnings
- `_call_model()` — the whole error table. In particular: classify on the `status_code` attribute, not on exception class, because the SDK raises from two different exception families depending on which API you call.
- `_record_usage()` and `_estimate_cost()`
- `_response_schema()` — the trick of stripping `title` and `default` off the Pydantic schema and marking every field required
- The prompt-injection paragraph from `_SYSTEM_INSTRUCTION`

### 11.2 Pass 1 — split and classify

**One call per upload.** Input is the whole file (all 1–3 pages).

**Do not use Stage 1's `prepare_document()` here.** It calls `_first_page_only()`, which throws away pages 2 and 3 — the exact opposite of what Pass 1 needs. Write a Stage 2 version that downsizes (reuse `file_downsize.downsize_bytes`) but keeps every page.

**The response schema.** Stage 1 keeps its schema completely flat because nested Pydantic models generate `$defs`/`$ref`, which Gemini's structured-output subset does not accept. Pass 1 genuinely needs a list, so **hand-write the schema dict** instead of generating it from a nested Pydantic model. Hand-writing produces no `$ref`. Validate the parsed reply with Pydantic afterwards.

```python
_PASS1_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_start":  {"type": "integer"},
                    "page_end":    {"type": "integer"},
                    "locator":     {"type": "string"},
                    "doc_type":    {"type": "string",
                                    "enum": ["receipt", "invoice", "other"]},
                    "doc_type_confidence": {"type": "number"},
                    "other_reason": {"type": "string"},
                },
                "required": ["page_start", "page_end", "locator",
                             "doc_type", "doc_type_confidence", "other_reason"],
            },
        }
    },
    "required": ["documents"],
}
```

**The splitting rule, stated in the prompt exactly like this:**

> Split by document boundary, never by page. A two-page invoice is ONE document with page_start 1 and page_end 2. Two receipts printed on one page are TWO documents, both with page_start 1 and page_end 1 — tell them apart using the locator field.

**`locator`** is a short human description — "top-left receipt, Starbucks, HK$48". It exists for the case where several documents share a page: Pass 2 receives the same page image for each, and the locator is the only thing that tells it which one to read. Cap it at 200 characters and treat it as untrusted text.

**After Pass 1, in Python, not in the prompt:**

1. Reply invalid, or `documents` empty → `upload.status = "rejected_not_supported"`, reason `no_document_found`.
2. `len(documents) > CAPTURE_AI_MAX_DOCUMENTS` → `status = "rejected_too_many"`. Do not process the first ten; the split is probably wrong and ten wrong drafts are worse than one clear error.
3. Every document is `doc_type == "other"` and `bypass_classification` is false → `status = "rejected_not_supported"`, reason `not_a_financial_document`. **Stop here. Do not run Pass 2.** This is the check that saves the money.
4. A *mix* of `other` and real documents → drop the `other` ones and carry on with the rest. A receipt stapled to a covering letter is normal.
5. Clamp `page_start` and `page_end` into `1..page_count` and require `page_start <= page_end`. The model will occasionally return page 4 of a 3-page PDF, and an unclamped value would crash pikepdf.

### 11.3 Pass 2 — extract the fields

**One call per document.** Input is only that document's pages.

Cutting the pages out lives in `pdf_tools.extract_pages(data, start, end)` using pikepdf — the same library `_first_page_only()` already uses. Store the result at `doc-{sequence}.{ext}` and put the key in `page_s3_key`. For a single-document upload, skip the cut and reuse the original.

**Two schemas, both flat, both modelled on Stage 1's `ExpenseSuggestion`:**

*Receipt* — reuse Stage 1's `ExpenseSuggestion` as-is. Same fields, same meanings, and reusing it means the confidence bands and validation already match.

*Invoice* — same fields plus:

| Field | Type | Notes |
| --- | --- | --- |
| `invoice_number` | str | `""` when not found |
| `invoice_number_confidence` | float | |
| `due_date` | str | ISO 8601, `""` when not found |
| `due_date_confidence` | float | |
| `tax_amount` | float | `0` when not found |
| `tax_amount_confidence` | float | |
| `subtotal_amount` | float | `0` when not found |

**The context we send** — build it with a Stage 2 copy of `build_entity_context()`:

- For a receipt: the entity's Petty Cash chart of accounts and contacts, exactly as Stage 1 builds them (active rows in `entity_account_xero`, plus `xero_contact_sync`).
- For an invoice: the **Payment** chart of accounts, which lives in `pettycashv2.entity_bill_account_xero` — see `blueprints/entity/services/onboarding_bill_codes.py`. Same contacts.

Sort both lists deterministically (by code then id, name then id) and put them at the **front** of the prompt. Gemini's caching is implicit prefix matching with no marker to set: an unstable ordering does not reduce the cache hit rate, it eliminates it. Same-entity uploads then share a cached prefix, which is most of the cost saving.

**When several documents share a page**, add one line to the variable half of the prompt:

> This page contains more than one document. Read ONLY this one: {locator}. Ignore the others.

### 11.4 The routing rule — Python decides, not the model

Put this in `services/routing.py` as a pure function so it can be unit-tested with no database and no network:

```python
def decide_destination(doc_type, petty_cash_enabled, bill_enabled):
    """Return one of: 'petty_cash', 'payment', 'hold', 'rejected'."""
```

| `doc_type` | Petty Cash on | Payment on | Destination |
| --- | --- | --- | --- |
| `receipt` | yes | — | `petty_cash` |
| `receipt` | no | yes | `hold` |
| `invoice` | — | yes | `payment` |
| `invoice` | — | no | `hold` |
| `other` | — | — | `rejected` |
| anything | no | no | unreachable — the gate already blocked the request |

**Why the model does not choose.** Three reasons, and all three matter:

1. It is deterministic and unit-testable. A routing bug is reproducible instead of probabilistic.
2. The model cannot route a document into a module the entity has not paid for. If it could, entitlement would depend on a language model's judgement, which is not a position anybody wants to defend.
3. When the rule changes, we change one function and one test — not a prompt, and not the model's behaviour on thousands of past documents.

`hold` means "we know what this is, but you do not have the module for it". The draft sits in the queue with a message explaining which module would receive it. It is not an error and not a rejection.

### 11.5 Validation

Reuse Stage 1's `_validate()` idea completely, per field:

- An `account_id` or `contact_id` is accepted **only if it appears in the list we sent in that same request**. Otherwise the field is dropped. Never "corrected" to a near match — a wrong suggestion costs the user more than no suggestion.
- Amounts: parse as `Decimal`, must be greater than zero and within a sane maximum, quantised to two places.
- Dates: ISO 8601 only, capped at 10 characters.
- Currency: exactly three alphabetic characters, uppercased, or empty.
- Text: stripped, length-capped, and rendered with `textContent` in the browser — **never `innerHTML`**. This text came off a photograph that somebody else supplied.
- Confidence: clamped to 0.0–1.0 and banded high / medium / low using `CAPTURE_AI_CONF_HIGH` and `CAPTURE_AI_CONF_MEDIUM`. A low-confidence field is stored with its confidence but marked `applied: false`, and the queue leaves it blank.

---

## 12. Background processing

### 12.1 Why threads and not a queue

The obvious answer is Celery or RQ with Redis and a worker process. We are not doing that, because Minty has no Redis, no worker process, and no deployment slot for one. Adding that infrastructure for this feature would be a bigger change than the feature.

What we have is APScheduler 3.11, already running.

So: **process in a daemon thread, keep all state in the database, and let the browser poll.** The database is the source of truth, never the thread. If every thread died right now, the data would be consistent and a sweeper would recover it.

There is precedent in the codebase — `sync_chart_of_accounts_if_changed_background()` in `blueprints/entity/services/settings.py` does fire-and-forget work in a daemon thread. Read it before you write `pipeline.py`.

### 12.2 Starting the thread

```python
def start(upload_id):
    app = current_app._get_current_object()   # NOT current_app itself
    threading.Thread(
        target=_run, args=(app, upload_id), daemon=True
    ).start()
```

Three things that will bite you:

- **`current_app` is a proxy.** Passing it into a thread gives you a proxy bound to a request that has already ended. `_get_current_object()` gives you the real app.
- **Inside the thread, wrap everything in `with app.app_context():`.** Without it, every `db.session` call raises "working outside of application context".
- **Do not share the request's session.** Call `db.session.remove()` in a `finally` block so the thread's session is returned to the pool. A leaked session will exhaust the pool under load, and the symptom (requests hanging, not erroring) is horrible to diagnose.

### 12.3 The concurrency cap

A module-level `threading.Semaphore(CAPTURE_AI_MAX_CONCURRENT)`, acquired for the whole of one upload's processing. Without it, ten users uploading 3-document PDFs at the same time fires forty concurrent model calls, and Google's rate limiter answers for us — with 429s, on their terms rather than ours.

### 12.4 The three scheduled jobs

Register these in `bootstrap.py` beside the existing scheduled jobs.

**1. Stuck-upload sweeper — every 5 minutes.**
A thread dies when the process restarts, and the row it was working on stays `processing` forever. Find uploads with `status = "processing"` and `processing_started_at` older than 15 minutes, set them to `failed` with reason `worker_lost`. The queue then offers a Retry button. Do not restart them automatically — a crash loop that keeps re-calling a paid API is exactly the failure mode you cannot afford.

**2. Send retry — every 10 minutes.**
Find drafts with `status = "send_failed"` and `send_attempts < 5`, and re-run `routing.push()`. Back off: skip a draft whose `updated_at` is newer than `2 ** send_attempts` minutes ago. At 5 attempts, stop and leave it for a human.

**3. Retention sweeper — daily.**
Delete `capture_upload` rows (and their S3 objects) older than `CAPTURE_RETENTION_DAYS`, default 90. `capture_draft` and `capture_ai_audit` cascade. Skip anything still `processing`. Delete the S3 objects **first**, then the row — an orphaned S3 object is a small cost, but a row pointing at a deleted object is a broken page.

### 12.5 The pipeline itself

```
_run(app, upload_id):
  with app.app_context():
    with SEMAPHORE:
      try:
        mark processing, stamp processing_started_at, commit
        download the original from S3
        pass1 = capture_ai.split_and_classify(data, mime, page_count, bypass)
        write a capture_ai_audit row for pass 1
        apply the Section 11.2 post-checks
          -> rejected? set status, commit, return
        for each document Pass 1 kept:
          cut the pages, upload doc-{n}, 
          pass2 = capture_ai.extract(doc_bytes, doc_mime, context, doc_type, locator)
          write a capture_ai_audit row for pass 2
          destination = decide_destination(...)
          insert capture_draft
          commit  <-- per draft, NOT once at the end
        upload.status = done, document_count = n, completed_at = now, commit
      except Exception:
        logger.exception(...)
        upload.status = failed, reject_reason = internal_error, commit
      finally:
        db.session.remove()
```

**Commit after each draft, not once at the end.** If document 4 of 5 fails, the user keeps drafts 1–3 instead of losing everything. It also means the bubble's count climbs while the user watches, which is the difference between "it is working" and "it is stuck".

---

## 13. The bubble

### 13.1 Where it lives

`templates/components/ai_capture_bubble.html`, included from `templates/base/layout.html` inside `<body>`, just before the closing `</div>` of `.main-container`.

**Not inside `{% block scripts %}`.** Several pages override that block without calling `{{ super() }}`, and the bubble would silently vanish on exactly those pages.

### 13.2 When it renders

A context processor in `blueprints/capture/services/context.py`, registered with `@capture_bp.app_context_processor` so it runs for every template in the app.

It provides one variable, `capture_bubble`, which is `None` — meaning render nothing — unless **all** of these hold:

1. `CAPTURE_AI_ENABLED` is true
2. The user is authenticated
3. An entity can be resolved for this request
4. That entity has `PETTY_CASH` or `BILL` enabled
5. The user has the required permission on it

Two hard requirements on this function:

- **It must never raise.** It runs on every page render including the login page and the error page. Wrap the body in `try/except Exception` and return `{"capture_bubble": None}` on any failure. A context processor that throws turns every page in the app into a 500.
- **It must be cheap.** Two indexed queries at most. Cache the module check on `flask.g` for the request.

The template is a single `{% if capture_bubble %}` around everything, then a `window.CAPTURE_HUB = {...}` config block and the script tag — copying the `window.EXPENSE_AI` pattern at the bottom of `templates/report/expense.html`.

### 13.3 What it looks like

Collapsed: a 56px circular button, fixed at `bottom: 24px; right: 24px`, `z-index` above the app chrome but below modals. Brand colour `#294882` (Tailwind `primary`). A Remix Icon glyph — `ri-sparkling-2-line` or similar; Remix Icon 4.6.0 is already loaded in the layout.

A small count badge sits on the button when anything needs attention: ready plus needs-clarification.

Expanded, about 340×420px:

```
 ┌──────────────────────────────────┐
 │  AI Capture                  ✕   │
 ├──────────────────────────────────┤
 │                                  │
 │      ┌────────────────────┐      │
 │      │   Drop a file here │      │
 │      │   or click to pick │      │
 │      │                    │      │
 │      │  PDF, JPG, PNG     │      │
 │      │  Up to 3 pages     │      │
 │      └────────────────────┘      │
 │                                  │
 │  Recent                          │
 │  ● receipt-mar.pdf   3 drafts    │
 │  ◐ invoice-042.pdf   reading…    │
 │  ✕ statement.pdf     not a       │
 │                      receipt     │
 │                                  │
 │  [ Review 5 drafts →  ]          │
 └──────────────────────────────────┘
```

Keep it to the last three uploads. The bubble is a launcher, not the queue.

### 13.4 `static/js/capture_bubble.js`

Plain JavaScript, no framework, matching `static/js/expense_ai.js`. It must handle:

**Drag and drop.** `dragover`/`dragleave`/`drop` on the panel, and — nice touch — a full-window `dragover` that pops the bubble open when the user starts dragging anything over the page.

**Client-side pre-checks before uploading.** Type from `file.type` and the extension, and size from `file.size`. This is a courtesy, not security — the server checks everything again from the bytes. But it saves a 10 MB round trip to be told no.

**Page count is a server-side check only.** Counting PDF pages in the browser means shipping a PDF library; not worth it. The server answers in well under a second.

**Polling.** After a successful upload, `GET /capture/status` every 2 seconds. Stop when nothing is `processing`. Stop after 5 minutes regardless — a poll loop that outlives its reason is a bug that only shows up in production, in aggregate. Pause on `document.visibilityState === "hidden"` and resume on visible.

**One upload at a time from the bubble.** Disable the drop zone while a request is in flight. If the user has five files, they go one after another with a small queue in the JS.

**Error messages.** 4xx messages are shown to the user verbatim — the server wrote them in plain English for exactly this. A reason code from a 200 response shows a quiet "Could not read that one" and nothing more.

**Never `innerHTML` with a filename, a locator, or a supplier name.** Use `textContent`. Every one of those strings came from a file somebody uploaded.

**Accessibility.** The button needs `aria-label` and `aria-expanded`; the panel needs `role="dialog"` and `aria-modal="false"`; Escape closes it; focus returns to the button. Status changes go through an `aria-live="polite"` region — Stage 1's `aiLiveRegion` shows the pattern.

---

## 14. The Draft Queue page

`GET /capture` → `templates/capture/queue.html`, extending `templates/base/layout.html`.

### 14.1 Layout

A filter bar (All / Ready / Needs clarification / On hold / Rejected / Archived), then one card per draft.

Each card:

- **Left:** the document image, from `/capture/draft/<id>/file`, click to enlarge. If the upload produced several drafts, a small line reads "Document 2 of 5 · page 3".
- **Right:** the editable fields. Which fields depends on the destination — Petty Cash shows amount, description, supplier, account code, date; Payment shows those plus invoice number, due date and tax.
- Fields the AI filled carry a subtle marking. The marking disappears the moment the user edits the field. Copy the exact behaviour from `expense_ai.js` — this interaction is already designed and users have already learnt it.
- A field the AI was not confident about is **left blank**, not filled with a guess.
- **Actions:** Confirm, Archive, and — for a Petty Cash draft — a required "Add to report" dropdown, see 14.2.

### 14.2 The Petty Cash gotcha

`ShopExpense.report_id` is `nullable=False` with a foreign key to `pettycashv2.report.id`. A petty cash expense **cannot exist without a report**.

So a Petty Cash draft cannot be confirmed on its own. The card must carry a required "Add to report" dropdown listing the entity's open draft reports, and:

- Default to the most recently updated open draft report.
- If there are none, replace Confirm with a disabled button and the message *"You need an open petty cash report first."* plus a link that creates one.
- The user can change the target report per draft.

Do this early. It is the difference between the feature working and the feature being a nice list nobody can action.

### 14.3 The `hold` state

A draft whose destination came back `hold` shows a plain message: *"This looks like a supplier invoice. Payment Submission isn't switched on for this company, so there's nowhere to send it yet."* Confirm is disabled. Archive still works.

Do not hide these. The user should see that the system understood the document.

---

## 15. Confirm → destination

### 15.1 Petty Cash — a local write

Everything is in one database, so this is a normal transaction.

1. Load the target report; confirm it belongs to the resolved entity and is still an open draft.
2. Build a `ShopExpense`: `report_id`, `item`, `amount`, `remarks`, `contact_id`, `contact_name`, `account_id`, `account_code`, `s3_key`.
3. **Read `blueprints/report/routes/expense.py` before writing this.** The `files` column is `Text` and there is an established convention for what goes in it alongside `s3_key`. Match what that route does today; do not invent a second format.
4. Copy the document to the report's expense location in S3 so deleting a capture upload later never removes a file a posted expense depends on. Copy, do not move.
5. Commit `ShopExpense` and the draft's `status = "posted"` / `target_ref = <expense id>` **in one transaction**. Half of this succeeding is the one outcome worth real effort to avoid.

### 15.2 Payment Submission — a cross-service push

This one leaves the building.

**The URL.** Add `BILLING_BACKEND_URL` to Minty's environment. `docker/stack/docker-compose.yml` already carries `BILLING_BACKEND_PUBLIC_URL` for the frontend container; wire the same value into the Minty service.

**The token.** Reuse `_generate_module_token()` from `blueprints/entity/routes/modules.py`. It mints an HS256 JWT signed with the shared `SECRET_KEY` and containing `user_id`, `entity_id`, `xero_org_id`, `role` and an expiry. Module 2's backend already verifies exactly this token on every request it serves — nothing new to build on either side.

Refactor `_generate_module_token` into a service both blueprints can import rather than importing it out of a routes module. A routes-module import is how the circular-import problem described in `blueprint_loader.py` starts.

**The request.**

```
POST {BILLING_BACKEND_URL}/api/payment-requests/
Authorization: Bearer <jwt>
X-Entity-Id: <entity_id>
Content-Type: application/json
Idempotency-Key: <draft_id>
```

Body: supplier, invoice number, dates, amounts, currency, account code, description, plus a reference to the document.

**`Idempotency-Key: <draft_id>` matters.** The retry job in Section 12.4 will re-send after a timeout, and a timeout does not tell you whether the other side processed the request. Without an idempotency key, a slow response creates a duplicate payment request — which is a genuinely bad outcome, not a cosmetic one.

**The document.** Two options, and the choice is Module 2's to make:

- **Preferred:** we generate a short-lived presigned S3 URL and send that. Module 2 downloads the file itself. No large payload crosses between the services.
- **Fallback:** multipart upload of the file bytes.

**The response.** On 2xx: `status = "posted"`, `target_ref = <the PaymentRequest id from the response>`. On 4xx: `status = "send_failed"`, store the message in `last_error`, and **do not retry** — a 4xx will still be a 4xx in ten minutes. On 5xx or a timeout: `status = "send_failed"`, increment `send_attempts`, and let the retry job handle it.

**Timeout: 15 seconds.** Never call this synchronously inside the user's request without one.

> **CONFIRM BEFORE CODING — everything in this section that is outside the Minty repository:**
> 1. The exact endpoint path and JSON body for creating a PaymentRequest.
> 2. Whether the backend accepts a presigned URL for the attachment, or needs the bytes.
> 3. Whether it honours an `Idempotency-Key` header. If it does not, we need one, or a "find by external reference" endpoint to check before re-sending.
> 4. Whether a token minted by Minty (rather than handed to the browser) is accepted — including whether the 30-minute expiry is workable for a background retry, since a token minted at confirm time will be stale by the fifth retry. It may need minting fresh inside `push()` rather than being passed in.
>
> Do not guess any of these. Ask the Module 2 developer and write the answers into this document.

### 15.3 What the user sees when a send fails

The draft stays in the queue with a plain line: *"Couldn't send this to Payment Submission. We'll try again automatically."* Plus a manual Retry button.

It is never silently lost, and it never turns into a posted record that does not exist on the other side.

---

## 16. Status machine

### 16.1 `capture_upload.status`

| Status | Meaning | Goes to |
| --- | --- | --- |
| `queued` | Stored, waiting for a worker slot | `processing` |
| `processing` | Pass 1 or Pass 2 running | `done`, `rejected_*`, `failed` |
| `done` | Drafts created | — |
| `rejected_not_supported` | Pass 1 says this is not a receipt or invoice | `queued` (once, via the override) |
| `rejected_too_many` | More documents than the limit | — |
| `failed` | Something broke on our side | `queued` (manual retry) |

### 16.2 `capture_draft.status`

| Status | Meaning | Goes to |
| --- | --- | --- |
| `ready` | Fields extracted, waiting for the user | `confirming`, `archived` |
| `needs_clarification` | Read, but key fields are missing or low confidence | `confirming`, `archived` |
| `hold` | Understood, but the destination module is off | `archived` |
| `confirming` | User confirmed, push in progress | `posted`, `send_failed` |
| `send_failed` | Destination rejected it or was unreachable | `confirming` (retry), `archived` |
| `posted` | It became a real record. **Terminal.** | — |
| `archived` | User discarded it. Kept until retention. | — |

A draft is `needs_clarification` rather than `ready` when the amount is missing, or the document date is missing, or more than half the fields came back low-confidence. Tune that rule from real data; do not agonise over it now.

---

## 17. Security checklist

Work through this before opening a pull request.

- [ ] `entity_id` is resolved server-side on every route. A client-supplied value is never trusted.
- [ ] Every draft and upload read or write re-checks `row.entity_id == resolved entity`. Cross-entity access is a security defect, not a bug.
- [ ] A draft belonging to another entity returns **404**, not 403. Do not confirm that other companies' rows exist.
- [ ] File type is decided by magic bytes. The extension is not evidence.
- [ ] The upload route reads at most its own cap, not the global `MAX_CONTENT_LENGTH`.
- [ ] The AI's reply is untrusted input. Ids are accepted only when they appear in the list we sent in that same request.
- [ ] The prompt-injection paragraph from Stage 1's `_SYSTEM_INSTRUCTION` is present in both Pass 1 and Pass 2 prompts.
- [ ] File bytes are never logged, never put in an audit row, never put in an error message.
- [ ] `capture_ai_audit` holds numbers and reason codes only — no amounts, no supplier names.
- [ ] S3 keys never reach the browser. Files are streamed through an authorised endpoint.
- [ ] Everything from a document — filename, locator, supplier name, description — is rendered with `textContent`, never `innerHTML`.
- [ ] Rate limits are on, per user per minute and per entity per hour.
- [ ] The kill switch turns the whole feature off, including the bubble, without a deploy.
- [ ] The retention sweeper actually deletes the S3 objects, not only the rows.
- [ ] The data-residency note from Stage 1 §8.5 has been re-read and applies here too. The direct Gemini API pins no region, so documents may be processed outside Singapore. Stage 2 sends **more** documents, including supplier invoices, so if the Stage 1 customer disclosure needs updating, it needs updating before this ships.

---

## 18. Testing checklist

Tests go in `tests/`, following the existing files there.

**Unit — no database, no network:**

- `decide_destination()` — every row of the Section 11.4 table, including both-modules-off.
- Page clamping — the model returns pages 0, 4 and 2–1 on a 3-page PDF.
- Validation — an `account_id` that was not in the sent list is dropped; a negative amount is dropped; a four-letter currency is dropped; a 500-character description is truncated.
- Confidence banding at the exact cut-offs.

**Integration — database, mocked AI:**

- Upload rejects: 4-page PDF, a `.pdf` that is really a JPEG, an 11 MB file, an empty file, a corrupt PDF.
- The duplicate hash path returns the existing `upload_id` and makes no model call.
- A 3-document PDF creates exactly 3 drafts with the right page ranges.
- Pass 1 returning all-`other` creates **zero** drafts and makes **zero** Pass 2 calls. Assert the call count — this test is what protects the cost saving.
- The override re-runs and creates drafts. A second override is refused.
- Confirming a Petty Cash draft writes one `ShopExpense` and sets the draft to `posted`, in one transaction.
- Confirming a draft from another entity returns 404.
- Confirming an already-`posted` draft returns 409.
- The kill switch off: `/capture/upload` is 404 and the bubble does not render.
- A user with only `BILL` enabled can reach `/capture` — **this is the test that would have caught putting the routes in the `report` blueprint.**

**Manual, before release:**

- Drop a real 3-receipt PDF and watch three drafts appear one at a time.
- Kill the process mid-processing, wait for the sweeper, confirm the upload lands in `failed` and Retry works.
- Point `BILLING_BACKEND_URL` at a dead port and confirm the draft lands in `send_failed` and the retry job picks it up.
- Check the bubble on ten different pages, including ones that override `{% block scripts %}`.

---

## 19. Build order

Each step should be a separate pull request. Steps 1–4 ship dark behind `CAPTURE_AI_ENABLED=false`.

| # | Step | Done when |
| --- | --- | --- |
| 1 | Migration and models. Three tables, `models/db.py` wiring, the `.sql` twin. | `alembic upgrade head` works and `alembic downgrade` cleanly reverses it. |
| 2 | Blueprint skeleton and the gate. Empty routes, module guard, `blueprint_loader` wiring, config readers, `.env.example`. | A logged-in user with either module hits `/capture` and gets an empty page; a user with neither gets 403; kill switch off gets 404. |
| 3 | Upload endpoint and storage. All of Section 10.1 **except** starting the pipeline. | Every rejection in Section 3.1 returns the right message; a good file lands in S3 and creates a `queued` row. |
| 4 | `pdf_tools` — page count and page extraction. | Unit tests pass on a 1-page, a 3-page and a corrupt PDF. |
| 5 | `capture_ai.split_and_classify` (Pass 1) plus the audit row. | A 3-receipt PDF returns 3 documents with correct page ranges; a bank statement returns all-`other`. |
| 6 | `capture_ai.extract` (Pass 2), both schemas, validation. | Fields come back for a single receipt with confidence bands. |
| 7 | `routing.decide_destination` plus its tests. | The Section 11.4 table is fully covered. |
| 8 | `pipeline.py` — the thread, the semaphore, per-draft commits, the stuck sweeper. | Upload a 3-document PDF and watch three `capture_draft` rows appear one at a time. |
| 9 | `GET /capture/status` and `GET /capture/drafts`. | Both return correct counts and respect the entity filter. |
| 10 | The bubble — partial, context processor, JS, polling. | Upload from any page and watch the badge climb. |
| 11 | The queue page and confirm-to-Petty-Cash, including the report dropdown. | A confirmed draft becomes a real `ShopExpense` on a real report. |
| 12 | The override and Archive. | Both work end to end. |
| 13 | **Payment Submission push.** Do not start until Section 15.2's CONFIRM items are answered. | A confirmed invoice draft creates a PaymentRequest in Module 2. |
| 14 | Retry and retention sweepers. | A dead backend produces `send_failed` and an automatic retry; old uploads and their S3 objects are deleted. |
| 15 | Turn it on for one pilot entity. | Real receipts, real users, real numbers in `capture_ai_audit`. |

Step 13 is the only one that can be blocked by another team. Everything before it is entirely within this repository — so if the Module 2 conversation is slow, the feature still gets to a genuinely useful state (Petty Cash capture with automatic splitting) without it.

---

## 20. Open items to confirm before coding

| # | Question | Ask | Blocks |
| --- | --- | --- | --- |
| 1 | The exact PaymentRequest endpoint, body and response shape. | Module 2 developer | Step 13 |
| 2 | Does the backend accept a presigned URL for the attachment, or does it need the bytes? | Module 2 developer | Step 13 |
| 3 | Does it honour `Idempotency-Key`? If not, how do we avoid duplicates on retry? | Module 2 developer | Step 13 |
| 4 | Will a JWT minted by Minty be accepted, and what expiry works for a background retry? | Module 2 developer | Step 13 |
| 5 | Does a Payment-only user hold `REPORT_EDIT_OWN`? If not, we need a new permission and a grant migration. | Whoever owns `permission_policy.py` | Step 2 |
| 6 | Does the Stage 1 customer data disclosure already cover invoices being sent to Gemini, or does it need updating? | Whoever owns the Stage 1 §8.7 disclosure | Step 15 |
| 7 | Which model — reuse Stage 1's `gemini-3.5-flash`, or is Pass 1 (multi-page reasoning) worth a stronger one? Measure in step 5 before deciding. | Measurement, not opinion | Step 5 |

---

## Appendix A — environment variables

Add this block to `.env.example`, following the commenting style of the existing `EXPENSE_AI_*` block.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CAPTURE_AI_ENABLED` | `false` | Master kill switch. Off = no bubble, `/capture/*` returns 404, no model call is possible. |
| `CAPTURE_AI_MODEL` | `gemini-3.5-flash` | Must be a Gemini 3.x id. The 2.5 family is listed by `models.list()` but returns 404 on `interactions.create`. |
| `CAPTURE_AI_THINKING_LEVEL` | `low` | `low`, `medium` or `high` |
| `CAPTURE_AI_MAX_OUTPUT_TOKENS` | `4096` | Thinking tokens come out of this same allowance. Too low truncates the JSON mid-object. |
| `CAPTURE_AI_TIMEOUT_S` | `40` | Higher than Stage 1's 25 — nobody is staring at a form field waiting for this. |
| `CAPTURE_AI_MAX_FILE_MB` | `10` | |
| `CAPTURE_AI_MAX_PAGES` | `3` | |
| `CAPTURE_AI_MAX_DOCUMENTS` | `10` | |
| `CAPTURE_AI_MAX_CONCURRENT` | `4` | Process-wide semaphore |
| `CAPTURE_AI_CONF_HIGH` | `0.85` | Set from real data during the pilot. The default exists so the feature is runnable during measurement. |
| `CAPTURE_AI_CONF_MEDIUM` | `0.60` | Same |
| `CAPTURE_AI_RATE_USER_PER_MIN` | `5` | Lower than Stage 1's 10 — one upload here can cost eleven model calls |
| `CAPTURE_AI_RATE_ENTITY_PER_HOUR` | `100` | |
| `CAPTURE_RETENTION_DAYS` | `90` | |
| `CAPTURE_DEDUPE_DAYS` | `30` | How far back the duplicate check looks |
| `BILLING_BACKEND_URL` | *(none)* | Module 2 backend base URL. Unset = the Payment destination is unavailable and invoices go to `hold`. |

Credentials are shared with Stage 1 — `GEMINI_API_KEY`, or `GOOGLE_CLOUD_PROJECT` plus `EXPENSE_AI_LOCATION` for the Vertex route. Do not add a second key.

---

## Appendix B — JSON shapes

### B.1 Pass 1 output, after validation

```json
{
  "documents": [
    {
      "page_start": 1,
      "page_end": 1,
      "locator": "top receipt, Starbucks HK$48",
      "doc_type": "receipt",
      "doc_type_confidence": 0.94,
      "other_reason": ""
    },
    {
      "page_start": 2,
      "page_end": 3,
      "locator": "invoice from CLP Power, 2 pages",
      "doc_type": "invoice",
      "doc_type_confidence": 0.91,
      "other_reason": ""
    }
  ]
}
```

### B.2 `capture_draft.suggested`

Field shape is identical to Stage 1's, so the queue page can reuse `expense_ai.js`'s marking logic:

```json
{
  "amount":       { "value": "128.50", "confidence": 0.96, "band": "high",   "applied": true },
  "description":  { "value": "Taxi to client meeting", "confidence": 0.88, "band": "high", "applied": true },
  "supplier":     { "value": "", "confidence": 0.0, "band": "low", "applied": false,
                    "contact_id": "", "detected_name": "Hong Kong Taxi" },
  "account":      { "value": "429 Travel", "confidence": 0.79, "band": "medium", "applied": true,
                    "account_id": "…", "code": "429", "name": "Travel" },
  "document_date":{ "value": "2026-09-03", "confidence": 0.93, "band": "high", "applied": true },
  "currency": "HKD",
  "entity_currency": "HKD"
}
```

Invoice drafts carry the same shape plus `invoice_number`, `due_date`, `tax_amount` and `subtotal_amount`, each in the same `{value, confidence, band, applied}` form.

`applied: false` means **the queue leaves that field blank**. It is not a suggestion the user should have to delete. `detected_name` on a supplier that matched nothing is the exception: the model read a real name off the document, and offering it as a starting point for the New Contact panel saves the user retyping something we already have.

### B.3 A queue row from `GET /capture/drafts`

```json
{
  "id": "…",
  "upload_id": "…",
  "sequence": 2,
  "of": 3,
  "original_filename": "march-receipts.pdf",
  "page_start": 2,
  "page_end": 2,
  "doc_type": "receipt",
  "destination": "petty_cash",
  "status": "ready",
  "file_url": "/capture/draft/…/file",
  "suggested": { "…": "as in B.2" },
  "created_at": "2026-09-07T10:04:11+00:00"
}
```

---

*End of document.*
