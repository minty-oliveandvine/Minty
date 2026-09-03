# Minty · Petty Cash · Stage 1 Implementation Plan
## AI-Assisted Expense Capture on the Expense Page

**Document control**

| Field | Value |
|---|---|
| Governing document | *AI Adoption Stage 1* — Three Brains, three concepts, exclusion list |
| Scope | `/report/expense` — the **Add New Expense** card |
| Approach | Vision-capable AI model. Explicitly **not** an OCR service. |
| Provider | **Google Gemini**, called through **Google Cloud Vertex AI** |
| Region | **`asia-southeast1` (Singapore)** — the region the application already runs in. See §5.3. |
| Recommended model | **Gemini 3.1 Pro** (`gemini-3.1-pro-preview`) for the spike; newest GA Flash for production. See §5.4. |
| Fields filled | Expense Amount, Description, Supplier, Account Code |
| Owner | Engineering — Petty Cash |
| Status | Draft for engineering and operations review |
| Version / date | **v3.1 — 3 September 2026** |

**Change log**

| Version | Date | Change |
|---|---|---|
| v2.0 | 2 Sep 2026 | First full plan. Recommended Claude Opus 5 via the Anthropic API. |
| v3.0 | 3 Sep 2026 | Provider changed to Gemini. Access analysis written on the assumption that our calls originate in Hong Kong. **Superseded — see below.** |
| **v3.1** | **3 Sep 2026** | **Access analysis corrected.** The application servers run in **Singapore**, not Hong Kong, and Google applies its regional restriction to the region the *calling instance* is in. Singapore is a supported region, so the developer APIs were never closed to us. **Gemini is unchanged as the provider and Vertex AI is unchanged as the route** — but the reason is now data governance and latency rather than availability, and the region is `asia-southeast1`. Rewritten: §1.5, §5.2, §5.3, §5.5, §8.5, §15 Stage 0, §17. Costs, SDK usage, error handling and the whole feature design are unaffected. |

---

## 1. Purpose and Scope

### 1.1 What this document does
The *AI Adoption Stage 1* plan sets the architecture: three brains, a **suggestion engine rather than an accounting engine**, and an explicit list of what we are not building. This document translates that architecture into a buildable specification for one page — the Add New Expense card on `/report/expense` — and names the model to call.

### 1.2 In scope
- Reading an attached receipt and suggesting four field values on the Add New Expense card.
- The server endpoint, the model call, response validation, and the on-screen suggestion states.
- Security, data handling, error handling, rollout and rollback for that feature.

### 1.3 Out of scope
- Any change to how an expense is validated, totalled, saved, or published to Xero.
- Any feature on a submitted report. The feature exists only on the draft entry card.
- Everything on the Stage 1 exclusion list (Section 12).
- Duplicate-receipt detection, which appeared in an earlier Minty proposal. It is not part of Stage 1 and should be considered separately.

### 1.4 Two items requiring a decision
Two items in the strategy document have no home on the current form: **date** and **invoice number**. They are raised in Section 13 rather than quietly dropped. Neither blocks delivery.

### 1.5 Provider history, and a correction

v2.0 recommended Claude Opus 5 through the Anthropic API. That was set aside on availability grounds, and **Gemini is the provider from v3.0 onward**. That decision stands and this revision does not reopen it.

What this revision corrects is the *reasoning about access*, which was wrong in a way worth recording.

> **What the v3.0 draft got wrong.** It treated Hong Kong as the region our requests originate from, and concluded that the direct developer APIs of both Anthropic and Google were closed to us. **Hong Kong is where the team is. It is not where the code runs.** The application servers are in **Singapore**, Google applies its regional restriction to the region of the *calling instance* rather than the user, and Singapore is on Google's supported list. The developer API was open the whole time.

The correction does not change the provider and it does not change the route — Gemini through Vertex AI remains the recommendation. It changes the **reason**, from *"nothing else is available to us"* to *"this is the better of two available options"*, and it changes the **region**, from a constrained Hong Kong endpoint to `asia-southeast1`, which is where the application already runs.

That is worth the rewrite for three practical reasons:

1. A recommendation resting on a wrong premise is fragile. Anyone who checks the premise finds it false and reasonably doubts everything built on it.
2. The corrected picture is materially **better**. Singapore's Vertex region carries a broad model catalogue, so the region no longer constrains the model choice; and the residency story becomes simple rather than awkward (§8.5).
3. It moves work off the critical path. v3.0 made a Legal contracting question a prerequisite for pilot. On the corrected facts that is ordinary procurement, not a risk (§17).

**The general lesson, recorded so it is not re-learned:** when checking whether a service is available, check it *from where the code runs*, not from a browser on someone's desk. The two answers differ, and the second one is not the one that matters.

---

## 2. Alignment with the AI Adoption Stage 1 Strategy

Every requirement in the strategy document maps to a section of this plan. Nothing is added that the strategy does not call for.

| Strategy requirement | Where it lands in this plan | Status |
|---|---|---|
| Brain 1 — AI understands the document | §3.1, §7.2 model call | Covered |
| Brain 1 — AI applies general business knowledge | §3.1, §4 (why not OCR) | Covered |
| Brain 2 — Minty supplies chart of accounts | §3.2 context assembly | Covered |
| Brain 2 — Minty supplies entity and supplier information | §3.2 context assembly | Covered |
| Brain 3 — User is the final authority | §3.3, §7.4 suggestion states | Covered |
| AI never posts automatically | §3.3, §6.3 | Covered |
| Concept 1 — Structured output | §6.1 (schema-enforced JSON) | Covered |
| Concept 2 — Confidence on every suggestion | §6.2 (per-field confidence + calibration) | Covered |
| Concept 3 — Suggestion engine, not accounting engine | §6.3 (explicit non-responsibilities) | Covered |
| Not building: entity learning engine | §12 | Excluded |
| Not building: historical behaviour engine | §12 | Excluded |
| Not building: multi-provider AI routing | §5.6, §12 | Excluded |
| Not building: AI orchestration platform | §12 | Excluded |
| Not building: custom accounting intelligence | §12 | Excluded |
| Extract date | §13.1 | **Decision required** |
| Extract invoice number | §13.2 | **Decision required** |

**Founder decision rule applied.** For every capability below we asked: *can the AI already solve this using its existing business knowledge?* Where the answer is yes, we use the model. Where the answer requires knowledge unique to one client — "PARKnSHOP is pantry for Client A but inventory for Client B" — we have deferred it to a future intelligence phase. Nothing client-specific is being built in Stage 1.

---

## 3. The Three Brains, Mapped to Minty

### 3.1 Brain 1 — AI Knowledge (primary intelligence)
The model receives the receipt and performs **two jobs, not one**:

- **Understanding the document** — reads the image or PDF and returns supplier, amount and description.
- **Applying business knowledge** — recognises the vendor and knows what kind of expense it represents. SF Express is courier. China Mobile is telephone. Hong Kong Electric is utilities. **We teach it none of this.**

The second job is the reason this cannot be an OCR service, and it is the central argument of the strategy document. Section 4 sets out what that rules out.

### 3.2 Brain 2 — Minty Context
Everything the model cannot know on its own, sent with the receipt on every request. All of it already exists in Minty and already populates the dropdowns on the same form.

| Context | Source in Minty | Why the AI needs it |
|---|---|---|
| Chart of accounts | Entity's synced Xero accounts (`sync_chart_of_accounts_if_changed`) | So it recommends `5100 Courier Expense` rather than inventing a category. |
| Supplier list | Entity's synced Xero contacts (`XeroContactSync`) | So a suggested supplier is one the user can actually select. |
| Entity information | Company name, country, base currency | Improves recommendations and lets us flag a currency mismatch. |

> **This is the whole of Minty's contribution in Stage 1: context, not intelligence.** We supply the lists and the company facts; the model supplies the judgement. Nothing here learns, ranks by history, or accumulates over time.

**Context assembly rules**
- Assemble server-side only. The browser never chooses what context is sent.
- Scope strictly to the entity resolved for the request. Cross-entity leakage is a security defect, not a bug (§8.2).
- Send only the fields listed above — account code, account name, contact id, contact name, entity name, country, currency. No transaction history, no amounts, no user data.
- Sort lists deterministically (by code, then id) so the cached prefix stays byte-stable (§7.3). **This is load-bearing on Gemini**, whose caching is implicit prefix matching with no explicit cache marker: unstable ordering does not merely reduce the hit rate, it eliminates it.

### 3.3 Brain 3 — User
The Add New Expense card **is** Brain 3. The strategy flow maps onto it exactly as written:

```
AI Suggestion   ->  the four fields arrive prefilled and marked as suggestions
User Reviews    ->  every field stays editable; low confidence is left blank
User Confirms   ->  the user edits, tabs past, or presses Add
Save            ->  Add submits exactly what it submits today
```

- The user may **accept**, **change**, or **override completely**.
- Nothing posts automatically. The model has no write path to any record.
- The feature never appears on a submitted report.
- **The user can always ignore it.** With the feature switched off, the card behaves exactly as it does today.

---

## 4. Why This Is Not OCR — and What That Rules Out

The strategy is explicit that the goal is **not** `Receipt → OCR → Done`. That single line has a concrete procurement consequence, because the obvious candidates are receipt-parsing services.

| Ruled out | What it does | Why it fails Stage 1 |
|---|---|---|
| AWS Textract — `AnalyzeExpense` | Returns merchant, total and line items as typed fields | Extraction only. It can read "SF Express, HKD 120" but has no idea that means Courier Expense, and cannot choose from our chart of accounts. |
| Google Document AI | Same class of receipt parser | Same reason. Note this is **not** the same product as Gemini on Vertex AI, despite both being Google Cloud: Document AI is the parser we are ruling out; Gemini is the model we are choosing. |
| Azure Document Intelligence | Same class of receipt parser | Same reason. |
| Tesseract / PaddleOCR | Raw text only | Everything after the text is a parser we would write and maintain. No business knowledge at all. |

All four cover Brain 1's *first* job and none of them cover the *second*. A vision-capable AI model does both in a single call, which is why the strategy points there.

> **Correction carried forward from v2.0.** An early draft argued that Textract was the obvious candidate "because Minty already runs on AWS". That is only half true and should not be used as an argument. The application database runs on AWS RDS, but receipt files are stored in **Backblaze B2** via the S3-compatible API (`blueprints/report/services/s3_storage.py`, endpoint `s3.<region>.backblazeb2.com`). There is no existing Textract adjacency to trade on, so the decision rests entirely on capability — which is the correct basis anyway.

---

## 5. Model Selection

### 5.1 What Stage 1 requires of the model

- [ ] **Vision** — reads an image or a PDF. The upload accepts `.pdf, .jpg, .jpeg, .png`.
- [ ] **Business knowledge** — knows Hong Kong vendors: SF Express, PARKnSHOP, China Mobile, Hong Kong Electric.
- [ ] **Structured output** — returns valid JSON reliably, not prose. This is Concept 1.
- [ ] **Constrained selection** — picks from a supplied list rather than generating a value.
- [ ] **Multilingual** — many Hong Kong receipts are Traditional Chinese or mixed script.
- [ ] **Callable from where our code runs, on terms we can accept for customer documents** — see §5.2. Gemini clears this on both halves; the second half is what decides the route.

### 5.2 Where we call from, and what that opens

**Our servers are in Singapore.** That single fact determines what is available, and it is the fact the v3.0 draft got wrong (§1.5). Google states plainly that its regional restrictions are applied on the region of the **calling instance**, not the region of the user — and **Singapore is on the supported list**.

| Route | Open to our Singapore servers? | Detail |
|---|---|---|
| **Google Cloud Vertex AI**, `asia-southeast1` | **Yes — chosen** | Enterprise Google Cloud terms, an in-region endpoint with a published ML-processing residency commitment, IAM instead of an API key, and a broad in-region model catalogue (50+ models across publishers). |
| Gemini API direct (`ai.google.dev`) | **Yes** | Singapore is a supported region. Genuinely viable and much faster to start — but with the data-handling limits in §5.3. Suitable for a spike on non-customer receipts; not for customer documents. |
| Amazon Bedrock | Yes | Under AWS terms. A fallback — see §5.5. |
| Microsoft Foundry / Azure OpenAI | Yes | Under Azure terms, with an APAC Data Zone. A fallback — see §5.5. |
| Anthropic API direct | Likely, from Singapore | Not pursued. Gemini is the chosen provider (§1.5); recorded here only so the list is complete and the v3.0 claim is not left standing uncorrected. |

> **The choice is now a real one.** Two Google routes are open to us and we are picking between them on merit, not taking the only one left. §5.3 says which, and why, and when the other is the right tool.

**One rule survives from v3.0 unchanged.** We do not reach a restricted endpoint through a VPN, a proxy, or a third-party API reseller. It breaches the provider's terms and would route customer financial documents through an unvetted intermediary with no data-protection agreement. Nothing in this plan requires it, and nothing in a future revision should.

### 5.3 Recommendation

> **Call Gemini through Google Cloud Vertex AI, on the `asia-southeast1` (Singapore) regional endpoint** — the same region the application already runs in.

**Why Vertex rather than the direct Gemini API**

1. **The AI call introduces no new jurisdiction.** Customer receipts already live in Singapore. A Singapore regional endpoint keeps model inference there too, and Google publishes an ML-processing residency commitment for Generative AI on Vertex AI in that region. **This feature moves no customer data across a border it does not already cross** — which is the entire compliance conversation, answered in one sentence.
2. **The direct API cannot make that promise.** Even on the paid tier, Google's Gemini API terms reserve the right to store or cache data "in any country in which Google or its agents maintain facilities". For a bookkeeping product holding clients' financial documents that is a real gap, not a technicality.
3. **No long-lived API key.** Vertex authenticates with IAM, and Workload Identity Federation from our AWS role means there is no secret to leak, rotate, or accidentally commit (§8.1).
4. **Co-located with the application.** Same region, lowest latency, on a path where a user is watching a form.
5. **The region does not constrain the model.** `asia-southeast1` carries a broad catalogue — 50+ models across Google, Anthropic, Alibaba, OpenAI and others. Model choice and region choice are independent here, which was not true of the Hong Kong region the v3.0 draft was steering towards.

**When the direct Gemini API is the right tool**

It is legitimately faster to start: an API key and one dependency, with no project, IAM, or federation work. That is worth something during a spike.

- Use it **only on the paid tier**. The free tier's terms let Google use submitted content to "provide, improve, and develop Google products" and let **human reviewers read, annotate, and process your API input and output**. That is categorically unacceptable for a customer receipt, and the distinction is easy to miss because both tiers use the same SDK and the same code.
- Use it **only with non-customer receipts** — our own, or synthetic. The moment a real client document is involved, the residency gap in point 2 applies.
- Moving to Vertex afterwards is a **client-construction change, not a rewrite**: same `google-genai` package, same call shape, different constructor arguments (§7.3).

> **Recommended path:** stand Vertex up in Stage 0, which is half a day, and run the whole spike on it. Reach for the direct API only if Stage 0 is blocked on something outside engineering's control and the spike would otherwise stall — and if you do, on the paid tier with non-customer receipts.

**One caveat remains from v3.0**

`gemini-3.1-pro-preview` is a **preview model**. Preview models change behaviour, can be retired at short notice, and are frequently excluded from enterprise availability and support commitments. It is the right instrument for measuring the accuracy ceiling in a throwaway spike. It must not be the production pin. If the spike shows that only Pro clears the accuracy bar, wait for the GA release or re-open §5.5 — do not ship a preview model into a customer path.

*(The v3.0 caveat about a narrow regional model catalogue is withdrawn. It applied to `asia-east2`; it does not apply to `asia-southeast1`. Confirming the region's current model list is still the first task of Stage 0, but as a routine check rather than a risk.)*

### 5.4 Models and pricing

Model choice is a cost decision that belongs to the business, not to engineering. The spike runs on the strongest candidate so the accuracy figure is a **ceiling** rather than a compromise; stepping down then becomes an informed decision instead of a hopeful one.

| Model | Model ID | Input / 1M | Output / 1M | Note |
|---|---|---|---|---|
| Gemini 3.1 Pro (preview) | `gemini-3.1-pro-preview` | $2.00 | $12.00 | **Spike here.** Highest accuracy. Preview — see §5.3. Input rate quoted is for prompts ≤ 200k tokens; ours are ~5k. |
| Gemini 3.8 Flash | `gemini-3.8-flash` | $0.75 | $3.75 | **Likely production choice.** Promotional rate through **31 December 2026** — budget at the post-promotional rate, not this one. |
| Gemini 3.5 Flash | `gemini-3.5-flash` | $1.50 | $9.00 | Stable, non-promotional Flash pricing. A reasonable proxy for what 3.x Flash costs once the promotion ends. |
| Gemini 2.5 Flash | `gemini-2.5-flash` | $0.30 | $2.50 | Cheapest credible option. Older; test vendor knowledge before assuming. |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | $0.30 | $2.50 | Cheapest tier. Likely too weak for the business-knowledge half of Brain 1. Test before assuming. |

**Three warnings attached to this table**

- These are the **Gemini API list prices published by Google, checked on 3 September 2026**. **Vertex AI publishes its own price list**, and per-token rates there are not guaranteed to match. Re-verify against the Vertex AI pricing page before committing a number to a budget, and again at every stage gate (§14.3).
- The Flash promotional rate expires **31 December 2026**. A cost model built on $0.75 / $3.75 will be wrong in January. Budget at the Gemini 3.5 Flash rate and treat the promotion as upside.
- Preview-model pricing is not a commitment.

### 5.5 Alternatives to Gemini

Gemini is the decision (§1.5) and none of the following is being built alongside it (§5.6). This is a **procurement fallback list**, kept so that a commercial or capability setback costs a provider swap rather than a restart. On the corrected facts every entry is reachable from Singapore, so the list is genuinely available rather than theoretical.

**1. Claude via Vertex AI Model Garden — the cheapest hedge**

Claude models are offered through Vertex AI Model Garden, and Google lists Claude among the models with ML-processing guarantees in `asia-southeast1`. Same project, same billing account, same credentials, same region.

- *For:* once we are on Vertex for Gemini, this costs almost nothing to keep open. A switch is a model string and a request shape inside one module — no new vendor, contract, region, or auth mechanism.
- *Against:* nothing structural. It is simply not the chosen provider.
- *Verdict:* **the strongest fallback, and a real argument for the Vertex route independent of §5.3.** Choosing Vertex buys this option for free.

**2. Claude via Amazon Bedrock**

- *For:* Claude under AWS terms, and Minty's application database already runs on AWS.
- *Against:* a second AI vendor relationship when option 1 needs none. Bedrock regional availability for the newest Claude models is narrower than Vertex's.
- *Verdict:* keep on the list; option 1 is strictly easier for us.

**3. GPT-5.x via Microsoft Foundry / Azure OpenAI**

- *For:* strong vision and structured output. The APAC Data Zone gives regional processing.
- *Against:* a third cloud vendor, with new identity, billing and network plumbing and no existing adjacency.
- *Verdict:* the fallback if both Google routes fail.

**4. Qwen3-VL via Alibaba Cloud Model Studio (Singapore endpoint)**

- *For:* the strongest native handling of Traditional and Simplified Chinese in this list, which speaks directly to §17 open question 6. Roughly an order of magnitude cheaper than Gemini Flash, and a free evaluation quota makes a comparison arm nearly free. The Singapore endpoint matches where our data already sits.
- *Against:* **the blocker is governance, not technology.** Routing clients' financial documents to a PRC-headquartered vendor is a decision for the business and for our clients, and for an accounting product it may be unacceptable to some clients regardless of where the endpoint sits. Separately, "choose the right code from these 200 Xero accounts" is the capability least evidenced by public benchmarks.
- *Verdict:* **do not adopt without an explicit business decision.** It is a genuinely useful *measurement*, though: adding it as a comparison arm on the same receipts costs very little and would tell us how much accuracy on Chinese-language receipts we are trading away. Recommended as a spike comparison only, with the numbers put to the business alongside the governance question.

### 5.6 One provider, no routing
The strategy rules out multi-provider AI routing. Section 5.5 does not change that and must not be read as licence to build a provider abstraction. We take the exclusion literally:

- One provider, one model, **one function** that makes the call.
- No fallback chain, no provider abstraction layer, no runtime model selection.
- The model ID is a single configuration value, not a per-request parameter.

Keeping the call inside a single module (`blueprints/report/services/expense_ai.py`) is enough to make a future change cheap without building the routing the strategy excludes. **The v2.0 → v3.0 provider change is the evidence that this is the right call**: the provider changed completely, and the change was confined to a handful of sections here and would be confined to one module in the codebase.

### 5.7 Request configuration
- **Thinking:** Gemini 3 models expose `thinking_level` (`low` / `medium` / `high`). Start at **`low`** and tune from spike data. Receipt extraction is a bounded perception-and-lookup task, not a reasoning problem; the top of the range is unlikely to earn its cost. Measure before defaulting higher.
- **`max_output_tokens`:** ~1,024 is ample for the JSON reply. Do not lowball further — a truncated reply is a wasted call.
- **Safety settings:** configure them explicitly and treat a safety block as "no suggestion" (§9.1). A receipt should never trip a safety filter, but a false positive must degrade quietly rather than surface an error to the user.
- **Streaming:** not required. The reply is small and the call is a single request/response.
- **Batch API:** not applicable. This is an interactive request; the batch discount cannot be used here.

---

## 6. The Three Concepts, Implemented

### 6.1 Concept 1 — Structured output
The reply is a fixed JSON shape **enforced by the API** through a supplied JSON Schema, not requested politely in the prompt.

```json
{
  "supplier":    { "contact_id": "…", "name": "SF Express",   "confidence": 0.93 },
  "account":     { "account_id": "…", "code": "5100",
                   "name": "Courier Expense",                 "confidence": 0.88 },
  "amount":      { "value": 120.00,                           "confidence": 0.97 },
  "description": { "value": "Courier delivery",               "confidence": 0.81 },
  "currency":    "HKD"
}
```

**Rules**
- Define the schema once as a Pydantic model and pass `Model.model_json_schema()` to the request. Parse the reply with `Model.model_validate_json(...)`. One definition, used for both enforcement and validation.
- Any field the model cannot read comes back **empty rather than guessed**.
- Supplier and account are returned as **ids drawn from the lists we supplied**.
- Minty re-checks every id against the lists it sent before the reply reaches the page (§6.3, §8.3). An id that is not in the sent list is dropped, not corrected.
- A parse failure is an error path (§9), never a partial fill.

> **Do not put the chart of accounts into the schema as an enum.** It is tempting — it would let the API enforce constrained selection directly. It is wrong here: a 200-account enum makes the schema large enough to risk rejection, it re-sends on every call, and it invalidates the cached prefix whenever Xero syncs. The accounts go in the **prompt context**, and constrained selection is enforced by **Minty's own id check** (§8.3). That check is required regardless, so the enum would buy nothing and cost a great deal.

### 6.2 Concept 2 — Confidence
Every field carries **its own** confidence, because one receipt can have a crisp total and an illegible supplier. The strategy's examples set the shape of the rule: 95 % is good, 55 % needs review.

| Confidence band | Behaviour on the card |
|---|---|
| High | Field is prefilled and marked as a suggestion. |
| Medium | Field is prefilled and marked more strongly for review. |
| Low | **Nothing is prefilled.** A wrong suggestion costs the user more than no suggestion. |

**Calibration is required, not optional.** Confidence is self-reported by the model; it is a useful signal, not a measured probability. The spike must report **accuracy per confidence band per field**, and the band cut-offs are set from that table. Until then the cut-offs are unset, not guessed. Cut-offs are held in configuration so they can be tuned without a deployment.

### 6.3 Concept 3 — Suggestion engine, not accounting engine
The accounting logic stays in Minty. Concretely, the model never touches any of these:

- **Validating that a suggested account is real** — Minty re-checks it against the entity's list.
- **Creating a supplier** — if there is no match the field is left empty and the user uses the existing New Contact panel.
- **The expense total, the closing balance, or any figure on the report.**
- **Anything to do with publishing to Xero.**
- **Deciding whether the expense is valid** — Add validates exactly as it does today.

---

## 7. Solution Design on the Expense Page

### 7.1 End-to-end flow

```
1  User attaches a receipt on the Add New Expense card         (unchanged)
2  Browser POSTs the file to /report/expense/extract           (new)
3  Server authenticates, authorises the entity, rate-limits    (§8)
4  Server assembles accounts, contacts, entity facts           (Brain 2)
5  Server calls the model: document + context + JSON schema    (Brain 1)
6  Server validates returned ids against the lists it sent     (§6.3)
7  Four fields arrive on the card, marked as suggestions       (Brain 3)
8  User checks, adjusts if needed, presses Add                 (unchanged)
```

> **Step 8 is untouched.** Reading the receipt happens *beside* the form, never inside Add. If the model is slow, rate limited, or down, the card behaves exactly as it does today and the user types the four fields. **Expense entry can never be blocked by an AI outage.**

**Two facts about the current page that shape the design**
1. Receipt files are uploaded to object storage **only when the expense is submitted**. At attach time the file exists solely in the browser, so the extract endpoint must receive the bytes in its own request — it cannot read them from storage.
2. An expense row may carry **several attachments**. Stage 1 extracts from the **first** attached file only; additional files are ignored. Anything more is a Stage 2 question.

### 7.2 Endpoint contract

| Item | Specification |
|---|---|
| Route | `POST /report/expense/extract` |
| Auth | `@login_required` — same as `/report/expense` |
| Authorisation | `has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id)`, with `entity_id` resolved server-side by the existing helper |
| CSRF | Inherits the application-wide `CSRFProtect`. **Do not add a CSRF exemption.** |
| Request | `multipart/form-data`: one file plus `entity_id` |
| Accepted types | `application/pdf`, `image/jpeg`, `image/png` — validated by sniffed content, not by file extension |
| Size cap | 10 MB per request, enforced on this route. The global `MAX_CONTENT_LENGTH` of 2 GB is far too permissive for a model call. |
| Response | `200` with the validated suggestion object, or `200` with `{"suggestions": null, "reason": "<code>"}`. See §9. |
| Timeout | 20 s client-side, 25 s server-side. SDK defaults are far too generous for an interactive path. An in-region endpoint (§5.3) makes this comfortable. |
| Idempotency | None required. The call has no side effects beyond the audit row. |

### 7.3 The model request

The receipt and the Minty context go in one call, against the **`asia-southeast1` Vertex AI regional endpoint**.

```python
from google import genai
from pydantic import BaseModel

# One client per process. Vertex AI mode — IAM, not an API key. See §8.1.
client = genai.Client(
    vertexai=True,
    project=settings.GOOGLE_CLOUD_PROJECT,
    location=settings.EXPENSE_AI_LOCATION,      # "asia-southeast1" — see §8.5
    http_options={"timeout": 25_000},           # milliseconds
)

interaction = client.interactions.create(
    model=settings.EXPENSE_AI_MODEL,
    input=[
        # Stable prefix FIRST — this is what implicit caching matches on.
        {"type": "text", "text": INSTRUCTION + entity_context
                                 + chart_of_accounts + supplier_list},
        # Then the variable part: the receipt itself.
        {"type": "document", "data": base64_bytes, "mime_type": "application/pdf"},
        {"type": "text", "text": "Extract the four fields."},
    ],
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": ExpenseSuggestion.model_json_schema(),   # the schema from §6.1
    },
    generation_config={
        "thinking_level": "low",            # §5.7
        "max_output_tokens": 1024,
    },
)

suggestion = ExpenseSuggestion.model_validate_json(interaction.output_text)
```

**Notes on this call**

- **SDK:** `pip install -U google-genai`, imported as `from google import genai`. The older `google-generativeai` package and the generative-AI modules inside the Vertex AI SDK (`vertexai.generative_models`) are both **deprecated** — do not start there. The `interactions.create` API is the current shape; `models.generate_content` still exists and is what the older examples in circulation use.
- **The direct Gemini API uses the same package and the same call.** Only the client constructor differs — `genai.Client(api_key=...)` instead of the Vertex arguments above. That is what makes the §5.3 fallback cheap, and also what makes it easy to end up on the wrong tier by accident. If both are ever configurable, make the Vertex path the default and the API-key path an explicit opt-in.
- **Images** are passed the same way as the PDF above, with `mime_type` set to `image/jpeg` or `image/png`.
- Reuse the existing `downsize_bytes` helper (`blueprints/report/services/file_downsize.py`) before sending, so large phone photos do not inflate the input token count. Gemini rescales pages to a maximum of 3072 × 3072 in any case, so sending more resolution than that is pure waste.
- Inline base64 is correct for our 10 MB cap. The Files API exists for larger uploads and adds a round trip we do not need.

**Caching on Gemini differs from the v2.0 Anthropic design — read this before assuming the old cost model.**

| | v2.0 (Anthropic) | Now (Gemini on Vertex) |
|---|---|---|
| Mechanism | Explicit — `cache_control: {"type": "ephemeral"}` on a content block | **Implicit only.** The `interactions` API supports implicit caching; explicit caching requires the older `generateContent` API. |
| How to get a hit | Mark the block | **Put the stable content first and keep it byte-identical.** There is no marker to set. |
| Minimum prefix | Model-dependent, 512–4,096 tokens | **4,096 tokens** for Gemini 3.x Flash and 3.1 Pro; 2,048 for Gemini 2.5. |
| How to verify | `usage.cache_read_input_tokens` | `usage.total_cached_tokens` |
| Endpoint constraint | None | **The Vertex global endpoint does not support context caching.** Caching requires a regional endpoint — which we are using anyway (§5.3). |

Two consequences follow. First, **§3.2's deterministic ordering requirement is load-bearing**, not a nicety. Second, a small entity's chart of accounts may fall below 4,096 tokens, in which case nothing is cached and **no error is raised** — the cost is simply higher than modelled. Verify with `usage.total_cached_tokens` during the spike; if it is zero across repeated requests for the same entity, the prefix is either too short or not byte-stable.

### 7.4 What the user sees

| State | When | On screen |
|---|---|---|
| Reading | Receipt attached, model working | A quiet indicator on the upload area. All fields stay editable. |
| Suggested | Value returned with enough confidence | Field filled and marked as a suggestion, with a one-tap clear. |
| Confirmed | User edits, tabs past, or presses Add | Becomes an ordinary value; the marking disappears. |
| Blank | Low confidence or unreadable | Field left empty. The user fills it as they do today. |
| Unavailable | Model slow, rate limited, or down | No indicator, no error message. The card is exactly as it is now. |

> **Never overwrite the user.** If a field already holds a value when the reply arrives — because the user typed faster than the model — that field is left alone regardless of confidence.

**Accessibility.** Suggestion marking must not rely on colour alone: pair it with a text label or icon, and announce the arrival of suggestions to screen readers via a polite live region.

---

## 8. Security, Privacy and Compliance

Receipts are customer financial documents. This section is a build requirement, not an appendix.

### 8.1 Authentication and secret management

Vertex AI does not authenticate with a simple API key the way the Anthropic API did. It uses Google Cloud IAM, which is more work to set up and materially better once it is. This is one of the five reasons for the route in §5.3.

**Preferred — no long-lived credential at all.** Minty runs on AWS. Google Cloud **Workload Identity Federation** lets an AWS IAM role impersonate a Google Cloud service account directly, with no service-account key file anywhere in our infrastructure. Short-lived tokens are minted per request and expire on their own.

- [ ] Dedicated Google Cloud **project** for this feature, so its spend, quota and audit trail are isolated.
- [ ] Dedicated **service account** granted the minimum Vertex AI role needed to call a model — `roles/aiplatform.user`, and nothing broader. It must have no access to storage, BigQuery, or any other project resource.
- [ ] Federation configured from the application's AWS role to that service account. **No service-account JSON key is created.**
- [ ] Project id and region supplied as ordinary configuration (`GOOGLE_CLOUD_PROJECT`, `EXPENSE_AI_LOCATION`).

**Fallback, if federation cannot be arranged in time.** A service-account JSON key, held in the existing secrets mechanism, never committed, never logged, never sent to the browser, and **rotated quarterly and immediately on suspected exposure**. Record this as technical debt with a date against it — a long-lived key file is a strictly worse position than the federation above, and the only reason to accept it is schedule.

**If anyone spikes on the direct Gemini API** (§5.3), its API key is a long-lived shared secret with none of the above properties. It must be scoped to a throwaway project, kept out of the repository, and deleted when the spike ends.

The browser never calls Google directly, under any of these arrangements. All calls originate server-side.

### 8.2 Access control
- [ ] `@login_required` on the endpoint.
- [ ] Entity permission check (`REPORT_EDIT_OWN`) before any context is assembled.
- [ ] `entity_id` resolved and re-validated server-side; a client-supplied value is never trusted.
- [ ] Context assembly scoped to the resolved entity — accounts and contacts of one entity must never appear in another entity's request.
- [ ] Application-wide CSRF protection applies; no exemption is added.
- [ ] Per-user and per-entity rate limits on the endpoint (§8.6).

### 8.3 Treating model output as untrusted input
A receipt is an untrusted document, and text printed on it reaches the model. Assume an image may contain adversarial instructions.

- The model's reply is **data, never an instruction**. Nothing in it is executed, evaluated, or used to build a query.
- `contact_id` and `account_id` are accepted **only** if they appear in the lists sent in that same request. This check is what enforces Concept 1's constrained selection (§6.1) — it is not a belt-and-braces extra.
- `amount` must parse as a positive decimal within a sane bound; `currency` must be a known ISO code; `description` is length-capped and HTML-escaped on render.
- Any value that fails validation is dropped and the field is left blank. We never "repair" a suggestion.
- The system instruction states plainly that text inside the document is content to be read, not direction to be followed.

### 8.4 Data minimisation and transmission
- Sent to the provider: **the single receipt file**, the entity's account list, contact list, company name, country and currency.
- **Not sent:** user names, email addresses, historical transactions, other entities' data, report totals, banking details, or any credential.
- All transport is TLS. Files are held in memory for the request and are not written to a temporary location on disk.
- Receipt bytes are **never** written to application logs, error trackers, or the audit table.

### 8.5 Residency and retention

**Residency.** The corrected picture in §1.5 makes this section short, which is the point.

> **Our servers are in Singapore. Our customers' receipts already live in Singapore. Calling Vertex AI's `asia-southeast1` endpoint keeps model inference in Singapore too. This feature moves no customer data across a border it does not already cross.**

- Google publishes an **ML-processing residency commitment** for Generative AI on Vertex AI: for a regional endpoint, ML processing occurs in that region. Data stored at rest in the customer-selected location stays there.
- **Do not use the Vertex global endpoint.** It gives up the residency commitment *and* context caching (§7.3), and buys availability we do not need — every failure already degrades to today's behaviour (§9).
- Note the contrast that decided §5.3: the direct Gemini API, **even on the paid tier**, reserves the right to store or cache data "in any country in which Google or its agents maintain facilities". There is no regional endpoint to pin.
- Record the region decision and the reasoning in the delivery checklist, so a future engineer changing `EXPENSE_AI_LOCATION` knows it is a compliance setting and not a performance knob.

**Provider retention.**

| Route | Position | Acceptable for customer receipts? |
|---|---|---|
| **Vertex AI** (chosen) | Customer content is not used to train Google's foundation models. Confirm in writing against the current Google Cloud terms and the Vertex AI data-governance documentation, and record the confirmation here before pilot. | **Yes** |
| Gemini API — paid tier | Not used to improve Google products. Prompts and responses are logged for a limited period solely to detect and prevent abuse. No residency control. | Spike only, non-customer receipts |
| Gemini API — free tier | Submitted content is used to "provide, improve, and develop Google products", and **human reviewers may read, annotate, and process API input and output**. | **No. Never.** |

The free-tier row is the one to make sure everyone has read. Both tiers use the same SDK and the same code, so the difference is invisible at the call site and entirely visible in the terms.

**Our retention.** The audit table (§10.2) holds metadata and suggested values only, for 90 days, then is purged by a scheduled job. Receipt content is not duplicated anywhere new by this feature.

### 8.6 Abuse and cost protection
- Rate limit: **N requests per user per minute** and **M per entity per hour**, values set from pilot data. The application does not currently ship a rate limiter, so one must be introduced with this feature.
- Vertex AI enforces its own per-project quotas, and a regional endpoint's quota is smaller than the global one. Establish the project's quota during Stage 2 and set our own limits comfortably beneath it, so we shed load on our terms rather than collecting `429`s on Google's.
- One extraction per attached file. A re-extract requires a deliberate user action.
- A daily spend ceiling with alerting (§14.3); breaching it disables the feature rather than degrading the page.

### 8.7 Compliance checklist before pilot
- [ ] Terms of service and privacy policy reviewed for third-party document processing.
- [ ] Customer-facing disclosure agreed with the business — what is sent, to whom, in which region, and why. The Singapore answer (§8.5) should make this a short conversation.
- [ ] Google Cloud data-retention and no-training position documented in §8.5.
- [ ] Region decision recorded, with `EXPENSE_AI_LOCATION` flagged in configuration as a compliance setting.
- [ ] Security review of the endpoint completed and findings closed.
- [ ] Data flow added to the processing register, naming Google Cloud and `asia-southeast1`.

---

## 9. Error Handling and Resilience

**Governing principle: every failure degrades to today's behaviour.** There is no failure mode in which the user cannot enter an expense by hand.

### 9.1 Failure matrix

The `google-genai` SDK raises its **own** exception types — `ClientError` for 4xx and `ServerError` for 5xx, both subclasses of `APIError`. It does **not** raise `google.api_core` exceptions, which is the mistake most examples in circulation make. Catch the SDK's types.

| Failure | Detection | Behaviour | User sees |
|---|---|---|---|
| Rate limited / quota exhausted (`429 RESOURCE_EXHAUSTED`) | `ClientError`, status 429 | Retry once after the advised delay, then give up | Nothing — card as today |
| Provider error (`5xx`) | `ServerError` | Retry once with jitter, then give up | Nothing |
| Service unavailable (`503 UNAVAILABLE`) | `ServerError` | Retry once, then give up | Nothing |
| Network / connection error | Transport exception | Retry once, then give up | Nothing |
| Timeout (>25 s) | Server-side deadline | Abandon; do not retry | Nothing |
| Bad request (`400 INVALID_ARGUMENT`) | `ClientError`, status 400 | **No retry.** Log with request id; alert if sustained — usually a malformed schema or an oversized document | Nothing |
| Permission denied (`403`) | `ClientError`, status 403 | No retry. Page the on-call engineer — IAM misconfiguration or an expired federated credential | Nothing |
| Model not found in this region (`404`) | `ClientError`, status 404 | No retry. **Page on-call** — the configured model is not served where we are calling | Nothing |
| Blocked by safety filters | `finish_reason` / `prompt_feedback.block_reason` on the response | Treat as "no suggestion". Log the category. **Do not retry** | Nothing |
| Reply truncated | `finish_reason == MAX_TOKENS` | Discard the reply; the JSON is incomplete. Log — repeated occurrences mean `max_output_tokens` is too low | Nothing |
| Reply fails schema validation | Pydantic `ValidationError` | Discard the whole reply. Log a redacted sample | Nothing |
| Field fails Minty validation | Id / range check (§8.3) | Drop **that field only**; keep the rest | That field stays blank |
| Unsupported or corrupt file | Content sniff before the call | Return early; no model call, no charge | Nothing |
| Feature flag off / kill switch | Config check before the call | Endpoint returns "disabled"; no model call | Nothing |

### 9.2 Retry discipline
- **At most one retry**, and only for `429`, `5xx`, `503` and connection errors. The SDK retries transient errors automatically **up to four times with exponential backoff by default** — far too many for a user waiting on a form. **Override it explicitly via `HttpRetryOptions` to a single attempt**, and do not rely on the default.
- Never retry a `4xx` other than `429` — the request is wrong and will stay wrong.
- Never retry a safety block. It is deterministic for the same input.
- Total wall-clock for the endpoint, retries included, must stay inside the 25 s server deadline.
- Catch **specific exception classes, most-specific-first**, and branch on `status` within `ClientError`. A single broad `except APIError` loses the retryable / non-retryable distinction and is a review-blocking defect.

### 9.3 Client-side behaviour
- The request is fired on attach and its result is applied only if the card is still open and the file unchanged.
- Any in-flight request is cancelled when the file is removed or replaced.
- If the user presses **Add** while a request is in flight, Add proceeds immediately. The reply is discarded.
- No error toast, no red banner, no spinner that can hang. Unavailable means invisible.

---

## 10. Data, Backup and Recovery

### 10.1 What this feature stores
The feature adds **one table** and changes no existing table. Suggestions are advisory; once the user presses Add, the expense record is identical in shape to one typed by hand.

### 10.2 Audit table — `ai_expense_suggestion`

| Column group | Contents |
|---|---|
| Identity | `id`, `entity_id`, `user_id`, `report_id` (nullable), `created_at` |
| Request | `model_id`, `provider_request_id`, `location`, `latency_ms`, `thinking_level` |
| Usage | `input_tokens`, `output_tokens`, `cached_tokens`, `estimated_cost` |
| Result | `suggested_fields` (JSON, post-validation), `confidence_by_field` (JSON), `status`, `error_code` |
| Outcome | `accepted_fields` (JSON, written on Add — the input to §11.4 measurement) |

`location` is recorded because it is a compliance-relevant setting (§8.5) and because it lets us evidence, per request, where inference happened.

**Never stored here:** receipt bytes, raw model text, prompts, or any credential.

### 10.3 Backup and restore
- The table lives in the existing application database and is therefore covered by the existing RDS automated backups and point-in-time recovery. **No new backup mechanism is introduced.**
- Confirm before pilot that the backup and PITR window covers the new table, and record the confirmation in the delivery checklist.
- **Restore test:** during Stage 2 of delivery, restore a snapshot to a scratch instance and confirm the table restores cleanly with its data. A backup that has never been restored is an assumption, not a control.
- Receipt files themselves are unaffected — this feature adds no new file storage and no new copy of customer documents.
- The 90-day purge (§8.5) runs as a scheduled job with a dry-run mode; its first production run is reviewed before the retention period elapses.

### 10.4 Data loss exposure
Losing the entire `ai_expense_suggestion` table would cost us **measurement data only**. No expense, report, receipt, or Xero record depends on it. This is deliberate, and it is what makes the rollback in §11.3 cheap.

---

## 11. Rollout, Feature Flags and Rollback

### 11.1 Controls

| Control | Scope | Purpose |
|---|---|---|
| `EXPENSE_AI_ENABLED` | Global environment variable | **Kill switch.** Off disables the endpoint and the client call outright. |
| Per-entity flag | Entity setting | Pilot enablement, one entity at a time. |
| `EXPENSE_AI_MODEL` | Configuration | Model id, changeable without a deployment. |
| `EXPENSE_AI_LOCATION` | Configuration | Vertex region. **A compliance setting, not a performance knob** (§8.5) — changing it changes where customer documents are processed. |
| Confidence cut-offs | Configuration | Tunable from pilot data without a deployment. |
| Daily spend ceiling | Configuration | Automatic disable on breach (§8.6). |

Default for every flag is **off**. The feature ships dark.

### 11.2 Rollout sequence
1. Enable for one internal entity. Run a full week of ordinary petty-cash entry.
2. Review the accept-rate report (§11.4) and the error log with operations.
3. Enable for one pilot customer entity, with their agreement and the §8.7 disclosure in place.
4. Widen only on evidence, one cohort at a time.

### 11.3 Rollback plan
Rollback is ordered from cheapest to most invasive. In practice step 1 is always sufficient.

| Level | Action | Time to effect | Data impact |
|---|---|---|---|
| 1 — Disable | Set `EXPENSE_AI_ENABLED=false` | Immediate, no deployment | None |
| 2 — Un-enrol | Clear the per-entity flag | Immediate | None |
| 3 — Revert code | Deploy the previous release | One deployment cycle | None |
| 4 — Drop table | Run the migration downgrade | One migration | Audit history lost only |

**Rules**
- Step 4 is performed only after the feature has been off for a full retention period and the business confirms the audit history is no longer needed.
- The migration must ship with a tested `downgrade()`. Test it on a copy of the database, not in production.
- Rollback requires **no data repair**, because no existing record was ever written by the model.
- Rollback authority: any on-call engineer may execute steps 1 and 2 without approval. Steps 3 and 4 follow the normal change process.

### 11.4 Success measurement
- **Primary metric:** accept rate per field — the share of suggestions the user submitted unchanged.
- **Secondary:** extraction latency (p50, p95), error rate by class, cost per receipt, share of receipts producing at least one usable field.
- **Decision rule:** a field whose accept rate does not clear the threshold agreed at the Stage 1 gate is switched off. Fields are kept individually, not as a bundle.

---

## 12. What We Are Not Building

Taken directly from the Stage 1 strategy. Listed here because two of these appeared in earlier Minty drafts and are now removed.

| Excluded | Consequence for this build |
|---|---|
| Complex entity learning engine | No learning of any kind in Stage 1. |
| Historical behaviour engine | The account-code ranking from past expenses in the earlier Minty proposal is **dropped**. The model's own business knowledge replaces it. |
| Multi-provider AI routing | One provider, one model, one call. No fallback chain or abstraction layer. **§5.5 is a procurement list, not a runtime design.** |
| AI orchestration platform | A single request. No pipeline, no queue, no agent loop. |
| Custom accounting intelligence system | Minty supplies context and validates the result. It does not reason about accounting. |

Client-specific vendor mapping — "PARKnSHOP is pantry for Client A, inventory for Client B" — is exactly the proprietary intelligence the strategy places in a **future** stage. It is not required for Stage 1 success and must not be smuggled into this build.

---

## 13. Decisions Required

The strategy lists five things for the AI to extract. Two have nowhere to go on the current form. Flagging rather than assuming.

### 13.1 Date
The strategy has the AI extract the date, and the worked example includes 28 Aug 2026. The Add New Expense card has **no date field** — an expense takes its date from the report being worked on, shown in the page header.

Three options, in order of preference:

1. **Extract and check** *(recommended default)* — the model returns the date and Minty uses it only to warn when the receipt is from a noticeably different day than the report. Nothing new appears on the form.
2. **Extract and hold** — the model returns it, we store it in the audit table, nothing uses it yet.
3. **Skip** — do not ask for it in Stage 1.

### 13.2 Invoice number
The same situation: the strategy lists it, the form has no field for it. It could be appended to Description or held for a later stage. Adding a field to the form is a larger change than this feature should carry on its own.

> **Neither of these blocks the work.** Both can be settled after the spike, when we know how reliably the model reads them off real receipts. Extract-and-check is the safe default for the date in the meantime.

---

## 14. Cost Model and Controls

### 14.1 Rough per-receipt estimate

To be replaced with a measured figure at the end of the spike. Assumes one receipt plus the entity context in, a short JSON reply out, and **no cache hit** — the pessimistic case.

| Component | Tokens | Gemini 3.1 Pro | Gemini 3.8 Flash *(promo)* | Gemini 3.5 Flash *(budget at this)* | Gemini 2.5 Flash |
|---|---|---|---|---|---|
| Input — receipt + context | ~5,000 | ~$0.010 | ~$0.004 | ~$0.008 | ~$0.002 |
| Output — JSON reply | ~300 | ~$0.004 | ~$0.001 | ~$0.003 | ~$0.001 |
| **Per receipt** | | **~$0.014** | **~$0.005** | **~$0.011** | **~$0.003** |

For comparison, the v2.0 estimate on Claude Opus 5 was ~$0.03 per receipt. The provider change is cost-neutral at worst and roughly a halving at best — but cost was never the reason for it, and should not be presented as the justification.

**Budget at the Gemini 3.5 Flash column**, per §5.4: it is the honest post-promotional Flash rate.

### 14.2 What moves the number
- **Implicit prefix caching** reduces the input side within a data-entry session — but only under the §7.3 conditions: a regional endpoint, a stable prefix placed first, and at least 4,096 tokens of it. For a small entity this may never trigger.
- **Document size.** Running `downsize_bytes` before the call is the single largest lever on input tokens. A PDF costs a flat 258 tokens per page, so **the multi-page question in §17 is a cost question as well as a correctness one.**
- **`thinking_level`.** `low` versus `high` is a real difference in output tokens on a bounded task.
- Measure with token counting during the spike rather than estimating from the code.

### 14.3 Controls
- [ ] Per-request token usage recorded on every call (§10.2), including `total_cached_tokens`.
- [ ] Daily and monthly spend dashboards, reviewed weekly during pilot. Google Cloud billing budgets and alerts configured on the dedicated project (§8.1).
- [ ] Alert at 80 % of the agreed daily ceiling; automatic disable at 100 %.
- [ ] Pricing re-verified **against the Vertex AI price list** at each delivery stage gate.
- [ ] A calendar reminder set for **December 2026** to re-baseline the cost model when the Flash promotional pricing ends.
- [ ] A cost-per-receipt ceiling agreed with the business **before** Stage 3 (§15).

---

## 15. Delivery Plan

### Stage 0 — Access and region *(half a day)*
**Work:** stand up the Google Cloud path and confirm the region, before anyone writes a prompt.
**Outcome:** a working credential and a confirmed model id.

- [ ] Google Cloud project created and billing enabled.
- [ ] Vertex AI API enabled; service account created with `roles/aiplatform.user` only.
- [ ] Workload Identity Federation from AWS configured, or the §8.1 fallback accepted and logged as debt.
- [ ] Confirm which Gemini models `asia-southeast1` serves today, and pin the spike model from that list.
- [ ] One successful round-trip call **from the application's own network path** — not from a laptop.
- [ ] Region decision recorded per §8.7.

> **Kept from the v3.0 draft, though smaller than it looked there.** That draft made Stage 0 existential because it believed access was blocked; on the corrected facts it is routine setup. It stays because the general lesson in §1.5 stands: verify from where the code runs, and find out in half a day rather than in Stage 2.

### Stage 1 — Spike *(mandatory)*
**Work:** a throwaway script, a batch of real Hong Kong receipts, and a per-field accuracy report. Run on Gemini 3.1 Pro via Vertex. No page changes.
**Outcome:** a go / no-go, the real cost per receipt, and the confidence cut-offs.

- [ ] Assemble ≥ 50 real receipts, deliberately sampling Traditional Chinese and mixed-script examples.
- [ ] Include multi-page PDFs and poor-quality phone photos in the sample.
- [ ] Run extraction against real entity context (accounts, contacts, entity facts).
- [ ] Report accuracy **per field** and **per confidence band**.
- [ ] Record measured tokens and cost per receipt, and `total_cached_tokens` across repeated same-entity calls.
- [ ] Re-run on the intended production Flash model and compare — the step-down decision needs both numbers.
- [ ] *Optional, cheap, and worth it:* run the same receipts through Qwen3-VL as a comparison arm on Chinese-language accuracy (§5.5, item 4). Measurement only; adoption is a separate business decision.
- [ ] Propose confidence cut-offs from the data.
- [ ] Present findings and obtain a documented go / no-go.

> **This stage is not optional.** Whether the model reads real Hong Kong receipts accurately is the single assumption the whole plan rests on, and it can be tested in isolation for very little. Building the page first would mean finding out last.

### Stage 2 — Server
**Work:** the extract endpoint — Brain 2 context assembly, the model call, schema enforcement, and id validation.
**Outcome:** extraction working and testable; nothing visible to users.

- [ ] `expense_ai.py` service module with the single model call.
- [ ] Endpoint with auth, entity authorisation, CSRF, size cap and content sniffing (§7.2, §8.2).
- [ ] Server-side validation of every returned field (§8.3).
- [ ] Full error matrix implemented with the SDK's typed exceptions (§9.1), and SDK auto-retry overridden to one attempt (§9.2).
- [ ] Rate limiter introduced and configured beneath the project's Vertex quota (§8.6).
- [ ] `ai_expense_suggestion` migration with a tested `downgrade()`.
- [ ] Backup coverage confirmed and a restore test performed (§10.3).
- [ ] Metrics, structured logging and alerts wired up (§16).
- [ ] Unit tests: schema validation, id rejection, out-of-range amount, safety block, truncation, timeout, malformed JSON, 404-model-not-in-region.
- [ ] Integration test against the live model behind a flag, excluded from CI by default.
- [ ] Security review completed.

### Stage 3 — Page
**Work:** suggestion states on the Add New Expense card, wired into the upload that already exists.
**Outcome:** live behind a flag for one pilot entity.

- [ ] Five UI states implemented (§7.4).
- [ ] Never-overwrite rule enforced and tested.
- [ ] In-flight cancellation on file change or removal.
- [ ] Add is never blocked, never delayed.
- [ ] Accessibility check: marking is not colour-only; suggestions are announced.
- [ ] Feature verified as fully invisible with the flag off.

### Stage 4 — Measure
**Work:** accept rate per field.
**Outcome:** evidence for which fields keep the feature.

- [ ] Accept-rate report per field, per entity.
- [ ] Latency, error-rate and cost review.
- [ ] Confidence cut-offs re-tuned from live data.
- [ ] Keep / drop decision recorded per field.

---

## 16. Observability

- **Metrics:** request count, success rate, error rate by class, latency p50/p95/p99, tokens in/out, cached tokens, estimated cost, accept rate per field.
- **Logging:** structured logs via the existing `loguru` setup, carrying entity id, user id, provider request id, region, latency, status and error code. **Never** the receipt, the prompt, or the raw reply.
- **Front-end monitoring:** the page already reports to Datadog; extraction failures are recorded as non-blocking events, not user-visible errors.
- **Alerts:** IAM/permission failure (page immediately), model-not-found in region (page immediately), sustained `400` (indicates a broken request or schema shape), error rate above threshold over 15 minutes, spend at 80 % of the daily ceiling, p95 latency above 15 s.
- **Weekly pilot review:** accept rate, error mix and cost, reviewed jointly by engineering and operations.

---

## 17. Open Questions and Risks

Two items that blocked pilot in the v3.0 draft are resolved by the correction in §1.5 and no longer appear: whether we could reach the provider at all, and which jurisdiction would process the data. Both are answered by Singapore.

| # | Question / risk | Impact | Owner | Needed by |
|---|---|---|---|---|
| 1 | **Google Cloud retention posture.** Confirm and document in writing that customer content is not used to train foundation models and is not retained beyond abuse detection. | Blocks pilot | Engineering | Stage 2 |
| 2 | **Preview-model dependency.** If only `gemini-3.1-pro-preview` clears the accuracy bar, we have no production-safe model (§5.3). | Could delay Stage 3 pending a GA release, or re-open §5.5 | Engineering | After spike |
| 3 | **Cost ceiling.** What is acceptable per receipt at expected daily volume — and re-baselined for the January 2027 end of promotional Flash pricing? | Blocks Stage 3 | Business | Stage 3 |
| 4 | **Date and invoice number** — the two decisions in §13. | Non-blocking | Business | After spike |
| 5 | **Confidence cut-offs.** Set from spike data; self-reported confidence is not a calibrated probability (§6.2). | Blocks Stage 3 | Engineering | After spike |
| 6 | **Traditional Chinese receipts.** How common in the real mix, and does Gemini handle them well enough? The Qwen comparison arm (§15, Stage 1) would quantify what we are giving up. | Affects go / no-go | Engineering | Spike |
| 7 | **Multi-page PDFs.** Which page do we read? At 258 tokens per page this is a cost question as well as a correctness one. | Non-blocking; default is page 1 | Engineering | Stage 2 |
| 8 | **Cache hit rate may be low** — implicit-only caching with a 4,096-token minimum prefix (§7.3). Entities with small charts of accounts may never get a hit. | Cost only | Engineering | Stage 4 |
| 9 | **Customer disclosure wording.** What we tell clients about receipts being processed by Google in Singapore. Expected to be straightforward given §8.5, but it still needs agreeing. | Blocks pilot | Business | Stage 3 |
| 10 | **Google Cloud contracting.** Ordinary procurement — billing account, entity, and the standard terms. Downgraded from a risk in v3.0; flagged only so it is not forgotten. | Routine | Business | Stage 2 |

---

## Appendix A — Configuration Reference

| Key | Type | Default | Purpose |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | String (env) | — | Dedicated Google Cloud project id for this feature. |
| `EXPENSE_AI_LOCATION` | String (env) | `asia-southeast1` | Vertex AI **regional** endpoint. Never `global` — see §8.5. **Compliance setting:** changing it changes where customer documents are processed. |
| *(credential)* | Workload Identity Federation | — | No long-lived secret in the preferred design (§8.1). If the fallback is used, a service-account key in the existing secrets mechanism, rotated quarterly. |
| `EXPENSE_AI_ENABLED` | Boolean (env) | `false` | Global kill switch. |
| `EXPENSE_AI_MODEL` | String | Set after spike | Model id, e.g. `gemini-3.8-flash`. |
| `EXPENSE_AI_THINKING_LEVEL` | String | `low` | Gemini 3 reasoning effort: `low` / `medium` / `high`. |
| `EXPENSE_AI_MAX_OUTPUT_TOKENS` | Integer | `1024` | Cap on the JSON reply. |
| `EXPENSE_AI_TIMEOUT_S` | Integer | `25` | Server-side deadline. |
| `EXPENSE_AI_MAX_FILE_MB` | Integer | `10` | Per-request size cap on the extract route. |
| `EXPENSE_AI_CONF_HIGH` / `_MEDIUM` | Float | Unset until spike | Confidence band cut-offs. |
| `EXPENSE_AI_DAILY_CEILING` | Decimal | Set at pilot | Daily spend ceiling. |
| `EXPENSE_AI_RETENTION_DAYS` | Integer | `90` | Audit-table retention. |

**Removed since v2.0:** `ANTHROPIC_API_KEY`, `EXPENSE_AI_EFFORT`. Replaced by the Google Cloud credentials above and `EXPENSE_AI_THINKING_LEVEL` respectively. **No `GOOGLE_API_KEY`** — the Vertex route does not use one, and its presence in configuration would indicate someone has taken the direct-API path with customer data (§5.3, §8.5).

**Dependency:** `google-genai` (`pip install -U google-genai`). Do **not** add `google-generativeai` or depend on `vertexai.generative_models` — both are deprecated (§7.3).

## Appendix B — Definition of Done

- [ ] Every checklist in §15 complete for the stage being signed off, **including Stage 0**.
- [ ] Feature verified invisible and inert with `EXPENSE_AI_ENABLED=false`.
- [ ] Rollback steps 1 and 2 rehearsed in a non-production environment.
- [ ] Migration `downgrade()` tested.
- [ ] Restore test performed and recorded.
- [ ] Security review closed.
- [ ] Compliance checklist (§8.7) complete.
- [ ] Every model call verified as going to the Vertex regional endpoint — no API-key path, no global endpoint.
- [ ] Cost per receipt measured, not estimated, on the production model and region.
- [ ] Accept-rate reporting live before general enablement.

---

## Appendix C — Sources

Verified on 3 September 2026. Availability, pricing and API shapes all move; **re-verify at each stage gate** rather than trusting this appendix later.

| Claim | Source |
|---|---|
| Singapore is a supported Gemini API region; restriction applied on the calling instance's region, not the user's | `ai.google.dev/gemini-api/docs/available-regions` |
| Gemini model ids and list pricing; Flash promotional rate to 31 Dec 2026 | `ai.google.dev/gemini-api/docs/pricing` |
| Free tier vs paid tier data use — product improvement and human review on the free tier; caching "in any country" on the paid tier | `ai.google.dev/gemini-api/terms` |
| `google-genai` SDK, `interactions.create`, structured output via `response_format` | `ai.google.dev/gemini-api/docs/quickstart`, `.../structured-output` |
| PDF handling: 50 MB / 1,000 pages, 258 tokens per page, 3072 × 3072 rescale | `ai.google.dev/gemini-api/docs/document-processing` |
| Implicit caching only on the interactions API; 4,096-token minimum; `usage.total_cached_tokens` | `ai.google.dev/gemini-api/docs/caching` |
| `thinking_level` values | `ai.google.dev/gemini-api/docs/thinking` |
| SDK error types, default retry behaviour, retryable status codes | `googleapis/python-genai` |
| Vertex AI regional vs global endpoints; global endpoint supports neither residency nor context caching | Google Cloud Vertex AI locations documentation |
| ML-processing residency commitment for Generative AI on Vertex AI; Singapore data-residency expansion | Google Cloud Vertex AI data-residency documentation |
| Breadth of the `asia-southeast1` model catalogue, including Claude with in-region ML processing | Google Cloud Vertex AI model availability by region |
| Qwen3-VL pricing on the Alibaba Cloud Model Studio Singapore endpoint | Alibaba Cloud Model Studio pricing |

---

*Minty · Petty Cash · Stage 1 on the Expense Page · v3.1 · Gemini on Google Cloud Vertex AI, `asia-southeast1` · Draft for engineering and operations review*
